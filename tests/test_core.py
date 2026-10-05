import importlib
import io
import subprocess
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from sample_data import OFFICIAL, SPOKEN, make_asr  # noqa: E402

from concall import align, structure, transcript_parser  # noqa: E402


def test_parser_finds_turns_and_participants():
    parsed = transcript_parser.parse_text(OFFICIAL)
    speakers = [t["speaker"] for t in parsed["turns"]]
    assert speakers[:4] == ["Moderator", "Arjun Mehta", "Priya Nair", "Moderator"]
    assert "Rahul Jain" in speakers and "Sneha Rao" in speakers
    assert parsed["participants"]["arjun mehta"]["role"] == "Managing Director"
    # The participants list and page footers must not leak into the text.
    assert not parsed["turns"][0]["text"].startswith("MR.")
    assert all("Page 2 of 4" not in t["text"] for t in parsed["turns"])
    # Lines continuing a turn across a page break are joined.
    assert "Capex for the year" in parsed["turns"][1]["text"]


def test_parser_ignores_single_word_colon_lines():
    text = "Moderator: Welcome to the call.\nArjun Mehta: Revenue grew.\nNote: this is part of what he said.\n"
    parsed = transcript_parser.parse_text(text)
    assert [t["speaker"] for t in parsed["turns"]] == ["Moderator", "Arjun Mehta"]
    assert "Note: this is part" in parsed["turns"][1]["text"]


def test_alignment_handles_edited_text():
    asr = [{"w": w, "s": i * 1.0, "e": i * 1.0 + 0.5} for i, w in enumerate(
        "so um revenue grew 18.7% to INR 182 crores you know and margins improved".split())]
    official = "Revenue grew 18.7% to INR 182 crores and margins improved.".split()
    times, matched = align.align(official, asr)
    assert len(times) == len(official)
    assert matched > 0.9
    assert times[0] == (2.0, 2.5)  # "Revenue" -> 3rd spoken word
    starts = [t[0] for t in times]
    assert starts == sorted(starts)


def test_alignment_interpolates_unmatched_words():
    asr = [{"w": "alpha", "s": 0.0, "e": 0.5}, {"w": "omega", "s": 10.0, "e": 10.5}]
    times, _ = align.align(["alpha", "beta", "gamma", "omega"], asr)
    assert 0.5 <= times[1][0] < times[2][0] < 10.0


def test_structure_from_official():
    asr, _diar, dur = make_asr()
    doc = structure.build_from_official(transcript_parser.parse_text(OFFICIAL), asr, dur)
    kinds = [c["kind"] for c in doc["chapters"]]
    assert kinds == ["intro", "remarks", "qa", "question", "question", "closing"]
    assert doc["alignment"] > 0.9
    assert doc["speakers"]["rahul jain"]["group"] == "analyst"
    assert doc["speakers"]["rahul jain"]["firm"] == "Alpha Capital"
    assert doc["speakers"]["priya nair"]["group"] == "management"
    assert any(h["kind"] == "guidance" for h in doc["highlights"])
    # Timings are monotonic across the whole document.
    starts = [w[1] for t in doc["turns"] for p in t["paras"] for w in p["w"]]
    assert starts == sorted(starts)


def test_structure_from_asr_with_speakers():
    asr, diar, dur = make_asr()
    doc = structure.build_from_asr(asr, diar, dur)
    assert len(doc["turns"]) == len(SPOKEN)
    assert doc["speakers"]["SPEAKER_00"]["name"] == "Moderator"
    analyst_turns = [t for t in doc["turns"] if t.get("label")]
    assert [t["label"] for t in analyst_turns] == ["Rahul Jain", "Sneha Rao"]
    assert [c["title"] for c in doc["chapters"] if c["kind"] == "question"] == [
        "Rahul Jain · Alpha Capital", "Sneha Rao · Beta Advisors"]


def test_structure_from_asr_without_speakers():
    asr, _diar, dur = make_asr()
    doc = structure.build_from_asr(asr, None, dur)
    assert doc["speakers_separated"] is False
    assert {c["kind"] for c in doc["chapters"]} >= {"intro", "qa", "question", "closing"}


def _make_pdf(path: Path, text: str) -> None:
    reportlab = pytest.importorskip("reportlab")  # noqa: F841
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    c = canvas.Canvas(str(path), pagesize=A4)
    lines = text.splitlines()
    for page_start in range(0, len(lines), 9):
        y = 800
        c.drawString(40, 820, "Demo Controls Limited")  # repeated header
        for ln in lines[page_start:page_start + 9]:
            # wrap long lines like a real PDF would
            while ln:
                c.drawString(40, y, ln[:95])
                ln = ln[95:]
                y -= 14
        c.drawString(280, 30, f"Page {page_start // 9 + 1}")
        c.showPage()
    c.save()


def test_pdf_transcript(tmp_path):
    pdf = tmp_path / "t.pdf"
    _make_pdf(pdf, OFFICIAL)
    parsed = transcript_parser.parse_file(pdf)
    speakers = [t["speaker"] for t in parsed["turns"]]
    assert speakers[:3] == ["Moderator", "Arjun Mehta", "Priya Nair"]
    assert all("Demo Controls Limited Page" not in t["text"] for t in parsed["turns"])


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CONCALL_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("DIARIZATION", "off")
    from concall import config

    importlib.reload(config)
    from concall import asr as asr_mod
    from concall import diarize, pipeline, server, store, summarize  # noqa: F401

    for m in (diarize, store, asr_mod, pipeline, summarize, server):
        importlib.reload(m)

    fake, _diar, _dur = make_asr()
    monkeypatch.setattr(asr_mod, "transcribe", lambda wav, dur, prompt, progress: (progress(1.0), fake)[1])
    from fastapi.testclient import TestClient

    with TestClient(server.app) as c:
        yield c


def _wait_ready(client, call_id, timeout=30):
    end = time.time() + timeout
    while time.time() < end:
        meta = client.get(f"/api/calls/{call_id}").json()
        if meta["status"] in ("ready", "error"):
            return meta
        time.sleep(0.2)
    raise AssertionError("timed out")


def _wav_bytes(seconds: int = 3) -> bytes:
    return subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", f"sine=frequency=200:duration={seconds}", "-f", "mp3", "-"],
        capture_output=True, check=True,
    ).stdout


def test_upload_then_attach_transcript_later(client):
    r = client.post(
        "/api/calls",
        data={"company": "Demo Controls", "period": "Q1 FY27", "date": "2026-08-07"},
        files={"audio": ("call.mp3", io.BytesIO(_wav_bytes()), "audio/mpeg")},
    )
    assert r.status_code == 200, r.text
    call_id = r.json()["id"]
    meta = _wait_ready(client, call_id)
    assert meta["status"] == "ready", meta
    assert meta["has_official"] is False
    doc = client.get(f"/api/calls/{call_id}/doc").json()
    assert doc["source"] == "asr"

    # Audio supports range requests (needed for seeking in the browser).
    a = client.get(f"/api/calls/{call_id}/audio", headers={"Range": "bytes=0-99"})
    assert a.status_code == 206 and len(a.content) == 100

    # Days later: the company transcript is published.
    r = client.post(f"/api/calls/{call_id}/transcript", data={"transcript_text": OFFICIAL})
    assert r.status_code == 200, r.text
    time.sleep(0.2)
    meta = _wait_ready(client, call_id)
    assert meta["has_official"] is True
    doc = client.get(f"/api/calls/{call_id}/doc").json()
    assert doc["source"] == "official"
    assert doc["speakers"]["arjun mehta"]["role"] == "Managing Director"

    # User data round-trips.
    client.patch(f"/api/calls/{call_id}/user", json={"bookmarks": [{"id": "x", "t": 12.5, "note": "margin"}], "position": 40})
    assert client.get(f"/api/calls/{call_id}/user").json()["position"] == 40

    # Back to auto transcript.
    client.delete(f"/api/calls/{call_id}/transcript")
    time.sleep(0.2)
    _wait_ready(client, call_id)
    assert client.get(f"/api/calls/{call_id}/doc").json()["source"] == "asr"


def test_upload_with_bad_transcript_still_processes(client):
    r = client.post(
        "/api/calls",
        data={"company": "X", "period": "Q2", "transcript_text": "just some text without speakers"},
        files={"audio": ("call.mp3", io.BytesIO(_wav_bytes()), "audio/mpeg")},
    )
    meta = _wait_ready(client, r.json()["id"])
    assert meta["status"] == "ready"
    assert meta["has_official"] is False
