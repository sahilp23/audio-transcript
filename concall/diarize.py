"""Optional speaker separation ("who spoke when") with pyannote.audio.

Needs a free Hugging Face token with the models' terms accepted, connected in
Settings (the app then installs pyannote.audio itself). Without it the app still
works; the transcript just isn't split by speaker until an official transcript
is attached.
"""

import contextlib
import wave
from typing import Optional

from . import config


def wanted() -> bool:
    """The user has asked for speaker separation (Hugging Face connected and switched on)."""
    return config.diarization_enabled() and config.hf_ready()


def available() -> Optional[str]:
    """Returns None if diarization should run, otherwise the reason it won't."""
    if not config.diarization_enabled():
        return "turned off in Settings"
    if not config.hf_token():
        return "Hugging Face isn't connected (Settings → Speaker separation)"
    if not config.hf_ready():
        return "Hugging Face setup isn't finished (Settings → Speaker separation)"
    return None


# pyannote.audio 3.x calls hf_hub_download(use_auth_token=...), an argument newer
# huggingface_hub versions removed. Translate it to `token=` for those modules.
_PYANNOTE_HUB_USERS = (
    "pyannote.audio.core.pipeline",
    "pyannote.audio.core.model",
    "pyannote.audio.pipelines.speaker_verification",
)


def hub_download_compat(download):
    def wrapper(*args, use_auth_token=None, **kwargs):
        if use_auth_token is not None and "token" not in kwargs:
            kwargs["token"] = use_auth_token
        return download(*args, **kwargs)

    wrapper.__concall_compat__ = True
    return wrapper


def patch_pyannote_hub() -> None:
    import importlib

    for name in _PYANNOTE_HUB_USERS:
        try:
            mod = importlib.import_module(name)
        except ImportError:
            continue
        fn = getattr(mod, "hf_hub_download", None)
        if fn is not None and not getattr(fn, "__concall_compat__", False):
            mod.hf_hub_download = hub_download_compat(fn)


@contextlib.contextmanager
def trusted_torch_load():
    """PyTorch 2.6+ refuses to unpickle pyannote's checkpoints by default
    ("Weights only load failed"). These files come from the official pyannote
    repos on Hugging Face, so allow full loading while the pipeline loads."""
    import torch

    original = torch.load

    def load(*args, **kwargs):
        kwargs["weights_only"] = False
        return original(*args, **kwargs)

    torch.load = load
    try:
        yield
    finally:
        torch.load = original


def load_pipeline(device: Optional[str] = None):
    with trusted_torch_load():
        return _load_pipeline(device)


def _load_pipeline(device: Optional[str]):
    from pyannote.audio import Pipeline

    patch_pyannote_hub()

    try:  # pyannote.audio >= 4
        pipeline = Pipeline.from_pretrained(config.DIARIZATION_MODEL, token=config.hf_token())
    except TypeError:  # pyannote.audio 3.x
        pipeline = Pipeline.from_pretrained(config.DIARIZATION_MODEL, use_auth_token=config.hf_token())
    if pipeline is None:
        raise RuntimeError(
            f"Could not load {config.DIARIZATION_MODEL}. Accept its terms on huggingface.co "
            "with the account you connected in Settings."
        )
    import torch

    if device is None and torch.backends.mps.is_available():
        device = "mps"
    if device and device != "cpu":
        try:
            pipeline.to(torch.device(device))
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


def diarize(wav_path: str, gentle: bool = False) -> list[dict]:
    """Returns [{"s": start, "e": end, "spk": "SPEAKER_00"}, ...] sorted by start.

    gentle: CPU only with a few threads, so the Mac stays usable."""
    if gentle:
        import torch

        torch.set_num_threads(4)
    pipeline = load_pipeline("cpu" if gentle else None)
    output = pipeline(_read_wav(wav_path))
    annotation = getattr(output, "speaker_diarization", output)  # 4.x wraps the result
    segs = [
        {"s": round(turn.start, 3), "e": round(turn.end, 3), "spk": str(label)}
        for turn, _, label in annotation.itertracks(yield_label=True)
    ]
    segs.sort(key=lambda x: x["s"])
    return segs
