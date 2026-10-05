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


def reload_app(tmp_path, monkeypatch, **env):
    monkeypatch.setenv("CONCALL_SUPPORT_DIR", str(tmp_path))
    monkeypatch.delenv("CONCALL_DATA_DIR", raising=False)
    monkeypatch.delenv("HF_TOKEN", raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    from concall import config

    importlib.reload(config)
    from concall import asr as asr_mod
    from concall import components, diarize, hf, media, pipeline, server, store, summarize, updater

    for m in (components, diarize, store, asr_mod, media, hf, updater, pipeline, summarize, server):
        importlib.reload(m)
    return server


@pytest.fixture
def client(tmp_path, monkeypatch):
    server = reload_app(tmp_path, monkeypatch, DIARIZATION="off")
    from concall import asr as asr_mod

    from concall import components

    fake, _diar, _dur = make_asr()
    monkeypatch.setattr(asr_mod, "transcribe", lambda wav, dur, prompt, progress: (progress(1.0), fake)[1])
    monkeypatch.setattr(components, "ensure_speech_ready", lambda on_update=None: None)
    from fastapi.testclient import TestClient

    with TestClient(server.app, headers={"X-Concall": "1"}) as c:
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
    from concall import media

    return subprocess.run(
        [media.ensure_ffmpeg(), "-loglevel", "error", "-f", "lavfi", "-i", f"sine=frequency=200:duration={seconds}", "-f", "mp3", "-"],
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


def test_api_rejects_cross_site_posts(client):
    from fastapi.testclient import TestClient
    from concall import server

    bare = TestClient(server.app)
    assert bare.post("/api/hf/disconnect").status_code == 403  # no app header
    assert bare.get("/api/ping").status_code == 200
    assert client.get("/api/ping", headers={"Host": "evil.example"}).status_code == 403


def test_settings_roundtrip_hides_token(client):
    from concall import config

    config.save_settings({"hf_token": "hf_secret"})
    s = client.get("/api/settings").json()
    assert "hf_token" not in s
    s = client.patch("/api/settings", json={"auto_update_check": False, "hf_token": "x"}).json()
    assert s["auto_update_check"] is False
    assert config.hf_token() == "hf_secret"  # not changeable through PATCH


def test_open_only_allows_known_sites(client, monkeypatch):
    from concall import server

    opened = []
    monkeypatch.setattr(server, "_open", opened.append)
    assert client.post("/api/open", json={"url": "https://huggingface.co/settings/tokens"}).status_code == 200
    assert client.post("/api/open", json={"url": "https://evil.example/x"}).status_code == 400
    assert client.post("/api/open", json={"url": "file:///etc/passwd"}).status_code == 400
    assert opened == ["https://huggingface.co/settings/tokens"]


def test_hf_check_reports_missing_terms(tmp_path, monkeypatch):
    reload_app(tmp_path, monkeypatch)
    import huggingface_hub
    from huggingface_hub.utils import GatedRepoError

    from concall import config, hf

    class FakeApi:
        def whoami(self, token=None):
            return {"name": "sahil"}

    def fake_download(repo, filename, token=None):
        if repo == "pyannote/segmentation-3.0":
            err = GatedRepoError.__new__(GatedRepoError)  # skip its HTTP-response constructor
            Exception.__init__(err, "gated")
            raise err
        return "/tmp/x"

    monkeypatch.setattr(huggingface_hub, "HfApi", FakeApi)
    monkeypatch.setattr(huggingface_hub, "hf_hub_download", fake_download)
    started = []
    monkeypatch.setattr(hf, "start_setup", lambda: started.append(1))

    r = hf.connect("hf_abc123")
    assert r["token_valid"] and not r["ok"]
    assert [m["repo"] for m in r["missing_terms"]] == ["pyannote/segmentation-3.0"]
    assert config.hf_token() == "hf_abc123" and not config.hf_ready()
    assert not started

    monkeypatch.setattr(huggingface_hub, "hf_hub_download", lambda *a, **k: "/tmp/x")
    r = hf.recheck()
    assert r["ok"] and config.hf_ready() and started
    assert hf.check("nope")["error"]


def test_updater_check_and_install(tmp_path, monkeypatch):
    import json as _json
    import tarfile

    reload_app(tmp_path, monkeypatch, CONCALL_APP="1")
    from concall import config, updater

    # Build a fake release tarball like GitHub's (one top-level folder).
    src = tmp_path / "src" / "sahilp23-audio-transcript-abc123"
    (src / "concall").mkdir(parents=True)
    (src / "concall" / "__init__.py").write_text('__version__ = "9.9.9"\n')
    tarball = tmp_path / "rel.tar.gz"
    with tarfile.open(tarball, "w:gz") as tf:
        tf.add(src, arcname=src.name)

    release = {"tag_name": "v9.9.9", "body": "## New\n- things", "tarball_url": "https://x/tar", "html_url": "https://x"}

    class Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_get(url, timeout=15):
        return Resp(tarball.read_bytes()) if url == "https://x/tar" else Resp(_json.dumps(release).encode())

    monkeypatch.setattr(updater, "_get", fake_get)
    info = updater.check(force=True)
    assert info["available"] and info["latest"] == "9.9.9"

    updater.install()
    for _ in range(100):
        if updater.install_status()["state"] != "running":
            break
        time.sleep(0.05)
    st = updater.install_status()
    assert st["state"] == "done", st
    current = Path((config.SUPPORT_DIR / "app" / "current").read_text())
    assert (current / "concall" / "__init__.py").exists()
    assert updater.parse_version("v0.10.0") > updater.parse_version("0.9.9")


def test_components_stamp(tmp_path, monkeypatch):
    reload_app(tmp_path, monkeypatch, CONCALL_UV="/nonexistent/uv")
    from concall import components

    # With the app's uv, an importable package without a matching stamp counts as
    # needing (re)install, so requirement changes in an update get applied.
    monkeypatch.setitem(components.PACKAGES["engine"], "modules", ["json"])
    assert not components.package_installed("engine")
    stamp = components._stamp_path("engine")
    stamp.parent.mkdir(parents=True, exist_ok=True)
    stamp.write_text(components._req_hash("engine"))
    assert components.package_installed("engine")


def test_media_duration(tmp_path):
    from concall import media

    f = tmp_path / "a.mp3"
    f.write_bytes(_wav_bytes(4))
    assert abs(media.duration(f) - 4.0) < 0.2
