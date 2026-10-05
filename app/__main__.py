import argparse
import logging
import os
import signal
import socket
import threading
import time
import webbrowser

import uvicorn

from app.config import HOST, PORT_START, VAR

_PID = VAR / "app.pid"
_URL = VAR / "app.url"


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Image Utilities on this Mac.")
    parser.add_argument("--port", type=int, default=0, help="Port to listen on. 0 picks a free one.")
    parser.add_argument("--no-browser", action="store_true", help="Don't open the page.")
    args = parser.parse_args()

    # Uvicorn handles the signal, then raises it again with the old action.
    # Clearing the files here still runs when that second signal arrives.
    signal.signal(signal.SIGTERM, _on_signal)
    signal.signal(signal.SIGINT, _on_signal)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    print("Starting Image Utilities…", flush=True)
    from app.server import app

    port = args.port or _free_port(PORT_START)
    url = f"http://{HOST}:{port}"

    config = uvicorn.Config(app, host=HOST, port=port, log_level="info")
    server = uvicorn.Server(config)
    threading.Thread(target=_announce, args=(server, url, not args.no_browser), daemon=True).start()
    try:
        server.run()
    finally:
        _forget()


def _free_port(start: int) -> int:
    for port in range(start, start + 20):
        with socket.socket() as sock:
            try:
                sock.bind((HOST, port))
            except OSError:
                continue
            return port
    raise SystemExit(f"No free port from {start} to {start + 19}.")


def _announce(server: uvicorn.Server, url: str, open_browser: bool) -> None:
    for _ in range(200):
        if server.started:
            _remember(url)
            print(f"Image Utilities is at {url}", flush=True)
            if open_browser:
                webbrowser.open(url)
            return
        time.sleep(0.05)


def _remember(url: str) -> None:
    VAR.mkdir(parents=True, exist_ok=True)
    _write(_URL, url + "\n")
    _write(_PID, f"{os.getpid()}\n")


def _on_signal(signum: int, _frame) -> None:
    _forget()
    signal.signal(signum, signal.SIG_DFL)
    os.kill(os.getpid(), signum)


def _forget() -> None:
    for path in (_PID, _URL):
        try:
            path.unlink()
        except FileNotFoundError:
            pass


def _write(path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


if __name__ == "__main__":
    main()
