"""In-app updates from GitHub Releases.

A release tagged vX.Y.Z on github.com/<repo> is a new version. "Install" downloads
that release's source code into Application Support/app/versions/<tag>, points
app/current at it and restarts; the launcher then installs any new
dependencies. If the new version fails to start, the launcher falls back to the
version built into the app.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from . import __version__, config

API = "https://api.github.com/repos/{repo}/releases/latest"
_cache: dict = {}
_install = {"state": "idle", "message": "", "error": None, "version": None}


def parse_version(v: str) -> tuple:
    nums = re.findall(r"\d+", v.split("-")[0])
    return tuple(int(n) for n in nums[:3]) + (0,) * (3 - len(nums[:3]))


def _get(url: str, timeout: float = 15):
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": "ConcallPlayer"})
    return urllib.request.urlopen(req, timeout=timeout)


def check(force: bool = False) -> dict:
    if not force and _cache.get("at", 0) > time.time() - 3600:
        return _cache["result"]
    result = {"current": __version__, "available": False, "app_mode": config.APP_MODE}
    try:
        with _get(API.format(repo=config.GITHUB_REPO)) as r:
            rel = json.loads(r.read())
        latest = rel.get("tag_name", "")
        result.update(
            latest=latest.lstrip("v"),
            notes=rel.get("body") or "",
            url=rel.get("html_url"),
            tarball=rel.get("tarball_url"),
            published=rel.get("published_at"),
            available=parse_version(latest) > parse_version(__version__),
        )
    except urllib.error.HTTPError as exc:
        result["error"] = (
            "No released version found yet (or the GitHub repository is private)." if exc.code == 404 else f"GitHub said {exc.code}."
        )
    except Exception as exc:
        result["error"] = f"Couldn't check for updates (offline?): {exc}"
    _cache.update(at=time.time(), result=result)
    return result


def versions_dir() -> Path:
    return config.SUPPORT_DIR / "app" / "versions"


def install_status() -> dict:
    return dict(_install)


def install() -> dict:
    if not config.APP_MODE:
        return {"state": "error", "error": "Running from source: update with `git pull` instead."}
    if _install["state"] == "running":
        return install_status()
    info = check(force=True)
    if not info.get("available"):
        return {"state": "error", "error": info.get("error") or "You already have the latest version."}

    def run():
        _install.update(state="running", message="Downloading…", error=None, version=info["latest"])
        try:
            dest = versions_dir() / f"v{info['latest']}"
            with tempfile.TemporaryDirectory() as tmp:
                archive = Path(tmp) / "src.tar.gz"
                with _get(info["tarball"], timeout=120) as r, archive.open("wb") as f:
                    shutil.copyfileobj(r, f)
                _install["message"] = "Unpacking…"
                out = Path(tmp) / "x"
                with tarfile.open(archive) as tf:
                    for m in tf.getmembers():
                        if m.name.startswith("/") or ".." in Path(m.name).parts:
                            raise RuntimeError("Unexpected file in update")
                    tf.extractall(out, filter="data")
                roots = [p for p in out.iterdir() if p.is_dir()]
                if len(roots) != 1 or not (roots[0] / "concall" / "__init__.py").exists():
                    raise RuntimeError("Downloaded update doesn't look like Concall Player")
                text = (roots[0] / "concall" / "__init__.py").read_text(encoding="utf-8")
                m = re.search(r'__version__\s*=\s*"([^"]+)"', text)
                if not m or parse_version(m.group(1)) != parse_version(info["latest"]):
                    raise RuntimeError("Update version mismatch")
                if dest.exists():
                    shutil.rmtree(dest)
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(roots[0]), dest)
            (config.SUPPORT_DIR / "app" / "current").write_text(str(dest), encoding="utf-8")
            _cleanup_old(keep=dest)
            _install.update(state="done", message="Installed. Restart to finish.")
        except Exception as exc:
            _install.update(state="error", error=str(exc), message="Failed")

    threading.Thread(target=run, daemon=True, name="updater").start()
    return install_status()


def _cleanup_old(keep: Path) -> None:
    running = Path(__file__).resolve().parent.parent
    for d in versions_dir().iterdir():
        if d.is_dir() and d.resolve() not in (keep.resolve(), running):
            shutil.rmtree(d, ignore_errors=True)


def restart() -> bool:
    """Relaunch the app (the launcher picks up the new version)."""
    if not config.APP_PATH:
        return False
    if config.IS_WINDOWS:
        # Start the launcher again; it waits for this process to exit before checking packages.
        pythonw = Path(sys.executable).with_name("pythonw.exe")
        exe = str(pythonw if pythonw.exists() else sys.executable)
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        subprocess.Popen([exe, config.APP_PATH, "--after-pid", str(os.getpid())], creationflags=flags, close_fds=True)
    else:
        subprocess.Popen(["/bin/sh", "-c", 'sleep 2; /usr/bin/open "$0"', config.APP_PATH], start_new_session=True)
    from . import remote

    remote.shutdown()
    threading.Timer(0.5, lambda: os._exit(0)).start()
    return True
