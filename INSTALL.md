# Installing Concall Player (Mac)

No Terminal and no technical setup are needed. You need a Mac with Apple Silicon (M1, M2, M3 or M4) running macOS 13.5 Ventura or newer, and an internet connection the first time.

## 1. Download

Go to the **Releases** page of this project:
<https://github.com/sahilp23/audio-transcript/releases>

Under the newest version, click **Concall-Player.dmg** to download it.

## 2. Install

1. Open the downloaded **Concall-Player.dmg**.
2. Drag **Concall Player** onto the **Applications** folder in that window.
3. Close the window, then eject the disk image (the ⏏ button next to it in Finder's sidebar).

## 3. First launch (one time only)

The app isn't from the App Store, so macOS asks you to approve it once:

1. Open **Applications** and double-click **Concall Player**. macOS says it can't verify the app. Close that message with **Done** or **OK** (not *Move to Trash*).
2. Open  → **System Settings** → **Privacy & Security**.
3. Scroll down. Next to *"Concall Player" was blocked…*, click **Open Anyway**, then confirm with your password or Touch ID.

From then on it opens normally, like any other app. You can keep it in the Dock: right-click its icon → Options → Keep in Dock.

**The very first time** the app sets itself up:

- **About a minute:** it gets ready, then the window opens.
- **A few more minutes, in the background:** it downloads the speech engine and model (about 2 GB in total). A purple badge at the top shows the progress. You can add a call straight away; it starts transcribing as soon as the setup is done.

## 4. Optional: let the app tell speakers apart

Open **Settings** (the ⚙ gear at the top right) → **Speaker separation**, and follow the 4 steps on screen. It takes about 3 minutes and uses a free Hugging Face account. The app checks each step and tells you if something is missing.

You don't strictly need this. When you attach the company's transcript to a call, speaker names come from the transcript.

## Updates

When a new version is out, the app shows a banner. Click **See what's new** → **Install update** → **Restart now**. Your calls, bookmarks and notes are kept.

If an update ever fails to start, the app goes back to the version you installed from the DMG on its own.

## Where your data is

Everything stays on your Mac, in your user folder at
`Library/Application Support/Concall Player`.
**Settings → Your data → Show in Finder** opens it.

To remove the app completely, delete it from Applications and delete that folder.

## If something goes wrong

- **The app doesn't open after "Open Anyway":** open it again from Applications. The first launch needs internet.
- **"Setup needs attention" badge:** open Settings and click **Try again**. This is usually an internet hiccup.
- **Anything else:** Settings → **Open log files**, and send the file `app.log`.
