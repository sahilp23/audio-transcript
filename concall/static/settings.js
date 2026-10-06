/* Settings screen: setup progress, Hugging Face connection, updates, data. */
"use strict";

const Settings = {
  setup: null,
  hfResult: null,
  update: null,
  pollTimer: null,

  /* ---------- background: setup pill + update banner on every page ---------- */

  async watchSetup() {
    try {
      this.setup = await api.get("/api/setup");
    } catch { this.setup = null; }
    this.renderPill();
    const running = this.anyRunning();
    if (state.page === "settings") this.renderSetupBlocks();
    setTimeout(() => this.watchSetup(), running ? 1500 : 5000);
  },

  anyRunning() {
    const c = this.setup?.components;
    return !!c && Object.values(c).some((x) => x.state === "running");
  },

  renderPill() {
    const pill = $("#engine-status");
    const c = this.setup?.components;
    if (!c) { pill.classList.add("hidden"); return; }
    let text = "", cls = "";
    const eng = c.engine, model = c.speech_model;
    if (eng.state === "error" || model.state === "error") { text = "Setup needs attention"; cls = "err"; }
    else if (eng.state === "running" || (!eng.installed && state.status?.app_mode)) { text = "Setting up speech engine…"; }
    else if (model.state === "running") { text = `Downloading speech model ${model.progress ? Math.round(model.progress * 100) + "%" : "…"}`; }
    else if (c.speakers.state === "running" || c.speaker_model.state === "running") { text = "Setting up speaker separation…"; }
    pill.textContent = text;
    pill.className = `setup-pill ${cls} ${text ? "" : "hidden"}`;
    pill.onclick = () => (location.hash = "#/settings");
  },

  async checkUpdateQuietly() {
    if (!state.status?.app_mode || state.status?.remote) return;
    try {
      const s = await api.get("/api/settings");
      if (!s.auto_update_check) return;
      this.update = await api.get("/api/update");
      this.renderBanner();
    } catch {}
  },

  renderBanner() {
    const b = $("#update-banner");
    const u = this.update;
    if (!u?.available || state.page === "settings") { b.classList.add("hidden"); return; }
    b.innerHTML = `<span>Version ${esc(u.latest)} is available.</span> <a href="#/settings" class="btn small primary">See what's new</a>`;
    b.classList.remove("hidden");
  },

  /* ---------- the page ---------- */

  async render() {
    state.page = "settings";
    $("#update-banner").classList.add("hidden");
    const view = $("#view");
    view.innerHTML = `<div class="settings"><h1>Settings</h1><p class="muted">Loading…</p></div>`;
    if (state.status?.remote) { this.renderRemotePage(view); return; }
    let settings, setup, upd;
    try {
      [settings, setup, upd] = await Promise.all([api.get("/api/settings"), api.get("/api/setup"), api.get("/api/update").catch(() => null)]);
    } catch (e) { view.innerHTML = `<div class="settings"><p class="error">${esc(e.message)}</p></div>`; return; }
    if (state.page !== "settings") return;
    this.setup = setup; this.settings = settings; this.update = upd || this.update;
    const st = state.status || {};
    view.innerHTML = `
      <div class="settings">
        <a href="#/" class="back">← Your calls</a>
        <h1>Settings</h1>

        <section class="card" id="gladia-card">
          <h2>Transcription + speakers <span class="badge">cloud via Gladia · free 10 h/month</span></h2>
          <p class="muted small">Tried first. Gladia transcribes the call <b>and</b> tells the speakers apart in one go, so the slow speaker separation on this ${DEV()} isn't needed. The free plan covers about 10 hours of audio a month (calls up to 2¼ hours each). The call audio is uploaded to Gladia for this. When the free hours run out, the app uses Groq below.</p>
          <div id="gladia-body"></div>
        </section>

        <section class="card" id="groq-card">
          <h2>Backup transcription <span class="badge">cloud via Groq · free</span></h2>
          <p class="muted small">Used when Gladia isn't connected or its free hours are used up. Calls are transcribed on Groq's servers with the Whisper model: a 1-hour call takes about a minute and your ${DEV()} stays free. The free plan covers roughly 8 hours of audio a day. Groq gives words only, so speakers are then separated on this ${DEV()} (if set up below). The call audio is uploaded to Groq for this.</p>
          <div id="groq-body"></div>
        </section>

        <section class="card">
          <h2>On this ${DEV()}</h2>
          <p class="muted small">Used when the cloud isn't available (you're asked first), and for speaker separation.</p>
          <div id="setup-speech"></div>
          <div id="mac-mode"></div>
        </section>

        <section class="card" id="hf-card">
          <h2>Speaker separation <span class="badge">via Hugging Face · free</span></h2>
          <p class="muted small">Lets the app tell speakers apart (management vs analysts) when the company transcript isn't out yet. It uses free models from Hugging Face, which need a one-time sign-up. Not needed for calls transcribed by Gladia (it finds speakers itself); used when Groq or this ${DEV()} did the transcription. It's slow on computers with 8 GB of memory.</p>
          <div id="hf-body"></div>
        </section>

        <section class="card" id="remote-card">
          <h2>Use from other computers <span class="badge">via Cloudflare · free</span></h2>
          <p class="muted small">Open Concall Player from another computer's web browser (e.g. your office PC), with nothing to install there. This ${DEV()} stays in charge: it must be <b>on, awake and online</b>, with Concall Player open. Two locks protect it: a one-time code sent to your email (by Cloudflare), and a password you choose here.</p>
          <div id="remote-body"></div>
        </section>

        <section class="card">
          <h2>AI summaries <span class="badge">optional</span></h2>
          <div id="ollama-body">${this.ollamaHtml(st.ollama || {})}</div>
        </section>

        <section class="card">
          <h2>Updates</h2>
          <div id="update-body"></div>
          <label class="check"><input type="checkbox" id="auto-update" ${settings.auto_update_check ? "checked" : ""}> Check for updates when the app opens</label>
        </section>

        <section class="card">
          <h2>Your data</h2>
          <p class="small">Calls, transcripts, bookmarks and notes are stored only on this ${DEV()}:<br><code>${esc(st.data_dir || "")}</code></p>
          <div class="row-actions">
            <button class="btn small" id="reveal-data">${IS_WIN() ? "Open folder" : "Show in Finder"}</button>
            ${st.app_mode ? `<button class="btn small ghost" id="reveal-logs">Open log files</button>` : ""}
            <button class="btn small ghost" data-report="">Report a problem</button>
          </div>
        </section>
        <p class="muted small center">Concall Player ${esc(st.version || "")}</p>
      </div>`;
    this.renderSetupBlocks();
    this.renderUpdate();
    this.renderRemote();
    $("#auto-update").onchange = (e) => api.patch("/api/settings", { auto_update_check: e.target.checked });
    $("#reveal-data").onclick = () => api.post("/api/reveal", { what: "data" }).catch((e) => toast(e.message));
    $("#reveal-logs")?.addEventListener("click", () => api.post("/api/reveal", { what: "logs" }).catch((e) => toast(e.message)));
  },

  renderSetupBlocks() {
    if (state.page !== "settings" || !this.setup) return;
    const c = this.setup.components;
    const sp = $("#setup-speech");
    if (sp) {
      sp.innerHTML = this.statusRow("Speech engine", c.engine, "engine") +
        (c.speech_model.repo ? this.statusRow(`Speech model <span class="muted small">(${esc(c.speech_model.repo.split("/").pop())}, about 1.6 GB)</span>`, c.speech_model, "speech_model") : "");
      $$("[data-retry]", sp).forEach((b) => (b.onclick = () => this.start(b.dataset.retry)));
    }
    this.renderGladia();
    this.renderGroq();
    this.renderMacMode();
    const hf = $("#hf-body");
    // Don't redraw the form while you're typing the token.
    if (hf && !hf.contains(document.activeElement)) this.renderHf();
  },

  statusRow(title, comp, key) {
    let icon, text, extra = "";
    if (comp.state === "running") {
      icon = `<span class="spinner"></span>`;
      text = esc(comp.message || "Working…");
      if (comp.progress != null) extra = `<div class="progress"><div style="width:${Math.round(comp.progress * 100)}%"></div></div>`;
    } else if (comp.state === "error") {
      icon = `<span class="dot err">!</span>`;
      text = `<span class="error">${esc(comp.error || "Failed")}</span>`;
      extra = `<button class="btn small" data-retry="${key}">Try again</button> <button class="btn small ghost" data-report="${esc(title.replace(/<[^>]+>/g, "") + ": " + (comp.error || ""))}">Report</button>`;
    } else if (comp.installed || comp.state === "done") {
      icon = `<span class="dot ok">✓</span>`; text = "Ready";
    } else {
      icon = `<span class="dot"></span>`; text = "Not installed yet";
      extra = `<button class="btn small" data-retry="${key}">Install now</button>`;
    }
    return `<div class="status-row">${icon}<div class="grow"><div class="title">${title}</div><div class="small muted">${text}</div>${extra.startsWith("<div") ? extra : ""}</div>${extra.startsWith("<button") ? `<div class="row-actions" style="margin:0">${extra}</div>` : ""}</div>`;
  },

  async start(key) {
    try { this.setup.components = await api.post(`/api/setup/${key}`); } catch (e) { toast(e.message); }
    this.renderSetupBlocks();
  },

  renderHf() {
    const el = $("#hf-body");
    const hf = this.setup.hf, c = this.setup.components;
    const r = this.hfResult;

    if (hf.connected && hf.ready) {
      const busy = c.speakers.state === "running" || c.speaker_model.state === "running";
      const failed = c.speakers.state === "error" ? c.speakers : c.speaker_model.state === "error" ? c.speaker_model : null;
      el.innerHTML = `
        <div class="status-row"><span class="dot ok">✓</span><div class="grow">
          <div class="title">Connected${hf.username ? ` as <b>${esc(hf.username)}</b>` : ""}</div>
          <div class="small muted">Token ${esc(hf.token_hint)}</div></div></div>
        ${busy ? this.statusRow("Getting speaker separation ready", c.speakers.state === "running" ? c.speakers : c.speaker_model, "speaker_model")
          : failed ? this.statusRow("Speaker separation", failed, "speaker_model")
          : c.speakers.installed ? `<div class="status-row"><span class="dot ok">✓</span><div class="grow"><div class="title">Ready</div><div class="small muted">New calls without a company transcript get speakers automatically. For older calls, open the call → Speakers tab → Detect speakers.</div></div></div>`
          : this.statusRow("Speaker separation", { state: "idle" }, "speaker_model")}
        <label class="check"><input type="checkbox" id="diar-toggle" ${hf.enabled ? "checked" : ""}> Separate speakers on new calls</label>
        <div class="row-actions"><button class="btn small ghost" id="hf-disconnect">Disconnect</button></div>`;
      $("#diar-toggle").onchange = async (e) => { await api.patch("/api/settings", { diarization: e.target.checked }); this.refresh(); };
      $("#hf-disconnect").onclick = async () => {
        if (!confirm("Disconnect Hugging Face? New calls won't be split by speaker.")) return;
        await api.post("/api/hf/disconnect"); this.hfResult = null; this.refresh();
      };
      $$("[data-retry]", el).forEach((b) => (b.onclick = () => this.start(b.dataset.retry)));
      return;
    }

    const missing = new Set((r?.missing_terms || []).map((m) => m.repo));
    const termsChecked = r && r.token_valid;
    const step = (n, done, title, body) => `
      <li class="step ${done ? "done" : ""}"><span class="num">${done ? "✓" : n}</span>
        <div class="grow"><div class="title">${title}</div>${body}</div></li>`;
    el.innerHTML = `
      <ol class="steps">
        ${step(1, hf.connected || termsChecked, "Create a free Hugging Face account",
          `<div class="small muted">Skip if you already have one.</div><a class="btn small" href="${esc(hf.join_url)}">Open huggingface.co</a>`)}
        ${step(2, termsChecked && !missing.size, "Accept the terms of these two models",
          `<div class="small muted">On each page, log in and click the button to agree (if it asks for a company or website, anything honest is fine, e.g. “personal research”).</div>
           <div class="row-actions">${hf.models.map((m) => `
             <a class="btn small ${missing.has(m.repo) ? "attention" : ""}" href="${esc(m.url)}">${termsChecked ? (missing.has(m.repo) ? "✗ " : "✓ ") : ""}${esc(m.repo.split("/")[1])}</a>`).join("")}</div>
           ${missing.size ? `<div class="small error">Not accepted yet: ${[...missing].map(esc).join(", ")}. Accept, then press “Check again”.</div>` : ""}`)}
        ${step(3, hf.connected || termsChecked, "Create an access token",
          `<div class="small muted">Click <b>Create new token</b>, choose type <b>Read</b>, type any name (e.g. “Concall Player”), click <b>Create token</b>, then <b>Copy</b>.</div><a class="btn small" href="${esc(hf.token_url)}">Open token page</a>`)}
        ${step(4, false, "Paste the token here",
          `<div class="token-row">
             <input id="hf-token" type="password" placeholder="hf_…" autocomplete="off" spellcheck="false" value="">
             <button class="btn primary small" id="hf-connect">${hf.connected ? "Connect again" : "Connect"}</button>
             ${hf.connected ? `<button class="btn small" id="hf-recheck">Check again</button>` : ""}
           </div>
           <div id="hf-msg" class="small">${r?.error ? `<span class="error">${esc(r.error)}</span>` : hf.connected && !hf.ready ? `<span class="muted">Token saved${hf.username ? ` for ${esc(hf.username)}` : ""}. Finish step 2, then press “Check again”.</span>` : ""}</div>`)}
      </ol>`;
    const connect = async () => {
      const token = $("#hf-token").value.trim();
      $("#hf-msg").innerHTML = `<span class="spinner"></span> Checking with Hugging Face…`;
      try { this.hfResult = await api.post("/api/hf/connect", { token }); } catch (e) { this.hfResult = { error: e.message }; }
      if (this.hfResult.ok) toast("Connected to Hugging Face. Setting up speaker separation…", 4000);
      $("#hf-token").blur();
      this.refresh();
    };
    $("#hf-connect").onclick = connect;
    $("#hf-token").addEventListener("keydown", (e) => { if (e.key === "Enter") connect(); });
    $("#hf-recheck")?.addEventListener("click", async () => {
      $("#hf-msg").innerHTML = `<span class="spinner"></span> Checking…`;
      try { this.hfResult = await api.post("/api/hf/check"); } catch (e) { this.hfResult = { error: e.message }; }
      if (this.hfResult.ok) toast("All set. Setting up speaker separation…", 4000);
      this.refresh();
    });
  },

  renderGladia() {
    const el = $("#gladia-body");
    if (!el || el.contains(document.activeElement) || !this.setup.gladia) return;
    const g = this.setup.gladia;
    if (g.connected) {
      el.innerHTML = `
        <div class="status-row"><span class="dot ${g.paused ? "" : "ok"}">${g.paused ? "!" : "✓"}</span><div class="grow">
          <div class="title">${g.paused ? "Connected, free hours used up" : "Connected"}</div>
          <div class="small muted">Key ${esc(g.key_hint)}. ${g.paused
            ? "Gladia's free hours ran out, so new calls use Groq for now. The app tries Gladia again after a day, or when you press “Try the cloud again” on a call."
            : "New calls are transcribed and split by speaker in the cloud."}</div></div>
          <button class="btn small ghost" id="gladia-disconnect">Disconnect</button></div>`;
      $("#gladia-disconnect").onclick = async () => {
        if (!confirm(`Disconnect Gladia? New calls will use Groq (if connected) or ask before using this ${DEV()}.`)) return;
        await api.post("/api/gladia/disconnect"); this.refresh();
      };
      return;
    }
    el.innerHTML = `
      <ol class="steps">
        <li class="step"><span class="num">1</span><div class="grow"><div class="title">Create a free Gladia account</div>
          <div class="small muted">Sign up with Google or email. No card needed for the free plan.</div><a class="btn small" href="${esc(g.signup_url)}">Open app.gladia.io</a></div></li>
        <li class="step"><span class="num">2</span><div class="grow"><div class="title">Copy your API key</div>
          <div class="small muted">In the Gladia dashboard, open <b>API keys</b> (left-hand menu), create or copy a key.</div></div></li>
        <li class="step"><span class="num">3</span><div class="grow"><div class="title">Paste the key here</div>
          <div class="token-row"><input id="gladia-key" type="password" placeholder="Gladia API key" autocomplete="off" spellcheck="false">
          <button class="btn primary small" id="gladia-connect">Connect</button></div>
          <div id="gladia-msg" class="small">${this.gladiaError ? `<span class="error">${esc(this.gladiaError)}</span>` : ""}</div></div></li>
      </ol>`;
    const connect = async () => {
      $("#gladia-msg").innerHTML = `<span class="spinner"></span> Checking the key with Gladia…`;
      try {
        const r = await api.post("/api/gladia/connect", { key: $("#gladia-key").value.trim() });
        this.gladiaError = r.ok ? "" : r.error;
        if (r.ok) toast("Gladia connected. Calls waiting for transcription start now.", 4000);
      } catch (e) { this.gladiaError = e.message; }
      $("#gladia-key").blur();
      this.refresh();
    };
    $("#gladia-connect").onclick = connect;
    $("#gladia-key").addEventListener("keydown", (e) => { if (e.key === "Enter") connect(); });
  },

  renderGroq() {
    const el = $("#groq-body");
    if (!el || el.contains(document.activeElement) || !this.setup.groq) return;
    const g = this.setup.groq;
    if (g.connected) {
      el.innerHTML = `
        <div class="status-row"><span class="dot ok">✓</span><div class="grow">
          <div class="title">Connected</div><div class="small muted">Key ${esc(g.key_hint)}. New calls are transcribed in the cloud.</div></div>
          <button class="btn small ghost" id="groq-disconnect">Disconnect</button></div>`;
      $("#groq-disconnect").onclick = async () => {
        if (!confirm(`Disconnect Groq? New calls will ask before transcribing on this ${DEV()}.`)) return;
        await api.post("/api/groq/disconnect"); this.refresh();
      };
      return;
    }
    el.innerHTML = `
      <ol class="steps">
        <li class="step"><span class="num">1</span><div class="grow"><div class="title">Create a free Groq account</div>
          <div class="small muted">Sign in with Google or email. No card needed for the free plan.</div><a class="btn small" href="${esc(g.signup_url)}">Open console.groq.com</a></div></li>
        <li class="step"><span class="num">2</span><div class="grow"><div class="title">Create an API key</div>
          <div class="small muted">Create a new API key, give it any name (e.g. “Concall Player”) and copy it. Groq shows the key only once.</div><a class="btn small" href="${esc(g.keys_url)}">Open the API keys page</a></div></li>
        <li class="step"><span class="num">3</span><div class="grow"><div class="title">Paste the key here</div>
          <div class="token-row"><input id="groq-key" type="password" placeholder="gsk_…" autocomplete="off" spellcheck="false">
          <button class="btn primary small" id="groq-connect">Connect</button></div>
          <div id="groq-msg" class="small">${this.groqError ? `<span class="error">${esc(this.groqError)}</span>` : ""}</div></div></li>
      </ol>`;
    const connect = async () => {
      $("#groq-msg").innerHTML = `<span class="spinner"></span> Checking the key with Groq…`;
      try {
        const r = await api.post("/api/groq/connect", { key: $("#groq-key").value.trim() });
        this.groqError = r.ok ? "" : r.error;
        if (r.ok) toast("Groq connected. Calls waiting for transcription start now.", 4000);
      } catch (e) { this.groqError = e.message; }
      $("#groq-key").blur();
      this.refresh();
    };
    $("#groq-connect").onclick = connect;
    $("#groq-key").addEventListener("keydown", (e) => { if (e.key === "Enter") connect(); });
  },

  /* ---------- use from other computers (remote.py) ---------- */

  async renderRemote() {
    const el = $("#remote-body");
    if (!el || state.page !== "settings") return;
    if (el.contains(document.activeElement) && document.activeElement.tagName === "INPUT") return;
    let r;
    try { r = await api.get("/api/remote"); } catch (e) { el.innerHTML = `<p class="error small">${esc(e.message)}</p>`; return; }
    clearTimeout(this.remoteTimer);
    if (r.state === "starting" || (r.enabled && r.state !== "on")) this.remoteTimer = setTimeout(() => this.renderRemote(), 2000);
    if (!r.available) { el.innerHTML = `<p class="small muted">Not available on this computer.</p>`; return; }
    const form = (editing) => `
      <ol class="steps">
        <li class="step"><span class="num">1</span><div class="grow"><div class="title">Your email address</div>
          <div class="small muted">Only this address can open the link. Cloudflare emails it a short code when you sign in, again about every 4 hours (Cloudflare's rule), and after this computer restarts the link.</div>
          <div class="token-row"><input id="remote-email" type="email" placeholder="you@example.com" value="${esc(r.email || "")}" autocomplete="off"></div></div></li>
        <li class="step"><span class="num">2</span><div class="grow"><div class="title">${editing && r.has_password ? "New password (leave empty to keep the current one)" : "Choose a password"}</div>
          <div class="small muted">At least 8 characters. You'll type it once per browser (it's remembered for 30 days).</div>
          <div class="token-row"><input id="remote-pw" type="password" autocomplete="new-password" placeholder="Password">
          <button class="btn primary small" id="remote-save">Save</button></div>
          <div id="remote-msg" class="small">${this.remoteError ? `<span class="error">${esc(this.remoteError)}</span>` : ""}</div></div></li>
      </ol>`;
    if (!r.email || !r.has_password || this.remoteEditing) {
      el.innerHTML = form(true) + (this.remoteEditing ? `<button class="btn small ghost" id="remote-cancel">Cancel</button>` : "");
      $("#remote-cancel")?.addEventListener("click", () => { this.remoteEditing = false; this.remoteError = ""; this.renderRemote(); });
      $("#remote-save").onclick = async () => {
        $("#remote-msg").innerHTML = `<span class="spinner"></span> Saving…`;
        try {
          const res = await api.post("/api/remote/setup", { email: $("#remote-email").value.trim(), password: $("#remote-pw").value });
          this.remoteError = res.ok ? "" : res.error;
          if (res.ok) { this.remoteEditing = false; toast("Saved.", 2500); }
        } catch (e) { this.remoteError = e.message; }
        document.activeElement?.blur();
        this.renderRemote();
      };
      return;
    }
    const change = `<button class="btn small ghost" id="remote-edit">Change email or password</button>`;
    let body;
    if (r.state === "on" && r.url) {
      body = `<div class="status-row"><span class="dot ok">✓</span><div class="grow"><div class="title">On. Your link:</div>
          <div class="token-row"><input id="remote-url" readonly value="${esc(r.url)}"><button class="btn small" id="remote-copy">Copy</button></div>
          <div class="small muted">Open it on the other computer and sign in with <b>${esc(r.email)}</b> and your password. A new link can take a minute or two before it opens.
          <b>The link changes</b> when Concall Player or this ${DEV()} restarts, so check here (or email it to yourself) after a restart.
          Keep this ${DEV()} plugged in with the lid open; it's kept awake while this is on.</div>
          <div class="row-actions"><button class="btn small" id="remote-mail">Email me the link</button>
          <button class="btn small ghost" id="remote-stop">Turn off</button> ${change}</div></div></div>`;
    } else if (r.enabled) {
      body = `<div class="status-row"><span class="spinner"></span><div class="grow"><div class="title">${esc(r.message || "Starting…")}</div>
          ${r.error ? `<div class="small error">${esc(r.error)}</div>` : ""}
          <div class="row-actions"><button class="btn small ghost" id="remote-stop">Turn off</button></div></div></div>`;
    } else {
      body = `<div class="status-row"><span class="dot"></span><div class="grow"><div class="title">Off</div>
          <div class="small muted">Email ${esc(r.email)} · password set.</div>
          <div class="row-actions"><button class="btn primary small" id="remote-start">Turn on</button> ${change}</div></div></div>`;
    }
    el.innerHTML = body;
    $("#remote-edit")?.addEventListener("click", () => { this.remoteEditing = true; this.renderRemote(); });
    $("#remote-start")?.addEventListener("click", async () => {
      try { const res = await api.post("/api/remote/start"); if (!res.ok) toast(res.error); } catch (e) { toast(e.message); }
      this.renderRemote();
    });
    $("#remote-stop")?.addEventListener("click", async () => {
      if (!confirm("Turn off the link? The other computer will lose access until you turn it on again (with a new link).")) return;
      await api.post("/api/remote/stop"); this.renderRemote();
    });
    $("#remote-copy")?.addEventListener("click", () => copyText(r.url).then(() => toast("Link copied.", 2000)));
    $("#remote-mail")?.addEventListener("click", () => api.post("/api/remote/email").catch((e) => toast(e.message)));
  },

  renderRemotePage(view) {
    view.innerHTML = `
      <div class="settings">
        <a href="#/" class="back">← Your calls</a>
        <h1>Settings</h1>
        <section class="card">
          <h2>Using Concall Player remotely</h2>
          <p class="small">You're connected to Concall Player running on your ${esc(state.status?.platform === "windows" ? "PC" : "Mac")} through your private link.
          Settings, connections and updates can only be changed on that computer.</p>
          <p class="small muted">Big recordings: uploads through the link are limited to about 100 MB per file.</p>
          <div class="row-actions"><button class="btn small" id="remote-logout">Sign out of this browser</button>
          <button class="btn small ghost" data-report="">Report a problem</button></div>
        </section>
        <p class="muted small center">Concall Player ${esc(state.status?.version || "")}</p>
      </div>`;
    $("#remote-logout").onclick = async () => { await api.post("/api/remote/logout"); location.href = "/login"; };
  },

  renderMacMode() {
    const el = $("#mac-mode");
    if (!el || !this.setup.mac) return;
    const m = this.setup.mac;
    const opt = (v, label, desc) => `<label class="radio"><input type="radio" name="mac-mode" value="${v}" ${m.mode === v ? "checked" : ""}>
      <span><b>${label}</b><br><span class="small muted">${desc}</span></span></label>`;
    el.innerHTML = `<div class="mode-box"><div class="title">How hard may it work?</div>
      ${opt("auto", `Automatic (${m.gentle ? "gentle" : "fast"} on this ${DEV()})`, `Gentle on computers with 8 GB of memory or less, fast otherwise. This ${DEV()} has about ${m.ram_gb} GB.`)}
      ${opt("gentle", "Gentle", `Background priority on a few cores: the ${DEV()} stays usable, processing takes longer.`)}
      ${opt("fast", "Fast", IS_WIN() ? "Uses all processor cores: quicker, but the PC may lag meanwhile." : "Uses the graphics chip and all cores: quicker, but the Mac may lag meanwhile.")}</div>`;
    $$("input[name=mac-mode]", el).forEach((r) => (r.onchange = async () => {
      await api.patch("/api/settings", { mac_mode: r.value }); this.refresh();
    }));
  },

  async refresh() {
    try { this.setup = await api.get("/api/setup"); } catch {}
    try { state.status = await api.get("/api/status"); } catch {}
    this.renderSetupBlocks();
  },

  ollamaHtml(ol) {
    if (ol.running && ol.model_available) {
      return `<div class="status-row"><span class="dot ok">✓</span><div class="grow"><div class="title">Ollama is running</div><div class="small muted">Model ${esc(ol.model)}. Open a call → Summary tab → Generate summary.</div></div></div>`;
    }
    return `<p class="small">Summaries are made by a free AI model that runs on your ${DEV()} through <a href="https://ollama.com">Ollama</a>.</p>
      <ol class="small plain">
        <li>Download and install Ollama from <a href="https://ollama.com/download">ollama.com/download</a> and open it.</li>
        <li>Open the <b>Terminal</b> app, paste <code>ollama pull ${esc(ol.model || "llama3.2:3b")}</code> and press Return (a ~2 GB download).</li>
        <li>Come back here. ${ol.running ? "Ollama is running, but the model isn't downloaded yet." : "Ollama isn't running yet."}</li>
      </ol>`;
  },

  renderUpdate() {
    const el = $("#update-body");
    if (!el) return;
    const u = this.update;
    const st = state.status || {};
    let html = `<p class="small">You have version <b>${esc(st.version || "")}</b>.</p>`;
    const inst = u?.install || {};
    if (inst.state === "running") {
      html += `<p class="small"><span class="spinner"></span> ${esc(inst.message || "Installing…")}</p>`;
      setTimeout(() => this.pollInstall(), 1000);
    } else if (inst.state === "done") {
      html += `<p class="small">Version ${esc(inst.version)} is installed.</p><button class="btn primary small" id="upd-restart">Restart now</button>`;
    } else if (u?.available) {
      html += `<div class="update-box"><div class="title">Version ${esc(u.latest)} is available</div>
        ${u.notes ? `<div class="notes">${renderMarkdown(u.notes)}</div>` : ""}
        ${st.app_mode ? `<button class="btn primary small" id="upd-install">Install update</button>` : `<p class="small muted">Running from source: update with <code>git pull</code>.</p>`}
        ${inst.state === "error" ? `<p class="error small">${esc(inst.error)}</p>` : ""}</div>`;
    } else if (u?.error) {
      html += `<p class="small muted">${esc(u.error)}</p>`;
    } else if (u) {
      html += `<p class="small muted">You're up to date.</p>`;
    }
    html += `<div class="row-actions"><button class="btn small" id="upd-check">Check now</button></div>`;
    el.innerHTML = html;
    $("#upd-check").onclick = async () => {
      $("#upd-check").disabled = true;
      try { this.update = await api.get("/api/update?force=true"); } catch (e) { toast(e.message); }
      this.renderUpdate();
    };
    $("#upd-install")?.addEventListener("click", async () => {
      try { const r = await api.post("/api/update/install"); this.update.install = r; if (r.state === "error") toast(r.error); } catch (e) { toast(e.message); }
      this.renderUpdate();
    });
    $("#upd-restart")?.addEventListener("click", async () => {
      try { await api.post("/api/update/restart"); $("#view").innerHTML = `<div class="empty"><h2>Restarting…</h2><p>The app will open again in a few seconds.</p></div>`; }
      catch (e) { toast(e.message); }
    });
  },

  async pollInstall() {
    if (state.page !== "settings") return;
    try { this.update = await api.get("/api/update"); } catch {}
    this.renderUpdate();
  },
};
