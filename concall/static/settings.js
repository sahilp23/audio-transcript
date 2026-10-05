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
    if (!state.status?.app_mode) return;
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

        <section class="card">
          <h2>Speech engine</h2>
          <p class="muted small">Turns the call audio into text, on your Mac. Downloaded once, then works offline.</p>
          <div id="setup-speech"></div>
        </section>

        <section class="card" id="hf-card">
          <h2>Speaker separation <span class="badge">via Hugging Face · free</span></h2>
          <p class="muted small">Lets the app tell speakers apart (management vs analysts) when the company transcript isn't out yet. It uses free models from Hugging Face, which need a one-time sign-up.</p>
          <div id="hf-body"></div>
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
          <p class="small">Calls, transcripts, bookmarks and notes are stored only on this Mac:<br><code>${esc(st.data_dir || "")}</code></p>
          <div class="row-actions">
            <button class="btn small" id="reveal-data">Show in Finder</button>
            ${st.app_mode ? `<button class="btn small ghost" id="reveal-logs">Open log files</button>` : ""}
          </div>
        </section>
        <p class="muted small center">Concall Player ${esc(st.version || "")}</p>
      </div>`;
    this.renderSetupBlocks();
    this.renderUpdate();
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
      extra = `<button class="btn small" data-retry="${key}">Try again</button>`;
    } else if (comp.installed || comp.state === "done") {
      icon = `<span class="dot ok">✓</span>`; text = "Ready";
    } else {
      icon = `<span class="dot"></span>`; text = "Not installed yet";
      extra = `<button class="btn small" data-retry="${key}">Install now</button>`;
    }
    return `<div class="status-row">${icon}<div class="grow"><div class="title">${title}</div><div class="small muted">${text}</div>${extra.startsWith("<div") ? extra : ""}</div>${extra.startsWith("<button") ? extra : ""}</div>`;
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

  async refresh() {
    try { this.setup = await api.get("/api/setup"); } catch {}
    try { state.status = await api.get("/api/status"); } catch {}
    this.renderSetupBlocks();
  },

  ollamaHtml(ol) {
    if (ol.running && ol.model_available) {
      return `<div class="status-row"><span class="dot ok">✓</span><div class="grow"><div class="title">Ollama is running</div><div class="small muted">Model ${esc(ol.model)}. Open a call → Summary tab → Generate summary.</div></div></div>`;
    }
    return `<p class="small">Summaries are made by a free AI model that runs on your Mac through <a href="https://ollama.com">Ollama</a>.</p>
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
