# Concall Player

A local, Quartr-style player for earnings conference calls. You upload a call recording, and you get a transcript that highlights each word as it's spoken. It also builds a chapter timeline, a Q&A view, search, bookmarks and a list of key numbers. Everything runs on your Mac and costs nothing.

It's built for the companies Quartr doesn't cover. The company's official transcript is optional. Indian companies often publish it on BSE/NSE a few days after the call, so you can start listening with an automatic transcript and attach the official one when it arrives. The app then switches to the official wording and speaker names and keeps the audio sync.

## What you get

- **Word-by-word sync.** The current word is highlighted. Words already spoken in the current paragraph turn dark and the rest stay grey. Click any word to play from that point.
- **Speakers.** Each section shows the speaker's name, role and an avatar. Speakers come from the official transcript or from automatic speaker separation. Analyst names and firms are picked up from the moderator's "the next question is from…" lines.
- **Chapters.** The call is split into Introduction, Management remarks, Q&A, one chapter per analyst question, and Closing remarks. Chapters show up in the timeline, a jump list and the sidebar.
- **Remarks / Q&A filter.** Show only the prepared remarks or only the Q&A.
- **Key numbers.** A list of every sentence with a reported figure (%, crores, bps, ₹…). Guidance and outlook statements are tagged separately. Click one to jump to it.
- **Find in transcript.** Search phrases with next/previous. Matches are marked on the timeline.
- **Bookmarks with notes.** Press `B` to bookmark the current moment. Bookmarks appear as yellow marks on the timeline.
- **Notes.** Free-form notes per call.
- **Speakers panel.** Shows talk-time share for each speaker. You can rename auto-detected speakers (e.g. "Speaker 2" → "CFO") and jump to someone's next answer.
- **Optional AI summary** using a local model through [Ollama](https://ollama.com). It's free and runs offline. Setup steps are in the app under Settings.
- **Player.** Playback speed from 0.75× to 2×, ±15 s skips, keyboard shortcuts (press `?`), media keys, and it remembers where you stopped.
- Copy the transcript, or download it as Markdown with timestamps and chapters.
- Works in light and dark mode.

## Install

**Mac app (recommended):** see **[INSTALL.md](INSTALL.md)**. You download a `.dmg`, drag the app to Applications and open it. No Terminal needed. The app installs its speech engine on its own, has a guided Hugging Face setup in Settings, and updates itself.

**From source (developers):**

```bash
brew install ffmpeg python@3.12
git clone https://github.com/sahilp23/audio-transcript.git && cd audio-transcript
./run.sh              # creates .venv, installs everything, opens http://127.0.0.1:8765
```

`.venv/bin/python scripts/demo.py` adds a demo call so you can try the player without transcribing anything.

## How it works

```
audio ──ffmpeg──▶ 16 kHz wav ──Whisper (mlx, Apple GPU)──▶ words + timings ─┐
                           └─pyannote (optional)──▶ who spoke when ─────────┤
company transcript (PDF/text) ──parser──▶ speaker turns ──aligner───────────┴─▶ doc.json ──▶ player
```

- **Speech-to-text:** [mlx-whisper](https://github.com/ml-explore/mlx-examples/tree/main/whisper) on Apple Silicon. On other machines it uses [faster-whisper](https://github.com/SYSTRAN/faster-whisper) on the CPU. The model gets a short vocabulary hint (company name, EBITDA, crores, FY27…) so finance terms are spelled correctly.
- **Lining up the official transcript with the audio:** company transcripts are edited, with fillers removed and grammar fixed, so they never match the audio word for word. The aligner matches the official words to the speech-to-text words. Matched words take the exact audio timing. Words that don't match get timings spread evenly between their matched neighbours. The sidebar shows the result as "N% synced". Aligning a one-hour call takes about 0.1 s, so attaching a transcript is quick.
- **Storage:** each call is a folder in `calls/`, inside `~/Library/Application Support/Concall Player` for the app or `./data` when running from source. It holds the audio and JSON files. Bookmarks, notes and speaker names are kept in `user.json` in the call's folder. Re-processing a call doesn't touch them.

## Transcript formats

The app accepts a PDF (as filed on BSE/NSE), a .txt/.md file, or pasted text. It expects the usual Indian concall layout:

```
MANAGEMENT: MR. A B – MANAGING DIRECTOR – XYZ LIMITED
Moderator:   Ladies and gentlemen, good day…
A B:         Thank you…
```

Speaker roles are read from the participants list on the first page. Page headers, footers and page numbers are removed. If a transcript can't be parsed, the app tells you, and the call keeps its auto transcript.

## Project layout

| Path | What it is |
|---|---|
| `concall/server.py` | Local web server (FastAPI): all `/api/...` endpoints |
| `concall/pipeline.py` | Background job: audio → speech-to-text → speakers → transcript |
| `concall/cloud.py` | Groq cloud transcription (chunked upload, word timings) |
| `concall/asr.py`, `diarize.py` | On-Mac Whisper (mlx / faster-whisper) and pyannote wrappers |
| `concall/isolated.py` | Runs heavy model work in a separate low-priority process |
| `concall/report.py` | "Report a problem": redacted GitHub issue links |
| `concall/transcript_parser.py`, `align.py`, `structure.py` | Company-transcript parsing, audio alignment, chapters/speakers/key numbers |
| `concall/components.py` | Installs the speech engine and speaker separation in the background |
| `concall/hf.py` | Hugging Face token and model-terms checks |
| `concall/updater.py` | In-app updates from GitHub Releases |
| `concall/desktop.py` | Mac app entry point (native window via pywebview) |
| `concall/static/` | The interface (plain HTML/CSS/JS, no build step) |
| `packaging/macos/` | `.app` launcher, build script, icon, CI smoke test |
| `requirements.txt` | Core packages (the app's launcher installs these) |
| `requirements-engine.txt` | Speech engine (installed by the app on first launch) |
| `requirements-diarization.txt` | Speaker separation (installed when Hugging Face is connected) |

## Shipping a new version

1. Make the change, run `pytest`, and push a branch. CI ([.github/workflows/mac-app.yml](.github/workflows/mac-app.yml)) runs the tests, builds the `.app` on a real Mac, installs it fresh and transcribes a spoken sample. Each branch push also publishes a **preview** pre-release you can install to try the change.
2. Bump `__version__` in `concall/__init__.py` and add a `## <version>` section to `CHANGELOG.md`. That section becomes the "what's new" text in the app.
3. Merge to `main`. CI publishes release `v<version>` with the `.dmg`. Installed apps offer it as a one-click update. Changed dependencies in the `requirements*.txt` files are installed automatically on the next launch.

Optional repository secrets for fuller CI coverage (Settings → Secrets and variables → Actions): `GROQ_API_KEY` tests cloud transcription, and `HF_TOKEN` tests real speaker separation. Without them, those two checks are skipped.

Changes to the launcher (`packaging/macos/launcher.sh`) or `Info.plist` only reach people who download the new `.dmg`. Everything else updates in place.

## Settings for developers (environment variables or `.env`)

| Variable | Default | |
|---|---|---|
| `HF_TOKEN` | – | Hugging Face token (the app stores it in Settings instead) |
| `MLX_MODEL` | `mlx-community/whisper-large-v3-turbo` | Speech model on Apple Silicon |
| `ASR_ENGINE` | `auto` | `mlx`, `faster`, or `auto` |
| `CONCALL_SUPPORT_DIR` | `./data` (app: `~/Library/Application Support/Concall Player`) | Where calls and settings are stored |
| `OLLAMA_MODEL` | `llama3.2:3b` | Model for summaries |
| `PORT` | `8765` | |

## Roadmap

- **Live mode** (dial into the concall bridge or capture a webcast, then transcribe live). This is the next phase.
