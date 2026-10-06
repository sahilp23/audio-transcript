# Installing Concall Player

- [Mac](#mac)
- [Windows](#windows)
- [Use it from another computer (e.g. a locked-down office PC)](#use-it-from-another-computer)

## Mac

No Terminal and no technical setup are needed. You need a Mac with Apple Silicon (M1, M2, M3 or M4) running macOS 13.5 Ventura or newer, and an internet connection the first time.

### 1. Download

Go to the **Releases** page of this project:
<https://github.com/sahilp23/audio-transcript/releases>

Under the newest version, click **Concall-Player.dmg** to download it.

### 2. Install

1. Open the downloaded **Concall-Player.dmg**.
2. Drag **Concall Player** onto the **Applications** folder in that window.
3. Close the window, then eject the disk image (the ⏏ button next to it in Finder's sidebar).

### 3. First launch (one time only)

The app isn't from the App Store, so macOS asks you to approve it once:

1. Open **Applications** and double-click **Concall Player**. macOS says it can't verify the app. Close that message with **Done** or **OK** (not *Move to Trash*).
2. Open  → **System Settings** → **Privacy & Security**.
3. Scroll down. Next to *"Concall Player" was blocked…*, click **Open Anyway**, then confirm with your password or Touch ID.

From then on it opens normally, like any other app. You can keep it in the Dock: right-click its icon → Options → Keep in Dock.

**The very first time** the app sets itself up:

- **About a minute:** it gets ready, then the window opens.
- **A few more minutes, in the background:** it downloads the speech engine and model (about 2 GB in total). A purple badge at the top shows the progress. You can add a call straight away; it starts transcribing as soon as the setup is done.

### 4. Recommended: connect free cloud transcription (Gladia and Groq)

Open **Settings** (the ⚙ gear at the top right):

- **Transcription + speakers (Gladia):** follow the 3 steps (create a free Gladia account, copy your API key, paste it in). Calls are then transcribed **and** split by speaker in the cloud. The free plan covers about 10 hours of audio a month.
- **Backup transcription (Groq):** follow the 3 steps (free Groq account, API key, paste). Used when Gladia's free hours are used up: a 1-hour call takes about a minute, but without speakers. The free plan covers roughly 8 hours of audio a day.

If the cloud isn't available (no internet, or the daily free limit is used up), the app asks you before transcribing on your Mac. You can then choose **gentle** mode, which keeps the Mac usable but is slower, or **fast** mode.

### 5. Optional: let the app tell speakers apart

Open **Settings** (the ⚙ gear at the top right) → **Speaker separation**, and follow the 4 steps on screen. It takes about 3 minutes and uses a free Hugging Face account. The app checks each step and tells you if something is missing.

You don't strictly need this. When you attach the company's transcript to a call, speaker names come from the transcript.

### Updates

When a new version is out, the app shows a banner. Click **See what's new** → **Install update** → **Restart now**. Your calls, bookmarks and notes are kept.

If an update ever fails to start, the app goes back to the version you installed from the DMG on its own.

### Where your data is

Everything stays on your Mac, in your user folder at
`Library/Application Support/Concall Player`.
**Settings → Your data → Show in Finder** opens it.

To remove the app completely, delete it from Applications and delete that folder.

### If something goes wrong

Click the **bug icon** at the top right (**Report a problem**), or the **Report** button next to an error. Describe what happened, then click **Continue to GitHub** → **Submit new issue**. The report includes the error and recent log lines, with your tokens and Mac user name removed. Then tell Claude to "fix the open issues".

- **The app doesn't open after "Open Anyway":** open it again from Applications. The first launch needs internet.
- **"Setup needs attention" badge:** open Settings and click **Try again**. This is usually an internet hiccup.
- **Anything else:** Settings → **Open log files**, and send the file `app.log`.


## Windows

You need a 64-bit Windows 10 or 11 PC and an internet connection the first time. No administrator rights are needed: the app installs for your Windows user only.

1. Go to the **Releases** page: <https://github.com/sahilp23/audio-transcript/releases>. Under the newest version, click **Concall-Player-Setup.exe** to download it.
2. Open the downloaded file. The app isn't from a known publisher, so Windows may show **"Windows protected your PC"**. Click **More info**, then **Run anyway**.
3. Click through the installer. Near the end it downloads Python and the app's components (about a minute). Leave **Open Concall Player** ticked and click **Finish**.

Afterwards, open it from the **Start menu** (type "Concall") or the desktop shortcut. Everything else (connecting Gladia or Groq in Settings, speaker separation, updates) works as on the Mac.

**On an office PC:** if the installer or the app is blocked (a message from your company's security software, or nothing happens), your IT team has locked down installing apps. Ask IT to allow it, or use Concall Player on your Mac.

Your calls, notes and settings are stored in `%LOCALAPPDATA%\Concall Player`. Uninstalling the app (Settings → Apps) keeps them.


## Use it from another computer

If you can't install apps on a computer (e.g. your office PC), you can open Concall Player running on your Mac from that computer's web browser.

**On the Mac (once):**
1. Open **Settings** → **Use from other computers**.
2. Enter your email address and choose a password (at least 8 characters), then **Save**.
3. Click **Turn on**. After a few seconds a link like `https://some-random-words.trycloudflare.com` appears. Click **Email me the link** (or **Copy**).

**On the other computer:**
1. Open the link in the browser.
2. Cloudflare asks for your email and emails you a code. Enter it.
3. Enter your Concall Player password. The browser remembers it for 30 days.

**Good to know:**
- The Mac must be **on, online, plugged in and with the lid open**, with Concall Player running. The app stops it from going to sleep while the link is on.
- **The link changes** whenever Concall Player or the Mac restarts (for example after an update). Get the new one from Settings, or with **Email me the link**.
- It's light work for the Mac. Transcription runs in the cloud (Gladia/Groq) as usual.
- Uploads through the link are limited to about 100 MB per file (use MP3/M4A recordings).
- Settings, connections and updates can only be changed on the Mac itself.
- The link uses Cloudflare's free "quick tunnel" service, which has no uptime guarantee. If it stops, the app reconnects on its own and shows the new link.
- Some offices block such links. If the link doesn't open at all at work, that's the reason.
