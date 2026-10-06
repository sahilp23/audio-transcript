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
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default


def write_json(path: Path, data: Any) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    os.replace(tmp, path)


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
