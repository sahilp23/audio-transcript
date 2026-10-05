"""macOS notifications (e.g. "transcript ready") when running as the Mac app."""

import subprocess

from . import config


def _quote(text: str) -> str:
    """AppleScript string literal."""
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def send(message: str, title: str = "Concall Player") -> None:
    if not (config.APP_MODE and config.IS_MAC):
        return
    script = f"display notification {_quote(message[:200])} with title {_quote('Concall Player')} subtitle {_quote(title)}"
    try:
        subprocess.Popen(["/usr/bin/osascript", "-e", script], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        pass
