"""Helpers shared by the pipeline stages."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from functools import cache
from importlib import resources

from groundcast.models import Chunk

Progress = Callable[[str, str], None]


def no_progress(stage: str, message: str) -> None:
    pass


@cache
def load_prompt(name: str) -> str:
    """Load prompts/<name>.md, with {rubric} filled from prompts/rubric.md."""
    files = resources.files("groundcast.prompts")
    text = files.joinpath(f"{name}.md").read_text(encoding="utf-8")
    if "{rubric}" in text:
        text = text.replace("{rubric}", files.joinpath("rubric.md").read_text(encoding="utf-8"))
    return text


def format_passages(chunks: Iterable[Chunk]) -> str:
    return "\n\n".join(f"[{c.id}] {c.text}" for c in chunks)
