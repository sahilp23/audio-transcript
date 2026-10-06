/* Concall Player — single-page app, no build step. */
"use strict";

/* "Mac" or "PC" in messages, depending on where the app runs. */
const IS_WIN = () => state?.status?.platform === "windows";
const DEV = () => (IS_WIN() ? "PC" : "Mac");

const $ = (sel, el = document) => el.querySelector(sel);
const $$ = (sel, el = document) => [...el.querySelectorAll(sel)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const clamp = (x, a, b) => Math.max(a, Math.min(b, x));

function fmtTime(sec, forceHours = false) {
  sec = Math.max(0, Math.floor(sec || 0));
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
  return h || forceHours ? `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}` : `${m}:${String(s).padStart(2, "0")}`;
}
function fmtDate(d) {
  if (!d) return "";
  const dt = new Date(d + "T00:00:00");
  return isNaN(dt) ? d : dt.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}
function initials(name) {
  const parts = String(name || "?").replace(/[^\p{L}\s]/gu, "").trim().split(/\s+/);
  return ((parts[0]?.[0] || "?") + (parts.length > 1 ? parts[parts.length - 1][0] : "")).toUpperCase();
}
function hashColor(str) {
  let h = 0;
  for (const c of String(str)) h = (h * 31 + c.charCodeAt(0)) >>> 0;
  return `hsl(${h % 360} 55% 48%)`;
}
function debounce(fn, ms) {
  let t;
  return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
}
function toast(msg, ms = 2600) {
  const el = $("#toast");
  el.textContent = msg;
  el.classList.remove("hidden");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => el.classList.add("hidden"), ms);
}

const api = {
  async req(method, url, body) {
    const opts = { method, headers: { "X-Concall": "1" } };
    if (body instanceof FormData) opts.body = body;
    else if (body !== undefined) { opts.body = JSON.stringify(body); opts.headers["Content-Type"] = "application/json"; }
    const r = await fetch(url, opts);
    if (r.status === 401 && state.status?.web) { location.href = "/auth/login"; throw new Error("Please sign in again"); }
    if (!r.ok) {
      let msg = r.statusText;
      try { msg = (await r.json()).detail || msg; } catch {}
      throw new Error(msg);
    }
    return r.json();
  },
  get: (u) => api.req("GET", u),
  post: (u, b) => api.req("POST", u, b),
  patch: (u, b) => api.req("PATCH", u, b),
  del: (u) => api.req("DELETE", u),
};

const GROUP_COLOR = {
  management: "var(--c-management)", analyst: "var(--c-analyst)",
  moderator: "var(--c-moderator)", unknown: "var(--c-unknown)",
};
const CHAPTER_COLOR = { intro: "var(--c-moderator)", remarks: "var(--c-management)", qa: "var(--c-analyst)", question: "var(--c-analyst)", closing: "var(--c-moderator)" };
const RATES = [0.75, 1, 1.1, 1.25, 1.5, 1.75, 2];

const state = {
  page: null,
  status: null,
  calls: [],
  pollTimer: null,
};

/* ------------------------------------------------------------------ */
/* Router                                                              */
/* ------------------------------------------------------------------ */

async function route() {
  clearTimeout(state.pollTimer);
  const m = location.hash.match(/^#\/call\/([\w-]+)/);
  if (m) return Player.open(m[1]);
  Player.close();
  if (location.hash.startsWith("#/settings")) return Settings.render();
  return renderLibrary();
}
window.addEventListener("hashchange", route);

/* ------------------------------------------------------------------ */
/* Library                                                             */
/* ------------------------------------------------------------------ */

async function renderLibrary() {
  state.page = "library";
  const view = $("#view");
  let calls;
  try { calls = await api.get("/api/calls"); } catch (e) {
    view.innerHTML = `<div class="empty"><h2>Can't reach the app server</h2><p>${esc(e.message)}</p></div>`;
    return;
  }
  state.calls = calls;
  fillCompanyList();
  if (state.page !== "library") return;

  if (!calls.length) {
    view.innerHTML = `<div class="empty"><h2>No calls yet</h2><p>Add a concall recording to get a synced, searchable transcript.<br>You can attach the company's transcript now or whenever it's published.</p><button class="btn primary" onclick="Upload.open()">+ Add your first call</button></div>`;
    return;
  }
  const filter = (state.libFilter || "").toLowerCase();
  const byCompany = new Map();
  for (const c of calls) {
    if (filter && !`${c.company} ${c.period}`.toLowerCase().includes(filter)) continue;
    if (!byCompany.has(c.company)) byCompany.set(c.company, []);
    byCompany.get(c.company).push(c);
  }
  const companies = [...byCompany.keys()].sort((a, b) => a.localeCompare(b));
  view.innerHTML = `
    <div class="library">
      <div class="library-head">
        <h1>Your calls</h1>
        <input id="lib-filter" placeholder="Filter companies…" value="${esc(state.libFilter || "")}">
      </div>
      ${companies.map((co) => `
        <section class="company">
          <h2><span class="company-avatar" style="background:${hashColor(co)}">${esc(initials(co))}</span>${esc(co)}</h2>
          <div class="call-grid">${byCompany.get(co).map(callCard).join("")}</div>
        </section>`).join("") || `<p class="muted">No matches.</p>`}
    </div>`;
  const f = $("#lib-filter");
  f.addEventListener("input", debounce(() => { state.libFilter = f.value; renderLibrary().then(() => { const n = $("#lib-filter"); n.focus(); n.setSelectionRange(n.value.length, n.value.length); }); }, 200));
  $$(".call-card", view).forEach((el) => {
    el.addEventListener("click", (e) => {
      if (e.target.closest(".card-menu")) return;
      location.hash = `#/call/${el.dataset.id}`;
    });
  });
  $$(".card-menu", view).forEach((btn) => btn.addEventListener("click", (e) => { e.stopPropagation(); cardMenu(btn, btn.closest(".call-card").dataset.id); }));

  if (calls.some((c) => c.status === "queued" || c.status === "processing")) {
    state.pollTimer = setTimeout(() => state.page === "library" && renderLibrary(), 3000);
  }
}

function statusBadges(c) {
  const b = [];
  if (c.status === "ready") {
    b.push(c.has_official ? `<span class="badge ok">Official transcript</span>` : `<span class="badge warn">Auto transcript</span>`);
  } else if (c.status === "error") b.push(`<span class="badge err">Failed</span>`);
  else if (c.status === "needs_input") b.push(`<span class="badge warn">Needs your OK</span>`);
  else b.push(`<span class="badge accent">${esc(c.stage || "Processing")}</span>`);
  if (c.duration) b.push(`<span class="badge">${fmtTime(c.duration)}</span>`);
  return b.join("");
}

function callCard(c) {
  const busy = c.status === "queued" || c.status === "processing";
  return `
    <div class="call-card" data-id="${esc(c.id)}">
      <button class="icon-btn card-menu" title="More"><svg viewBox="0 0 24 24"><circle cx="5" cy="12" r="1.3"/><circle cx="12" cy="12" r="1.3"/><circle cx="19" cy="12" r="1.3"/></svg></button>
      <div class="period">${esc(c.period || "Call")}</div>
      <div class="date">${esc(fmtDate(c.date))}</div>
      <div class="badges">${statusBadges(c)}</div>
      ${busy ? `<div class="progress"><div style="width:${Math.round((c.progress || 0) * 100)}%"></div></div>` : ""}
    </div>`;
}

function decisionHtml(meta) {
  if (state.status?.web) {
    return `<div class="decision">
      <div class="title">Waiting for cloud transcription</div>
      <p class="small">${esc(meta.decision?.reason || "Cloud transcription isn't available right now.")}</p>
      <div class="row-actions center-row"><button class="btn primary" data-choice="retry">Try again</button>
      <a class="btn ghost" href="#/settings">Open Settings</a></div>
    </div>`;
  }
  const gentleDefault = Settings.setup?.mac?.gentle ?? true;
  return `<div class="decision">
      <div class="title">Transcribe on this ${DEV()} instead?</div>
      <p class="small">${esc(meta.decision?.reason || "Cloud transcription isn't available right now.")}</p>
      <div class="row-actions center-row">
        <button class="btn primary" data-choice="local_gentle">Use this ${DEV()} (gentle)</button>
        <button class="btn" data-choice="local">Use this ${DEV()} (fast)</button>
        <button class="btn ghost" data-choice="retry">Try the cloud again</button>
      </div>
      <p class="muted small"><b>Gentle</b> runs in the background at low priority, so the ${DEV()} stays usable, but a 1-hour call can take an hour or more.
      <b>Fast</b> uses ${IS_WIN() ? "all processor cores" : "the Mac's graphics chip"}: quicker, but the ${DEV()} may lag while it runs${gentleDefault ? ` (likely on an 8 GB ${DEV()})` : ""}.
      <br>Or <a href="#/settings">connect / check Gladia or Groq in Settings</a>; waiting calls start automatically once it's connected.</p>
    </div>`;
}

function wireDecision(root, callId, after) {
  $$("[data-choice]", root).forEach((b) => (b.onclick = async () => {
    try { await api.post(`/api/calls/${callId}/decision`, { choice: b.dataset.choice }); after && after(); }
    catch (e) { toast(e.message); }
  }));
}

function cardMenu(anchor, id) {
  closeMenus();
  const call = state.calls.find((c) => c.id === id);
  const r = anchor.getBoundingClientRect();
  const menu = document.createElement("div");
  menu.className = "menu";
  menu.style.top = `${r.bottom + 4 + window.scrollY}px`;
  menu.style.left = `${Math.min(r.left, window.innerWidth - 180)}px`;
  menu.innerHTML = `
    <button data-a="open">Open</button>
    <button data-a="transcript">${call?.has_official ? "Replace" : "Attach"} company transcript</button>
    <button data-a="edit">Edit details</button>
    <button data-a="delete" class="btn danger" style="border:0">Delete</button>`;
  document.body.appendChild(menu);
  menu.addEventListener("click", async (e) => {
    const a = e.target.dataset.a;
    closeMenus();
    if (a === "open") location.hash = `#/call/${id}`;
    if (a === "transcript") TranscriptDialog.open(id, renderLibrary);
    if (a === "edit") EditDialog.open(call, renderLibrary);
    if (a === "delete" && confirm(`Delete ${call.company} ${call.period}? This removes the audio and transcript.`)) {
      try { await api.del(`/api/calls/${id}`); renderLibrary(); } catch (err) { toast(err.message); }
    }
  });
  setTimeout(() => document.addEventListener("click", closeMenus, { once: true }), 0);
}
function closeMenus() { $$(".menu").forEach((m) => m.remove()); }

function fillCompanyList() {
  const names = [...new Set(state.calls.map((c) => c.company))].sort();
  $("#company-list").innerHTML = names.map((n) => `<option value="${esc(n)}">`).join("");
}

/* ------------------------------------------------------------------ */
/* Dialogs                                                             */
/* ------------------------------------------------------------------ */

function wireDialog(dlg) {
  $$("[data-close]", dlg).forEach((b) => b.addEventListener("click", () => dlg.close()));
  $$(".drop", dlg).forEach((drop) => {
    const input = $("input[type=file]", drop);
    const text = $(".drop-text", drop);
    const orig = text.innerHTML;
    input.addEventListener("change", () => {
      drop.classList.toggle("has-file", !!input.files.length);
      text.innerHTML = input.files.length ? `<strong>${esc(input.files[0].name)}</strong> <span class="muted small">(${(input.files[0].size / 1e6).toFixed(1)} MB)</span>` : orig;
    });
    drop.addEventListener("dragover", (e) => { e.preventDefault(); drop.classList.add("over"); });
    drop.addEventListener("dragleave", () => drop.classList.remove("over"));
    drop.addEventListener("drop", (e) => {
      e.preventDefault(); drop.classList.remove("over");
      if (e.dataTransfer.files.length) { input.files = e.dataTransfer.files; input.dispatchEvent(new Event("change")); }
    });
    drop._reset = () => { input.value = ""; drop.classList.remove("has-file"); text.innerHTML = orig; };
  });
}

const Upload = {
  open() {
    const dlg = $("#upload-dialog");
    const form = $("#upload-form");
    form.reset();
    $$(".drop", form).forEach((d) => d._reset && d._reset());
    $("#upload-error").classList.add("hidden");
    $("#upload-progress").classList.add("hidden");
    dlg.showModal();
  },
  submit(e) {
    e.preventDefault();
    if (state.status?.web) return this.submitWeb();
    const form = $("#upload-form");
    const fd = new FormData(form);
    if (!fd.get("transcript")?.name) fd.delete("transcript");
    const err = $("#upload-error");
    err.classList.add("hidden");
    const prog = $("#upload-progress");
    prog.classList.remove("hidden");
    const bar = $(".bar > div", prog);
    const btn = $("button[type=submit]", form);
    btn.disabled = true;
    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/calls");
    xhr.setRequestHeader("X-Concall", "1");
    xhr.upload.onprogress = (ev) => { if (ev.lengthComputable) bar.style.width = `${(ev.loaded / ev.total) * 100}%`; };
    xhr.onload = () => {
      btn.disabled = false;
      if (xhr.status >= 200 && xhr.status < 300) {
        const meta = JSON.parse(xhr.responseText);
        $("#upload-dialog").close();
        location.hash = `#/call/${meta.id}`;
      } else {
        let msg = xhr.statusText;
        try { msg = JSON.parse(xhr.responseText).detail || msg; } catch {}
        err.textContent = typeof msg === "string" ? msg : "Upload failed";
        err.classList.remove("hidden");
        prog.classList.add("hidden");
      }
    };
    xhr.onerror = () => { btn.disabled = false; err.textContent = "Upload failed — is the app still running?"; err.classList.remove("hidden"); };
    xhr.send(fd);
  },
};

Upload.submitWeb = async function () {
  // Website: the recording goes straight from this browser into your Google Drive.
  const form = $("#upload-form");
  const fd = new FormData(form);
  const audio = fd.get("audio");
  const err = $("#upload-error"), prog = $("#upload-progress"), bar = $(".bar > div", prog);
  const btn = $("button[type=submit]", form);
  err.classList.add("hidden"); prog.classList.remove("hidden"); bar.style.width = "0%"; btn.disabled = true;
  let callId = null;
  try {
    if (!audio?.name) throw new Error("Choose the call recording first.");
    const start = await api.post("/api/calls/new", { company: fd.get("company"), period: fd.get("period"), date: fd.get("date"), filename: audio.name });
    callId = start.meta.id;
    const fileId = await driveUpload(audio, start.name, start.folder, start.token, start.props, (p) => (bar.style.width = `${p * 100}%`));
    await api.post(`/api/calls/${callId}/uploaded`, { file_id: fileId });
    const tfile = fd.get("transcript"), ttext = (fd.get("transcript_text") || "").trim();
    if (tfile?.name || ttext) {
      const tfd = new FormData();
      if (tfile?.name) tfd.append("transcript", tfile); else tfd.append("transcript_text", ttext);
      try { await api.post(`/api/calls/${callId}/transcript`, tfd); } catch (e) { toast(`Transcript not attached: ${e.message}`, 6000); }
    }
    $("#upload-dialog").close();
    location.hash = `#/call/${callId}`;
  } catch (e) {
    err.textContent = e.message || "Upload failed";
    err.classList.remove("hidden"); prog.classList.add("hidden");
    if (callId) api.del(`/api/calls/${callId}`).catch(() => {});
  } finally { btn.disabled = false; }
};

/* Upload a file from this browser into a Google Drive folder (resumable upload; the token is
   a short-lived one the website hands out, limited to Concall Player's own files). */
async function driveUpload(file, name, folder, token, props, onProgress) {
  const auth = { Authorization: `Bearer ${token}` };
  const type = file.type || "application/octet-stream";
  const init = await fetch("https://www.googleapis.com/upload/drive/v3/files?uploadType=resumable&fields=id", {
    method: "POST",
    headers: { ...auth, "Content-Type": "application/json; charset=UTF-8", "X-Upload-Content-Type": type, "X-Upload-Content-Length": String(file.size) },
    body: JSON.stringify({ name, parents: [folder], appProperties: props || {} }),
  });
  if (!init.ok) throw new Error(`Google Drive refused the upload (${init.status}). Try signing out and in again.`);
  const session = init.headers.get("Location");
  if (!session) throw new Error("Google Drive didn't start the upload. Please use Report a problem.");
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("PUT", session);
    xhr.upload.onprogress = (ev) => { if (ev.lengthComputable && onProgress) onProgress(ev.loaded / ev.total); };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) { try { resolve(JSON.parse(xhr.responseText).id); } catch { reject(new Error("Unexpected answer from Google Drive")); } }
      else reject(new Error(`Upload to Google Drive failed (${xhr.status})`));
    };
    xhr.onerror = () => reject(new Error("Upload to Google Drive failed. Check your internet connection."));
    xhr.send(file);
  });
}

const TranscriptDialog = {
  open(callId, after) {
    this.callId = callId; this.after = after;
    const form = $("#transcript-form");
    form.reset();
    $$(".drop", form).forEach((d) => d._reset && d._reset());
    $("#transcript-error").classList.add("hidden");
    $("#transcript-dialog").showModal();
  },
  async submit(e) {
    e.preventDefault();
    const form = $("#transcript-form");
    const fd = new FormData(form);
    if (!fd.get("transcript")?.name) fd.delete("transcript");
    const btn = $("button[type=submit]", form);
    btn.disabled = true;
    try {
      const res = await api.post(`/api/calls/${this.callId}/transcript`, fd);
      $("#transcript-dialog").close();
      toast(`Transcript attached: ${res.turns} sections, ${res.speakers.length} speakers. Syncing…`);
      this.after && this.after();
    } catch (err) {
      $("#transcript-error").textContent = err.message;
      $("#transcript-error").classList.remove("hidden");
    } finally { btn.disabled = false; }
  },
};

const EditDialog = {
  open(call, after) {
    this.call = call; this.after = after;
    const f = $("#edit-form");
    f.company.value = call.company || "";
    f.period.value = call.period || "";
    f.date.value = call.date || "";
    $("#edit-dialog").showModal();
  },
  async submit(e) {
    e.preventDefault();
    const f = $("#edit-form");
    try {
      await api.patch(`/api/calls/${this.call.id}`, { company: f.company.value, period: f.period.value, date: f.date.value });
      $("#edit-dialog").close();
      this.after && this.after();
    } catch (err) { toast(err.message); }
  },
};

/* ------------------------------------------------------------------ */
/* Player page                                                         */
/* ------------------------------------------------------------------ */

const Player = {
  id: null, meta: null, doc: null, user: {},
  words: [], starts: null, paras: [], wordEls: [], paraEls: [],
  cur: -1, curPara: -1, follow: true, raf: null, filter: "all",
  matches: [], matchIdx: -1, tab: "chapters",

  get audio() { return $("#audio"); },

  async open(id) {
    state.page = "call";
    if (this.id !== id) {
      this.close();
      this.id = id;
      this.tab = "chapters";
      this.filter = "all";
    }
    let meta;
    try { meta = await api.get(`/api/calls/${id}`); } catch (e) {
      $("#view").innerHTML = `<div class="empty"><h2>Call not found</h2><p><a href="#/">Back to library</a></p></div>`;
      return;
    }
    this.meta = meta;
    let doc = null;
    try { doc = await api.get(`/api/calls/${id}/doc`); } catch {}
    if (state.page !== "call" || this.id !== id) return;

    if (!doc) {
      this.renderProcessing(meta);
      if (meta.status !== "error") state.pollTimer = setTimeout(() => this.open(id), meta.status === "needs_input" ? 4000 : 2000);
      return;
    }
    this.user = await api.get(`/api/calls/${id}/user`).catch(() => ({}));
    this.doc = doc;
    this.index();
    this.renderPage();
    this.setupAudio();
    if (meta.status === "processing" || meta.status === "queued") this.pollRebuild();
  },

  close() {
    if (!this.id) return;
    const a = this.audio;
    if (a && !a.paused) a.pause();
    this.savePosition();
    cancelAnimationFrame(this.raf);
    $("#player").classList.add("hidden");
    a.removeAttribute("src");
    a.load();
    this.id = null; this.doc = null; this.cur = -1; this.curPara = -1;
  },

  pollRebuild() {
    state.pollTimer = setTimeout(async () => {
      if (state.page !== "call") return;
      const m = await api.get(`/api/calls/${this.id}`).catch(() => null);
      if (!m) return;
      const sp = $("#speaker-progress");
      if (sp && m.status === "processing") sp.textContent = m.stage || "Separating speakers";
      if (m.status === "ready" || m.status === "error") {
        const t = this.audio.currentTime, playing = !this.audio.paused;
        this.meta = m;
        this.doc = await api.get(`/api/calls/${this.id}/doc`);
        this.index();
        this.renderPage();
        this.cur = -1; this.curPara = -1;
        this.audio.currentTime = t;
        this.sync();
        if (playing) this.audio.play();
        if (m.status === "error") toast(`Failed: ${m.error}`, 5000);
        else toast(m.has_official ? `Synced to company transcript (${Math.round((m.alignment || 0) * 100)}% words matched)` : "Transcript updated");
      } else this.pollRebuild();
    }, 1500);
  },

  renderProcessing(meta) {
    const pct = Math.round((meta.progress || 0) * 100);
    $("#player").classList.add("hidden");
    let body;
    if (meta.status === "error") {
      body = `<p class="error">Processing failed: ${esc(meta.error)}</p>
        <div class="row-actions center-row"><button class="btn primary" id="retry-btn">Retry</button>
        <button class="btn" data-report="${esc(meta.error)}">Report this problem</button></div>`;
    } else if (meta.status === "needs_input") {
      body = decisionHtml(meta);
    } else {
      body = `<div class="progress"><div style="width:${pct}%"></div></div>
        <p><strong>${esc(meta.stage || "Processing")}</strong> — ${pct}%</p>
        <p class="muted small">You can leave this page; processing continues in the background, and you'll get a notification when it's done.</p>`;
    }
    $("#view").innerHTML = `
      <div class="processing">
        <h2>${esc(meta.company)} · ${esc(meta.period || "")}</h2>
        ${body}
        <p><a href="#/">← Back to library</a></p>
      </div>`;
    $("#retry-btn")?.addEventListener("click", async () => { await api.post(`/api/calls/${meta.id}/retry`); this.open(meta.id); });
    wireDecision($("#view"), meta.id, () => this.open(meta.id));
  },

  /* ---------- data ---------- */

  index() {
    const doc = this.doc;
    this.words = []; this.paras = []; this.turnOfPara = [];
    doc.turns.forEach((t, ti) => {
      t.paras.forEach((p, pi) => {
        const pIdx = this.paras.length;
        const first = this.words.length;
        for (const w of p.w) this.words.push({ t: w[0], s: w[1], e: w[2], p: pIdx });
        this.paras.push({ ti, pi, s: p.s, e: p.e, first, last: this.words.length - 1, qa: t.qa });
      });
    });
    this.starts = Float64Array.from(this.words, (w) => w.s);
    this.norm = this.words.map((w) => w.t.toLowerCase().replace(/[^\p{L}\p{N}%.]+/gu, "").replace(/\.$/, ""));
    this.duration = doc.duration || (this.words.length ? this.words[this.words.length - 1].e : 0);
    this.chapters = [...(doc.chapters || [])].sort((a, b) => a.t - b.t);
    this.qaTime = this.chapters.find((c) => c.kind === "qa")?.t ?? null;
    if (!this.user.bookmarks) this.user.bookmarks = [];
    if (!this.user.speakers) this.user.speakers = {};
  },

  speakerOf(turn) {
    const base = this.doc.speakers[turn.sp] || { name: "Speaker", group: "unknown" };
    const ov = this.user.speakers[turn.sp] || {};
    let name, role, group = base.group || "unknown";
    if (turn.label && !ov.name) {
      name = turn.label;
      role = `Analyst${turn.firm ? ", " + turn.firm : ""}`;
      group = "analyst";
    } else {
      name = ov.name || base.name;
      role = ov.role ?? base.role ?? "";
      if (!role && group === "analyst") role = `Analyst${base.firm ? ", " + base.firm : ""}`;
      if (role && group === "management" && this.meta.company && !ov.role) role = `${role}, ${this.meta.company.split(/\s+/)[0]}`;
    }
    return { name, role, group, color: GROUP_COLOR[group] || GROUP_COLOR.unknown };
  },

  chapterAt(t) {
    let c = null;
    for (const ch of this.chapters) { if (ch.t <= t + 0.05) c = ch; else break; }
    return c;
  },

  chapterTitle(ch) {
    return ch.kind === "question" ? `Q: ${ch.title}` : ch.title;
  },

  /* ---------- render ---------- */

  renderPage() {
    const m = this.meta;
    $("#view").innerHTML = `
      <div class="call-page ${sidePanelHidden() ? "side-hidden" : ""}">
        <aside class="sidebar">
          <div class="side-head">
            <h1 class="company-name">${esc(m.company)}</h1>
            <div class="period-line">${esc(m.period || "")}${m.date ? " · " + esc(fmtDate(m.date)) : ""}</div>
            <div class="badges">${this.sourceBadges()}</div>
            <div class="side-actions">
              <button class="btn small" id="attach-btn">${m.has_official ? "Replace" : "Attach"} company transcript</button>
              <button class="btn small ghost" id="more-btn">More…</button>
            </div>
          </div>
          <nav class="side-tabs" id="side-tabs">
            ${[["chapters", "Chapters"], ["highlights", "Key numbers"], ["bookmarks", "Bookmarks"], ["speakers", "Speakers"], ["notes", "Notes"], ...(state.status?.web ? [] : [["summary", "Summary"]])]
              .map(([k, l]) => `<button data-tab="${k}" class="${this.tab === k ? "on" : ""}">${l}</button>`).join("")}
          </nav>
          <div class="side-panel" id="side-panel"></div>
        </aside>
        <section class="main-col">
          <div class="toolbar">
            <button class="icon-btn" id="side-toggle" title="Show/hide the side panel (chapters, key numbers, notes…)"><svg viewBox="0 0 24 24"><rect x="3" y="4" width="18" height="16" rx="2"/><path d="M9 4v16"/></svg></button>
            <button class="icon-btn" id="copy-btn" title="Copy transcript"><svg viewBox="0 0 24 24"><rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2"/></svg></button>
            <button class="icon-btn" id="download-btn" title="Download transcript (.md)"><svg viewBox="0 0 24 24"><path d="M12 4v11M7 10l5 5 5-5M5 20h14"/></svg></button>
            <span class="sep"></span>
            <div class="seg" id="filter-seg">
              <button data-f="all">All</button><button data-f="remarks">Remarks</button><button data-f="qa">Q&amp;A</button>
            </div>
            <select class="chapter-select" id="chapter-select" title="Jump to chapter">
              <option value="">Chapters…</option>
              ${this.chapters.map((c, i) => `<option value="${i}">${fmtTime(c.t)} · ${esc(this.chapterTitle(c))}</option>`).join("")}
            </select>
            <span class="spacer"></span>
            <div class="find">
              <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="7"/><path d="M20 20l-4-4"/></svg>
              <input id="find-input" placeholder="Find" autocomplete="off">
              <span class="count" id="find-count"></span>
              <button class="icon-btn" id="find-prev" title="Previous (Shift+Enter)"><svg viewBox="0 0 24 24"><path d="M6 15l6-6 6 6"/></svg></button>
              <button class="icon-btn" id="find-next" title="Next (Enter)"><svg viewBox="0 0 24 24"><path d="M6 9l6 6 6-6"/></svg></button>
            </div>
            <button class="icon-btn" id="help-btn" title="Keyboard shortcuts (?)"><svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M9.5 9.5a2.5 2.5 0 1 1 3.5 2.3c-.6.3-1 .8-1 1.5v.7M12 17h.01"/></svg></button>
          </div>
          <div class="transcript-wrap" id="tw">
            <div class="transcript" id="transcript"></div>
            <button class="follow-btn hidden" id="follow-btn">↓ Back to what's playing</button>
          </div>
        </section>
      </div>`;

    this.renderTranscript();
    this.renderSidePanel();
    this.applyFilter(this.filter);

    $("#attach-btn").onclick = () => TranscriptDialog.open(this.id, () => { this.meta.status = "processing"; this.pollRebuild(); });
    $("#more-btn").onclick = (e) => this.moreMenu(e.currentTarget);
    $$("#side-tabs button").forEach((b) => (b.onclick = () => { this.tab = b.dataset.tab; $$("#side-tabs button").forEach((x) => x.classList.toggle("on", x === b)); this.renderSidePanel(); }));
    $$("#filter-seg button").forEach((b) => (b.onclick = () => this.applyFilter(b.dataset.f)));
    $("#chapter-select").onchange = (e) => {
      const c = this.chapters[+e.target.value];
      if (c) this.seek(c.t, true);
      e.target.value = "";
    };
    $("#copy-btn").onclick = () => copyText(this.exportText(false)).then(() => toast("Transcript copied"), () => toast("Copy failed"));
    $("#download-btn").onclick = () => this.download();
    $("#help-btn").onclick = () => $("#help-dialog").showModal();
    $("#side-toggle").onclick = () => {
      const page = $(".call-page");
      const hidden = !page.classList.contains("side-hidden");
      page.classList.toggle("side-hidden", hidden);
      try { localStorage.setItem("sidePanelHidden", hidden ? "1" : "0"); } catch {}
    };
    $("#follow-btn").onclick = () => { this.follow = true; $("#follow-btn").classList.add("hidden"); this.scrollToCurrent(true); };

    const fi = $("#find-input");
    fi.addEventListener("input", debounce(() => this.find(fi.value), 150));
    fi.addEventListener("keydown", (e) => {
      if (e.key === "Enter") { e.preventDefault(); this.stepMatch(e.shiftKey ? -1 : 1); }
      if (e.key === "Escape") { fi.value = ""; this.find(""); fi.blur(); }
    });
    $("#find-prev").onclick = () => this.stepMatch(-1);
    $("#find-next").onclick = () => this.stepMatch(1);

    const tw = $("#tw");
    const userScroll = () => {
      if (this.follow && !this.audio.paused) { this.follow = false; $("#follow-btn").classList.remove("hidden"); }
    };
    tw.addEventListener("wheel", userScroll, { passive: true });
    tw.addEventListener("touchmove", userScroll, { passive: true });

    $("#transcript").addEventListener("click", (e) => {
      const ts = e.target.closest(".ts");
      if (ts) { this.seek(+ts.dataset.t, false); this.play(); return; }
      const w = e.target.closest(".w");
      if (!w) return;
      if (!window.getSelection().isCollapsed) return; // user is selecting text
      this.seek(this.words[+w.dataset.i].s, false);
      this.follow = true;
      $("#follow-btn").classList.add("hidden");
      this.play();
    });
  },

  sourceBadges() {
    const m = this.meta, d = this.doc;
    const b = [];
    if (m.has_official) {
      b.push(`<span class="badge ok">Official transcript</span>`);
      if (m.alignment != null) b.push(`<span class="badge" title="Share of transcript words matched to the audio; the rest are timed by interpolation">${Math.round(m.alignment * 100)}% synced</span>`);
    } else {
      b.push(`<span class="badge warn">Auto transcript</span>`);
      b.push(`<span class="badge">${d.speakers_separated ? "Speakers detected" : "Speakers not separated"}</span>`);
    }
    const via = { gladia: "Gladia (cloud)", groq: "Groq (cloud)", mac: `this ${DEV()}` }[m.asr_service];
    if (via) b.push(`<span class="badge" title="Which service transcribed this call">Transcribed by ${via}</span>`);
    if (m.duration) b.push(`<span class="badge">${fmtTime(m.duration)}</span>`);
    return b.join("");
  },

  moreMenu(anchor) {
    closeMenus();
    const r = anchor.getBoundingClientRect();
    const menu = document.createElement("div");
    menu.className = "menu";
    menu.style.top = `${r.bottom + 4}px`;
    menu.style.left = `${r.left}px`;
    menu.innerHTML = `
      <button data-a="edit">Edit details</button>
      ${this.meta.has_official ? `<button data-a="auto">Switch back to auto transcript</button>` : ""}
      <button data-a="retranscribe">Re-run speech-to-text</button>
      <button data-a="library">Back to library</button>`;
    document.body.appendChild(menu);
    menu.addEventListener("click", async (e) => {
      const a = e.target.dataset.a;
      closeMenus();
      try {
        if (a === "edit") EditDialog.open(this.meta, async () => { this.meta = await api.get(`/api/calls/${this.id}`); this.renderPage(); this.syncPlayerTitle(); });
        if (a === "auto") { await api.del(`/api/calls/${this.id}/transcript`); this.meta.status = "processing"; toast("Switching to auto transcript…"); this.pollRebuild(); }
        if (a === "retranscribe" && confirm("Re-run speech-to-text on this recording? This takes several minutes.")) {
          await api.post(`/api/calls/${this.id}/retranscribe`);
          const id = this.id; this.close(); this.open(id);
        }
        if (a === "library") location.hash = "#/";
      } catch (err) { toast(err.message); }
    });
    setTimeout(() => document.addEventListener("click", closeMenus, { once: true }), 0);
  },

  renderTranscript() {
    const doc = this.doc, out = [];
    const banners = [];
    if (this.meta.speakers_pending) {
      banners.push(`<div class="banner" id="speaker-banner"><span><span class="spinner"></span> <b id="speaker-progress">${esc(this.meta.stage || "Separating speakers")}</b>. The transcript is ready to read; speaker names will appear when this finishes.</span><button class="btn small" id="skip-speakers">Skip</button></div>`);
    }
    if (!this.meta.has_official) {
      banners.push(`<div class="banner"><span>Auto transcript from the recording. When the company publishes its transcript, attach it for exact wording and speaker names — the audio sync is kept.</span><button class="btn small" onclick="$('#attach-btn').click()">Attach</button></div>`);
    }
    for (const w of this.meta.warnings || []) banners.push(`<div class="banner warn"><span>${esc(w)}</span><button class="btn small" data-report="${esc(w)}">Report</button></div>`);
    out.push(banners.join(""));

    let ci = 0;
    const bmTimes = this.user.bookmarks.map((b) => b.t);
    this.paras.forEach((p, pIdx) => {
      const turn = doc.turns[p.ti];
      while (ci < this.chapters.length && this.chapters[ci].t <= p.s + 0.05) {
        const ch = this.chapters[ci];
        const isQa = this.qaTime != null && ch.t >= this.qaTime - 0.05;
        out.push(`<div class="chapter-divider ${isQa ? "qa" : ""}" data-ch="${ci}">${esc(this.chapterTitle(ch))}</div>`);
        ci++;
      }
      const sp = this.speakerOf(turn);
      const showHead = doc.speakers_separated && p.pi === 0;
      const head = showHead
        ? `<div class="para-head"><span class="avatar" style="background:${sp.color}">${esc(initials(sp.name))}</span>
             <div class="who"><div class="name">${esc(sp.name)}</div>${sp.role ? `<div class="role">${esc(sp.role)}</div>` : ""}</div>
             <button class="ts" data-t="${p.s}">${fmtTime(p.s)}</button></div>`
        : `<div class="para-head compact"><button class="ts" data-t="${p.s}">${fmtTime(p.s)}</button></div>`;
      const words = [];
      for (let k = p.first; k <= p.last; k++) {
        const w = this.words[k];
        const bm = bmTimes.some((t) => t >= w.s - 0.01 && t < w.e + 0.01);
        words.push(`<span class="w${bm ? " bm" : ""}" data-i="${k}">${esc(w.t)}</span>`);
      }
      out.push(`<div class="para ${showHead ? "" : "cont"} ${p.qa ? "qa" : ""}" data-p="${pIdx}">${head}<div class="para-text">${words.join(" ")}</div></div>`);
    });
    if (!this.paras.length) out.push(`<div class="empty">No speech found in this recording.</div>`);
    $("#transcript").innerHTML = out.join("");
    $("#skip-speakers")?.addEventListener("click", async (e) => {
      if (!confirm("Skip speaker separation for this call? You can run it later from the Speakers tab.")) return;
      e.target.disabled = true;
      try { await api.post(`/api/calls/${this.id}/skip_speakers`); toast("Stopping speaker separation…"); }
      catch (err) { toast(err.message); }
    });
    this.wordEls = $$("#transcript .w");
    this.paraEls = $$("#transcript .para");
    this.cur = -1; this.curPara = -1;
    if (this.matches.length) this.find($("#find-input")?.value || "");
  },

  applyFilter(f) {
    this.filter = f;
    $$("#filter-seg button").forEach((b) => b.classList.toggle("on", b.dataset.f === f));
    const tr = $("#transcript");
    tr.classList.toggle("filter-qa", f === "qa");
    tr.classList.toggle("filter-remarks", f === "remarks");
  },

  /* ---------- sidebar panels ---------- */

  renderSidePanel() {
    const el = $("#side-panel");
    if (!el) return;
    const fn = { chapters: this.panelChapters, highlights: this.panelHighlights, bookmarks: this.panelBookmarks, speakers: this.panelSpeakers, notes: this.panelNotes, summary: this.panelSummary }[this.tab];
    fn.call(this, el);
  },

  panelChapters(el) {
    if (!this.chapters.length) { el.innerHTML = `<p class="muted small">No chapters detected.</p>`; return; }
    el.innerHTML = this.chapters.map((c, i) => `
      <div class="list-item" data-i="${i}">
        <span class="time">${fmtTime(c.t)}</span>
        <div class="body"><div class="title"><span class="chapter-kind" style="background:${CHAPTER_COLOR[c.kind] || "var(--text-3)"}"></span>${esc(this.chapterTitle(c))}</div></div>
      </div>`).join("");
    $$(".list-item", el).forEach((it) => (it.onclick = () => this.seek(this.chapters[+it.dataset.i].t, true)));
    this.markActiveChapter();
  },

  markActiveChapter() {
    if (this.tab !== "chapters") return;
    const ch = this.chapterAt(this.audio.currentTime);
    const idx = ch ? this.chapters.indexOf(ch) : -1;
    $$("#side-panel .list-item").forEach((it) => it.classList.toggle("on", +it.dataset.i === idx));
  },

  panelHighlights(el) {
    const hl = this.doc.highlights || [];
    const kind = this.hlKind || "all";
    const items = hl.filter((h) => kind === "all" || h.kind === kind);
        const numRe = /(^|[^A-Za-z0-9.#&])((?:₹|rs\.?|inr|\$|usd)\s?)?(\d[\d,]*(?:\.\d+)?\s?(?:%|percent|per cent|crores?|cr\b|lakhs?|bps|basis points|million|billion|mn\b|bn\b|x\b|times)?)/gi;
    el.innerHTML = `
      <div class="filter-row">
        ${[["all", "All"], ["guidance", "Guidance & outlook"], ["number", "Reported numbers"]].map(([k, l]) => `<button class="chip ${kind === k ? "on" : ""}" data-k="${k}">${l}</button>`).join("")}
      </div>
      ${items.length ? items.map((h, i) => {
        const sp = this.speakerOf(this.doc.turns[h.turn]);
        return `<div class="list-item" data-t="${h.t}">
          <span class="time">${fmtTime(h.t)}</span>
          <div class="body"><div class="hl-text">${esc(h.text).replace(numRe, (m, pre, cur, num) => `${pre}<b>${cur || ""}${num}</b>`)}</div>
          ${this.doc.speakers_separated ? `<div class="sub">${esc(sp.name)}</div>` : ""}</div>
        </div>`;
      }).join("") : `<p class="muted small">Nothing found.</p>`}`;
    $$(".chip", el).forEach((c) => (c.onclick = () => { this.hlKind = c.dataset.k; this.panelHighlights(el); }));
    $$(".list-item", el).forEach((it) => (it.onclick = () => this.seek(+it.dataset.t, true)));
  },

  panelBookmarks(el) {
    const bms = [...this.user.bookmarks].sort((a, b) => a.t - b.t);
    el.innerHTML = `
      <div class="filter-row"><button class="btn small" id="bm-add">+ Bookmark current moment</button><span class="muted small" style="align-self:center">or press B</span></div>
      ${bms.length ? bms.map((b) => `
        <div class="list-item" data-id="${b.id}">
          <span class="time">${fmtTime(b.t)}</span>
          <div class="body">
            <input class="bm-note-input" data-id="${b.id}" value="${esc(b.note || "")}" placeholder="Add a note…">
            <div class="sub" style="margin-top:4px">${esc(b.text || "")}</div>
          </div>
          <button class="icon-btn" data-del="${b.id}" title="Delete"><svg viewBox="0 0 24 24"><path d="M6 6l12 12M18 6L6 18"/></svg></button>
        </div>`).join("") : `<p class="muted small" style="padding:0 6px">No bookmarks yet. Bookmark moments you want to come back to — they show as yellow marks on the timeline.</p>`}`;
    $("#bm-add").onclick = () => this.addBookmark();
    $$(".list-item", el).forEach((it) => (it.onclick = (e) => {
      if (e.target.closest("input, [data-del]")) return;
      const b = this.user.bookmarks.find((x) => x.id === it.dataset.id);
      if (b) this.seek(b.t, true);
    }));
    $$(".bm-note-input", el).forEach((inp) => inp.addEventListener("input", debounce(() => {
      const b = this.user.bookmarks.find((x) => x.id === inp.dataset.id);
      if (b) { b.note = inp.value; this.saveUser({ bookmarks: this.user.bookmarks }); }
    }, 400)));
    $$("[data-del]", el).forEach((btn) => (btn.onclick = () => {
      this.user.bookmarks = this.user.bookmarks.filter((x) => x.id !== btn.dataset.del);
      this.saveUser({ bookmarks: this.user.bookmarks });
      this.renderSidePanel(); this.renderMarks(); this.refreshBookmarkWords();
    }));
  },

  addBookmark() {
    const t = this.audio.currentTime;
    const i = Math.max(0, this.wordAt(t));
    const text = this.words.slice(Math.max(0, i - 3), i + 12).map((w) => w.t).join(" ");
    const b = { id: Math.random().toString(36).slice(2, 10), t: +t.toFixed(2), note: "", text: text ? `“${text}…”` : "" };
    this.user.bookmarks.push(b);
    this.saveUser({ bookmarks: this.user.bookmarks });
    this.renderMarks();
    this.refreshBookmarkWords();
    this.tab = "bookmarks";
    $$("#side-tabs button").forEach((x) => x.classList.toggle("on", x.dataset.tab === "bookmarks"));
    this.renderSidePanel();
    toast(`Bookmarked ${fmtTime(t)}`);
    $(`.bm-note-input[data-id="${b.id}"]`)?.focus({ preventScroll: true });
  },

  refreshBookmarkWords() {
    const ts = this.user.bookmarks.map((b) => b.t);
    this.wordEls.forEach((el, k) => {
      const w = this.words[k];
      el.classList.toggle("bm", ts.some((t) => t >= w.s - 0.01 && t < w.e + 0.01));
    });
  },

  panelSpeakers(el) {
    const talk = {};
    let total = 0;
    for (const t of this.doc.turns) { const d = t.e - t.s; total += d; const k = t.label ? `label:${t.label}` : t.sp; talk[k] = (talk[k] || 0) + d; }
    const rows = [];
    const seen = new Set();
    for (const t of this.doc.turns) {
      const k = t.label ? `label:${t.label}` : t.sp;
      if (seen.has(k)) continue;
      seen.add(k);
      rows.push({ k, turn: t, sp: this.speakerOf(t) });
    }
    rows.sort((a, b) => (talk[b.k] || 0) - (talk[a.k] || 0));
    const note = this.doc.speakers_separated
      ? (this.meta.has_official ? "" : `<p class="muted small" style="padding:0 6px">Speakers were detected automatically. Click ✎ to name them (e.g. CEO, CFO) — names apply across the whole call.</p>`)
      : (state.status?.diarization === "ready"
        ? `<div class="hint">Speakers aren't separated for this call yet. <button class="btn small primary" id="detect-speakers">Detect speakers</button><br><span class="small">Takes a few minutes. Or attach the company transcript.</span></div>`
        : `<div class="hint">Speakers aren't separated for this call. Attach the company transcript, or <a href="#/settings">connect Hugging Face in Settings</a> to let the app tell speakers apart.</div>`);
    el.innerHTML = note + rows.map(({ k, turn, sp }) => `
      <div class="speaker-row" data-k="${esc(k)}">
        <span class="avatar" style="background:${sp.color}">${esc(initials(sp.name))}</span>
        <div class="body">
          <div class="title" style="font-weight:600;font-size:14px">${esc(sp.name)}</div>
          <div class="sub muted small">${esc(sp.role || sp.group)} · ${Math.round(((talk[k] || 0) / (total || 1)) * 100)}% talk time</div>
          <div class="bar"><div style="width:${((talk[k] || 0) / (total || 1)) * 100}%;background:${sp.color}"></div></div>
        </div>
        <button class="icon-btn" data-next="${esc(k)}" title="Jump to their next turn"><svg viewBox="0 0 24 24"><path d="M9 6l6 6-6 6"/></svg></button>
        ${!k.startsWith("label:") ? `<button class="icon-btn" data-edit="${esc(k)}" title="Rename"><svg viewBox="0 0 24 24"><path d="M4 20h4L19 9l-4-4L4 16z"/></svg></button>` : ""}
      </div>
      <div class="speaker-edit hidden" data-form="${esc(k)}">
        <input placeholder="Name" value="${esc(this.user.speakers[k]?.name ?? (this.doc.speakers[k]?.name || ""))}" data-field="name">
        <input placeholder="Role (e.g. CFO)" value="${esc(this.user.speakers[k]?.role ?? (this.doc.speakers[k]?.role || ""))}" data-field="role">
        <div style="display:flex;gap:6px"><button class="btn small primary" data-save="${esc(k)}">Save</button><button class="btn small ghost" data-cancel="${esc(k)}">Cancel</button></div>
      </div>`).join("");
    $("#detect-speakers", el)?.addEventListener("click", async () => {
      try { await api.post(`/api/calls/${this.id}/speakers`); toast("Detecting speakers…"); const id = this.id; this.close(); this.open(id); }
      catch (e) { toast(e.message); }
    });
    $$("[data-edit]", el).forEach((b) => (b.onclick = () => $(`[data-form="${CSS.escape(b.dataset.edit)}"]`, el).classList.toggle("hidden")));
    $$("[data-cancel]", el).forEach((b) => (b.onclick = () => $(`[data-form="${CSS.escape(b.dataset.cancel)}"]`, el).classList.add("hidden")));
    $$("[data-save]", el).forEach((b) => (b.onclick = () => {
      const k = b.dataset.save;
      const form = $(`[data-form="${CSS.escape(k)}"]`, el);
      this.user.speakers[k] = { name: $("[data-field=name]", form).value.trim() || undefined, role: $("[data-field=role]", form).value.trim() };
      this.saveUser({ speakers: this.user.speakers });
      const t = this.audio.currentTime;
      this.renderTranscript(); this.renderSpeakerStrip(); this.applyFilter(this.filter);
      this.audio.currentTime = t; this.sync();
      this.panelSpeakers(el);
    }));
    $$("[data-next]", el).forEach((b) => (b.onclick = () => {
      const k = b.dataset.next, now = this.audio.currentTime + 0.5;
      const turns = this.doc.turns.filter((t) => (t.label ? `label:${t.label}` : t.sp) === k);
      const next = turns.find((t) => t.s > now) || turns[0];
      if (next) this.seek(next.s, true);
    }));
  },

  panelNotes(el) {
    el.innerHTML = `
      <p class="muted small" style="margin:0 4px 8px">Your notes for this call (saved automatically). Tip: <kbd>B</kbd> bookmarks the current moment.</p>
      <textarea class="notes-area" id="notes-area" placeholder="Thesis checkpoints, questions for next call…">${esc(this.user.notes || "")}</textarea>`;
    const ta = $("#notes-area");
    ta.addEventListener("input", debounce(() => { this.user.notes = ta.value; this.saveUser({ notes: ta.value }); }, 500));
  },

  async panelSummary(el) {
    el.innerHTML = `<p class="muted small">Loading…</p>`;
    const [sum, st] = await Promise.all([api.get(`/api/calls/${this.id}/summary`), state.status ? Promise.resolve(state.status) : api.get("/api/status")]);
    state.status = st;
    if (this.tab !== "summary") return;
    const ol = st.ollama || {};
    const canRun = ol.running && ol.model_available;
    const btn = `<button class="btn small ${sum.status === "done" ? "" : "primary"}" id="sum-btn" ${canRun ? "" : "disabled"}>${sum.status === "done" ? "Regenerate" : "Generate summary"}</button>`;
    let body = "";
    if (sum.status === "running") {
      body = `<p class="muted small">Summarising with ${esc(sum.model)} on your ${DEV()}… ${Math.round((sum.progress || 0) * 100)}%<br>Takes a few minutes for a one-hour call.</p>`;
      setTimeout(() => this.tab === "summary" && this.id && this.panelSummary(el), 3000);
    } else if (sum.status === "done") {
      body = `<div class="summary">${renderMarkdown(sum.text)}</div><p class="muted small" style="padding:0 6px">Generated locally by ${esc(sum.model)}. AI summaries can be wrong — click through to the transcript to verify.</p>`;
    } else if (sum.status === "error") {
      body = `<p class="error">${esc(sum.error)}</p>`;
    }
    const setup = !ol.running
      ? `<div class="hint">AI summaries are optional and run locally with <a href="https://ollama.com" target="_blank" rel="noopener">Ollama</a> (free).<br>1. Install Ollama<br>2. In Terminal: <code>ollama pull ${esc(ol.model || "llama3.2:3b")}</code><br>3. Keep Ollama open, then reload this page.</div>`
      : !ol.model_available ? `<div class="hint">Ollama is running but the model isn't downloaded. In Terminal run: <code>ollama pull ${esc(ol.model)}</code></div>` : "";
    el.innerHTML = `${sum.status === "running" ? "" : `<div class="filter-row">${btn}</div>`}${setup}${body}`;
    $("#sum-btn")?.addEventListener("click", async () => {
      try { await api.post(`/api/calls/${this.id}/summary`); this.panelSummary(el); } catch (e) { toast(e.message); }
    });
  },

  saveUser(patch) {
    api.patch(`/api/calls/${this.id}/user`, patch).catch(() => toast("Couldn't save"));
  },

  savePosition() {
    if (!this.id || !this.audio || !isFinite(this.audio.currentTime)) return;
    const pos = +this.audio.currentTime.toFixed(1);
    if (Math.abs(pos - (this.user.position || 0)) < 1) return;
    this.user.position = pos;
    api.patch(`/api/calls/${this.id}/user`, { position: pos }).catch(() => {});
  },

  /* ---------- export ---------- */

  exportText(markdown) {
    const m = this.meta;
    const lines = [markdown ? `# ${m.company} — ${m.period}` : `${m.company} — ${m.period}`, m.date ? fmtDate(m.date) : "", ""];
    let ci = 0;
    this.doc.turns.forEach((t) => {
      while (ci < this.chapters.length && this.chapters[ci].t <= t.s + 0.05) {
        lines.push(markdown ? `## ${this.chapterTitle(this.chapters[ci])}` : `--- ${this.chapterTitle(this.chapters[ci])} ---`, "");
        ci++;
      }
      const sp = this.speakerOf(t);
      const text = t.paras.map((p) => p.w.map((w) => w[0]).join(" ")).join(markdown ? "\n\n" : "\n");
      const who = this.doc.speakers_separated ? `${sp.name}${sp.role ? ` (${sp.role})` : ""}` : "";
      lines.push(markdown ? `**[${fmtTime(t.s)}] ${who}**` : `[${fmtTime(t.s)}] ${who}`, text, "");
    });
    return lines.join("\n");
  },

  download() {
    saveFile(`${this.meta.company} ${this.meta.period}.md`.replace(/[\/:]/g, "-"), this.exportText(true));
  },

  /* ---------- find ---------- */

  find(q) {
    for (const i of this.matches) for (let k = i; k < i + this.matchLen; k++) this.wordEls[k]?.classList.remove("match", "current");
    this.matches = []; this.matchIdx = -1;
    const toks = q.toLowerCase().split(/\s+/).map((t) => t.replace(/[^\p{L}\p{N}%.]+/gu, "")).filter(Boolean);
    this.matchLen = toks.length;
    if (toks.length) {
      if (this.filter !== "all") this.applyFilter("all");
      const n = this.norm;
      for (let i = 0; i + toks.length <= n.length; i++) {
        let ok = true;
        for (let k = 0; k < toks.length && ok; k++) {
          const w = n[i + k], tk = toks[k];
          if (toks.length === 1) ok = w.includes(tk);
          else if (k === 0) ok = w.endsWith(tk);
          else if (k === toks.length - 1) ok = w.startsWith(tk);
          else ok = w === tk;
        }
        if (ok) this.matches.push(i);
      }
      for (const i of this.matches) for (let k = i; k < i + toks.length; k++) this.wordEls[k]?.classList.add("match");
    }
    $("#find-count").textContent = toks.length ? (this.matches.length ? `0/${this.matches.length}` : "0") : "";
    this.renderMarks();
    if (this.matches.length) {
      // Start from the first match after the current position.
      const t = this.audio.currentTime;
      const idx = this.matches.findIndex((i) => this.words[i].s >= t);
      this.matchIdx = (idx === -1 ? 0 : idx) - 1;
      this.stepMatch(1);
    }
  },

  stepMatch(dir) {
    if (!this.matches.length) return;
    if (this.matchIdx >= 0) for (let k = this.matches[this.matchIdx]; k < this.matches[this.matchIdx] + this.matchLen; k++) this.wordEls[k]?.classList.remove("current");
    this.matchIdx = (this.matchIdx + dir + this.matches.length) % this.matches.length;
    const i = this.matches[this.matchIdx];
    for (let k = i; k < i + this.matchLen; k++) this.wordEls[k]?.classList.add("current");
    $("#find-count").textContent = `${this.matchIdx + 1}/${this.matches.length}`;
    this.follow = false;
    if (!this.audio.paused) $("#follow-btn").classList.remove("hidden");
    this.wordEls[i]?.scrollIntoView({ block: "center" });
  },

  /* ---------- audio + sync ---------- */

  setupAudio() {
    const a = this.audio;
    const clear = !!this.user.clear && this.meta.enhanced === "ready";
    const src = `/api/calls/${this.id}/audio${clear ? "?clear=1" : ""}`;
    $("#player").classList.remove("hidden");
    $("#pl-clear").classList.toggle("active", clear);
    this.syncPlayerTitle();
    this.renderTimeline();
    if (a.dataset.callId !== this.id) {
      a.dataset.callId = this.id;
      a.src = src;
      a.playbackRate = this.user.rate || 1;
      $("#pl-rate").textContent = `${a.playbackRate}×`;
      const resume = this.user.position;
      a.addEventListener("loadedmetadata", () => {
        if (resume > 5 && resume < (a.duration || this.duration) - 5) {
          a.currentTime = resume;
          toast(`Resumed at ${fmtTime(resume)}`);
        }
        this.sync();
      }, { once: true });
    }
    this.sync();
    if ("mediaSession" in navigator) {
      navigator.mediaSession.metadata = new MediaMetadata({ title: `${this.meta.period} earnings call`, artist: this.meta.company, album: "Concall Player" });
    }
  },

  async toggleClear() {
    const btn = $("#pl-clear");
    if (btn.classList.contains("busy")) return;
    const turnOn = !this.user.clear || this.meta.enhanced !== "ready";
    if (turnOn && this.meta.enhanced !== "ready") {
      btn.classList.add("busy");
      toast("Preparing clear-voice audio (takes up to a minute)…", 4000);
      try {
        await api.post(`/api/calls/${this.id}/enhance`);
        const id = this.id;
        for (;;) {
          await new Promise((r) => setTimeout(r, 1500));
          if (this.id !== id) return;
          this.meta = await api.get(`/api/calls/${id}`);
          if (this.meta.enhanced === "ready") break;
          if (this.meta.enhanced === "error") throw new Error(this.meta.enhanced_error || "Couldn't clean up the audio");
        }
      } catch (e) { btn.classList.remove("busy"); toast(e.message, 5000); return; }
      btn.classList.remove("busy");
    }
    this.user.clear = turnOn;
    this.saveUser({ clear: turnOn });
    this.swapSource(`/api/calls/${this.id}/audio${turnOn ? "?clear=1" : ""}`);
    btn.classList.toggle("active", turnOn);
    toast(turnOn ? "Clear voice on: less noise, steadier volume" : "Clear voice off: original audio");
  },

  swapSource(src) {
    const a = this.audio, t = a.currentTime, playing = !a.paused, rate = a.playbackRate;
    a.src = src;
    a.addEventListener("loadedmetadata", () => {
      a.currentTime = t; a.playbackRate = rate;
      if (playing) a.play().catch(() => {});
    }, { once: true });
  },

  syncPlayerTitle() {
    $("#pl-company").textContent = this.meta.company;
    $("#pl-period").textContent = this.meta.period || "";
  },

  play() { this.audio.play().catch(() => {}); },
  toggle() { this.audio.paused ? this.play() : this.audio.pause(); },
  seek(t, scroll) {
    const a = this.audio;
    a.currentTime = clamp(t, 0, (a.duration || this.duration) - 0.05);
    this.follow = true;
    $("#follow-btn")?.classList.add("hidden");
    this.sync();
    if (scroll) this.scrollToCurrent(true);
  },
  skip(d) { this.seek(this.audio.currentTime + d, false); },

  wordAt(t) {
    // Last word whose start <= t.
    const s = this.starts;
    let lo = 0, hi = s.length;
    while (lo < hi) { const mid = (lo + hi) >> 1; if (s[mid] <= t) lo = mid + 1; else hi = mid; }
    return lo - 1;
  },

  loop() {
    this.sync();
    if (!this.audio.paused) this.raf = requestAnimationFrame(() => this.loop());
  },

  sync() {
    if (!this.doc) return;
    const t = this.audio.currentTime || 0;
    let i = this.wordAt(t + 0.03);
    // Before the first word of a paragraph has started, keep nothing highlighted.
    if (i !== this.cur) this.setCurrent(i);
    this.updatePlayerUi(t);
  },

  setCurrent(i) {
    const W = this.wordEls;
    const newPara = i >= 0 ? this.words[i].p : -1;
    if (this.cur >= 0) W[this.cur]?.classList.remove("now");
    if (newPara !== this.curPara) {
      if (this.curPara >= 0) {
        const op = this.paras[this.curPara];
        this.paraEls[this.curPara]?.classList.remove("active");
        for (let k = op.first; k <= op.last; k++) W[k].classList.remove("spoken");
      }
      if (newPara >= 0) {
        const np = this.paras[newPara];
        this.paraEls[newPara]?.classList.add("active");
        for (let k = np.first; k <= i; k++) W[k].classList.add("spoken");
      }
      this.curPara = newPara;
      this.cur = i;
      if (this.follow) this.scrollToCurrent(false);
      this.markActiveChapter();
    } else if (i > this.cur) {
      for (let k = this.cur + 1; k <= i; k++) W[k].classList.add("spoken");
    } else {
      for (let k = i + 1; k <= this.cur; k++) W[k].classList.remove("spoken");
    }
    this.cur = i;
    if (i >= 0) W[i]?.classList.add("now");
  },

  scrollToCurrent(force) {
    const el = this.paraEls[this.curPara];
    const tw = $("#tw");
    if (!el || !tw) return;
    if (el.offsetParent === null) return; // hidden by the Q&A filter
    const top = el.offsetTop, h = el.offsetHeight, view = tw.clientHeight;
    const visible = top >= tw.scrollTop + 10 && top + Math.min(h, view * 0.6) <= tw.scrollTop + view;
    if (force || !visible) tw.scrollTo({ top: top - view * 0.18, behavior: force ? "auto" : "smooth" });
  },

  /* ---------- timeline ---------- */

  renderTimeline() {
    const D = this.duration || 1;
    const chs = this.chapters.length ? this.chapters : [{ t: 0, title: "", kind: "intro" }];
    this.segs = chs.map((c, i) => ({ s: i === 0 ? 0 : c.t, e: i + 1 < chs.length ? chs[i + 1].t : D, c }));
    $("#tl-chapters").innerHTML = this.segs.map((sg) =>
      `<div class="seg-c" style="left:${(sg.s / D) * 100}%;width:calc(${((sg.e - sg.s) / D) * 100}% - 2px)"><div></div></div>`).join("");
    this.segFills = $$("#tl-chapters .seg-c > div");
    this.renderSpeakerStrip();
    this.renderMarks();
  },

  renderSpeakerStrip() {
    const D = this.duration || 1;
    if (!this.doc.speakers_separated) { $("#tl-speakers").innerHTML = ""; return; }
    $("#tl-speakers").innerHTML = this.doc.turns.map((t) => {
      const sp = this.speakerOf(t);
      return `<div style="left:${(t.s / D) * 100}%;width:${Math.max(0.1, ((t.e - t.s) / D) * 100)}%;background:${sp.color}"></div>`;
    }).join("");
  },

  renderMarks() {
    const D = this.duration || 1;
    const bms = (this.user.bookmarks || []).map((b) => `<div style="left:${(b.t / D) * 100}%" title="${esc(b.note || "Bookmark")}"></div>`);
    const fm = this.matches.slice(0, 400).map((i) => `<div class="find" style="left:${(this.words[i].s / D) * 100}%"></div>`);
    $("#tl-marks").innerHTML = fm.join("") + bms.join("");
  },

  updatePlayerUi(t) {
    const D = this.audio.duration || this.duration || 1;
    $("#tl-head").style.left = `${(t / D) * 100}%`;
    this.segs?.forEach((sg, k) => { this.segFills[k].style.width = `${clamp((t - sg.s) / (sg.e - sg.s || 1), 0, 1) * 100}%`; });
    const now = Math.floor(t);
    if (now !== this._lastSec) {
      this._lastSec = now;
      $("#pl-time").textContent = fmtTime(t, D >= 3600);
      $("#pl-remaining").textContent = "-" + fmtTime(D - t, D >= 3600);
      const ch = this.chapterAt(t);
      $("#pl-chapter").textContent = ch ? this.chapterTitle(ch) : "";
      if (this._lastChapter !== ch) { this._lastChapter = ch; this.markActiveChapter(); }
    }
  },

  nextChapter(dir) {
    const t = this.audio.currentTime;
    if (dir > 0) { const c = this.chapters.find((c) => c.t > t + 0.5); if (c) this.seek(c.t, true); }
    else {
      const prev = this.chapters.filter((c) => c.t < t - 3);
      const c = prev[prev.length - 1] || this.chapters[0];
      if (c) this.seek(c.t, true);
    }
  },

  cycleRate(dir) {
    const a = this.audio;
    let i = RATES.indexOf(a.playbackRate);
    if (i === -1) i = 1;
    i = dir === 0 ? (i + 1) % RATES.length : clamp(i + dir, 0, RATES.length - 1);
    a.playbackRate = RATES[i];
    $("#pl-rate").textContent = `${RATES[i]}×`;
    this.user.rate = RATES[i];
    api.patch(`/api/calls/${this.id}/user`, { rate: RATES[i] }).catch(() => {});
  },
};

/* ------------------------------------------------------------------ */
/* Player bar wiring (once)                                            */
/* ------------------------------------------------------------------ */

function wirePlayerBar() {
  const a = $("#audio");
  const playIcon = $("#pl-play-icon");
  a.addEventListener("play", () => { playIcon.innerHTML = `<path d="M7 5h3.5v14H7zM13.5 5H17v14h-3.5z" fill="currentColor"/>`; Player.loop(); });
  a.addEventListener("pause", () => { playIcon.innerHTML = `<path d="M7 4l13 8-13 8z" fill="currentColor"/>`; Player.savePosition(); });
  a.addEventListener("seeked", () => Player.sync());
  a.addEventListener("timeupdate", () => { if (a.paused) Player.sync(); });
  a.addEventListener("error", () => a.src && toast("Couldn't play this audio file in the browser"));
  setInterval(() => !a.paused && Player.savePosition(), 5000);
  window.addEventListener("beforeunload", () => Player.savePosition());

  $("#pl-play").onclick = () => Player.toggle();
  $("#pl-back").onclick = () => Player.skip(-15);
  $("#pl-fwd").onclick = () => Player.skip(15);
  $("#pl-rate").onclick = () => Player.cycleRate(0);
  $("#pl-mute").onclick = () => { a.muted = !a.muted; $("#pl-mute").classList.toggle("active", a.muted); $("#pl-vol-waves").style.display = a.muted ? "none" : ""; };
  $("#pl-bookmark").onclick = () => Player.addBookmark();
  $("#pl-clear").onclick = () => Player.toggleClear();
  $("#pl-chapter").onclick = () => {
    Player.tab = "chapters";
    $$("#side-tabs button").forEach((x) => x.classList.toggle("on", x.dataset.tab === "chapters"));
    Player.renderSidePanel();
  };

  const tl = $("#timeline"), tip = $("#tl-tip");
  const tAt = (e) => {
    const r = tl.getBoundingClientRect();
    return clamp((e.clientX - r.left) / r.width, 0, 1) * (a.duration || Player.duration || 0);
  };
  let dragging = false;
  tl.addEventListener("pointerdown", (e) => { dragging = true; tl.setPointerCapture(e.pointerId); Player.seek(tAt(e), true); });
  tl.addEventListener("pointermove", (e) => {
    const t = tAt(e);
    const r = tl.getBoundingClientRect();
    const ch = Player.chapterAt(t);
    const wi = Player.wordAt(t);
    const turn = wi >= 0 ? Player.doc.turns[Player.paras[Player.words[wi].p].ti] : null;
    const who = turn && Player.doc.speakers_separated ? Player.speakerOf(turn).name : "";
    tip.textContent = [fmtTime(t), ch ? Player.chapterTitle(ch) : "", who].filter(Boolean).join(" · ");
    tip.style.left = `${clamp(e.clientX - r.left, 60, r.width - 60)}px`;
    tip.classList.remove("hidden");
    if (dragging) Player.seek(t, true);
  });
  tl.addEventListener("pointerup", () => (dragging = false));
  tl.addEventListener("pointerleave", () => tip.classList.add("hidden"));

  if ("mediaSession" in navigator) {
    const ms = navigator.mediaSession;
    ms.setActionHandler("play", () => Player.play());
    ms.setActionHandler("pause", () => a.pause());
    ms.setActionHandler("seekbackward", () => Player.skip(-15));
    ms.setActionHandler("seekforward", () => Player.skip(15));
    ms.setActionHandler("previoustrack", () => Player.nextChapter(-1));
    ms.setActionHandler("nexttrack", () => Player.nextChapter(1));
  }
}

document.addEventListener("keydown", (e) => {
  if (state.page !== "call" || !Player.doc) return;
  if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "f") { e.preventDefault(); $("#find-input")?.focus(); $("#find-input")?.select(); return; }
  if (e.target.closest("input, textarea, select, [contenteditable]") || e.metaKey || e.ctrlKey || e.altKey) return;
  if ($("dialog[open]")) return;
  const k = e.key;
  const handled = {
    " ": () => Player.toggle(), k: () => Player.toggle(),
    j: () => Player.skip(-15), l: () => Player.skip(15),
    ArrowLeft: () => Player.skip(-5), ArrowRight: () => Player.skip(5),
    "[": () => Player.cycleRate(-1), "]": () => Player.cycleRate(1),
    n: () => Player.nextChapter(1), p: () => Player.nextChapter(-1),
    b: () => Player.addBookmark(), "/": () => $("#find-input")?.focus(),
    c: () => $("#follow-btn").click(), m: () => $("#pl-mute").click(),
    "?": () => $("#help-dialog").showModal(),
  }[k.length === 1 ? k.toLowerCase() : k];
  if (handled) { e.preventDefault(); handled(); }
  if (["PageUp", "PageDown", "ArrowUp", "ArrowDown", "Home", "End"].includes(k) && !Player.audio.paused) {
    Player.follow = false; $("#follow-btn")?.classList.remove("hidden");
  }
});

/* ------------------------------------------------------------------ */
/* App-window helpers (the Mac app window can't do browser downloads)  */
/* ------------------------------------------------------------------ */

const inApp = () => !!state.status?.app_mode;

function sidePanelHidden() {
  let saved = null;
  try { saved = localStorage.getItem("sidePanelHidden"); } catch {}
  return saved === null ? window.innerWidth < 900 : saved === "1";
}

async function copyText(text) {
  try { await navigator.clipboard.writeText(text); }
  catch { await api.post("/api/clipboard", { text }); }
}

async function saveFile(filename, text) {
  if (state.status?.platform === "darwin") {
    const r = await api.post("/api/export", { filename, text });
    toast(`Saved to Downloads: ${r.path.split("/").pop()}`, 4000);
    return;
  }
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([text], { type: "text/markdown" }));
  a.download = filename;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 2000);
}

function openExternal(url) {
  if (inApp()) api.post("/api/open", { url }).catch((e) => toast(e.message));
  else window.open(url, "_blank", "noopener");
}

// External links open in your normal browser.
document.addEventListener("click", (e) => {
  const a = e.target.closest("a[href^='https://']");
  if (!a) return;
  e.preventDefault();
  openExternal(a.href);
});

/* ------------------------------------------------------------------ */
/* Report a problem                                                    */
/* ------------------------------------------------------------------ */

const Report = {
  open(errorText) {
    this.error = errorText || "";
    const f = $("#report-form");
    f.reset();
    $("#report-error-box").classList.toggle("hidden", !this.error);
    $("#report-error-text").textContent = this.error;
    $("#report-msg").textContent = "";
    $("#report-dialog").showModal();
    f.description.focus();
  },
  context() {
    const ctx = { page: location.hash || "#/", error: this.error };
    if (state.page === "call" && Player.meta) {
      const m = Player.meta;
      Object.assign(ctx, {
        call: `${m.company} ${m.period || ""}`.trim(), call_status: m.status, call_stage: m.stage,
        call_error: m.error, call_warnings: (m.warnings || []).join(" | "), transcript: m.has_official ? "official" : "auto",
        duration_s: Math.round(m.duration || 0),
      });
    }
    return ctx;
  },
  async submit(e) {
    e.preventDefault();
    const f = $("#report-form");
    const btn = $("button[type=submit]", f);
    btn.disabled = true;
    try {
      const r = await api.post("/api/report", { description: f.description.value, context: this.context() });
      openExternal(r.url);
      $("#report-dialog").close();
      toast("Opened GitHub in your browser: check it and click “Submit new issue”.", 6000);
    } catch (err) { $("#report-msg").textContent = err.message; }
    finally { btn.disabled = false; }
  },
};

document.addEventListener("click", (e) => {
  const b = e.target.closest("[data-report]");
  if (b) { e.preventDefault(); Report.open(b.dataset.report); }
});

/* ------------------------------------------------------------------ */
/* Tiny markdown (for AI summaries)                                    */
/* ------------------------------------------------------------------ */

function renderMarkdown(md) {
  const lines = esc(md || "").split("\n");
  const out = [];
  let inList = false;
  for (const raw of lines) {
    const line = raw.trimEnd();
    const inline = (s) => s.replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/(^|\W)\*(.+?)\*(?=\W|$)/g, "$1<i>$2</i>");
    const li = line.match(/^\s*[-*•]\s+(.*)$/);
    if (li) { if (!inList) { out.push("<ul>"); inList = true; } out.push(`<li>${inline(li[1])}</li>`); continue; }
    if (inList) { out.push("</ul>"); inList = false; }
    const h = line.match(/^#{1,4}\s+(.*)$/);
    if (h) out.push(`<h2>${inline(h[1])}</h2>`);
    else if (line.trim()) out.push(`<p>${inline(line)}</p>`);
  }
  if (inList) out.push("</ul>");
  return out.join("");
}

/* ------------------------------------------------------------------ */
/* Boot                                                                */
/* ------------------------------------------------------------------ */

async function boot() {
  wireDialog($("#upload-dialog"));
  wireDialog($("#transcript-dialog"));
  wireDialog($("#edit-dialog"));
  wireDialog($("#help-dialog"));
  $("#upload-form").addEventListener("submit", (e) => Upload.submit(e));
  $("#transcript-form").addEventListener("submit", (e) => TranscriptDialog.submit(e));
  $("#edit-form").addEventListener("submit", (e) => EditDialog.submit(e));
  wireDialog($("#report-dialog"));
  $("#report-form").addEventListener("submit", (e) => Report.submit(e));
  $("#report-btn").addEventListener("click", () => Report.open(""));
  $("#upload-btn").addEventListener("click", () => Upload.open());
  wirePlayerBar();
  try { state.status = await api.get("/api/status"); } catch {}
  route();
  Settings.watchSetup();
  Settings.checkUpdateQuietly();
}
document.addEventListener("DOMContentLoaded", boot);
