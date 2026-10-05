"""Optional AI summary using a local Ollama model (free, runs on the laptop).

Long calls don't fit a small model's context, so we summarise in chunks and then
combine the chunk notes into one summary.
"""

import json
import threading
import time
import traceback
import urllib.error
import urllib.request

from . import config, store

CHUNK_WORDS = 2500

CHUNK_PROMPT = """You are an equity research analyst. Below is part of an earnings conference call transcript of {company} ({period}).
Write concise bullet notes of everything an investor would care about: reported numbers, growth rates, margins,
segment/geography commentary, guidance and outlook, capex/capacity, order book, risks, and anything management
was asked about in Q&A (who asked, what, and the answer). Keep exact numbers. No preamble.

TRANSCRIPT PART:
{text}
"""

FINAL_PROMPT = """You are an equity research analyst. Below are notes taken from the earnings call of {company} ({period}).
Write the final summary in Markdown with exactly these sections:

## One-line takeaway
## Key numbers
## Guidance & outlook
## Segment / geography commentary
## Q&A themes
## Watch-outs

Use short bullets, keep exact numbers, do not invent anything that isn't in the notes.

NOTES:
{text}
"""


def ollama_status() -> dict:
    try:
        with urllib.request.urlopen(config.OLLAMA_URL + "/api/tags", timeout=2) as r:
            models = [m["name"] for m in json.loads(r.read()).get("models", [])]
        return {"running": True, "models": models, "model": config.OLLAMA_MODEL,
                "model_available": any(m == config.OLLAMA_MODEL or m.split(":")[0] == config.OLLAMA_MODEL for m in models)}
    except Exception:
        return {"running": False, "models": [], "model": config.OLLAMA_MODEL, "model_available": False}


def _generate(prompt: str) -> str:
    body = json.dumps({
        "model": config.OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {"num_ctx": 8192, "temperature": 0.2},
    }).encode()
    req = urllib.request.Request(config.OLLAMA_URL + "/api/generate", data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=900) as r:
        return json.loads(r.read())["response"].strip()


def _doc_chunks(doc: dict) -> list[str]:
    chunks, cur, n = [], [], 0
    for t in doc["turns"]:
        sp = doc["speakers"].get(t["sp"], {})
        name = t.get("label") or sp.get("name", "Speaker")
        text = " ".join(w[0] for p in t["paras"] for w in p["w"])
        cur.append(f"{name}: {text}")
        n += len(text.split())
        if n >= CHUNK_WORDS:
            chunks.append("\n".join(cur))
            cur, n = [], 0
    if cur:
        chunks.append("\n".join(cur))
    return chunks


def start(call_id: str) -> dict:
    path = store.call_dir(call_id) / "summary.json"
    current = store.read_json(path, {})
    if current.get("status") == "running":
        return current
    state = {"status": "running", "progress": 0.0, "model": config.OLLAMA_MODEL, "started_at": time.time()}
    store.write_json(path, state)

    def run():
        try:
            meta = store.get_meta(call_id)
            doc = store.read_json(store.call_dir(call_id) / "doc.json")
            chunks = _doc_chunks(doc)
            notes = []
            for i, chunk in enumerate(chunks):
                notes.append(_generate(CHUNK_PROMPT.format(company=meta["company"], period=meta["period"], text=chunk)))
                store.write_json(path, {**state, "progress": (i + 1) / (len(chunks) + 1)})
            final = _generate(FINAL_PROMPT.format(company=meta["company"], period=meta["period"], text="\n\n".join(notes)))
            store.write_json(path, {"status": "done", "text": final, "model": config.OLLAMA_MODEL, "created_at": time.time()})
        except urllib.error.URLError:
            store.write_json(path, {"status": "error", "error": f"Could not reach Ollama at {config.OLLAMA_URL}. Is it running?"})
        except Exception as exc:
            traceback.print_exc()
            store.write_json(path, {"status": "error", "error": str(exc)})

    threading.Thread(target=run, daemon=True).start()
    return state
