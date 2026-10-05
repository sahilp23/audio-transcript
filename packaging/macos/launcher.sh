#!/bin/bash
# Concall Player launcher: this script is the app's executable
# ("Concall Player.app/Contents/MacOS/Concall Player").
#
# 1. Picks the code to run: an update installed from inside the app
#    (Application Support/app/current) if it's at least as new as the built-in
#    copy and didn't fail to start last time; otherwise the built-in copy.
# 2. Makes sure Python and the small core packages are installed (uv, bundled
#    with the app, downloads them; first launch only, or after an update).
# 3. Starts the app (concall.desktop). The heavy speech engine is installed by
#    the app itself in the background, with progress shown in its window.
set -u

CONTENTS="$(cd "$(dirname "$0")/.." && pwd)"
APP="$(dirname "$CONTENTS")"
RES="$CONTENTS/Resources"
SUPPORT="${CONCALL_SUPPORT_DIR:-$HOME/Library/Application Support/Concall Player}"
LOGS="$HOME/Library/Logs/Concall Player"
mkdir -p "$SUPPORT/app" "$LOGS"
LOG="$LOGS/app.log"
if [ -f "$LOG" ] && [ "$(wc -c < "$LOG")" -gt 5000000 ]; then mv -f "$LOG" "$LOG.old"; fi
if [ "${CONCALL_LOG_STDOUT:-}" != "1" ]; then exec >>"$LOG" 2>&1; fi
echo "=== $(date '+%Y-%m-%d %H:%M:%S') starting from $APP"

alert() {
  /usr/bin/osascript -e "display alert \"Concall Player\" message \"$1\" as critical buttons {\"OK\"} default button 1" >/dev/null 2>&1 || true
}
notify() {
  /usr/bin/osascript -e "display notification \"$1\" with title \"Concall Player\"" >/dev/null 2>&1 || true
}
ver_of() { sed -n 's/^__version__ = "\(.*\)"/\1/p' "$1/concall/__init__.py" 2>/dev/null | head -1; }
ver_ge() {  # ver_ge A B -> success if version A >= version B
  awk -v a="$1" -v b="$2" 'BEGIN { split(a, x, "."); split(b, y, ".");
    for (i = 1; i <= 3; i++) { if (x[i] + 0 > y[i] + 0) exit 0; if (x[i] + 0 < y[i] + 0) exit 1 } exit 0 }'
}

BUNDLED="$RES/app"
CODE="$BUNDLED"
CURRENT_FILE="$SUPPORT/app/current"
STARTING="$SUPPORT/app/starting"
if [ -f "$CURRENT_FILE" ]; then
  CAND="$(cat "$CURRENT_FILE")"
  if [ -f "$STARTING" ] && [ "$(cat "$STARTING")" = "$CAND" ]; then
    echo "The update in $CAND didn't start last time; using the built-in version"
    rm -f "$CURRENT_FILE"
    alert "The last update didn't start properly, so Concall Player is using its built-in version. Your calls and notes are safe."
  elif [ -f "$CAND/concall/__init__.py" ] && ver_ge "$(ver_of "$CAND")" "$(ver_of "$BUNDLED")"; then
    CODE="$CAND"
  fi
fi
echo "Code: $CODE (version $(ver_of "$CODE"))"

export UV_PYTHON_INSTALL_DIR="$SUPPORT/python"
export UV_CACHE_DIR="$SUPPORT/cache/uv"
export UV_MANAGED_PYTHON=1
export UV_NO_CONFIG=1
UV="$RES/uv"
VENV="$SUPPORT/venv"
PY="$VENV/bin/python"
STAMP="$VENV/.core-requirements"
WANT="$(/usr/bin/shasum -a 256 "$CODE/requirements.txt" | cut -c1-16)"

if [ ! -x "$PY" ] || [ "$(cat "$STAMP" 2>/dev/null)" != "$WANT" ]; then
  if [ ! -x "$PY" ]; then
    notify "Getting ready for the first time (about a minute)…"
    if ! "$UV" venv --python 3.12 "$VENV"; then
      alert "Concall Player couldn't download its setup files. Check your internet connection and open the app again."
      exit 1
    fi
  else
    notify "Finishing the update…"
  fi
  if ! "$UV" pip install --python "$PY" -r "$CODE/requirements.txt"; then
    alert "Concall Player couldn't download its setup files. Check your internet connection and open the app again. (Details are in ~/Library/Logs/Concall Player)"
    exit 1
  fi
  echo "$WANT" > "$STAMP"
fi

# The app deletes this marker once it has started; if it's still here next time,
# the update it names gets rolled back (see above).
echo "$CODE" > "$STARTING"

export CONCALL_APP=1
export CONCALL_UV="$UV"
export CONCALL_APP_PATH="$APP"
export CONCALL_SUPPORT_DIR="$SUPPORT"
export CONCALL_ICON="$RES/AppIcon.icns"
export PYTHONPATH="$CODE"
export PYTHONDONTWRITEBYTECODE=1
export PYTHONUNBUFFERED=1
cd "$CODE" || exit 1
exec "$PY" -m concall.desktop
