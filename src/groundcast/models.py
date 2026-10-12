"""Typed records passed between pipeline stages and stored in the data directory."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


MaterialKind = Literal["pdf", "markdown", "text", "pptx", "docx", "html", "video", "audio", "image"]
# processing: text is being extracted in the background (speech recognition);
# review: the extracted text waits for the user to check and confirm it;
# ready: usable in sessions; failed: extraction stopped with an error.
MaterialStatus = Literal["processing", "review", "ready", "failed"]


class Material(BaseModel):
    id: str  # hash prefix, the first part of every chunk ID
    sha256: str
    filename: str
    kind: MaterialKind
    stored_name: str  # file name inside <data>/materials/
    pages: int  # pages, slides, or transcript passages
    words: int
    added_at: datetime = Field(default_factory=utc_now)
    # Web pages: where the page came from and when it was fetched.
    source_url: str = ""
    fetched_at: datetime | None = None
    duration_s: float | None = None  # video and audio
    # PDF pages whose text was recognised from the page image (no usable text layer).
    ocr_pages: list[int] = Field(default_factory=list)
    status: MaterialStatus = "ready"
    error: str = ""
    reviewed_at: datetime | None = None
    # Process extracting the text while status is processing.
    pid: int | None = None


class Chunk(BaseModel):
    id: str  # <material hash prefix>:<locator>:<index>
    material_id: str
    locator: str  # p<page>, s<slide>, or t<start second>
    index: int
    text: str
    # Recognised text only (speech or OCR): mean word confidence, 0 to 1, and
    # the words recognised with low confidence, for the review step.
    confidence: float | None = None
    uncertain: list[str] = Field(default_factory=list)
    edited: bool = False  # corrected by the user during review


MIN_MINUTES, MAX_MINUTES = 2, 60
Context = Literal["desk", "commute", "exercise", "revision"]
Level = Literal["introductory", "intermediate", "advanced"]
Speaker = Literal["A", "B"]
ScriptFormat = Literal["narrator", "two_hosts"]


def speaker_label(speaker: str) -> str:
    return f"Host {speaker}"


class SourceLink(BaseModel):
    """A cited chunk as shown in the web app: a label and a path to open it."""

    chunk_id: str
    label: str  # file name and locator
    path: str  # relative to the data directory: the file at its page or moment, or its text view


class Brief(BaseModel):
    """Session brief, from the form or the brief dialogue."""

    title: str = ""
    focus: str = Field(description="What the session should cover, in the user's words")
    material_ids: list[str]
    minutes: int = Field(default=10, ge=MIN_MINUTES, le=MAX_MINUTES)
    context: Context = "commute"
    level: Level = "introductory"
    format: ScriptFormat = Field(default="narrator", description="One narrator, or two hosts in conversation")
    recall_prompts: bool = Field(default=False, description="End with recall questions, each followed by a pause")
    notes: str = ""


class SentenceKind(StrEnum):
    CLAIM = "claim"  # states something about the subject; must be supported
    FRAMING = "framing"  # analogy or example; must not mislead
    CONNECTIVE = "connective"  # signposting with no content of its own
    RECALL = "recall"  # a question to the listener; a pause and its answer follow


class Sentence(BaseModel):
    id: str
    text: str
    kind: SentenceKind
    sources: list[str] = Field(default_factory=list)
    # The host speaking this line in a two-host script; None for a narrator.
    speaker: Speaker | None = None
    # Set when the sentence failed verification and pipeline.unresolved="mark".
    unverified: bool = False

    def line(self) -> str:
        """The sentence as a listener hears it, with its speaker when there is one."""
        return f"{speaker_label(self.speaker)}: {self.text}" if self.speaker else self.text


class Segment(BaseModel):
    id: str
    heading: str
    sentences: list[Sentence]


class Script(BaseModel):
    title: str
    segments: list[Segment]
    format: ScriptFormat = "narrator"

    def sentences(self) -> list[Sentence]:
        return [s for seg in self.segments for s in seg.sentences]

    def word_count(self) -> int:
        return sum(len(s.text.split()) for s in self.sentences())


class Label(StrEnum):
    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"
    CONTRADICTED = "contradicted"
    FRAMING_OK = "framing_ok"
    FRAMING_MISLEADING = "framing_misleading"
    NO_CLAIM = "no_claim"


PASSING_LABELS = frozenset({Label.SUPPORTED, Label.FRAMING_OK, Label.NO_CLAIM})


class Verdict(BaseModel):
    sentence_id: str
    label: Label
    evidence: list[str] = Field(default_factory=list)
    rationale: str = ""

    @property
    def passed(self) -> bool:
        return self.label in PASSING_LABELS


class SessionStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class SessionRecord(BaseModel):
    id: str
    brief: Brief
    title: str = ""  # the script's title, once the Writer has chosen it
    status: SessionStatus = SessionStatus.QUEUED
    stage: str = ""
    log: list[str] = Field(default_factory=list)
    error: str = ""
    # Process that queued or runs the session; lets a restarted app tell an
    # interrupted session from one another process is still running.
    pid: int | None = None
    created_at: datetime = Field(default_factory=utc_now)
    finished_at: datetime | None = None
