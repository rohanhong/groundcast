"use strict";

// groundcast web UI: plain DOM code, no build step. Views are switched by the URL hash
// (#library, #create, #listen/<session id>, #concepts, #profile); one audio element plays
// sessions across views.

const $ = (id) => document.getElementById(id);
const SVG_NS = "http://www.w3.org/2000/svg";
const POLL_MS = 3000;
const SPEEDS = [0.8, 1, 1.15, 1.3, 1.5, 1.75, 2];
const STORE_KEYS = { theme: "groundcast-theme", rate: "groundcast-rate", mode: "groundcast-brief-mode",
  follow: "groundcast-follow", position: "groundcast-pos-" };

const state = {
  settings: null, materials: [], sessions: [], concepts: [], prefs: null,
  picked: new Set(), pickTouched: false, materialFilter: "",
};

// Helpers

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === null || value === undefined || value === false) continue;
    if (key === "class") node.className = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value === true ? "" : value);
  }
  append(node, children);
  return node;
}

function fill(node, ...children) {
  // replaceChildren, but arrays among the children are flattened as in el().
  node.replaceChildren();
  return append(node, children);
}

function append(node, children) {
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false || child === "") continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

function icon(name, cls = "") {
  const svg = document.createElementNS(SVG_NS, "svg");
  svg.setAttribute("class", `icon ${cls}`.trim());
  svg.setAttribute("aria-hidden", "true");
  const use = document.createElementNS(SVG_NS, "use");
  use.setAttribute("href", `#i-${name}`);
  svg.append(use);
  return svg;
}

function setIcon(button, name) {
  button.querySelector("use").setAttribute("href", `#i-${name}`);
}

async function api(path, options = {}) {
  let response;
  try {
    response = await fetch(path, options);
  } catch (error) {
    showOffline(); // the service is not answering at all
    throw error;
  }
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch (_) { /* keep statusText */ }
    const error = new Error(detail);
    error.status = response.status;
    throw error;
  }
  return response.json();
}

function send(path, method, body) {
  return api(path, { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
}

function stored(key, fallback = null) {
  try {
    const value = localStorage.getItem(key);
    return value === null ? fallback : value;
  } catch (_) {
    return fallback;
  }
}

function store(key, value) {
  try {
    if (value === null) localStorage.removeItem(key);
    else localStorage.setItem(key, String(value));
  } catch (_) { /* storage unavailable: the setting lasts for this page only */ }
}

function clock(seconds) {
  const total = Math.max(0, Math.floor(seconds || 0));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = String(total % 60).padStart(2, "0");
  return h ? `${h}:${String(m).padStart(2, "0")}:${s}` : `${m}:${s}`;
}

const relative = new Intl.RelativeTimeFormat("en", { numeric: "auto" });

function ago(iso) {
  const seconds = (Date.now() - new Date(iso).getTime()) / 1000;
  if (seconds < 45) return "just now";
  const steps = [[60, "second"], [3600, "minute"], [86400, "hour"], [86400 * 7, "day"]];
  for (let i = 1; i < steps.length; i += 1) {
    if (seconds < steps[i][0]) return relative.format(-Math.round(seconds / steps[i - 1][0]), steps[i][1]);
  }
  if (seconds < 86400 * 28) return relative.format(-Math.round(seconds / 86400), "day");
  return new Date(iso).toLocaleDateString("en", { day: "numeric", month: "short", year: "numeric" });
}

function plural(n, word) {
  return `${n} ${word}${n === 1 ? "" : "s"}`;
}

function cssVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

function busy(button, on) {
  button.disabled = on;
  button.classList.toggle("busy", on);
}

function setStatus(node, text, kind = "") {
  node.textContent = text;
  node.className = `status ${kind}`.trim();
}

// Toasts and dialogs

function toast(message, kind = "info", action = null) {
  const name = { error: "alert", ok: "check" }[kind] || "sparkle";
  const node = el("div", { class: `toast ${kind}`, role: kind === "error" ? "alert" : "status" },
    icon(name), el("span", {}, message));
  const dismiss = () => {
    node.classList.add("leaving");
    setTimeout(() => node.remove(), 200);
  };
  if (action) node.append(el("button", { type: "button", onclick: () => { action.run(); dismiss(); } }, action.label));
  $("toasts").append(node);
  setTimeout(dismiss, kind === "error" ? 8000 : 4500);
}

function ask({ title, body = "", ok = "OK", danger = false, input = null }) {
  const dialog = $("ask-dialog");
  const field = $("ask-input");
  $("ask-title").textContent = title;
  $("ask-body").textContent = body;
  $("ask-body").hidden = !body;
  field.hidden = input === null;
  field.value = input ?? "";
  $("ask-ok").textContent = ok;
  $("ask-ok").className = `btn ${danger ? "danger" : "primary"}`;
  dialog.returnValue = "";
  return new Promise((resolve) => {
    dialog.addEventListener("close", () => {
      if (dialog.returnValue !== "ok") resolve(null);
      else resolve(input === null ? true : field.value.trim());
    }, { once: true });
    dialog.showModal();
    if (input !== null) field.select();
  });
}

for (const button of document.querySelectorAll("dialog [data-close]")) {
  button.addEventListener("click", () => button.closest("dialog").close());
}
$("text-dialog").addEventListener("click", (event) => {
  if (event.target === $("text-dialog")) $("text-dialog").close(); // a click on the backdrop
});

// Theme

function applyTheme(choice) {
  if (choice === "light" || choice === "dark") document.documentElement.dataset.theme = choice;
  else delete document.documentElement.dataset.theme;
  for (const button of document.querySelectorAll("[data-theme-choice]")) {
    button.setAttribute("aria-checked", String(button.dataset.themeChoice === choice));
  }
  requestAnimationFrame(() => paint(true));
}

for (const button of document.querySelectorAll("[data-theme-choice]")) {
  button.addEventListener("click", () => {
    const choice = button.dataset.themeChoice;
    store(STORE_KEYS.theme, choice === "auto" ? null : choice);
    applyTheme(choice);
  });
}
matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => paint(true));

// Router

const VIEWS = { library: "Library", create: "New session", listen: "Sessions", concepts: "Concepts",
  profile: "Preferences" };
let currentView = null;

function defaultView() {
  return state.materials.some((m) => m.status === "ready") ? "create" : "library";
}

function route() {
  const [name, arg] = location.hash.slice(1).split("/");
  const view = name in VIEWS ? name : defaultView();
  if (view !== currentView) {
    for (const dialog of document.querySelectorAll("dialog[open]")) dialog.close(); // Back must not leave one open
    for (const section of document.querySelectorAll(".view")) section.hidden = section.dataset.view !== view;
    for (const link of document.querySelectorAll(".nav a")) {
      if (link.dataset.view === view) link.setAttribute("aria-current", "page");
      else link.removeAttribute("aria-current");
    }
    document.title = `${VIEWS[view]} | groundcast`;
    if (currentView !== null) window.scrollTo({ top: 0 });
    currentView = view;
  }
  if (view === "listen") showDetail(arg || null);
  if (view === "profile" && $("doctor").open && !$("doctor-list").childElementCount) loadDoctor();
}

window.addEventListener("hashchange", route);

// Settings line

async function loadSettings() {
  state.settings = await api("/api/settings");
  const s = state.settings;
  fill($("settings-line"), 
    el("b", {}, "LLM "), s.llm_backend, el("br"),
    el("b", {}, "Voice "), `${s.voice} at ${s.speed}x (${s.tts_engine})`);
  updateMinutes();
}

// Library

const KINDS = {
  pdf: ["pdf", "PDF"], pptx: ["slides", "Slides"], docx: ["doc", "Word"], markdown: ["text", "Markdown"],
  text: ["text", "Text"], html: ["globe", "Web page"], image: ["image", "Image"], video: ["video", "Video"],
  audio: ["audio", "Audio"],
};
const UNIT_NAMES = { pptx: "slide", video: "passage", audio: "passage" };
let materialTimer = null;

function kindIcon(kind) {
  return el("span", { class: `kind-icon kind-${kind}` }, icon((KINDS[kind] || ["doc"])[0]));
}

function sizeText(m) {
  const parts = [(KINDS[m.kind] || [null, m.kind])[1]];
  if (m.duration_s) parts.push(`${Math.max(1, Math.round(m.duration_s / 60))} min`);
  parts.push(plural(m.pages, UNIT_NAMES[m.kind] || "page"), `${m.words.toLocaleString()} words`);
  return parts.join(" / ");
}

function materialStatus(m) {
  if (m.status === "processing") {
    return el("span", { class: "tag accent live" }, el("span", { class: "spinner" }), "Recognising");
  }
  if (m.status === "review") return el("span", { class: "tag warn" }, icon("alert"), "Needs your check");
  if (m.status === "failed") return el("span", { class: "tag bad" }, icon("x"), "Failed");
  const notes = [];
  if (m.ocr_pages && m.ocr_pages.length) notes.push(`text recognised on ${plural(m.ocr_pages.length, "page")}`);
  if (m.reviewed_at) notes.push("checked by you");
  return [el("span", { class: "tag ok" }, icon("check"), "Ready"), notes.length ? ` ${notes.join(", ")}` : ""];
}

async function loadMaterials() {
  state.materials = await api("/api/materials");
  renderMaterials();
  renderPicker();
  clearTimeout(materialTimer);
  if (state.materials.some((m) => m.status === "processing")) {
    // Recognition runs in the background; refresh until it is done.
    materialTimer = setTimeout(() => loadMaterials().catch(() => {}), POLL_MS);
  }
}

function renderMaterials() {
  const all = state.materials;
  const query = state.materialFilter.toLowerCase();
  const shown = all.filter((m) => m.filename.toLowerCase().includes(query));
  $("materials-count").textContent = all.length ? String(all.length) : "";
  $("onboarding").hidden = all.length > 0;
  const needs = all.filter((m) => m.status === "review" || m.status === "failed").length;
  $("badge-library").hidden = !needs;
  $("badge-library").textContent = String(needs);
  const list = $("materials");
  if (!shown.length) {
    fill(list, el("li", { class: "empty" }, icon("library"),
      el("strong", {}, all.length ? "Nothing matches the filter" : "No materials yet"),
      all.length ? "" : "Add a file or a web page above to begin."));
    return;
  }
  fill(list, ...shown.map((m, i) => {
    const ready = m.status === "ready";
    const actions = [];
    if (m.status === "review") {
      actions.push(el("button", { class: "btn primary sm", type: "button", onclick: () => showReview(m) },
        icon("eye"), "Check text"));
    } else if (ready) {
      actions.push(el("button", { class: "linkish", type: "button", onclick: () => showText(m) }, icon("text"), "View text"));
    }
    if (m.status === "failed") {
      actions.push(el("button", { class: "linkish", type: "button", onclick: () => retryMaterial(m) },
        icon("refresh"), "Try again"));
    }
    actions.push(el("a", { class: "linkish", href: m.source_url || `/data/materials/${m.stored_name}`, target: "_blank",
      rel: "noopener" }, icon("external"), m.source_url ? "Open page" : "Open file"));
    actions.push(el("span", { class: "spacer" }));
    actions.push(el("button", { class: "linkish bad", type: "button", title: "Remove", "aria-label": `Remove ${m.filename}`,
      onclick: () => deleteMaterial(m) }, icon("trash")));
    return el("li", { class: `material${m.status === "review" || m.status === "failed" ? " needs" : ""}`,
      style: `animation-delay: ${Math.min(i, 12) * 25}ms` },
      el("div", { class: "material-top" }, kindIcon(m.kind),
        el("div", {}, el("div", { class: "material-name" }, m.filename),
          el("div", { class: "material-meta" }, `${sizeText(m)} / added ${ago(m.added_at)}`))),
      el("div", { class: `material-status${m.error ? " error" : ""}` }, materialStatus(m),
        m.error ? el("div", { class: "small" }, m.error) : ""),
      el("div", { class: "material-actions" }, actions));
  }));
}

$("materials-search").addEventListener("input", (event) => {
  state.materialFilter = event.target.value.trim();
  renderMaterials();
});

async function retryMaterial(material) {
  try {
    await api(`/api/materials/${material.id}/retry`, { method: "POST" });
    await loadMaterials();
  } catch (error) {
    toast(`Could not try again: ${error.message}`, "error");
  }
}

async function deleteMaterial(material) {
  const ok = await ask({ title: `Remove ${material.filename}?`, ok: "Remove", danger: true,
    body: "The file and its extracted text leave the data directory. Sessions made from it keep their audio." });
  if (!ok) return;
  try {
    await api(`/api/materials/${material.id}`, { method: "DELETE" });
    state.picked.delete(material.id);
    toast(`Removed ${material.filename}.`, "ok");
    await loadMaterials();
  } catch (error) {
    toast(`Could not remove it: ${error.message}`, "error");
  }
}

async function showText(material) {
  try {
    const chunks = await api(`/api/materials/${material.id}/chunks`);
    $("text-title").textContent = `${material.filename}: ${plural(chunks.length, "passage")}`;
    fill($("text-list"), ...chunks.map((c) => el("li", {}, el("code", {}, c.id), el("div", {}, c.text))));
    $("text-dialog").showModal();
  } catch (error) {
    toast(`Could not load the text: ${error.message}`, "error");
  }
}

// Upload: files go up with a progress bar, then the server extracts their text.

function uploadFiles(files) {
  if (!files.length) return;
  const form = new FormData();
  for (const file of files) form.append("files", file);
  const meter = $("upload-bar").parentElement;
  $("upload-progress").hidden = false;
  meter.classList.remove("indeterminate");
  $("upload-bar").style.width = "0";
  $("upload-label").textContent = `Uploading ${plural(files.length, "file")}...`;
  setStatus($("upload-status"), "");
  const xhr = new XMLHttpRequest();
  xhr.open("POST", "/api/materials");
  xhr.upload.addEventListener("progress", (event) => {
    if (!event.lengthComputable) return;
    $("upload-bar").style.width = `${Math.round((event.loaded / event.total) * 100)}%`;
    if (event.loaded >= event.total) {
      meter.classList.add("indeterminate");
      $("upload-label").textContent = "Extracting text...";
    }
  });
  xhr.addEventListener("load", async () => {
    $("upload-progress").hidden = true;
    let body = null;
    try { body = JSON.parse(xhr.responseText); } catch (_) { /* not JSON */ }
    if (xhr.status >= 300) {
      const detail = body && typeof body.detail === "string" ? body.detail : xhr.statusText;
      setStatus($("upload-status"), `Upload failed: ${detail}`, "error");
      return;
    }
    const waiting = body.filter((m) => m.status !== "ready").length;
    toast(`Added ${plural(body.length, "file")}.` + (waiting ? " Recognition runs in the background." : ""), "ok");
    setStatus($("upload-status"), waiting
      ? "Speech and scanned text are recognised in the background; check the text when it is done."
      : "Open \"View text\" to see what was extracted.");
    $("upload-input").value = "";
    await loadMaterials();
  });
  xhr.addEventListener("error", () => {
    $("upload-progress").hidden = true;
    setStatus($("upload-status"), "Upload failed: the local service did not answer.", "error");
  });
  xhr.send(form);
}

$("upload-input").addEventListener("change", (event) => uploadFiles(event.target.files));

const dropzone = $("dropzone");
for (const name of ["dragenter", "dragover"]) {
  dropzone.addEventListener(name, (event) => {
    event.preventDefault();
    dropzone.classList.add("over");
  });
}
dropzone.addEventListener("dragleave", (event) => {
  if (!dropzone.contains(event.relatedTarget)) dropzone.classList.remove("over");
});
dropzone.addEventListener("drop", (event) => {
  event.preventDefault();
  dropzone.classList.remove("over");
  uploadFiles(event.dataTransfer.files);
});
// A file dropped outside the drop zone must not replace the page.
for (const name of ["dragover", "drop"]) window.addEventListener(name, (event) => event.preventDefault());

$("url-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const url = $("url-input").value.trim();
  if (!url) return;
  const button = event.target.querySelector("button");
  busy(button, true);
  try {
    const m = await send("/api/materials/url", "POST", { url });
    toast(`Added ${m.filename}.`, "ok");
    setStatus($("upload-status"), "Check the extracted text with \"View text\" before you use it.");
    $("url-input").value = "";
    await loadMaterials();
  } catch (error) {
    setStatus($("upload-status"), `Could not add the page: ${error.message}`, "error");
  } finally {
    busy(button, false);
  }
});

// Review of recognised text (speech, OCR)

let reviewing = null; // { material, chunks }

function sourceLink(material, locator) {
  // Speech opens at its moment, a PDF page at its page; an image opens whole.
  const n = Number(locator.slice(1));
  const file = `/data/materials/${material.stored_name}`;
  const link = (href, text) => el("a", { href, target: "_blank", rel: "noopener" }, icon("external"), text);
  if (locator.startsWith("t")) return link(`${file}#t=${n}`, `Play from ${clock(n)}`);
  if (material.kind === "pdf") return link(`${file}#page=${n}`, `Page ${n}`);
  return link(file, material.pages > 1 ? `The image (page ${n})` : "The image");
}

async function showReview(material) {
  try {
    const all = await api(`/api/materials/${material.id}/chunks`);
    // Only recognised passages need checking; a PDF's text layer is as the file has it.
    const chunks = all.filter((c) => c.confidence !== null);
    const s = state.settings || {};
    const threshold = ["video", "audio"].includes(material.kind) ? s.review_below : s.ocr_review_below;
    reviewing = { material, chunks };
    $("review-title").textContent = `Check the recognised text: ${material.filename}`;
    fill($("review-list"), ...chunks.map((c) => {
      const low = c.confidence < threshold;
      const text = el("textarea", { rows: "3", "data-id": c.id, "aria-label": `Passage ${c.id}` });
      text.value = c.text;
      return el("li", { class: low || c.uncertain.length ? "low" : "" },
        el("div", { class: "review-meta" }, sourceLink(material, c.locator),
          el("span", { class: "conf", title: `Recognition confidence ${c.confidence.toFixed(2)}` },
            el("span", { class: "meter" }, el("span", { style: `width: ${Math.round(c.confidence * 100)}%` })),
            c.confidence.toFixed(2)),
          low ? el("span", { class: "tag warn" }, "low confidence") : "",
          c.uncertain.length ? el("span", { class: "tag warn" }, `check: ${c.uncertain.join(", ")}`) : ""),
        text);
    }));
    setStatus($("review-status"), "");
    $("review-dialog").showModal();
  } catch (error) {
    toast(`Could not load the text: ${error.message}`, "error");
  }
}

$("review-cancel").addEventListener("click", () => $("review-dialog").close());

$("review-confirm").addEventListener("click", async () => {
  if (!reviewing) return;
  const corrections = {};
  for (const box of document.querySelectorAll("#review-list textarea")) {
    const original = reviewing.chunks.find((c) => c.id === box.dataset.id);
    if (box.value.trim() !== original.text) corrections[box.dataset.id] = box.value;
  }
  busy($("review-confirm"), true);
  try {
    await send(`/api/materials/${reviewing.material.id}/review`, "POST", { corrections });
    toast(`${reviewing.material.filename} is ready to use.`, "ok");
    $("review-dialog").close();
    reviewing = null;
    await loadMaterials();
  } catch (error) {
    setStatus($("review-status"), `Could not save: ${error.message}`, "error");
  } finally {
    busy($("review-confirm"), false);
  }
});

// New session: brief controls

const CONTEXTS = [["commute", "Commute", "bus"], ["exercise", "Exercise", "run"],
  ["revision", "Revision before an exam", "book"], ["desk", "At my desk", "cup"]];
const LEVELS = [["introductory", "Introductory"], ["intermediate", "Intermediate"], ["advanced", "Advanced"]];
const FORMATS = [["narrator", "One narrator", "person", "A single voice explains"],
  ["two_hosts", "Two hosts", "people", "Two voices talk it through"]];
const LABELS = {
  context: Object.fromEntries(CONTEXTS.map(([v, l]) => [v, l])),
  level: Object.fromEntries(LEVELS),
  format: Object.fromEntries(FORMATS.map(([v, l]) => [v, l])),
};

function radioValue(name) {
  const checked = document.querySelector(`input[name="${name}"]:checked`);
  return checked ? checked.value : "";
}

function setRadio(name, value) {
  for (const input of document.querySelectorAll(`input[name="${name}"]`)) input.checked = input.value === String(value);
}

function buildBriefControls() {
  fill($("context-group"), ...CONTEXTS.map(([value, label, name]) => el("label", {},
    el("input", { type: "radio", name: "context", value }), el("span", {}, icon(name), label))));
  fill($("format-group"), ...FORMATS.map(([value, label, name, note]) => el("label", {},
    el("input", { type: "radio", name: "format", value }),
    el("span", { class: "choice" }, icon(name), el("strong", {}, label), el("small", {}, note)))));
  fill($("level-group"), ...LEVELS.map(([value, label]) => el("label", {},
    el("input", { type: "radio", name: "level", value }), el("span", {}, label))));
  setRadio("context", "commute");
  setRadio("format", "narrator");
  setRadio("level", "introductory");
}

function updateMinutes() {
  const input = $("minutes");
  const minutes = Number(input.value);
  const fill = ((minutes - input.min) / (input.max - input.min)) * 100;
  input.style.setProperty("--fill", `${fill}%`);
  $("minutes-out").textContent = `${minutes} min`;
  const wpm = state.settings ? state.settings.words_per_minute : null;
  $("minutes-hint").textContent = wpm ? `About ${Math.round(minutes * wpm).toLocaleString()} words of script` : "";
}

$("minutes").addEventListener("input", updateMinutes);

function readyMaterials() {
  return state.materials.filter((m) => m.status === "ready");
}

function renderPicker() {
  const ready = readyMaterials();
  const ids = new Set(ready.map((m) => m.id));
  for (const id of [...state.picked]) if (!ids.has(id)) state.picked.delete(id);
  if (!state.pickTouched) for (const m of ready) state.picked.add(m.id);
  const picker = $("material-picker");
  if (!ready.length) {
    fill(picker, el("p", { class: "empty-note" }, "No materials are ready yet. ",
      el("a", { href: "#library" }, "Add or check materials in the Library"), "."));
    $("picker-count").textContent = "";
    return;
  }
  fill(picker, ...ready.map((m) => {
    const box = el("input", { type: "checkbox", value: m.id });
    box.checked = state.picked.has(m.id);
    box.addEventListener("change", () => {
      state.pickTouched = true;
      if (box.checked) state.picked.add(m.id);
      else state.picked.delete(m.id);
      $("picker-count").textContent = `${state.picked.size} of ${ready.length} selected`;
    });
    return el("label", { title: `${m.filename} (${sizeText(m)})` }, box,
      el("span", {}, el("span", { class: "tick" }, icon("check")), kindIcon(m.kind), el("span", { class: "name" }, m.filename)));
  }));
  $("picker-count").textContent = `${state.picked.size} of ${ready.length} selected`;
}

function selectedMaterials() {
  return readyMaterials().filter((m) => state.picked.has(m.id)).map((m) => m.id);
}

function applyBrief(brief) {
  $("focus").value = brief.focus;
  $("title").value = brief.title || "";
  $("minutes").value = brief.minutes;
  setRadio("context", brief.context);
  setRadio("level", brief.level);
  setRadio("format", brief.format);
  $("recall").checked = brief.recall_prompts;
  $("notes").value = brief.notes || "";
  state.pickTouched = true;
  state.picked = new Set(brief.material_ids);
  renderPicker();
  updateMinutes();
}

// Mode tabs: describe it, or fill in the form

function setMode(mode) {
  $("tab-chat").setAttribute("aria-selected", String(mode === "chat"));
  $("tab-form").setAttribute("aria-selected", String(mode === "form"));
  $("panel-chat").hidden = mode !== "chat";
  $("panel-form").hidden = mode !== "form";
  store(STORE_KEYS.mode, mode);
}

$("tab-chat").addEventListener("click", () => setMode("chat"));
$("tab-form").addEventListener("click", () => setMode("form"));

// Brief by dialogue (S1): the proposal fills the form, then the usual review step

let chat = [];
let proposal = null;
let thinking = false;

function renderChat() {
  const log = $("chat-log");
  const intro = log.querySelector(".intro");
  fill(log, intro, ...chat.map((t) => el("div", { class: `bubble ${t.role}` }, t.text)));
  if (thinking) log.append(el("div", { class: "bubble assistant typing", "aria-label": "Thinking" }, el("i"), el("i"), el("i")));
  log.scrollTop = log.scrollHeight;
}

$("chat-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const text = $("chat-input").value.trim();
  if (!text || thinking) return;
  chat.push({ role: "user", text });
  thinking = true;
  renderChat();
  $("chat-input").value = "";
  setStatus($("chat-status"), "");
  try {
    const r = await send("/api/elicit", "POST", { messages: chat, material_ids: selectedMaterials() });
    chat.push({ role: "assistant", text: r.reply });
    proposal = r.brief;
    $("chat-use").hidden = !(r.ready && proposal);
    setStatus($("chat-status"), r.ready && proposal ? "Use this brief, or keep talking to change it." : "");
  } catch (error) {
    chat.pop();
    $("chat-input").value = text;
    setStatus($("chat-status"), `Could not reply: ${error.message}`, "error");
  } finally {
    thinking = false;
    renderChat();
  }
});

$("chat-use").addEventListener("click", () => {
  if (!proposal) return;
  activeSuggestion = null;
  applyBrief(proposal);
  openReview();
});

$("chat-reset").addEventListener("click", () => {
  chat = [];
  proposal = null;
  renderChat();
  $("chat-use").hidden = true;
  setStatus($("chat-status"), "");
});

// Review and start

let pendingBrief = null;
let activeSuggestion = null;

function openReview() {
  const materialIds = selectedMaterials();
  const focus = $("focus").value.trim();
  if (!materialIds.length) {
    setStatus($("brief-status"), "Select at least one material first.", "error");
    $("material-picker").scrollIntoView({ behavior: "smooth", block: "center" });
    return;
  }
  if (!focus) {
    setMode("form");
    $("focus").focus();
    setStatus($("brief-status"), "Say what the session should cover.", "error");
    return;
  }
  pendingBrief = {
    focus, title: $("title").value.trim(), minutes: Number($("minutes").value),
    context: radioValue("context"), level: radioValue("level"), format: radioValue("format"),
    recall_prompts: $("recall").checked, notes: $("notes").value.trim(), material_ids: materialIds,
  };
  const names = state.materials.filter((m) => materialIds.includes(m.id)).map((m) => m.filename);
  const wpm = state.settings ? state.settings.words_per_minute : 0;
  const rows = [
    ["Focus", pendingBrief.focus, "focus"],
    ["Materials", names.join(", ")],
    ["Length", `${pendingBrief.minutes} minutes` + (wpm ? ` (about ${Math.round(pendingBrief.minutes * wpm).toLocaleString()} words)` : "")],
    ["Listening", LABELS.context[pendingBrief.context]],
    ["Format", LABELS.format[pendingBrief.format]],
    ["Level", LABELS.level[pendingBrief.level]],
    ["Recall questions", pendingBrief.recall_prompts ? "Yes, at the end" : "No"],
    ["Title", pendingBrief.title || "The Writer chooses one"],
    ["Notes", pendingBrief.notes || "None"],
  ];
  fill($("brief-summary"), ...rows.flatMap(([k, v, cls]) => [el("dt", {}, k), el("dd", { class: cls || null }, v)]));
  $("panel-chat").hidden = true;
  $("panel-form").hidden = true;
  document.querySelector(".mode-tabs").hidden = true;
  $("brief-review").hidden = false;
  setStatus($("brief-status"), "");
  $("brief-review").scrollIntoView({ behavior: "smooth", block: "start" });
}

function closeReview(mode) {
  $("brief-review").hidden = true;
  document.querySelector(".mode-tabs").hidden = false;
  setMode(mode);
}

$("brief-form").addEventListener("submit", (event) => {
  event.preventDefault();
  openReview(); // a suggestion in use stays in use: editing it is part of the outcome
});

$("brief-edit").addEventListener("click", () => closeReview("form"));

$("brief-confirm").addEventListener("click", async () => {
  busy($("brief-confirm"), true);
  try {
    const record = await send("/api/sessions", "POST", pendingBrief);
    if (activeSuggestion) {
      // Whether the suggestion was taken as it was or edited first (spec 13, personalisation).
      await send("/api/suggestions/outcome", "POST", { suggestion: activeSuggestion, brief: pendingBrief }).catch(() => {});
      activeSuggestion = null;
    }
    loadSuggestions().catch(() => {});
    closeReview(stored(STORE_KEYS.mode, "chat"));
    toast("Session started. It takes a few minutes; you can keep working.", "ok");
    await loadSessions();
    location.hash = `#listen/${record.id}`;
  } catch (error) {
    setStatus($("brief-status"), `Could not start: ${error.message}`, "error");
  } finally {
    busy($("brief-confirm"), false);
  }
});

// Suggestions (spec 8.2): ranked, each with its reasons; using one fills in the brief

const SUGGESTION_TAGS = { weak_topics: ["Revise", "warn"], same_as_last: ["Again", "sky"], new_material: ["New", "accent"] };

async function loadSuggestions() {
  const view = await api("/api/suggestions");
  fill($("suggestion-list"), ...view.suggestions.map((s) => {
    const [tag, tone] = SUGGESTION_TAGS[s.kind] || ["Suggested", "accent"];
    return el("article", { class: `suggestion ${s.kind}` },
      el("span", { class: `tag ${tone}` }, tag),
      el("h3", {}, s.title),
      el("ul", {}, s.why.map((w) => el("li", {}, w))),
      el("button", { class: "btn ghost sm", type: "button", onclick: () => {
        applyBrief(s.brief);
        activeSuggestion = s;
        openReview(); // edit there, or go back to change it
      } }, "Use this", icon("arrow")));
  }));
  $("suggestions").hidden = !view.suggestions.length;
  renderLearned(view);
}

// Sessions

const STEPS = [["concepts", "Concepts"], ["write", "Writing"], ["verify", "Checking"], ["edit", "Editing"],
  ["render", "Voicing"]];
const STAGE_STEP = { concepts: 0, write: 1, trim: 1, verify: 2, revise: 2, edit: 3, reverify: 3, render: 4, done: 5 };
let sessionTimer = null;

function sessionTitle(s) {
  return s.brief.title || s.brief.focus;
}

function stepper(s) {
  const at = s.status === "queued" ? -1 : (STAGE_STEP[s.stage] ?? 0);
  return el("ol", { class: "stepper", "aria-hidden": "true" },
    STEPS.map((_, i) => el("li", { class: i < at ? "done" : i === at ? "now" : "" })));
}

function stageText(s) {
  if (s.status === "queued") return "Waiting to start";
  const at = STAGE_STEP[s.stage] ?? 0;
  return at < STEPS.length ? STEPS[at][1] : "Finishing";
}

function elapsed(s) {
  return clock((Date.now() - new Date(s.created_at).getTime()) / 1000);
}

async function loadSessions() {
  const before = new Map(state.sessions.map((s) => [s.id, s.status]));
  state.sessions = await api("/api/sessions");
  renderSessions();
  for (const s of state.sessions) {
    const was = before.get(s.id);
    if (was && was !== s.status && s.status === "done") {
      toast(`Ready to listen: ${sessionTitle(s)}`, "ok", { label: "Listen", run: () => { location.hash = `#listen/${s.id}`; } });
      loadConcepts().catch(() => {});
      loadSuggestions().catch(() => {});
    }
    if (was && was !== s.status && s.status === "failed") toast(`A session failed: ${s.error}`, "error");
  }
  const active = state.sessions.filter((s) => s.status === "queued" || s.status === "running").length;
  $("badge-listen").hidden = !active;
  $("badge-listen").textContent = String(active);
  if (currentView === "listen") showDetail(detail.id, true);
  clearTimeout(sessionTimer);
  if (active) sessionTimer = setTimeout(() => loadSessions().catch(() => {}), POLL_MS);
}

function renderSessions() {
  const list = $("sessions");
  if (!state.sessions.length) {
    fill(list, el("li", { class: "empty" }, icon("listen"), el("strong", {}, "No sessions yet"),
      el("a", { href: "#create" }, "Start your first session")));
    return;
  }
  fill(list, ...state.sessions.map((s) => {
    const active = s.status === "queued" || s.status === "running";
    const meta = [el("span", {}, `${s.brief.minutes} min`), el("span", {}, "/"),
      el("span", {}, LABELS.format[s.brief.format]), el("span", {}, "/"), el("span", {}, ago(s.created_at))];
    if (s.status === "failed") meta.unshift(el("span", { class: "tag bad" }, "Failed"));
    const card = el("button", { type: "button", class: `session-card${player.id === s.id ? " playing" : ""}`,
      "aria-current": String(detail.id === s.id), onclick: () => { location.hash = `#listen/${s.id}`; } },
      el("span", { class: "title" }, sessionTitle(s)), el("span", { class: "meta" }, meta));
    if (active) {
      card.append(stepper(s),
        el("span", { class: "stage-line" }, el("strong", {}, stageText(s)), el("span", {}, elapsed(s))),
        el("span", { class: "log-line" }, (s.log.at(-1) || "").replace(/^\d\d:\d\d:\d\d /, "")));
    }
    return el("li", {}, card);
  }));
}

// Session detail: player with waveform, verification, transcript, questions, quiz, feedback

const detail = { id: null, status: null, refs: null };
const transcripts = new Map(); // session id -> Promise of the timed transcript
const peaks = new Map(); // session id -> Promise of { peaks, duration }

function transcriptOf(id) {
  if (!transcripts.has(id)) {
    const p = api(`/api/sessions/${id}/transcript`);
    p.catch(() => transcripts.delete(id));
    transcripts.set(id, p);
  }
  return transcripts.get(id);
}

function peaksOf(id) {
  // The waveform: the MP3 decoded at a low sample rate, reduced to loudness per slice.
  if (!peaks.has(id)) {
    peaks.set(id, (async () => {
      const Offline = window.OfflineAudioContext || window.webkitOfflineAudioContext;
      const data = await (await fetch(`/data/sessions/${id}/session.mp3`)).arrayBuffer();
      const buffer = await new Offline(1, 1, 8000).decodeAudioData(data);
      const samples = buffer.getChannelData(0);
      const n = 1200;
      const size = Math.max(1, Math.floor(samples.length / n));
      const out = new Float32Array(n);
      let max = 0;
      for (let i = 0; i < n; i += 1) {
        let sum = 0;
        const start = i * size;
        for (let j = start; j < Math.min(start + size, samples.length); j += 1) sum += samples[j] * samples[j];
        out[i] = Math.sqrt(sum / size);
        max = Math.max(max, out[i]);
      }
      for (let i = 0; i < n; i += 1) out[i] = max ? out[i] / max : 0;
      return { peaks: out, duration: buffer.duration };
    })());
  }
  return peaks.get(id);
}

function showDetail(id, refresh = false) {
  const box = $("session-detail");
  if (!id) {
    const first = state.sessions.find((s) => s.status === "done") || state.sessions[0];
    if (first) {
      history.replaceState(null, "", `#listen/${first.id}`);
      id = first.id;
    }
  }
  const s = state.sessions.find((x) => x.id === id);
  $("view-listen").querySelector(".listen-layout").classList.toggle("single", !s);
  if (!s) {
    box.hidden = true;
    detail.id = null;
    return;
  }
  const same = detail.id === id && detail.status === s.status;
  for (const card of document.querySelectorAll(".session-card")) card.setAttribute("aria-current", "false");
  const index = state.sessions.indexOf(s);
  const card = document.querySelectorAll(".session-card")[index];
  if (card) card.setAttribute("aria-current", "true");
  if (same && (s.status === "done" || s.status === "failed")) return;
  if (same && refresh && detail.refs && detail.refs.progress) {
    detail.refs.progress(s);
    return;
  }
  detail.id = id;
  detail.status = s.status;
  box.hidden = false;
  if (s.status === "done") renderDone(box, s);
  else renderProgress(box, s);
  if (!refresh && window.innerWidth <= 1100) box.scrollIntoView({ behavior: "smooth", block: "start" });
}

function heroMeta(s, extra = []) {
  const b = s.brief;
  return el("div", { class: "detail-meta" },
    el("span", { class: "tag" }, icon("history"), new Date(s.created_at).toLocaleString("en",
      { dateStyle: "medium", timeStyle: "short" })),
    el("span", { class: "tag" }, icon(b.format === "two_hosts" ? "people" : "person"), LABELS.format[b.format]),
    el("span", { class: "tag" }, LABELS.context[b.context]),
    el("span", { class: "tag" }, LABELS.level[b.level]),
    b.recall_prompts ? el("span", { class: "tag accent" }, "Recall questions") : "",
    extra);
}

function renderProgress(box, s) {
  let steps = el("ol", { class: "stepper" });
  const label = el("strong");
  const time = el("span");
  const log = el("pre", { class: "log-line", style: "white-space: pre-wrap; max-height: 16rem; overflow: auto" });
  const status = el("p", { class: "status" });
  const update = (x) => {
    const next = stepper(x);
    steps.replaceWith(next);
    steps = next;
    label.textContent = x.status === "failed" ? "Failed" : stageText(x);
    time.textContent = x.status === "failed" ? "" : `${elapsed(x)} so far`;
    log.textContent = x.log.join("\n");
    log.scrollTop = log.scrollHeight;
    setStatus(status, x.status === "failed" ? x.error : "", x.status === "failed" ? "error" : "");
  };
  fill(box, 
    el("section", { class: "detail-hero" },
      el("p", { class: "eyebrow" }, s.status === "failed" ? "Session failed" : "In progress"),
      el("h2", {}, sessionTitle(s)), heroMeta(s),
      steps, el("div", { class: "stage-line", style: "margin-top: .6rem" }, label, time), status),
    el("section", { class: "card" }, el("h2", { class: "card-title" }, icon("list"), "Progress log"), log));
  detail.refs = { progress: (x) => { if (detail.id === x.id) update(x); } };
  update(s);
}

function renderDone(box, s) {
  const id = s.id;
  const playBtn = el("button", { type: "button", class: "big-play", "aria-label": "Play", onclick: () => togglePlay(id) },
    icon(player.id === id && !audio.paused ? "pause" : "play"));
  const canvas = el("canvas", { "aria-hidden": "true" });
  const ticks = el("div", { class: "ticks" });
  const hover = el("span", { class: "hover-time", hidden: true });
  const wave = el("div", { class: "wave-wrap", role: "slider", tabindex: "0", "aria-label": "Position",
    "aria-valuemin": "0", "aria-valuemax": "100", "aria-valuenow": "0" }, canvas, ticks, hover);
  const time = el("span", { class: "time" }, "0:00");
  const chapterNow = el("span", { class: "now-chapter" });
  const speed = el("button", { type: "button", class: "speed", title: "Playback speed", onclick: cycleSpeed }, speedText());
  const refs = { id, canvas, ticks, wave, time, chapterNow, playBtn, speed, peaks: null, duration: 0,
    view: null, sentences: new Map(), chapterButtons: [], current: -1, hoverFrac: null };
  detail.refs = refs;

  const row = el("div", { class: "player-row" },
    el("span", { class: "time" }, time, " ", chapterNow),
    el("button", { type: "button", class: "ctl small", title: "Previous chapter", onclick: () => jumpChapter(id, -1) }, icon("prev")),
    el("button", { type: "button", class: "ctl", title: "Back 15 seconds (J)", onclick: () => skip(id, -15) },
      icon("back"), el("span", { class: "ctl-n" }, "15")),
    el("button", { type: "button", class: "ctl", title: "Forward 30 seconds (L)", onclick: () => skip(id, 30) },
      icon("forward"), el("span", { class: "ctl-n" }, "30")),
    el("button", { type: "button", class: "ctl small", title: "Next chapter", onclick: () => jumpChapter(id, 1) }, icon("next")),
    speed,
    el("a", { class: "ctl small", href: `/data/sessions/${id}/session.mp3`, download: `${id}.mp3`, title: "Download the MP3 (with chapters)" },
      icon("download")),
    el("a", { class: "ctl small", href: `/data/sessions/${id}/transcript.html`, target: "_blank", rel: "noopener",
      title: "Open the transcript as a page" }, icon("external")));
  const title = el("h2", {}, sessionTitle(s));
  const verify = el("section", { class: "card verify-card" }, el("p", { class: "muted small" }, "Loading the check..."));
  const tabsCard = el("section", { class: "card" });
  fill(box, 
    el("section", { class: "detail-hero" },
      el("p", { class: "eyebrow" }, "Session"), title,
      heroMeta(s, [el("span", { class: "tag" }, "AI-generated audio")]),
      el("div", { class: "player" }, playBtn, wave, row)),
    verify, tabsCard);

  bindWave(refs);
  new ResizeObserver(() => drawWave(refs)).observe(wave);
  drawWave(refs);
  peaksOf(id).then((p) => {
    refs.peaks = p.peaks;
    refs.duration = p.duration;
    renderTicks(refs);
    paint(true);
  }).catch(() => { /* no waveform: the bar stays flat */ });

  transcriptOf(id).then((view) => {
    refs.view = view;
    title.textContent = view.title;
    renderTicks(refs);
    buildTabs(tabsCard, s, view, refs);
    paint(true);
  }).catch((error) => {
    fill(tabsCard, el("p", { class: "status error" }, `Could not load the transcript: ${error.message}`));
  });
  api(`/api/sessions/${id}/report`).then((r) => renderVerification(verify, r))
    .catch(() => fill(verify, el("p", { class: "muted small" }, "No verification report for this session.")));
}

// Verification summary

const LABEL_ORDER = [["supported", "Supported"], ["framing_ok", "Fair framing"], ["no_claim", "Connective"],
  ["unsupported", "Unsupported"], ["contradicted", "Contradicted"], ["framing_misleading", "Misleading framing"]];
const PASSING = new Set(["supported", "framing_ok", "no_claim"]);

function labelBar(counts) {
  const total = Object.values(counts).reduce((a, b) => a + b, 0) || 1;
  return el("div", { class: "bar", role: "img",
    "aria-label": LABEL_ORDER.filter(([k]) => counts[k]).map(([k, l]) => `${l} ${counts[k]}`).join(", ") },
    LABEL_ORDER.filter(([k]) => counts[k]).map(([k, l]) =>
      el("span", { class: `l-${k}`, style: `flex-grow: ${counts[k] / total}`, title: `${l}: ${counts[k]}` })));
}

function renderVerification(box, r) {
  const final = r.final || {};
  const first = r.first_pass || {};
  const total = Object.values(final).reduce((a, b) => a + b, 0);
  const passing = Object.entries(final).filter(([k]) => PASSING.has(k)).reduce((a, [, v]) => a + v, 0);
  const failedFirst = Object.entries(first).filter(([k]) => !PASSING.has(k)).reduce((a, [, v]) => a + v, 0);
  const removed = r.events.filter((e) => e.outcome === "dropped").length;
  const drafts = r.draft_words || [];
  const legend = el("div", { class: "legend" }, LABEL_ORDER.filter(([k]) => final[k] || first[k]).map(([k, l]) =>
    el("span", {}, el("i", { class: `l-${k}` }), l)));
  const fact = (value, label) => el("div", { class: "fact" }, el("b", {}, value), el("span", {}, label));
  fill(box, 
    el("div", { class: "verify-head" },
      el("h2", { class: "card-title", style: "margin: 0" }, icon("shield"), "Checked against your materials"),
      el("span", { class: "score" }, total ? `${passing} of ${total}` : "-")),
    el("p", { class: "muted small" }, "Final script, sentence by sentence"),
    labelBar(final),
    Object.keys(first).length ? [el("p", { class: "muted small" }, "First draft, before revision"), labelBar(first)] : "",
    legend,
    el("div", { class: "facts" },
      fact(r.writer_sentences, "sentences written"),
      fact(failedFirst, "failed the first check"),
      fact(r.revise_rounds, plural(r.revise_rounds, "revision round").replace(/^\d+ /, "")),
      fact(removed, "removed"),
      fact(`${r.edits_applied}/${r.edits_applied + r.edits_reverted}`, "fluency edits kept"),
      drafts.length ? fact(`${drafts.at(-1).toLocaleString()}`, `words, target ${r.target_words.toLocaleString()}`) : ""));
}

// Tabs: transcript, questions, quiz, feedback

function buildTabs(card, s, view, refs) {
  const tabs = [
    ["transcript", "Transcript", "text", () => transcriptPanel(view, refs)],
    ["ask", "Ask", "chat", () => askPanel(s.id)],
    ["quiz", "Quiz", "quiz", () => quizPanel(s.id)],
    ["feedback", "How was it?", "star", () => feedbackPanel(s.id)],
  ];
  const bar = el("div", { class: "tabs", role: "tablist" });
  const panels = el("div");
  const made = new Map();
  const select = (key) => {
    for (const button of bar.children) button.setAttribute("aria-selected", String(button.dataset.key === key));
    if (!made.has(key)) {
      const panel = el("div", { role: "tabpanel" }, tabs.find((t) => t[0] === key)[3]());
      made.set(key, panel);
      panels.append(panel);
    }
    for (const [k, panel] of made) panel.hidden = k !== key;
  };
  for (const [key, label, name] of tabs) {
    bar.append(el("button", { type: "button", role: "tab", "data-key": key, onclick: () => select(key) }, icon(name), label));
  }
  fill(card, bar, panels);
  select("transcript");
}

function transcriptPanel(view, refs) {
  const id = refs.id;
  const follow = el("button", { type: "button", class: "linkish", "aria-pressed": String(stored(STORE_KEYS.follow, "1") === "1") },
    icon("follow"), "Follow along");
  follow.addEventListener("click", () => {
    const on = follow.getAttribute("aria-pressed") !== "true";
    follow.setAttribute("aria-pressed", String(on));
    store(STORE_KEYS.follow, on ? "1" : "0");
    follow.style.opacity = on ? "1" : ".55";
  });
  follow.style.opacity = follow.getAttribute("aria-pressed") === "true" ? "1" : ".55";
  refs.follow = follow;
  const chapters = el("ol", { class: "chapters", "aria-label": "Chapters" });
  refs.chapterButtons = view.segments.map((seg, i) => {
    const button = el("button", { type: "button", onclick: () => playSession(id, seg.start_s ?? 0) },
      el("time", {}, clock(seg.start_s ?? 0)), `${i + 1}. ${seg.heading}`);
    chapters.append(el("li", {}, button));
    return button;
  });
  const reader = el("div", { class: "reader" });
  const cite = (s) => s.sources.length ? el("sup", { class: "cite" }, s.sources.map((n) => {
    const src = view.sources[n - 1];
    return el("a", { href: `/data/${src.path}`, target: "_blank", rel: "noopener", title: src.label,
      onclick: (event) => event.stopPropagation() }, String(n));
  })) : "";
  const sentence = (s) => {
    const node = el("span", { class: `sent ${s.kind}${s.unverified ? " unverified" : ""}`,
      title: s.unverified ? "Not verified against your materials" : null,
      onclick: () => { if (s.start_s !== null) playSession(id, s.start_s); } }, s.text, cite(s));
    refs.sentences.set(s.id, node);
    return [node, " "];
  };
  for (const seg of view.segments) {
    reader.append(el("h3", {}, seg.heading));
    if (view.format === "two_hosts") {
      let turn = null;
      let speaker = null;
      for (const s of seg.sentences) {
        if (s.speaker !== speaker || !turn) {
          speaker = s.speaker;
          const letter = speaker.replace(/^Host /, "") || "?";
          turn = el("p");
          reader.append(el("div", { class: `turn ${letter.toLowerCase()}` },
            el("span", { class: "avatar", title: speaker }, letter), turn));
        }
        append(turn, sentence(s));
      }
    } else {
      reader.append(el("p", {}, seg.sentences.map(sentence)));
    }
  }
  refs.flat = view.segments.flatMap((seg) => seg.sentences).filter((s) => s.start_s !== null)
    .sort((a, b) => a.start_s - b.start_s);
  const sources = view.sources.length ? [el("h3", { style: "font-family: var(--sans)" }, "Sources"),
    el("ol", { class: "sources" }, view.sources.map((src) => el("li", {},
      el("a", { href: `/data/${src.path}`, target: "_blank", rel: "noopener" }, src.label))))] : "";
  const hasUnverified = refs.flat.some((s) => s.unverified);
  return [
    el("div", { class: "transcript-tools" },
      el("span", { class: "muted small" }, "Click a sentence to play from there; numbers open its source."), follow),
    chapters, reader,
    hasUnverified ? el("p", { class: "notice" }, icon("alert"), "Wavy underlines mark sentences not verified against your materials.") : "",
    el("div", { class: "reader-sources" }, sources),
  ];
}

// Questions about a finished session (text Q&A)

function renderExchange(x) {
  const numbers = new Map(x.sources.map((s, i) => [s.chunk_id, i + 1]));
  const answer = el("p");
  for (const s of x.sentences) {
    answer.append(el("span", s.verified ? {} : { class: "unverified", title: s.rationale || "Not verified" }, s.text));
    if (s.sources.length) {
      answer.append(el("sup", { class: "cite" }, s.sources.map((cid) => {
        const src = x.sources[numbers.get(cid) - 1];
        return el("a", { href: `/data/${src.path}`, target: "_blank", rel: "noopener", title: src.label }, String(numbers.get(cid)));
      })));
    }
    answer.append(" ");
  }
  return [
    el("div", { class: "qa-q" }, x.question),
    el("div", { class: "qa-a" },
      x.covered ? "" : el("span", { class: "tag warn not-covered" }, "Not covered by your materials"),
      answer,
      x.sources.length ? el("ol", { class: "sources" }, x.sources.map((s) => el("li", {},
        el("a", { href: `/data/${s.path}`, target: "_blank", rel: "noopener" }, s.label)))) : ""),
  ];
}

function askPanel(sessionId) {
  const log = el("div", { class: "qa-log" });
  const empty = el("div", { class: "empty-state" }, icon("chat"),
    el("p", {}, "Ask anything about this session. Answers come only from your materials, and each sentence is checked."));
  const input = el("input", { type: "text", placeholder: "Ask a question about this session", "aria-label": "Your question" });
  const button = el("button", { type: "submit", class: "btn primary icon-only", "aria-label": "Ask" }, icon("send"));
  const status = el("p", { class: "status", role: "status" });
  const form = el("form", { class: "composer" }, input, button);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const question = input.value.trim();
    if (!question) return;
    busy(button, true);
    empty.hidden = true;
    const pending = el("div", { class: "qa-q" }, question);
    const typing = el("div", { class: "bubble assistant typing" }, el("i"), el("i"), el("i"));
    log.append(pending, typing);
    setStatus(status, "Answering and checking against your materials...");
    try {
      const x = await send(`/api/sessions/${sessionId}/questions`, "POST", { question });
      pending.remove();
      typing.remove();
      log.append(...renderExchange(x));
      input.value = "";
      setStatus(status, "");
    } catch (error) {
      pending.remove();
      typing.remove();
      empty.hidden = log.childElementCount > 0;
      setStatus(status, `Could not answer: ${error.message}`, "error");
    } finally {
      busy(button, false);
    }
  });
  api(`/api/sessions/${sessionId}/questions`).then((xs) => {
    log.prepend(...xs.flatMap(renderExchange));
    empty.hidden = xs.length > 0;
  }).catch((error) => setStatus(status, `Could not load earlier questions: ${error.message}`, "error"));
  return [empty, log, form, status];
}

// Quizzes on a finished session

function ring(score, total) {
  const r = 30;
  const length = 2 * Math.PI * r;
  const value = document.createElementNS(SVG_NS, "circle");
  const track = document.createElementNS(SVG_NS, "circle");
  for (const c of [track, value]) {
    c.setAttribute("cx", "36");
    c.setAttribute("cy", "36");
    c.setAttribute("r", String(r));
  }
  track.setAttribute("class", "track");
  value.setAttribute("class", "value");
  value.style.strokeDasharray = String(length);
  value.style.strokeDashoffset = String(length);
  const share = total ? score / total : 0;
  if (share < 0.5) value.style.stroke = "var(--bad)";
  else if (share < 0.8) value.style.stroke = "var(--amber)";
  const svg = document.createElementNS(SVG_NS, "svg");
  svg.setAttribute("viewBox", "0 0 72 72");
  svg.append(track, value);
  requestAnimationFrame(() => requestAnimationFrame(() => { value.style.strokeDashoffset = String(length * (1 - share)); }));
  return el("div", { class: "ring", role: "img", "aria-label": `${score} of ${total} right` }, svg, el("b", {}, `${score}/${total}`));
}

function renderQuiz(sessionId, quiz, scoreBox) {
  const form = el("form");
  const blocks = quiz.questions.map((q, n) => {
    const name = `${quiz.id}-${n}`;
    const options = q.options.map((text, m) => el("label", { class: "opt" },
      el("input", { type: "radio", name, value: String(m) }),
      el("span", { "data-key": String.fromCharCode(65 + m) }, text)));
    const feedback = el("div", { class: "quiz-feedback" });
    form.append(el("fieldset", { class: "quiz-q" },
      el("legend", {}, el("span", { class: "num" }, `${n + 1}.`), q.question), el("div", { class: "opts" }, options), feedback));
    return { name, options, feedback };
  });
  const status = el("p", { class: "status", role: "status" });
  const button = el("button", { type: "submit", class: "btn primary" }, icon("check"), "Check answers");
  form.append(el("div", { class: "form-actions start" }, button, status));
  if (quiz.attempts.length) {
    setStatus(status, `Earlier attempts: ${quiz.attempts.map((a) => a.score).join(", ")} of ${quiz.questions.length}.`);
  }
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const answers = blocks.map((b) => {
      const picked = form.querySelector(`input[name="${b.name}"]:checked`);
      return picked ? Number(picked.value) : null;
    });
    busy(button, true);
    try {
      const r = await send(`/api/sessions/${sessionId}/quizzes/${quiz.id}/attempts`, "POST", { answers });
      r.results.forEach((res, n) => {
        const b = blocks[n];
        b.options.forEach((label, m) => {
          label.classList.toggle("correct", m === res.correct);
          label.classList.toggle("wrong", m === res.chosen && !res.right);
        });
        const verdict = res.right ? "Right." : res.chosen === null ? "Skipped." : "Not quite.";
        fill(b.feedback, 
          el("p", {}, el("span", { class: `verdict ${res.right ? "ok" : "bad"}` }, verdict), " ", res.explanation),
          res.sources.length ? el("ol", { class: "sources" }, res.sources.map((s) => el("li", {},
            el("a", { href: `/data/${s.path}`, target: "_blank", rel: "noopener" }, s.label)))) : "");
      });
      const total = quiz.questions.length;
      fill(scoreBox, ring(r.attempt.score, total),
        el("div", {}, el("strong", {}, r.attempt.score === total ? "All right. Well done." : `${r.attempt.score} of ${total} right`),
          el("p", { class: "muted small" }, "Results go into your concept table. Change answers and check again any time.")));
      scoreBox.hidden = false;
      setStatus(status, "");
      loadConcepts().catch(() => {});
      loadSuggestions().catch(() => {});
    } catch (error) {
      setStatus(status, `Could not check: ${error.message}`, "error");
    } finally {
      busy(button, false);
    }
  });
  return form;
}

function quizPanel(sessionId) {
  const body = el("div");
  const scoreBox = el("div", { class: "score-row", hidden: true, style: "margin-bottom: 1rem" });
  const status = el("p", { class: "status", role: "status" });
  const button = el("button", { type: "button", class: "btn ghost" }, icon("sparkle"), "New quiz");
  const empty = el("div", { class: "empty-state" }, icon("quiz"),
    el("p", {}, "Multiple-choice questions on this session, each checked against your materials."));
  button.addEventListener("click", async () => {
    busy(button, true);
    setStatus(status, "Writing questions and checking them against your materials...");
    try {
      const quiz = await api(`/api/sessions/${sessionId}/quizzes`, { method: "POST" });
      empty.hidden = true;
      scoreBox.hidden = true;
      fill(body, renderQuiz(sessionId, quiz, scoreBox));
      setStatus(status, "");
    } catch (error) {
      setStatus(status, `Could not write a quiz: ${error.message}`, "error");
    } finally {
      busy(button, false);
    }
  });
  api(`/api/sessions/${sessionId}/quizzes`).then((quizzes) => {
    if (!quizzes.length) return;
    empty.hidden = true;
    fill(body, renderQuiz(sessionId, quizzes.at(-1), scoreBox));
  }).catch((error) => setStatus(status, `Could not load quizzes: ${error.message}`, "error"));
  return [el("div", { class: "quiz-head" }, el("p", { class: "muted small" }, "Answers are explained with their sources."), button),
    status, empty, scoreBox, body];
}

// Feedback on a finished session (S11): used by the suggestions

function feedbackPanel(sessionId) {
  const name = `rating-${sessionId}`;
  const stars = el("div", { class: "stars", role: "radiogroup", "aria-label": "Rating" },
    [5, 4, 3, 2, 1].flatMap((n) => {
      const id = `${name}-${n}`;
      return [el("input", { type: "radio", name, value: String(n), id }),
        el("label", { for: id, title: `${n} of 5` }, icon("star"), el("span", { class: "sr" }, `${n} of 5`))];
    }));
  const lengthName = `length-${sessionId}`;
  const length = el("div", { class: "seg" }, [["too_short", "Too short"], ["right", "About right"], ["too_long", "Too long"]]
    .map(([value, label]) => el("label", {}, el("input", { type: "radio", name: lengthName, value }), el("span", {}, label))));
  const comment = el("textarea", { rows: "2", maxlength: "1000", placeholder: "Anything else? (optional)", "aria-label": "Comment" });
  const status = el("span", { class: "status", role: "status" });
  const save = el("button", { type: "submit", class: "btn primary" }, "Save");
  const form = el("form", { class: "feedback-grid" },
    el("div", { class: "field" }, el("span", { class: "label" }, "Rating"), stars),
    el("div", { class: "field" }, el("span", { class: "label" }, "Length"), length),
    el("label", { class: "field" }, el("span", { class: "label" }, "Comment"), comment),
    el("div", { class: "form-actions start" }, save, status));
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const rating = radioValue(name);
    busy(save, true);
    try {
      await send(`/api/sessions/${sessionId}/feedback`, "PUT", {
        rating: rating ? Number(rating) : null, length: radioValue(lengthName) || null, comment: comment.value.trim() });
      setStatus(status, "Saved. Your next suggestions take it into account.", "ok");
      loadSuggestions().catch(() => {});
    } catch (error) {
      setStatus(status, `Not saved: ${error.message}`, "error");
    } finally {
      busy(save, false);
    }
  });
  api(`/api/sessions/${sessionId}/feedback`).then((f) => {
    if (!f) return;
    if (f.rating !== null) setRadio(name, f.rating);
    if (f.length) setRadio(lengthName, f.length);
    comment.value = f.comment;
  }).catch(() => {});
  return [el("p", { class: "muted small", style: "margin-bottom: 1rem" },
    "Tell groundcast how it went; the length and rating shape what it suggests next."), form];
}

// Player: one audio element, a dock that follows you across views, and the detail waveform

const audio = $("audio");
const player = { id: null, view: null, raf: 0, savedAt: 0 };

function speedText() {
  return `${Number(stored(STORE_KEYS.rate, "1"))}x`;
}

function cycleSpeed() {
  const now = Number(stored(STORE_KEYS.rate, "1"));
  const next = SPEEDS[(SPEEDS.indexOf(now) + 1) % SPEEDS.length] || 1;
  store(STORE_KEYS.rate, next);
  audio.playbackRate = next;
  audio.defaultPlaybackRate = next;
  for (const button of [$("dock-speed"), detail.refs && detail.refs.speed].filter(Boolean)) button.textContent = speedText();
}

$("dock-speed").textContent = speedText();
$("dock-speed").addEventListener("click", cycleSpeed);

function savedPosition(id) {
  const value = Number(stored(STORE_KEYS.position + id, "0"));
  return Number.isFinite(value) ? value : 0;
}

function whenReady() {
  return new Promise((resolve) => {
    if (audio.readyState >= 1) resolve();
    else audio.addEventListener("loadedmetadata", resolve, { once: true });
  });
}

async function playSession(id, at = null) {
  const s = state.sessions.find((x) => x.id === id);
  if (player.id !== id) {
    player.id = id;
    player.view = null;
    audio.src = `/data/sessions/${id}/session.mp3`;
    audio.defaultPlaybackRate = Number(stored(STORE_KEYS.rate, "1"));
    $("dock").hidden = false;
    document.documentElement.style.setProperty("--dock-h", `${$("dock").offsetHeight}px`);
    $("dock-title").textContent = s ? sessionTitle(s) : id;
    transcriptOf(id).then((view) => {
      if (player.id !== id) return;
      player.view = view;
      $("dock-title").textContent = view.title;
      renderDockTicks(view);
      if ("mediaSession" in navigator) {
        navigator.mediaSession.metadata = new MediaMetadata({ title: view.title, artist: "groundcast", album: "Study sessions" });
      }
    }).catch(() => {});
    renderSessions();
    await whenReady();
    const resume = at ?? savedPosition(id);
    if (resume > 0 && resume < audio.duration - 5) {
      audio.currentTime = resume;
      if (at === null) toast(`Resumed at ${clock(resume)}.`, "info", { label: "From the start", run: () => { audio.currentTime = 0; } });
    }
  } else if (at !== null) {
    await whenReady();
    audio.currentTime = at;
  }
  audio.playbackRate = Number(stored(STORE_KEYS.rate, "1"));
  try {
    await audio.play();
  } catch (error) {
    if (error.name !== "AbortError") toast(`Could not play: ${error.message}`, "error");
  }
}

function togglePlay(id = player.id) {
  if (!id) return;
  if (player.id !== id) {
    playSession(id);
    return;
  }
  if (audio.paused) audio.play().catch(() => {});
  else audio.pause();
}

function skip(id, seconds) {
  if (player.id !== id) {
    playSession(id);
    return;
  }
  audio.currentTime = Math.max(0, Math.min((audio.duration || 0) - 0.1, audio.currentTime + seconds));
}

function chapterStarts(view) {
  return view ? view.segments.map((seg) => seg.start_s).filter((t) => t !== null) : [];
}

function chapterAt(view, t) {
  if (!view) return -1;
  let index = -1;
  view.segments.forEach((seg, i) => { if (seg.start_s !== null && seg.start_s <= t + 0.05) index = i; });
  return index;
}

async function jumpChapter(id, step) {
  const view = await transcriptOf(id).catch(() => null);
  const starts = chapterStarts(view);
  if (!starts.length) return;
  const t = player.id === id ? audio.currentTime : 0;
  let index = chapterAt(view, t);
  // "Previous" first goes back to the start of the current chapter, as players usually do.
  if (step < 0 && index >= 0 && t - starts[index] > 3) step = 0;
  index = Math.max(0, Math.min(starts.length - 1, index + step));
  playSession(id, starts[index]);
}

function renderDockTicks(view) {
  const bar = $("dock-progress");
  for (const tick of bar.querySelectorAll(".tick")) tick.remove();
  const duration = audio.duration;
  if (!duration || !view) {
    audio.addEventListener("loadedmetadata", () => renderDockTicks(view), { once: true });
    return;
  }
  for (const t of chapterStarts(view).slice(1)) bar.append(el("span", { class: "tick", style: `left: ${(t / duration) * 100}%` }));
}

$("dock-play").addEventListener("click", () => togglePlay());
$("dock-back").addEventListener("click", () => skip(player.id, -15));
$("dock-fwd").addEventListener("click", () => skip(player.id, 30));
$("dock-open").addEventListener("click", () => { if (player.id) location.hash = `#listen/${player.id}`; });
$("dock-close").addEventListener("click", () => {
  if (player.id) store(STORE_KEYS.position + player.id, audio.currentTime);
  audio.pause();
  audio.removeAttribute("src");
  audio.load();
  player.id = null;
  player.view = null;
  $("dock").hidden = true;
  document.documentElement.style.setProperty("--dock-h", "0px");
  renderSessions();
  paint(true);
});
$("dock-progress").addEventListener("click", (event) => {
  const box = event.currentTarget.getBoundingClientRect();
  if (audio.duration) audio.currentTime = ((event.clientX - box.left) / box.width) * audio.duration;
});

function onPlayState() {
  const playing = !audio.paused;
  $("dock").classList.toggle("playing", playing);
  setIcon($("dock-play"), playing ? "pause" : "play");
  $("dock-play").setAttribute("aria-label", playing ? "Pause" : "Play");
  if (detail.refs && detail.refs.playBtn) {
    const mine = detail.refs.id === player.id && playing;
    setIcon(detail.refs.playBtn, mine ? "pause" : "play");
    detail.refs.playBtn.setAttribute("aria-label", mine ? "Pause" : "Play");
  }
  cancelAnimationFrame(player.raf);
  if (playing) {
    const loop = () => {
      paint();
      player.raf = requestAnimationFrame(loop);
    };
    player.raf = requestAnimationFrame(loop);
  } else if (player.id) {
    store(STORE_KEYS.position + player.id, audio.currentTime);
  }
  if ("mediaSession" in navigator) navigator.mediaSession.playbackState = playing ? "playing" : "paused";
}

audio.addEventListener("play", onPlayState);
audio.addEventListener("pause", onPlayState);
audio.addEventListener("timeupdate", () => paint());
audio.addEventListener("ended", () => { if (player.id) store(STORE_KEYS.position + player.id, 0); });
audio.addEventListener("error", () => { if (player.id) toast("Could not load this session's audio.", "error"); });

if ("mediaSession" in navigator) {
  const handlers = {
    play: () => audio.play(), pause: () => audio.pause(),
    seekbackward: () => skip(player.id, -15), seekforward: () => skip(player.id, 30),
    previoustrack: () => player.id && jumpChapter(player.id, -1), nexttrack: () => player.id && jumpChapter(player.id, 1),
  };
  for (const [action, handler] of Object.entries(handlers)) {
    try { navigator.mediaSession.setActionHandler(action, handler); } catch (_) { /* not supported here */ }
  }
}

let lastPaint = { t: -1, id: null };

function paint(force = false) {
  const t = audio.currentTime || 0;
  if (!force && lastPaint.t === t && lastPaint.id === player.id) return;
  lastPaint = { t, id: player.id };
  const duration = audio.duration || 0;
  if (player.id && duration) {
    $("dock-fill").style.width = `${(t / duration) * 100}%`;
    $("dock-time").textContent = `${clock(t)} / ${clock(duration)}`;
    const i = chapterAt(player.view, t);
    $("dock-chapter").textContent = i >= 0 ? `Chapter ${i + 1}: ${player.view.segments[i].heading}` : "";
    if (Math.abs(t - player.savedAt) > 5) {
      player.savedAt = t;
      store(STORE_KEYS.position + player.id, t);
    }
  }
  const refs = detail.refs;
  if (!refs || !refs.canvas) return;
  const mine = refs.id === player.id;
  const d = (mine && duration) || refs.duration;
  const now = mine ? t : 0;
  refs.time.textContent = d ? `${clock(now)} / ${clock(d)}` : clock(now);
  refs.wave.setAttribute("aria-valuenow", String(d ? Math.round((now / d) * 100) : 0));
  refs.wave.setAttribute("aria-valuetext", `${clock(now)} of ${clock(d)}`);
  drawWave(refs, d ? now / d : 0);
  if (refs.view) {
    const ci = chapterAt(refs.view, mine ? now : -1);
    refs.chapterButtons.forEach((b, i) => b.classList.toggle("now", mine && i === ci));
    refs.chapterNow.textContent = mine && ci >= 0 ? refs.view.segments[ci].heading : "";
  }
  if (refs.flat) highlight(refs, mine ? now : -1);
}

function highlight(refs, t) {
  let index = -1;
  let lo = 0;
  let hi = refs.flat.length - 1;
  while (lo <= hi) { // the last sentence starting at or before t
    const mid = (lo + hi) >> 1;
    if (refs.flat[mid].start_s <= t + 0.05) { index = mid; lo = mid + 1; } else hi = mid - 1;
  }
  if (index === refs.current) return;
  refs.current = index;
  refs.flat.forEach((s, i) => {
    const node = refs.sentences.get(s.id);
    if (!node) return;
    node.classList.toggle("now", i === index);
    node.classList.toggle("past", i < index);
  });
  const node = index >= 0 ? refs.sentences.get(refs.flat[index].id) : null;
  if (node && !audio.paused && refs.follow && refs.follow.getAttribute("aria-pressed") === "true") {
    const box = node.getBoundingClientRect();
    const bottom = window.innerHeight - (parseFloat(cssVar("--dock-h")) || 0);
    if (box.top < 80 || box.bottom > bottom - 40) node.scrollIntoView({ behavior: "smooth", block: "center" });
  }
}

function drawWave(refs, progress = null) {
  const canvas = refs.canvas;
  const width = canvas.clientWidth;
  const height = canvas.clientHeight;
  if (!width || !height) return;
  if (progress === null) {
    const mine = refs.id === player.id && audio.duration;
    progress = mine ? audio.currentTime / audio.duration : 0;
  }
  const dpr = window.devicePixelRatio || 1;
  if (canvas.width !== Math.round(width * dpr)) {
    canvas.width = Math.round(width * dpr);
    canvas.height = Math.round(height * dpr);
  }
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, width, height);
  const step = 4;
  const bars = Math.max(20, Math.floor(width / step));
  const source = refs.peaks;
  const played = cssVar("--accent");
  const rest = cssVar("--wave");
  const hover = refs.hoverFrac;
  for (let i = 0; i < bars; i += 1) {
    let value = 0.12;
    if (source) {
      const a = Math.floor((i / bars) * source.length);
      const b = Math.max(a + 1, Math.floor(((i + 1) / bars) * source.length));
      value = 0;
      for (let j = a; j < b; j += 1) value = Math.max(value, source[j]);
      value = 0.08 + 0.92 * Math.pow(value, 0.8);
    }
    const x = i * step;
    const h = Math.max(3, value * height);
    const frac = (i + 0.5) / bars;
    const isPlayed = frac <= progress;
    const isHover = !isPlayed && hover !== null && frac <= hover;
    ctx.fillStyle = isPlayed || isHover ? played : rest;
    ctx.globalAlpha = isHover ? 0.35 : 1;
    const y = (height - h) / 2;
    if (ctx.roundRect) {
      ctx.beginPath();
      ctx.roundRect(x, y, step - 1.5, h, 1.5);
      ctx.fill();
    } else {
      ctx.fillRect(x, y, step - 1.5, h);
    }
  }
  ctx.globalAlpha = 1;
}

function renderTicks(refs) {
  const d = refs.duration || (refs.id === player.id && audio.duration) || 0;
  if (!d || !refs.view) return;
  fill(refs.ticks, ...refs.view.segments.slice(1).filter((seg) => seg.start_s !== null).map((seg) =>
    el("span", { class: "tick", style: `left: ${(seg.start_s / d) * 100}%`, title: seg.heading })));
}

function bindWave(refs) {
  const wave = refs.wave;
  const fraction = (event) => {
    const box = wave.getBoundingClientRect();
    return Math.max(0, Math.min(1, (event.clientX - box.left) / box.width));
  };
  const duration = () => (refs.id === player.id && audio.duration) || refs.duration;
  const hoverLabel = wave.querySelector(".hover-time");
  let dragging = false;
  wave.addEventListener("pointermove", (event) => {
    const f = fraction(event);
    refs.hoverFrac = f;
    const d = duration();
    if (d) {
      const t = f * d;
      const i = chapterAt(refs.view, t);
      hoverLabel.textContent = clock(t) + (i >= 0 ? `  ${refs.view.segments[i].heading}` : "");
      hoverLabel.style.left = `${f * 100}%`;
      hoverLabel.hidden = false;
    }
    if (dragging && refs.id === player.id && audio.duration) audio.currentTime = f * audio.duration;
    drawWave(refs);
  });
  wave.addEventListener("pointerleave", () => {
    refs.hoverFrac = null;
    hoverLabel.hidden = true;
    drawWave(refs);
  });
  wave.addEventListener("pointerdown", (event) => {
    const d = duration();
    if (!d) return;
    dragging = true;
    wave.setPointerCapture(event.pointerId);
    playSession(refs.id, fraction(event) * d);
  });
  wave.addEventListener("pointerup", () => { dragging = false; });
  wave.addEventListener("keydown", (event) => {
    const steps = { ArrowLeft: -5, ArrowRight: 5, PageDown: -30, PageUp: 30 };
    if (event.key in steps) {
      event.preventDefault();
      skip(refs.id, steps[event.key]);
    } else if (event.key === "Home") {
      event.preventDefault();
      playSession(refs.id, 0);
    }
  });
}

// Keyboard shortcuts: K or Space play and pause, J and L skip

document.addEventListener("keydown", (event) => {
  const target = event.target;
  if (event.ctrlKey || event.metaKey || event.altKey || !player.id) return;
  if (target.closest("input, textarea, select, [contenteditable], dialog")) return;
  const key = event.key.toLowerCase();
  if (key === "k" || (key === " " && !target.closest("button, a, [role=slider]"))) {
    event.preventDefault();
    togglePlay();
  } else if (key === "j") {
    skip(player.id, -15);
  } else if (key === "l") {
    skip(player.id, 30);
  }
});

// Concepts and the change log

function mastery(c) {
  return (c.right + 1) / (c.asked + 2); // the same estimate the suggestions use (Laplace)
}

async function conceptAction(path, body) {
  try {
    state.concepts = await send(path, "POST", body);
    renderConcepts();
    if ($("events").open) loadEvents();
  } catch (error) {
    toast(error.message, "error");
  }
}

function renderConcepts() {
  const all = state.concepts;
  const weakBelow = state.settings ? state.settings.weak_mastery : 0.6;
  const quizzed = all.filter((c) => c.asked);
  const weak = quizzed.filter((c) => mastery(c) < weakBelow);
  const average = quizzed.length ? quizzed.reduce((a, c) => a + c.right / c.asked, 0) / quizzed.length : null;
  const stat = (value, label) => el("div", { class: "stat" }, el("b", {}, value), el("span", {}, label));
  fill($("concept-stats"), 
    stat(String(all.length), "concepts found"),
    stat(String(quizzed.length), "quizzed so far"),
    stat(average === null ? "-" : `${Math.round(average * 100)}%`, "answered right, on average"),
    stat(String(weak.length), "need more work"));
  const query = $("concept-search").value.trim().toLowerCase();
  const sort = $("concept-sort").value;
  const shown = all.filter((c) => `${c.name} ${c.description}`.toLowerCase().includes(query));
  shown.sort((a, b) => sort === "name" ? a.name.localeCompare(b.name)
    : sort === "asked" ? b.asked - a.asked || a.name.localeCompare(b.name)
      : (a.asked ? mastery(a) : 2) - (b.asked ? mastery(b) : 2) || a.name.localeCompare(b.name));
  const list = $("concepts");
  if (!shown.length) {
    fill(list, el("li", { class: "empty" }, icon("concepts"),
      el("strong", {}, all.length ? "Nothing matches the filter" : "No concepts yet"),
      all.length ? "" : "They are found when a session first uses a material."));
    return;
  }
  fill(list, ...shown.map((c, i) => {
    const m = mastery(c);
    const level = !c.asked ? "none" : m < weakBelow ? "weak" : m < (1 + weakBelow) / 2 ? "mid" : "good";
    const name = el("div", { class: "concept-name" }, c.name);
    const target = el("select", { "aria-label": `Merge ${c.name} into another concept` },
      el("option", { value: "" }, "Merge into..."),
      all.filter((o) => o.id !== c.id).map((o) => el("option", { value: o.id }, o.name)));
    target.addEventListener("change", async () => {
      const into = all.find((o) => o.id === target.value);
      const ok = into && await ask({ title: `Merge "${c.name}" into "${into.name}"?`, ok: "Merge",
        body: "Its passages and quiz results move there. The change goes into the log." });
      if (ok) conceptAction(`/api/concepts/${c.id}/merge`, { into: into.id });
      else target.value = "";
    });
    const rename = () => {
      const input = el("input", { type: "text", value: c.name, "aria-label": "New name" });
      let finished = false;
      const done = (save) => {
        if (finished) return;
        finished = true;
        const value = input.value.trim();
        if (save && value && value !== c.name) conceptAction(`/api/concepts/${c.id}/rename`, { name: value });
        else fill(name, c.name);
      };
      input.addEventListener("keydown", (event) => {
        if (event.key === "Enter") done(true);
        if (event.key === "Escape") done(false);
      });
      input.addEventListener("blur", () => done(true));
      fill(name, input);
      input.select();
    };
    return el("li", { class: "concept", style: `animation-delay: ${Math.min(i, 16) * 20}ms` },
      el("div", { class: "concept-head" }, name),
      c.description ? el("p", { class: "concept-desc" }, c.description) : "",
      el("span", { class: "faint small" }, `Found in ${plural(c.chunks, "passage")} of ${plural(c.material_ids.length, "material")}`),
      el("div", { class: `mastery ${level}`, title: c.asked ? `Estimated mastery ${Math.round(m * 100)}%` : "" },
        el("span", { class: "meter" }, el("span", { style: `width: ${Math.round(m * 100)}%` })),
        c.asked ? `${c.right} of ${c.asked} right` : "Not quizzed yet"),
      el("div", { class: "concept-actions" },
        el("button", { class: "linkish", type: "button", onclick: rename }, icon("edit"), "Rename"),
        target));
  }));
}

$("concept-search").addEventListener("input", renderConcepts);
$("concept-sort").addEventListener("change", renderConcepts);

async function loadConcepts() {
  state.concepts = await api("/api/concepts");
  renderConcepts();
}

const EVENT_NAMES = {
  "preference.set": "Preference changed", "preference.undone": "Preference change undone",
  "preference.inferred": "Learned from your sessions", "concept.renamed": "Concept renamed",
  "concept.merged": "Concepts merged", "concept.added": "Concept found", "suggestion.accepted": "Suggestion taken",
  "suggestion.edited": "Suggestion edited, then taken", "session.feedback": "Feedback saved", "quiz.answered": "Quiz answered",
  "profile.deleted": "Profile deleted",
};

function compact(value) {
  if (value === null || value === undefined) return "";
  return typeof value === "object" ? JSON.stringify(value).replace(/[{}"]/g, "").replace(/,/g, ", ").replace(/:/g, ": ")
    : String(value);
}

async function loadEvents() {
  const events = await api("/api/events");
  if (!events.length) {
    fill($("event-list"), el("li", { class: "muted" }, "Nothing has changed yet."));
    return;
  }
  fill($("event-list"), ...events.map((e) => {
    const change = [compact(e.before), compact(e.after)].filter(Boolean).join("  ->  ");
    const item = el("li", { class: e.source },
      el("div", {}, el("span", { class: "what" }, EVENT_NAMES[e.kind] || e.kind), " ", el("span", { class: "muted" }, e.subject)),
      change ? el("div", { class: "change" }, change) : "",
      el("div", { class: "when", title: e.at }, `${ago(e.at)} / ${e.source}${e.reason ? ` / ${e.reason}` : ""}`));
    if (e.kind === "preference.set") {
      item.append(el("button", { class: "linkish", type: "button", onclick: async () => {
        try {
          showPreferences(await api(`/api/events/${e.id}/undo`, { method: "POST" }));
          toast("Undone.", "ok");
          await loadEvents();
        } catch (error) {
          toast(error.message, "error");
        }
      } }, icon("history"), "Undo"));
    }
    return item;
  }));
}

$("events").addEventListener("toggle", () => { if ($("events").open) loadEvents().catch(() => {}); });

// What groundcast has learned (inferred preferences)

const LEARNED_LABELS = { minutes: "Length", format: "Format", recall_prompts: "Recall questions",
  context: "Listening context", level: "Level" };

function shown(key, value) {
  if (value === null || value === undefined) return "";
  if (key === "minutes") return `${value} minutes`;
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (LABELS[key]) return LABELS[key][value] || String(value);
  return String(value);
}

function renderLearned(view) {
  const list = $("learned-list");
  const items = (view.inference_on ? view.inferred : []).map((i) => el("li", {},
    el("span", { class: "k" }, LEARNED_LABELS[i.key]),
    el("span", { class: "v" }, shown(i.key, i.value)),
    el("span", { class: "meter", title: `Confidence ${i.confidence.toFixed(2)}` },
      el("span", { style: `width: ${Math.round(i.confidence * 100)}%` })),
    el("span", { class: "muted small" }, `Chosen in ${i.sessions} of ${i.of_sessions} sessions; ` +
      (i.applied ? "used in suggestions" : "not confident enough yet")),
    el("button", { class: "linkish", type: "button", onclick: () => keepLearned(i) }, icon("pin"), "Keep as preference")));
  if (!view.inference_on) items.push(el("li", { class: "note" }, "Learning from your sessions is switched off."));
  else if (!view.inferred.length) items.push(el("li", { class: "note" }, "Nothing yet: it learns from the sessions you start."));
  fill(list, ...items);
  const a = view.acceptance;
  $("acceptance").textContent = a.rate === null ? "" :
    `Suggestions taken without changes: ${a.accepted} of ${a.accepted + a.edited}.`;
}

async function keepLearned(inferred) {
  try {
    showPreferences(await send("/api/preferences", "PUT", { changes: { [inferred.key]: inferred.value } }));
    toast(`Saved as a preference: ${LEARNED_LABELS[inferred.key]}.`, "ok");
    await loadSuggestions();
  } catch (error) {
    toast(error.message, "error");
  }
}

// Preferences

const PREF_KEYS = ["voice", "second_voice", "speed", "adapt_pace", "minutes", "format", "context", "level",
  "quiz_questions", "recall_prompts", "extract_concepts", "infer_preferences"];
const NUMBER_KEYS = new Set(["speed", "minutes", "quiz_questions"]);
const BOOL_KEYS = new Set(["adapt_pace", "recall_prompts", "extract_concepts", "infer_preferences"]);
const SEG_CHOICES = {
  format: FORMATS.map(([v, l]) => [v, l]), context: CONTEXTS.map(([v, l]) => [v, l.replace(" before an exam", "")]),
  level: LEVELS,
};

function prefSeg(key) {
  return document.querySelector(`.seg[data-pref="${key}"]`);
}

function readPref(key) {
  const seg = prefSeg(key);
  const raw = seg ? (seg.querySelector("input:checked") || { value: "" }).value : $(`pref-${key}`).value.trim();
  if (raw === "") return null;
  if (NUMBER_KEYS.has(key)) return Number(raw);
  if (BOOL_KEYS.has(key)) return raw === "true";
  return raw;
}

function showPreferences(view) {
  state.prefs = view;
  const defaults = Object.keys(view.defaults || {}).length ? view.defaults : view.effective;
  for (const key of ["voice", "second_voice"]) {
    fill($(`pref-${key}`), el("option", { value: "" }, `Default (${defaults[key]})`),
      view.voice_choices.map((v) => el("option", { value: v }, v)));
  }
  for (const key of PREF_KEYS) {
    const value = view.preferences[key];
    const seg = prefSeg(key);
    if (seg) {
      const choices = BOOL_KEYS.has(key) ? [["true", "Yes"], ["false", "No"]] : SEG_CHOICES[key];
      const name = `pref-${key}`;
      fill(seg, 
        el("label", {}, el("input", { type: "radio", name, value: "" }),
          el("span", {}, "Default", el("small", {}, `(${shown(key, defaults[key])})`))),
        choices.map(([v, l]) => el("label", {}, el("input", { type: "radio", name, value: v }), el("span", {}, l))));
      setRadio(name, value === null ? "" : String(value));
    } else {
      const input = $(`pref-${key}`);
      input.value = value === null ? "" : String(value);
      if (input.tagName === "INPUT") input.placeholder = `Default (${defaults[key]})`;
    }
  }
  // The brief form starts from the effective defaults; a brief can still change them.
  $("minutes").value = view.effective.minutes;
  setRadio("format", view.effective.format);
  setRadio("context", view.effective.context);
  setRadio("level", view.effective.level);
  $("recall").checked = view.effective.recall_prompts;
  updateMinutes();
}

$("prefs-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const changes = {};
  for (const key of PREF_KEYS) {
    const value = readPref(key);
    if (value !== state.prefs.preferences[key]) changes[key] = value;
  }
  if (!Object.keys(changes).length) {
    setStatus($("prefs-status"), "Nothing changed.");
    return;
  }
  const button = event.target.querySelector("button[type=submit]");
  busy(button, true);
  try {
    showPreferences(await send("/api/preferences", "PUT", { changes }));
    setStatus($("prefs-status"), `Saved: ${Object.keys(changes).map((k) => k.replace(/_/g, " ")).join(", ")}.`, "ok");
    loadSettings().catch(() => {});
    loadSuggestions().catch(() => {});
    if ($("events").open) loadEvents();
  } catch (error) {
    setStatus($("prefs-status"), `Not saved: ${error.message}`, "error");
  } finally {
    busy(button, false);
  }
});

$("profile-delete").addEventListener("click", async () => {
  const ok = await ask({ title: "Delete the whole profile?", ok: "Delete the profile", danger: true,
    body: "Preferences, concepts, quiz results, feedback, and the change log are deleted. This cannot be undone." });
  if (!ok) return;
  try {
    await api("/api/profile", { method: "DELETE" });
    showPreferences(await api("/api/preferences"));
    await Promise.all([loadConcepts(), loadSuggestions(), loadSettings()]);
    if ($("events").open) loadEvents();
    toast("The profile is deleted.", "ok");
  } catch (error) {
    toast(error.message, "error");
  }
});

// System check

const CHECK_ICONS = { ok: "check", warn: "alert", missing: "x", optional: "alert" };

async function loadDoctor() {
  const list = $("doctor-list");
  busy($("doctor-run"), true);
  fill(list, el("li", {}, el("span", { class: "st" }, el("span", { class: "spinner" })),
    el("span", { class: "name" }, "Checking this machine...")));
  try {
    const checks = await api("/api/doctor");
    fill(list, ...checks.map((c) => el("li", { class: c.status },
      el("span", { class: "st", title: c.status }, icon(CHECK_ICONS[c.status] || "alert")),
      el("span", { class: "name" }, c.name),
      c.detail ? el("span", { class: "detail-text" }, c.detail) : "",
      c.fix && c.status !== "ok" ? el("code", {}, c.fix) : "")));
  } catch (error) {
    fill(list, el("li", { class: "missing" }, el("span", { class: "st" }, icon("x")),
      el("span", { class: "name" }, error.status === 404 ? "The system check is not available in this version."
        : `Could not run the check: ${error.message}`)));
  } finally {
    busy($("doctor-run"), false);
  }
}

$("doctor").addEventListener("toggle", () => { if ($("doctor").open && !$("doctor-list").childElementCount) loadDoctor(); });
$("doctor-run").addEventListener("click", loadDoctor);

// Service presence: open pages check in, so the launcher can stop the service once all are closed

const PAGE_ID = (crypto.randomUUID && crypto.randomUUID()) || `${Date.now()}-${Math.random().toString(36).slice(2)}`;
let presenceTimer = null;
let offlineTimer = null;
let stopped = false;

function checkIn(open) {
  const body = JSON.stringify({ page: PAGE_ID, open });
  if (!open && navigator.sendBeacon) {
    navigator.sendBeacon("/api/presence", new Blob([body], { type: "application/json" }));
    return;
  }
  fetch("/api/presence", { method: "POST", headers: { "Content-Type": "application/json" }, body, keepalive: true })
    .catch(() => showOffline());
}

function startPresence() {
  clearInterval(presenceTimer);
  checkIn(true);
  const seconds = state.settings ? state.settings.heartbeat_s : 20;
  presenceTimer = setInterval(() => checkIn(true), seconds * 1000);
}

window.addEventListener("pagehide", () => checkIn(false));
window.addEventListener("pageshow", (event) => { if (event.persisted) startPresence(); });

function stopMedia() {
  // Dropping the source closes the audio stream, which would otherwise hold the service open while it stops.
  if (!player.id) return;
  store(STORE_KEYS.position + player.id, audio.currentTime);
  player.id = null; // first, so the error event of the emptied player is not reported
  audio.pause();
  audio.removeAttribute("src");
  audio.load();
}

function showOffline(title = null, body = null, waiting = true) {
  if (title) $("offline-title").textContent = title;
  if (body) $("offline-body").textContent = body;
  $("offline-wait").hidden = !waiting;
  if (!$("offline").hidden) return;
  $("offline").hidden = false;
  clearInterval(presenceTimer);
  clearTimeout(sessionTimer);
  clearTimeout(materialTimer);
  stopMedia();
  clearInterval(offlineTimer);
  offlineTimer = setInterval(async () => {
    try {
      const r = await fetch("/api/health", { cache: "no-store" });
      if (r.ok) location.reload(); // back: start over with fresh data
    } catch (_) { /* still not running */ }
  }, 3000);
}

$("app-stop").addEventListener("click", async () => {
  const running = state.sessions.filter((s) => s.status === "queued" || s.status === "running").length;
  const ok = await ask({ title: "Quit groundcast?", ok: "Quit", danger: running > 0,
    body: running ? `${plural(running, "session")} still being made will be cut short and marked as failed.`
      : "The window closes and the service stops. Start it again from the groundcast shortcut." });
  if (!ok) return;
  stopMedia();
  checkIn(false);
  try {
    await api("/api/shutdown", { method: "POST" });
    stopped = true;
    showOffline("groundcast has stopped", "You can close this window. To start it again, use the groundcast shortcut "
      + "on your desktop or in the Start menu.", false);
    window.close(); // where the browser allows it; the launcher also closes app windows
  } catch (error) {
    if (!stopped) toast(error.message, "error");
  }
});

// Start

async function init() {
  buildBriefControls();
  applyTheme(stored(STORE_KEYS.theme, "auto"));
  setMode(stored(STORE_KEYS.mode, "chat") === "form" ? "form" : "chat");
  updateMinutes();
  const results = await Promise.allSettled([loadSettings(), loadMaterials(), loadSessions(), loadConcepts(),
    api("/api/preferences").then(showPreferences)]);
  const failed = results.find((r) => r.status === "rejected");
  if (failed) {
    $("settings-line").textContent = `Could not reach the local service: ${failed.reason.message}`;
    toast(`Could not reach the local service: ${failed.reason.message}`, "error");
  }
  if (!failed) startPresence();
  renderConcepts(); // the settings carry the threshold for weak concepts
  await loadSuggestions().catch(() => {}); // after the preferences have set the form's defaults
  route();
}

init();
