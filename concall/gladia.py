"""Cloud transcription + speaker separation on Gladia (free plan: 10 hours a month).

One request does both jobs: the audio is uploaded once (compressed to a small
mono file), Gladia transcribes it with diarization switched on, and we poll
until the result is ready. Its word timings fill asr.json and its speaker turns
fill diar.json, so the slow on-Mac speaker separation isn't needed.

API (v2, as used by Gladia's official SDK, gladiaio-sdk 2.1):
  POST /v2/upload (multipart, field "audio")      -> {"audio_url"}
  POST /v2/pre-recorded {audio_url, diarization}  -> {"id", "result_url"}
  GET  /v2/pre-recorded/{id}                      -> {"status": queued|processing|done|error,
                                                      "result": {"transcription": {"utterances": [...]}}}
Auth is the "x-gladia-key" header. Files may be up to 135 minutes long.

Anything that means "Gladia can't do this one" raises GladiaUnavailable; the
pipeline then falls through to Groq (text only), and after that asks before
using the Mac.
"""

import json
import secrets
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable

from . import __version__, align, media

API = "https://api.gladia.io"
SIGNUP_PAGE = "https://app.gladia.io"
MAX_SECONDS = 135 * 60  # longest file the regular plans accept
POLL_EVERY = 3.0
MAX_POLL = 2 * 3600  # give up waiting after two hours
USER_AGENT = f"ConcallPlayer/{__version__}"
# Same light clean-up as for Groq: helps on quiet or uneven phone lines.
SPEECH_FILTER = "highpass=f=70,speechnorm=e=3:r=0.0001:l=1"

_QUOTA_WORDS = ("quota", "limit", "credit", "exceed", "balance", "payment", "billing", "plan", "upgrade")


class GladiaUnavailable(Exception):
    """Gladia can't transcribe this call right now (not connected, offline, free hours used up...)."""


def _request(method: str, url: str, key: str, body: bytes = None, headers: dict = None, timeout: float = 60):
    req = urllib.request.Request(url, data=body, method=method, headers={
        "x-gladia-key": key, "User-Agent": USER_AGENT, "Accept": "application/json", **(headers or {})})
    return urllib.request.urlopen(req, timeout=timeout)


def _error_detail(exc: urllib.error.HTTPError) -> str:
    try:
        raw = exc.read().decode(errors="replace")
    except Exception:
        return ""
    try:
        data = json.loads(raw)
    except ValueError:
        return "blocked by a firewall" if "cloudflare" in raw.lower() else raw[:200]
    if isinstance(data, dict):
        msg = data.get("message") or data.get("error") or data.get("detail") or ""
        if isinstance(msg, (list, dict)):
            msg = json.dumps(msg)
        return str(msg)[:200]
    return str(data)[:200]


def quota_message(code: int, detail: str) -> str | None:
    """A friendly message if this error means the free hours are used up, else None."""
    text = detail.lower()
    if code == 402 or (code in (403, 429) and any(w in text for w in _QUOTA_WORDS)):
        return ("Gladia's free hours for this month are used up" + (f" ({detail})" if detail else "") +
                ". They renew next month.")
    return None


def is_quota(message: str) -> bool:
    return message.startswith("Gladia's free hours")


def _http_problem(exc: urllib.error.HTTPError, detail: str = None) -> str:
    detail = _error_detail(exc) if detail is None else detail
    if exc.code == 401:
        return "Gladia rejected this key" + (f" ({detail})" if detail else "") + ". Copy the key again and paste it."
    quota = quota_message(exc.code, detail)
    if quota:
        return quota
    if exc.code == 403:
        return f"Gladia refused the request (403{': ' + detail if detail else ''})."
    if exc.code == 413:
        return "This recording is too large for Gladia."
    return f"Gladia said {exc.code}" + (f": {detail}" if detail else "") + "."


def check_key(key: str) -> dict:
    key = (key or "").strip()
    if not key:
        return {"ok": False, "error": "Paste your Gladia API key first."}
    if len(key) < 20 or " " in key:
        return {"ok": False, "error": "That doesn't look like a Gladia API key. Copy the whole key from app.gladia.io."}
    try:
        # Listing your (zero or more) past jobs is free and needs a valid key.
        with _request("GET", f"{API}/v2/pre-recorded?limit=1", key, timeout=20) as r:
            r.read()
    except urllib.error.HTTPError as exc:
        return {"ok": False, "error": _http_problem(exc)}
    except Exception as exc:
        return {"ok": False, "error": f"Couldn't reach Gladia. Check your internet connection. ({exc})"}
    return {"ok": True}


def _call(method: str, url: str, key: str, body: bytes = None, headers: dict = None, timeout: float = 60) -> dict:
    """One API call with a few retries for busy (429) and server (5xx) errors."""
    attempts = 0
    while True:
        attempts += 1
        try:
            with _request(method, url, key, body, headers, timeout) as r:
                return json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as exc:
            detail = _error_detail(exc)
            if exc.code in (429, 500, 502, 503, 504) and not quota_message(exc.code, detail) and attempts <= 4:
                retry_after = str(exc.headers.get("retry-after") or "") if exc.headers else ""
                time.sleep(min(float(retry_after) if retry_after.replace(".", "", 1).isdigit() else 10 * attempts, 60))
                continue
            raise GladiaUnavailable(_http_problem(exc, detail))
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            if attempts <= 2:
                time.sleep(5)
                continue
            raise GladiaUnavailable(f"Couldn't reach Gladia (no internet?): {exc}")


def _multipart(field: str, path: Path, ctype: str) -> tuple[bytes, str]:
    boundary = "----concall" + secrets.token_hex(12)
    body = b"".join([
        f'--{boundary}\r\nContent-Disposition: form-data; name="{field}"; filename="{path.name}"\r\n'
        f"Content-Type: {ctype}\r\n\r\n".encode(),
        path.read_bytes(),
        f"\r\n--{boundary}--\r\n".encode(),
    ])
    return body, f"multipart/form-data; boundary={boundary}"


def parse_result(result: dict) -> tuple[list[dict], list[dict]]:
    """Gladia's result -> (words with timings, speaker segments in diar.json format)."""
    utterances = ((result or {}).get("transcription") or {}).get("utterances") or []
    words: list[dict] = []
    diar: list[dict] = []
    for u in sorted(utterances, key=lambda u: float(u.get("start") or 0)):
        timed = [{"w": str(w.get("word", "")).strip(), "s": float(w["start"]), "e": float(w["end"]),
                  "p": float(w.get("confidence") or 1.0)}
                 for w in u.get("words") or [] if str(w.get("word", "")).strip()]
        tokens = str(u.get("text") or "").split()
        if timed and tokens and [t["w"] for t in timed] != tokens:
            # Use the utterance text (punctuated, cased) and give each token the timing of its spoken word.
            times, _ = align.align(tokens, timed)
            timed = [{"w": tok, "s": round(s, 3), "e": round(e, 3), "p": 1.0} for tok, (s, e) in zip(tokens, times)]
        elif not timed and tokens:
            s0, s1 = float(u.get("start") or 0), float(u.get("end") or 0)
            step = max(s1 - s0, 0.01) / len(tokens)
            timed = [{"w": t, "s": round(s0 + i * step, 3), "e": round(s0 + (i + 1) * step, 3), "p": 1.0}
                     for i, t in enumerate(tokens)]
        words += [{**w, "s": round(w["s"], 3), "e": round(w["e"], 3)} for w in timed]
        if u.get("speaker") is not None and timed:
            diar.append({"s": round(float(u.get("start", timed[0]["s"])), 3),
                         "e": round(float(u.get("end", timed[-1]["e"])), 3),
                         "spk": f"SPEAKER_{int(u['speaker']):02d}"})
    words.sort(key=lambda w: w["s"])
    return words, diar


def transcribe(audio_path: str, duration: float, key: str, progress: Callable[[float], None]) -> dict:
    """Returns {"asr": {...}, "diar": [...]}. Raises GladiaUnavailable."""
    if duration > MAX_SECONDS:
        raise GladiaUnavailable(f"This recording is longer than Gladia's {MAX_SECONDS // 60}-minute limit.")
    with tempfile.TemporaryDirectory() as tmp:
        small = Path(tmp) / "call.m4a"
        # Mono 16 kHz AAC: about 20 MB per hour, so the upload is quick.
        media.run("-i", audio_path, "-vn", "-ac", "1", "-ar", "16000", "-af", SPEECH_FILTER,
                  "-c:a", "aac", "-b:a", "48k", str(small))
        body, ctype = _multipart("audio", small, "audio/mp4")
        progress(0.05)
        uploaded = _call("POST", f"{API}/v2/upload", key, body, {"Content-Type": ctype}, timeout=600)
    audio_url = uploaded.get("audio_url")
    if not audio_url:
        raise GladiaUnavailable("Gladia didn't accept the upload. Please use Report a problem.")
    progress(0.15)
    job = _call("POST", f"{API}/v2/pre-recorded", key, json.dumps({
        "audio_url": audio_url,
        "diarization": True,
        "language_config": {"languages": ["en"]},
    }).encode(), {"Content-Type": "application/json"})
    job_id = job.get("id")
    if not job_id:
        raise GladiaUnavailable("Gladia didn't start the transcription. Please use Report a problem.")

    started = time.time()
    # Gladia doesn't report progress; assume roughly a minute per 10 minutes of audio for the bar.
    expected = max(60.0, duration / 10)
    while True:
        res = _call("GET", f"{API}/v2/pre-recorded/{job_id}", key, timeout=30)
        status = res.get("status")
        if status == "done":
            break
        if status == "error":
            code = int(res.get("error_code") or 0)
            raise GladiaUnavailable(quota_message(code, "") or f"Gladia couldn't transcribe this call (error {code}).")
        if time.time() - started > MAX_POLL:
            raise GladiaUnavailable("Gladia is taking too long with this call.")
        progress(min(0.95, 0.15 + 0.8 * (time.time() - started) / expected))
        time.sleep(POLL_EVERY)

    words, diar = parse_result(res.get("result") or {})
    if not words:
        raise GladiaUnavailable("Gladia returned an empty transcript.")
    progress(1.0)
    return {"asr": {"engine": "gladia", "model": "gladia", "words": words},
            "diar": diar or None}
