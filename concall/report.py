"""'Report a problem': builds a bug report and a pre-filled GitHub issue link.

The repository is public, so everything that goes into the issue is redacted:
API tokens are masked and the Mac's home folder (which contains your user name)
is replaced with "~". The full report is also saved locally.
"""

import platform
import re
import time
import urllib.parse
from pathlib import Path

from . import __version__, components, config, diarize

LOG_FILE = Path.home() / "Library" / "Logs" / "Concall Player" / "app.log"
MAX_BODY = 5500  # characters; GitHub's new-issue links stop working when the URL gets too long


def redact(text: str) -> str:
    text = re.sub(r"hf_[A-Za-z0-9]{6,}", "hf_***", text)
    text = re.sub(r"gsk_[A-Za-z0-9]{6,}", "gsk_***", text)
    # Gladia keys have no recognisable prefix: mask the connected key itself.
    gkey = config.gladia_key()
    if gkey:
        text = text.replace(gkey, "<gladia key>")
    home = str(Path.home())
    if home and home != "/":
        text = text.replace(home, "~")
    return re.sub(r"/Users/[^/\s]+", "/Users/<you>", text)


def _log_tail(lines: int) -> str:
    try:
        content = LOG_FILE.read_text(errors="replace").splitlines()
    except FileNotFoundError:
        return "(no log file)"
    return "\n".join(content[-lines:])


def _environment() -> str:
    comp = components.status()
    settings = config.load_settings()
    mac = platform.mac_ver()[0] or platform.platform()
    rows = [
        f"- App version: {__version__} ({'Mac app' if config.APP_MODE else 'from source'})",
        f"- macOS: {mac}, {platform.machine()}, {config.total_ram_gb():.0f} GB RAM",
        f"- Cloud transcription: Gladia {'connected' if config.gladia_key() else 'not connected'}, "
        f"Groq {'connected' if config.groq_key() else 'not connected'}",
        f"- Mac mode: {settings['mac_mode']} (gentle={config.gentle_mode()})",
        f"- Speaker separation: {diarize.available() or 'ready'}",
        "- Components: " + ", ".join(
            f"{k}={'installed' if v.get('installed') else v.get('state')}" + (f" (error: {v['error']})" if v.get("error") else "")
            for k, v in comp.items()
        ),
    ]
    return "\n".join(rows)


def build(description: str, context: dict) -> dict:
    title_src = (description or context.get("error") or "Problem report").strip().splitlines()[0]
    title = redact(f"[App] {title_src[:90]}")
    ctx_lines = [f"- {k}: {v}" for k, v in context.items() if v not in (None, "", [], {})]
    head = "\n".join([
        "### What happened",
        (description or "(no description)").strip(),
        "",
        "### Details",
        *ctx_lines,
        _environment(),
    ])
    full = redact(head + "\n\n### Log (last 400 lines)\n```\n" + _log_tail(400) + "\n```\n")

    reports = config.SUPPORT_DIR / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    path = reports / f"report-{time.strftime('%Y%m%d-%H%M%S')}.md"
    path.write_text(full)

    # The issue gets as much of the log as fits in a link.
    head = redact(head)
    budget = MAX_BODY - len(head) - 200
    log_lines = redact(_log_tail(120)).splitlines()
    while log_lines and sum(len(line) + 1 for line in log_lines) > budget:
        log_lines.pop(0)
    body = head + "\n\n### Log (most recent lines)\n```\n" + "\n".join(log_lines) + "\n```\n" + \
        "\n_Sent from Concall Player's “Report a problem”._"
    query = urllib.parse.urlencode({"title": title, "body": body, "labels": "bug"})
    return {"url": f"https://github.com/{config.GITHUB_REPO}/issues/new?{query}", "path": str(path), "title": title}
