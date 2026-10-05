from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VAR = ROOT / "var"
MODELS = ROOT / "models"
INBOX = VAR / "inbox"
PREVIEWS = VAR / "previews"
SETTINGS_PATH = VAR / "settings.json"

HOST = "127.0.0.1"
PORT_START = 8765

# A 12 megapixel photo at 4× lands near 200 megapixels. Past this, saving
# and previewing stops being practical on a laptop.
MAX_EDGE = 20000
MAX_PIXELS = 250_000_000
MAX_BATCH = 200

IMAGE_SUFFIXES = {
    ".jpg",
    ".jpeg",
    ".jpe",
    ".jfif",
    ".png",
    ".webp",
    ".gif",
    ".tif",
    ".tiff",
    ".bmp",
    ".heic",
    ".heif",
    ".avif",
}
