"""Background processing: audio prep -> speech-to-text -> speakers -> transcript doc.

One job runs at a time (a laptop can only transcribe one call efficiently).
Intermediate results are cached, so attaching an official transcript later only
re-runs the cheap alignment step.
"""

import json
import queue
import shutil
import subprocess
import threading
import traceback
from pathlib import Path

from . import asr, diarize, store, structure

BROWSER_AUDIO = {".mp3", ".m4a", ".aac", ".mp4", ".wav", ".ogg", ".oga", ".webm", ".flac", ".opus"}

_jobs: "queue.Queue[str]" = queue.Queue()
_queued: set[str] = set()
_qlock = threading.Lock()
_build_locks: dict[str, threading.Lock] = {}


def ffprobe_duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout
    return float(json.loads(out)["format"]["duration"])


def _ffmpeg(*args: str) -> None:
    proc = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args], capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError("ffmpeg failed: " + proc.stderr.strip()[-500:])


def enqueue(call_id: str) -> None:
    with _qlock:
        if call_id in _queued:
            return
        _queued.add(call_id)
    store.update_meta(call_id, status="queued", stage="Waiting in queue", error=None)
    _jobs.put(call_id)


def start_worker() -> None:
    if shutil.which("ffmpeg") is None:
        print("WARNING: ffmpeg not found. Install it with: brew install ffmpeg")
    threading.Thread(target=_worker, daemon=True, name="concall-worker").start()
    # Resume anything interrupted by a restart.
    for meta in store.list_calls():
        if meta.get("status") in ("queued", "processing"):
            enqueue(meta["id"])


def _worker() -> None:
    while True:
        call_id = _jobs.get()
        try:
            process(call_id)
        except Exception as exc:  # keep the worker alive
            traceback.print_exc()
            try:
                store.update_meta(call_id, status="error", error=str(exc), stage="Failed")
            except KeyError:
                pass
        finally:
            with _qlock:
                _queued.discard(call_id)


def process(call_id: str) -> None:
    d = store.call_dir(call_id)
    meta = store.update_meta(call_id, status="processing", stage="Preparing audio", progress=0.02, error=None, warnings=[])
    audio = d / meta["audio_file"]
    warnings: list[str] = []

    duration = ffprobe_duration(audio)
    play_file = meta["audio_file"]
    if audio.suffix.lower() not in BROWSER_AUDIO:
        play_file = "play.m4a"
        _ffmpeg("-i", str(audio), "-vn", "-ac", "1", "-c:a", "aac", "-b:a", "96k", str(d / play_file))
    store.update_meta(call_id, duration=duration, play_file=play_file)

    wav = d / "audio16k.wav"
    asr_path = d / "asr.json"
    diar_path = d / "diar.json"
    official = store.read_json(d / "official.json")

    try:
        if not asr_path.exists() or (not diar_path.exists() and not official and diarize.available() is None):
            _ffmpeg("-i", str(audio), "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(wav))

        if not asr_path.exists():
            engine = asr.pick_engine()
            store.update_meta(call_id, stage=f"Transcribing ({engine})", progress=0.05)
            names = [t["speaker"] for t in official["turns"]] if official else None
            prompt = asr.build_prompt(meta.get("company", ""), list(dict.fromkeys(names)) if names else None)

            def on_progress(p: float) -> None:
                store.update_meta(call_id, progress=round(0.05 + 0.75 * p, 3))

            try:
                result = asr.transcribe(str(wav), duration, prompt, on_progress)
            except Exception as exc:
                raise RuntimeError(
                    f"Speech-to-text failed ({exc}). On the first run the model is downloaded "
                    "from huggingface.co, so check your internet connection and retry."
                ) from exc
            store.write_json(asr_path, result)

        # Speaker separation is only needed when there's no official transcript to name speakers.
        official = store.read_json(d / "official.json")
        if not official and not diar_path.exists():
            reason = diarize.available()
            if reason is None:
                store.update_meta(call_id, stage="Separating speakers", progress=0.82)
                try:
                    store.write_json(diar_path, diarize.diarize(str(wav)))
                except Exception as exc:
                    traceback.print_exc()
                    warnings.append(f"Speaker separation failed: {exc}")
            else:
                warnings.append(f"Speaker separation skipped: {reason}.")
    finally:
        wav.unlink(missing_ok=True)

    store.update_meta(call_id, stage="Building transcript", progress=0.96)
    build_doc(call_id)
    store.update_meta(call_id, status="ready", stage="Ready", progress=1.0, warnings=warnings)


def build_doc(call_id: str) -> dict:
    lock = _build_locks.setdefault(call_id, threading.Lock())
    with lock:
        d = store.call_dir(call_id)
        meta = store.get_meta(call_id)
        asr_data = store.read_json(d / "asr.json")
        if asr_data is None:
            raise RuntimeError("Audio has not been transcribed yet")
        official = store.read_json(d / "official.json")
        duration = meta.get("duration") or (asr_data["words"][-1]["e"] if asr_data["words"] else 0)
        if official and official.get("turns"):
            doc = structure.build_from_official(official, asr_data, duration)
        else:
            doc = structure.build_from_asr(asr_data, store.read_json(d / "diar.json"), duration)
        store.write_json(d / "doc.json", doc)
        store.update_meta(call_id, has_official=bool(official), alignment=doc.get("alignment"))
        return doc


def rebuild_async(call_id: str) -> None:
    """Re-align after an official transcript is attached/removed (seconds, not minutes)."""

    def run():
        try:
            store.update_meta(call_id, stage="Aligning transcript", status="processing", progress=0.97)
            build_doc(call_id)
            store.update_meta(call_id, status="ready", stage="Ready", progress=1.0)
        except Exception as exc:
            traceback.print_exc()
            store.update_meta(call_id, status="error", error=str(exc), stage="Failed")

    meta = store.get_meta(call_id)
    if meta.get("status") in ("queued", "processing") and not (store.call_dir(call_id) / "doc.json").exists():
        return  # the running job will pick the transcript up when it builds the doc
    threading.Thread(target=run, daemon=True).start()
