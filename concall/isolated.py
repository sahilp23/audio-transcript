"""Runs heavy model work (speech-to-text, speaker separation) in a separate process.

Why a separate process:
  * the memory the models use (1-2 GB) is fully returned when it ends, which
    matters a lot on 8 GB Macs;
  * in gentle mode it runs at low priority on a few CPU cores, so the Mac
    stays responsive (at the cost of speed);
  * it can be stopped (e.g. "Skip speaker separation") without touching the app.

The child prints "PROGRESS <0..1>" lines and writes its result as JSON.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Callable, Optional

from . import config

ROOT = Path(__file__).resolve().parent.parent


class Cancelled(Exception):
    """The job was stopped by the user."""


_running: dict[str, subprocess.Popen] = {}
_cancelled: set[str] = set()


def cancel(tag: str) -> bool:
    proc = _running.get(tag)
    if not proc:
        return False
    _cancelled.add(tag)
    proc.terminate()
    return True


def run(kind: str, input_path: str, opts: dict, gentle: bool,
        on_progress: Optional[Callable[[float], None]] = None, tag: Optional[str] = None) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "result.json"
        cmd = [sys.executable, "-m", "concall.isolated", kind, input_path, str(out), json.dumps({**opts, "gentle": gentle})]
        env = {**os.environ, "PYTHONPATH": os.pathsep.join(filter(None, [str(ROOT), os.environ.get("PYTHONPATH")]))}
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1, env=env)
        if tag:
            _running[tag] = proc
        if config.IS_MAC and shutil.which("caffeinate"):
            # Don't let the Mac sleep halfway through a long job.
            subprocess.Popen(["caffeinate", "-i", "-w", str(proc.pid)])
        tail: list[str] = []
        for line in proc.stdout:  # type: ignore[union-attr]
            line = line.rstrip()
            if line.startswith("PROGRESS ") and on_progress:
                try:
                    on_progress(float(line.split()[1]))
                except ValueError:
                    pass
                continue
            if line:
                print(f"[{kind}] {line}", flush=True)
                tail = (tail + [line])[-8:]
        code = proc.wait()
        if tag:
            _running.pop(tag, None)
            if tag in _cancelled:
                _cancelled.discard(tag)
                raise Cancelled()
        if code != 0:
            last = next((t for t in reversed(tail) if "Error" in t or "error" in t), tail[-1] if tail else "unknown error")
            raise RuntimeError(last)
        return json.loads(out.read_text())


def _child(kind: str, input_path: str, out: str, opts: dict) -> None:
    gentle = opts.get("gentle")
    if gentle:
        try:
            os.nice(10)
        except OSError:
            pass

    def progress(p: float) -> None:
        print(f"PROGRESS {p:.4f}", flush=True)

    if kind == "asr":
        from . import asr

        result = asr.transcribe(input_path, opts["duration"], opts["prompt"], progress,
                                engine="faster" if gentle else None, threads=4 if gentle else None)
    elif kind == "selftest":  # used by the tests
        import time

        for p in (0.5, 1.0):
            progress(p)
        time.sleep(float(opts.get("sleep", 0)))
        result = {"input": input_path, "gentle": bool(gentle)}
    elif kind == "load_speakers":
        from . import diarize

        diarize.load_pipeline("cpu")
        result = {"ok": True}
    elif kind == "diarize":
        from . import diarize

        result = diarize.diarize(input_path, gentle=bool(gentle), progress=progress)
    else:
        raise SystemExit(f"unknown job {kind}")
    Path(out).write_text(json.dumps(result))


if __name__ == "__main__":
    _child(sys.argv[1], sys.argv[2], sys.argv[3], json.loads(sys.argv[4]))
