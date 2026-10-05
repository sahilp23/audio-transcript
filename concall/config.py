"""Runtime settings, read from environment variables (or a .env file in the repo root)."""

import os
import platform
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

IS_APPLE_SILICON = platform.system() == "Darwin" and platform.machine() == "arm64"

DATA_DIR = Path(os.environ.get("CONCALL_DATA_DIR", ROOT / "data")).expanduser()

# "auto" picks mlx on Apple Silicon, faster-whisper elsewhere.
ASR_ENGINE = os.environ.get("ASR_ENGINE", "auto")
MLX_MODEL = os.environ.get("MLX_MODEL", "mlx-community/whisper-large-v3-turbo")
FASTER_WHISPER_MODEL = os.environ.get("FASTER_WHISPER_MODEL", "large-v3-turbo")

# Speaker separation needs a free Hugging Face token (see README).
HF_TOKEN = os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_TOKEN")
DIARIZATION_MODEL = os.environ.get("DIARIZATION_MODEL", "pyannote/speaker-diarization-3.1")
DIARIZATION = os.environ.get("DIARIZATION", "auto")  # auto | off

# Optional local LLM summaries via Ollama.
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.2:3b")

HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "8765"))
