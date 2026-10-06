"""File-based storage: one folder per call under DATA_DIR/calls/<id>/.

Files in a call folder:
  meta.json      company, period, date, status, progress, ...
  audio.<ext>    the uploaded recording (played in the browser)
  asr.json       raw speech-to-text words with timings (kept so re-alignment is cheap)
  diar.json      speaker-separation segments (optional)
  official.json  parsed company transcript (optional, can arrive days later)
  doc.json       final transcript shown in the player
  user.json      your bookmarks, notes, speaker renames, last position
"""

import json
import os
import re
import secrets
import threading
import time
from pathlib import Path
from typing import Any

from . import config

_lock = threading.RLock()

# Website mode: drivesync.py plugs in here so call files are kept in Google Drive.
# It provides has(path), fetch(path), push(path), deleted(path), deleted_call(call_id).
remote = None


def calls_dir() -> Path:
    d = config.DATA_DIR / "calls"
    d.mkdir(parents=True, exist_ok=True)
    return d


def call_dir(call_id: str) -> Path:
    if not re.fullmatch(r"[a-z0-9-]{4,80}", call_id):
        raise KeyError(call_id)
    return calls_dir() / call_id


def new_call_id(company: str, period: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", f"{company} {period}".lower()).strip("-")[:50] or "call"
    return f"{slug}-{secrets.token_hex(3)}"


def read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(config.read_text(path))
    except FileNotFoundError:
        if remote is not None and remote.fetch(path):
            return json.loads(config.read_text(path))
        return default


def write_json(path: Path, data: Any) -> None:
    # A temp name per write, so two threads saving the same file never share one.
    tmp = path.with_suffix(f"{path.suffix}.{threading.get_ident()}.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    config.replace_file(tmp, path)
    saved(path)


def saved(path: Path) -> None:
    """A call file was written (JSON here, or audio by ffmpeg): keep the Drive copy up to date."""
    if remote is not None:
        remote.push(path)


def exists(path: Path) -> bool:
    """The file exists here or (website mode) in Google Drive."""
    return path.exists() or (remote is not None and remote.has(path))


def ensure_local(path: Path) -> Path:
    """Make sure a call file is on this computer (website mode downloads it from Drive)."""
    if not path.exists() and remote is not None:
        remote.fetch(path)
    return path


def delete_file(path: Path) -> None:
    path.unlink(missing_ok=True)
    if remote is not None:
        remote.deleted(path)


def delete_call(call_id: str) -> None:
    import shutil

    shutil.rmtree(call_dir(call_id), ignore_errors=True)
    if remote is not None:
        remote.deleted_call(call_id)


def get_meta(call_id: str) -> dict:
    meta = read_json(call_dir(call_id) / "meta.json")
    if meta is None:
        raise KeyError(call_id)
    return meta


def update_meta(call_id: str, **fields: Any) -> dict:
    with _lock:
        meta = get_meta(call_id)
        meta.update(fields)
        meta["updated_at"] = time.time()
        write_json(call_dir(call_id) / "meta.json", meta)
        return meta


def create_call(company: str, period: str, date: str, audio_name: str) -> dict:
    call_id = new_call_id(company, period)
    d = call_dir(call_id)
    d.mkdir(parents=True)
    meta = {
        "id": call_id,
        "company": company.strip(),
        "period": period.strip(),
        "date": date,
        "audio_file": audio_name,
        "status": "queued",
        "stage": "Waiting",
        "progress": 0.0,
        "error": None,
        "has_official": False,
        "created_at": time.time(),
        "updated_at": time.time(),
    }
    write_json(d / "meta.json", meta)
    return meta


def list_calls() -> list[dict]:
    out = []
    for d in calls_dir().iterdir():
        meta = read_json(d / "meta.json")
        if meta:
            out.append(meta)
    out.sort(key=lambda m: (m.get("date") or "", m.get("created_at", 0)), reverse=True)
    return out


def get_user(call_id: str) -> dict:
    return read_json(call_dir(call_id) / "user.json", {}) or {}


def update_user(call_id: str, patch: dict) -> dict:
    with _lock:
        data = get_user(call_id)
        data.update(patch)
        write_json(call_dir(call_id) / "user.json", data)
        return data
