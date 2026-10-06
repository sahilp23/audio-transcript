"""Concall Player launcher for Windows (the Start-menu shortcut runs this with pythonw).

The Windows counterpart of packaging/macos/launcher.sh. Uses only the standard
library, because it may run before the app's packages are installed.

1. Picks the code to run: an update installed from inside the app
   (%LOCALAPPDATA%\\Concall Player\\app\\current) if it's at least as new as the
   installed copy and didn't fail to start last time; otherwise the installed copy.
2. Makes sure the small core packages match that code's requirements.txt
   (the bundled uv.exe installs them; the installer already did this once).
3. Starts the app (concall.desktop) and waits for it to close.

Option: --after-pid N waits for process N to exit first (used to restart after an update).
"""

import hashlib
import os
import re
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent  # the install folder
BUNDLED = HERE / "app"
UV = HERE / "uv.exe"
LOCAL = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
SUPPORT = Path(os.environ.get("CONCALL_SUPPORT_DIR") or LOCAL / "Concall Player")
LOGS = SUPPORT / "logs"
VENV = SUPPORT / "venv"
PY = VENV / "Scripts" / "python.exe"
PYW = VENV / "Scripts" / "pythonw.exe"
STAMP = VENV / ".core-requirements"
CURRENT_FILE = SUPPORT / "app" / "current"
STARTING = SUPPORT / "app" / "starting"


def alert(message: str) -> None:
    print("ALERT:", message, flush=True)
    if os.environ.get("CONCALL_HEADLESS") == "1":
        return
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, message, "Concall Player", 0x30)
    except Exception:
        pass


def version_of(code: Path) -> tuple:
    try:
        text = (code / "concall" / "__init__.py").read_text(encoding="utf-8")
    except OSError:
        return (0, 0, 0)
    m = re.search(r'__version__\s*=\s*"([^"]+)"', text)
    nums = re.findall(r"\d+", m.group(1)) if m else []
    return tuple(int(n) for n in nums[:3]) + (0,) * (3 - len(nums[:3]))


def wait_for_pid(pid: int, timeout: float = 30) -> None:
    try:
        import ctypes

        SYNCHRONIZE = 0x00100000
        handle = ctypes.windll.kernel32.OpenProcess(SYNCHRONIZE, False, pid)
        if handle:
            ctypes.windll.kernel32.WaitForSingleObject(handle, int(timeout * 1000))
            ctypes.windll.kernel32.CloseHandle(handle)
    except Exception:
        time.sleep(3)


def pick_code() -> Path:
    code = BUNDLED
    if CURRENT_FILE.exists():
        cand = Path(CURRENT_FILE.read_text(encoding="utf-8").strip())
        last_try = STARTING.read_text(encoding="utf-8").strip() if STARTING.exists() else ""
        if last_try and Path(last_try) == cand:
            print(f"The update in {cand} didn't start last time; using the installed version", flush=True)
            CURRENT_FILE.unlink(missing_ok=True)
            alert("The last update didn't start properly, so Concall Player is using its installed version. "
                  "Your calls and notes are safe.")
        elif (cand / "concall" / "__init__.py").exists() and version_of(cand) >= version_of(BUNDLED):
            code = cand
    return code


def uv_env() -> dict:
    return {
        **os.environ,
        "UV_PYTHON_INSTALL_DIR": str(SUPPORT / "python"),
        "UV_CACHE_DIR": str(SUPPORT / "cache" / "uv"),
        "UV_MANAGED_PYTHON": "1",
        "UV_NO_CONFIG": "1",
    }


def ensure_packages(code: Path) -> bool:
    req = code / "requirements.txt"
    want = hashlib.sha256(req.read_bytes()).hexdigest()[:16]
    have = STAMP.read_text(encoding="utf-8").strip() if STAMP.exists() else ""
    if PY.exists() and have == want:
        return True
    hidden = 0x08000000  # CREATE_NO_WINDOW: no console window popping up
    if not PY.exists():
        if subprocess.call([str(UV), "venv", "--allow-existing", "--python", "3.12", str(VENV)],
                           env=uv_env(), creationflags=hidden, stdout=sys.stdout, stderr=sys.stderr) != 0:
            return False
    if subprocess.call([str(UV), "pip", "install", "--python", str(PY), "-r", str(req)],
                       env=uv_env(), creationflags=hidden, stdout=sys.stdout, stderr=sys.stderr) != 0:
        return False
    STAMP.write_text(want, encoding="utf-8")
    return True


def main() -> int:
    LOGS.mkdir(parents=True, exist_ok=True)
    (SUPPORT / "app").mkdir(parents=True, exist_ok=True)
    log = LOGS / "app.log"
    if log.exists() and log.stat().st_size > 5_000_000:
        os.replace(log, LOGS / "app.log.old")
    if os.environ.get("CONCALL_LOG_STDOUT") != "1":
        # pythonw has no console: send everything to the log file.
        out = open(log, "a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stderr = out
    print(f"=== {time.strftime('%Y-%m-%d %H:%M:%S')} starting from {HERE}", flush=True)

    args = sys.argv[1:]
    if len(args) >= 2 and args[0] == "--after-pid":
        wait_for_pid(int(args[1]))

    code = pick_code()
    print(f"Code: {code} (version {'.'.join(map(str, version_of(code)))})", flush=True)

    if not ensure_packages(code):
        alert("Concall Player couldn't download its setup files. Check your internet connection and open the app "
              f"again. (Details are in {LOGS})")
        return 1

    # The app deletes this marker once it has started; if it's still here next time,
    # the update it names gets rolled back (see pick_code).
    STARTING.write_text(str(code), encoding="utf-8")

    env = {
        **os.environ,
        "CONCALL_APP": "1",
        "CONCALL_UV": str(UV),
        "CONCALL_APP_PATH": str(Path(__file__).resolve()),
        "CONCALL_SUPPORT_DIR": str(SUPPORT),
        "CONCALL_LOG_DIR": str(LOGS),
        "CONCALL_ICON": str(HERE / "icon.ico"),
        "PYTHONPATH": str(code),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONUNBUFFERED": "1",
        "PYTHONUTF8": "1",
    }
    exe = PY if os.environ.get("CONCALL_LOG_STDOUT") == "1" else (PYW if PYW.exists() else PY)
    return subprocess.call([str(exe), "-m", "concall.desktop"], cwd=str(code), env=env,
                           stdout=sys.stdout, stderr=sys.stderr)


if __name__ == "__main__":
    sys.exit(main())
