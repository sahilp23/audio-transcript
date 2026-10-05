"""Cloud transcription on Groq (free tier) using Whisper large-v3-turbo.

The audio is cut into ~10-minute FLAC chunks (the free tier accepts files up to
25 MB) with a short overlap, sent one by one, and stitched back together with
word timings shifted to the call's timeline. Free-tier limits at the time of
writing: about 2 hours of audio per hour and 8 hours per day.

Any problem that means "the cloud can't do this right now" raises
CloudUnavailable; the pipeline then asks the user whether to use the Mac instead.
"""

import json
import math
import secrets
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable

from . import align, media

API = "https://api.groq.com/openai/v1"
MODEL = "whisper-large-v3-turbo"
CHUNK = 600.0  # seconds
OVERLAP = 2.0
MAX_WAIT = 120  # seconds we'll wait out a rate limit before asking the user
KEYS_PAGE = "https://console.groq.com/keys"
SIGNUP_PAGE = "https://console.groq.com"
# Light clean-up that helps on quiet or uneven phone lines.
SPEECH_FILTER = "highpass=f=70,speechnorm=e=3:r=0.0001:l=1"


class CloudUnavailable(Exception):
    """Groq can't transcribe right now (offline, limit reached, bad key...)."""


def _request(method: str, url: str, key: str, body: bytes = None, headers: dict = None, timeout: float = 300):
    req = urllib.request.Request(url, data=body, method=method, headers={"Authorization": f"Bearer {key}", **(headers or {})})
    return urllib.request.urlopen(req, timeout=timeout)


def check_key(key: str) -> dict:
    key = (key or "").strip()
    if not key:
        return {"ok": False, "error": "Paste your Groq API key first."}
    if not key.startswith("gsk_"):
        return {"ok": False, "error": "That doesn't look like a Groq API key (they start with gsk_)."}
    try:
        with _request("GET", f"{API}/models", key, timeout=20) as r:
            models = [m.get("id") for m in json.loads(r.read()).get("data", [])]
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            return {"ok": False, "error": "Groq rejected this key. Create a new key and paste it again."}
        return {"ok": False, "error": f"Groq said {exc.code}. Try again in a minute."}
    except Exception as exc:
        return {"ok": False, "error": f"Couldn't reach Groq. Check your internet connection. ({exc})"}
    if MODEL not in models:
        return {"ok": False, "error": f"Your Groq account doesn't offer {MODEL} right now."}
    return {"ok": True}


def _multipart(fields: dict, file_field: str, file_path: Path) -> tuple[bytes, str]:
    boundary = "----concall" + secrets.token_hex(12)
    parts = []
    for name, value in fields.items():
        values = value if isinstance(value, list) else [value]
        for v in values:
            parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{v}\r\n'.encode())
    parts.append(
        f'--{boundary}\r\nContent-Disposition: form-data; name="{file_field}"; filename="{file_path.name}"\r\n'
        f"Content-Type: audio/flac\r\n\r\n".encode()
    )
    parts.append(file_path.read_bytes())
    parts.append(f"\r\n--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def _transcribe_chunk(path: Path, key: str, prompt: str) -> dict:
    body, ctype = _multipart(
        {
            "model": MODEL,
            "language": "en",
            "response_format": "verbose_json",
            "timestamp_granularities[]": ["word", "segment"],
            "temperature": "0",
            "prompt": prompt[:800],
        },
        "file",
        path,
    )
    attempts = 0
    while True:
        attempts += 1
        try:
            with _request("POST", f"{API}/audio/transcriptions", key, body, {"Content-Type": ctype}) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")[:300]
            if exc.code in (401, 403):
                raise CloudUnavailable("Groq rejected the API key. Reconnect it in Settings.")
            if exc.code == 429:
                wait = float(exc.headers.get("retry-after") or 60)
                if wait > MAX_WAIT or attempts > 3:
                    mins = max(1, round(wait / 60))
                    raise CloudUnavailable(f"Groq's free limit is used up for now (resets in about {mins} min).")
                time.sleep(wait + 1)
                continue
            if exc.code >= 500 and attempts <= 3:
                time.sleep(5 * attempts)
                continue
            raise CloudUnavailable(f"Groq returned an error ({exc.code}): {detail}")
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            if attempts <= 2:
                time.sleep(5)
                continue
            raise CloudUnavailable(f"Couldn't reach Groq (no internet?): {exc}")


def _words_from_response(resp: dict) -> list[dict]:
    """Words with timings, punctuated using the segment text (word entries are often bare)."""
    raw = [w for w in resp.get("words") or [] if str(w.get("word", "")).strip()]
    segments = resp.get("segments") or []
    if raw:
        timed = [{"w": str(w["word"]).strip(), "s": float(w["start"]), "e": float(w["end"])} for w in raw]
        tokens = [t for seg in segments for t in str(seg.get("text", "")).split()]
        if not tokens:
            return timed
        times, _ = align.align(tokens, timed)
        return [{"w": tok, "s": round(s, 3), "e": round(e, 3)} for tok, (s, e) in zip(tokens, times)]
    # No word timings: spread each segment's words across its time span.
    out = []
    for seg in segments:
        toks = str(seg.get("text", "")).split()
        if not toks:
            continue
        s0, s1 = float(seg["start"]), float(seg["end"])
        step = (s1 - s0) / len(toks)
        out += [{"w": t, "s": round(s0 + i * step, 3), "e": round(s0 + (i + 1) * step, 3)} for i, t in enumerate(toks)]
    return out


def transcribe(audio_path: str, duration: float, prompt: str, key: str, progress: Callable[[float], None]) -> dict:
    n = max(1, math.ceil(duration / CHUNK))
    words: list[dict] = []
    with tempfile.TemporaryDirectory() as tmp:
        for i in range(n):
            start = i * CHUNK
            s0 = max(0.0, start - OVERLAP)
            length = CHUNK + (start - s0)
            chunk = Path(tmp) / f"chunk{i:03d}.flac"
            media.run("-ss", f"{s0:.3f}", "-t", f"{length:.3f}", "-i", audio_path, "-vn", "-ac", "1", "-ar", "16000",
                      "-af", SPEECH_FILTER, "-c:a", "flac", str(chunk))
            resp = _transcribe_chunk(chunk, key, prompt)
            for w in _words_from_response(resp):
                t = w["s"] + s0
                # Keep each word once: it belongs to the chunk whose own span contains its start.
                if (i > 0 and t < start) or (i < n - 1 and t >= start + CHUNK):
                    continue
                words.append({"w": w["w"], "s": round(t, 3), "e": round(w["e"] + s0, 3), "p": 1.0})
            progress((i + 1) / n)
    words.sort(key=lambda w: w["s"])
    return {"engine": "groq", "model": MODEL, "words": words}
