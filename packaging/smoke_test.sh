#!/bin/bash
# End-to-end test of the built app on a clean Mac or Windows PC (used in CI):
# first-launch setup, speech engine install, model download, a real
# transcription of generated speech (macOS `say` / Windows speech synthesis),
# and the speaker-separation install. Uses the small Whisper model to keep CI fast.
#   packaging/smoke_test.sh "dist/Concall Player.app"        (Mac)
#   packaging/smoke_test.sh "<installed folder>"              (Windows, Git Bash)
set -euo pipefail
APP="$1"
if [ -d "$APP/Contents" ]; then OS=mac; else OS=win; fi
if [ "$OS" = win ]; then
  WORK="$(cygpath -m "$(mktemp -d)")"  # C:/... paths work for bash and Windows programs alike
  HOSTPY=python
  CODE="$APP/app"
  VPY="$WORK/support/venv/Scripts/python.exe"
else
  WORK="$(mktemp -d)"
  HOSTPY=python3
  CODE="$APP/Contents/Resources/app"
  VPY="$WORK/support/venv/bin/python"
fi
export CONCALL_SUPPORT_DIR="$WORK/support"
export CONCALL_HEADLESS=1
export CONCALL_LOG_STDOUT=1
export PORT=8799
export MLX_MODEL="mlx-community/whisper-tiny"
export FASTER_WHISPER_MODEL="tiny.en"
BASE="http://127.0.0.1:$PORT"
H=(-H "X-Concall: 1")

if [ "$OS" = win ]; then
  # What the installer does after copying files, then what the Start-menu shortcut runs.
  cmd //c "$(cygpath -w "$APP/setup.cmd")" || { cat "$WORK/support/logs/setup.log"; exit 1; }
  echo "✓ installer setup step (Python + core packages)"
  "$VPY" "$APP/launcher.pyw" > "$WORK/app.log" 2>&1 &
else
  "$APP/Contents/MacOS/Concall Player" > "$WORK/app.log" 2>&1 &
fi
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
show() { local x; x="$(cat)"; echo "$x" >&2; echo "$x"; }  # like `tee /dev/stderr` (missing on Windows)
json() { "$HOSTPY" -c "import sys,json; d=json.load(sys.stdin); print($1)"; }

wait_for 600 "app started (first-launch setup)" curl -sf "$BASE/api/ping"
curl -sf "$BASE/api/status" | json "d['version'], d['asr_engine'], d['app_mode']"

engine_ready() { curl -sf "$BASE/api/setup" | json "d['components']['engine']['installed'] and d['components']['speech_model']['installed']" | grep -q True; }
wait_for 1500 "speech engine installed and model downloaded" engine_ready

SPEECH="Good afternoon everyone. Revenue grew eighteen percent this quarter, and EBITDA margins improved. We will now begin the question and answer session."
if [ "$OS" = win ]; then
  AUDIO="$WORK/speech.wav"
  powershell -NoProfile -Command "Add-Type -AssemblyName System.Speech; \$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; \$s.SetOutputToWaveFile('$AUDIO'); \$s.Speak('$SPEECH'); \$s.Dispose()"
else
  AUDIO="$WORK/speech.aiff"
  say -o "$AUDIO" "$SPEECH"
fi

upload() { curl -sf "${H[@]}" -F company="Smoke Test" -F period="$1" -F audio=@"$AUDIO" "$BASE/api/calls" | json "d['id']"; }
status_of() { curl -sf "$BASE/api/calls/$1" | json "d['status']"; }
wait_status() {  # wait_status <id> <regex> <seconds>
  local id="$1" want="$2" secs="$3"
  for _ in $(seq 1 "$secs"); do
    st=$(status_of "$id"); if echo "$st" | grep -Eq "$want"; then echo "$st"; return 0; fi
    if [ "$st" = "error" ]; then curl -sf "$BASE/api/calls/$id" | json "d.get('error')"; return 1; fi
    sleep 1
  done
  echo "✗ timed out waiting for $want (last: $st)"; return 1
}
text_of() { curl -sf "$BASE/api/calls/$1/doc" | json "' '.join(w[0] for t in d['turns'] for p in t['paras'] for w in p['w'])"; }
decide() { curl -sf -X POST "${H[@]}" -H "Content-Type: application/json" -d "{\"choice\": \"$2\"}" "$BASE/api/calls/$1/decision" >/dev/null; }

# 1. No cloud key: the app must ask before using the computer, then transcribe locally (fast mode).
ID=$(upload "Q1")
wait_status "$ID" "needs_input" 120 >/dev/null
echo "✓ asks before transcribing on this computer"
decide "$ID" local
wait_status "$ID" "ready" 600 >/dev/null
TEXT=$(text_of "$ID"); echo "Local (fast): $TEXT"
echo "$TEXT" | grep -iq "revenue" || { echo "✗ transcript doesn't contain 'revenue'"; exit 1; }
echo "✓ local transcription (fast) works"

# 2. Gentle mode: CPU engine at background priority in a separate process.
ID2=$(upload "Q2")
wait_status "$ID2" "needs_input" 120 >/dev/null
decide "$ID2" local_gentle
wait_status "$ID2" "ready" 900 >/dev/null
TEXT=$(text_of "$ID2"); echo "Local (gentle): $TEXT"
echo "$TEXT" | grep -iq "revenue" || { echo "✗ gentle transcript doesn't contain 'revenue'"; exit 1; }
echo "✓ local transcription (gentle) works"

# 3. Clear voice audio.
curl -sf -X POST "${H[@]}" "$BASE/api/calls/$ID/enhance" >/dev/null
enhanced() { curl -sf "$BASE/api/calls/$ID" | json "d.get('enhanced')" | grep -Eq "ready|error"; }
wait_for 300 "clear-voice audio finished" enhanced
curl -sf "$BASE/api/calls/$ID" | json "d.get('enhanced'), d.get('enhanced_error')" | show | grep -q "ready"
curl -sf -o /dev/null "$BASE/api/calls/$ID/audio?clear=1"
echo "✓ clear voice works"

# 4. Report a problem builds a GitHub issue link.
curl -sf -X POST "${H[@]}" -H "Content-Type: application/json" -d '{"description": "smoke test", "context": {"error": "x"}}' \
  "$BASE/api/report" | json "d['url']" | grep -q "github.com/.*/issues/new"
echo "✓ report a problem works"

# 5. Speaker separation package (installed when the user connects Hugging Face).
curl -sf -X POST "${H[@]}" "$BASE/api/setup/speakers" >/dev/null
speakers_done() { curl -sf "$BASE/api/setup" | json "d['components']['speakers']['state']" | grep -Eq "done|error"; }
wait_for 1200 "speaker separation install finished" speakers_done
curl -sf "$BASE/api/setup" | json "d['components']['speakers']"
curl -sf "$BASE/api/setup" | json "d['components']['speakers']['installed']" | grep -q True

# Loading a pyannote model must work end to end (Hugging Face download + PyTorch
# unpickling). This public model needs no token.
PYTHONPATH="$CODE" "$VPY" - <<'PY'
from concall import diarize
diarize.patch_pyannote_hub()
from pyannote.audio import Model
with diarize.trusted_torch_load():
    m = Model.from_pretrained("pyannote/wespeaker-voxceleb-resnet34-LM")
assert m is not None
print("pyannote model loaded:", type(m).__name__)
PY
echo "✓ speaker model loads"

# 5b. Use from other computers: a real Cloudflare link, locked by email (visitors get sent to Cloudflare's sign-in).
curl -sf -X POST "${H[@]}" -H "Content-Type: application/json" -d '{"email": "smoke@example.com", "password": "smoke-test-pw"}' \
  "$BASE/api/remote/setup" | json "d['ok']" | grep -q True
curl -sf -X POST "${H[@]}" "$BASE/api/remote/start" >/dev/null
remote_on() { curl -sf "$BASE/api/remote" | json "d['state']" | grep -q "^on$"; }
if wait_for 180 "Cloudflare link created" remote_on; then
  LINK=$(curl -sf "$BASE/api/remote" | json "d['url']"); echo "Link: $LINK"
  LOCKED=""
  # A brand-new link takes a little while to resolve. Ask Cloudflare's DNS directly (the
  # system resolver may have cached "doesn't exist yet"), and fall back to the system one.
  for i in $(seq 1 60); do
    if [ $((i % 2)) -eq 1 ]; then DNS=(--doh-url https://1.1.1.1/dns-query); else DNS=(); fi
    WHERE=$(curl -sS -o /dev/null --max-time 15 "${DNS[@]}" -w "%{http_code} %{redirect_url}" "$LINK/" 2>&1 || true)
    if echo "$WHERE" | grep -q "302 https://login.trycloudflare.com"; then LOCKED=1; break; fi
    sleep 3
  done
  echo "Unauthenticated visit: $WHERE"
  [ -n "$LOCKED" ] || { echo "✗ the link isn't behind Cloudflare's email sign-in"; exit 1; }
  echo "✓ remote link works and is locked to the email address"
else
  curl -sf "$BASE/api/remote" | show
  exit 1
fi
curl -sf -X POST "${H[@]}" "$BASE/api/remote/stop" >/dev/null

# 6. Optional, only when the repository has these secrets: Groq, Gladia and full speaker separation.
if [ -n "${CI_GROQ_KEY:-}" ]; then
  curl -sf -X POST "${H[@]}" -H "Content-Type: application/json" -d "{\"key\": \"$CI_GROQ_KEY\"}" "$BASE/api/groq/connect" | json "d['ok']" | grep -q True
  ID3=$(upload "Q3")
  wait_status "$ID3" "ready" 300 >/dev/null
  TEXT=$(text_of "$ID3"); echo "Groq: $TEXT"
  echo "$TEXT" | grep -iq "revenue"
  echo "✓ Groq cloud transcription works"
else
  echo "- skipped Groq test (no CI_GROQ_KEY secret)"
fi
if [ -n "${CI_GLADIA_KEY:-}" ]; then
  # Gladia is tried before Groq once connected: transcript and speakers in one go.
  curl -sf -X POST "${H[@]}" -H "Content-Type: application/json" -d "{\"key\": \"$CI_GLADIA_KEY\"}" "$BASE/api/gladia/connect" | json "d['ok']" | grep -q True
  ID4=$(upload "Q4")
  wait_status "$ID4" "ready" 600 >/dev/null
  curl -sf "$BASE/api/calls/$ID4" | json "d.get('asr_service'), d.get('warnings')" | show | grep -q "gladia"
  TEXT=$(text_of "$ID4"); echo "Gladia: $TEXT"
  echo "$TEXT" | grep -iq "revenue"
  curl -sf "$BASE/api/calls/$ID4/doc" | json "d['speakers_separated']" | grep -q True
  curl -sf -X POST "${H[@]}" "$BASE/api/gladia/disconnect" >/dev/null
  echo "✓ Gladia cloud transcription + speakers works"
else
  echo "- skipped Gladia test (no CI_GLADIA_KEY secret)"
fi
if [ -n "${CI_HF_TOKEN:-}" ]; then
  curl -sf -X POST "${H[@]}" -H "Content-Type: application/json" -d "{\"token\": \"$CI_HF_TOKEN\"}" "$BASE/api/hf/connect" | json "d['ok']" | grep -q True
  model_ready() { curl -sf "$BASE/api/setup" | json "d['components']['speaker_model']['state']" | grep -Eq "done|error"; }
  wait_for 900 "speaker models downloaded" model_ready
  curl -sf "$BASE/api/setup" | json "d['components']['speaker_model']" | show | grep -q "'done'"
  curl -sf -X POST "${H[@]}" "$BASE/api/calls/$ID/speakers" >/dev/null
  wait_status "$ID" "ready" 900 >/dev/null
  curl -sf "$BASE/api/calls/$ID" | json "d.get('warnings')"
  curl -sf "$BASE/api/calls/$ID/doc" | json "d['speakers_separated']" | grep -q True
  echo "✓ speaker separation works"
else
  echo "- skipped full speaker separation test (no CI_HF_TOKEN secret)"
fi
echo "✓ all smoke tests passed"
