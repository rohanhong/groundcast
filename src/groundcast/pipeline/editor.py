"""Edit: fluency and vividness, with no new factual claims."""

from __future__ import annotations

from pydantic import BaseModel, Field

from groundcast.llm import LLMBackend, Role
from groundcast.models import Script
from groundcast.pipeline.common import load_prompt


class SentenceEdit(BaseModel):
    sentence_id: str
    text: str


class HeadingEdit(BaseModel):
    segment_id: str
    heading: str


class Edits(BaseModel):
    sentences: list[SentenceEdit] = Field(default_factory=list)
    headings: list[HeadingEdit] = Field(default_factory=list)


def _script_text(script: Script) -> str:
    lines = [f"Title: {script.title}", ""]
    for seg in script.segments:
        lines.append(f"[{seg.id}] Heading: {seg.heading}")
        lines.extend(f"  {s.id}: {s.line()}" for s in seg.sentences)
        lines.append("")
    return "\n".join(lines)


def edit_script(backend: LLMBackend, role: Role, script: Script) -> Edits:
    prompt = "# Script\n\n" + _script_text(script) + "\nReturn your edits."
    return backend.complete_structured(role, load_prompt("editor"), prompt, Edits)
