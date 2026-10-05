"""Create a demo call (synthetic audio + sample transcript) so you can try the
player without waiting for a real transcription.

    python scripts/demo.py
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from concall import pipeline, store, transcript_parser  # noqa: E402
from sample_data import OFFICIAL, make_asr  # noqa: E402


def main(with_official: bool = True) -> str:
    asr, diar, duration = make_asr()
    meta = store.create_call("Demo Controls", "Q1 FY27", "2026-08-07", "audio.mp3")
    d = store.call_dir(meta["id"])
    # A quiet tone stands in for the recording.
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"sine=frequency=180:duration={duration}",
         "-af", "volume=0.05", "-ac", "1", "-b:a", "48k", str(d / "audio.mp3")],
        check=True,
    )
    store.write_json(d / "asr.json", asr)
    store.write_json(d / "diar.json", diar)
    if with_official:
        store.write_json(d / "official.json", transcript_parser.parse_text(OFFICIAL))
    store.update_meta(meta["id"], duration=duration, play_file="audio.mp3")
    pipeline.build_doc(meta["id"])
    store.update_meta(meta["id"], status="ready", stage="Ready", progress=1.0, warnings=[])
    print(f"Created demo call {meta['id']}")
    return meta["id"]


if __name__ == "__main__":
    main(with_official="--auto" not in sys.argv)
