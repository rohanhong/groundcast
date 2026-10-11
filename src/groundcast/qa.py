"""S10 text Q&A: answers to the learner's typed questions, from their materials.

Answers are written live, so they cannot go through the revise loop of the
script; instead each sentence is checked by the Verifier and shown with a
warning when it fails (spec section 11a). The Tutor sees the BM25 top-k
passages of the session's materials for the question, plus the last few
exchanges so that follow-up questions make sense; earlier answers are never
sources.
"""

from __future__ import annotations

import secrets
from datetime import datetime

from pydantic import BaseModel, Field

from groundcast.config import Settings
from groundcast.llm import LLMBackend, Role
from groundcast.models import Chunk, Label, Material, Sentence, SentenceKind, SourceLink, utc_now
from groundcast.pipeline.common import format_passages, load_prompt
from groundcast.pipeline.verifier import build_items, verify_items
from groundcast.pipeline.writer import clean_sources
from groundcast.retrieval import BM25Index
from groundcast.storage import Store, read_model, write_model
from groundcast.transcript import source_links

QA_FILE = "qa.json"


class AnswerSentence(BaseModel):
    text: str
    sources: list[str] = Field(default_factory=list)


class TutorAnswer(BaseModel):
    covered: bool = Field(description="Whether the passages answer the question, at least in part")
    sentences: list[AnswerSentence]


class QASentence(BaseModel):
    text: str
    sources: list[str] = Field(default_factory=list)
    verified: bool = True
    label: Label | None = None
    rationale: str = ""


class QAExchange(BaseModel):
    id: str
    question: str
    covered: bool
    sentences: list[QASentence]
    sources: list[SourceLink] = Field(default_factory=list)
    asked_at: datetime = Field(default_factory=utc_now)


class QAHistory(BaseModel):
    exchanges: list[QAExchange] = Field(default_factory=list)


def load_history(store: Store, session_id: str) -> QAHistory:
    path = store.session_dir(session_id) / QA_FILE
    return read_model(path, QAHistory) if path.is_file() else QAHistory()


def save_history(store: Store, session_id: str, history: QAHistory) -> None:
    write_model(store.session_dir(session_id) / QA_FILE, history)


def _answer_text(exchange: QAExchange) -> str:
    return " ".join(s.text for s in exchange.sentences)


def _prompt(question: str, passages: list[Chunk], history: list[QAExchange]) -> str:
    parts = []
    if history:
        turns = [f"Learner: {e.question}\nTutor: {_answer_text(e)}" for e in history]
        parts.append("# Earlier questions (context only, not sources)\n\n" + "\n\n".join(turns))
    parts.append("# Passages\n\n" + (format_passages(passages) or "(no passage matches the question)"))
    parts.append(f"# Question\n\n{question}\n\nAnswer now.")
    return "\n\n".join(parts)


def answer_question(
    backend: LLMBackend,
    roles: dict[str, Role],
    settings: Settings,
    chunks: list[Chunk],
    materials: dict[str, Material],
    question: str,
    history: list[QAExchange],
) -> QAExchange:
    cfg = settings.qa
    recent = history[-cfg.history_turns :] if cfg.history_turns else []
    index = BM25Index(chunks)
    # A follow-up ("and the second one?") is retrieved together with the question it follows.
    query = " ".join([e.question for e in recent[-1:]] + [question])
    passages = index.top_k(query, cfg.top_k)
    prompt = _prompt(question, passages, recent)
    out = backend.complete_structured(roles["tutor"], load_prompt("tutor"), prompt, TutorAnswer)

    valid = {c.id for c in passages}
    sentences = [
        QASentence(text=s.text.strip(), sources=clean_sources(s.sources, valid))
        for s in out.sentences
        if s.text.strip()
    ]
    if cfg.verify and sentences:
        by_id = {c.id: c for c in chunks}
        pairs = []
        previous = f"Learner: {question}"
        for n, s in enumerate(sentences):
            pairs.append((Sentence(id=f"a{n + 1}", text=s.text, kind=SentenceKind.CLAIM, sources=s.sources), previous))
            previous = s.text
        items = build_items(pairs, by_id, index, settings.pipeline.bm25_top_k, settings.pipeline.retrieval_context)
        verdicts = verify_items(backend, roles["verifier"], items, settings.pipeline.verify_batch_size)
        for n, s in enumerate(sentences):
            v = verdicts[f"a{n + 1}"]
            s.verified, s.label, s.rationale = v.passed, v.label, v.rationale

    sources = source_links((cid for s in sentences for cid in s.sources), {c.id: c for c in passages}, materials)
    return QAExchange(
        id=secrets.token_hex(4), question=question, covered=out.covered, sentences=sentences, sources=sources
    )
