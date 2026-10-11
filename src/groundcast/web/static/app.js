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

const UNIT_NAMES = { pptx: "slide", video: "passage", audio: "passage" };
const STATUS_TEXT = {
  processing: "recognising...",
  review: "waiting for your check",
  failed: "failed",
};
let materialTimer = null;

function sizeText(m) {
  const unit = UNIT_NAMES[m.kind] || "page";
  const parts = [`${m.pages} ${unit}${m.pages === 1 ? "" : "s"}`, `${m.words} words`];
  if (m.duration_s) parts.unshift(`${Math.round(m.duration_s / 60)} min`);
  return ` (${m.kind}, ${parts.join(", ")})`;
}

async function loadMaterials() {
  const checked = new Set(selectedMaterials());
  const list = $("materials");
  list.replaceChildren();
  const materials = await api("/api/materials");
  if (!materials.length) {
    list.append(el("li", { class: "muted" }, "No materials yet."));
  }
  for (const m of materials) {
    const ready = m.status === "ready";
    const box = el("input", { type: "checkbox", value: m.id, "data-name": m.filename });
    box.checked = ready && (checked.size === 0 || checked.has(m.id));
    box.disabled = !ready;
    const actions = [];
    if (m.status === "review") {
      actions.push(el("button", { class: "link", type: "button", onclick: () => showReview(m) }, "Check text"));
    } else if (ready) {
      actions.push(el("button", { class: "link", type: "button", onclick: () => showChunks(m) }, "View text"));
    }
    if (m.status === "failed") {
      actions.push(el("button", { class: "link", type: "button", onclick: () => retryMaterial(m) }, "Try again"));
    }
    actions.push(el("a", { href: m.source_url || `/data/materials/${m.stored_name}`, target: "_blank" },
      m.source_url ? "Open page" : "Open file"));
    actions.push(el("button", { class: "link", type: "button", onclick: () => deleteMaterial(m) }, "Remove"));
    const status = ready ? "" : ` ${STATUS_TEXT[m.status]}${m.error ? `: ${m.error}` : ""}`;
    list.append(el("li", {},
      el("label", {}, box, " ", m.filename, el("span", { class: "muted" }, sizeText(m)),
        el("span", { class: `status-${m.status}` }, status)),
      ...actions,
    ));
  }
  // Recognition runs in the background; refresh until it is done.
  clearTimeout(materialTimer);
  if (materials.some((m) => m.status === "processing")) {
    materialTimer = setTimeout(() => loadMaterials().catch(() => {}), POLL_MS);
  }
}

async function retryMaterial(material) {
  await api(`/api/materials/${material.id}/retry`, { method: "POST" });
  await loadMaterials();
}

let reviewing = null; // { material, chunks }

function clockText(seconds) {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = String(seconds % 60).padStart(2, "0");
  return h ? `${h}:${String(m).padStart(2, "0")}:${s}` : `${m}:${s}`;
}

function sourceLink(material, locator) {
  // Speech opens at its moment, a PDF page at its page; an image opens whole.
  const n = Number(locator.slice(1));
  const file = `/data/materials/${material.stored_name}`;
  if (locator.startsWith("t")) return el("a", { href: `${file}#t=${n}`, target: "_blank" }, `Play from ${clockText(n)}`);
  if (material.kind === "pdf") return el("a", { href: `${file}#page=${n}`, target: "_blank" }, `Open page ${n}`);
  return el("a", { href: file, target: "_blank" }, material.pages > 1 ? `Open the image (page ${n})` : "Open the image");
}

async function showReview(material) {
  const [all, settings] = await Promise.all([
    api(`/api/materials/${material.id}/chunks`), api("/api/settings")]);
  // Only recognised passages need checking; a PDF's text layer is as the file has it.
  const chunks = all.filter((c) => c.confidence !== null);
  const threshold = ["video", "audio"].includes(material.kind) ? settings.review_below : settings.ocr_review_below;
  reviewing = { material, chunks };
  $("review-title").textContent = `Check the recognised text: ${material.filename}`;
  $("review-list").replaceChildren(...chunks.map((c) => {
    const low = c.confidence < threshold;
    const text = el("textarea", { rows: "3", "data-id": c.id });
    text.value = c.text;
    return el("li", { class: low || c.uncertain.length ? "low-confidence" : "" },
      sourceLink(material, c.locator),
      low ? el("span", { class: "low" }, ` low confidence (${c.confidence.toFixed(2)})`) : "",
      c.uncertain.length ? el("span", { class: "low" }, ` check: ${c.uncertain.join(", ")}`) : "",
      text);
  }));
  $("review-status").textContent = "";
  $("review-view").hidden = false;
  $("review-view").scrollIntoView({ behavior: "smooth" });
}

$("review-cancel").addEventListener("click", () => { $("review-view").hidden = true; reviewing = null; });

$("review-confirm").addEventListener("click", async () => {
  if (!reviewing) return;
  const corrections = {};
  for (const box of document.querySelectorAll("#review-list textarea")) {
    const original = reviewing.chunks.find((c) => c.id === box.dataset.id);
    if (box.value.trim() !== original.text) corrections[box.dataset.id] = box.value;
  }
  $("review-status").textContent = "Saving...";
  try {
    await api(`/api/materials/${reviewing.material.id}/review`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ corrections }),
    });
    $("review-view").hidden = true;
    reviewing = null;
    await loadMaterials();
  } catch (error) {
    $("review-status").textContent = `Could not save: ${error.message}`;
  }
});

$("url-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const url = $("url-input").value.trim();
  if (!url) return;
  $("upload-status").textContent = "Fetching the page...";
  try {
    const m = await api("/api/materials/url", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ url }),
    });
    $("upload-status").textContent = `Added ${m.filename}. Check the extracted text before using it.`;
    $("url-input").value = "";
    await loadMaterials();
  } catch (error) {
    $("upload-status").textContent = `Could not add the page: ${error.message}`;
  }
});

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
  $("upload-status").textContent = "Uploading and extracting text...";
  try {
    const added = await api("/api/materials", { method: "POST", body: form });
    const waiting = added.filter((m) => m.status !== "ready").length;
    $("upload-status").textContent = `Added ${added.length} file(s). Check the extracted text before using it.` +
      (waiting ? ` Speech recognition runs in the background; check its text when it is done.` : "");
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
  activeSuggestion = null;
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
    if (activeSuggestion) {
      // Whether the suggestion was taken as it was or edited first (spec 13, personalisation).
      await api("/api/suggestions/outcome", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ suggestion: activeSuggestion, brief: pendingBrief }),
      }).catch(() => {});
      activeSuggestion = null;
      loadSuggestions().catch(() => {});
    }
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

// Concepts and the change log

let concepts = [];

async function conceptAction(path, body) {
  try {
    concepts = await api(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    renderConcepts();
    if ($("events").open) loadEvents();
  } catch (error) {
    alert(error.message);
  }
}

function renderConcepts() {
  const list = $("concepts");
  list.replaceChildren();
  if (!concepts.length) {
    list.append(el("li", { class: "muted" }, "No concepts yet. They are found when a session first uses a material."));
  }
  for (const c of concepts) {
    const quiz = c.asked ? `quiz ${c.right} of ${c.asked} right` : "not quizzed yet";
    const target = el("select", {}, el("option", { value: "" }, "Merge into..."),
      ...concepts.filter((o) => o.id !== c.id).map((o) => el("option", { value: o.id }, o.name)));
    target.addEventListener("change", () => {
      const into = concepts.find((o) => o.id === target.value);
      if (into && confirm(`Merge "${c.name}" into "${into.name}"? Its passages and quiz results move there.`)) {
        conceptAction(`/api/concepts/${c.id}/merge`, { into: into.id });
      } else {
        target.value = "";
      }
    });
    list.append(el("li", { class: "concept" },
      el("div", {}, el("strong", {}, c.name), el("span", { class: "muted" }, ` ${c.id} | ${quiz}`)),
      el("div", { class: "muted" }, c.description),
      el("div", { class: "concept-actions" },
        el("button", { class: "link", type: "button", onclick: () => {
          const name = prompt("New name", c.name);
          if (name && name.trim() !== c.name) conceptAction(`/api/concepts/${c.id}/rename`, { name });
        } }, "Rename"),
        target)));
  }
}

async function loadConcepts() {
  concepts = await api("/api/concepts");
  renderConcepts();
}

async function loadEvents() {
  const events = await api("/api/events");
  $("event-list").replaceChildren(...events.map((e) => {
    const change = [e.before, e.after].filter((v) => v !== null).map((v) => JSON.stringify(v)).join(" -> ");
    const item = el("li", {}, el("code", {}, e.at.slice(0, 19).replace("T", " ")), ` ${e.kind} ${e.subject} `,
      el("span", { class: "muted" }, `${change} (${e.source})${e.reason ? `: ${e.reason}` : ""}`));
    if (e.kind === "preference.set") {
      item.append(" ", el("button", { class: "link", type: "button", onclick: async () => {
        try {
          showPreferences(await api(`/api/events/${e.id}/undo`, { method: "POST" }));
          await loadEvents();
        } catch (error) {
          alert(error.message);
        }
      } }, "Undo"));
    }
    return item;
  }));
}

// Suggestions (spec 8.2): ranked, each with its reasons; using one fills the form

let activeSuggestion = null;

const LEARNED_LABELS = { minutes: "Length", format: "Format", recall_prompts: "Recall questions",
  context: "Listening context", level: "Level" };

function learnedValue(key, value) {
  if (key === "minutes") return `${value} minutes`;
  if (key === "recall_prompts") return value ? "yes" : "no";
  if (key === "format") return value === "two_hosts" ? "two hosts" : "one narrator";
  return String(value);
}

async function loadSuggestions() {
  const view = await api("/api/suggestions");
  $("suggestion-list").replaceChildren(...view.suggestions.map((s) => el("li", {},
    el("strong", {}, s.title), " ",
    el("button", { class: "link", type: "button", onclick: () => {
      applyBrief(s.brief);
      activeSuggestion = s;
      $("brief-form").requestSubmit(); // opens the review step; edit there or go back to change it
    } }, "Use this"),
    el("ul", { class: "muted why" }, ...s.why.map((w) => el("li", {}, w))))));
  $("suggestions").hidden = !view.suggestions.length;
  $("learned-list").replaceChildren(...(view.inference_on ? view.inferred : []).map((i) => el("li", {},
    `${LEARNED_LABELS[i.key]}: ${learnedValue(i.key, i.value)} `,
    el("span", { class: "muted" },
      `(chosen in ${i.sessions} of ${i.of_sessions} sessions, confidence ${i.confidence.toFixed(2)}` +
      `${i.applied ? ", used in suggestions" : ", not used yet"}) `),
    el("button", { class: "link", type: "button", onclick: () => keepLearned(i) }, "Keep as preference"))));
  if (!view.inference_on) {
    $("learned-list").append(el("li", { class: "muted" }, "Learning from your sessions is switched off."));
  } else if (!view.inferred.length) {
    $("learned-list").append(el("li", { class: "muted" }, "Nothing yet: it learns from the sessions you start."));
  }
  const a = view.acceptance;
  $("acceptance").textContent = a.rate === null ? "" :
    `Suggestions taken without changes: ${a.accepted} of ${a.accepted + a.edited}.`;
}

async function keepLearned(inferred) {
  showPreferences(await api("/api/preferences", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ changes: { [inferred.key]: inferred.value } }),
  }));
  $("prefs-status").textContent = `Saved: ${inferred.key}.`;
  await loadSuggestions();
}

// Preferences

const PREF_KEYS = ["voice", "second_voice", "speed", "adapt_pace", "minutes", "format", "context", "level",
  "quiz_questions", "recall_prompts", "extract_concepts", "infer_preferences"];
const NUMBER_KEYS = new Set(["speed", "minutes", "quiz_questions"]);
const BOOL_KEYS = new Set(["adapt_pace", "recall_prompts", "extract_concepts", "infer_preferences"]);
let savedPrefs = {};

function showPreferences(view) {
  savedPrefs = view.preferences;
  for (const id of ["pref-voice", "pref-second_voice"]) {
    const key = id.slice(5);
    $(id).replaceChildren(el("option", { value: "" }, `(default: ${view.effective[key]})`),
      ...view.voice_choices.map((v) => el("option", { value: v }, v)));
  }
  for (const key of PREF_KEYS) {
    const input = $(`pref-${key}`);
    const value = view.preferences[key];
    input.value = value === null ? "" : String(value);
    if (input.tagName === "INPUT") input.placeholder = String(view.effective[key]);
  }
  // The brief form starts from the effective defaults; a brief can still change them.
  $("minutes").value = view.effective.minutes;
  $("format").value = view.effective.format;
  $("context").value = view.effective.context;
  $("level").value = view.effective.level;
  $("recall").checked = view.effective.recall_prompts;
  showSettingsLine().catch(() => {});
}

$("prefs-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const changes = {};
  for (const key of PREF_KEYS) {
    const raw = $(`pref-${key}`).value.trim();
    let value = raw === "" ? null : raw;
    if (value !== null && NUMBER_KEYS.has(key)) value = Number(value);
    if (value !== null && BOOL_KEYS.has(key)) value = value === "true";
    if (value !== savedPrefs[key]) changes[key] = value;
  }
  if (!Object.keys(changes).length) {
    $("prefs-status").textContent = "Nothing changed.";
    return;
  }
  try {
    showPreferences(await api("/api/preferences", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ changes }),
    }));
    $("prefs-status").textContent = `Saved: ${Object.keys(changes).join(", ")}.`;
    if ($("events").open) loadEvents();
  } catch (error) {
    $("prefs-status").textContent = `Not saved: ${error.message}`;
  }
});

$("profile-delete").addEventListener("click", async () => {
  if (!confirm("Delete the whole profile: preferences, concepts, quiz results, and the change log?")) return;
  await api("/api/profile", { method: "DELETE" });
  showPreferences(await api("/api/preferences"));
  await loadConcepts();
  if ($("events").open) loadEvents();
});

$("events").addEventListener("toggle", () => { if ($("events").open) loadEvents().catch(() => {}); });

async function showSettingsLine() {
  const s = await api("/api/settings");
  $("settings-line").textContent =
    `LLM: ${s.llm_backend} | voice: ${s.voice} at ${s.speed}x (${s.tts_engine})`;
}

async function init() {
  await Promise.all([loadMaterials(), loadSessions(), loadConcepts(),
    api("/api/preferences").then(showPreferences)]);
  await loadSuggestions().catch(() => {}); // after the preferences have set the form's defaults
}

init().catch((error) => {
  $("settings-line").textContent = `Could not reach the local service: ${error.message}`;
});
