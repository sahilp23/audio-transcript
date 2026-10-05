# Changelog

Each `## <version>` section becomes the release notes shown in the app's update screen.

## 0.3.2
- The transcript opens as soon as cloud transcription finishes (about a minute); speaker separation continues in the background and the speaker names appear when it's done.
- Speaker separation shows real progress (it used to sit at 82% with no sign of life) and has a **Skip** button.
- Speaker separation is much faster: it now processes audio in batches, and gentle mode uses a few normal CPU cores at low priority instead of only the slowest ones.

## 0.3.1
- Fixed: connecting Groq failed with "Groq rejected this key" even for valid keys. Groq's firewall was blocking the app's requests; the app now identifies itself properly.
- Clearer Groq error messages (an invalid key vs. a blocked request).

## 0.3.0
- **Fast cloud transcription (free):** connect a free Groq account in Settings and a 1-hour call is transcribed in about a minute, without slowing your Mac.
- If the cloud isn't available, the app now **asks first** before using your Mac, and offers a **gentle mode** that keeps the Mac usable (slower).
- Speaker separation and on-Mac transcription run in the background at low priority and give their memory back when done (better on 8 GB Macs).
- Fixed: speaker separation failing with "Weights only load failed".
- **Clear voice** button in the player: less background noise, steadier volume. Audio is also lightly cleaned up before transcription.
- **Report a problem** button (bug icon, top right): opens a pre-filled GitHub issue with the error and recent log lines, with tokens and your user name removed.
- The window can now be resized to half the screen; the side panel can be hidden (and starts hidden in narrow windows).
- Notifications when a transcript is ready or needs your OK.

## 0.2.0
- Concall Player is now a Mac app: download, drag to Applications, double-click.
- Speech engine and model install themselves on first launch, with progress in the app.
- Settings screen with guided Hugging Face connection for speaker separation.
- One-click in-app updates.
- "Detect speakers" for calls transcribed before speaker separation was set up.

## 0.1.0
- First version: upload a call, synced word-by-word transcript, chapters, Q&A filter, search, key numbers, bookmarks, notes, AI summary via Ollama.
