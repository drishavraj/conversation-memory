import morphdom from "morphdom";
import { mountMemories } from "./memories-ui.js";
let memoryCleanup;
import { processingSteps } from "./processing-progress.js";
import { createClient } from "@supabase/supabase-js";
const root = document.querySelector("#app");
let appearance = 'system';
try { appearance = localStorage.getItem('memory-appearance') || 'system'; } catch {}
const systemAppearance = matchMedia('(prefers-color-scheme: dark)');
function applyAppearance() {
  const dark = appearance === 'dark' || (appearance === 'system' && systemAppearance.matches);
  document.documentElement.dataset.appearance = dark ? 'dark' : 'light';
  document.querySelector('meta[name="theme-color"]')?.setAttribute('content', dark ? '#191a1b' : '#faf9f6');
}
systemAppearance.addEventListener('change', applyAppearance);
applyAppearance();
let captureBusy = false;
let previewURL, recordingPending = false, libraryQuery = '';
function clearAudio() {
  if (previewURL) URL.revokeObjectURL(previewURL);
  previewURL = null; recordingFile = null;
}
function leaveCapture() {
  if (captureBusy) { message("Please wait for your conversation to finish saving."); return false; }
  if (screen === 'Capture' && (recordingPending || recordingFile || recorder?.state === 'recording' || recorder?.state === 'paused')) {
    if (!confirm('Leave and discard this unsaved recording?')) return false;
  }
  stopRecording(); clearAudio(); return true;
}
window.addEventListener('beforeunload', e => {
  if (captureBusy || recordingPending || recordingFile || recorder?.state === 'recording' || recorder?.state === 'paused') {
    e.preventDefault(); e.returnValue = '';
  }
});
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
  Memories: icon("M12 3a9 9 0 1 0 9 9M12 3v9h9"),
  Settings: icon("M4 7h16M4 17h16M9 4v6M15 14v6"),
  Capture: icon("M12 5v14M5 12h14"),
  Ask: icon("M5 4h14v12H9l-4 4V4Z"),
  Library: icon("M4 4h7v16H4V4ZM13 4h7v16h-7V4Z"),
  Actions: icon("m5 12 4 4L19 6"),
};
let auth,
  config,
  session,
  screen = "Actions",
  theme = "",
  mode = "audio",
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
// Reconcile refreshed data without discarding unchanged nodes or open disclosures.
function updateContent(node, html) {
  const next = node.cloneNode(false);
  next.innerHTML = html;
  morphdom(node, next, {
    childrenOnly: true,
    onBeforeElUpdated(from, to) {
      if (from.tagName === 'DETAILS') to.open = from.open;
      if (from.id === 'libraryQuery' || (from === document.activeElement && from.matches('input,textarea'))) {
        to.value = from.value;
      }
      return !from.isEqualNode(to);
    },
  });
}
function savingProgress(percent) {
  const host = document.querySelector('#captureResult');
  if (!host) return;
  const uploading = Number.isFinite(percent) && percent < 100;
  const button = document.querySelector('#saveCapture');
  if (button) button.textContent = uploading ? `Uploading… ${percent}%` : 'Saving…';
  host.innerHTML = `<div class="save-progress" role="status"><p>${uploading ? `Uploading… ${percent}%` : 'Saving your conversation…'}</p><progress aria-label="${uploading ? 'Upload progress' : 'Saving conversation'}" ${uploading ? `value="${percent}" max="100"` : ''}></progress><p class="helper">${percent === 100 ? 'Upload received. Waiting for the server to confirm.' : 'Keep this page open. Your notes will process automatically after saving.'}</p></div>`;
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
  const { onUploadProgress, ...requestOptions } = options;
  const response = onUploadProgress ? await new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open(requestOptions.method || 'POST', '/api' + path);
    Object.entries(headers).forEach(([key, value]) => xhr.setRequestHeader(key, value));
    xhr.upload.onprogress = e => { if (e.lengthComputable) onUploadProgress(Math.round(e.loaded / e.total * 100)); };
    xhr.onload = () => resolve({ ok: xhr.status >= 200 && xhr.status < 300, status: xhr.status, json: async () => JSON.parse(xhr.responseText) });
    xhr.onerror = () => reject(new Error('Upload interrupted. Your file is still selected; please try again.'));
    xhr.onabort = () => reject(new Error('Upload cancelled. Please try again.'));
    xhr.send(requestOptions.body);
  }) : await fetch("/api" + path, { ...requestOptions, headers });
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
  if (button.disabled) return;
  const original = button.innerHTML;
  const saving = button.id === 'saveCapture';
  const row = button.closest('.todo-row');
  if (row) row.inert = true;
  button.disabled = true;
  button.setAttribute('aria-busy', 'true');
  button.insertAdjacentHTML('afterbegin', '<span class="busy-spinner" aria-hidden="true"></span>');
  const captureControls = saving ? [...document.querySelectorAll('#capture input, #capture select, #capture textarea, #record, #discardAudio')] : [];
  const controlStates = captureControls.map(el => el.disabled);
  if (saving) { document.querySelector('#captureResult')?.replaceChildren(); captureBusy = true; savingProgress(); captureControls.forEach(el => el.disabled = true); }
  try {
    await work();
  } catch (e) {
    message(e.message, 'error', saving ? document.querySelector('#captureResult') || root : root);
  } finally {
    button.disabled = false;
    if (button.hasAttribute('aria-busy')) button.innerHTML = original;
    button.removeAttribute('aria-busy');
    if (row) row.inert = false;
    captureControls.forEach((el, index) => el.disabled = controlStates[index]);
    if (saving) { captureBusy = false; document.querySelector('#captureResult .save-progress')?.remove(); }
  }
}
async function showAuth() {
  memoryCleanup?.();memoryCleanup=null;
  stopRecording(); clearAudio();
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
  if (!leaveCapture()) return;
  await auth.auth.signOut();
  await showAuth();
}
const navNames = {Capture:'Record', Actions:'To-dos', Memories:'Memories', Library:'Conversations'};
const screenTitles = {Capture:'Record a conversation',Actions:'To-dos',Library:'Conversations',Ask:'Ask your memory',Settings:'Settings',Memories:'Memories'};
function closeAccount() { const menu=document.querySelector('#accountMenu'); if(menu)menu.hidden=true; document.querySelector('#accountToggle')?.setAttribute('aria-expanded','false'); }
root.addEventListener('click',e=>{if(!e.target.closest('.account-dock'))closeAccount();});
root.addEventListener('keydown',e=>{if(e.key==='Escape'&&!document.querySelector('#accountMenu')?.hidden){closeAccount();document.querySelector('#accountToggle')?.focus();}});
function updateShellHeader() { document.querySelector('#pageTitle').textContent=screenTitles[screen]||'Memory'; document.querySelector('.main').dataset.screen=screen; document.querySelector('#theme').hidden=screen==='Settings'; root.querySelectorAll('[data-nav]').forEach(b=>{if(b.dataset.nav===(screen==='Ask'?'Library':screen))b.setAttribute('aria-current','page');else b.removeAttribute('aria-current');}); }
function navigate(next) {
  if (!leaveCapture()) return;
  screen = next; render();
}
function shell() {
  const email=session.user.email||'';
  const metadata=session.user.user_metadata||{};
  const displayName=String(metadata.full_name||metadata.name||email.split('@')[0]||'Your account');
  const initials=displayName.trim().split(/\s+/).slice(0,2).map(x=>x[0]||'').join('').toUpperCase();
  const environment=config.environment&&config.environment!=='production'?`<span class="env-badge" aria-label="${esc(config.environment)} environment">${esc(config.environment==='development'?'DEV':config.environment.toUpperCase())}</span>`:'';
  let collapsed=false;try{collapsed=localStorage.getItem('memory-sidebar-collapsed')==='true';}catch{}
  root.innerHTML = `<div class="shell ${collapsed?'sidebar-collapsed':''}"><aside class="sidebar"><div class="brand-row"><div class="brand"><span class="brand-word">Memory</span>${environment}</div>${btn('‹','sidebar-toggle','id="sidebarToggle" aria-label="Toggle sidebar" aria-expanded="'+!collapsed+'"')}</div><nav class="nav" aria-label="Main navigation">${Object.entries(navNames).filter(([id])=>id!=='Memories'||config.memories_enabled).map(([id,label])=>btn(`${icons[id]}<span>${label}</span>`,'',`data-nav="${id}" aria-label="${label}" title="${label}"`)).join('')}</nav><footer class="account-dock"><div id="accountMenu" class="account-menu" hidden><div class="account-menu-identity"><strong>${esc(displayName)}</strong><span>${esc(email)}</span></div>${btn('Settings','','id="settingsNav"') }<label for="accountAppearance">Appearance</label><select id="accountAppearance">${['system','light','dark'].map(x=>`<option value="${x}" ${appearance===x?'selected':''}>${x[0].toUpperCase()+x.slice(1)}</option>`).join('')}</select>${btn('Sign out','','id="accountLogout"')}</div><button id="accountToggle" class="account-toggle" aria-expanded="false" aria-controls="accountMenu" aria-label="Open account menu"><span class="account-avatar">${esc(initials)}</span><span class="account-identity"><span>${esc(displayName)}</span><small>${esc(email)}</small></span><span class="account-chevron" aria-hidden="true">⌃</span></button></footer></aside><main class="main"><header class="topbar"><div class="page-heading"><h1 id="pageTitle"></h1><span class="mobile-environment">${environment}</span></div><select id="theme" aria-label="Current theme"><option value="">All themes</option>${Object.entries(names).map(([id,n])=>`<option value="${id}" ${theme===id?'selected':''}>${n}</option>`).join('')}</select></header><div id="content"></div></main></div>`;
  document.querySelector('#settingsNav').onclick = () => {closeAccount();navigate('Settings');};
  document.querySelector('#accountToggle').onclick=()=>{const menu=document.querySelector('#accountMenu');menu.hidden=!menu.hidden;document.querySelector('#accountToggle').setAttribute('aria-expanded',!menu.hidden);};
  document.querySelector('#accountLogout').onclick=e=>safe(e.currentTarget,logout);
  document.querySelector('#accountAppearance').onchange=e=>{appearance=e.target.value;try{localStorage.setItem('memory-appearance',appearance);}catch{}applyAppearance();const settings=document.querySelector('#appearance');if(settings)settings.value=appearance;};
  document.querySelector('#sidebarToggle').onclick=()=>{const collapsed=document.querySelector('.shell').classList.toggle('sidebar-collapsed');document.querySelector('#sidebarToggle').setAttribute('aria-expanded',!collapsed);try{localStorage.setItem('memory-sidebar-collapsed',collapsed);}catch{}positionCaptureBar();};
  document.querySelector('#theme').onchange = e => {
    if (!leaveCapture()) { e.target.value = theme; return; }
    theme = e.target.value; render();
  };
  root.querySelectorAll('[data-nav]').forEach(b=>b.onclick=()=>navigate(b.dataset.nav));
  render();
}
function render() {
  memoryCleanup?.();memoryCleanup=null;
  clearTimeout(refreshTimer);
  const version = ++requestVersion;
  root
    .querySelectorAll("[data-nav]")
    .forEach((b) => b.classList.toggle("active", b.dataset.nav === (screen === "Ask" ? "Library" : screen)));
  const area = document.querySelector("#content");
  delete area.dataset.entryId;
  closeAccount();updateShellHeader();
  area.innerHTML = `${screen==='Actions'?`<div class="page-actions">${btn('Record conversation','secondary','id="quickRecord"')}</div>`:''}${['Library','Ask'].includes(screen)?`<div class="tabs">${btn('Conversations',screen==='Library'?'active':'','data-view="Library"')}${btn('Ask your memory',screen==='Ask'?'active':'','data-view="Ask"')}</div>`:''}<div id="panel"></div>`;
  document.querySelector('#quickRecord')?.addEventListener('click',()=>navigate('Capture'));
  root.querySelectorAll('[data-view]').forEach(b=>b.onclick=()=>navigate(b.dataset.view));
  ({
    Memories: () => { memoryCleanup=mountMemories(document.querySelector('#panel'),{api,esc,theme,openEntry,active:()=>version===requestVersion}); },
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
let captureBarObserver;
function positionCaptureBar() {
  const panel = document.querySelector('.capture-panel'), bar = document.querySelector('#captureActions');
  if (!panel || !bar) return;
  const bounds = panel.getBoundingClientRect();
  const nav = document.querySelector('.sidebar');
  const navHeight = nav && getComputedStyle(nav).position === 'fixed' ? nav.getBoundingClientRect().height : 0;
  const viewport = window.visualViewport;
  const keyboardInset = viewport ? Math.max(0, innerHeight - viewport.height - viewport.offsetTop) : 0;
  bar.style.left = `${bounds.left}px`; bar.style.width = `${bounds.width}px`;
  bar.style.bottom = `${Math.max(navHeight, keyboardInset) + 8}px`;
  panel.style.paddingBottom = `${bar.getBoundingClientRect().height + 24}px`;
}
window.addEventListener('resize', positionCaptureBar);
window.visualViewport?.addEventListener('resize', positionCaptureBar);
window.visualViewport?.addEventListener('scroll', positionCaptureBar);
function syncCaptureActions() {
  if (!document.querySelector('#captureActions')) return;
  const active = recorder?.state === 'recording' || recorder?.state === 'paused';
  const hasFile = Boolean(recordingFile || document.querySelector('#file')?.files.length);
  const record = document.querySelector('#record'); if (record) record.hidden = active;
  const finish = document.querySelector('#finishRecord');
  if (finish) { finish.hidden = !active; finish.disabled = recordingPending; }
  const pause = document.querySelector('#pauseRecord');
  if (pause) { pause.hidden = !active; pause.textContent = recorder?.state === 'paused' ? 'Resume' : 'Pause'; }
  const discard = document.querySelector('#discardAudio'); if (discard) discard.hidden = !recordingFile || active;
  document.querySelector('#saveCapture').hidden = active || (mode === 'audio' && !hasFile);
  document.querySelector('#captureHint').textContent = active ? 'Recording stays on this device until you save.' : mode === 'audio' && !hasFile ? 'Record or choose an audio file to save.' : 'Ready to save your conversation.';
  positionCaptureBar();
}
function capture() {
  const captureVersion = requestVersion;
  document.querySelector("#panel").innerHTML = `<section class="capture-panel"><div class="tabs capture-tabs">${[['audio','Record / audio'],['text','Text'],['document','Document']].map(([id,label])=>btn(label,mode===id?'active':'',`data-mode="${id}"`)).join('')}</div><form id="capture"><label for="captureTheme">Theme</label><select id="captureTheme" required><option value="">Choose a theme</option>${Object.entries(names).map(([id,n])=>`<option value="${id}" ${theme===id?'selected':''}>${n}</option>`).join('')}</select>${mode==='audio'?`<div class="recorder"><button id="record" type="button" class="record-button">${icon('M9 5a3 3 0 0 1 6 0v7a3 3 0 0 1-6 0V5ZM5 10v2a7 7 0 0 0 14 0v-2M12 19v3M8 22h8')}<span>Record conversation</span></button><p id="recordState" role="status">Ready when you are.</p><div id="audioPreview"></div></div><details><summary>Upload an audio file</summary><label for="file">Audio file</label><input id="file" type="file" accept=".mp3,.m4a,.wav,.ogg,.flac,.webm"><p class="helper">Up to 25 MB</p></details>`:mode==='text'?'<label for="transcript">Conversation or note</label><textarea id="transcript" required maxlength="200000" placeholder="Paste a conversation or write a note…"></textarea>':'<label for="file">Document</label><input id="file" type="file" accept=".txt,.pdf,.docx"><p class="helper">TXT, DOCX or text-based PDF · Up to 10 MB</p>'}${config.memories_enabled?'<label for="captureProject">Project (optional)</label><select id="captureProject"><option value="">No project</option></select>':''}<details class="capture-details"><summary>Title &amp; date</summary><label for="title">Title (optional)</label><input id="title" maxlength="200" placeholder="A title will be added if left blank"><label for="event">When did it happen?</label><input id="event" type="datetime-local" value="${localNow()}" required><p class="helper">${esc(Intl.DateTimeFormat().resolvedOptions().timeZone)} · Used to interpret dates in the conversation.</p></details><details class="processing-options"><summary>Processing options</summary><div id="processingControls">Loading model choices…</div></details><div id="captureActions" class="capture-actions" aria-label="Conversation actions"><p id="captureHint" class="helper"></p><div class="capture-action-buttons">${mode==='audio'?'<button id="pauseRecord" type="button" class="secondary" hidden>Pause</button><button id="discardAudio" type="button" class="secondary" hidden>Discard recording</button><button id="finishRecord" type="button" class="primary" hidden>Finish recording</button>':''}${btn('Save conversation','primary','id="saveCapture" disabled')}</div><div id="captureResult" aria-live="polite"></div></div></form></section>`;
  captureBarObserver?.disconnect();
  captureBarObserver = new ResizeObserver(positionCaptureBar);
  for (const selector of ['.capture-panel', '#captureActions', '.sidebar']) captureBarObserver.observe(document.querySelector(selector));
  syncCaptureActions();
  document.querySelector('#finishRecord')?.addEventListener('click', () => { document.querySelector('#finishRecord').disabled = true; document.querySelector('#pauseRecord').disabled = true; recordAudio({currentTarget:document.querySelector('#record')}); });
  document.querySelector('#discardAudio')?.addEventListener('click', () => {
    clearAudio();document.querySelector('#audioPreview').replaceChildren();
    const button=document.querySelector('#record');button.textContent='Record conversation';button.classList.remove('has-recording');
    document.querySelector('#recordState').textContent='Ready when you are.';syncCaptureActions();
  });
  document.querySelector('#pauseRecord')?.addEventListener('click', e=>{
    if(recorder?.state==='recording'){recorder.pause();e.target.textContent='Resume';}
    else if(recorder?.state==='paused'){recorder.resume();e.target.textContent='Pause';}
    syncCaptureActions();
  });
  document.querySelector('#file')?.addEventListener('change',e=>{
    if(recordingFile && e.target.files.length && !confirm('Replace the recorded audio with this file?')) {e.target.value='';return;}
    clearAudio(); document.querySelector('#audioPreview')?.replaceChildren(); syncCaptureActions();
  });
  let captureProjectRequest=0;
  async function loadCaptureProjects(){
    if(!config.memories_enabled)return;
    const selectedTheme=document.querySelector('#captureTheme').value;
    const sequence=++captureProjectRequest;
    const select=document.querySelector('#captureProject');select.innerHTML='<option value="">No project</option>';
    if(!selectedTheme)return;
    try{const data=await api('/memories/projects?limit=100&theme_id='+selectedTheme);if(captureVersion!==requestVersion||sequence!==captureProjectRequest)return;select.innerHTML='<option value="">No project</option>'+data.items.map(p=>`<option value="${esc(p.id)}">${esc(p.name)}</option>`).join('');}catch(error){if(captureVersion===requestVersion)message('Could not load projects. You can link the conversation from Memories after saving.');}
  }
  document.querySelector('#captureTheme').addEventListener('change',loadCaptureProjects);
  loadCaptureProjects();
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
        if (!leaveCapture()) return;
        mode = b.dataset.mode;
        render();
      }),
  );
  document.querySelector("#record")?.addEventListener("click", recordAudio);
  document.querySelector("#capture").onsubmit = (e) => {
    e.preventDefault();
    safe(e.submitter, async () => {
      if (recordingPending || recorder?.state === "recording" || recorder?.state === "paused")
        throw new Error("Stop the recording before saving.");
      const title = document.querySelector("#title").value.trim() || `${names[document.querySelector("#captureTheme").value] || "New"} conversation · ${new Date().toLocaleDateString()}`,
        theme_id = document.querySelector("#captureTheme").value,
        event_at = eventISO(document.querySelector("#event").value);
      if (!title || !theme_id)
        throw new Error("Add a title and choose a theme.");
      if(!captureSettings) throw new Error('Wait for model choices to load.');
      const processing = {models:readModels('capture'), languages:[...document.querySelectorAll('[name="language"]:checked')].map(x=>x.value)};
      const selectedProject=document.querySelector('#captureProject')?.value;
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
        entry = await api("/entries/upload", { method: "POST", body: data, onUploadProgress: savingProgress });
      }
      if (captureVersion !== requestVersion) return;
      document.querySelector("#captureResult").innerHTML =
        `<p class="success">${entry.duplicate ? "Already saved. Opening the existing entry with its original processing settings." : "Saved. Processing will run automatically."}</p>`;
      let linkingError;
      if(selectedProject){try{await api(`/memories/projects/${selectedProject}/entries`,{method:'POST',body:JSON.stringify({entry_id:entry.id,topic_ids:[]})});}catch(error){linkingError=error.message;}}
      clearAudio();
      await openEntry(entry.id);
      if(linkingError)message('Conversation saved, but project linking failed: '+linkingError+'. Link it from Memories.');
    });
  };
}
async function recordAudio(e) {
  const button=e.currentTarget;
  if (recorder && recorder.state!=='inactive') { recorder.stop(); button.disabled=true; return; }
  if(recordingFile && !confirm('Replace your unsaved recording?')) return;
  const version=requestVersion;
  button.disabled=true; recordingPending=true;
  try {
    if(!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) throw new Error('Recording is unavailable. Upload an audio file instead.');
    const acquired=await navigator.mediaDevices.getUserMedia({audio:true});
    if(version!==requestVersion){acquired.getTracks().forEach(t=>t.stop());return;}
    stream=acquired; clearAudio(); document.querySelector('#file').value='';
    document.querySelector('#audioPreview').replaceChildren();
    const type=['audio/webm;codecs=opus','audio/mp4','audio/ogg;codecs=opus'].find(t=>MediaRecorder.isTypeSupported(t));
    const active=new MediaRecorder(stream,type?{mimeType:type}:undefined); recorder=active;
    const parts=[]; let seconds=0, size=0;
    const pause=document.querySelector('#pauseRecord');pause.hidden=false;pause.textContent='Pause';
    document.querySelector('#file').disabled=true;
    active.ondataavailable=e=>{if(e.data.size){parts.push(e.data);size+=e.data.size;}};
    active.onstop=()=>{
      clearInterval(recordTimer);acquired.getTracks().forEach(t=>t.stop());
      if(version!==requestVersion)return;
      const mime=active.mimeType,ext=mime.includes('mp4')?'m4a':mime.includes('ogg')?'ogg':'webm';
      recordingFile=new File(parts,`recording.${ext}`,{type:mime});
      previewURL=URL.createObjectURL(recordingFile);
      button.disabled=false;button.textContent='Record again';button.classList.remove('is-recording');button.classList.add('has-recording');pause.hidden=true;
      document.querySelector('#file').disabled=false;
      document.querySelector('#recordState').textContent='Recording ready. Listen before saving.';
      document.querySelector('#audioPreview').innerHTML=`<audio controls src="${previewURL}" aria-label="Recording playback"></audio>`;
      pause.disabled=false;syncCaptureActions();
    };
    active.start(1000);button.textContent='Finish recording';button.classList.remove('has-recording');button.classList.add('is-recording');
    document.querySelector('#recordState').textContent='Recording · 0:00';
    syncCaptureActions();
    recordTimer=setInterval(()=>{
      if(active.state==='recording')seconds++;
      const node=document.querySelector('#recordState');
      if(node)node.textContent=`${active.state==='paused'?'Paused':'Recording'} · ${Math.floor(seconds/60)}:${String(seconds%60).padStart(2,'0')}`;
      if(size>24*1024*1024 && active.state!=='inactive')active.stop();
    },1000);
  } catch(error) {
    stream?.getTracks().forEach(t=>t.stop());
    if(version===requestVersion)message(error.name==='NotAllowedError'?'Allow microphone access to record, or upload a file.':error.message);
  } finally {recordingPending=false;if(button.isConnected)button.disabled=false;syncCaptureActions();}
}
function stopRecording() {
  clearInterval(recordTimer);
  if(recorder){recorder.onstop=null;if(recorder.state!=='inactive')recorder.stop();}
  stream?.getTracks().forEach(t=>t.stop());
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
function onClick(selector, handler) {
  const node = document.querySelector(selector);
  if (node) node.onclick = handler;
}
function scope() {
  return theme ? "&theme_id=" + encodeURIComponent(theme) : "";
}
async function library(version, offset = 0) {
  const panel = document.querySelector("#panel");
  clearTimeout(refreshTimer);
  if (!panel.children.length) panel.innerHTML = '<p class="muted" role="status">Loading your entries…</p>';
  try {
    const rows = await api(`/entries?limit=20&offset=${offset}&q=${encodeURIComponent(libraryQuery)}${scope()}`);
    if (version !== requestVersion) return;
    updateContent(panel, `<form id="conversationSearch" class="row library-search"><input id="libraryQuery" type="search" aria-label="Search conversations" placeholder="Search titles and transcripts" maxlength="200" value="${esc(libraryQuery)}">${btn("Search","secondary")}</form><div class="row spread" style="margin-bottom:18px"><span class="helper">${esc(theme ? names[theme] : "All themes")} · Page ${offset / 20 + 1}</span>${btn("Refresh", "secondary", 'id="refresh"')}</div>${rows.length ? rows.map((r) => `<button class="entry" data-entry="${esc(r.id)}"><div class="row spread">${badge(r.theme_id)}<span class="pill ${esc(r.status)}">${esc(r.status)}</span></div><h3>${esc(r.title)}</h3><p class="meta">${esc(r.input_type || "text")} · ${date(r.event_at || r.uploaded_at)}</p><p class="muted">${esc((r.original_text || "").slice(0, 150))}${(r.original_text || "").length > 150 ? "…" : ""}</p></button>`).join("") : '<div class="card empty">Nothing saved here yet. Capture a conversation to start your memory.</div>'}<div class="row">${offset ? btn("Previous", "secondary", 'id="prev"') : ""}${rows.length === 20 ? btn("Next page", "secondary", 'id="next"') : ""}</div>`);
    panel
      .querySelectorAll("[data-entry]")
      .forEach((b) => (b.onclick = () => openEntry(b.dataset.entry)));
    document.querySelector('#conversationSearch').onsubmit=e=>{e.preventDefault();libraryQuery=document.querySelector('#libraryQuery').value;library(++requestVersion,0);};
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
  memoryCleanup?.();memoryCleanup=null;
  clearTimeout(refreshTimer);
  screen = "Library";
  updateShellHeader();
  root
    .querySelectorAll("[data-nav]")
    .forEach((b) => b.classList.toggle("active", b.dataset.nav === "Library"));
  const version = ++requestVersion,
    area = document.querySelector("#content");
  if (area.dataset.entryId !== id) {
    area.insertAdjacentHTML('beforeend', '<p id="openingEntry" class="muted" role="status">Opening entry…</p>');
  }
  try {
    const [entry, knowledge] = await Promise.all([
      api("/entries/" + id),
      api("/entries/" + id + "/knowledge"),
    ]);
    if (version !== requestVersion) return;
    updateContent(area, `${btn("← Conversations", "link", 'id="back"')}<div class="intro"><h1>${esc(entry.title)}</h1><div class="row">${badge(entry.theme_id)}<span class="pill ${esc(entry.status)}">${esc(entry.status)}</span><span class="meta">${date(entry.event_at || entry.uploaded_at)}</span></div></div>${processingProgress(entry)}${processingDetails(entry)}${knowledge.summary ? `<section class="card soft" id="entrySummary"><span class="eyebrow">The essentials</span><p>${esc(knowledge.summary)}</p></section>` : ""}${knowledge.items.length ? `<h2>What to remember</h2>${knowledge.items.map((item) => itemCard(item, true)).join("")}` : ""}<section class="card" id="entryOriginal"><h2>Original ${entry.input_type === "audio" ? "transcript" : "text"}</h2><p class="text">${esc(entry.original_text || "Available after processing.")}</p>${entry.input_type !== "text" ? btn("Download original file", "secondary", 'id="download"') : ""}</section>${knowledge.english_text ? `<section class="card" id="entryEnglish"><h2>English version</h2><p class="text">${esc(knowledge.english_text)}</p></section>` : ""}${entry.index_status === "failed" ? `<p class="notice">Semantic indexing failed. ${btn("Retry indexing", "secondary", 'id="indexRetry"')}</p>` : ""}`);
    area.dataset.entryId = id;
    document.querySelector("#back").onclick = () => {
      screen = "Library";
      render();
    };
    onClick("#retry", (e) =>
      safe(e.target, async () => {
        await api(`/entries/${id}/retry`, { method: "POST" });
        openEntry(id);
      }),
    );
    onClick("#indexRetry", (e) =>
      safe(e.target, async () => {
        await api(`/entries/${id}/index/retry`, { method: "POST" });
        openEntry(id);
      }),
    );
    onClick("#download", (e) =>
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
  return `<article class="card" id="item-${esc(item.id)}"><div class="row spread"><div class="row">${badge(item.theme_id)}<span class="pill">${esc(item.kind)}</span>${item.certainty === "tentative" ? '<span class="pill tentative">Tentative</span>' : ""}</div><span class="meta">${esc(item.status)}</span></div><h3 class="sectiongap">${esc(item.text)}</h3><p class="meta">${esc(item.owner || "Owner unspecified")} · ${due(item)}</p><blockquote class="quote">${esc(item.evidence)}</blockquote><div class="row">${item.kind === "action" && item.status === "active" ? btn("Mark complete", "secondary", `data-status="completed" data-item="${esc(item.id)}"`) + btn("Dismiss", "link", `data-status="dismissed" data-item="${esc(item.id)}"`) : ""}${item.kind === "action" && item.status !== "active" ? btn("Reopen", "secondary", `data-status="active" data-item="${esc(item.id)}"`) : ""}${edit ? btn("Correct", "link", `data-edit="${esc(item.id)}"`) : btn("Open source", "link", `data-entry="${esc(item.source_entry_id)}"`)}</div></article>`;
}
function wireItems(items, reload) {
  root.querySelectorAll("[data-status]").forEach(
    (b) =>
      (b.onclick = () =>
        safe(b, async () => {
          const version = requestVersion;
          const item = items.find((x) => x.id === b.dataset.item);
          await api("/knowledge/" + item.id, {
            method: "PATCH",
            body: JSON.stringify({
              expected_version: item.version,
              reason: "Updated from the web app",
              status: b.dataset.status,
            }),
          });
          if (version === requestVersion) await reload();
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
  if (!document.querySelector("#actionRows")) document.querySelector("#panel").innerHTML =
    `<div class="tabs">${["active", "completed", "dismissed"].map((s) => btn(s[0].toUpperCase() + s.slice(1), actionStatus === s ? "active" : "", `data-filter="${s}"`)).join("")}</div><div id="actionRows" role="status">Loading to-dos…</div><div id="attentionRows"></div>`;
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
    const today=localNow().slice(0,10);
    const groups=actionStatus==='active' ? [
      ['Overdue',items.filter(i=>i.certainty!=='tentative' && i.due_date && i.due_date<today)],
      ['Today',items.filter(i=>i.certainty!=='tentative' && i.due_date===today)],
      ['Upcoming',items.filter(i=>i.certainty!=='tentative' && i.due_date>today)],
      ['No date',items.filter(i=>i.certainty!=='tentative' && !i.due_date)],
      ['Tentative · needs confirmation',items.filter(i=>i.certainty==='tentative')]
    ] : [[actionStatus==='completed'?'Completed':'Dismissed',items]];
    updateContent(document.querySelector('#actionRows'), items.length?groups.filter(([,rows])=>rows.length).map(([label,rows])=>`<section class="todo-group"><h2>${label}<span class="count">${rows.length}</span></h2>${rows.sort((a,b)=>(a.due_date||'').localeCompare(b.due_date||'')).map(i=>`<article class="todo-row" id="todo-${esc(i.id)}">${btn(i.status==='active'?'○':'✓','check-button',`data-status="${i.status==='active'?'completed':'active'}" data-item="${esc(i.id)}" aria-label="${i.status==='active'?'Complete':'Reopen'}: ${esc(i.text)}"`)}<details><summary>${esc(i.text)}<span class="todo-meta">${badge(i.theme_id)}<span class="${i.due_date && i.due_date<today && i.status==='active'?'overdue':''}">${esc(due(i))}</span>${i.owner?`<span>${esc(i.owner)}</span>`:''}</span></summary><blockquote class="quote">${esc(i.evidence)}</blockquote><div class="row">${btn('Open conversation','link',`data-entry="${esc(i.source_entry_id)}"`)}${btn('Correct','link',`data-edit="${esc(i.id)}"`)}${i.status==='active'?btn('Dismiss','link',`data-status="dismissed" data-item="${esc(i.id)}"`):''}</div></details></article>`).join('')}</section>`).join(''):'<div class="empty">No '+actionStatus+' to-dos here.</div>');
    if (items.length === 100)
      document
        .querySelector("#actionRows")
        .insertAdjacentHTML(
          "beforeend",
          '<p class="notice">Showing the first 100 actions.</p>',
        );
    wireItems(items, () => actions(version));
    const recent=await api(`/entries?limit=100${scope()}`);
    if(version!==requestVersion)return;
    const attention=recent.filter(r=>['failed','queued','processing'].includes(r.status));
    document.querySelector('#attentionRows').innerHTML=attention.length?`<section class="card sectiongap"><h2>Recent conversations to check</h2>${attention.slice(0,5).map(r=>`<button class="entry" data-attention="${esc(r.id)}"><strong>${esc(r.title)}</strong><p class="meta">${r.status==='failed'?'Processing needs attention':'Preparing your notes…'}</p></button>`).join('')}${attention.length>5?'<p class="helper">More conversations are waiting in Conversations.</p>':''}</section>`:'';
    root.querySelectorAll('[data-attention]').forEach(b=>b.onclick=()=>openEntry(b.dataset.attention));
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

const taskNames={transcription:'Transcription',translation:'English translation',summary:'Summary',extraction:'Memories, decisions & actions',answer:'Answers to questions',reconciliation:'Memory organisation'};
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
  const host=document.querySelector('#panel');
  host.innerHTML=`<section class="card appearance-card"><h2>Appearance</h2><label for="appearance">Colour mode</label><select id="appearance">${['system','light','dark'].map(x=>`<option value="${x}" ${appearance===x?'selected':''}>${x[0].toUpperCase()+x.slice(1)}</option>`).join('')}</select><div class="row spread sectiongap"><span class="helper">${esc(session.user.email)}</span>${btn('Sign out','link','id="logout"')}</div></section><details class="card"><summary>AI model defaults</summary><div id="aiPanel"><p role="status">Loading AI settings…</p></div></details>`;
  document.querySelector('#appearance').onchange=e=>{appearance=e.target.value;try{localStorage.setItem('memory-appearance',appearance);}catch{}applyAppearance();const account=document.querySelector('#accountAppearance');if(account)account.value=appearance;};
  document.querySelector('#logout').onclick=logout;
  const panel=document.querySelector('#aiPanel');
  try{
    const data=await api('/ai-settings');if(version!==requestVersion)return;
    const providers=[...new Set(data.catalog.map(x=>x.provider))];
    panel.innerHTML=`<div class="grid"><section class="card"><form id="aiSettings"><h2>Default models</h2><p class="helper">These defaults apply to new uploads. Existing entries keep the choices saved with them. Answer settings apply to your next question.</p>${modelControls(data,Object.keys(taskNames).filter(task=>data.defaults[task]),'defaults')}<div class="sectiongap">${btn('Save defaults')}</div></form><div id="settingsStatus" role="status"></div></section><aside><section class="card soft"><h2>Connected providers</h2>${providers.map(name=>{const row=data.catalog.find(x=>x.provider===name);return `<p><strong>${esc(name)}</strong> · ${row.available?'Key configured':'Key needed'}<br><span class="helper">${esc(row.key_variable)}</span></p>`}).join('')}<p class="helper">Keys are managed in Render. “Key configured” means a key is present; model access and results still need a live test.</p></section><section class="card"><h3>Semantic search</h3><p>${esc(data.embedding.model||'Not configured')}</p><p class="helper">Managed through EMBEDDING_MODEL. Switching embedding models requires reindexing, so this setting stays outside per-upload controls.</p></section><p class="helper">Transcription, translation, summary, and extraction run independently. Choosing different providers sends the relevant source to each selected provider. Separate calls can increase processing time and cost.</p></aside></div>`;
    wireModelNotes(data,'defaults');
    document.querySelector('#aiSettings').onsubmit=e=>{e.preventDefault();safe(e.submitter,async()=>{
      const updated=await api('/ai-settings',{method:'PUT',body:JSON.stringify({expected_version:data.version,defaults:readModels('defaults')})});
      data.version=updated.version;
      if(version===requestVersion)document.querySelector('#settingsStatus').innerHTML='<p class="success">Defaults saved. New uploads will use these choices.</p>';
    })};
  }catch(error){if(version===requestVersion)message(error.message)}
}
function processingProgress(entry) {
  const steps = processingSteps(entry);
  const ready = entry.status === 'ready';
  const failed = entry.status === 'failed';
  const states = {completed:'Completed', running:'In progress', waiting:'Waiting to resume', pending:'Upcoming', failed:'Needs retry'};
  const rows = `<ol class="processing-steps">${steps.map((step,index)=>`<li id="progress-${esc(step.id)}" class="processing-step ${step.state}" ${step.state==='running'?'aria-current="step"':''}><span class="step-marker" aria-hidden="true">${step.state==='completed'?'✓':step.state==='running'?'<span class="busy-spinner"></span>':step.state==='failed'?'!':index+1}</span><div><div class="step-label">${esc(step.label)}</div><span class="helper">${states[step.state]}</span>${step.state==='failed'?`<p class="helper">Completed work is saved.</p>${btn('Retry processing','secondary','id="retry"')}`:''}</div></li>`).join('')}</ol>`;
  if (ready) return `<p class="success" id="processingReady" role="status">✓ Conversation ready</p><details class="card" id="processingHistory"><summary>Processing history</summary>${rows}</details>`;
  const title = failed ? 'Processing needs attention' : entry.status === 'queued' ? 'Saved · waiting to continue' : 'Preparing your conversation';
  return `<section class="card processing-progress" id="processingProgress" aria-label="Conversation processing"><div role="status" aria-live="polite"><h2>${title}</h2><p class="helper">${steps.filter(s=>s.state==='completed').length} of ${steps.length} stages complete</p>${rows}</div>${failed?`<p class="error">${esc(entry.job?.error || 'Processing could not finish.')}</p>${steps.some(s=>s.state==='failed')?'':btn('Retry processing','secondary','id="retry"')}`:'<p class="helper">Your conversation is saved. You can leave this page while processing continues.</p>'}</section>`;
}
function processingDetails(entry){
  const config=entry.processing_config;
  if(!config)return '<p class="helper">This entry predates saved model selections.</p>';
  const completed=entry.completed_stages||[];
  return `<details class="card" id="processingDetails"><summary>Models &amp; processing settings</summary><p class="helper">Choices saved when this entry was queued. A retry keeps these choices and completed stages.</p>${Object.entries(config.models).map(([task,choice])=>`<p><strong>${esc(taskNames[task]||task)}</strong><br>${esc(choice.provider)} / ${esc(choice.model)} <span class="pill">${completed.includes(task)?'Completed':'Not completed'}</span></p>`).join('')}<p class="helper">Expected languages: ${esc(config.languages?.join(', ')||'Automatic detection')}</p></details>`;
}

init();
