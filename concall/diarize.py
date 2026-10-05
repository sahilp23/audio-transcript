"""Optional speaker separation ("who spoke when") with pyannote.audio.

Needs `pip install -r requirements-diarization.txt` and a free Hugging Face token
with the model's terms accepted (see README). Without it the app still works; the
transcript just won't be split by speaker until an official transcript is attached.
"""

import wave
from typing import Optional

from . import config


def available() -> Optional[str]:
    """Returns None if diarization can run, otherwise the reason it can't."""
    if config.DIARIZATION == "off":
        return "turned off (DIARIZATION=off)"
    if not config.HF_TOKEN:
        return "no HF_TOKEN set"
    try:
        import pyannote.audio  # noqa: F401
    except ImportError:
        return "pyannote.audio not installed"
    return None


def _load_pipeline():
    from pyannote.audio import Pipeline

    try:  # pyannote.audio >= 4
        pipeline = Pipeline.from_pretrained(config.DIARIZATION_MODEL, token=config.HF_TOKEN)
    except TypeError:  # pyannote.audio 3.x
        pipeline = Pipeline.from_pretrained(config.DIARIZATION_MODEL, use_auth_token=config.HF_TOKEN)
    if pipeline is None:
        raise RuntimeError(
            f"Could not load {config.DIARIZATION_MODEL}. Accept its terms on huggingface.co "
            "with the account that owns HF_TOKEN."
        )
    import torch

    if torch.backends.mps.is_available():
        try:
            pipeline.to(torch.device("mps"))
        except Exception:
            pass
    return pipeline


def _read_wav(path: str):
    import numpy as np
    import torch

    with wave.open(path, "rb") as f:
        rate = f.getframerate()
        frames = f.readframes(f.getnframes())
    audio = np.frombuffer(frames, dtype=np.int16).astype("float32") / 32768.0
    return {"waveform": torch.from_numpy(audio).unsqueeze(0), "sample_rate": rate}


def diarize(wav_path: str) -> list[dict]:
    """Returns [{"s": start, "e": end, "spk": "SPEAKER_00"}, ...] sorted by start."""
    pipeline = _load_pipeline()
    output = pipeline(_read_wav(wav_path))
    annotation = getattr(output, "speaker_diarization", output)  # 4.x wraps the result
    segs = [
        {"s": round(turn.start, 3), "e": round(turn.end, 3), "spk": str(label)}
        for turn, _, label in annotation.itertracks(yield_label=True)
    ]
    segs.sort(key=lambda x: x["s"])
    return segs
