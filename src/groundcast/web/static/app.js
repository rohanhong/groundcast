"use strict";

const $ = (id) => document.getElementById(id);
const POLL_MS = 3000;
let pollTimer = null;
let pendingBrief = null;

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (key === "class") node.className = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value);
  }
  for (const child of children) {
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

async function api(path, options = {}) {
  const response = await fetch(path, options);
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch (_) { /* keep statusText */ }
    throw new Error(detail);
  }
  return response.json();
}

// Materials

async function loadMaterials() {
  const checked = new Set(selectedMaterials());
  const list = $("materials");
  list.replaceChildren();
  const materials = await api("/api/materials");
  if (!materials.length) {
    list.append(el("li", { class: "muted" }, "No materials yet."));
  }
  for (const m of materials) {
    const box = el("input", { type: "checkbox", value: m.id, "data-name": m.filename });
    box.checked = checked.size === 0 || checked.has(m.id);
    list.append(el("li", {},
      el("label", {}, box, " ", m.filename,
        el("span", { class: "muted" }, ` (${m.pages} page${m.pages === 1 ? "" : "s"}, ${m.words} words)`)),
      el("button", { class: "link", type: "button", onclick: () => showChunks(m) }, "View text"),
      el("a", { href: `/data/materials/${m.stored_name}`, target: "_blank" }, "Open file"),
      el("button", { class: "link", type: "button", onclick: () => deleteMaterial(m) }, "Remove"),
    ));
  }
}

function selectedMaterials() {
  return [...document.querySelectorAll("#materials input[type=checkbox]:checked")].map((b) => b.value);
}

async function showChunks(material) {
  const chunks = await api(`/api/materials/${material.id}/chunks`);
  $("chunk-title").textContent = `Extracted text: ${material.filename} (${chunks.length} chunks)`;
  $("chunk-list").replaceChildren(...chunks.map((c) => el("li", {}, el("code", {}, c.id), " ", c.text)));
  $("chunk-view").hidden = false;
  $("chunk-view").open = true;
}

async function deleteMaterial(material) {
  if (!confirm(`Remove ${material.filename} from the data directory?`)) return;
  await api(`/api/materials/${material.id}`, { method: "DELETE" });
  $("chunk-view").hidden = true;
  await loadMaterials();
}

$("upload-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const files = $("upload-input").files;
  if (!files.length) return;
  const form = new FormData();
  for (const file of files) form.append("files", file);
  $("upload-status").textContent = "Extracting text...";
  try {
    const added = await api("/api/materials", { method: "POST", body: form });
    $("upload-status").textContent = `Added ${added.length} file(s). Check the extracted text before using it.`;
    $("upload-input").value = "";
    await loadMaterials();
  } catch (error) {
    $("upload-status").textContent = `Upload failed: ${error.message}`;
  }
});

// Brief

$("brief-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const materialIds = selectedMaterials();
  if (!materialIds.length) {
    $("brief-status").textContent = "Select at least one material first.";
    return;
  }
  pendingBrief = {
    focus: $("focus").value.trim(),
    title: $("title").value.trim(),
    minutes: Number($("minutes").value),
    context: $("context").value,
    level: $("level").value,
    format: $("format").value,
    notes: $("notes").value.trim(),
    material_ids: materialIds,
  };
  const names = [...document.querySelectorAll("#materials input[type=checkbox]:checked")]
    .map((b) => b.dataset.name);
  const rows = [
    ["Focus", pendingBrief.focus],
    ["Title", pendingBrief.title || "(the Writer chooses)"],
    ["Length", `${pendingBrief.minutes} minutes`],
    ["Context", $("context").selectedOptions[0].textContent],
    ["Level", $("level").selectedOptions[0].textContent],
    ["Format", $("format").selectedOptions[0].textContent],
    ["Notes", pendingBrief.notes || "(none)"],
    ["Materials", names.join(", ")],
  ];
  $("brief-summary").replaceChildren(...rows.flatMap(([k, v]) => [el("dt", {}, k), el("dd", {}, v)]));
  $("brief-form").hidden = true;
  $("brief-review").hidden = false;
  $("brief-status").textContent = "";
});

$("brief-edit").addEventListener("click", () => {
  $("brief-review").hidden = true;
  $("brief-form").hidden = false;
});

$("brief-confirm").addEventListener("click", async () => {
  $("brief-confirm").disabled = true;
  try {
    await api("/api/sessions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(pendingBrief),
    });
    $("brief-status").textContent = "Session started. Progress appears below.";
    $("brief-review").hidden = true;
    $("brief-form").hidden = false;
    await loadSessions();
  } catch (error) {
    $("brief-status").textContent = `Could not start: ${error.message}`;
  } finally {
    $("brief-confirm").disabled = false;
  }
});

// Sessions

function reportLine(report) {
  const first = report.first_pass || {};
  const final = report.final || {};
  const failedFirst = (first.unsupported || 0) + (first.contradicted || 0) + (first.framing_misleading || 0);
  const removed = report.events.filter((e) => e.outcome === "dropped").length;
  return `Verifier: ${report.writer_sentences} sentences written, ${failedFirst} failed the first check, ` +
    `${report.revise_rounds} revision round(s), ${removed} removed, ` +
    `${report.edits_applied} edits kept, ${report.edits_reverted} edits reverted. ` +
    `Final: ${Object.entries(final).map(([k, v]) => `${k} ${v}`).join(", ")}.`;
}

async function loadSessions() {
  const sessions = await api("/api/sessions");
  const list = $("sessions");
  list.replaceChildren();
  if (!sessions.length) list.append(el("li", { class: "muted" }, "No sessions yet."));
  let active = false;
  for (const s of sessions) {
    const title = s.brief.title || s.brief.focus;
    const item = el("li", {},
      el("div", {}, el("strong", {}, title), " ",
        el("span", { class: `status-${s.status}` }, s.status),
        el("span", { class: "muted" }, ` ${s.brief.minutes} min, ${s.id}`)),
    );
    if (s.status === "queued" || s.status === "running") {
      active = true;
      item.append(el("pre", { class: "log" }, s.log.slice(-6).join("\n")));
    }
    if (s.status === "failed") item.append(el("div", { class: "status-failed" }, s.error));
    if (s.status === "done") {
      const base = `/data/sessions/${s.id}`;
      item.append(
        el("audio", { controls: "", preload: "none", src: `${base}/session.mp3` }),
        el("div", {},
          el("a", { href: `${base}/transcript.html`, target: "_blank" }, "Transcript"), " | ",
          el("a", { href: `${base}/session.mp3`, download: `${s.id}.mp3` }, "Download MP3")),
      );
      const reportBox = el("div", { class: "muted" });
      item.append(reportBox);
      api(`/api/sessions/${s.id}/report`).then((r) => { reportBox.textContent = reportLine(r); }).catch(() => {});
    }
    list.append(item);
  }
  clearTimeout(pollTimer);
  if (active) pollTimer = setTimeout(loadSessions, POLL_MS);
}

async function init() {
  const s = await api("/api/settings");
  $("settings-line").textContent =
    `LLM: ${s.llm_backend} | voice: ${s.voice} at ${s.speed}x (${s.tts_engine})`;
  await Promise.all([loadMaterials(), loadSessions()]);
}

init().catch((error) => {
  $("settings-line").textContent = `Could not reach the local service: ${error.message}`;
});
