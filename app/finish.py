"""Resize, trim, matte, color, file format, and rename.

The model pipeline stays in engine.py. Everything here is ordinary image work.
"""

from __future__ import annotations

import shutil
from dataclasses import asdict, dataclass, fields
from io import BytesIO
from pathlib import Path

import numpy as np
from PIL import Image, ImageCms, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps

from app.config import MAX_EDGE, MAX_PIXELS
from app.naming import output_name, unique_path

PAPER = (244, 241, 234)
TASKS = {"cutout", "upscale", "both", "resize", "convert", "rename"}
FITS = {"none", "long", "width", "height", "box", "percent"}
ASPECT_RATIOS = {"auto", "1:1", "4:5", "9:16", "16:9", "4:3", "3:2"}
WATERMARK_POSITIONS = {"bottom-right", "bottom-left", "top-right", "top-left", "center"}
EDGES = {"tight", "normal", "loose"}
BACKGROUNDS = {"transparent", "white", "paper", "custom"}
FORMATS = {"png", "jpeg", "webp", "svg", "same"}
INT_FIELDS = {
    "scale",
    "fit_a",
    "fit_b",
    "padding",
    "quality",
    "sharpen",
    "brightness",
    "contrast",
    "saturation",
    "watermark_opacity",
    "watermark_size",
    "number_start",
    "digits",
}
BOOL_FIELDS = {"no_upscale", "fill_holes", "trim", "shadow", "also_webp", "srgb", "number", "keep_exif", "auto_contrast"}


class TooLarge(Exception):
    pass


@dataclass
class Options:
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
    aspect_ratio: str = "auto"
    sharpen: int = 0
    keep_exif: bool = True
    brightness: int = 100
    contrast: int = 100
    saturation: int = 100
    auto_contrast: bool = False
    watermark_text: str = ""
    watermark_pos: str = "bottom-right"
    watermark_opacity: int = 50
    watermark_size: int = 24

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: object) -> Options:
        options = cls()
        if not isinstance(data, dict):
            return normalize(options)
        known = {item.name for item in fields(cls)}
        for key, value in data.items():
            if key not in known or value is None:
                continue
            if key in INT_FIELDS:
                try:
                    value = int(value)
                except (TypeError, ValueError):
                    continue
            elif key in BOOL_FIELDS:
                value = bool(value)
            else:
                value = str(value)
            setattr(options, key, value)
        return normalize(options)


def normalize(options: Options) -> Options:
    if options.task not in TASKS:
        options.task = "both"
    if options.scale not in (2, 4):
        options.scale = 4
    if options.look not in ("photo", "illustration"):
        options.look = "photo"
    if options.save not in ("beside", "folder"):
        options.save = "beside"
    if options.fit not in FITS:
        options.fit = "none"
    if options.edge not in EDGES:
        options.edge = "normal"
    if options.background not in BACKGROUNDS:
        options.background = "transparent"
    if options.format not in FORMATS:
        options.format = "png"
    if options.aspect_ratio not in ASPECT_RATIOS:
        options.aspect_ratio = "auto"
    options.fit_a = _clamp(options.fit_a, 0, MAX_EDGE)
    options.fit_b = _clamp(options.fit_b, 0, MAX_EDGE)
    options.padding = _clamp(options.padding, 0, 512)
    options.quality = _clamp(options.quality, 1, 100)
    options.sharpen = _clamp(options.sharpen, 0, 100)
    options.brightness = _clamp(options.brightness, 50, 150)
    options.contrast = _clamp(options.contrast, 50, 150)
    options.saturation = _clamp(options.saturation, 0, 200)
    options.watermark_opacity = _clamp(options.watermark_opacity, 10, 100)
    options.watermark_size = _clamp(options.watermark_size, 10, 200)
    if options.watermark_pos not in WATERMARK_POSITIONS:
        options.watermark_pos = "bottom-right"
    options.watermark_text = str(options.watermark_text or "").strip()[:100]
    options.number_start = _clamp(options.number_start, 0, 9999)
    options.digits = _clamp(options.digits, 1, 4)
    options.background_hex = _hex(options.background_hex)
    options.prefix = _label(options.prefix)
    options.suffix = _label(options.suffix)
    options.find = _label(options.find, 120)
    options.replace = _label(options.replace, 120)
    if options.task == "resize" and options.fit == "none":
        options.fit = "long"
        if options.fit_a <= 0:
            options.fit_a = 2048
    if options.task == "convert" and options.format == "same":
        options.format = "webp"
    if options.task == "rename":
        options.format = "same"
        options.also_webp = False
    if options.format == "webp":
        options.also_webp = False
    if options.fit in ("long", "width", "height", "percent") and options.fit_a <= 0:
        options.fit_a = 100 if options.fit == "percent" else 2048
    if options.fit == "box":
        if options.fit_a <= 0:
            options.fit_a = 2048
        if options.fit_b <= 0:
            options.fit_b = options.fit_a
    if options.fit == "percent":
        options.fit_a = _clamp(options.fit_a, 1, 800)
    return options


def renamed_stem(stem: str, options: Options, index: int) -> str:
    text = stem or "image"
    if options.find:
        text = text.replace(options.find, options.replace)
    text = f"{options.prefix}{text}{options.suffix}"
    text = _label(text, 180)
    if options.number:
        text = f"{text}-{options.number_start + index:0{options.digits}d}"
    text = text.strip(" .")
    if not text:
        text = stem or "image"
    return text


def disambiguate(stems: list[str]) -> list[str]:
    used: set[str] = set()
    names: list[str] = []
    for stem in stems:
        candidate = stem
        base = stem
        number = 2
        while candidate.lower() in used:
            candidate = f"{base}-{number}"
            number += 1
        used.add(candidate.lower())
        names.append(candidate)
    return names


def file_suffix(options: Options, source: Path) -> str:
    if options.task == "rename" or options.format == "same":
        mapped = {".jpeg": ".jpg", ".jpg": ".jpg", ".png": ".png", ".webp": ".webp"}.get(source.suffix.lower())
        return mapped or ".png"
    if options.format == "jpeg":
        return ".jpg"
    return f".{options.format}"


def planned_filename(stem: str, options: Options, index: int, source: Path) -> str:
    name = renamed_stem(stem, options, index)
    return output_name(name, options.task, options.scale, file_suffix(options, source))


def target_size(
    width: int,
    height: int,
    fit: str,
    fit_a: int,
    fit_b: int,
    no_upscale: bool,
) -> tuple[int, int, str]:
    """Return the new size and a short note when the picture was left alone."""
    if fit == "none" or width <= 0 or height <= 0:
        return width, height, ""
    if fit == "percent":
        scale = fit_a / 100
    elif fit == "long":
        scale = fit_a / max(width, height)
    elif fit == "width":
        scale = fit_a / width
    elif fit == "height":
        scale = fit_a / height
    elif fit == "box":
        box_w = fit_a or fit_b
        box_h = fit_b or fit_a
        scale = min(box_w / width, box_h / height)
    else:
        return width, height, ""
    new_w = max(1, round(width * scale))
    new_h = max(1, round(height * scale))
    if no_upscale and (new_w > width or new_h > height):
        return width, height, "Kept the original size because it was already smaller."
    if max(new_w, new_h) > MAX_EDGE or new_w * new_h > MAX_PIXELS:
        raise TooLarge(
            f"The result would be {new_w}×{new_h} pixels, which is too large. Use a smaller size."
        )
    return new_w, new_h, ""


def pad_to_aspect_ratio(image: Image.Image, ratio_str: str, options: Options) -> Image.Image:
    if ratio_str == "auto":
        return image
    parts = ratio_str.split(":")
    if len(parts) != 2:
        return image
    try:
        rw, rh = float(parts[0]), float(parts[1])
        if rw <= 0 or rh <= 0:
            return image
        target_ratio = rw / rh
    except ValueError:
        return image

    curr_ratio = image.width / image.height
    if abs(curr_ratio - target_ratio) < 1e-4:
        return image

    if curr_ratio > target_ratio:
        new_width = image.width
        new_height = max(1, round(image.width / target_ratio))
    else:
        new_height = image.height
        new_width = max(1, round(image.height * target_ratio))

    bg = _background(options)
    if bg is None or image.mode == "RGBA":
        if bg is None:
            canvas = Image.new("RGBA", (new_width, new_height), (0, 0, 0, 0))
        else:
            canvas = Image.new("RGBA", (new_width, new_height), (*bg, 255))
        offset_x = (new_width - image.width) // 2
        offset_y = (new_height - image.height) // 2
        canvas.paste(image, (offset_x, offset_y), mask=image if image.mode == "RGBA" else None)
        return canvas
    else:
        canvas = Image.new("RGB", (new_width, new_height), bg)
        offset_x = (new_width - image.width) // 2
        offset_y = (new_height - image.height) // 2
        canvas.paste(image, (offset_x, offset_y))
        return canvas


def apply_sharpen(image: Image.Image, amount: int) -> Image.Image:
    if amount <= 0:
        return image
    radius = max(0.8, min(2.5, amount * 0.025))
    percent = int(amount * 1.5)
    return image.filter(ImageFilter.UnsharpMask(radius=radius, percent=percent, threshold=3))


def apply_adjustments(image: Image.Image, options: Options) -> Image.Image:
    has_alpha = "A" in image.getbands()
    alpha = image.getchannel("A") if has_alpha else None

    working = image.convert("RGB")
    if options.auto_contrast:
        working = ImageOps.autocontrast(working, cutoff=0.5)
    if options.brightness != 100:
        working = ImageEnhance.Brightness(working).enhance(options.brightness / 100.0)
    if options.contrast != 100:
        working = ImageEnhance.Contrast(working).enhance(options.contrast / 100.0)
    if options.saturation != 100:
        working = ImageEnhance.Color(working).enhance(options.saturation / 100.0)

    if has_alpha and alpha is not None:
        working = working.convert("RGBA")
        working.putalpha(alpha)
    elif image.mode == "RGBA":
        working = working.convert("RGBA")
    return working


def apply_watermark(image: Image.Image, options: Options) -> Image.Image:
    text = options.watermark_text.strip()
    if not text:
        return image

    working = image.convert("RGBA")
    overlay = Image.new("RGBA", working.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    font_size = max(10, min(options.watermark_size, min(working.size) // 5))
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", size=font_size)
    except Exception:
        try:
            font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", size=font_size)
        except Exception:
            font = ImageFont.load_default()

    bbox = draw.textbbox((0, 0), text, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    margin = max(16, font_size)

    pos = options.watermark_pos
    if pos == "top-left":
        x, y = margin, margin
    elif pos == "top-right":
        x, y = working.width - text_w - margin, margin
    elif pos == "bottom-left":
        x, y = margin, working.height - text_h - margin
    elif pos == "center":
        x, y = (working.width - text_w) // 2, (working.height - text_h) // 2
    else:  # bottom-right
        x, y = working.width - text_w - margin, working.height - text_h - margin

    x = max(0, min(x, working.width - text_w))
    y = max(0, min(y, working.height - text_h))

    alpha_shadow = int(options.watermark_opacity * 2.55 * 0.6)
    draw.text((x + 1, y + 1), text, fill=(0, 0, 0, alpha_shadow), font=font)
    alpha_fg = int(options.watermark_opacity * 2.55)
    draw.text((x, y), text, fill=(255, 255, 255, alpha_fg), font=font)

    return Image.alpha_composite(working, overlay)


def finish_image(image: Image.Image, meta: dict, options: Options) -> tuple[Image.Image, dict, list[str]]:
    notes: list[str] = []
    meta = dict(meta)
    if options.task in ("cutout", "both"):
        image = adjust_edge(image, options.edge, options.fill_holes)
        padding = options.padding if options.trim else 0
        if options.shadow:
            padding = max(padding, 64)
        if options.trim or options.shadow:
            image = crop_to_subject(image, padding)
        if options.shadow:
            image = add_shadow(image)
        image = apply_background(image, options, notes)
    if options.aspect_ratio != "auto" and options.task not in ("rename", "convert"):
        image = pad_to_aspect_ratio(image, options.aspect_ratio, options)
        notes.append(f"Padded canvas to {options.aspect_ratio} aspect ratio.")
    if options.fit != "none" and options.task not in ("rename", "convert"):
        image, note = fit_image(image, options)
        if note:
            notes.append(note)
    if options.sharpen > 0 and options.task not in ("rename", "convert"):
        image = apply_sharpen(image, options.sharpen)
    if (
        options.auto_contrast
        or options.brightness != 100
        or options.contrast != 100
        or options.saturation != 100
    ) and options.task not in ("rename", "convert"):
        image = apply_adjustments(image, options)
        notes.append("Applied tone & color adjustments.")
    if options.watermark_text.strip() and options.task not in ("rename", "convert"):
        image = apply_watermark(image, options)
        notes.append("Stamped watermark.")
    if options.srgb:
        image, meta, note = to_srgb(image, meta)
        if note:
            notes.append(note)
    if options.format == "jpeg" and image.mode == "RGBA":
        image = _flatten(image, (255, 255, 255))
        notes.append("JPEG has no transparency, so the background is white.")
    return image, meta, notes


def write_outputs(
    image: Image.Image,
    meta: dict,
    dest_dir: Path,
    filename: str,
    options: Options,
) -> tuple[Path, list[str]]:
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = unique_path(dest_dir / filename)
    notes: list[str] = []
    if dest.suffix.lower() == ".svg":
        _write_svg(image, dest, notes)
    else:
        _write_raster(image, dest, meta, options)
    if options.also_webp and dest.suffix.lower() != ".webp":
        sibling = unique_path(dest.with_suffix(".webp"))
        _write_raster(image, sibling, meta, _as_webp(options))
        notes.append(f"Also saved {sibling.name}.")
    return dest, notes


def place_file(source: Path, dest_dir: Path, filename: str, move: bool) -> Path:
    """Copy or rename a file. A file is never written on top of a different one."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    desired = dest_dir / filename
    if desired.resolve() == source.resolve():
        return source
    dest = unique_path(desired)
    if move:
        try:
            source.rename(dest)
        except OSError:
            shutil.copy2(source, dest)
            source.unlink()
    else:
        shutil.copy2(source, dest)
    return dest


def adjust_edge(image: Image.Image, edge: str, fill_holes: bool) -> Image.Image:
    image = image.convert("RGBA")
    alpha = image.getchannel("A")
    if fill_holes and min(alpha.size) >= 5:
        alpha = _fill_holes(alpha)
    if edge == "tight" and min(alpha.size) >= 3:
        alpha = alpha.filter(ImageFilter.MinFilter(3))
    elif edge == "loose" and min(alpha.size) >= 3:
        alpha = alpha.filter(ImageFilter.MaxFilter(3))
    image.putalpha(alpha)
    return image


def crop_to_subject(image: Image.Image, padding: int) -> Image.Image:
    image = image.convert("RGBA")
    mask = image.getchannel("A").point(lambda value: 255 if value > 12 else 0)
    bbox = mask.getbbox()
    if bbox is None:
        return image
    cropped = image.crop(bbox)
    if padding <= 0:
        return cropped
    canvas = Image.new("RGBA", (cropped.width + padding * 2, cropped.height + padding * 2), (0, 0, 0, 0))
    canvas.paste(cropped, (padding, padding), cropped)
    return canvas


def add_shadow(image: Image.Image) -> Image.Image:
    image = image.convert("RGBA")
    radius = max(8, min(48, min(image.size) // 24 or 8))
    blur = image.getchannel("A").filter(ImageFilter.GaussianBlur(radius))
    shift = max(6, min(40, image.height // 30 or 6))
    shifted = Image.new("L", image.size, 0)
    shifted.paste(blur, (0, shift))
    strength = shifted.point(lambda value: int(value * 0.42))
    shadow = Image.new("RGBA", image.size, (0, 0, 0, 0))
    shadow.putalpha(strength)
    return Image.alpha_composite(shadow, image)


def apply_background(image: Image.Image, options: Options, notes: list[str]) -> Image.Image:
    color = _background(options)
    if color is None:
        return image.convert("RGBA")
    return _flatten(image, color)


def fit_image(image: Image.Image, options: Options) -> tuple[Image.Image, str]:
    width, height, note = target_size(
        image.width,
        image.height,
        options.fit,
        options.fit_a,
        options.fit_b,
        options.no_upscale,
    )
    if (width, height) == image.size:
        return image, note
    return image.resize((width, height), Image.Resampling.LANCZOS), note


def to_srgb(image: Image.Image, meta: dict) -> tuple[Image.Image, dict, str]:
    profile = meta.get("icc")
    meta = dict(meta)
    if not profile:
        return image, meta, ""
    try:
        source = ImageCms.ImageCmsProfile(BytesIO(profile))
        target = ImageCms.createProfile("sRGB")
        mode = "RGBA" if image.mode == "RGBA" else "RGB"
        converted = ImageCms.profileToProfile(image, source, target, outputMode=mode)
    except (OSError, ValueError):
        return image, meta, ""
    meta["icc"] = None
    return converted, meta, "Converted the colors to sRGB."


def _write_raster(image: Image.Image, dest: Path, meta: dict, options: Options) -> None:
    suffix = dest.suffix.lower()
    tmp = dest.with_name(dest.name + ".partial")
    save = image
    kwargs: dict = {}
    if suffix in (".jpg", ".jpeg"):
        save = save.convert("RGB")
        kwargs = {"format": "JPEG", "quality": options.quality, "optimize": True}
    elif suffix == ".webp":
        if save.mode not in ("RGB", "RGBA"):
            save = save.convert("RGBA" if "A" in save.getbands() else "RGB")
        kwargs = {"format": "WEBP", "quality": options.quality, "method": 4}
    else:
        if save.mode not in ("RGB", "RGBA"):
            save = save.convert("RGBA" if "A" in save.getbands() else "RGB")
        kwargs = {
            "format": "PNG",
            "compress_level": 1 if save.width * save.height > 20_000_000 else 3,
        }
    if meta.get("icc") and suffix == ".png" and save.mode in ("RGB", "RGBA"):
        kwargs["icc_profile"] = meta["icc"]
    if meta.get("dpi") and suffix != ".webp":
        kwargs["dpi"] = meta["dpi"]
    if options.keep_exif and meta.get("exif") and suffix in (".jpg", ".jpeg", ".webp", ".png"):
        kwargs["exif"] = meta["exif"]
    try:
        try:
            save.save(tmp, **kwargs)
        except (OSError, ValueError):
            kwargs.pop("dpi", None)
            kwargs.pop("icc_profile", None)
            kwargs.pop("exif", None)
            save.save(tmp, **kwargs)
        tmp.replace(dest)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


def _write_svg(image: Image.Image, dest: Path, notes: list[str]) -> None:
    try:
        import vtracer
    except ImportError as exc:
        raise RuntimeError("SVG needs vtracer. Run ./run.sh once so it can install.") from exc
    trace = image.convert("RGBA")
    limit = 1600
    if max(trace.size) > limit:
        trace = trace.copy()
        trace.thumbnail((limit, limit), Image.Resampling.LANCZOS)
        notes.append(f"Traced from a {limit} pixel version.")
    partial = dest.with_name(dest.name + ".partial")
    raster = dest.with_name(dest.name + ".trace.png")
    try:
        trace.save(raster, "PNG")
        vtracer.convert_image_to_svg_py(
            str(raster),
            str(partial),
            colormode="color",
            hierarchical="stacked",
            mode="spline",
            filter_speckle=4,
            color_precision=6,
            layer_difference=16,
            corner_threshold=60,
            length_threshold=4.0,
            max_iterations=10,
            splice_threshold=45,
            path_precision=3,
        )
        with partial.open("rb") as handle:
            head = handle.read(800).lower()
        if partial.stat().st_size < 20 or b"<svg" not in head:
            raise RuntimeError("The SVG trace came out empty.")
        partial.replace(dest)
    except Exception:
        partial.unlink(missing_ok=True)
        raise
    finally:
        raster.unlink(missing_ok=True)


def _fill_holes(alpha: Image.Image) -> Image.Image:
    closed = alpha.filter(ImageFilter.MaxFilter(5)).filter(ImageFilter.MinFilter(5))
    return Image.fromarray(np.maximum(np.asarray(alpha), np.asarray(closed)), "L")


def _flatten(image: Image.Image, color: tuple[int, int, int]) -> Image.Image:
    if image.mode != "RGBA":
        return image.convert("RGB")
    base = Image.new("RGB", image.size, color)
    base.paste(image, mask=image.getchannel("A"))
    return base


def _background(options: Options) -> tuple[int, int, int] | None:
    if options.background == "white":
        return (255, 255, 255)
    if options.background == "paper":
        return PAPER
    if options.background == "custom":
        return _rgb(options.background_hex)
    return None


def _as_webp(options: Options) -> Options:
    copy = Options(**options.to_dict())
    copy.format = "webp"
    copy.also_webp = False
    return copy


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, int(value)))


def _label(value: str, limit: int = 80) -> str:
    text = str(value or "")
    for mark in ("/", "\\", ":", "\x00", "\n", "\r"):
        text = text.replace(mark, "")
    return text.strip()[:limit]


def _hex(value: str) -> str:
    text = str(value or "").strip()
    if not text.startswith("#"):
        text = f"#{text}"
    raw = text[1:]
    if len(raw) == 3 and all(character in "0123456789abcdefABCDEF" for character in raw):
        raw = "".join(character * 2 for character in raw)
    if len(raw) == 6 and all(character in "0123456789abcdefABCDEF" for character in raw):
        return f"#{raw.lower()}"
    return "#ffffff"


def _rgb(value: str) -> tuple[int, int, int]:
    text = _hex(value)[1:]
    return (int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16))
