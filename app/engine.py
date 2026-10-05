"""Cut out backgrounds and enlarge images.

Cutout uses BiRefNet through rembg. Enlarging uses Real-ESRGAN on the Mac
GPU when Metal is available. Doing both enlarges first, then cuts out, so
the matte lines up with the sharpened picture.
"""

from __future__ import annotations

import threading
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F
from PIL import Image, ImageFilter, ImageOps
from rembg import new_session, remove

from app.config import MAX_EDGE, MAX_PIXELS, MODELS
from app.finish import Options, finish_image, write_outputs
from app.tiles import iter_tiles

try:
    from pillow_heif import register_heif_opener

    register_heif_opener()
except ImportError:
    pass

Image.MAX_IMAGE_PIXELS = 400_000_000

MODEL_FILES = {
    ("photo", 2): (
        "RealESRGAN_x2plus.pth",
        "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.1/RealESRGAN_x2plus.pth",
        2,
    ),
    ("photo", 4): (
        "RealESRGAN_x4plus.pth",
        "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.0/RealESRGAN_x4plus.pth",
        4,
    ),
    ("illustration", 4): (
        "RealESRGAN_x4plus_anime_6B.pth",
        "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.2.4/RealESRGAN_x4plus_anime_6B.pth",
        4,
    ),
}


class Cancelled(Exception):
    pass


class OutputTooLarge(Exception):
    pass


@dataclass
class JobSpec:
    source: Path
    dest_dir: Path
    dest_name: str
    task: str
    scale: int
    look: str
    preview_before: Path
    preview_after: Path
    thumb: Path
    options: Options | None = None


@dataclass
class Result:
    output: Path
    source_width: int
    source_height: int
    width: int
    height: int
    note: str


class Reporter:
    def __init__(self, fn) -> None:
        self.fn = fn

    def __call__(self, phase: str, frac: float = 1.0) -> None:
        self.fn(phase, float(frac))

    def span(self, start: float, end: float) -> Reporter:
        def inner(phase: str, frac: float = 1.0) -> None:
            bounded = max(0.0, min(1.0, float(frac)))
            self.fn(phase, start + (end - start) * bounded)

        return Reporter(inner)


def device_name() -> str:
    if torch.backends.mps.is_available():
        return "GPU"
    return "CPU"


def load_image(path: Path) -> tuple[Image.Image, dict]:
    image = Image.open(path)
    note = ""
    frames = getattr(image, "n_frames", 1) or 1
    if getattr(image, "is_animated", False) or frames > 1:
        image.seek(0)
        note = "Used the first frame."
    exif = image.info.get("exif")
    if exif is None and hasattr(image, "getexif"):
        try:
            raw_exif = image.getexif()
            if raw_exif:
                exif = raw_exif.tobytes()
        except Exception:
            exif = None
    image = ImageOps.exif_transpose(image)
    meta = {
        "icc": image.info.get("icc_profile"),
        "dpi": _dpi(image.info.get("dpi")),
        "exif": exif,
        "note": note,
    }
    if image.mode == "P":
        image = image.convert("RGBA" if "transparency" in image.info else "RGB")
    elif image.mode == "LA":
        image = image.convert("RGBA")
    elif image.mode == "L":
        image = image.convert("RGB")
    elif image.mode == "CMYK":
        image = image.convert("RGB")
        meta["icc"] = None
    elif image.mode not in ("RGB", "RGBA"):
        image = image.convert("RGB")
        meta["icc"] = None
    return image, meta


def _dpi(value) -> tuple[float, float] | None:
    if not isinstance(value, tuple) or len(value) != 2:
        return None
    try:
        return (float(value[0]), float(value[1]))
    except (TypeError, ValueError):
        return None


class Engine:
    def __init__(self) -> None:
        self.device = torch.device("mps" if torch.backends.mps.is_available() else "cpu")
        self._lock = threading.Lock()
        self._cutout = None
        self._upscalers: dict[tuple[str, int], object] = {}

    def process_file(
        self,
        spec: JobSpec,
        report: Reporter,
        cancel: threading.Event,
    ) -> Result:
        self._check(cancel)
        report("Opening", 0.02)
        image, meta = load_image(spec.source)
        out_scale = spec.scale if spec.task in ("upscale", "both") else 1
        self._check_size(image.width * out_scale, image.height * out_scale)

        working = image
        note = meta["note"]
        if spec.task in ("upscale", "both"):
            model_key, model_scale = _model_choice(spec.look, spec.scale)
            up_end = 0.72 if spec.task == "both" else 0.9
            enlarged = self._upscale(
                working,
                model_key,
                model_scale,
                spec.scale,
                keep_alpha=spec.task == "upscale" and _has_transparency(working),
                report=report.span(0.04, up_end),
                cancel=cancel,
            )
            working = enlarged
        if spec.task in ("cutout", "both"):
            self._check(cancel)
            load_span = report.span(0.04, 0.3) if spec.task == "cutout" else report.span(0.72, 0.78)
            session = self._cutout_session(load_span)
            report("Removing the background", 0.82 if spec.task == "both" else 0.45)
            working = _cutout(working, session)

        options = spec.options or Options(task=spec.task, scale=spec.scale, look=spec.look)
        if spec.task in ("resize", "convert", "cutout", "upscale", "both"):
            report("Finishing", 0.9)
            working, meta, extra = finish_image(working, meta, options)
            if extra:
                note = " ".join(part for part in (note, " ".join(extra)) if part)

        report("Saving", 0.94)
        self._check(cancel)
        dest, saved = write_outputs(working, meta, spec.dest_dir, spec.dest_name, options)
        if saved:
            note = " ".join(part for part in (note, " ".join(saved)) if part)
        _write_preview(image, spec.preview_before)
        _write_preview(working, spec.preview_after)
        _write_thumb(working, spec.thumb)
        report("Saved", 1)
        return Result(
            output=dest,
            source_width=image.width,
            source_height=image.height,
            width=working.width,
            height=working.height,
            note=note,
        )

    def _cutout_session(self, report: Reporter):
        with self._lock:
            session = self._cutout
        if session is not None:
            return session
        cached = Path.home().joinpath(".rembg", "models", "birefnet-general", "birefnet-general.onnx").exists()
        if cached:
            report("Loading the cutout model", 0.4)
        else:
            report("Downloading the cutout model — the terminal shows progress", 0.2)
        session = new_session("birefnet-general")
        with self._lock:
            if self._cutout is None:
                self._cutout = session
            return self._cutout

    def _upscale(
        self,
        image: Image.Image,
        model_key: tuple[str, int],
        model_scale: int,
        out_scale: int,
        keep_alpha: bool,
        report: Reporter,
        cancel: threading.Event,
    ) -> Image.Image:
        # A transparent image that is only being enlarged keeps its alpha.
        # Color is premultiplied first so empty pixels don't bleed into the edge.
        if keep_alpha:
            return self._upscale_with_alpha(image, model_key, model_scale, out_scale, report, cancel)

        flat = _flatten(image)
        array = np.ascontiguousarray(flat, dtype=np.uint8)
        enlarged = self._run_upscaler(array, model_key, model_scale, out_scale, report, cancel)
        return Image.fromarray(enlarged, "RGB")

    def _upscale_with_alpha(self, image, model_key, model_scale, out_scale, report, cancel) -> Image.Image:
        arr = np.asarray(image.convert("RGBA"), dtype=np.float32)
        alpha = arr[:, :, 3:4] / 255.0
        premul = np.clip(arr[:, :, :3] * alpha, 0, 255).astype(np.uint8)
        rgb = self._run_upscaler(premul, model_key, model_scale, out_scale, report, cancel)
        alpha_im = Image.fromarray(arr[:, :, 3].astype(np.uint8), "L")
        alpha_im = alpha_im.resize(rgb.shape[1::-1], Image.Resampling.LANCZOS)
        up_alpha = np.asarray(alpha_im, dtype=np.float32) / 255.0
        safe = np.maximum(up_alpha, 1.0 / 255.0)
        color = np.clip(rgb.astype(np.float32) / safe[:, :, None], 0, 255)
        out = np.dstack([color, up_alpha * 255.0]).astype(np.uint8)
        return Image.fromarray(out, "RGBA")

    def _run_upscaler(
        self,
        rgb: np.ndarray,
        model_key: tuple[str, int],
        model_scale: int,
        out_scale: int,
        report: Reporter,
        cancel: threading.Event,
    ) -> np.ndarray:
        model = self._get_upscaler(model_key, report.span(0.0, 0.22), cancel)
        height, width = rgb.shape[:2]
        reduce = model_scale // out_scale
        output = np.empty((height * out_scale, width * out_scale, 3), dtype=np.uint8)
        last_error: RuntimeError | None = None
        for tile_size in (768, 384):
            try:
                self._fill_tiles(
                    model, rgb, output, model_scale, reduce, tile_size, report.span(0.22, 1.0), cancel
                )
                return output
            except RuntimeError as exc:
                if not _memory_error(exc):
                    raise
                last_error = exc
                _empty_cache(self.device)
                report("Retrying in smaller pieces", 0.22)
        if self.device.type == "mps":
            report("Continuing on the CPU", 0.22)
            model.to(torch.device("cpu"))
            try:
                self._fill_tiles(
                    model, rgb, output, model_scale, reduce, 384, report.span(0.22, 1.0), cancel, device=torch.device("cpu")
                )
                return output
            finally:
                model.to(self.device)
                _empty_cache(self.device)
        if last_error is not None:
            raise last_error
        raise RuntimeError("Enlarging failed.")

    def _fill_tiles(
        self,
        model,
        rgb: np.ndarray,
        output: np.ndarray,
        model_scale: int,
        reduce: int,
        tile_size: int,
        report: Reporter,
        cancel: threading.Event,
        device: torch.device | None = None,
    ) -> None:
        device = device or self.device
        height, width = rgb.shape[:2]
        tiles = iter_tiles(width, height, tile_size, 32)
        total = max(len(tiles), 1)
        for index, tile in enumerate(tiles):
            self._check(cancel)
            window = rgb[tile.win_top : tile.win_bottom, tile.win_left : tile.win_right]
            pred = _infer_tile(model, window, model_scale, device)
            crop = pred[
                (tile.top - tile.win_top) * model_scale : (tile.bottom - tile.win_top) * model_scale,
                (tile.left - tile.win_left) * model_scale : (tile.right - tile.win_left) * model_scale,
            ]
            if reduce == 2:
                # The illustration model only enlarges 4×. For a 2× result,
                # average each 2×2 block so neighboring tiles still meet.
                crop = _box_downsample_2(crop)
            y = tile.top * (model_scale // reduce)
            x = tile.left * (model_scale // reduce)
            expected_h = (tile.bottom - tile.top) * (model_scale // reduce)
            expected_w = (tile.right - tile.left) * (model_scale // reduce)
            if crop.shape[0] != expected_h or crop.shape[1] != expected_w:
                raise RuntimeError(
                    f"Enlarge tile was {crop.shape[1]}×{crop.shape[0]}, expected {expected_w}×{expected_h}."
                )
            output[y : y + crop.shape[0], x : x + crop.shape[1]] = crop
            report("Enlarging", (index + 1) / total)
            if index % 6 == 5:
                _empty_cache(device)

    def _get_upscaler(self, model_key: tuple[str, int], report: Reporter, cancel: threading.Event):
        with self._lock:
            cached = self._upscalers.get(model_key)
        if cached is not None:
            report("Loading the enlarge model", 1)
            return cached
        filename, url, expected_scale = MODEL_FILES[model_key]
        label = "illustration" if model_key[0] == "illustration" else f"photo {expected_scale}×"
        path = MODELS / filename
        _download(url, path, f"Downloading the {label} model", report.span(0.0, 0.75), cancel)
        report("Loading the enlarge model", 0.9)
        from spandrel import ImageModelDescriptor, ModelLoader

        try:
            descriptor = ModelLoader().load_from_file(path)
        except Exception as exc:
            path.unlink(missing_ok=True)
            raise RuntimeError(
                f"The model file {filename} didn't load, so it was removed. Run again to download it."
            ) from exc
        if not isinstance(descriptor, ImageModelDescriptor):
            raise RuntimeError(f"{filename} is not an image model.")
        if descriptor.scale != expected_scale:
            raise RuntimeError(f"{filename} enlarges {descriptor.scale}×, expected {expected_scale}×.")
        moved = descriptor.to(self.device)
        (moved or descriptor).eval()
        with self._lock:
            self._upscalers.setdefault(model_key, descriptor)
            return self._upscalers[model_key]

    def _check(self, cancel: threading.Event) -> None:
        if cancel.is_set():
            raise Cancelled()

    def _check_size(self, width: int, height: int) -> None:
        if max(width, height) > MAX_EDGE or width * height > MAX_PIXELS:
            raise OutputTooLarge(
                f"The result would be {width}×{height} pixels, which is too large. "
                "Use 2×, or start from a smaller image."
            )


def _model_choice(look: str, out_scale: int) -> tuple[tuple[str, int], int]:
    if look == "illustration":
        return ("illustration", 4), 4
    return (look, out_scale), out_scale


def _has_transparency(image: Image.Image) -> bool:
    if image.mode != "RGBA":
        return False
    return image.getchannel("A").getextrema()[0] < 255


def _flatten(image: Image.Image) -> Image.Image:
    if image.mode == "RGBA" and _has_transparency(image):
        base = Image.new("RGB", image.size, (255, 255, 255))
        base.paste(image, mask=image.getchannel("A"))
        return base
    return image.convert("RGB")


def _cutout(image: Image.Image, session) -> Image.Image:
    flat = _flatten(image)
    # pymatting's foreground estimate is the better edge cleanup, and it gets
    # expensive past a normal photo. Larger results use a cheaper fill.
    small = flat.width * flat.height <= 16_000_000
    try:
        result = remove(flat, session=session, decontaminate=small)
    except Exception:
        if not small:
            raise
        result = remove(flat, session=session)
        small = False
    if isinstance(result, (bytes, bytearray)):
        from io import BytesIO

        result = Image.open(BytesIO(result))
    result = result.convert("RGBA")
    if not small:
        result = _decontaminate(result)
    return result


def _decontaminate(image: Image.Image) -> Image.Image:
    """Pull foreground color into soft edge pixels.

    The mask is right, but those pixels still contain background color. A
    shared blur of the opaque colors, divided by the blur of the mask, fills
    them with nearby foreground color instead.
    """
    arr = np.asarray(image.convert("RGBA")).astype(np.float32)
    rgb = arr[:, :, :3]
    alpha = arr[:, :, 3]
    confident = alpha > (0.85 * 255)
    if not bool(confident.any()):
        return image
    color = np.where(confident[:, :, None], rgb, 0)
    weight = np.where(confident, 255, 0).astype(np.uint8)
    color_im = Image.fromarray(np.clip(color, 0, 255).astype(np.uint8), "RGB")
    weight_im = Image.fromarray(weight, "L")
    for _ in range(6):
        color_im = color_im.filter(ImageFilter.BoxBlur(1))
        weight_im = weight_im.filter(ImageFilter.BoxBlur(1))
    blurred = np.asarray(color_im).astype(np.float32)
    weight_f = np.asarray(weight_im).astype(np.float32) / 255.0
    use = (alpha > 0) & ~confident & (weight_f > 0.02)
    if not bool(use.any()):
        return image
    filled = blurred / np.maximum(weight_f, 1e-4)[:, :, None]
    rgb[use] = np.clip(filled[use], 0, 255)
    arr[:, :, :3] = rgb
    return Image.fromarray(arr.astype(np.uint8), "RGBA")


def _infer_tile(model, window: np.ndarray, scale: int, device: torch.device) -> np.ndarray:
    array = np.ascontiguousarray(window, dtype=np.uint8)
    tensor = torch.from_numpy(array.copy())
    tensor = tensor.permute(2, 0, 1).unsqueeze(0).to(device=device, dtype=torch.float32).div_(255.0)
    _, _, height, width = tensor.shape
    pad_h = (4 - height % 4) % 4
    pad_w = (4 - width % 4) % 4
    if pad_h or pad_w:
        mode = "reflect"
        if height <= 1 or width <= 1 or pad_h >= height or pad_w >= width:
            mode = "replicate"
        tensor = F.pad(tensor, (0, pad_w, 0, pad_h), mode=mode)
    with torch.inference_mode():
        pred = model(tensor)
    pred = pred[:, :, : height * scale, : width * scale].clamp(0, 1)
    if device.type == "mps":
        torch.mps.synchronize()
    out = pred.squeeze(0).permute(1, 2, 0).detach().cpu().numpy()
    return np.clip(out * 255.0 + 0.5, 0, 255).astype(np.uint8)


def _box_downsample_2(arr: np.ndarray) -> np.ndarray:
    height, width = arr.shape[:2]
    height -= height % 2
    width -= width % 2
    block = arr[:height, :width].astype(np.float32)
    block = block.reshape(height // 2, 2, width // 2, 2, block.shape[2]).mean(axis=(1, 3))
    return np.clip(block + 0.5, 0, 255).astype(np.uint8)


def _download(url: str, dest: Path, phase: str, report: Reporter, cancel: threading.Event) -> None:
    if dest.exists() and dest.stat().st_size > 5_000_000:
        report(phase, 1)
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    partial = dest.with_suffix(dest.suffix + ".part")
    request = urllib.request.Request(url, headers={"User-Agent": "ImageUtilities"})
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            content_type = response.headers.get("Content-Type", "")
            if "text/html" in content_type:
                raise RuntimeError("The model download returned a web page instead of the file.")
            total = int(response.headers.get("Content-Length") or 0)
            done = 0
            with partial.open("wb") as handle:
                while True:
                    if cancel.is_set():
                        raise Cancelled()
                    chunk = response.read(256 * 1024)
                    if not chunk:
                        break
                    handle.write(chunk)
                    done += len(chunk)
                    if total:
                        report(phase, done / total)
        if partial.stat().st_size < 1_000_000:
            raise RuntimeError("The model download stopped early.")
        partial.replace(dest)
    except Cancelled:
        partial.unlink(missing_ok=True)
        raise
    except Exception:
        partial.unlink(missing_ok=True)
        raise
    report(phase, 1)


def _write_preview(image: Image.Image, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    preview = image.copy()
    preview.thumbnail((2000, 2000), Image.Resampling.LANCZOS)
    if preview.mode == "RGBA":
        preview.save(dest.with_suffix(".png"), "PNG", compress_level=3)
    else:
        preview.convert("RGB").save(dest.with_suffix(".jpg"), "JPEG", quality=90)


def _write_thumb(image: Image.Image, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    thumb = image.copy()
    thumb.thumbnail((360, 360), Image.Resampling.LANCZOS)
    if thumb.mode == "RGBA":
        board = Image.new("RGB", thumb.size, (28, 26, 24))
        board.paste(thumb, mask=thumb.getchannel("A"))
        thumb = board
    else:
        thumb = thumb.convert("RGB")
    thumb.save(dest, "JPEG", quality=85)


def remember_views(image: Image.Image, folder: Path, item_id: str) -> None:
    """Write the before, after, and thumb used by the page. Rename uses the same picture for both."""
    _write_preview(image, folder / f"{item_id}-before.jpg")
    _write_preview(image, folder / f"{item_id}-after.png")
    _write_thumb(image, folder / f"{item_id}-thumb.jpg")


def make_source_thumb(source: Path, dest: Path) -> None:
    if dest.exists():
        return
    image, _meta = load_image(source)
    _write_thumb(image, dest)


def make_source_preview(source: Path, dest: Path) -> None:
    """A large preview of the original, so the page can show it before a run."""
    if dest.exists():
        return
    image, _meta = load_image(source)
    preview = image.convert("RGB")
    preview.thumbnail((1600, 1600), Image.Resampling.LANCZOS)
    dest.parent.mkdir(parents=True, exist_ok=True)
    preview.save(dest, "JPEG", quality=88)


def _memory_error(exc: RuntimeError) -> bool:
    text = str(exc).lower()
    return "memory" in text or "mps" in text or "out of" in text


def _empty_cache(device: torch.device) -> None:
    if device.type == "mps":
        torch.mps.empty_cache()
