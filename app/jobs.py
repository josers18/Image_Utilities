"""One batch of pictures at a time, processed on a single background thread."""

from __future__ import annotations

import asyncio
import gc
import json
import logging
import shutil
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import torch
from PIL import UnidentifiedImageError
from fastapi import HTTPException

from app.config import IMAGE_SUFFIXES, INBOX, MAX_BATCH, PREVIEWS
from app.engine import (
    Cancelled,
    Engine,
    JobSpec,
    OutputTooLarge,
    Reporter,
    load_image,
    make_source_preview,
    make_source_thumb,
    remember_views,
)
from app.finish import Options, TooLarge, disambiguate, file_suffix, place_file, renamed_stem
from app.naming import format_bytes, list_images, output_name
from app.settings import Settings

log = logging.getLogger("image_utilities")


@dataclass
class Item:
    id: str
    source: Path
    name: str
    origin: str
    location: str
    status: str = "queued"
    phase: str = "Waiting"
    progress: float = 0
    message: str = ""
    note: str = ""
    output: Path | None = None
    source_width: int = 0
    source_height: int = 0
    width: int = 0
    height: int = 0
    nbytes: int = 0
    seconds: float = 0

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "location": self.location,
            "origin": self.origin,
            "status": self.status,
            "phase": self.phase,
            "progress": self.progress,
            "message": self.message,
            "note": self.note,
            "output": str(self.output) if self.output else "",
            "source_width": self.source_width,
            "source_height": self.source_height,
            "width": self.width,
            "height": self.height,
            "bytes": self.nbytes,
            "bytes_label": format_bytes(self.nbytes) if self.nbytes else "",
            "seconds": round(self.seconds, 1) if self.seconds else 0,
        }


@dataclass
class Batch:
    id: str
    origin: str
    items: list[Item] = field(default_factory=list)
    status: str = "editing"
    task: str = "both"
    scale: int = 4
    look: str = "photo"
    save: str = "beside"
    options: Options = field(default_factory=Options)
    notice: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "origin": self.origin,
            "status": self.status,
            "task": self.task,
            "scale": self.scale,
            "look": self.look,
            "save": self.save,
            "notice": self.notice,
            "items": [item.to_dict() for item in self.items],
        }


class Store:
    def __init__(self) -> None:
        self.settings = Settings()
        self.engine = Engine()
        self.lock = threading.Lock()
        self.batch: Batch | None = None
        self.cancel = threading.Event()
        self.thread: threading.Thread | None = None
        self._undo_stack: list[list[Item]] = []
        self._subscribers: set[tuple[asyncio.Queue, asyncio.AbstractEventLoop]] = set()
        self._last_notify = 0.0

    def subscribe(self, queue: asyncio.Queue, loop: asyncio.AbstractEventLoop) -> None:
        with self.lock:
            self._subscribers.add((queue, loop))

    def unsubscribe(self, queue: asyncio.Queue, loop: asyncio.AbstractEventLoop) -> None:
        with self.lock:
            self._subscribers.discard((queue, loop))

    def notify(self, notice: str = "") -> None:
        snap = self.snapshot(notice=notice)
        data = json.dumps(snap)
        with self.lock:
            subs = list(self._subscribers)
        for queue, loop in subs:
            try:
                loop.call_soon_threadsafe(queue.put_nowait, data)
            except Exception:
                pass

    def snapshot(self, notice: str = "", cancelled: bool = False) -> dict:
        with self.lock:
            batch = self.batch.to_dict() if self.batch else None
            if batch is not None and notice:
                batch["notice"] = notice
            output_dir = str(self.settings.output_dir)
            settings = dict(self.settings.last)
        return {
            "device": "GPU" if self.engine.device.type == "mps" else "CPU",
            "output_dir": output_dir,
            "settings": settings,
            "cancelled": cancelled,
            "notice": notice,
            "batch": batch,
        }

    def add_paths(self, paths: list[Path], subfolders: bool, replace: bool = False) -> dict:
        files: list[Path] = []
        skipped = 0
        truncated = False
        for path in paths:
            if path.is_dir():
                found, cut = list_images(path, subfolders)
                files.extend(found)
                truncated = truncated or cut
            elif path.is_file() and not path.name.startswith(".") and path.suffix.lower() in IMAGE_SUFFIXES:
                files.append(path)
            elif path.exists():
                skipped += 1
        if not files and not truncated:
            if skipped:
                raise HTTPException(status_code=400, detail="None of those files look like images.")
            raise HTTPException(status_code=400, detail="That folder doesn't have any images.")
        self._add(files, origin="path", force_new=replace)
        notice = _add_notice(skipped, truncated)
        with self.lock:
            if self.batch is not None and notice:
                previous = self.batch.notice
                self.batch.notice = f"{previous} {notice}".strip() if previous else notice
                notice = self.batch.notice
            elif self.batch is not None:
                notice = self.batch.notice
        return self.snapshot(notice=notice)

    def upload_folder(self) -> str:
        """Folder id for files dropped in the browser, stable while a drop batch is open."""
        with self.lock:
            running = self.thread is not None and self.thread.is_alive()
            if running:
                raise HTTPException(status_code=409, detail="Wait for the current batch to finish.")
            if self.batch and self.batch.status == "editing" and self.batch.origin == "upload":
                return self.batch.id
            return uuid.uuid4().hex[:12]

    def add_uploads(self, saved: list[Path], batch_id: str) -> dict:
        images = []
        skipped = 0
        for path in saved:
            if path.suffix.lower() in IMAGE_SUFFIXES:
                images.append(path)
            else:
                skipped += 1
                path.unlink(missing_ok=True)
        if not images:
            raise HTTPException(status_code=400, detail="None of those files look like images.")
        self._add(images, origin="upload", batch_id=batch_id)
        notice = _add_notice(skipped, False)
        with self.lock:
            if self.batch is not None and notice:
                self.batch.notice = f"{self.batch.notice} {notice}".strip()
        return self.snapshot(notice=notice)

    def remove_item(self, item_id: str) -> dict:
        with self.lock:
            self._require_editable()
            assert self.batch is not None
            removed = next((item for item in self.batch.items if item.id == item_id), None)
            if removed is None:
                raise HTTPException(status_code=404, detail="That picture isn't in the list.")
            self.batch.items = [item for item in self.batch.items if item.id != item_id]
            upload_path = removed.source if removed.origin == "upload" else None
            if not self.batch.items:
                batch_id = self.batch.id
                self.batch = None
            else:
                batch_id = None
        if upload_path is not None and batch_id is None:
            upload_path.unlink(missing_ok=True)
        if batch_id:
            _discard_files(batch_id)
        self.notify()
        return self.snapshot()

    def remove_items(self, item_ids: list[str]) -> dict:
        with self.lock:
            if self.thread and self.thread.is_alive():
                raise HTTPException(status_code=409, detail="Wait for the current batch to finish.")
            if self.batch is None:
                return self.snapshot()
            id_set = set(item_ids)
            removed = [item for item in self.batch.items if item.id in id_set]
            if not removed:
                return self.snapshot()
            self._undo_stack = [list(removed)]
            self.batch.items = [item for item in self.batch.items if item.id not in id_set]
            if not self.batch.items:
                self.batch = None
        self.notify()
        return self.snapshot()

    def clear_batch(self) -> dict:
        with self.lock:
            if self.thread and self.thread.is_alive():
                raise HTTPException(status_code=409, detail="Wait for the current batch to finish.")
            if self.batch is None:
                return self.snapshot()
            self._undo_stack = [list(self.batch.items)]
            self.batch = None
        self.notify()
        return self.snapshot()

    def undo_remove(self) -> dict:
        with self.lock:
            if self.thread and self.thread.is_alive():
                raise HTTPException(status_code=409, detail="Wait for the current batch to finish.")
            if not self._undo_stack:
                raise HTTPException(status_code=400, detail="Nothing to restore.")
            restored = self._undo_stack.pop()
            if self.batch is None:
                self.batch = Batch(id=uuid.uuid4().hex[:12], origin="mixed", items=restored)
            else:
                existing_ids = {item.id for item in self.batch.items}
                for item in restored:
                    if item.id not in existing_ids:
                        self.batch.items.append(item)
        self.notify(f"Restored {len(restored)} items.")
        return self.snapshot()

    def batch_items(self) -> list[Item]:
        with self.lock:
            return list(self.batch.items) if self.batch else []

    def set_output_dir(self, path: Path) -> dict:
        if not path.is_dir():
            raise HTTPException(status_code=400, detail="That folder isn't available.")
        self.settings.set_output_dir(path)
        return self.snapshot()

    def start(self, options: Options) -> dict:
        requested = Options.from_dict(options.to_dict())
        with self.lock:
            if self.batch is None or not self.batch.items:
                raise HTTPException(status_code=400, detail="Add images first.")
            if self.thread and self.thread.is_alive():
                raise HTTPException(status_code=409, detail="A batch is already running.")
            options = Options.from_dict(requested.to_dict())
            if options.save == "beside" and self.batch.origin != "path":
                options.save = "folder"
                self.batch.notice = "Dropped files are saved in the output folder."
            else:
                self.batch.notice = ""
            self.settings.set_last(requested)
            self.cancel.clear()
            self.batch.status = "running"
            self.batch.task = options.task
            self.batch.scale = options.scale
            self.batch.look = options.look
            self.batch.save = options.save
            self.batch.options = options
            for item in self.batch.items:
                item.status = "queued"
                item.phase = "Waiting"
                item.progress = 0
                item.message = ""
                item.output = None
                item.nbytes = 0
                item.seconds = 0
        thread = threading.Thread(target=self._run, name="image-utilities", daemon=True)
        self.thread = thread
        thread.start()
        return self.snapshot()

    def request_cancel(self) -> dict:
        self.cancel.set()
        return self.snapshot()

    def current_batch_id(self) -> str:
        with self.lock:
            if self.batch is None:
                raise HTTPException(status_code=404, detail="No pictures are open.")
            return self.batch.id

    def item(self, item_id: str) -> Item:
        with self.lock:
            if self.batch is None:
                raise HTTPException(status_code=404, detail="No pictures are open.")
            for item in self.batch.items:
                if item.id == item_id:
                    return item
        raise HTTPException(status_code=404, detail="That picture isn't in the list.")

    def _add(self, paths: list[Path], origin: str, batch_id: str | None = None, force_new: bool = False) -> None:
        with self.lock:
            running = self.thread is not None and self.thread.is_alive()
            if running:
                raise HTTPException(status_code=409, detail="Wait for the current batch to finish.")
            replace = (
                force_new
                or self.batch is None
                or self.batch.status != "editing"
                or self.batch.origin != origin
            )
            if replace:
                old = self.batch.id if self.batch else None
                self.batch = Batch(id=batch_id or uuid.uuid4().hex[:12], origin=origin)
            else:
                old = None
                assert self.batch is not None
            existing = {item.source.resolve() for item in self.batch.items}
            added = 0
            for path in paths:
                resolved = path.resolve()
                if resolved in existing:
                    continue
                if len(self.batch.items) >= MAX_BATCH:
                    self.batch.notice = f"Only the first {MAX_BATCH} images were added."
                    break
                existing.add(resolved)
                self.batch.items.append(_make_item(path, origin))
                added += 1
            if added == 0 and paths and self.batch.items:
                self.batch.notice = "Those images are already in the list."
            if not self.batch.items:
                self.batch = None
        if old:
            _discard_files(old)

    def _require_editable(self) -> None:
        if self.thread and self.thread.is_alive():
            raise HTTPException(status_code=409, detail="Wait for the current batch to finish.")
        if self.batch is None:
            raise HTTPException(status_code=404, detail="No pictures are open.")

    def _run(self) -> None:
        with self.lock:
            assert self.batch is not None
            items = list(self.batch.items)
            options = self.batch.options
            task = options.task
            scale = options.scale
            look = options.look
            save = options.save
            batch_id = self.batch.id
            output_dir = self.settings.output_dir
        stems = disambiguate(
            [renamed_stem(Path(item.name).stem, options, index) for index, item in enumerate(items)]
        )
        try:
            for index, item in enumerate(items):
                if self.cancel.is_set():
                    self._cancel_from(items, item.id)
                    break
                self._set(item.id, status="running", phase="Starting", progress=0.01, message="")
                started = time.perf_counter()

                def report(phase: str, frac: float, item_id: str = item.id) -> None:
                    self._set(item_id, phase=phase, progress=frac)

                try:
                    dest_dir = item.source.parent if save == "beside" else output_dir
                    filename = output_name(stems[index], task, scale, file_suffix(options, item.source))
                    if task == "rename":
                        move = save == "beside" and item.origin == "path"
                        self._preview_source(item, batch_id)
                        dest = place_file(item.source, dest_dir, filename, move=move)
                        note = "Renamed the file." if move and dest != item.source else "Saved a copy."
                        if dest == item.source and move:
                            note = "The name stayed the same."
                        changes = {
                            "status": "done",
                            "phase": "Saved",
                            "progress": 1,
                            "message": "",
                            "note": note,
                            "output": dest,
                            "nbytes": dest.stat().st_size,
                            "seconds": time.perf_counter() - started,
                        }
                        if move:
                            changes["source"] = dest
                            changes["name"] = dest.name
                        self._set(item.id, **changes)
                        continue
                    spec = JobSpec(
                        source=item.source,
                        dest_dir=dest_dir,
                        dest_name=filename,
                        task=task,
                        scale=scale,
                        look=look,
                        preview_before=PREVIEWS / batch_id / f"{item.id}-before.jpg",
                        preview_after=PREVIEWS / batch_id / f"{item.id}-after.png",
                        thumb=PREVIEWS / batch_id / f"{item.id}-thumb.jpg",
                        options=options,
                    )
                    result = self.engine.process_file(spec, Reporter(report), self.cancel)
                    self._set(
                        item.id,
                        status="done",
                        phase="Saved",
                        progress=1,
                        message="",
                        note=result.note,
                        output=result.output,
                        source_width=result.source_width,
                        source_height=result.source_height,
                        width=result.width,
                        height=result.height,
                        nbytes=result.output.stat().st_size,
                        seconds=time.perf_counter() - started,
                    )
                except Cancelled:
                    self._cancel_from(items, item.id)
                    break
                except Exception as exc:
                    log.exception("Failed on %s", item.name)
                    self._set(
                        item.id,
                        status="error",
                        phase="Failed",
                        progress=0,
                        message=friendly_error(exc),
                        seconds=time.perf_counter() - started,
                    )
                finally:
                    if torch.backends.mps.is_available():
                        torch.mps.empty_cache()
                    gc.collect()
        finally:
            with self.lock:
                if self.batch is not None and self.batch.id == batch_id and self.batch.status == "running":
                    is_cancelled = self.cancel.is_set()
                    self.batch.status = "cancelled" if is_cancelled else "done"
                    if not is_cancelled:
                        done_count = sum(1 for it in self.batch.items if it.status == "done")
                        send_system_notification(
                            "Image Utilities",
                            f"Batch complete: {done_count} picture{'s' if done_count != 1 else ''} processed! 🎉",
                        )
            self.notify()

    def _cancel_from(self, items: list[Item], start_id: str) -> None:
        seen = False
        for item in items:
            if item.id == start_id:
                seen = True
            if seen and item.status in ("queued", "running"):
                self._set(item.id, status="cancelled", phase="Cancelled", progress=0, message="")

    def _preview_source(self, item: Item, batch_id: str) -> None:
        image, _meta = load_image(item.source)
        remember_views(image, PREVIEWS / batch_id, item.id)
        with self.lock:
            if self.batch is None:
                return
            for current in self.batch.items:
                if current.id == item.id:
                    current.source_width = image.width
                    current.source_height = image.height
                    current.width = image.width
                    current.height = image.height

    def _set(self, item_id: str, **changes) -> None:
        with self.lock:
            if self.batch is None:
                return
            for item in self.batch.items:
                if item.id == item_id:
                    for key, value in changes.items():
                        setattr(item, key, value)
                    break
            else:
                return
        now = time.monotonic()
        is_milestone = "status" in changes or "message" in changes or changes.get("progress") in (0, 1)
        if is_milestone or (now - self._last_notify >= 0.05):
            self._last_notify = now
            self.notify()


def source_thumb(item: Item, batch_id: str) -> Path:
    dest = PREVIEWS / batch_id / f"{item.id}-source.jpg"
    make_source_thumb(item.source, dest)
    return dest


def waiting_preview(item: Item, batch_id: str) -> Path:
    dest = PREVIEWS / batch_id / f"{item.id}-waiting.jpg"
    make_source_preview(item.source, dest)
    return dest


def result_thumb(item: Item, batch_id: str) -> Path | None:
    path = PREVIEWS / batch_id / f"{item.id}-thumb.jpg"
    return path if path.is_file() else None


def before_preview(batch_id: str, item: Item) -> Path | None:
    jpg = PREVIEWS / batch_id / f"{item.id}-before.jpg"
    png = PREVIEWS / batch_id / f"{item.id}-before.png"
    if png.is_file():
        return png
    if jpg.is_file():
        return jpg
    return None


def after_preview(batch_id: str, item: Item) -> Path | None:
    path = PREVIEWS / batch_id / f"{item.id}-after.png"
    if path.is_file():
        return path
    jpeg = path.with_suffix(".jpg")
    return jpeg if jpeg.is_file() else None


def _make_item(path: Path, origin: str) -> Item:
    location = "Dropped file" if origin == "upload" else str(path.parent)
    return Item(
        id=uuid.uuid4().hex[:12],
        source=path,
        name=path.name,
        origin=origin,
        location=location,
    )


def _add_notice(skipped: int, truncated: bool) -> str:
    parts = []
    if truncated:
        parts.append(f"Only the first {MAX_BATCH} images were added.")
    if skipped:
        parts.append(f"Skipped {skipped} file{'s' if skipped != 1 else ''} that aren't images.")
    return " ".join(parts)


def _discard_files(batch_id: str) -> None:
    shutil.rmtree(INBOX / batch_id, ignore_errors=True)
    shutil.rmtree(PREVIEWS / batch_id, ignore_errors=True)


def friendly_error(exc: Exception) -> str:
    if isinstance(exc, (OutputTooLarge, TooLarge)):
        return str(exc)
    if isinstance(exc, PermissionError):
        return "Can't save next to that file. Switch Save to the output folder and run it again."
    if isinstance(exc, UnidentifiedImageError):
        return "Couldn't open this file. Use a JPEG, PNG, WebP, TIFF, or HEIC."
    if isinstance(exc, OSError) and exc.errno == 28:
        return "The disk is full."
    text = str(exc).strip() or exc.__class__.__name__
    if "urlopen" in text.lower() or "nodename" in text.lower() or "network" in text.lower():
        return "Couldn't download the model. Check the network and run it again."
    if len(text) > 280:
        return text[:277] + "…"
    return text


def send_system_notification(title: str, message: str) -> None:
    try:
        import platform
        import subprocess

        if platform.system() == "Darwin":
            safe_title = title.replace('"', '\\"')
            safe_msg = message.replace('"', '\\"')
            script = f'display notification "{safe_msg}" with title "{safe_title}" sound name "Glass"'
            subprocess.run(["osascript", "-e", script], check=False, timeout=3)
    except Exception:
        pass

