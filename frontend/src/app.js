import { createClient } from "@supabase/supabase-js";
const root = document.querySelector("#app");
const esc = (x) =>
  String(x ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const names = {
  personal: "Personal",
  "side-projects": "Side Projects",
  office: "Office",
};
const icon = (path) =>
  `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path d="${path}" /></svg>`;
const icons = {
  Settings: icon("M4 7h16M4 17h16M9 4v6M15 14v6"),
  Capture: icon("M12 5v14M5 12h14"),
  Ask: icon("M5 4h14v12H9l-4 4V4Z"),
  Library: icon("M4 4h7v16H4V4ZM13 4h7v16h-7V4Z"),
  Actions: icon("m5 12 4 4L19 6"),
};
let auth,
  config,
  session,
  screen = "Capture",
  theme = "",
  mode = "text",
  actionStatus = "active",
  factor,
  qr,
  secret,
  recorder,
  stream,
  recordingFile,
  recordTimer,
  requestVersion = 0,
  refreshTimer;
const date = (x) =>
  x
    ? new Date(x).toLocaleString(undefined, {
        dateStyle: "medium",
        timeStyle: "short",
      })
    : "Date not specified";
const badge = (id) =>
  `<span class="pill ${esc(id)}">${esc(names[id] || "Needs review")}</span>`;
const btn = (label, cls = "primary", attrs = "") =>
  `<button class="${cls}" ${attrs}>${label}</button>`;
function message(text, type = "error", target = root) {
  let node = target.querySelector('[role="alert"]');
  if (!node) {
    node = document.createElement("div");
    node.setAttribute("role", "alert");
    target.append(node);
  }
  node.className = type;
  node.textContent = text;
}
async function api(path, options = {}) {
  const { data, error } = await auth.auth.getSession();
  if (error || !data.session)
    throw new Error("Your session has expired. Please sign in again.");
  session = data.session;
  const headers = {
    Authorization: `Bearer ${session.access_token}`,
    ...options.headers,
  };
  if (options.body && !(options.body instanceof FormData))
    headers["Content-Type"] = "application/json";
  const response = await fetch("/api" + path, { ...options, headers });
  let body;
  try {
    body = await response.json();
  } catch {
    throw new Error("The server returned an unexpected response. Try again.");
  }
  if (!response.ok) {
    if (response.status === 401) {
      await auth.auth.signOut();
      await showAuth();
    }
    const detail = body.detail;
    throw new Error(
      typeof detail === "string"
        ? detail
        : response.status === 422
          ? "Please check the fields and include a valid event time."
          : detail?.message ||
            "Unable to finish this request. Please try again.",
    );
  }
  return body;
}
async function safe(button, work) {
  button.disabled = true;
  try {
    await work();
  } catch (e) {
    message(e.message);
  } finally {
    button.disabled = false;
  }
}
async function showAuth() {
  stopRecording();
  clearTimeout(refreshTimer);
  requestVersion++;
  const { data } = await auth.auth.getSession();
  session = data.session;
  qr = null;
  secret = null;
  factor = null;
  if (session) {
    const { data: level, error } =
      await auth.auth.mfa.getAuthenticatorAssuranceLevel();
    if (error) {
      loginForm(error.message);
      return;
    }
    if (level.currentLevel === "aal2") {
      try {
        await api("/session");
        shell();
        return;
      } catch (e) {
        loginForm(e.message);
        return;
      }
    }
    const { data: factors, error: factorError } =
      await auth.auth.mfa.listFactors();
    if (factorError) {
      loginForm(factorError.message);
      return;
    }
    factor = factors.totp.find((f) => f.status === "verified");
    if (!factor) {
      mfaForm(false);
      return;
    }
    mfaForm(true);
    return;
  }
  loginForm();
}
function authFrame(title, subtitle, content) {
  root.innerHTML = `<main class="auth"><div class="brand"><img src="/ui/icon.svg" alt="">Conversation Memory</div><h1>${title}</h1><p class="muted">${subtitle}</p><div class="card">${content}</div><p class="helper">Private by default. Your conversations stay in your memory database.</p></main>`;
}
function loginForm(error) {
  authFrame(
    "A little less to remember.",
    "Sign in to your private space.",
    `<form id="login"><label for="email">Email</label><input id="email" type="email" autocomplete="username" required><label for="password">Password</label><input id="password" type="password" autocomplete="current-password" required minlength="8"><div class="sectiongap">${btn("Sign in")}</div></form><hr class="divider">${btn("Forgot password?", "link", 'id="forgot"')}${session ? btn("Sign out", "link", 'id="signout"') : ""}`,
  );
  if (error) message(error);
  document.querySelector("#login").onsubmit = (e) => {
    e.preventDefault();
    safe(e.submitter, async () => {
      const { error } = await auth.auth.signInWithPassword({
        email: document.querySelector("#email").value.trim(),
        password: document.querySelector("#password").value,
      });
      if (error) throw error;
      await showAuth();
    });
  };
  document.querySelector("#forgot").onclick = (e) =>
    safe(e.target, async () => {
      const email = document.querySelector("#email").value.trim();
      if (!email) throw new Error("Enter your email address first.");
      const { error } = await auth.auth.resetPasswordForEmail(email, {
        redirectTo: location.origin + "/?recovery=1",
      });
      if (error) throw error;
      message("Check your email for a password reset link.", "success");
    });
  document.querySelector("#signout")?.addEventListener("click", logout);
}
function mfaForm(existing) {
  authFrame(
    existing ? "One more check." : "Protect your memory.",
    "Use an authenticator app to keep your conversations private.",
    existing
      ? `<form id="verify"><label for="code">Six-digit authenticator code</label><input id="code" inputmode="numeric" pattern="[0-9]{6}" maxlength="6" autocomplete="one-time-code" required><div class="sectiongap">${btn("Verify and continue")}</div></form>`
      : `<p>Set up an authenticator such as Google Authenticator, Microsoft Authenticator, or your password manager.</p>${btn("Set up authenticator", "primary", 'id="enroll"')}<div id="enrollment"></div>`,
  );
  root
    .querySelector(".card")
    .insertAdjacentHTML(
      "beforeend",
      `<hr class="divider"><p class="helper">Lost your authenticator? Contact the deployment owner for account recovery. Email reset does not bypass MFA.</p>${btn("Sign out", "link", 'id="signout"')}`,
    );
  document.querySelector("#signout").onclick = logout;
  if (existing) wireVerify();
  else
    document.querySelector("#enroll").onclick = (e) =>
      safe(e.target, async () => {
        const { data: old } = await auth.auth.mfa.listFactors();
        for (const f of old?.all || [])
          if (f.status === "unverified")
            await auth.auth.mfa.unenroll({ factorId: f.id });
        const { data, error } = await auth.auth.mfa.enroll({
          factorType: "totp",
          friendlyName: "Memory authenticator",
        });
        if (error) throw error;
        factor = { id: data.id };
        qr = data.totp.qr_code;
        secret = data.totp.secret;
        document.querySelector("#enrollment").innerHTML =
          `<img class="qr" alt="Authenticator setup QR code"><p class="helper">Or enter this setup key manually:</p><p class="secret">${esc(secret)}</p><form id="verify"><label for="code">Six-digit authenticator code</label><input id="code" inputmode="numeric" pattern="[0-9]{6}" maxlength="6" autocomplete="one-time-code" required><div class="sectiongap">${btn("Verify and continue")}</div></form>`;
        document.querySelector(".qr").src = qr.startsWith("data:")
          ? qr
          : "data:image/svg+xml;charset=utf-8," + encodeURIComponent(qr);
        e.target.hidden = true;
        wireVerify();
      });
}
function wireVerify() {
  document.querySelector("#verify").onsubmit = (e) => {
    e.preventDefault();
    safe(e.submitter, async () => {
      const { error } = await auth.auth.mfa.challengeAndVerify({
        factorId: factor.id,
        code: document.querySelector("#code").value,
      });
      if (error) throw error;
      qr = secret = null;
      await showAuth();
    });
  };
}
async function logout() {
  stopRecording();
  await auth.auth.signOut();
  await showAuth();
}
function shell() {
  root.innerHTML = `<div class="shell"><aside class="sidebar"><div class="brand"><img src="/ui/icon.svg" alt="">Conversation<br>Memory</div><nav class="nav">${["Capture","Ask","Library","Actions","Settings"]
    .map((n) =>
      btn(
        `${icons[n]} &nbsp;${n}<small>${{ Capture: "Save something worth keeping", Ask: "Find answers with evidence", Library: "Your conversations, organised", Actions: "Keep your commitments", Settings: "Choose how your memory works" }[n]}</small>`,
        "",
        `data-nav="${n}"`,
      ),
    )
    .join(
      "",
    )}</nav><div class="notice">A place for what matters.<br><span class="muted">Across work, life, and everything you’re building.</span></div><footer><span class="pill">MFA verified</span><p class="helper">${esc(session.user.email)}</p></footer></aside><main class="main">${config.environment && config.environment !== "production" ? `<div class="env-banner">${esc(config.environment.toUpperCase())} · Test environment</div>` : ""}<header class="topbar"><img class="mobile-mark" src="/ui/icon.svg" alt="Conversation Memory"><span class="eyebrow">Your space to remember</span><div class="row"><select id="theme" aria-label="Current theme"><option value="">All themes</option>${Object.entries(
    names,
  )
    .map(
      ([id, n]) =>
        `<option value="${id}" ${theme === id ? "selected" : ""}>${n}</option>`,
    )
    .join(
      "",
    )}</select>${btn("Sign out", "link logout", 'id="logout"')}</div></header><div id="content"></div></main></div>`;
  document.querySelector("#logout").onclick = logout;
  document.querySelector("#theme").onchange = (e) => {
    theme = e.target.value;
    render();
  };
  root.querySelectorAll("[data-nav]").forEach(
    (b) =>
      (b.onclick = () => {
        stopRecording();
        screen = b.dataset.nav;
        render();
      }),
  );
  render();
}
function render() {
  clearTimeout(refreshTimer);
  const version = ++requestVersion;
  root
    .querySelectorAll("[data-nav]")
    .forEach((b) => b.classList.toggle("active", b.dataset.nav === screen));
  const area = document.querySelector("#content");
  area.innerHTML = `<div class="intro"><span class="eyebrow">${esc(theme ? names[theme] : "All parts of your life")}</span><h1>${{ Capture: "Keep the thought.", Ask: "What’s on your mind?", Library: "Your memory, organised.", Actions: "Make room for progress.", Settings: "Your AI, your choices." }[screen]}</h1><p class="muted">${{ Capture: "A conversation today. A useful reminder tomorrow.", Ask: "Ask naturally. Every answer leads back to its source.", Library: "The things you said, heard, and saved — all in one place.", Actions: "Your commitments, with the context that matters.", Settings: "Choose a default for each task. Fine-tune individual uploads when needed." }[screen]}</p></div><div id="panel"></div>`;
  ({
    Capture: capture,
    Ask: ask,
    Library: () => library(version),
    Actions: () => actions(version),
    Settings: () => settingsScreen(version),
  })[screen]();
}
function localNow() {
  const d = new Date();
  return new Date(d.getTime() - d.getTimezoneOffset() * 60000)
    .toISOString()
    .slice(0, 16);
}
function eventISO(value) {
  if (!value) return null;
  const d = new Date(value);
  if (Number.isNaN(d.getTime()))
    throw new Error("Choose a valid event date and time.");
  const offset = -d.getTimezoneOffset(),
    sign = offset >= 0 ? "+" : "-",
    abs = Math.abs(offset);
  return `${value}:00${sign}${String(Math.floor(abs / 60)).padStart(2, "0")}:${String(abs % 60).padStart(2, "0")}`;
}
function capture() {
  const captureVersion = requestVersion;
  document.querySelector("#panel").innerHTML =
    `<div class="grid"><section class="card"><div class="tabs">${[
      ["text", "Text"],
      ["audio", "Audio"],
      ["document", "Document"],
    ]
      .map(([id, n]) =>
        btn(n, id === mode ? "active" : "", `data-mode="${id}"`),
      )
      .join(
        "",
      )}</div><form id="capture"><label for="title">Give it a title</label><input id="title" placeholder="e.g. Friday’s product review" maxlength="200" required><div class="fields"><div><label for="captureTheme">Theme</label><select id="captureTheme" required><option value="">Choose a theme</option>${Object.entries(
      names,
    )
      .map(
        ([id, n]) =>
          `<option value="${id}" ${id === theme ? "selected" : ""}>${n}</option>`,
      )
      .join(
        "",
      )}</select></div><div><label for="event">When did it happen?</label><input id="event" type="datetime-local" value="${localNow()}" required></div></div><p class="helper">Timezone: ${esc(Intl.DateTimeFormat().resolvedOptions().timeZone)}. Dates in your conversation use this event time.</p>${mode === "text" ? `<label for="transcript">Conversation or note</label><textarea id="transcript" placeholder="Paste your conversation here. Hinglish is welcome." required maxlength="200000"></textarea>` : `<label for="file">${mode === "audio" ? "Audio file" : "Document"}</label><input id="file" type="file" accept="${mode === "audio" ? ".mp3,.m4a,.wav,.ogg,.flac,.webm" : ".txt,.docx,.pdf"}"><p class="helper">${mode === "audio" ? "MP3, M4A, WAV, OGG, FLAC, WebM · Up to 25 MB" : "TXT, DOCX, text-based PDF · Up to 10 MB. Scanned PDFs are not supported."}</p>${mode === "audio" ? `${btn("Record audio", "secondary", 'id="record" type="button"')}<p id="recordState" class="helper" aria-live="polite"></p>` : ""}`}<details class="processing-options"><summary>Processing options</summary><div id="processingControls" aria-live="polite">Loading model choices…</div></details><div class="sectiongap">${btn("Save to memory ↗", "primary", 'id="saveCapture" disabled')}</div></form><div id="captureResult" aria-live="polite"></div></section><aside><div class="card soft"><span class="eyebrow">From conversation to clarity</span><h2 class="sectiongap">Save it once.<br>Come back with a question.</h2><p class="muted">Your memory keeps the original, translates when needed, and brings out useful details and commitments.</p><hr class="divider"><p><strong>Always with context.</strong><br><span class="muted">Check the source behind an answer. Review and correct anything that needs a second look.</span></p></div><p class="helper">Keep Personal, Side Projects, and Office separate using themes.</p></aside></div>`;
  let captureSettings;
  api('/ai-settings').then(data => {
    if(captureVersion !== requestVersion) return;
    captureSettings = data;
    const tasks = mode === 'audio' ? fileTasks : fileTasks.filter(t => t !== 'transcription');
    document.querySelector('#processingControls').innerHTML = languageControls()+modelControls(data,tasks,'capture');
    wireModelNotes(data,'capture');
    document.querySelector('#saveCapture').disabled = false;
  }).catch(error => { if(captureVersion === requestVersion) {
    document.querySelector('#processingControls').textContent = 'Could not load model choices. Refresh this screen to retry.';
    message(error.message);
  }});
  document.querySelectorAll("[data-mode]").forEach(
    (b) =>
      (b.onclick = () => {
        stopRecording();
        recordingFile = null;
        mode = b.dataset.mode;
        render();
      }),
  );
  document.querySelector("#record")?.addEventListener("click", recordAudio);
  document.querySelector("#capture").onsubmit = (e) => {
    e.preventDefault();
    safe(e.submitter, async () => {
      if (recorder?.state === "recording")
        throw new Error("Stop the recording before saving.");
      const title = document.querySelector("#title").value.trim(),
        theme_id = document.querySelector("#captureTheme").value,
        event_at = eventISO(document.querySelector("#event").value);
      if (!title || !theme_id)
        throw new Error("Add a title and choose a theme.");
      if(!captureSettings) throw new Error('Wait for model choices to load.');
      const processing = {models:readModels('capture'), languages:[...document.querySelectorAll('[name="language"]:checked')].map(x=>x.value)};
      let entry;
      if (mode === "text") {
        const text = document.querySelector("#transcript").value;
        if (!text.trim()) throw new Error("Add a conversation or note.");
        entry = await api("/entries/text", {
          method: "POST",
          body: JSON.stringify({ title, theme_id, event_at, text, processing }),
        });
      } else {
        const file = document.querySelector("#file").files[0] || recordingFile;
        if (!file) throw new Error("Choose a file or record audio first.");
        if (file.size > (mode === "audio" ? 25 : 10) * 1024 * 1024)
          throw new Error("This file exceeds the upload limit.");
        const data = new FormData();
        data.set("file", file);
        data.set("processing",JSON.stringify(processing));
        data.set("title", title);
        data.set("theme_id", theme_id);
        data.set("event_at", event_at);
        entry = await api("/entries/upload", { method: "POST", body: data });
      }
      document.querySelector("#captureResult").innerHTML =
        `<p class="success">${entry.duplicate ? "Already saved. Opening the existing entry with its original processing settings." : "Saved. Processing will run automatically."}</p>`;
      await openEntry(entry.id);
    });
  };
}
async function recordAudio(e) {
  const button = e.target;
  if (recorder?.state === "recording") {
    recorder.stop();
    button.disabled = true;
    return;
  }
  try {
    if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder)
      throw new Error(
        "Recording is unavailable in this browser. Upload an audio file instead.",
      );
    stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const type = [
      "audio/webm;codecs=opus",
      "audio/mp4",
      "audio/ogg;codecs=opus",
    ].find((t) => MediaRecorder.isTypeSupported(t));
    recorder = new MediaRecorder(stream, type ? { mimeType: type } : undefined);
    const parts = [];
    recorder.ondataavailable = (e) => {
      if (e.data.size) parts.push(e.data);
    };
    recorder.onstop = () => {
      clearInterval(recordTimer);
      stream?.getTracks().forEach((t) => t.stop());
      const mime = recorder.mimeType,
        extension = mime.includes("mp4")
          ? "m4a"
          : mime.includes("ogg")
            ? "ogg"
            : "webm";
      recordingFile = new File(parts, `recording.${extension}`, { type: mime });
      if (button.isConnected) {
        button.disabled = false;
        button.textContent = "Record again";
        document.querySelector("#recordState").textContent =
          `Recording ready · ${(recordingFile.size / 1024 / 1024).toFixed(1)} MB`;
      }
    };
    recorder.start(1000);
    button.textContent = "Stop recording";
    let seconds = 0;
    recordTimer = setInterval(() => {
      seconds++;
      const node = document.querySelector("#recordState");
      if (node)
        node.textContent = `Recording · ${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
      if (parts.reduce((sum, b) => sum + b.size, 0) > 24 * 1024 * 1024)
        recorder.stop();
    }, 1000);
  } catch (e) {
    stream?.getTracks().forEach((t) => t.stop());
    message(
      e.name === "NotAllowedError"
        ? "Microphone permission was denied. Allow access or upload an audio file."
        : e.message,
    );
  }
}
function stopRecording() {
  clearInterval(recordTimer);
  if (recorder?.state === "recording") recorder.stop();
  stream?.getTracks().forEach((t) => t.stop());
}
function ask() {
  document.querySelector("#panel").innerHTML =
    `<section class="card"><form id="ask"><label for="question">Ask your memory</label><textarea id="question" style="min-height:100px" placeholder="What commitments did I make this week?" maxlength="1000" required></textarea><div class="row spread sectiongap"><span class="helper">Searching ${esc(theme ? names[theme] : "all themes")}</span>${btn("Find an answer ↗")}</div></form></section><div id="answer" aria-live="polite"><div class="empty">Your next answer starts with a question.</div></div>`;
  document.querySelector("#ask").onsubmit = (e) => {
    e.preventDefault();
    const version = requestVersion;
    safe(e.submitter, async () => {
      const question = document.querySelector("#question").value.trim();
      if (!question) throw new Error("Enter a question.");
      const result = await api("/chat", {
        method: "POST",
        body: JSON.stringify({ question, theme_id: theme || null }),
      });
      if (version !== requestVersion) return;
      const answer = document.querySelector("#answer");
      answer.innerHTML =
        result.status === "no_evidence"
          ? '<div class="card empty">No supporting evidence was found in this theme. Try another question or save more context.</div>'
          : `<section class="card"><span class="eyebrow">From your memory</span>${(
              result.claims || []
            )
              .map(
                (c) =>
                  `<p>${esc(c.text)}</p><div>${c.source_ids
                    .map((id) => {
                      const i = result.sources.findIndex((s) => s.id === id);
                      return i < 0
                        ? ""
                        : btn(
                            `Source ${i + 1}`,
                            "secondary source-button",
                            `data-source="${i}"`,
                          );
                    })
                    .join("")}</div>`,
              )
              .join(
                "",
              )}${result.warning ? `<p class="notice">${esc(result.warning)}</p>` : ""}</section>`;
      answer
        .querySelectorAll("[data-source]")
        .forEach(
          (b) =>
            (b.onclick = () =>
              sourceDialog(result.sources[Number(b.dataset.source)])),
        );
    });
  };
}
function sourceDialog(source) {
  const dialog = document.createElement("dialog");
  dialog.innerHTML = `<div class="row spread"><h2>${esc(source.source_title || "Source")}</h2>${btn("Close", "secondary", "data-close")}</div>${badge(source.theme_id)}<p class="meta">${date(source.event_at)}</p><blockquote class="quote">${esc(source.evidence || source.text)}</blockquote>${btn("Open full entry", "primary", "data-open")}`;
  root.append(dialog);
  dialog.querySelector("[data-close]").onclick = () => dialog.close();
  dialog.onclose = () => dialog.remove();
  dialog.querySelector("[data-open]").onclick = () => {
    dialog.close();
    openEntry(source.source_entry_id);
  };
  dialog.showModal();
}
function scope() {
  return theme ? "&theme_id=" + encodeURIComponent(theme) : "";
}
async function library(version, offset = 0) {
  const panel = document.querySelector("#panel");
  panel.innerHTML = '<p class="muted" role="status">Loading your entries…</p>';
  try {
    const rows = await api(`/entries?limit=20&offset=${offset}${scope()}`);
    if (version !== requestVersion) return;
    panel.innerHTML = `<div class="row spread" style="margin-bottom:18px"><span class="helper">${esc(theme ? names[theme] : "All themes")} · Page ${offset / 20 + 1}</span>${btn("Refresh", "secondary", 'id="refresh"')}</div>${rows.length ? rows.map((r) => `<button class="entry" data-entry="${esc(r.id)}"><div class="row spread">${badge(r.theme_id)}<span class="pill ${esc(r.status)}">${esc(r.status)}</span></div><h3>${esc(r.title)}</h3><p class="meta">${esc(r.input_type || "text")} · ${date(r.event_at || r.uploaded_at)}</p><p class="muted">${esc((r.original_text || "").slice(0, 150))}${(r.original_text || "").length > 150 ? "…" : ""}</p></button>`).join("") : '<div class="card empty">Nothing saved here yet. Capture a conversation to start your memory.</div>'}<div class="row">${offset ? btn("Previous", "secondary", 'id="prev"') : ""}${rows.length === 20 ? btn("Next page", "secondary", 'id="next"') : ""}</div>`;
    panel
      .querySelectorAll("[data-entry]")
      .forEach((b) => (b.onclick = () => openEntry(b.dataset.entry)));
    document.querySelector("#refresh").onclick = () => library(version, offset);
    document
      .querySelector("#prev")
      ?.addEventListener("click", () => library(version, offset - 20));
    document
      .querySelector("#next")
      ?.addEventListener("click", () => library(version, offset + 20));
    if (rows.some((r) => ["queued", "processing"].includes(r.status)))
      refreshTimer = setTimeout(() => {
        if (version === requestVersion) library(version, offset);
      }, 5000);
  } catch (e) {
    if (version === requestVersion) message(e.message);
  }
}
async function openEntry(id) {
  clearTimeout(refreshTimer);
  screen = "Library";
  root
    .querySelectorAll("[data-nav]")
    .forEach((b) => b.classList.toggle("active", b.dataset.nav === "Library"));
  const version = ++requestVersion,
    area = document.querySelector("#content");
  area.innerHTML = '<p class="muted" role="status">Opening entry…</p>';
  try {
    const [entry, knowledge] = await Promise.all([
      api("/entries/" + id),
      api("/entries/" + id + "/knowledge"),
    ]);
    if (version !== requestVersion) return;
    area.innerHTML = `${btn("← Back to library", "link", 'id="back"')}<div class="intro"><h1>${esc(entry.title)}</h1><div class="row">${badge(entry.theme_id)}<span class="pill ${esc(entry.status)}">${esc(entry.status)}</span><span class="meta">${date(entry.event_at || entry.uploaded_at)}</span></div></div>${entry.status === "failed" ? `<div class="error">Processing failed: ${esc(entry.job?.error || "Unknown error")}. ${btn("Retry processing", "secondary", 'id="retry"')}</div>` : ""}${["queued", "processing"].includes(entry.status) ? `<p class="notice" role="status">${esc(entry.job?.stage || "queued")} · Processing automatically. This page will update when it is ready.</p>` : ""}${processingDetails(entry)}${knowledge.summary ? `<section class="card soft"><span class="eyebrow">The essentials</span><p>${esc(knowledge.summary)}</p></section>` : ""}${knowledge.items.length ? `<h2>What to remember</h2>${knowledge.items.map((item) => itemCard(item, true)).join("")}` : ""}<section class="card"><h2>Original ${entry.input_type === "audio" ? "transcript" : "text"}</h2><p class="text">${esc(entry.original_text || "Available after processing.")}</p>${entry.input_type !== "text" ? btn("Download original file", "secondary", 'id="download"') : ""}</section>${knowledge.english_text ? `<section class="card"><h2>English version</h2><p class="text">${esc(knowledge.english_text)}</p></section>` : ""}${entry.index_status === "failed" ? `<p class="notice">Semantic indexing failed. ${btn("Retry indexing", "secondary", 'id="indexRetry"')}</p>` : ""}`;
    document.querySelector("#back").onclick = () => {
      screen = "Library";
      render();
    };
    document.querySelector("#retry")?.addEventListener("click", (e) =>
      safe(e.target, async () => {
        await api(`/entries/${id}/retry`, { method: "POST" });
        openEntry(id);
      }),
    );
    document.querySelector("#indexRetry")?.addEventListener("click", (e) =>
      safe(e.target, async () => {
        await api(`/entries/${id}/index/retry`, { method: "POST" });
        openEntry(id);
      }),
    );
    document.querySelector("#download")?.addEventListener("click", (e) =>
      safe(e.target, async () => {
        const { data } = await auth.auth.getSession();
        const r = await fetch(`/api/entries/${id}/file`, {
          headers: { Authorization: `Bearer ${data.session.access_token}` },
        });
        if (!r.ok) throw new Error("Could not download this file.");
        const url = URL.createObjectURL(await r.blob()),
          a = document.createElement("a");
        a.href = url;
        a.download =
          r.headers
            .get("Content-Disposition")
            ?.match(/filename="([^"]+)"/)?.[1] || "original-file";
        a.click();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
      }),
    );
    wireItems(knowledge.items, () => openEntry(id));
    if (["queued", "processing"].includes(entry.status))
      refreshTimer = setTimeout(() => {
        if (version === requestVersion) openEntry(id);
      }, 5000);
  } catch (e) {
    if (version === requestVersion) message(e.message);
  }
}
function due(item) {
  if (!item.due_date) return "No confirmed due date";
  const formatted = new Date(item.due_date + "T12:00:00").toLocaleDateString(
    undefined,
    { dateStyle: "medium" },
  );
  return `Due ${formatted}`;
}
function itemCard(item, edit = false) {
  return `<article class="card"><div class="row spread"><div class="row">${badge(item.theme_id)}<span class="pill">${esc(item.kind)}</span>${item.certainty === "tentative" ? '<span class="pill tentative">Tentative</span>' : ""}</div><span class="meta">${esc(item.status)}</span></div><h3 class="sectiongap">${esc(item.text)}</h3><p class="meta">${esc(item.owner || "Owner unspecified")} · ${due(item)}</p><blockquote class="quote">${esc(item.evidence)}</blockquote><div class="row">${item.kind === "action" && item.status === "active" ? btn("Mark complete", "secondary", `data-status="completed" data-item="${esc(item.id)}"`) + btn("Dismiss", "link", `data-status="dismissed" data-item="${esc(item.id)}"`) : ""}${item.kind === "action" && item.status !== "active" ? btn("Reopen", "secondary", `data-status="active" data-item="${esc(item.id)}"`) : ""}${edit ? btn("Correct", "link", `data-edit="${esc(item.id)}"`) : btn("Open source", "link", `data-entry="${esc(item.source_entry_id)}"`)}</div></article>`;
}
function wireItems(items, reload) {
  root.querySelectorAll("[data-status]").forEach(
    (b) =>
      (b.onclick = () =>
        safe(b, async () => {
          const item = items.find((x) => x.id === b.dataset.item);
          await api("/knowledge/" + item.id, {
            method: "PATCH",
            body: JSON.stringify({
              expected_version: item.version,
              reason: "Updated from the web app",
              status: b.dataset.status,
            }),
          });
          await reload();
        })),
  );
  root.querySelectorAll("[data-edit]").forEach(
    (b) =>
      (b.onclick = () =>
        editDialog(
          items.find((x) => x.id === b.dataset.edit),
          reload,
        )),
  );
  root
    .querySelectorAll("[data-entry]")
    .forEach((b) => (b.onclick = () => openEntry(b.dataset.entry)));
}
async function actions(version) {
  document.querySelector("#panel").innerHTML =
    `<div class="tabs">${["active", "completed", "dismissed"].map((s) => btn(s[0].toUpperCase() + s.slice(1), actionStatus === s ? "active" : "", `data-filter="${s}"`)).join("")}</div><div id="actionRows" role="status">Loading commitments…</div>`;
  document.querySelectorAll("[data-filter]").forEach(
    (b) =>
      (b.onclick = () => {
        actionStatus = b.dataset.filter;
        render();
      }),
  );
  try {
    const items = await api(
      `/actions?limit=100&status=${actionStatus}${scope()}`,
    );
    if (version !== requestVersion) return;
    document.querySelector("#actionRows").innerHTML = items.length
      ? items.map((i) => itemCard(i)).join("")
      : '<div class="card empty">No ' +
        actionStatus +
        " commitments in this theme.</div>";
    if (items.length === 100)
      document
        .querySelector("#actionRows")
        .insertAdjacentHTML(
          "beforeend",
          '<p class="notice">Showing the first 100 actions.</p>',
        );
    wireItems(items, () => actions(version));
  } catch (e) {
    if (version === requestVersion) message(e.message);
  }
}
function editDialog(item, reload) {
  const d = document.createElement("dialog");
  d.innerHTML = `<div class="row spread"><h2>Correct this detail</h2>${btn("Close", "secondary", "data-close")}</div><form><label for="editText">Text</label><textarea id="editText" required>${esc(item.text)}</textarea><label for="editOwner">Owner</label><input id="editOwner" value="${esc(item.owner)}" maxlength="200"><label for="editTheme">Theme</label><select id="editTheme">${Object.entries(
    names,
  )
    .map(
      ([id, n]) =>
        `<option value="${id}" ${item.theme_id === id ? "selected" : ""}>${n}</option>`,
    )
    .join(
      "",
    )}</select><label for="editCertainty">Certainty</label><select id="editCertainty"><option value="explicit">Explicit</option><option value="tentative" ${item.certainty === "tentative" ? "selected" : ""}>Tentative</option></select><label for="editDate">Due date</label><input id="editDate" type="date" value="${esc(item.due_date)}"><label for="reason">Reason for correction</label><input id="reason" required maxlength="2000"><div class="sectiongap">${btn("Save correction")}</div></form>`;
  root.append(d);
  d.querySelector("[data-close]").onclick = () => d.close();
  d.onclose = () => d.remove();
  d.querySelector("form").onsubmit = (e) => {
    e.preventDefault();
    e.submitter.disabled = true;
    (async () => {
      try {
        await api("/knowledge/" + item.id, {
          method: "PATCH",
          body: JSON.stringify({
            expected_version: item.version,
            text: d.querySelector("#editText").value,
            owner: d.querySelector("#editOwner").value || null,
            theme_id: d.querySelector("#editTheme").value,
            certainty: d.querySelector("#editCertainty").value,
            due_date: d.querySelector("#editDate").value || null,
            reason: d.querySelector("#reason").value,
          }),
        });
        d.close();
        await reload();
      } catch (e) {
        message(e.message, "error", d);
      } finally {
        e.submitter.disabled = false;
      }
    })();
  };
  d.showModal();
}
function recoveryForm() {
  authFrame(
    "Choose a new password.",
    "Your authenticator is still required to access your memory.",
    `<form id="recovery"><label for="newPassword">New password</label><input id="newPassword" type="password" minlength="12" autocomplete="new-password" required><div class="sectiongap">${btn("Update password")}</div></form>`,
  );
  document.querySelector("#recovery").onsubmit = (e) => {
    e.preventDefault();
    safe(e.submitter, async () => {
      const { error } = await auth.auth.updateUser({
        password: document.querySelector("#newPassword").value,
      });
      if (error) throw error;
      history.replaceState({}, "", "/");
      await showAuth();
    });
  };
}
async function init() {
  try {
    const r = await fetch("/api/ui-config");
    if (!r.ok) throw new Error("Unable to load app configuration.");
    config = await r.json();
    if (!config.configured) {
      authFrame(
        "Your memory is almost ready.",
        "The web app is installed. Login needs a one-time setup.",
        `<p>The deployment owner needs to configure Supabase authentication and the allowed owner account.</p><p class="helper">Private API access remains protected. No conversations are shown here until login and MFA are configured.</p>`,
      );
      return;
    }
    auth = createClient(config.supabase_url, config.supabase_publishable_key);
    auth.auth.onAuthStateChange((event) => {
      if (event === "PASSWORD_RECOVERY") setTimeout(recoveryForm, 0);
      if (event === "SIGNED_OUT") setTimeout(showAuth, 0);
    });
    if (
      new URLSearchParams(location.search).has("recovery") &&
      (await auth.auth.getSession()).data.session
    ) {
      recoveryForm();
      return;
    }
    await showAuth();
  } catch (e) {
    authFrame(
      "Couldn’t open your memory.",
      "Please try again in a moment.",
      `<p class="error">${esc(e.message)}</p>${btn("Reload", "secondary", 'id="reload"')}`,
    );
    document.querySelector("#reload").onclick = () => location.reload();
  }
}

const taskNames={transcription:'Transcription',translation:'English translation',summary:'Summary',extraction:'Memories, decisions & actions',answer:'Answers to questions'};
const fileTasks=['transcription','translation','summary','extraction'];
function modelKey(choice){return choice.provider+'|'+choice.model}
function modelControls(data,tasks,prefix){
  return tasks.map(task=>{
    const selected=data.defaults[task], key=modelKey(selected);
    const options=data.catalog.filter(x=>x.tasks.includes(task));
    const missing=!options.some(x=>modelKey(x)===key);
    return `<div class="model-row"><label for="${prefix}-${task}">${esc(taskNames[task])}</label><select id="${prefix}-${task}" data-model-task="${task}" data-model-prefix="${prefix}">${missing?`<option value="${esc(key)}" selected disabled>${esc(selected.provider+' / '+selected.model)} — unavailable</option>`:''}${options.map(x=>`<option value="${esc(modelKey(x))}" ${key===modelKey(x)?'selected':''} ${x.available?'':'disabled'}>${esc(x.provider+' / '+x.model)}${x.available?'':' — key not configured'}</option>`).join('')}</select><p class="helper" data-model-note="${prefix}-${task}"></p></div>`;
  }).join('');
}
function wireModelNotes(data,prefix){
  document.querySelectorAll(`[data-model-prefix="${prefix}"]`).forEach(select=>{
    const update=()=>{const item=data.catalog.find(x=>modelKey(x)===select.value);document.querySelector(`[data-model-note="${select.id}"]`).textContent=item?item.note+(item.available?'':' Add '+item.key_variable+' to your shared Render group first.'):'This model is not in the supported catalog. Choose another model.'};
    select.onchange=update;update();
  });
}
function readModels(prefix){
  const models={};
  document.querySelectorAll(`[data-model-prefix="${prefix}"]`).forEach(select=>{
    if(select.selectedOptions[0]?.disabled)throw new Error('Choose an available model for '+taskNames[select.dataset.modelTask]+'.');
    const [provider,model]=select.value.split('|');models[select.dataset.modelTask]={provider,model};
  });return models;
}
function languageControls(){return `<fieldset class="languages"><legend>Expected languages</legend><p class="helper">Leave unchecked for automatic detection. For mixed speech, select all expected languages.</p>${Object.entries({en:'English',hi:'Hindi',mr:'Marathi'}).map(([id,name])=>`<label><input type="checkbox" name="language" value="${id}"> ${name}</label>`).join('')}</fieldset>`}
async function settingsScreen(version){
  const panel=document.querySelector('#panel');panel.innerHTML='<p role="status">Loading AI settings…</p>';
  try{
    const data=await api('/ai-settings');if(version!==requestVersion)return;
    const providers=[...new Set(data.catalog.map(x=>x.provider))];
    panel.innerHTML=`<div class="grid"><section class="card"><form id="aiSettings"><h2>Default models</h2><p class="helper">These defaults apply to new uploads. Existing entries keep the choices saved with them. Answer settings apply to your next question.</p>${modelControls(data,Object.keys(taskNames),'defaults')}<div class="sectiongap">${btn('Save defaults')}</div></form><div id="settingsStatus" role="status"></div></section><aside><section class="card soft"><h2>Connected providers</h2>${providers.map(name=>{const row=data.catalog.find(x=>x.provider===name);return `<p><strong>${esc(name)}</strong> · ${row.available?'Key configured':'Key needed'}<br><span class="helper">${esc(row.key_variable)}</span></p>`}).join('')}<p class="helper">Keys are managed in Render. “Key configured” means a key is present; model access and results still need a live test.</p></section><section class="card"><h3>Semantic search</h3><p>${esc(data.embedding.model||'Not configured')}</p><p class="helper">Managed through EMBEDDING_MODEL. Switching embedding models requires reindexing, so this setting stays outside per-upload controls.</p></section><p class="helper">Transcription, translation, summary, and extraction run independently. Choosing different providers sends the relevant source to each selected provider. Separate calls can increase processing time and cost.</p></aside></div>`;
    wireModelNotes(data,'defaults');
    document.querySelector('#aiSettings').onsubmit=e=>{e.preventDefault();safe(e.submitter,async()=>{
      const updated=await api('/ai-settings',{method:'PUT',body:JSON.stringify({expected_version:data.version,defaults:readModels('defaults')})});
      data.version=updated.version;
      if(version===requestVersion)document.querySelector('#settingsStatus').innerHTML='<p class="success">Defaults saved. New uploads will use these choices.</p>';
    })};
  }catch(error){if(version===requestVersion)message(error.message)}
}
function processingDetails(entry){
  const config=entry.processing_config;
  if(!config)return '<p class="helper">This entry predates saved model selections.</p>';
  const completed=entry.completed_stages||[];
  return `<details class="card"><summary>Processing details</summary><p class="helper">Choices saved when this entry was queued. A retry keeps these choices and completed stages.</p>${Object.entries(config.models).map(([task,choice])=>`<p><strong>${esc(taskNames[task]||task)}</strong><br>${esc(choice.provider)} / ${esc(choice.model)} <span class="pill">${completed.includes(task)?'Completed':'Not completed'}</span></p>`).join('')}<p class="helper">Expected languages: ${esc(config.languages?.join(', ')||'Automatic detection')}</p></details>`;
}

init();
