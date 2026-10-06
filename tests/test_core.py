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

    from concall import components, isolated

    fake, _diar, _dur = make_asr()
    monkeypatch.setattr(asr_mod, "transcribe", lambda wav, dur, prompt, progress, **kw: (progress(1.0), fake)[1])
    monkeypatch.setattr(components, "ensure_speech_ready", lambda on_update=None: None)

    def fake_isolated(kind, path, opts, gentle, on_progress=None):
        assert kind == "asr"
        return asr_mod.transcribe(path, opts["duration"], opts["prompt"], on_progress or (lambda p: None))

    monkeypatch.setattr(isolated, "run", fake_isolated)
    from fastapi.testclient import TestClient

    with TestClient(server.app, headers={"X-Concall": "1"}) as c:
        yield c


def _wait_ready(client, call_id, timeout=30):
    end = time.time() + timeout
    while time.time() < end:
        meta = client.get(f"/api/calls/{call_id}").json()
        if meta["status"] in ("ready", "error", "needs_input"):
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
    # No cloud key: the app asks before transcribing on this Mac.
    meta = _wait_ready(client, call_id)
    assert meta["status"] == "needs_input", meta
    assert "Groq" in meta["decision"]["reason"]
    assert client.post(f"/api/calls/{call_id}/decision", json={"choice": "nope"}).status_code == 400
    client.post(f"/api/calls/{call_id}/decision", json={"choice": "local_gentle"})
    meta = _wait_ready(client, call_id)
    assert meta["status"] == "ready", meta
    assert meta["asr_route"] == "local_gentle"
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
    assert meta["status"] == "needs_input"
    assert meta["has_official"] is False
    assert "Transcript ignored" in " ".join(meta.get("warnings") or [])


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


def test_pyannote_hub_compat_translates_old_token_argument():
    from concall import diarize

    calls = []

    def new_style_download(repo, filename, *, token=None, cache_dir=None):  # no use_auth_token
        calls.append((repo, filename, token))
        return "/tmp/x"

    shim = diarize.hub_download_compat(new_style_download)
    assert shim("pyannote/x", "config.yaml", use_auth_token="hf_1", cache_dir=None) == "/tmp/x"
    assert shim("pyannote/y", "pytorch_model.bin") == "/tmp/x"
    assert calls == [("pyannote/x", "config.yaml", "hf_1"), ("pyannote/y", "pytorch_model.bin", None)]


def test_cloud_route_and_fallback_question(client, monkeypatch):
    from concall import cloud, config

    config.save_settings({"groq_key": "gsk_test"})
    fake, _d, _ = make_asr()
    calls = []

    def fake_cloud(audio, duration, prompt, key, progress):
        calls.append(key)
        if len(calls) == 1:
            raise cloud.CloudUnavailable("Groq's free limit is used up for now (resets in about 30 min).")
        progress(1.0)
        return {"engine": "groq", "model": cloud.MODEL, "words": fake["words"]}

    monkeypatch.setattr(cloud, "transcribe", fake_cloud)
    r = client.post("/api/calls", data={"company": "Demo", "period": "Q1"},
                    files={"audio": ("call.mp3", io.BytesIO(_wav_bytes()), "audio/mpeg")})
    call_id = r.json()["id"]
    meta = _wait_ready(client, call_id)
    assert meta["status"] == "needs_input" and "free limit" in meta["decision"]["reason"]
    client.post(f"/api/calls/{call_id}/decision", json={"choice": "retry"})
    meta = _wait_ready(client, call_id)
    assert meta["status"] == "ready", meta
    assert calls == ["gsk_test", "gsk_test"]
    doc = client.get(f"/api/calls/{call_id}/doc").json()
    assert doc["turns"]


def test_cloud_chunks_and_stitches(tmp_path, monkeypatch):
    from concall import cloud, media

    audio = tmp_path / "a.mp3"
    audio.write_bytes(_wav_bytes(25))
    monkeypatch.setattr(cloud, "CHUNK", 10.0)
    sent = []

    def fake_chunk(path, key, prompt):
        sent.append(round(media.duration(path), 1))
        # Every chunk "hears" a word at its start and one at 5 s.
        return {"words": [{"word": "hello", "start": 0.5, "end": 0.9}, {"word": "world", "start": 5.0, "end": 5.4}],
                "segments": [{"text": " Hello, world.", "start": 0.0, "end": 6.0}]}

    monkeypatch.setattr(cloud, "_transcribe_chunk", fake_chunk)
    out = cloud.transcribe(str(audio), 25.0, "p", "gsk_x", lambda p: None)
    assert sent == [10.0, 12.0, 7.0]  # chunks after the first start 2 s early (overlap)
    starts = [w["s"] for w in out["words"]]
    assert starts == sorted(starts)
    # Later chunks' "hello" sits in the 2 s overlap (before their own span) and is dropped.
    assert [(w["w"], w["s"]) for w in out["words"]] == [("Hello,", 0.5), ("world.", 5.0), ("world.", 13.0), ("world.", 23.0)]
    assert out["engine"] == "groq"


def test_cloud_key_check_rejects_bad_format():
    from concall import cloud

    assert not cloud.check_key("")["ok"]
    assert "gsk_" in cloud.check_key("abc")["error"]


def test_report_redacts_and_builds_issue_link(client, monkeypatch, tmp_path):
    import urllib.parse

    from concall import report

    log = tmp_path / "app.log"
    log.write_text("starting\nError with token hf_abcdefghijklmnop and gsk_ABCDEFGH12345 in /Users/sahil/Library/x\n")
    monkeypatch.setattr(report, "LOG_FILE", log)
    r = client.post("/api/report", json={"description": "Speaker separation failed", "context": {"error": "Weights only load failed"}}).json()
    assert r["url"].startswith("https://github.com/sahilp23/audio-transcript/issues/new?")
    body = urllib.parse.parse_qs(urllib.parse.urlparse(r["url"]).query)["body"][0]
    assert "Weights only load failed" in body and "Speaker separation failed" in body
    assert "hf_abcdefghijklmnop" not in body and "gsk_ABCDEFGH12345" not in body and "/Users/sahil" not in body
    assert Path(r["path"]).exists()


def test_isolated_runs_in_child_process():
    from concall import isolated

    seen = []
    out = isolated.run("selftest", "abc", {}, gentle=True, on_progress=seen.append)
    assert out == {"input": "abc", "gentle": True}
    assert seen == [0.5, 1.0]


def test_trusted_torch_load_forces_full_unpickling(monkeypatch):
    import sys
    import types

    from concall import diarize

    calls = []
    fake_torch = types.SimpleNamespace(load=lambda *a, **k: calls.append(k) or "ok")
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    original = fake_torch.load
    with diarize.trusted_torch_load():
        assert fake_torch.load("x", weights_only=True) == "ok"
    assert calls == [{"weights_only": False}]
    assert fake_torch.load is original


def test_enhance_creates_clear_voice_audio(client):
    r = client.post("/api/calls", data={"company": "Demo", "period": "Q1"},
                    files={"audio": ("call.mp3", io.BytesIO(_wav_bytes(4)), "audio/mpeg")})
    call_id = r.json()["id"]
    _wait_ready(client, call_id)
    client.post(f"/api/calls/{call_id}/enhance")
    for _ in range(100):
        meta = client.get(f"/api/calls/{call_id}").json()
        if meta.get("enhanced") in ("ready", "error"):
            break
        time.sleep(0.1)
    assert meta["enhanced"] == "ready", meta
    a = client.get(f"/api/calls/{call_id}/audio?clear=1")
    assert a.status_code == 200 and len(a.content) > 1000


def test_cloud_requests_send_a_user_agent_and_explain_errors(monkeypatch):
    import email.message

    from concall import cloud

    seen = {}

    def fake_urlopen(req, timeout=0):
        seen["ua"] = req.get_header("User-agent")
        seen["auth"] = req.get_header("Authorization")
        hdrs = email.message.Message()
        raise urllib.error.HTTPError(req.full_url, 403, "Forbidden", hdrs, io.BytesIO(b"error code: 1010"))

    import urllib.error
    monkeypatch.setattr(cloud.urllib.request, "urlopen", fake_urlopen)
    r = cloud.check_key("gsk_abc")
    assert seen["ua"].startswith("ConcallPlayer/") and "urllib" not in seen["ua"]
    assert seen["auth"] == "Bearer gsk_abc"
    assert "firewall" in r["error"] and "rejected this key" not in r["error"]

    def fake_401(req, timeout=0):
        raise urllib.error.HTTPError(req.full_url, 401, "Unauthorized", email.message.Message(),
                                     io.BytesIO(b'{"error": {"message": "Invalid API Key"}}'))

    monkeypatch.setattr(cloud.urllib.request, "urlopen", fake_401)
    assert "Invalid API Key" in cloud.check_key("gsk_abc")["error"]


def test_isolated_job_can_be_cancelled():
    import threading

    from concall import isolated

    result = {}

    def go():
        try:
            isolated.run("selftest", "x", {"sleep": 30}, gentle=False, tag="call-1")
            result["r"] = "finished"
        except isolated.Cancelled:
            result["r"] = "cancelled"

    t = threading.Thread(target=go)
    t.start()
    for _ in range(100):
        if "call-1" in isolated._running:
            break
        time.sleep(0.05)
    assert isolated.cancel("call-1")
    t.join(10)
    assert result["r"] == "cancelled"
    assert not isolated.cancel("call-1")


def test_diarization_progress_hook(monkeypatch):
    import sys
    import types

    from concall import diarize

    seen = []

    class FakeAnnotation:
        def itertracks(self, yield_label=False):
            seg = types.SimpleNamespace(start=0.0, end=1.0)
            return iter([(seg, None, "SPEAKER_00")])

    class FakePipeline:
        embedding_batch_size = 1

        def __call__(self, audio, hook=None):
            hook("segmentation", None, total=10, completed=5)
            hook("embeddings", None, total=4, completed=2)
            hook("discrete_diarization", None)
            return FakeAnnotation()

    pipe = FakePipeline()
    monkeypatch.setattr(diarize, "load_pipeline", lambda device=None: pipe)
    monkeypatch.setattr(diarize, "_read_wav", lambda p: {})
    monkeypatch.setitem(sys.modules, "torch", types.SimpleNamespace(set_num_threads=lambda n: None))
    segs = diarize.diarize("x.wav", gentle=True, progress=seen.append)
    assert segs == [{"s": 0.0, "e": 1.0, "spk": "SPEAKER_00"}]
    assert pipe.embedding_batch_size == 32
    assert seen == sorted(seen) and seen[-1] == 1.0 and 0.1 < seen[0] < 0.2


# ---------- Gladia (cloud transcription + speakers), with mocked HTTP ----------

GLADIA_RESULT = {
    "metadata": {"audio_duration": 8.0},
    "transcription": {"utterances": [
        {"start": 0.2, "end": 2.0, "speaker": 0, "text": "Good evening, everyone.", "channel": 0, "confidence": 0.9,
         "words": [{"word": " Good", "start": 0.2, "end": 0.5, "confidence": 0.9},
                   {"word": " evening", "start": 0.5, "end": 1.0, "confidence": 0.9},
                   {"word": " everyone", "start": 1.1, "end": 2.0, "confidence": 0.9}]},
        {"start": 2.5, "end": 4.0, "speaker": 1, "text": "Revenue grew 18%.", "channel": 0, "confidence": 0.9,
         "words": [{"word": "Revenue", "start": 2.5, "end": 3.0, "confidence": 0.9},
                   {"word": "grew", "start": 3.0, "end": 3.4, "confidence": 0.9},
                   {"word": "18%.", "start": 3.4, "end": 4.0, "confidence": 0.9}]},
    ]},
}


class _FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def _http_error(url, code, body):
    import json
    import urllib.error

    return urllib.error.HTTPError(url, code, "err", {}, io.BytesIO(json.dumps(body).encode()))


def test_gladia_parse_result_words_and_speakers():
    from concall import gladia

    words, diar = gladia.parse_result(GLADIA_RESULT)
    assert [w["w"] for w in words] == ["Good", "evening,", "everyone.", "Revenue", "grew", "18%."]
    assert words[1]["s"] == 0.5 and words[3]["s"] == 2.5
    assert diar == [{"s": 0.2, "e": 2.0, "spk": "SPEAKER_00"}, {"s": 2.5, "e": 4.0, "spk": "SPEAKER_01"}]


def test_gladia_transcribe_flow(tmp_path, monkeypatch):
    import json

    from concall import gladia

    audio = tmp_path / "a.mp3"
    audio.write_bytes(_wav_bytes(3))
    monkeypatch.setattr(gladia, "POLL_EVERY", 0)
    seen = []
    polls = iter(["queued", "processing", "done"])

    def fake_request(method, url, key, body=None, headers=None, timeout=60):
        seen.append((method, url.replace(gladia.API, ""), key, (headers or {}).get("Content-Type", "")))
        if url.endswith("/v2/upload"):
            assert b'name="audio"' in body
            return _FakeResponse(json.dumps({"audio_url": "https://api.gladia.io/file/1"}).encode())
        if method == "POST":
            req = json.loads(body)
            assert req["diarization"] is True and req["audio_url"].endswith("/file/1")
            return _FakeResponse(json.dumps({"id": "job1", "result_url": "x"}).encode())
        status = next(polls)
        return _FakeResponse(json.dumps({"id": "job1", "status": status,
                                         "result": GLADIA_RESULT if status == "done" else None}).encode())

    monkeypatch.setattr(gladia, "_request", fake_request)
    progress = []
    out = gladia.transcribe(str(audio), 3.0, "k" * 36, progress.append)
    assert [s[:2] for s in seen] == [("POST", "/v2/upload"), ("POST", "/v2/pre-recorded")] + [("GET", "/v2/pre-recorded/job1")] * 3
    assert seen[0][3].startswith("multipart/form-data") and all(s[2] == "k" * 36 for s in seen)
    assert out["asr"]["engine"] == "gladia" and len(out["asr"]["words"]) == 6
    assert len(out["diar"]) == 2 and progress[-1] == 1.0


def test_gladia_sends_key_and_user_agent(monkeypatch):
    import urllib.request

    from concall import gladia

    captured = {}

    def fake_urlopen(req, timeout=0):
        captured.update({k.lower(): v for k, v in req.header_items()})
        return _FakeResponse(b"{}")

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    assert gladia.check_key("k" * 36) == {"ok": True}
    assert captured["x-gladia-key"] == "k" * 36
    assert captured["user-agent"].startswith("ConcallPlayer/")


def test_gladia_errors_are_explained(tmp_path, monkeypatch):
    from concall import gladia

    assert not gladia.check_key("")["ok"]
    assert "doesn't look like" in gladia.check_key("short")["error"]

    def bad_key(method, url, key, body=None, headers=None, timeout=60):
        raise _http_error(url, 401, {"message": "Invalid API key"})

    monkeypatch.setattr(gladia, "_request", bad_key)
    assert "rejected this key" in gladia.check_key("k" * 36)["error"]

    def out_of_hours(method, url, key, body=None, headers=None, timeout=60):
        raise _http_error(url, 402, {"message": "Monthly quota exceeded"})

    monkeypatch.setattr(gladia, "_request", out_of_hours)
    audio = tmp_path / "a.mp3"
    audio.write_bytes(_wav_bytes(2))
    with pytest.raises(gladia.GladiaUnavailable) as e:
        gladia.transcribe(str(audio), 2.0, "k" * 36, lambda p: None)
    assert gladia.is_quota(str(e.value)) and "free hours" in str(e.value)

    with pytest.raises(gladia.GladiaUnavailable, match="135-minute"):
        gladia.transcribe(str(audio), 3 * 3600, "k" * 36, lambda p: None)


def test_gladia_route_gives_speakers_and_service(client, monkeypatch):
    from concall import config, gladia

    config.save_settings({"gladia_key": "k" * 36})
    fake, diar, _ = make_asr()
    monkeypatch.setattr(gladia, "transcribe", lambda audio, dur, key, progress: (
        progress(1.0), {"asr": {"engine": "gladia", "model": "gladia", "words": fake["words"]}, "diar": diar})[1])
    r = client.post("/api/calls", data={"company": "Demo", "period": "Q1"},
                    files={"audio": ("call.mp3", io.BytesIO(_wav_bytes()), "audio/mpeg")})
    meta = _wait_ready(client, r.json()["id"])
    assert meta["status"] == "ready", meta
    assert meta["asr_service"] == "gladia"
    doc = client.get(f"/api/calls/{meta['id']}/doc").json()
    assert doc["speakers_separated"] is True
    setup = client.get("/api/setup").json()
    assert setup["gladia"]["connected"] and "k" * 36 not in str(setup)
    assert "gladia_key" not in client.get("/api/settings").json()


def test_gladia_out_of_hours_falls_back_to_groq(client, monkeypatch):
    from concall import cloud, config, gladia

    config.save_settings({"gladia_key": "k" * 36, "groq_key": "gsk_test"})
    fake, _d, _ = make_asr()
    gladia_calls = []

    def fake_gladia(audio, dur, key, progress):
        gladia_calls.append(1)
        raise gladia.GladiaUnavailable(gladia.quota_message(402, ""))

    monkeypatch.setattr(gladia, "transcribe", fake_gladia)
    monkeypatch.setattr(cloud, "transcribe", lambda audio, dur, prompt, key, progress: (
        progress(1.0), {"engine": "groq", "model": cloud.MODEL, "words": fake["words"]})[1])

    for period in ("Q1", "Q2"):
        r = client.post("/api/calls", data={"company": "Demo", "period": period},
                        files={"audio": ("call.mp3", io.BytesIO(_wav_bytes()), "audio/mpeg")})
        meta = _wait_ready(client, r.json()["id"])
        assert meta["status"] == "ready", meta
        assert meta["asr_service"] == "groq"
    # The first call told you why; the second didn't re-upload to Gladia.
    assert gladia_calls == [1]
    assert client.get("/api/setup").json()["gladia"]["paused"] is True


def test_gladia_and_groq_both_failing_asks_first(client, monkeypatch):
    from concall import cloud, config, gladia

    config.save_settings({"gladia_key": "k" * 36, "groq_key": "gsk_test"})

    def no_gladia(*a):
        raise gladia.GladiaUnavailable("Couldn't reach Gladia (no internet?): x")

    def no_groq(*a):
        raise cloud.CloudUnavailable("Couldn't reach Groq (no internet?): x")

    monkeypatch.setattr(gladia, "transcribe", no_gladia)
    monkeypatch.setattr(cloud, "transcribe", no_groq)
    r = client.post("/api/calls", data={"company": "Demo", "period": "Q1"},
                    files={"audio": ("call.mp3", io.BytesIO(_wav_bytes()), "audio/mpeg")})
    meta = _wait_ready(client, r.json()["id"])
    assert meta["status"] == "needs_input"
    assert "Gladia" in meta["decision"]["reason"] and "Groq" in meta["decision"]["reason"]


def test_report_hides_gladia_key(client):
    from concall import config, report

    config.save_settings({"gladia_key": "abcd1234-secret-key-value-0000"})
    assert "secret" not in report.redact("key=abcd1234-secret-key-value-0000")
