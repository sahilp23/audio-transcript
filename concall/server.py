"""Local web server: `python -m concall` then open http://127.0.0.1:8765"""

import shutil
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import asr, config, diarize, pipeline, store, summarize, transcript_parser

STATIC = Path(__file__).parent / "static"
TRANSCRIPT_TYPES = {".pdf", ".txt", ".md", ".text"}


@asynccontextmanager
async def lifespan(_app):
    pipeline.start_worker()
    yield


app = FastAPI(title="Concall Player", lifespan=lifespan)


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
        (d / "official_source.txt").write_text(transcript_text)
        parsed = transcript_parser.parse_text(transcript_text)
    else:
        raise HTTPException(400, "No transcript provided")
    if not parsed["turns"]:
        raise HTTPException(400, "Couldn't find any 'Speaker: text' sections in that transcript")
    store.write_json(d / "official.json", parsed)
    return parsed


@app.get("/api/status")
def status():
    return {
        "asr_engine": asr.pick_engine(),
        "asr_model": config.MLX_MODEL if asr.pick_engine() == "mlx" else config.FASTER_WHISPER_MODEL,
        "diarization": diarize.available() or "ready",
        "ollama": summarize.ollama_status(),
        "data_dir": str(config.DATA_DIR),
    }


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
            store.update_meta(meta["id"], warnings=[f"Transcript ignored: {exc.detail}"])
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


@app.get("/api/calls/{call_id}/doc")
def get_doc(call_id: str):
    _meta_or_404(call_id)
    doc = store.read_json(store.call_dir(call_id) / "doc.json")
    if doc is None:
        raise HTTPException(404, "Transcript not ready yet")
    return JSONResponse(doc)


@app.get("/api/calls/{call_id}/audio")
def get_audio(call_id: str):
    meta = _meta_or_404(call_id)
    path = store.call_dir(call_id) / (meta.get("play_file") or meta["audio_file"])
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
    if not (d / "diar.json").exists() and diarize.available() is None:
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
    allowed = {k: v for k, v in body.items() if k in ("bookmarks", "speakers", "position", "notes", "rate")}
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
    return FileResponse(STATIC / "index.html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")
