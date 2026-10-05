import json
from pathlib import Path

from app.config import SETTINGS_PATH
from app.finish import Options


class Settings:
    def __init__(self, path: Path = SETTINGS_PATH) -> None:
        self.path = path
        self.output_dir = Path.home() / "Pictures" / "Image Utilities"
        self.last = Options().to_dict()
        self.load()

    def load(self) -> None:
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text())
        except (OSError, json.JSONDecodeError):
            return
        raw = data.get("output_dir")
        if isinstance(raw, str) and raw.strip():
            self.output_dir = Path(raw)
        if isinstance(data.get("last"), dict):
            self.last = Options.from_dict(data["last"]).to_dict()

    def set_output_dir(self, path: Path) -> None:
        self.output_dir = path
        self._write()

    def set_last(self, options: Options) -> None:
        self.last = options.to_dict()
        self._write()

    def _write(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"output_dir": str(self.output_dir), "last": self.last}
        self.path.write_text(json.dumps(payload, indent=2) + "\n")
