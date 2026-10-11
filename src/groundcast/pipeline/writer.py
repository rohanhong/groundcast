"""S3 Write and S5 Revise."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from groundcast.llm import LLMBackend, Role
from groundcast.models import (
    Brief,
    Chunk,
    Script,
    ScriptFormat,
    Segment,
    Sentence,
    SentenceKind,
    Speaker,
    Verdict,
    speaker_label,
)
from groundcast.pipeline.common import format_passages, load_prompt
from groundcast.retrieval import BM25Index


class DraftSentence(BaseModel):
    text: str
    kind: SentenceKind
    sources: list[str] = Field(default_factory=list)
    speaker: Speaker = "A"


class DraftSegment(BaseModel):
    heading: str
    sentences: list[DraftSentence]


class Draft(BaseModel):
    title: str
    segments: list[DraftSegment]


class Revision(BaseModel):
    sentence_id: str
    action: Literal["replace", "drop"]
    text: str = ""
    kind: SentenceKind = SentenceKind.CLAIM
    sources: list[str] = Field(default_factory=list)


class Revisions(BaseModel):
    revisions: list[Revision]


def select_sources(chunks: list[Chunk], index: BM25Index, query: str, max_words: int) -> list[Chunk]:
    """All chunks when they fit the budget; otherwise the best BM25 matches, in document order."""
    if sum(len(c.text.split()) for c in chunks) <= max_words:
        return chunks
    ranked = sorted(zip(index.scores(query), range(len(chunks))), key=lambda p: (-p[0], p[1]))
    keep: set[int] = set()
    used = 0
    for _, i in ranked:
        words = len(chunks[i].text.split())
        if used + words > max_words:
            continue
        keep.add(i)
        used += words
    return [c for i, c in enumerate(chunks) if i in keep]


def _brief_text(brief: Brief, target_words: int) -> str:
    lines = [
        f"Focus: {brief.focus}",
        f"Listening context: {brief.context}",
        f"Listener level: {brief.level}",
        "Format: " + ("two hosts, A and B, in conversation" if brief.format == "two_hosts" else "one narrator"),
        f"Length: about {brief.minutes} minutes, so about {target_words} spoken words in total",
    ]
    if brief.title:
        lines.insert(0, f"Working title: {brief.title}")
    if brief.notes:
        lines.append(f"Notes from the listener: {brief.notes}")
    return "\n".join(lines)


def clean_sources(sources: list[str], valid: set[str]) -> list[str]:
    seen: list[str] = []
    for s in sources:
        s = s.strip().strip("[]")
        if s in valid and s not in seen:
            seen.append(s)
    return seen


def draft_to_script(draft: Draft, valid: set[str], script_format: ScriptFormat = "narrator") -> Script:
    two_hosts = script_format == "two_hosts"
    segments = []
    for g, dseg in enumerate(draft.segments, start=1):
        sentences = [
            Sentence(
                id=f"s{g}.{n}",
                text=ds.text.strip(),
                kind=ds.kind,
                sources=clean_sources(ds.sources, valid),
                speaker=ds.speaker if two_hosts else None,
            )
            for n, ds in enumerate(dseg.sentences, start=1)
            if ds.text.strip()
        ]
        if sentences:
            segments.append(Segment(id=f"g{g}", heading=dseg.heading.strip(), sentences=sentences))
    return Script(title=draft.title.strip(), segments=segments, format=script_format)


def write_script(
    backend: LLMBackend, role: Role, brief: Brief, sources: list[Chunk], words_per_minute: int
) -> Draft:
    target_words = brief.minutes * words_per_minute
    prompt = (
        "# Session brief\n\n"
        f"{_brief_text(brief, target_words)}\n\n"
        "# Passages\n\n"
        f"{format_passages(sources)}\n\n"
        "Write the script now."
    )
    system = load_prompt("writer")
    if brief.format == "two_hosts":
        system += "\n\n" + load_prompt("dialogue")
    return backend.complete_structured(role, system, prompt, Draft)


def revise_sentences(
    backend: LLMBackend,
    role: Role,
    failed: list[tuple[Sentence, str, Verdict, list[Chunk]]],
) -> Revisions:
    """failed: (sentence, previous sentence text, verdict, passages) per failed sentence."""
    pool: dict[str, Chunk] = {}
    items = []
    for sentence, context, verdict, passages in failed:
        for c in passages:
            pool.setdefault(c.id, c)
        speaker = f"speaker: {speaker_label(sentence.speaker)}\n" if sentence.speaker else ""
        items.append(
            f"sentence_id: {sentence.id}\n"
            f"{speaker}"
            f"previous sentence: {context or '(none)'}\n"
            f"sentence: {sentence.text}\n"
            f"label: {verdict.label.value}\n"
            f"reason: {verdict.rationale}\n"
            f"passages: {', '.join(c.id for c in passages) or '(none)'}"
        )
    prompt = (
        "# Passages\n\n"
        f"{format_passages(pool.values())}\n\n"
        "# Failed sentences\n\n" + "\n\n".join(items) + "\n\nReturn one revision per failed sentence."
    )
    return backend.complete_structured(role, load_prompt("reviser"), prompt, Revisions)
