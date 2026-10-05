#!/bin/bash
# End-to-end test of the built app on a clean Mac (used in CI):
# first-launch setup, speech engine install, model download, a real
# transcription of speech generated with macOS `say`, and the speaker-
# separation install. Uses the small Whisper model to keep CI fast.
#   packaging/macos/smoke_test.sh "dist/Concall Player.app"
set -euo pipefail
APP="$1"
WORK="$(mktemp -d)"
export CONCALL_SUPPORT_DIR="$WORK/support"
export CONCALL_HEADLESS=1
export CONCALL_LOG_STDOUT=1
export PORT=8799
export MLX_MODEL="mlx-community/whisper-tiny"
export FASTER_WHISPER_MODEL="tiny.en"
BASE="http://127.0.0.1:$PORT"
H=(-H "X-Concall: 1")

"$APP/Contents/MacOS/Concall Player" > "$WORK/app.log" 2>&1 &
PID=$!
cleanup() { kill "$PID" 2>/dev/null || true; echo "----- app log -----"; tail -n 80 "$WORK/app.log"; }
trap cleanup EXIT

wait_for() {  # wait_for <seconds> <description> <command...>
  local secs="$1" what="$2"; shift 2
  for _ in $(seq 1 "$secs"); do
    if "$@" >/dev/null 2>&1; then echo "✓ $what"; return 0; fi
    if ! kill -0 "$PID" 2>/dev/null; then echo "✗ app exited while waiting for: $what"; return 1; fi
    sleep 1
  done
  echo "✗ timed out: $what"; return 1
}
json() { python3 -c "import sys,json; d=json.load(sys.stdin); print($1)"; }

wait_for 600 "app started (first-launch setup)" curl -sf "$BASE/api/ping"
curl -sf "$BASE/api/status" | json "d['version'], d['asr_engine'], d['app_mode']"

engine_ready() { curl -sf "$BASE/api/setup" | json "d['components']['engine']['installed'] and d['components']['speech_model']['installed']" | grep -q True; }
wait_for 1500 "speech engine installed and model downloaded" engine_ready

AUDIO="$WORK/speech.aiff"
say -o "$AUDIO" "Good afternoon everyone. Revenue grew eighteen percent this quarter, and EBITDA margins improved. We will now begin the question and answer session."

ID=$(curl -sf "${H[@]}" -F company="Smoke Test" -F period="Q1" -F audio=@"$AUDIO" "$BASE/api/calls" | json "d['id']")
call_done() { curl -sf "$BASE/api/calls/$ID" | json "d['status']" | grep -Eq "ready|error"; }
wait_for 600 "call processed" call_done
curl -sf "$BASE/api/calls/$ID" | json "d['status'], d.get('error')"
TEXT=$(curl -sf "$BASE/api/calls/$ID/doc" | json "' '.join(w[0] for t in d['turns'] for p in t['paras'] for w in p['w'])")
echo "Transcript: $TEXT"
echo "$TEXT" | grep -iq "revenue" || { echo "✗ transcript doesn't contain 'revenue'"; exit 1; }
echo "✓ transcription works"

# The CPU engine (fallback when the Mac GPU path fails) must work too.
ASR_ENGINE=faster PYTHONPATH="$APP/Contents/Resources/app" "$CONCALL_SUPPORT_DIR/venv/bin/python" - "$AUDIO" <<'PY'
import sys, tempfile, os
from concall import asr, media
wav = os.path.join(tempfile.mkdtemp(), "a.wav")
media.run("-i", sys.argv[1], "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", wav)
out = asr.transcribe(wav, 10.0, asr.build_prompt("Smoke Test"), lambda p: None)
text = " ".join(w["w"] for w in out["words"])
print("faster-whisper:", out["engine"], text)
assert out["engine"] == "faster" and "revenue" in text.lower(), text
PY
echo "✓ CPU fallback engine works"

# Speaker separation package (installed when the user connects Hugging Face).
curl -sf -X POST "${H[@]}" "$BASE/api/setup/speakers" >/dev/null
speakers_done() { curl -sf "$BASE/api/setup" | json "d['components']['speakers']['state']" | grep -Eq "done|error"; }
wait_for 1200 "speaker separation install finished" speakers_done
curl -sf "$BASE/api/setup" | json "d['components']['speakers']"
curl -sf "$BASE/api/setup" | json "d['components']['speakers']['installed']" | grep -q True
"$CONCALL_SUPPORT_DIR/venv/bin/python" -c "from pyannote.audio import Pipeline; import torch; print('pyannote ok, torch', torch.__version__)"
echo "✓ all smoke tests passed"
