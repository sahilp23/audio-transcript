"""Speech-to-text with word-level timestamps, fully local.

Engines:
  mlx     mlx-whisper, runs on the Apple Silicon GPU (fastest on an M1/M2/M3 Mac)
  faster  faster-whisper, CPU (works on any machine, slower)
"""

import sys
import threading
import types
import wave
from typing import Callable, Optional

from . import config

ProgressFn = Callable[[float], None]

# Vocabulary hint so Whisper spells finance terms the way transcripts do.
BASE_PROMPT = (
    "Earnings conference call. Revenue, EBITDA, PAT, margins, crores, lakhs, "
    "basis points, year-on-year, quarter-on-quarter, FY26, FY27, Q1, capex, guidance."
)

_mlx_lock = threading.Lock()


def pick_engine() -> str:
    if config.ASR_ENGINE != "auto":
        return config.ASR_ENGINE
    return "mlx" if config.IS_APPLE_SILICON else "faster"


def build_prompt(company: str = "", names: Optional[list[str]] = None) -> str:
    parts = [BASE_PROMPT]
    if company:
        parts.insert(0, f"{company} earnings call.")
    if names:
        parts.append("Speakers: " + ", ".join(names[:12]) + ".")
    return " ".join(parts)


def transcribe(wav_path: str, duration: float, prompt: str, progress: ProgressFn) -> dict:
    engine = pick_engine()
    if engine == "mlx":
        try:
            words = _transcribe_mlx(wav_path, duration, prompt, progress)
            model = config.MLX_MODEL
        except Exception as exc:
            # e.g. the Mac GPU (Metal) isn't usable: fall back to the CPU engine if present.
            try:
                import faster_whisper  # noqa: F401
            except ImportError:
                raise exc
            print(f"mlx-whisper failed ({exc}); falling back to faster-whisper on CPU", flush=True)
            engine = "faster"
            words = _transcribe_faster(wav_path, duration, prompt, progress)
            model = config.FASTER_WHISPER_MODEL
    elif engine == "faster":
        words = _transcribe_faster(wav_path, duration, prompt, progress)
        model = config.FASTER_WHISPER_MODEL
    else:
        raise ValueError(f"Unknown ASR_ENGINE {engine!r} (use auto, mlx or faster)")
    return {"engine": engine, "model": model, "words": words}


def _clean_word(text: str, start: float, end: float, prob: float) -> Optional[dict]:
    text = text.strip()
    if not text:
        return None
    return {"w": text, "s": round(float(start), 3), "e": round(float(end), 3), "p": round(float(prob), 3)}


def _transcribe_mlx(wav_path: str, duration: float, prompt: str, progress: ProgressFn) -> list[dict]:
    import mlx_whisper

    # `mlx_whisper.transcribe` is the function (it shadows the submodule), so get the module itself.
    mt = sys.modules["mlx_whisper.transcribe"]

    # mlx-whisper only reports progress through tqdm; swap in a shim that forwards updates.
    total_frames = {"n": 1, "done": 0}

    class _Bar:
        def __init__(self, total=1, **_):
            total_frames["n"] = max(1, total or 1)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def update(self, n):
            total_frames["done"] += n
            progress(min(1.0, total_frames["done"] / total_frames["n"]))

    with _mlx_lock:
        original = mt.tqdm
        mt.tqdm = types.SimpleNamespace(tqdm=_Bar)
        try:
            result = mlx_whisper.transcribe(
                wav_path,
                path_or_hf_repo=config.MLX_MODEL,
                language="en",
                word_timestamps=True,
                initial_prompt=prompt,
                condition_on_previous_text=False,
                hallucination_silence_threshold=2.0,
                verbose=False,
            )
        finally:
            mt.tqdm = original

    words = []
    for seg in result.get("segments", []):
        for w in seg.get("words", []) or []:
            cw = _clean_word(w["word"], w["start"], w["end"], w.get("probability", 1.0))
            if cw:
                words.append(cw)
    return words


def _read_wav(path: str):
    """16 kHz mono PCM wav -> float32 numpy array."""
    import numpy as np

    with wave.open(path, "rb") as f:
        frames = f.readframes(f.getnframes())
    return np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0


def _transcribe_faster(wav_path: str, duration: float, prompt: str, progress: ProgressFn) -> list[dict]:
    from faster_whisper import WhisperModel

    model = WhisperModel(config.FASTER_WHISPER_MODEL, device="auto", compute_type="int8")
    segments, _info = model.transcribe(
        _read_wav(wav_path),  # decoded here: faster-whisper's own decoder breaks with some PyAV versions
        language="en",
        word_timestamps=True,
        initial_prompt=prompt,
        condition_on_previous_text=False,
        vad_filter=True,
        hallucination_silence_threshold=2.0,
    )
    words = []
    for seg in segments:
        for w in seg.words or []:
            cw = _clean_word(w.word, w.start, w.end, w.probability)
            if cw:
                words.append(cw)
        if duration:
            progress(min(1.0, seg.end / duration))
    return words
