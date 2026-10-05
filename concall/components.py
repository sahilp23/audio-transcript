"""Installs the heavy optional parts in the background, with progress for the UI.

  engine         speech-to-text libraries (mlx-whisper on Apple Silicon)
  speech_model   the Whisper model weights (~1.6 GB, downloaded once)
  speakers       speaker separation (pyannote.audio), installed when you connect Hugging Face
  speaker_model  pyannote model weights (needs the Hugging Face token)

The Mac app ships only a small core so it opens quickly; this module fetches the
rest on first launch. Package installs use the `uv` binary bundled in the app
(or pip when running from source). Each component remembers the hash of its
requirements file, so an app update that changes them reinstalls automatically.
"""

import hashlib
import importlib
import importlib.util
import re
import subprocess
import sys
import threading
import time
import traceback
from pathlib import Path
from typing import Callable, Optional

from . import config

REQ_DIR = Path(__file__).resolve().parent.parent

PACKAGES = {
    "engine": {
        "title": "Speech engine",
        "req": "requirements-engine.txt",
        "modules": ["mlx_whisper"] if config.IS_APPLE_SILICON else ["faster_whisper"],
    },
    "speakers": {
        "title": "Speaker separation",
        "req": "requirements-diarization.txt",
        "modules": ["pyannote.audio"],
    },
}


class Task:
    def __init__(self, title: str):
        self.title = title
        self.state = "idle"  # idle | running | done | error
        self.message = ""
        self.progress: Optional[float] = None
        self.error: Optional[str] = None
        self.thread: Optional[threading.Thread] = None

    def as_dict(self) -> dict:
        return {"state": self.state, "message": self.message, "progress": self.progress, "error": self.error}


_tasks: dict[str, Task] = {
    "engine": Task("Speech engine"),
    "speech_model": Task("Speech model"),
    "speakers": Task("Speaker separation"),
    "speaker_model": Task("Speaker model"),
}
_install_lock = threading.Lock()  # one package install at a time


def _stamp_path(name: str) -> Path:
    return config.SUPPORT_DIR / "components" / f"{name}.stamp"


def _req_hash(name: str) -> str:
    req = REQ_DIR / PACKAGES[name]["req"]
    return hashlib.sha256(req.read_bytes()).hexdigest()[:16] if req.exists() else "none"


def _importable(module: str) -> bool:
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        return False


def package_installed(name: str) -> bool:
    if not all(_importable(m) for m in PACKAGES[name]["modules"]):
        return False
    stamp = _stamp_path(name)
    # Running from source without a stamp: trust what's importable.
    if not stamp.exists():
        return not config.UV
    return stamp.read_text().strip() == _req_hash(name)


def _run_install(name: str, task: Task) -> None:
    req = REQ_DIR / PACKAGES[name]["req"]
    if config.UV:
        cmd = [config.UV, "pip", "install", "--python", sys.executable, "-r", str(req)]
    else:
        cmd = [sys.executable, "-m", "pip", "install", "-r", str(req)]
    task.message = "Starting…"
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
    tail: list[str] = []
    for line in proc.stdout:  # type: ignore[union-attr]
        line = line.strip()
        if not line:
            continue
        tail = (tail + [line])[-30:]
        print(f"[{name}] {line}", flush=True)
        m = re.match(r"(Downloading|Downloaded|Prepared|Installed|Resolved|Building|Built)\b(.*)", line)
        if m:
            task.message = (m.group(1) + m.group(2))[:120]
    if proc.wait() != 0:
        raise RuntimeError("Install failed: " + " | ".join(tail[-4:]))
    importlib.invalidate_caches()
    stamp = _stamp_path(name)
    stamp.parent.mkdir(parents=True, exist_ok=True)
    stamp.write_text(_req_hash(name))


def _start(key: str, work: Callable[[Task], None]) -> Task:
    task = _tasks[key]
    if task.state == "running":
        return task
    task.state, task.error, task.progress, task.message = "running", None, None, "Starting…"

    def run():
        try:
            work(task)
            task.state, task.message, task.progress = "done", "Ready", 1.0
        except Exception as exc:
            traceback.print_exc()
            task.state, task.error = "error", str(exc)[:500]
            task.message = "Failed"

    task.thread = threading.Thread(target=run, daemon=True, name=f"setup-{key}")
    task.thread.start()
    return task


def install(name: str) -> Task:
    def work(task: Task):
        with _install_lock:
            if not package_installed(name):
                _run_install(name, task)

    return _start(name, work)


# ---------------------------------------------------------------- model files


def _hf_cache_dir(repo: str) -> Path:
    from huggingface_hub import constants

    return Path(constants.HF_HUB_CACHE) / ("models--" + repo.replace("/", "--"))


def model_downloaded(repo: str, token: Optional[str] = None) -> bool:
    try:
        from huggingface_hub import snapshot_download

        snapshot_download(repo, local_files_only=True, token=token or None)
        return True
    except Exception:
        return False


def _download(repo: str, task: Task, token: Optional[str] = None) -> None:
    from huggingface_hub import HfApi, snapshot_download

    total = 0
    try:
        info = HfApi().model_info(repo, files_metadata=True, token=token or None)
        total = sum((s.size or 0) for s in info.siblings or [])
    except Exception:
        pass
    done = threading.Event()
    error: list[BaseException] = []

    def fetch():
        try:
            snapshot_download(repo, token=token or None)
        except BaseException as exc:  # noqa: BLE001
            error.append(exc)
        finally:
            done.set()

    threading.Thread(target=fetch, daemon=True).start()
    blobs = _hf_cache_dir(repo) / "blobs"
    while not done.wait(1.0):
        if total and blobs.exists():
            have = sum(f.stat().st_size for f in blobs.iterdir() if f.is_file())
            task.progress = min(0.99, have / total)
            task.message = f"Downloading {have / 1e9:.2f} of {total / 1e9:.2f} GB"
        else:
            task.message = "Downloading…"
    if error:
        raise RuntimeError(f"Download failed: {error[0]}. Check your internet connection.")


def speech_model_repo() -> Optional[str]:
    """The Hugging Face repo of the Whisper model we pre-download (mlx only)."""
    from . import asr

    return config.MLX_MODEL if asr.pick_engine() == "mlx" else None


def download_speech_model() -> Task:
    def work(task: Task):
        repo = speech_model_repo()
        if repo and not model_downloaded(repo):
            _download(repo, task)

    return _start("speech_model", work)


def download_speaker_model() -> Task:
    def work(task: Task):
        from . import diarize

        task.message = "Downloading speaker models…"
        diarize.load_pipeline()  # downloads and caches the weights

    return _start("speaker_model", work)


# ---------------------------------------------------------------- waiting helpers


def wait(task: Task, on_update: Optional[Callable[[Task], None]] = None) -> None:
    while task.state == "running":
        if on_update:
            on_update(task)
        time.sleep(1.0)
    if task.state == "error":
        raise RuntimeError(f"{task.title} setup failed: {task.error}. Open Settings to retry.")


def ensure_speech_ready(on_update: Optional[Callable[[str, Optional[float]], None]] = None) -> None:
    """Block until the speech engine and model are installed (used before transcribing)."""
    cb = (lambda t: on_update(f"Setting up speech engine (first time only): {t.message}", t.progress)) if on_update else None
    if not package_installed("engine"):
        wait(install("engine"), cb)
    repo = speech_model_repo()
    if repo and not model_downloaded(repo):
        cb2 = (lambda t: on_update(f"Downloading speech model (first time only): {t.message}", t.progress)) if on_update else None
        wait(download_speech_model(), cb2)


def ensure_speakers_ready(on_update: Optional[Callable[[str, Optional[float]], None]] = None) -> None:
    cb = (lambda t: on_update(f"Setting up speaker separation: {t.message}", t.progress)) if on_update else None
    if not package_installed("speakers"):
        wait(install("speakers"), cb)


def status() -> dict:
    repo = speech_model_repo()
    out = {}
    for key in ("engine", "speakers"):
        out[key] = {**_tasks[key].as_dict(), "installed": package_installed(key)}
    out["speech_model"] = {**_tasks["speech_model"].as_dict(), "repo": repo,
                           "installed": (model_downloaded(repo) if repo else out["engine"]["installed"])}
    out["speaker_model"] = {**_tasks["speaker_model"].as_dict()}
    return out


def auto_setup() -> None:
    """On app launch: fetch anything missing, in order, without blocking the UI."""

    def run():
        try:
            if not package_installed("engine"):
                wait(install("engine"))
            repo = speech_model_repo()
            if repo and not model_downloaded(repo):
                wait(download_speech_model())
            if config.hf_ready() and config.diarization_enabled() and not package_installed("speakers"):
                wait(install("speakers"))
        except Exception:
            traceback.print_exc()

    threading.Thread(target=run, daemon=True, name="auto-setup").start()
