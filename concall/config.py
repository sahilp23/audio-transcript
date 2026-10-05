"""Runtime settings.

Two ways to run:
  * Mac app (CONCALL_APP=1, set by the launcher): everything lives in
    ~/Library/Application Support/Concall Player, settings are edited in the app.
  * Developer mode (`./run.sh` or `python -m concall`): data in ./data, settings
    from environment variables or a .env file.

Settings the user can change in the app are stored in settings.json and read on
every use, so changes apply without a restart. Environment variables win.
"""

import json
import os
import platform
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv() -> None:
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv()

IS_MAC = platform.system() == "Darwin"
IS_APPLE_SILICON = IS_MAC and platform.machine() == "arm64"
APP_MODE = os.environ.get("CONCALL_APP") == "1"

if os.environ.get("CONCALL_SUPPORT_DIR"):
    SUPPORT_DIR = Path(os.environ["CONCALL_SUPPORT_DIR"]).expanduser()
elif APP_MODE and IS_MAC:
    SUPPORT_DIR = Path.home() / "Library" / "Application Support" / "Concall Player"
else:
    SUPPORT_DIR = ROOT / "data"

DATA_DIR = Path(os.environ.get("CONCALL_DATA_DIR", SUPPORT_DIR)).expanduser()
SETTINGS_FILE = SUPPORT_DIR / "settings.json"
BIN_DIR = SUPPORT_DIR / "bin"

# Set by the Mac launcher: the bundled `uv` (installs Python packages) and the .app path.
UV = os.environ.get("CONCALL_UV")
APP_PATH = os.environ.get("CONCALL_APP_PATH")

GITHUB_REPO = os.environ.get("CONCALL_GITHUB_REPO", "sahilp23/audio-transcript")

ASR_ENGINE = os.environ.get("ASR_ENGINE", "auto")  # auto | mlx | faster
MLX_MODEL = os.environ.get("MLX_MODEL", "mlx-community/whisper-large-v3-turbo")
FASTER_WHISPER_MODEL = os.environ.get("FASTER_WHISPER_MODEL", "large-v3-turbo")

DIARIZATION_MODEL = os.environ.get("DIARIZATION_MODEL", "pyannote/speaker-diarization-3.1")
# Gated models whose terms must be accepted on huggingface.co for speaker separation.
DIARIZATION_GATED = ("pyannote/speaker-diarization-3.1", "pyannote/segmentation-3.0")

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")

HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "8765"))

DEFAULTS = {
    "hf_token": "",
    "hf_ok": False,  # token valid and model terms accepted (last check)
    "hf_user": "",
    "diarization": True,  # separate speakers when a token is connected
    "auto_update_check": True,
    "ollama_model": "llama3.2:3b",
}

_lock = threading.Lock()


def load_settings() -> dict:
    try:
        data = json.loads(SETTINGS_FILE.read_text())
    except (FileNotFoundError, ValueError):
        data = {}
    return {**DEFAULTS, **data}


def save_settings(patch: dict) -> dict:
    with _lock:
        data = load_settings()
        data.update({k: v for k, v in patch.items() if k in DEFAULTS})
        SUPPORT_DIR.mkdir(parents=True, exist_ok=True)
        tmp = SETTINGS_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2))
        os.chmod(tmp, 0o600)  # holds the Hugging Face token
        os.replace(tmp, SETTINGS_FILE)
        return data


def hf_token() -> str:
    return os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_TOKEN") or load_settings()["hf_token"]


def hf_ready() -> bool:
    """A token is set and the last check passed (env tokens are trusted as-is)."""
    if os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_TOKEN"):
        return True
    s = load_settings()
    return bool(s["hf_token"]) and bool(s["hf_ok"])


def diarization_enabled() -> bool:
    if os.environ.get("DIARIZATION") == "off":
        return False
    return bool(load_settings()["diarization"])


def ollama_model() -> str:
    return os.environ.get("OLLAMA_MODEL") or load_settings()["ollama_model"]


def python_exe() -> str:
    return sys.executable
