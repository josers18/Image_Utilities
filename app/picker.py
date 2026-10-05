import subprocess
from pathlib import Path


def choose_files() -> list[Path] | None:
    """Open the macOS file dialog. None means the user cancelled."""
    script = """
    set theFiles to choose file with prompt "Choose images" with multiple selections allowed
    set out to ""
    repeat with f in theFiles
        set out to out & POSIX path of f & linefeed
    end repeat
    return out
    """
    text = _run(script)
    if text is None:
        return None
    return [Path(line) for line in text.splitlines() if line.strip()]


def choose_folder() -> Path | None:
    """Open the macOS folder dialog. None means the user cancelled."""
    script = 'POSIX path of (choose folder with prompt "Choose a folder of images")'
    text = _run(script)
    if text is None:
        return None
    return Path(text.strip())


def _run(script: str) -> str | None:
    result = subprocess.run(
        ["osascript", "-"],
        input=script,
        text=True,
        capture_output=True,
    )
    if result.returncode == 0:
        return result.stdout
    err = (result.stderr or "").strip()
    if result.returncode == 1 or "User canceled" in err or "(-128)" in err:
        return None
    raise RuntimeError(err or "Couldn't open the file dialog.")
