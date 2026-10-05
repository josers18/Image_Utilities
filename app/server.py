"""Local page for cutting out, enlarging, resizing, converting, and renaming images."""

from __future__ import annotations

import asyncio
import json
import logging
import subprocess
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import INBOX, PREVIEWS
from app.finish import Options
from app.jobs import Store, after_preview, before_preview, result_thumb, source_thumb, waiting_preview
from app.naming import safe_filename
from app.picker import choose_files, choose_folder

log = logging.getLogger("image_utilities")
STATIC = Path(__file__).resolve().parent / "static"
store = Store()


class BatchRemoveBody(BaseModel):
    ids: list[str]


class FolderPick(BaseModel):
    subfolders: bool = False


class RunBody(BaseModel):
    task: str = "both"
    scale: int = 4
    look: str = "photo"
    save: str = "beside"
    fit: str = "none"
    fit_a: int = 2048
    fit_b: int = 2048
    no_upscale: bool = False
    edge: str = "normal"
    fill_holes: bool = True
    trim: bool = False
    padding: int = 32
    background: str = "transparent"
    background_hex: str = "#ffffff"
    shadow: bool = False
    format: str = "png"
    quality: int = 90
    also_webp: bool = False
    srgb: bool = False
    prefix: str = ""
    suffix: str = ""
    find: str = ""
    replace: str = ""
    number: bool = False
    number_start: int = 1
    digits: int = 2


class OpenBody(BaseModel):
    paths: list[str] = Field(default_factory=list, max_length=200)


def create_app() -> FastAPI:
    app = FastAPI(title="Image Utilities")
    app.mount("/static", _Static(directory=STATIC), name="static")

    @app.middleware("http")
    async def guard(request, call_next):
        try:
            return await call_next(request)
        except (StarletteHTTPException, RequestValidationError):
            raise
        except Exception:
            log.exception("Request failed")
            return JSONResponse(
                status_code=500,
                content={"detail": "Something went wrong. The terminal has the details."},
            )

    @app.get("/")
    def index():
        return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})

    @app.get("/api/state")
    def state():
        return store.snapshot()

    @app.get("/api/events")
    async def sse_events(request: Request):
        queue = asyncio.Queue()
        loop = asyncio.get_running_loop()
        store.subscribe(queue, loop)

        async def event_generator():
            try:
                yield f"data: {json.dumps(store.snapshot())}\n\n"
                while True:
                    if await request.is_disconnected():
                        break
                    try:
                        data = await asyncio.wait_for(queue.get(), timeout=15.0)
                        yield f"data: {data}\n\n"
                    except asyncio.TimeoutError:
                        yield ": keep-alive\n\n"
            finally:
                store.unsubscribe(queue, loop)

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    @app.post("/api/pick/files")
    def pick_files():
        try:
            chosen = choose_files()
        except RuntimeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if chosen is None:
            return store.snapshot(cancelled=True)
        return store.add_paths(chosen, subfolders=False)

    @app.post("/api/pick/folder")
    def pick_folder(body: FolderPick):
        try:
            folder = choose_folder()
        except RuntimeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if folder is None:
            return store.snapshot(cancelled=True)
        return store.add_paths([folder], subfolders=body.subfolders)

    @app.post("/api/uploads")
    async def uploads(files: list[UploadFile] = File(...)):
        folder_id = store.upload_folder()
        folder = INBOX / folder_id
        folder.mkdir(parents=True, exist_ok=True)
        saved: list[Path] = []
        for upload in files:
            name = safe_filename(upload.filename or "image")
            dest = folder / name
            if dest.exists():
                dest = folder / f"{Path(name).stem}-{len(saved)}{Path(name).suffix}"
            with dest.open("wb") as handle:
                while True:
                    chunk = await upload.read(1024 * 1024)
                    if not chunk:
                        break
                    handle.write(chunk)
            saved.append(dest)
        return store.add_uploads(saved, folder_id)

    @app.delete("/api/items/{item_id}")
    def remove_item(item_id: str):
        return store.remove_item(item_id)

    @app.post("/api/items/clear")
    def clear_items():
        return store.clear_batch()

    @app.post("/api/items/remove-batch")
    def remove_batch(body: BatchRemoveBody):
        return store.remove_items(body.ids)

    @app.post("/api/output-dir")
    def output_dir():
        try:
            folder = choose_folder()
        except RuntimeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if folder is None:
            return store.snapshot(cancelled=True)
        return store.set_output_dir(folder)

    @app.post("/api/run")
    def run(body: RunBody):
        return store.start(Options.from_dict(body.model_dump()))

    @app.post("/api/open")
    def open_paths(body: OpenBody):
        paths = [Path(raw).expanduser() for raw in body.paths if raw.strip()]
        paths = [path for path in paths if path.exists()]
        if not paths:
            raise HTTPException(status_code=400, detail="None of those files are available.")
        store.add_paths(paths, subfolders=False, replace=True)
        return store.start(Options.from_dict(store.settings.last))

    @app.post("/api/cancel")
    def cancel():
        return store.request_cancel()

    @app.get("/api/items/{item_id}/thumb")
    def thumb(item_id: str):
        item = store.item(item_id)
        batch_id = store.current_batch_id()
        if item.status == "done":
            ready = result_thumb(item, batch_id)
            if ready is not None:
                return FileResponse(ready)
        return FileResponse(source_thumb(item, batch_id))

    @app.get("/api/items/{item_id}/preview/{which}")
    def preview(item_id: str, which: str):
        if which not in ("before", "after", "source"):
            raise HTTPException(status_code=404, detail="Unknown preview.")
        item = store.item(item_id)
        batch_id = store.current_batch_id()
        if which == "source":
            return FileResponse(waiting_preview(item, batch_id))
        path = before_preview(batch_id, item) if which == "before" else after_preview(batch_id, item)
        if path is None or not path.resolve().is_relative_to(PREVIEWS.resolve()):
            raise HTTPException(status_code=404, detail="The preview isn't ready.")
        return FileResponse(path)

    @app.get("/api/items/{item_id}/file")
    def download(item_id: str):
        item = store.item(item_id)
        if item.output is None or not item.output.is_file():
            raise HTTPException(status_code=404, detail="That file isn't saved yet.")
        return FileResponse(item.output, filename=item.output.name)

    @app.post("/api/items/{item_id}/reveal")
    def reveal(item_id: str):
        item = store.item(item_id)
        if item.output is None or not item.output.is_file():
            raise HTTPException(status_code=404, detail="That file isn't saved yet.")
        subprocess.run(["open", "-R", str(item.output)], check=False)
        return {"ok": True}

    return app


class _Static(StaticFiles):
    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        return response


app = create_app()
