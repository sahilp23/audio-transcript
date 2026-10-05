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
- **Optional AI summary** using a local model through [Ollama](https://ollama.com). It's free and runs offline.
- **Player.** Playback speed from 0.75× to 2×, ±15 s skips, keyboard shortcuts (press `?`), media keys, and it remembers where you stopped.
- Copy the transcript, or download it as Markdown with timestamps and chapters.
- Works in light and dark mode.

## Setup (MacBook, Apple Silicon)

You only need to do this once.

```bash
# 1. Tools (if you don't have Homebrew: https://brew.sh)
brew install ffmpeg python@3.12

# 2. Get the code
git clone https://github.com/sahilp23/audio-transcript.git
cd audio-transcript

# 3. Start (the first run installs dependencies into .venv)
./run.sh
```

The app opens at <http://127.0.0.1:8765>. Leave the Terminal window open while you use it, and press `Ctrl+C` to stop.

The first time you transcribe a call, the speech model (Whisper large-v3-turbo, about 1.6 GB) is downloaded from Hugging Face. After that, everything works offline.

**Want to try the player before transcribing anything?** Run `.venv/bin/python scripts/demo.py`. It adds a short demo call with a placeholder tone instead of real speech, so you can try the interface.

### Optional: speaker separation for calls without a transcript

Without this, an auto transcript is one continuous text. Chapters, Q&A detection and key numbers still work, and attaching the official transcript adds speakers anyway. To have the app tell speakers apart on its own:

1. Create a free account at <https://huggingface.co>.
2. Open these two pages and accept the terms on each:
   - <https://huggingface.co/pyannote/speaker-diarization-3.1>
   - <https://huggingface.co/pyannote/segmentation-3.0>
3. Create a **Read** token at <https://huggingface.co/settings/tokens>.
4. Copy the example settings file: `cp .env.example .env`. Then edit `.env` and set `HF_TOKEN=hf_...`.
5. Run `./run.sh` again. It installs `pyannote.audio` automatically.

The top-right corner of the app shows `speakers on` once this is working. For calls you already transcribed, use **More… → Re-run speech-to-text** to separate speakers.

### Optional: AI summaries

1. Install [Ollama](https://ollama.com).
2. In Terminal, run `ollama pull llama3.2:3b`.
3. Keep Ollama running, then open a call → **Summary** → **Generate summary**.

To use a different model, set `OLLAMA_MODEL` in `.env`. A larger model gives better summaries if your Mac has enough memory.

## How it works

```
audio ──ffmpeg──▶ 16 kHz wav ──Whisper (mlx, Apple GPU)──▶ words + timings ─┐
                           └─pyannote (optional)──▶ who spoke when ─────────┤
company transcript (PDF/text) ──parser──▶ speaker turns ──aligner───────────┴─▶ doc.json ──▶ player
```

- **Speech-to-text:** [mlx-whisper](https://github.com/ml-explore/mlx-examples/tree/main/whisper) on Apple Silicon. On other machines it uses [faster-whisper](https://github.com/SYSTRAN/faster-whisper) on the CPU. The model gets a short vocabulary hint (company name, EBITDA, crores, FY27…) so finance terms are spelled correctly.
- **Lining up the official transcript with the audio:** company transcripts are edited, with fillers removed and grammar fixed, so they never match the audio word for word. The aligner matches the official words to the speech-to-text words. Matched words take the exact audio timing. Words that don't match get timings spread evenly between their matched neighbours. The sidebar shows the result as "N% synced". Aligning a one-hour call takes about 0.1 s, so attaching a transcript is quick.
- **Storage:** each call is a folder in `./data/calls/`, holding the audio and JSON files. To use a different location, set `CONCALL_DATA_DIR`. Bookmarks, notes and speaker names are kept in `user.json` in the call's folder. Re-processing a call doesn't touch them.

## Transcript formats

The app accepts a PDF (as filed on BSE/NSE), a .txt/.md file, or pasted text. It expects the usual Indian concall layout:

```
MANAGEMENT: MR. A B – MANAGING DIRECTOR – XYZ LIMITED
Moderator:   Ladies and gentlemen, good day…
A B:         Thank you…
```

Speaker roles are read from the participants list on the first page. Page headers, footers and page numbers are removed. If a transcript can't be parsed, the app tells you, and the call keeps its auto transcript.

## Settings (`.env`)

| Variable | Default | |
|---|---|---|
| `HF_TOKEN` | – | Turns on speaker separation |
| `MLX_MODEL` | `mlx-community/whisper-large-v3-turbo` | Speech model on Mac |
| `ASR_ENGINE` | `auto` | `mlx`, `faster`, or `auto` |
| `CONCALL_DATA_DIR` | `./data` | Where calls are stored |
| `OLLAMA_MODEL` | `llama3.2:3b` | Model for summaries |
| `PORT` | `8765` | |

## Development

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
```

## Roadmap

- **Live mode** (dial into the concall bridge or capture a webcast, then transcribe live). This is the next phase.
