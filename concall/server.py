"""Local web server: `python -m concall` then open http://127.0.0.1:8765"""

import os
import platform
import shutil
import subprocess
import threading
import time
import webbrowser
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from . import (__version__, asr, cloud, components, config, diarize, gladia, hf, isolated, media, pipeline, remote, report,
               store, summarize, transcript_parser, updater)

STATIC = Path(__file__).parent / "static"
TRANSCRIPT_TYPES = {".pdf", ".txt", ".md", ".text"}


@asynccontextmanager
async def lifespan(_app):
    pipeline.start_worker()
    yield


app = FastAPI(title="Concall Player", lifespan=lifespan)

ALLOWED_HOSTS = {"127.0.0.1", "localhost"}


# Things that only make sense, or are only safe, on the computer running the app.
REMOTE_BLOCKED = ("/api/open", "/api/reveal", "/api/clipboard", "/api/export", "/api/update/install",
                  "/api/update/restart", "/api/remote", "/api/setup/", "/api/hf/", "/api/groq/", "/api/gladia/")
REMOTE_OPEN = ("/login", "/api/remote/login", "/api/ping")


@app.middleware("http")
async def local_only(request: Request, call_next):
    # Only this app's own page may call the API: block other websites open in a
    # browser (custom header => cross-site requests are refused) and DNS rebinding.
    path = request.url.path
    if request.method not in ("GET", "HEAD", "OPTIONS") and path.startswith("/api/"):
        if request.headers.get("x-concall") != "1":
            return JSONResponse({"detail": "Missing app header"}, status_code=403)
    host = (request.headers.get("host") or "").rsplit(":", 1)[0]
    if remote.is_remote(request.scope):
        # Arrived through the Cloudflare link (see remote.py): sign-in required.
        if not host.endswith(".trycloudflare.com") and host != "testserver":
            return JSONResponse({"detail": "Forbidden host"}, status_code=403)
        if path not in REMOTE_OPEN and not remote.session_valid(request.cookies.get(remote.SESSION_COOKIE)):
            if path.startswith("/api/"):
                return JSONResponse({"detail": "Please sign in again"}, status_code=401)
            return RedirectResponse("/login", status_code=302)
        if path not in ("/api/remote/login", "/api/remote/logout") and (
                any(path.startswith(p) for p in REMOTE_BLOCKED)
                or (path == "/api/settings" and request.method != "GET")):
            return JSONResponse({"detail": f"This can only be done on the {config.DEVICE} running Concall Player."},
                                status_code=403)
        return await call_next(request)
    if host not in ALLOWED_HOSTS and host != "testserver":
        return JSONResponse({"detail": "Forbidden host"}, status_code=403)
    if path == "/login":
        return RedirectResponse("/", status_code=302)
    return await call_next(request)


def _meta_or_404(call_id: str) -> dict:
    try:
        return store.get_meta(call_id)
    except KeyError:
        raise HTTPException(404, "Call not found")


def _save_upload(upload: UploadFile, dest: Path) -> None:
    with dest.open("wb") as f:
        shutil.copyfileobj(upload.file, f, length=1024 * 1024)


def _store_official(call_id: str, transcript: Optional[UploadFile], transcript_text: Optional[str]) -> dict:
    d = store.call_dir(call_id)
    if transcript is not None and transcript.filename:
        ext = Path(transcript.filename).suffix.lower()
        if ext not in TRANSCRIPT_TYPES:
            raise HTTPException(400, f"Transcript must be PDF or text (got {ext})")
        src = d / f"official_source{ext}"
        _save_upload(transcript, src)
        parsed = transcript_parser.parse_file(src)
    elif transcript_text and transcript_text.strip():
        (d / "official_source.txt").write_text(transcript_text, encoding="utf-8")
        parsed = transcript_parser.parse_text(transcript_text)
    else:
        raise HTTPException(400, "No transcript provided")
    if not parsed["turns"]:
        raise HTTPException(400, "Couldn't find any 'Speaker: text' sections in that transcript")
    store.write_json(d / "official.json", parsed)
    return parsed


@app.get("/api/ping")
def ping():
    return {"ok": True}


@app.get("/api/status")
def status(request: Request):
    engine = asr.pick_engine()
    return {
        "remote": remote.is_remote(request.scope),
        "version": __version__,
        "app_mode": config.APP_MODE,
        "platform": platform.system().lower(),
        "asr_engine": engine,
        "asr_model": config.MLX_MODEL if engine == "mlx" else config.FASTER_WHISPER_MODEL,
        "diarization": diarize.available() or "ready",
        "ollama": summarize.ollama_status(),
        "data_dir": str(config.DATA_DIR),
    }


@app.get("/api/setup")
def setup_status():
    key = config.groq_key()
    gkey = config.gladia_key()
    return {
        "components": components.status(),
        "hf": hf.status(),
        "gladia": {"connected": bool(gkey), "key_hint": (gkey[:4] + "…" + gkey[-4:]) if gkey else "",
                   "signup_url": gladia.SIGNUP_PAGE,
                   "paused": time.time() < float(config.load_settings().get("gladia_paused_until") or 0)},
        "groq": {"connected": bool(key), "key_hint": (key[:4] + "…" + key[-4:]) if key else "",
                 "signup_url": cloud.SIGNUP_PAGE, "keys_url": cloud.KEYS_PAGE},
        "mac": {"ram_gb": round(config.total_ram_gb()), "gentle": config.gentle_mode(),
                "mode": config.load_settings()["mac_mode"]},
    }


@app.post("/api/groq/connect")
def groq_connect(body: dict):
    key = str(body.get("key") or "").strip()
    result = cloud.check_key(key)
    if result["ok"]:
        config.save_settings({"groq_key": key})
        # Calls that were waiting because Groq wasn't connected can go now.
        for meta in store.list_calls():
            if meta.get("status") == "needs_input" and not meta.get("asr_route"):
                pipeline.decide(meta["id"], "retry")
    return result


@app.post("/api/gladia/connect")
def gladia_connect(body: dict):
    key = str(body.get("key") or "").strip()
    result = gladia.check_key(key)
    if result["ok"]:
        config.save_settings({"gladia_key": key, "gladia_paused_until": 0})
        for meta in store.list_calls():
            if meta.get("status") == "needs_input" and not meta.get("asr_route"):
                pipeline.decide(meta["id"], "retry")
    return result


@app.post("/api/gladia/disconnect")
def gladia_disconnect():
    config.save_settings({"gladia_key": "", "gladia_paused_until": 0})
    return {"ok": True}


@app.post("/api/groq/disconnect")
def groq_disconnect():
    config.save_settings({"groq_key": ""})
    return {"ok": True}


@app.post("/api/setup/{what}")
def setup_start(what: str):
    if what in ("engine", "speakers"):
        components.install(what)
    elif what == "speech_model":
        components.download_speech_model()
    elif what == "speaker_model":
        hf.start_setup()
    else:
        raise HTTPException(404, "Unknown component")
    return components.status()


@app.post("/api/hf/connect")
def hf_connect(body: dict):
    return hf.connect(str(body.get("token") or ""))


@app.post("/api/hf/check")
def hf_check():
    return hf.recheck()


@app.post("/api/hf/disconnect")
def hf_disconnect():
    hf.disconnect()
    return hf.status()


@app.get("/api/settings")
def get_settings():
    s = config.load_settings()
    return _public_settings(s)


def _public_settings(s: dict) -> dict:
    for secret in ("hf_token", "groq_key", "gladia_key", "remote_password", "remote_sessions"):
        s.pop(secret, None)
    return s


@app.patch("/api/settings")
def patch_settings(body: dict):
    allowed = {k: v for k, v in body.items() if k in ("diarization", "auto_update_check", "ollama_model", "mac_mode")}
    if "mac_mode" in allowed and allowed["mac_mode"] not in ("auto", "gentle", "fast"):
        raise HTTPException(400, "mac_mode must be auto, gentle or fast")
    return _public_settings(config.save_settings(allowed))


@app.get("/api/remote")
def remote_status():
    return remote.status()


@app.post("/api/remote/setup")
def remote_setup(body: dict):
    return remote.configure(str(body.get("email") or ""), str(body.get("password") or ""))


@app.post("/api/remote/start")
def remote_start():
    return remote.start()


@app.post("/api/remote/stop")
def remote_stop():
    return remote.stop()


@app.post("/api/remote/email")
def remote_email_link():
    """Open a new email to yourself with the current link (in the Mail app)."""
    st = remote.status()
    if not st["url"] or not st["email"]:
        raise HTTPException(400, "The link isn't ready yet")
    from urllib.parse import quote

    body = f"Your Concall Player link (works while your {config.DEVICE} is on):\n{st['url']}"
    _open(f"mailto:{st['email']}?subject={quote('Concall Player link')}&body={quote(body)}")
    return {"ok": True}


@app.post("/api/remote/login")
def remote_login(body: dict):
    try:
        token = remote.login(str(body.get("password") or ""))
    except PermissionError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=429)
    if not token:
        return JSONResponse({"ok": False, "error": "Wrong password."}, status_code=401)
    resp = JSONResponse({"ok": True})
    resp.set_cookie(remote.SESSION_COOKIE, token, max_age=remote.SESSION_DAYS * 86400, httponly=True,
                    secure=True, samesite="lax", path="/")
    return resp


@app.post("/api/remote/logout")
def remote_logout(request: Request):
    remote.logout(request.cookies.get(remote.SESSION_COOKIE))
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(remote.SESSION_COOKIE, path="/")
    return resp


@app.get("/login")
def login_page():
    return HTMLResponse((STATIC / "login.html").read_text(encoding="utf-8"))


@app.get("/api/update")
def update_check(force: bool = False):
    return {**updater.check(force=force), "install": updater.install_status()}


@app.post("/api/update/install")
def update_install():
    return updater.install()


@app.post("/api/update/restart")
def update_restart():
    if not updater.restart():
        raise HTTPException(400, "Restart isn't available when running from source")
    return {"ok": True}


OPEN_HOSTS = {"huggingface.co", "ollama.com", "github.com", "brew.sh", "groq.com", "gladia.io"}


def _open(target: str) -> None:
    if config.IS_MAC:
        subprocess.Popen(["/usr/bin/open", target])
    elif config.IS_WINDOWS and not target.startswith("http"):
        os.startfile(target)  # a folder: opens File Explorer
    else:
        webbrowser.open(target)


@app.post("/api/open")
def open_url(body: dict):
    url = str(body.get("url") or "")
    host = urlparse(url).hostname or ""
    if urlparse(url).scheme != "https" or not any(host == h or host.endswith("." + h) for h in OPEN_HOSTS):
        raise HTTPException(400, "Not an allowed link")
    _open(url)
    return {"ok": True}


@app.post("/api/reveal")
def reveal(body: dict):
    what = body.get("what")
    target = {"data": config.DATA_DIR, "logs": config.LOG_DIR}.get(what)
    if target is None:
        raise HTTPException(400, "Unknown folder")
    target.mkdir(parents=True, exist_ok=True)
    _open(str(target))
    return {"ok": True, "path": str(target)}


@app.post("/api/export")
def export(body: dict):
    """Save text to ~/Downloads (the app window can't do browser downloads)."""
    name = Path(str(body.get("filename") or "transcript.md")).name.replace("/", "-") or "transcript.md"
    downloads = Path.home() / "Downloads"
    downloads.mkdir(exist_ok=True)
    stem, suffix = os.path.splitext(name)
    path = downloads / name
    n = 1
    while path.exists():
        n += 1
        path = downloads / f"{stem} ({n}){suffix}"
    path.write_text(str(body.get("text") or ""), encoding="utf-8")
    if config.IS_MAC:
        subprocess.Popen(["/usr/bin/open", "-R", str(path)])
    elif config.IS_WINDOWS:
        subprocess.Popen(["explorer", f"/select,{path}"])
    return {"ok": True, "path": str(path)}


@app.post("/api/report")
def make_report(body: dict):
    context = body.get("context") or {}
    if not isinstance(context, dict):
        context = {}
    return report.build(str(body.get("description") or ""), {str(k): str(v)[:2000] for k, v in context.items()})


@app.post("/api/clipboard")
def clipboard(body: dict):
    text = str(body.get("text") or "")
    if config.IS_MAC:
        subprocess.run(["/usr/bin/pbcopy"], input=text, text=True, check=True)
    elif config.IS_WINDOWS:
        # clip.exe reads UTF-16 to keep ₹ and other non-ASCII characters intact.
        subprocess.run(["clip"], input=text.encode("utf-16"), check=True)
    else:
        raise HTTPException(400, "Clipboard helper isn't available here")
    return {"ok": True}


@app.get("/api/calls")
def list_calls():
    return store.list_calls()


@app.post("/api/calls")
def create_call(
    company: str = Form(...),
    period: str = Form(""),
    date: str = Form(""),
    audio: UploadFile = File(...),
    transcript: Optional[UploadFile] = File(None),
    transcript_text: Optional[str] = Form(None),
):
    ext = Path(audio.filename or "audio.mp3").suffix.lower() or ".mp3"
    meta = store.create_call(company, period, date, f"audio{ext}")
    d = store.call_dir(meta["id"])
    _save_upload(audio, d / meta["audio_file"])
    if (transcript is not None and transcript.filename) or (transcript_text and transcript_text.strip()):
        try:
            _store_official(meta["id"], transcript, transcript_text)
        except HTTPException as exc:
            store.update_meta(meta["id"], upload_warnings=[f"Transcript ignored: {exc.detail}"],
                              warnings=[f"Transcript ignored: {exc.detail}"])
    pipeline.enqueue(meta["id"])
    return store.get_meta(meta["id"])


@app.get("/api/calls/{call_id}")
def get_call(call_id: str):
    return _meta_or_404(call_id)


@app.patch("/api/calls/{call_id}")
def edit_call(call_id: str, body: dict):
    _meta_or_404(call_id)
    allowed = {k: str(v) for k, v in body.items() if k in ("company", "period", "date")}
    return store.update_meta(call_id, **allowed)


@app.delete("/api/calls/{call_id}")
def delete_call(call_id: str):
    meta = _meta_or_404(call_id)
    if meta.get("status") == "processing":
        raise HTTPException(409, "Can't delete while it's processing")
    shutil.rmtree(store.call_dir(call_id))
    return {"ok": True}


@app.post("/api/calls/{call_id}/retry")
def retry(call_id: str):
    _meta_or_404(call_id)
    store.update_meta(call_id, decision=None)
    pipeline.enqueue(call_id)
    return store.get_meta(call_id)


@app.post("/api/calls/{call_id}/retranscribe")
def retranscribe(call_id: str):
    meta = _meta_or_404(call_id)
    if meta.get("status") in ("queued", "processing"):
        raise HTTPException(409, "Already processing")
    d = store.call_dir(call_id)
    for name in ("asr.json", "diar.json"):
        (d / name).unlink(missing_ok=True)
    pipeline.enqueue(call_id)
    return store.get_meta(call_id)


@app.post("/api/calls/{call_id}/decision")
def decision(call_id: str, body: dict):
    _meta_or_404(call_id)
    try:
        return pipeline.decide(call_id, str(body.get("choice")))
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.post("/api/calls/{call_id}/enhance")
def enhance(call_id: str):
    """Make a cleaned-up copy of the audio for "Clear voice" playback."""
    meta = _meta_or_404(call_id)
    if meta.get("enhanced") in ("ready", "running"):
        return {"state": meta["enhanced"]}
    store.update_meta(call_id, enhanced="running")
    d = store.call_dir(call_id)
    src = d / (meta.get("play_file") or meta["audio_file"])

    def run():
        part = d / "enhanced.part.m4a"
        try:
            media.run("-i", str(src), "-vn", "-ac", "1", "-af", media.CLEAR_VOICE_FILTER,
                      "-c:a", "aac", "-b:a", "96k", str(part))
            os.replace(part, d / "enhanced.m4a")
            store.update_meta(call_id, enhanced="ready")
        except Exception as exc:
            part.unlink(missing_ok=True)
            store.update_meta(call_id, enhanced="error", enhanced_error=str(exc))

    threading.Thread(target=run, daemon=True).start()
    return {"state": "running"}


@app.post("/api/calls/{call_id}/skip_speakers")
def skip_speakers(call_id: str):
    _meta_or_404(call_id)
    return {"stopped": isolated.cancel(call_id)}


@app.post("/api/calls/{call_id}/speakers")
def detect_speakers(call_id: str):
    """Re-run speaker separation only (e.g. after connecting Hugging Face)."""
    meta = _meta_or_404(call_id)
    if meta.get("status") in ("queued", "processing"):
        raise HTTPException(409, "Already processing")
    reason = diarize.available()
    if reason:
        raise HTTPException(400, f"Speaker separation is off: {reason}")
    (store.call_dir(call_id) / "diar.json").unlink(missing_ok=True)
    pipeline.enqueue(call_id)
    return store.get_meta(call_id)


@app.get("/api/calls/{call_id}/doc")
def get_doc(call_id: str):
    _meta_or_404(call_id)
    doc = store.read_json(store.call_dir(call_id) / "doc.json")
    if doc is None:
        raise HTTPException(404, "Transcript not ready yet")
    return JSONResponse(doc)


@app.get("/api/calls/{call_id}/audio")
def get_audio(call_id: str, clear: bool = False):
    meta = _meta_or_404(call_id)
    d = store.call_dir(call_id)
    path = d / "enhanced.m4a" if clear and (d / "enhanced.m4a").exists() else d / (meta.get("play_file") or meta["audio_file"])
    return FileResponse(path)


@app.post("/api/calls/{call_id}/transcript")
def attach_transcript(
    call_id: str,
    transcript: Optional[UploadFile] = File(None),
    transcript_text: Optional[str] = Form(None),
):
    _meta_or_404(call_id)
    parsed = _store_official(call_id, transcript, transcript_text)
    pipeline.rebuild_async(call_id)
    return {"turns": len(parsed["turns"]), "speakers": sorted({t["speaker"] for t in parsed["turns"]})}


@app.delete("/api/calls/{call_id}/transcript")
def remove_transcript(call_id: str):
    _meta_or_404(call_id)
    d = store.call_dir(call_id)
    (d / "official.json").unlink(missing_ok=True)
    if not (d / "diar.json").exists() and diarize.wanted():
        pipeline.enqueue(call_id)  # speakers weren't separated yet; do it now
    else:
        pipeline.rebuild_async(call_id)
    return {"ok": True}


@app.get("/api/calls/{call_id}/user")
def get_user(call_id: str):
    _meta_or_404(call_id)
    return store.get_user(call_id)


@app.patch("/api/calls/{call_id}/user")
def patch_user(call_id: str, body: dict):
    _meta_or_404(call_id)
    allowed = {k: v for k, v in body.items() if k in ("bookmarks", "speakers", "position", "notes", "rate", "clear")}
    return store.update_user(call_id, allowed)


@app.get("/api/calls/{call_id}/summary")
def get_summary(call_id: str):
    _meta_or_404(call_id)
    return store.read_json(store.call_dir(call_id) / "summary.json", {"status": "none"})


@app.post("/api/calls/{call_id}/summary")
def make_summary(call_id: str):
    _meta_or_404(call_id)
    if not (store.call_dir(call_id) / "doc.json").exists():
        raise HTTPException(409, "Transcript not ready yet")
    return summarize.start(call_id)


@app.get("/")
def index():
    # Version the asset URLs so an app update never shows stale cached files.
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    for asset in ("/static/app.js", "/static/settings.js", "/static/styles.css"):
        html = html.replace(asset, f"{asset}?v={__version__}")
    return HTMLResponse(html, headers={"Cache-Control": "no-store"})


app.mount("/static", StaticFiles(directory=STATIC), name="static")
