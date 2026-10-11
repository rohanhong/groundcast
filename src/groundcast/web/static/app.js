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
    recall_prompts: $("recall").checked,
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
    ["Recall questions", pendingBrief.recall_prompts ? "Yes, at the end" : "No"],
    ["Notes", pendingBrief.notes || "(none)"],
    ["Materials", names.join(", ")],
  ];
  $("brief-summary").replaceChildren(...rows.flatMap(([k, v]) => [el("dt", {}, k), el("dd", {}, v)]));
  $("brief-form").hidden = true;
  $("brief-review").hidden = false;
  $("brief-status").textContent = "";
});

// Brief by dialogue (S1): the proposal fills the form, then the usual review step

let chat = [];
let proposal = null;

function renderChat() {
  $("chat-log").replaceChildren(...chat.map((t) =>
    el("p", { class: `chat-${t.role}` }, el("strong", {}, t.role === "user" ? "You: " : "groundcast: "), t.text)));
}

function applyBrief(brief) {
  $("focus").value = brief.focus;
  $("title").value = brief.title;
  $("minutes").value = brief.minutes;
  $("context").value = brief.context;
  $("level").value = brief.level;
  $("format").value = brief.format;
  $("recall").checked = brief.recall_prompts;
  $("notes").value = brief.notes;
  for (const box of document.querySelectorAll("#materials input[type=checkbox]")) {
    box.checked = brief.material_ids.includes(box.value);
  }
}

$("chat-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const text = $("chat-input").value.trim();
  if (!text) return;
  chat.push({ role: "user", text });
  renderChat();
  $("chat-input").value = "";
  $("chat-status").textContent = "Thinking...";
  try {
    const r = await api("/api/elicit", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ messages: chat, material_ids: selectedMaterials() }),
    });
    chat.push({ role: "assistant", text: r.reply });
    renderChat();
    proposal = r.brief;
    $("chat-use").hidden = !(r.ready && proposal);
    $("chat-status").textContent = r.ready && proposal ? "Review the proposal, or keep talking to change it." : "";
  } catch (error) {
    chat.pop();
    renderChat();
    $("chat-input").value = text;
    $("chat-status").textContent = `Could not reply: ${error.message}`;
  }
});

$("chat-use").addEventListener("click", () => {
  if (!proposal) return;
  applyBrief(proposal);
  $("brief-form").requestSubmit(); // opens the review step; nothing starts until confirmed
});

$("chat-reset").addEventListener("click", () => {
  chat = [];
  proposal = null;
  renderChat();
  $("chat-use").hidden = true;
  $("chat-status").textContent = "";
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

// Questions about a finished session (text Q&A)

const qaPanels = new Map(); // session id -> panel, kept across list refreshes

function renderExchange(x) {
  const numbers = new Map(x.sources.map((s, i) => [s.chunk_id, i + 1]));
  const answer = el("p", { class: "qa-answer" });
  if (!x.covered) answer.append(el("span", { class: "muted" }, "Not covered by your materials. "));
  for (const s of x.sentences) {
    const span = el("span", s.verified ? {} : { class: "unverified", title: s.rationale }, s.text);
    answer.append(span);
    for (const cid of s.sources) {
      answer.append(el("sup", {}, el("a", { href: `#${x.id}-${numbers.get(cid)}` }, `${numbers.get(cid)}`)));
    }
    answer.append(" ");
  }
  const sources = el("ol", { class: "qa-sources muted" },
    ...x.sources.map((s, i) => el("li", { id: `${x.id}-${i + 1}` },
      el("a", { href: `/data/${s.path}`, target: "_blank" }, s.label))));
  return el("div", { class: "qa-exchange" }, el("p", { class: "qa-question" }, x.question), answer, sources);
}

function qaPanel(sessionId) {
  if (qaPanels.has(sessionId)) return qaPanels.get(sessionId);
  const log = el("div", { class: "qa-log" });
  const input = el("input", { type: "text", placeholder: "Ask about this session; answers come from your materials" });
  const status = el("p", { class: "muted", role: "status" });
  const button = el("button", { type: "submit" }, "Ask");
  const form = el("form", { class: "qa-form" }, input, button);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const question = input.value.trim();
    if (!question) return;
    button.disabled = true;
    status.textContent = "Answering and checking against your materials...";
    try {
      const x = await api(`/api/sessions/${sessionId}/questions`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question }),
      });
      log.append(renderExchange(x));
      input.value = "";
      status.textContent = "";
    } catch (error) {
      status.textContent = `Could not answer: ${error.message}`;
    } finally {
      button.disabled = false;
    }
  });
  const panel = el("details", { class: "qa" }, el("summary", {}, "Questions"), log, form, status);
  panel.addEventListener("toggle", () => {
    if (!panel.open || panel.dataset.loaded) return;
    panel.dataset.loaded = "1";
    api(`/api/sessions/${sessionId}/questions`)
      .then((xs) => log.prepend(...xs.map(renderExchange)))
      .catch((error) => { status.textContent = `Could not load earlier questions: ${error.message}`; });
  });
  qaPanels.set(sessionId, panel);
  return panel;
}

// Quizzes on a finished session

const quizPanels = new Map(); // session id -> panel, kept across list refreshes

function sourceList(sources) {
  return el("ol", { class: "qa-sources muted" },
    ...sources.map((s) => el("li", {}, el("a", { href: `/data/${s.path}`, target: "_blank" }, s.label))));
}

function renderQuiz(sessionId, quiz) {
  const form = el("form", { class: "quiz-form" });
  const blocks = quiz.questions.map((q, n) => {
    const name = `${quiz.id}-${n}`;
    const options = q.options.map((text, m) =>
      el("label", { class: "quiz-option" }, el("input", { type: "radio", name, value: String(m) }), ` ${text}`));
    const feedback = el("div", { class: "quiz-feedback" });
    const block = el("fieldset", { class: "quiz-question" },
      el("legend", {}, `${n + 1}. ${q.question}`), ...options, feedback);
    form.append(block);
    return { name, options, feedback };
  });
  const status = el("p", { class: "muted", role: "status" });
  const last = quiz.attempts.at(-1);
  if (last) {
    const scores = quiz.attempts.map((a) => a.score).join(", ");
    status.textContent = `Earlier attempts: ${scores} of ${quiz.questions.length}.`;
  }
  const button = el("button", { type: "submit" }, "Check answers");
  form.append(button, status);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const answers = blocks.map((b) => {
      const picked = form.querySelector(`input[name="${b.name}"]:checked`);
      return picked ? Number(picked.value) : null;
    });
    button.disabled = true;
    try {
      const r = await api(`/api/sessions/${sessionId}/quizzes/${quiz.id}/attempts`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ answers }),
      });
      r.results.forEach((res, n) => {
        const b = blocks[n];
        b.options.forEach((label, m) => {
          label.classList.toggle("correct", m === res.correct);
          label.classList.toggle("wrong", m === res.chosen && !res.right);
        });
        b.feedback.replaceChildren(
          el("p", { class: res.right ? "status-done" : "status-failed" },
            res.right ? "Right. " : res.chosen === null ? "Skipped. " : "Not quite. ", res.explanation),
          sourceList(res.sources));
      });
      status.textContent =
        `Score: ${r.attempt.score} of ${quiz.questions.length}. Change answers and check again any time.`;
    } catch (error) {
      status.textContent = `Could not check: ${error.message}`;
    } finally {
      button.disabled = false;
    }
  });
  return form;
}

function quizPanel(sessionId) {
  if (quizPanels.has(sessionId)) return quizPanels.get(sessionId);
  const body = el("div");
  const status = el("p", { class: "muted", role: "status" });
  const button = el("button", { type: "button", class: "secondary" }, "New quiz");
  button.addEventListener("click", async () => {
    button.disabled = true;
    status.textContent = "Writing questions and checking them against your materials...";
    try {
      const quiz = await api(`/api/sessions/${sessionId}/quizzes`, { method: "POST" });
      body.replaceChildren(renderQuiz(sessionId, quiz));
      status.textContent = "";
    } catch (error) {
      status.textContent = `Could not write a quiz: ${error.message}`;
    } finally {
      button.disabled = false;
    }
  });
  const panel = el("details", { class: "qa" }, el("summary", {}, "Quiz"), body, button, status);
  panel.addEventListener("toggle", () => {
    if (!panel.open || panel.dataset.loaded) return;
    panel.dataset.loaded = "1";
    api(`/api/sessions/${sessionId}/quizzes`)
      .then((quizzes) => { if (quizzes.length) body.replaceChildren(renderQuiz(sessionId, quizzes.at(-1))); })
      .catch((error) => { status.textContent = `Could not load quizzes: ${error.message}`; });
  });
  quizPanels.set(sessionId, panel);
  return panel;
}

// Sessions

function reportLine(report) {
  const first = report.first_pass || {};
  const final = report.final || {};
  const failedFirst = (first.unsupported || 0) + (first.contradicted || 0) + (first.framing_misleading || 0);
  const removed = report.events.filter((e) => e.outcome === "dropped").length;
  const drafts = report.draft_words || [];
  const length = drafts.length
    ? `Length: ${drafts.join(" then ")} words for a ${report.target_words}-word target. `
    : "";
  return length + `Verifier: ${report.writer_sentences} sentences written, ${failedFirst} failed the first check, ` +
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
      item.append(reportBox, qaPanel(s.id), quizPanel(s.id));
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
