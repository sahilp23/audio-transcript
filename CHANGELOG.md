# Changelog

Each `## <version>` section becomes the release notes shown in the app's update screen.

## 0.7.1
- Website: when Google ends your sign-in (weekly while the Google project is in "Testing"), you're taken straight to Google's sign-in instead of seeing an error.
- Website setup: stray spaces in the Google codes are ignored, and a wrong-looking Client ID is explained on the page. The guide now uses Testing mode with yourself as a test user (publishing needs a domain you own).

## 0.7.0
- **Concall Player website**: your own private copy on the internet (free hosting on Render), for any browser, including the office PC. Sign in with Google; calls are saved in your Google Drive. Setup guide: docs/WEBSITE.md.
- **Export calls for the website** (Settings → Your data): copies your calls so you can import them on the website without transcribing again.
- Removed "Use from other computers" (the Cloudflare link). The website replaces it.

## 0.6.1
- Remote link: when Cloudflare's sign-in runs out (it lasts about 4 hours) or the connection to your Mac drops, the page now reloads so you can sign in again, instead of showing "Can't reach the app server · Failed to fetch". If your Mac really can't be reached, it says so and why.

## 0.6.0
- **Use Concall Player from another computer** (e.g. a locked-down office PC), with nothing to install there: Settings → **Use from other computers** → set your email and a password → **Turn on**. You get a private link that opens the app running on your Mac. Two locks: a one-time code emailed to you (by Cloudflare), and your password.
- Your Mac must stay on, awake and online with Concall Player open; it's kept from sleeping while this is on (keep the lid open). The link changes when the app restarts: **Copy** or **Email me the link** in Settings.

## 0.5.0
- **Concall Player for Windows:** download `Concall-Player-Setup.exe` from the Releases page. It installs for your Windows user only (no administrator rights needed) and works like the Mac app, including cloud transcription, in-app updates and Report a problem.
- Messages say "this PC" or "this Mac" depending on the computer.

## 0.4.0
- **Speakers from the cloud (free):** connect a free Gladia account in Settings and each call is transcribed **and** split by speaker in the cloud, in a few minutes, without the slow speaker separation on your Mac. The free plan covers about 10 hours of audio a month.
- When Gladia's free hours are used up (or it's unreachable), the app uses Groq automatically and tells you why; if that also fails, it asks before using your Mac, as before.
- Each call shows which service transcribed it (Gladia, Groq or this Mac).

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
