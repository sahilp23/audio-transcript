"""Mac app entry point: runs the local server and shows it in a native window.

Started by the launcher inside "Concall Player.app". Set CONCALL_HEADLESS=1 to run
only the server (used by the automated build test).
"""

import os
import socket
import threading
import time
import traceback
import urllib.request
import webbrowser
from pathlib import Path

import uvicorn

from . import __version__, components, config, media


def _free_port(preferred: int) -> int:
    for port in (preferred, 0):
        with socket.socket() as s:
            try:
                s.bind((config.HOST, port))
                return s.getsockname()[1]
            except OSError:
                continue
    raise RuntimeError("No free port")


def _wait_until_up(url: str, timeout: float = 60) -> None:
    end = time.time() + timeout
    while time.time() < end:
        try:
            urllib.request.urlopen(url + "/api/ping", timeout=2)
            return
        except Exception:
            time.sleep(0.2)
    raise RuntimeError("The app's server didn't start")


def _mark_started() -> None:
    """Tell the launcher this version started fine (it rolls back otherwise)."""
    (config.SUPPORT_DIR / "app" / "starting").unlink(missing_ok=True)


def _set_app_name() -> None:
    # The window runs inside Python; make the menu bar say "Concall Player".
    try:
        from Foundation import NSBundle

        info = NSBundle.mainBundle().localizedInfoDictionary() or NSBundle.mainBundle().infoDictionary()
        info["CFBundleName"] = "Concall Player"
    except Exception:
        pass


def main() -> None:
    print(f"Concall Player {__version__} starting (data: {config.DATA_DIR})", flush=True)
    config.SUPPORT_DIR.mkdir(parents=True, exist_ok=True)
    try:
        media.ensure_ffmpeg()
    except RuntimeError as exc:
        print(f"WARNING: {exc}", flush=True)

    port = _free_port(config.PORT)
    url = f"http://{config.HOST}:{port}"
    server = uvicorn.Server(uvicorn.Config("concall.server:app", host=config.HOST, port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True, name="server")
    thread.start()
    _wait_until_up(url)
    print(f"Server up at {url}", flush=True)

    if config.APP_MODE:
        components.auto_setup()

    if os.environ.get("CONCALL_HEADLESS") == "1":
        _mark_started()
        thread.join()
        return

    try:
        _set_app_name()
        import webview

        icon = os.environ.get("CONCALL_ICON")
        webview.create_window(
            "Concall Player", url, width=1380, height=900, min_size=(520, 480), text_select=True,
            background_color="#f6f6f8",
        )
        _mark_started()
        webview.start(icon=icon if icon and Path(icon).exists() else None, private_mode=False,
                      storage_path=str(config.SUPPORT_DIR / "webview"))
    except Exception:
        # No native window available: use the default browser instead.
        traceback.print_exc()
        _mark_started()
        webbrowser.open(url)
        thread.join()
        return
    os._exit(0)  # window closed: stop the server and any background work


if __name__ == "__main__":
    main()
