"""ffmpeg helpers. The Mac app doesn't need Homebrew: it uses the ffmpeg binary
shipped in the imageio-ffmpeg package and puts it on PATH as `ffmpeg` (Whisper
calls it by that name)."""

import os
import re
import shutil
import subprocess
from pathlib import Path

from . import config

# "Clear voice" playback: cut rumble and hiss, reduce steady background noise,
# and even out loud and quiet speakers.
CLEAR_VOICE_FILTER = "highpass=f=90,lowpass=f=7600,afftdn=nf=-25:tn=1,speechnorm=e=6:r=0.0001:l=1"


def ensure_ffmpeg() -> str:
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg
    except ImportError:
        raise RuntimeError("ffmpeg not found. Install it with: brew install ffmpeg")
    exe = Path(imageio_ffmpeg.get_ffmpeg_exe())
    config.BIN_DIR.mkdir(parents=True, exist_ok=True)
    link = config.BIN_DIR / "ffmpeg"
    if link.is_symlink() or link.exists():
        if link.resolve() != exe.resolve():
            link.unlink()
    if not link.exists():
        link.symlink_to(exe)
    os.environ["PATH"] = f"{config.BIN_DIR}{os.pathsep}{os.environ.get('PATH', '')}"
    return str(link)


def run(*args: str) -> None:
    proc = subprocess.run([ensure_ffmpeg(), "-y", "-loglevel", "error", *args], capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError("ffmpeg failed: " + proc.stderr.strip()[-500:])


def duration(path: Path) -> float:
    """Media duration in seconds, read from ffmpeg's header output."""
    proc = subprocess.run([ensure_ffmpeg(), "-hide_banner", "-i", str(path)], capture_output=True, text=True)
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", proc.stderr)
    if m:
        h, mnt, s = m.groups()
        return int(h) * 3600 + int(mnt) * 60 + float(s)
    if "Invalid data" in proc.stderr or "No such file" in proc.stderr:
        raise RuntimeError("This file doesn't look like audio ffmpeg can read.")
    # Some streams have no header duration: decode once to measure.
    proc = subprocess.run([ensure_ffmpeg(), "-hide_banner", "-i", str(path), "-f", "null", "-"], capture_output=True, text=True)
    times = re.findall(r"time=(\d+):(\d+):(\d+(?:\.\d+)?)", proc.stderr)
    if not times:
        raise RuntimeError("Couldn't read the audio length")
    h, mnt, s = times[-1]
    return int(h) * 3600 + int(mnt) * 60 + float(s)
