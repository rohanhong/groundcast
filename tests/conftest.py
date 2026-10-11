from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from groundcast.config import Settings, load_settings
from groundcast.ingest import ingest_file
from groundcast.llm.base import LLMBackend, Role
from groundcast.models import Chunk, Material
from groundcast.storage import Store

FIXTURES = Path(__file__).parent / "fixtures"

Handler = Callable[[Role, str, dict[str, Any]], Any]


class FakeBackend(LLMBackend):
    """Routes each structured call to a handler chosen by the output schema title."""

    def __init__(self, handlers: dict[str, Handler]) -> None:
        super().__init__(max_attempts=2)
        self.handlers = handlers
        self.calls: list[tuple[str, str, str]] = []

    def complete(self, role: Role, system: str, prompt: str) -> str:
        raise NotImplementedError

    def _complete_json(self, role: Role, system: str, prompt: str, schema: dict[str, Any]) -> Any:
        title = schema["title"]
        self.calls.append((role.name, title, prompt))
        return self.handlers[title](role, prompt, schema)


def items_in(prompt: str) -> list[dict[str, str]]:
    """Parse the sentence_id/sentence blocks the pipeline puts in prompts."""
    out = []
    for block in prompt.split("\n\n"):
        sid = re.search(r"^sentence_id: (\S+)$", block, re.M)
        text = re.search(r"^sentence: (.*)$", block, re.M)
        if sid and text:
            out.append({"sentence_id": sid.group(1), "text": text.group(1)})
    return out


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    config = tmp_path / "config.toml"
    config.write_text(
        f"data_dir = '{(tmp_path / 'data').as_posix()}'\n"
        f"model_dir = '{(tmp_path / 'models').as_posix()}'\n"
        "[tts]\nengine = 'silent'\n",
        encoding="utf-8",
    )
    return load_settings(config, environ={})


@pytest.fixture
def store(settings: Settings) -> Store:
    return Store(settings.data_dir)


@pytest.fixture
def tides(settings: Settings, store: Store) -> tuple[Material, list[Chunk]]:
    """The tides fixture, ingested into the test data directory."""
    material = ingest_file(FIXTURES / "tides.md", store, settings)
    return material, store.get_chunks(material.id)


def _label(text: str) -> str:
    if "WRONG" in text:
        return "contradicted"
    if "UNFIXABLE" in text:
        return "unsupported"
    if "like a" in text:
        return "framing_ok"
    if text.startswith("Let's"):
        return "no_claim"
    return "supported"


def scripted_backend() -> FakeBackend:
    """A full Writer, Verifier, reviser, and Editor run with known outcomes.

    The Verifier labels by marker words: WRONG is contradicted, UNFIXABLE is
    unsupported (and stays so after revision), "like a" is framing.
    """

    def draft(role: Role, prompt: str, schema: dict[str, Any]) -> dict[str, Any]:
        first = re.search(r"^\[(\S+)\]", prompt, re.M).group(1)  # type: ignore[union-attr]
        return {
            "title": "Tides",
            "segments": [
                {
                    "heading": "Causes",
                    "sentences": [
                        {"text": "The Moon causes tides.", "kind": "claim", "sources": [first, "bogus:p9:9"]},
                        {"text": "The Sun is the WRONG main cause.", "kind": "claim", "sources": [first]},
                        {"text": "Let's start.", "kind": "connective", "sources": []},
                    ],
                },
                {
                    "heading": "Spring tides",
                    "sentences": [
                        {"text": "An UNFIXABLE claim.", "kind": "claim", "sources": []},
                        {"text": "It is like a tug of war.", "kind": "framing", "sources": [first]},
                    ],
                },
            ],
        }

    def verify(role: Role, prompt: str, schema: dict[str, Any]) -> dict[str, Any]:
        return {"verdicts": [{**i, "label": _label(i["text"]), "rationale": "r"} for i in items_in(prompt)]}

    def revise(role: Role, prompt: str, schema: dict[str, Any]) -> dict[str, Any]:
        out = []
        for i in items_in(prompt):
            text = "The Moon is the main cause." if "WRONG" in i["text"] else "Still UNFIXABLE."
            out.append({"sentence_id": i["sentence_id"], "action": "replace", "text": text, "kind": "claim"})
        return {"revisions": out}

    def edit(role: Role, prompt: str, schema: dict[str, Any]) -> dict[str, Any]:
        return {
            "sentences": [
                {"sentence_id": "s1.1", "text": "It's the Moon that causes tides."},
                {"sentence_id": "s1.3", "text": "Let's start, WRONG way round."},
            ],
            "headings": [{"segment_id": "g1", "heading": "What causes tides"}],
        }

    return FakeBackend({"Draft": draft, "VerifierOutput": verify, "Revisions": revise, "Edits": edit})
