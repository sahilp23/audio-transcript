# Concall Player website: one-time setup (about 20 minutes)

The website is your own private copy of Concall Player on the internet. You open it in any browser (office PC, Mac, phone) and sign in with your Google account. Calls are saved in your **Google Drive**, in a folder called **Concall Player**. Transcription runs in the cloud (Gladia, then Groq), as in the Mac app.

It runs on **Render's free plan**. After about 15 minutes without visitors it goes to sleep. The next visit wakes it up, which can take **up to a minute**. That's normal.

You'll set up three things, in this order:

1. **Render**: hosts the website.
2. **Google Cloud**: lets the website sign you in and save calls to your Drive.
3. Paste two Google codes into Render, then sign in.

---

## Part 1: Create the website on Render (5 min)

1. Go to <https://render.com> and **Sign up**. Use a **new account**, not the one you use for Vantage. Free plans share their monthly hours across everything in an account, and Vantage uses a lot.
2. In the Render dashboard click **New → Blueprint**.
3. Connect GitHub when asked, then pick the repository **sahilp23/audio-transcript**.
4. Render reads the settings from the project and asks for three values:
   - **GOOGLE_CLIENT_ID** and **GOOGLE_CLIENT_SECRET**: type `later` for both for now; you'll replace them in Part 3.
   - **ALLOWED_EMAILS**: your Gmail address, e.g. `you@gmail.com`. Only this address can sign in.
5. Click **Apply** (or **Deploy Blueprint**). The first build takes a few minutes.
6. Open the service **concall-player** and copy its address at the top, e.g. `https://concall-player.onrender.com` (it may have extra letters at the end). You'll need it in Part 2.

Opening that address now shows *"Almost there"*. That's expected until Part 3 is done.

## Part 2: Allow Google sign-in and Drive (10 min)

1. Go to <https://console.cloud.google.com> and sign in with the **same Google account** you'll use for the website.
2. At the top, open the project list → **New project**. Name it `Concall Player` → **Create**. Make sure it's selected afterwards.
3. Search the top bar for **Google Drive API** → open it → **Enable**.
4. Search for **Google Auth Platform** (it may also be called **OAuth consent screen**) → **Get started**:
   - App name: `Concall Player`. Support email: your address. → **Next**
   - Audience: **External** → **Next**
   - Contact email: your address → **Next** → agree → **Create**
5. In Google Auth Platform → **Data access** → **Add or remove scopes**. Tick **`.../auth/drive.file`** ("See, edit, create and delete only the specific Google Drive files you use with this app"). If it isn't in the list, paste `https://www.googleapis.com/auth/drive.file` under *Manually add scopes*. → **Update** → **Save**.
6. **Audience** → **Publish app** → **Confirm**. This matters: while an app is in "Testing", Google signs you out every 7 days.
7. **Clients** → **Create client**:
   - Application type: **Web application**. Name: `Concall Player website`.
   - **Authorized redirect URIs** → **Add URI**: your Render address from Part 1 followed by `/auth/callback`, e.g. `https://concall-player.onrender.com/auth/callback`
   - **Create**. Copy the **Client ID** and **Client secret** that appear.

## Part 3: Put the Google codes into Render (2 min)

1. Render → **concall-player** → **Environment**.
2. Edit **GOOGLE_CLIENT_ID** and **GOOGLE_CLIENT_SECRET**: replace `later` with the values from Part 2.
3. **Save changes**. Render restarts the website (about a minute).

## Part 4: Sign in

1. Open your Render address. Google asks you to sign in.
2. Google may say **"Google hasn't verified this app"**. It's your own app, so click **Advanced → Go to Concall Player (unsafe)**.
3. Allow the two permissions: your email address, and Concall Player's own files in Google Drive. The site can't see the rest of your Drive.
4. You're in. Open **Settings** (⚙) and connect **Gladia** and **Groq** with the same keys as in the Mac app. You can copy them again from app.gladia.io and console.groq.com.

## Part 5: Copy your calls from the Mac app

1. Mac app: **Settings → Your data → Export calls for the website**. A folder **Concall Player calls** appears in your Downloads.
2. Website, on the Mac: **Settings → Your calls → Import calls**, then choose that folder. Each call is uploaded to your Google Drive; nothing is transcribed again.

---

## Good to know

- **Same calls everywhere.** The office PC, the Mac and your phone all show the same calls, bookmarks and notes.
- **Sleeping.** The first visit after a quiet period takes up to a minute. The page loads by itself once the site is awake.
- **Updates.** When a new version is released, Render updates the website automatically within a few minutes.
- **Storage.** Each call takes about 20–60 MB of your Google Drive.
- **Privacy.** Your call recordings and keys are kept in your Google Drive. The free server keeps nothing between sleeps, and your sign-in is stored only in your browser, encrypted.
- **If your office blocks it.** Some office networks block `onrender.com` addresses. If the site doesn't open at work but does at home, that's the reason.
