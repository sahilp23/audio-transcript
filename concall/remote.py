"""Use the app from another computer (e.g. the office PC) through a secure web link.

How it works:
  * A second copy of the web server listens on its own local port. Everything
    that arrives on that port came from outside, so the server can treat it
    differently (login required, Mac-only actions blocked; see server.py).
  * Cloudflare's free "quick tunnel" (the cloudflared program, downloaded on
    first use and checked against a pinned checksum) connects that port to a
    random https://<words>.trycloudflare.com link. No Cloudflare account needed.
  * Two locks: Cloudflare only lets in the configured email address (one-time
    code by email, the --allowed-mail option of cloudflared 2026.9.2+), and the
    app asks for its own password (session cookie, 30 days).
  * While it's on, the Mac is kept awake (caffeinate), as long as the lid is open.

The link changes whenever the tunnel restarts (e.g. after the app restarts).
"""

import hashlib
import hmac
import os
import re
import secrets
import shutil
import socket
import subprocess
import tarfile
import tempfile
import threading
import time
import urllib.request
from collections import deque
from pathlib import Path
from typing import Optional

from . import __version__, config

CLOUDFLARED_VERSION = "2026.10.0"
_RELEASE = f"https://github.com/cloudflare/cloudflared/releases/download/{CLOUDFLARED_VERSION}/"
# (download name, sha256) per platform; checksums computed from the official release files.
DOWNLOADS = {
    ("Darwin", "arm64"): ("cloudflared-darwin-arm64.tgz",
                          "a2f79ff7b9420aa537d74af239f376da170bbabeb529aec416002adac6a72e70"),
    ("Windows", "AMD64"): ("cloudflared-windows-amd64.exe",
                           "86aee4017b26625cee8484c113558f48effa4cd47f7aa05fcf425604e5d2b23c"),
    ("Linux", "x86_64"): ("cloudflared-linux-amd64",
                          "d33ff2d14475178d2012c2c56beba87389ac5ded27649519f198a7d3134a99db"),
}
URL_RE = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
SESSION_COOKIE = "concall_session"
SESSION_DAYS = 30
MIN_PASSWORD = 8
MAX_FAILS = 5  # wrong passwords allowed per 10 minutes, before logins pause
PBKDF2_ROUNDS = 300_000

_lock = threading.RLock()
_state = {"state": "off", "url": None, "error": None, "message": ""}
_proc: Optional[subprocess.Popen] = None
_awake: Optional[subprocess.Popen] = None
_server = None  # uvicorn.Server for the remote port
_port: Optional[int] = None
_fails: deque = deque()


# ---------- password and sessions ----------

def hash_password(password: str, salt: Optional[str] = None) -> str:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), PBKDF2_ROUNDS).hex()
    return f"pbkdf2${PBKDF2_ROUNDS}${salt}${digest}"


def _password_ok(password: str, stored: str) -> bool:
    try:
        _, rounds, salt, digest = stored.split("$")
        check = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(rounds)).hex()
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(check, digest)


def _session_key(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()  # only hashes of session tokens are stored


def login(password: str) -> Optional[str]:
    """Returns a new session token, or None. Raises PermissionError while logins are paused."""
    now = time.time()
    with _lock:
        while _fails and _fails[0] < now - 600:
            _fails.popleft()
        if len(_fails) >= MAX_FAILS:
            raise PermissionError("Too many wrong passwords. Try again in 10 minutes.")
        stored = config.load_settings()["remote_password"]
        if not stored or not _password_ok(password or "", stored):
            _fails.append(now)
            return None
        token = secrets.token_urlsafe(32)
        sessions = {k: v for k, v in config.load_settings()["remote_sessions"].items() if v > now}
        sessions[_session_key(token)] = now + SESSION_DAYS * 86400
        config.save_settings({"remote_sessions": sessions})
        return token


def session_valid(token: Optional[str]) -> bool:
    if not token:
        return False
    expiry = config.load_settings()["remote_sessions"].get(_session_key(token))
    return bool(expiry and expiry > time.time())


def logout(token: Optional[str]) -> None:
    if not token:
        return
    with _lock:
        sessions = dict(config.load_settings()["remote_sessions"])
        sessions.pop(_session_key(token), None)
        config.save_settings({"remote_sessions": sessions})


def configure(email: str, password: str) -> dict:
    """Save the allowed email and (if given) a new password. Signs out all remote sessions."""
    email = (email or "").strip().lower()
    if not EMAIL_RE.match(email):
        return {"ok": False, "error": "Enter the email address you'll use to sign in (you'll get a code there)."}
    patch = {"remote_email": email}
    if password:
        if len(password) < MIN_PASSWORD:
            return {"ok": False, "error": f"Choose a password of at least {MIN_PASSWORD} characters."}
        patch.update(remote_password=hash_password(password), remote_sessions={})
    elif not config.load_settings()["remote_password"]:
        return {"ok": False, "error": "Choose a password."}
    config.save_settings(patch)
    if _state["state"] in ("on", "starting"):
        restart()  # the email lock is part of the tunnel: restart it with the new address
    return {"ok": True}


# ---------- is this request from outside? ----------

def port() -> Optional[int]:
    return _port


def is_remote(scope: dict) -> bool:
    server = scope.get("server") or (None, None)
    return _port is not None and server[1] == _port


# ---------- cloudflared ----------

def binary_path() -> Path:
    return config.BIN_DIR / ("cloudflared.exe" if config.IS_WINDOWS else "cloudflared")


def _platform_download() -> tuple[str, str]:
    import platform

    key = (platform.system(), platform.machine())
    if key not in DOWNLOADS:
        raise RuntimeError(f"Remote access isn't available on this computer ({key[0]} {key[1]}).")
    return DOWNLOADS[key]


def ensure_cloudflared() -> Path:
    """Download cloudflared once (checked against the pinned checksum)."""
    dest = binary_path()
    stamp = dest.with_suffix(".version")
    if dest.exists() and stamp.exists() and stamp.read_text(encoding="utf-8").strip() == CLOUDFLARED_VERSION:
        return dest
    name, sha = _platform_download()
    _state["message"] = "Downloading Cloudflare's connector (about 20–50 MB, first time only)…"
    config.BIN_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        file = Path(tmp) / name
        req = urllib.request.Request(_RELEASE + name, headers={"User-Agent": f"ConcallPlayer/{__version__}"})
        with urllib.request.urlopen(req, timeout=300) as r, file.open("wb") as f:
            shutil.copyfileobj(r, f)
        if hashlib.sha256(file.read_bytes()).hexdigest() != sha:
            raise RuntimeError("The downloaded Cloudflare connector didn't match its checksum, so it wasn't used.")
        if name.endswith(".tgz"):
            with tarfile.open(file) as tf:
                member = tf.getmember("cloudflared")
                with tf.extractfile(member) as src, open(Path(tmp) / "cloudflared", "wb") as out:
                    shutil.copyfileobj(src, out)
            file = Path(tmp) / "cloudflared"
        shutil.copyfile(file, dest)
    os.chmod(dest, 0o755)
    stamp.write_text(CLOUDFLARED_VERSION, encoding="utf-8")
    return dest


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _start_server() -> int:
    """The remote-facing copy of the web server, on its own local port."""
    global _server, _port
    if _server is not None and _port is not None:
        return _port
    import uvicorn

    from .server import app

    p = _free_port()
    _server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=p, log_level="warning", lifespan="off"))
    threading.Thread(target=_server.run, daemon=True, name="remote-server").start()
    for _ in range(100):
        if _server.started:
            break
        time.sleep(0.05)
    _port = p
    return p


def _stop_server() -> None:
    global _server, _port
    if _server is not None:
        _server.should_exit = True
    _server, _port = None, None


def _keep_awake(on: bool) -> None:
    global _awake
    if on and config.IS_MAC and _awake is None and shutil.which("caffeinate"):
        # -i: no idle sleep, -s: no system sleep while on power. Ends when the app quits.
        _awake = subprocess.Popen(["caffeinate", "-i", "-s", "-w", str(os.getpid())])
    elif not on and _awake is not None:
        _awake.terminate()
        _awake = None


def _run_tunnel(generation: int) -> None:
    """Start cloudflared and watch it; restart it if it stops while remote access is on."""
    global _proc
    delay = 10
    while _generation == generation and config.load_settings()["remote_enabled"]:
        try:
            exe = ensure_cloudflared()
            local_port = _start_server()
            email = config.load_settings()["remote_email"]
            _state.update(message="Connecting to Cloudflare…", url=None)
            cmd = [str(exe), "tunnel", "--no-autoupdate", "--url", f"http://127.0.0.1:{local_port}",
                   "--allowed-mail", email]
            flags = 0x08000000 if config.IS_WINDOWS else 0  # CREATE_NO_WINDOW
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
                                    encoding="utf-8", errors="replace", creationflags=flags)
            with _lock:
                _proc = proc
            tail: list[str] = []
            for line in proc.stdout:  # type: ignore[union-attr]
                line = line.rstrip()
                if not line:
                    continue
                print(f"[tunnel] {line}", flush=True)
                tail = (tail + [line])[-5:]
                m = URL_RE.search(line)
                if m and not _state["url"] and m.group(0).split("//")[1].split(".")[0] not in ("api", "login", "www"):
                    _state.update(state="on", url=m.group(0), error=None, message="")
                    delay = 10
            code = proc.wait()
            if _generation != generation:
                return
            reason = next((t for t in reversed(tail) if "ERR" in t or "fail" in t.lower()), tail[-1] if tail else "")
            _state.update(state="starting", url=None,
                          message=f"Cloudflare connection stopped (code {code}); reconnecting…",
                          error=reason[-300:] or None)
        except Exception as exc:
            if _generation != generation:
                return
            _state.update(state="error", url=None, error=str(exc), message="Retrying in a moment…")
        time.sleep(delay)
        delay = min(delay * 2, 300)


_generation = 0


def start() -> dict:
    global _generation
    s = config.load_settings()
    if not s["remote_email"] or not s["remote_password"]:
        return {**status(), "ok": False, "error": "Set your email and a password first."}
    config.save_settings({"remote_enabled": True})
    with _lock:
        if _state["state"] in ("on", "starting") and _proc is not None and _proc.poll() is None:
            return {**status(), "ok": True}
        _generation += 1
        gen = _generation
        _state.update(state="starting", url=None, error=None, message="Starting…")
    _keep_awake(True)
    threading.Thread(target=_run_tunnel, args=(gen,), daemon=True, name="remote-tunnel").start()
    return {**status(), "ok": True}


def _stop_tunnel() -> None:
    global _generation, _proc
    with _lock:
        _generation += 1
        proc, _proc = _proc, None
    if proc is not None and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


def stop() -> dict:
    config.save_settings({"remote_enabled": False})
    _stop_tunnel()
    _stop_server()
    _keep_awake(False)
    _state.update(state="off", url=None, error=None, message="")
    return {**status(), "ok": True}


def shutdown() -> None:
    """The app is quitting: close the tunnel but remember that it should be on next time."""
    _stop_tunnel()
    _keep_awake(False)


def restart() -> None:
    _stop_tunnel()
    start()


def autostart() -> None:
    """Called when the app opens: resume remote access if it was on."""
    if config.load_settings()["remote_enabled"]:
        start()


def status() -> dict:
    s = config.load_settings()
    return {
        **_state,
        "enabled": bool(s["remote_enabled"]),
        "email": s["remote_email"],
        "has_password": bool(s["remote_password"]),
        "available": _available(),
    }


def _available() -> bool:
    try:
        _platform_download()
        return True
    except RuntimeError:
        return False
