"""Background processing: audio prep -> speech-to-text -> speakers -> transcript doc.

Speech-to-text runs in the cloud by default: Gladia first (words and speakers
in one go), then Groq (words only; speakers are then separated on the Mac). If
neither is possible (not connected, offline, free limits reached) the call pauses with status
"needs_input" and the app asks whether to use this Mac instead; the answer is
stored as meta["asr_route"] ("local" or "local_gentle") and the job resumes.

One job runs at a time. Intermediate results are cached, so attaching an
official transcript later only re-runs the cheap alignment step.
"""

import queue
import threading
import time
import traceback
from pathlib import Path

from . import asr, cloud, gladia, components, config, diarize, isolated, media, notify, store, structure

BROWSER_AUDIO = {".mp3", ".m4a", ".aac", ".mp4", ".wav", ".ogg", ".oga", ".webm", ".flac", ".opus"}

_jobs: "queue.Queue[str]" = queue.Queue()
_queued: set[str] = set()
_qlock = threading.Lock()
_build_locks: dict[str, threading.Lock] = {}


def enqueue(call_id: str) -> None:
    with _qlock:
        if call_id in _queued:
            return
        _queued.add(call_id)
    store.update_meta(call_id, status="queued", stage="Waiting in queue", error=None)
    _jobs.put(call_id)


def start_worker() -> None:
    try:
        media.ensure_ffmpeg()
    except RuntimeError as exc:
        print(f"WARNING: {exc}")
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
    meta = store.update_meta(call_id, status="processing", stage="Preparing audio", progress=0.02, error=None)
    audio = d / meta["audio_file"]
    warnings: list[str] = list(meta.get("upload_warnings") or [])

    duration = media.duration(audio)
    play_file = meta["audio_file"]
    if audio.suffix.lower() not in BROWSER_AUDIO:
        play_file = "play.m4a"
        media.run("-i", str(audio), "-vn", "-ac", "1", "-c:a", "aac", "-b:a", "96k", str(d / play_file))
    store.update_meta(call_id, duration=duration, play_file=play_file)

    wav = d / "audio16k.wav"
    asr_path = d / "asr.json"
    diar_path = d / "diar.json"
    official = store.read_json(d / "official.json")

    try:
        needs_local_asr = not asr_path.exists() and (meta.get("asr_route") or "cloud") != "cloud"
        if needs_local_asr or (not diar_path.exists() and not official and diarize.wanted()):
            media.run("-i", str(audio), "-vn", "-ac", "1", "-ar", "16000",
                      "-af", cloud.SPEECH_FILTER, "-c:a", "pcm_s16le", str(wav))

        if not asr_path.exists():
            names = [t["speaker"] for t in official["turns"]] if official else None
            prompt = asr.build_prompt(meta.get("company", ""), list(dict.fromkeys(names)) if names else None)

            def on_progress(p: float) -> None:
                store.update_meta(call_id, progress=round(0.05 + 0.75 * p, 3))

            route = meta.get("asr_route") or "cloud"
            if route == "cloud":
                result, cloud_diar, service = _transcribe_in_cloud(call_id, audio, duration, prompt, on_progress, warnings)
                if result is None:
                    return
            else:
                gentle = route == "local_gentle"

                def on_setup(msg: str, p) -> None:
                    store.update_meta(call_id, stage=msg, progress=round(0.02 + 0.03 * (p or 0), 3))

                components.ensure_speech_ready(on_setup)
                store.update_meta(call_id, progress=0.05, stage=(
                    "Transcribing on this Mac (gentle mode: slower, keeps the Mac usable)" if gentle
                    else "Transcribing on this Mac"))
                try:
                    result = isolated.run("asr", str(wav), {"duration": duration, "prompt": prompt}, gentle, on_progress)
                except Exception as exc:
                    raise RuntimeError(f"Speech-to-text on this Mac failed: {exc}") from exc
                cloud_diar, service = None, "mac"
            store.write_json(asr_path, result)
            if cloud_diar:
                store.write_json(diar_path, cloud_diar)
            store.update_meta(call_id, asr_service=service)

        # Speaker separation is only needed when there's no official transcript to name speakers.
        official = store.read_json(d / "official.json")
        if not official and not diar_path.exists():
            reason = diarize.available()
            if reason is None:
                # The transcript is usable already: show it while speakers are worked out.
                build_doc(call_id)
                store.update_meta(call_id, stage="Separating speakers", progress=0.82, speakers_pending=True)
                try:
                    components.ensure_speakers_ready(lambda msg, p: store.update_meta(call_id, stage=msg))
                    gentle = config.gentle_mode()
                    label = "Separating speakers" + (" (gentle mode)" if gentle else "")
                    store.update_meta(call_id, stage=label, progress=0.82)

                    def on_diar(p: float) -> None:
                        store.update_meta(call_id, progress=round(0.82 + 0.14 * p, 3), stage=f"{label}: {round(p * 100)}%")

                    store.write_json(diar_path, isolated.run("diarize", str(wav), {}, gentle, on_diar, tag=call_id))
                except isolated.Cancelled:
                    warnings.append("Speaker separation skipped. You can run it later: Speakers tab → Detect speakers.")
                except Exception as exc:
                    traceback.print_exc()
                    warnings.append(f"Speaker separation failed: {exc}")
                finally:
                    store.update_meta(call_id, speakers_pending=False)
            else:
                warnings.append(f"Speaker separation skipped: {reason}.")
    finally:
        wav.unlink(missing_ok=True)

    store.update_meta(call_id, stage="Building transcript", progress=0.96)
    build_doc(call_id)
    meta = store.update_meta(call_id, status="ready", stage="Ready", progress=1.0, warnings=warnings, decision=None)
    notify.send(f"{meta['company']} {meta.get('period', '')} is ready", "Transcript ready")


GLADIA_PAUSE = 24 * 3600  # after "free hours used up", skip Gladia for a day instead of re-uploading every call


def _transcribe_in_cloud(call_id, audio, duration, prompt, on_progress, warnings):
    """Gladia, then Groq. Returns (asr result, speaker segments or None, service), or
    (None, None, None) after asking the user whether to use the Mac."""
    problems = []
    gkey = config.gladia_key()
    paused = time.time() < float(config.load_settings().get("gladia_paused_until") or 0)
    if gkey and paused:
        problems.append("Gladia's free hours are used up for now.")
    elif gkey:
        store.update_meta(call_id, stage="Transcribing and separating speakers in the cloud (Gladia)", progress=0.05)
        try:
            out = gladia.transcribe(str(audio), duration, gkey, on_progress)
            return out["asr"], out["diar"], "gladia"
        except gladia.GladiaUnavailable as exc:
            if gladia.is_quota(str(exc)):
                config.save_settings({"gladia_paused_until": time.time() + GLADIA_PAUSE})
            problems.append(str(exc))
    key = config.groq_key()
    if key:
        store.update_meta(call_id, stage="Transcribing in the cloud (Groq)", progress=0.05)
        try:
            result = cloud.transcribe(str(audio), duration, prompt, key, on_progress)
            if problems:
                warnings.append(f"{problems[0]} Transcribed with Groq instead.")
            return result, None, "groq"
        except cloud.CloudUnavailable as exc:
            problems.append(str(exc))
    if not gkey and not key:
        ask_local(call_id, "Cloud transcription isn't connected yet (Gladia or Groq). Connect one in "
                           "Settings for fast transcription, or use this Mac.")
    else:
        if not key:
            problems.append("Groq isn't connected as a backup.")
        ask_local(call_id, " ".join(problems))
    return None, None, None


def ask_local(call_id: str, reason: str) -> None:
    """Pause the call and ask the user whether to transcribe on this Mac."""
    meta = store.update_meta(call_id, status="needs_input", stage="Waiting for your OK", decision={"reason": reason})
    notify.send(f"{meta['company']}: {reason}", "Transcribe on this Mac?")


def decide(call_id: str, choice: str) -> dict:
    if choice not in ("local", "local_gentle", "retry"):
        raise ValueError("choice must be local, local_gentle or retry")
    if choice == "retry":
        config.save_settings({"gladia_paused_until": 0})  # you asked to try the cloud again: include Gladia
    store.update_meta(call_id, asr_route=None if choice == "retry" else choice, decision=None)
    enqueue(call_id)
    return store.get_meta(call_id)


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
