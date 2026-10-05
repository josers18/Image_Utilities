from pathlib import Path

from app.config import IMAGE_SUFFIXES, MAX_BATCH


def output_name(stem: str, task: str, scale: int, suffix: str = ".png") -> str:
    """Build the file name written for one source file."""
    if not suffix.startswith("."):
        suffix = f".{suffix}"
    if task in ("rename", "convert"):
        return f"{stem}{suffix}"
    parts = [stem]
    if task in ("cutout", "both"):
        parts.append("cutout")
    if task in ("upscale", "both"):
        parts.append(f"x{scale}")
    if task == "resize":
        parts.append("resized")
    return ".".join(parts) + suffix


def unique_path(path: Path) -> Path:
    """Return `path`, or `path` with -2, -3, … inserted before the suffix."""
    if not path.exists():
        return path
    n = 2
    while True:
        candidate = path.with_name(f"{path.stem}-{n}{path.suffix}")
        if not candidate.exists():
            return candidate
        n += 1


def format_bytes(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.0f} KB"
    return f"{size / (1024 * 1024):.1f} MB"


def safe_filename(name: str) -> str:
    cleaned = Path(name or "").name.replace("\x00", "").strip()
    if not cleaned or cleaned.startswith("."):
        return "image"
    return cleaned


def list_images(folder: Path, subfolders: bool, limit: int = MAX_BATCH) -> tuple[list[Path], bool]:
    """Return image files in folder order, and whether the limit cut the list off."""
    found: list[Path] = []
    if subfolders:
        candidates = folder.rglob("*")
    else:
        candidates = folder.glob("*")
    for path in candidates:
        if not path.is_file():
            continue
        if path.name.startswith("."):
            continue
        if path.suffix.lower() not in IMAGE_SUFFIXES:
            continue
        found.append(path)
    found.sort(key=lambda path: str(path).lower())
    truncated = len(found) > limit
    return found[:limit], truncated
