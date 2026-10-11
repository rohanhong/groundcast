"""S1 Elicit: turn a rough request into a session brief through a short dialogue.

The Elicitor sees the conversation so far, the learner's materials (name,
size, and a short outline), and the brief of the last finished session (the
"same as last time" suggestion of spec section 4). Each turn it replies with
at most one question and its best brief so far; after a set number of
questions it must propose. The brief is a proposal: the learner reviews and
confirms it in the form before any session starts, and the form stays usable
without the dialogue. The service is stateless: the client sends the whole
conversation each turn.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field

from groundcast.config import Settings
from groundcast.llm import LLMBackend, Role
from groundcast.models import MAX_MINUTES, MIN_MINUTES, Brief, Chunk, Context, Level, Material, ScriptFormat
from groundcast.pipeline.common import load_prompt


class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    text: str


class BriefProposal(BaseModel):
    title: str = ""
    focus: str = ""
    material_ids: list[str] = Field(default_factory=list)
    minutes: int = 10
    context: Context = "commute"
    level: Level = "introductory"
    format: ScriptFormat = "narrator"
    recall_prompts: bool = False
    notes: str = ""


class ElicitorOutput(BaseModel):
    reply: str = Field(description="What to say to the learner: one question, or the proposal in a sentence or two")
    ready: bool = Field(description="True when the brief is complete enough to propose")
    brief: BriefProposal


class ElicitResult(BaseModel):
    reply: str
    ready: bool
    brief: Brief | None  # None while no material or focus is known
    questions_left: int


def outline(chunks: list[Chunk], max_words: int) -> str:
    """The first sentence of each chunk, in order, within a word budget."""
    parts: list[str] = []
    used = 0
    for c in chunks:
        first = re.split(r"(?<=[.!?])\s", c.text.strip(), maxsplit=1)[0]
        words = first.split()
        if used + len(words) > max_words:
            break
        parts.append(" ".join(words))
        used += len(words)
    return " | ".join(parts)


def _materials_text(materials: list[Material], outlines: dict[str, str], selected: list[str]) -> str:
    lines = []
    for m in materials:
        mark = " (selected in the form)" if m.id in selected else ""
        lines.append(f"- {m.id}: {m.filename}, {m.words} words{mark}\n  Outline: {outlines.get(m.id) or '(empty)'}")
    return "\n".join(lines) or "(no materials yet)"


def _brief_line(brief: Brief) -> str:
    fields = brief.model_dump(exclude={"title"} if not brief.title else set())
    return ", ".join(f"{k}={v}" for k, v in fields.items())


def to_brief(p: BriefProposal, known: set[str], selected: list[str]) -> Brief | None:
    """A valid Brief from the proposal: known materials only, minutes within limits."""
    ids = [m for m in dict.fromkeys(p.material_ids) if m in known] or [m for m in selected if m in known]
    if not ids or not p.focus.strip():
        return None
    return Brief(
        title=p.title.strip(),
        focus=p.focus.strip(),
        material_ids=ids,
        minutes=min(max(p.minutes, MIN_MINUTES), MAX_MINUTES),
        context=p.context,
        level=p.level,
        format=p.format,
        recall_prompts=p.recall_prompts,
        notes=p.notes.strip(),
    )


def elicit(
    backend: LLMBackend,
    role: Role,
    settings: Settings,
    materials: list[Material],
    outlines: dict[str, str],
    messages: list[ChatTurn],
    selected: list[str],
    last_brief: Brief | None,
) -> ElicitResult:
    cfg = settings.elicit
    asked = sum(t.role == "assistant" for t in messages)
    must_propose = asked >= cfg.max_questions
    conversation = "\n\n".join(f"{'Learner' if t.role == 'user' else 'You'}: {t.text}" for t in messages)
    parts = [
        f"# Materials\n\n{_materials_text(materials, outlines, selected)}",
        f"# Last session's brief\n\n{_brief_line(last_brief) if last_brief else '(no earlier session)'}",
        f"# Limits\n\nminutes: {MIN_MINUTES} to {MAX_MINUTES}. "
        f"You have asked {asked} of at most {cfg.max_questions} questions.",
        f"# Conversation\n\n{conversation}",
        "Propose the brief now, with ready set to true." if must_propose else "Reply now.",
    ]
    out = backend.complete_structured(role, load_prompt("elicitor"), "\n\n".join(parts), ElicitorOutput)
    brief = to_brief(out.brief, {m.id for m in materials}, selected)
    ready = brief is not None and (out.ready or must_propose)
    return ElicitResult(
        reply=out.reply.strip(), ready=ready, brief=brief, questions_left=max(0, cfg.max_questions - asked - 1)
    )
