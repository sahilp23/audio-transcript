r"""Runtime settings.

Two ways to run:
  * Desktop app (CONCALL_APP=1, set by the launcher): everything lives in
    ~/Library/Application Support/Concall Player (Mac) or
    %LOCALAPPDATA%\Concall Player (Windows); settings are edited in the app.
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
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv() -> None:
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv()

IS_MAC = platform.system() == "Darwin"
IS_APPLE_SILICON = IS_MAC and platform.machine() == "arm64"
IS_WINDOWS = platform.system() == "Windows"
DEVICE = "Mac" if IS_MAC else "PC"  # for messages: "Transcribe on this Mac/PC?"
APP_MODE = os.environ.get("CONCALL_APP") == "1"
# Website mode (hosted, e.g. on Render): Google sign-in, calls stored in Google Drive,
# cloud transcription only. See drivesync.py, webauth.py and docs/WEBSITE.md.
WEB_MODE = os.environ.get("CONCALL_WEB") == "1"
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
# Who may sign in: comma-separated email addresses.
ALLOWED_EMAILS = {e.strip().lower() for e in os.environ.get("ALLOWED_EMAILS", "").split(",") if e.strip()}
SECRET_KEY = os.environ.get("SECRET_KEY", "")  # encrypts the sign-in cookie
# The site's public address; Render sets RENDER_EXTERNAL_URL automatically.
PUBLIC_URL = (os.environ.get("PUBLIC_URL") or os.environ.get("RENDER_EXTERNAL_URL") or "").rstrip("/")

if os.environ.get("CONCALL_SUPPORT_DIR"):
    SUPPORT_DIR = Path(os.environ["CONCALL_SUPPORT_DIR"]).expanduser()
elif APP_MODE and IS_MAC:
    SUPPORT_DIR = Path.home() / "Library" / "Application Support" / "Concall Player"
elif WEB_MODE:
    SUPPORT_DIR = Path("/tmp/concall")  # temporary: the real copy is in Google Drive
elif APP_MODE and IS_WINDOWS:
    SUPPORT_DIR = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "Concall Player"
else:
    SUPPORT_DIR = ROOT / "data"

DATA_DIR = Path(os.environ.get("CONCALL_DATA_DIR", SUPPORT_DIR)).expanduser()
SETTINGS_FILE = SUPPORT_DIR / "settings.json"
BIN_DIR = SUPPORT_DIR / "bin"
if os.environ.get("CONCALL_LOG_DIR"):
    LOG_DIR = Path(os.environ["CONCALL_LOG_DIR"]).expanduser()
elif IS_MAC:
    LOG_DIR = Path.home() / "Library" / "Logs" / "Concall Player"
else:
    LOG_DIR = SUPPORT_DIR / "logs"
LOG_FILE = LOG_DIR / "app.log"

# Set by the launcher: the bundled `uv` (installs Python packages) and the app's location
# (the .app on a Mac, the launcher script on Windows; used to restart after an update).
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
    "groq_key": "",  # cloud transcription (free tier); empty = not connected
    "gladia_key": "",  # cloud transcription + speakers (free monthly hours); tried before Groq
    "gladia_paused_until": 0,  # free hours used up: skip Gladia until this time
    "mac_mode": "auto",  # auto | gentle | fast: how hard local processing may push the Mac
}

_lock = threading.Lock()
on_settings_saved: list = []  # website mode: drivesync uploads settings.json to Google Drive


def load_settings() -> dict:
    try:
        data = json.loads(read_text(SETTINGS_FILE))
    except (FileNotFoundError, ValueError):
        data = {}
    return {**DEFAULTS, **data}


def replace_file(tmp: Path, path: Path) -> None:
    """os.replace that copes with Windows: there, replacing a file fails while another
    thread is reading it (the window polls a call's status while it's being saved)."""
    for attempt in range(20):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if not IS_WINDOWS or attempt == 19:
                raise
            time.sleep(0.05)


def read_text(path: Path) -> str:
    """Path.read_text that copes with Windows, where a file being replaced by another
    thread can't be opened for a moment (PermissionError)."""
    for attempt in range(20):
        try:
            return path.read_text(encoding="utf-8")
        except PermissionError:
            if not IS_WINDOWS or attempt == 19:
                raise
            time.sleep(0.05)
    raise AssertionError("unreachable")


def save_settings(patch: dict) -> dict:
    with _lock:
        data = load_settings()
        data.update({k: v for k, v in patch.items() if k in DEFAULTS})
        SUPPORT_DIR.mkdir(parents=True, exist_ok=True)
        tmp = SETTINGS_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        os.chmod(tmp, 0o600)  # holds the Hugging Face token and API keys
        replace_file(tmp, SETTINGS_FILE)
    for hook in on_settings_saved:
        hook()
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


def groq_key() -> str:
    return os.environ.get("GROQ_API_KEY") or load_settings()["groq_key"]


def gladia_key() -> str:
    return os.environ.get("GLADIA_API_KEY") or load_settings()["gladia_key"]


def total_ram_gb() -> float:
    if IS_WINDOWS:
        try:
            import ctypes

            class MemoryStatus(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

            st = MemoryStatus()
            st.dwLength = ctypes.sizeof(MemoryStatus)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st))
            return st.ullTotalPhys / 1e9
        except Exception:
            return 16.0
    try:
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 1e9
    except (ValueError, OSError, AttributeError):
        return 16.0


def gentle_mode() -> bool:
    """Run local processing at low priority on a few cores. Default on for <=8 GB computers."""
    mode = load_settings()["mac_mode"]
    if mode in ("gentle", "fast"):
        return mode == "gentle"
    return total_ram_gb() < 12


def ollama_model() -> str:
    return os.environ.get("OLLAMA_MODEL") or load_settings()["ollama_model"]


def python_exe() -> str:
    return sys.executable
