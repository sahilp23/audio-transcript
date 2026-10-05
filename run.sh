#!/usr/bin/env bash
# One-command start: creates the virtualenv on first run, then launches the app.
set -euo pipefail
cd "$(dirname "$0")"

if ! command -v ffmpeg >/dev/null; then
  echo "ffmpeg is missing. Install it with:  brew install ffmpeg"
  exit 1
fi

PY=${PYTHON:-}
if [ -z "$PY" ]; then
  for c in python3.12 python3.13 python3.11 python3.10 python3; do
    if command -v "$c" >/dev/null && "$c" -c 'import sys; sys.exit(sys.version_info < (3, 10))'; then PY=$c; break; fi
  done
fi
if [ -z "$PY" ]; then
  echo "Python 3.10+ is needed. Install it with:  brew install python@3.12"
  exit 1
fi

if [ ! -d .venv ]; then
  echo "First run: setting up (takes a minute)…"
  "$PY" -m venv .venv
  .venv/bin/pip install --upgrade pip >/dev/null
  .venv/bin/pip install -r requirements.txt
fi
if [ -n "${HF_TOKEN:-}" ] || grep -qs '^HF_TOKEN=' .env; then
  .venv/bin/python -c 'import pyannote.audio' 2>/dev/null || .venv/bin/pip install -r requirements-diarization.txt
fi

exec .venv/bin/python -m concall
