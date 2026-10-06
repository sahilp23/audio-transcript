"""Website mode: keep calls in your Google Drive.

The server's own disk is temporary (the free host wipes it when the site goes
to sleep), so Google Drive is where calls really live:

  My Drive / Concall Player /          (created by the website)
      settings.json                    your connected services (Gladia, Groq)
      <call id> /                      one folder per call
          meta.json, user.json, doc.json, asr.json, audio.mp3, ...

The rest of the app keeps reading and writing files in its local folder as
usual (store.py). This module mirrors them:
  * on wake-up it lists everything in Drive in one go and downloads each call's
    meta.json and user.json (small), so the library shows straight away;
  * other files are downloaded the first time they're needed (store.read_json /
    store.ensure_local ask us);
  * every file the app writes is uploaded in the background a moment later;
  * deletions are passed on.
"""

import queue
import sys
import threading
import time
import traceback
from pathlib import Path
from typing import Optional

from . import config, gdrive

ROOT_NAME = "Concall Player"
ROOT_PROP = {"concall": "root"}
EAGER = ("meta.json", "user.json")  # downloaded on wake-up for every call
SKIP_SUFFIXES = (".tmp", ".download", ".part.m4a")
SKIP_NAMES = {"audio16k.wav"}

_lock = threading.RLock()
_folder_lock = threading.Lock()
_drive: Optional[gdrive.Drive] = None
_ready = threading.Event()
_root: Optional[str] = None
_settings_id: Optional[str] = None
_folders: dict[str, str] = {}  # call id -> Drive folder id
_files: dict[str, dict[str, str]] = {}  # call id -> {file name -> Drive file id}
_pending: "queue.Queue[str]" = queue.Queue()
_queued: set[str] = set()
_worker: Optional[threading.Thread] = None
_error: Optional[str] = None
_email = ""
_loading = False


# ---------- connection ----------

def connect(refresh_token: str, email: str = "") -> None:
    """Called on every signed-in request (cheap once connected).

    Each browser you sign in on has its own Google token; any of them works, so the
    first one is kept (switching would reload everything). A new token is only taken
    over when the current one stopped working. A failed load is retried."""
    global _drive, _email, _loading
    with _lock:
        same_user = _drive is not None and _email == email
        token_broken = bool(_error and "sign in again" in _error)
        if same_user and not token_broken:
            if _ready.is_set() or _loading:
                return
        else:
            _drive = gdrive.Drive(config.GOOGLE_CLIENT_ID, config.GOOGLE_CLIENT_SECRET, refresh_token)
            _email = email
            _ready.clear()
        if _loading:
            return
        _loading = True
    _install_hooks()
    threading.Thread(target=_load, daemon=True, name="drive-load").start()


def connected() -> bool:
    return _drive is not None


def ready(timeout: Optional[float] = None) -> bool:
    return _ready.wait(timeout)


def status() -> dict:
    return {"connected": _drive is not None, "ready": _ready.is_set(), "error": _error,
            "uploads_pending": len(_queued)}


def drive() -> gdrive.Drive:
    if _drive is None:
        raise gdrive.DriveError("Not signed in to Google")
    return _drive


def access_token() -> str:
    return drive().access_token()


def _load() -> None:
    """Find (or create) the Concall Player folder, index everything, pull the small files."""
    global _root, _settings_id, _error, _loading
    try:
        d = drive()
        files = d.list_files()
        roots = [f for f in files if f.get("mimeType") == gdrive.FOLDER and (f.get("appProperties") or {}).get("concall") == "root"]
        root = roots[0]["id"] if roots else d.create_folder(ROOT_NAME, props=ROOT_PROP)
        folders, by_folder, settings_id = {}, {}, None
        for f in files:
            props = f.get("appProperties") or {}
            if f.get("mimeType") == gdrive.FOLDER and props.get("concall") == "call" and root in (f.get("parents") or []):
                folders[props.get("call") or f["name"]] = f["id"]
        folder_to_call = {v: k for k, v in folders.items()}
        for f in files:
            if f.get("mimeType") == gdrive.FOLDER:
                continue
            parent = (f.get("parents") or [None])[0]
            if parent == root and f["name"] == "settings.json":
                settings_id = f["id"]
            elif parent in folder_to_call:
                by_folder.setdefault(folder_to_call[parent], {})[f["name"]] = f["id"]
        with _lock:
            _root, _settings_id = root, settings_id
            _folders.clear()
            _folders.update(folders)
            _files.clear()
            _files.update(by_folder)
        if settings_id:
            d.download(settings_id, config.SETTINGS_FILE)
        calls = config.DATA_DIR / "calls"
        for call_id, names in by_folder.items():
            for name in EAGER:
                if name in names and not (calls / call_id / name).exists():
                    d.download(names[name], calls / call_id / name)
        _error = None
        _ready.set()
        from . import pipeline

        pipeline.resume_interrupted()
    except gdrive.AuthExpired as exc:
        _error = str(exc)
    except Exception as exc:
        traceback.print_exc()
        _error = f"Couldn't load your calls from Google Drive: {exc}"
    finally:
        _loading = False


# ---------- mapping local paths <-> Drive ----------

def _split(path: Path) -> Optional[tuple[str, str]]:
    """Local call file -> (call id, file name), or None if it isn't a call file."""
    try:
        rel = Path(path).resolve().relative_to((config.DATA_DIR / "calls").resolve())
    except ValueError:
        return None
    parts = rel.parts
    return (parts[0], parts[1]) if len(parts) == 2 else None


def _syncable(name: str) -> bool:
    return name not in SKIP_NAMES and not name.endswith(SKIP_SUFFIXES)


def has(path: Path) -> bool:
    key = _split(path)
    return bool(key and key[1] in _files.get(key[0], {}))


def fetch(path: Path) -> bool:
    """Download a call file that isn't on this server yet. True if it now exists locally."""
    key = _split(path)
    if not key or _drive is None:
        return False
    file_id = _files.get(key[0], {}).get(key[1])
    if not file_id:
        return False
    _drive.download(file_id, Path(path))
    return True


def folder_for(call_id: str) -> str:
    """The call's Drive folder (created if needed)."""
    if call_id in _folders:
        return _folders[call_id]
    if not ready(60) or _root is None:
        raise gdrive.DriveError(_error or "Google Drive isn't ready yet")
    with _folder_lock:  # one at a time, so a call never gets two folders
        if call_id not in _folders:
            folder = drive().create_folder(call_id, _root, {"concall": "call", "call": call_id})
            with _lock:
                _folders[call_id] = folder
                _files.setdefault(call_id, {})
        return _folders[call_id]


def register(call_id: str, name: str, file_id: str) -> None:
    """A file was put into Drive directly (e.g. uploaded by the browser)."""
    with _lock:
        _files.setdefault(call_id, {})[name] = file_id


def rescan_call(call_id: str) -> int:
    """Re-read one call folder from Drive (after an import). Returns the number of files."""
    folder = folder_for(call_id)
    files = drive().list_files(f"'{folder}' in parents and trashed = false")
    with _lock:
        _files[call_id] = {f["name"]: f["id"] for f in files if f.get("mimeType") != gdrive.FOLDER}
    calls = config.DATA_DIR / "calls"
    for name in EAGER:
        if name in _files[call_id]:
            drive().download(_files[call_id][name], calls / call_id / name)
    return len(files)


# ---------- uploads ----------

def push(path: Path) -> None:
    """Upload this local file to Drive soon (writes in quick succession are combined)."""
    path = Path(path)
    if path != config.SETTINGS_FILE:
        key = _split(path)
        if not key or not _syncable(key[1]):
            return
    p = str(path)
    with _lock:
        if p in _queued:
            return
        _queued.add(p)
    _pending.put(p)
    _ensure_worker()


def _ensure_worker() -> None:
    global _worker
    with _lock:
        if _worker is None or not _worker.is_alive():
            _worker = threading.Thread(target=_upload_loop, daemon=True, name="drive-upload")
            _worker.start()


def _upload_loop() -> None:
    while True:
        p = _pending.get()
        time.sleep(0.5)  # let a burst of writes to the same file settle
        with _lock:
            _queued.discard(p)
        try:
            _upload(Path(p))
        except Exception as exc:
            traceback.print_exc()
            print(f"[drive] upload of {p} failed, retrying later: {exc}", flush=True)
            time.sleep(10)
            push(Path(p))


def _upload(path: Path) -> None:
    global _settings_id
    if not path.exists():
        return
    ready(120)
    d = drive()
    if path == config.SETTINGS_FILE:
        if _root is None:
            return
        _settings_id = d.upload_file(path, "settings.json", _root, {"concall": "settings"}, file_id=_settings_id)
        return
    call_id, name = _split(path)
    folder = folder_for(call_id)
    file_id = _files.get(call_id, {}).get(name)
    new_id = d.upload_file(path, name, folder, {"concall": "file", "call": call_id}, file_id=file_id)
    with _lock:
        _files.setdefault(call_id, {})[name] = new_id


def flush(timeout: float = 60) -> bool:
    """Wait until queued uploads are done (tests, shutdown)."""
    end = time.time() + timeout
    while time.time() < end:
        if not _queued and _pending.empty():
            return True
        time.sleep(0.1)
    return False


# ---------- deletions ----------

def deleted(path: Path) -> None:
    key = _split(path)
    if not key or _drive is None:
        return
    with _lock:
        file_id = _files.get(key[0], {}).pop(key[1], None)
    if file_id:
        threading.Thread(target=_drive.delete, args=(file_id,), daemon=True).start()


def deleted_call(call_id: str) -> None:
    if _drive is None:
        return
    with _lock:
        folder = _folders.pop(call_id, None)
        _files.pop(call_id, None)
    if folder:
        _drive.delete(folder)


def call_ids() -> list[str]:
    return list(_folders)


# ---------- wiring ----------

_hooked = False


def _install_hooks() -> None:
    global _hooked
    if _hooked:
        return
    from . import store

    store.remote = sys.modules[__name__]
    config.on_settings_saved.append(lambda: push(config.SETTINGS_FILE))
    _hooked = True
