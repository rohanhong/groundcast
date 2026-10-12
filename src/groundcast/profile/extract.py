"""Concept extraction from a material, matched against the global table.

The model reads the material's passages in batches together with the
existing concepts that share the most words with the batch, and returns the
concepts it finds; for each it says whether it is one already in the table.
Later batches see the concepts found in earlier ones.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from groundcast.config import Settings
from groundcast.llm import LLMBackend, Role
from groundcast.models import Chunk, Material, utc_now
from groundcast.pipeline.common import format_passages, load_prompt
from groundcast.pipeline.writer import clean_sources
from groundcast.profile.concepts import Concept, add_concept, link_sources, list_concepts, resolve
from groundcast.profile.db import ProfileDB, log_event
from groundcast.retrieval import tokenize


class FoundConcept(BaseModel):
    name: str
    description: str = Field(description="One sentence on what it is, as the passages put it")
    chunk_ids: list[str] = Field(description="IDs of the passages that explain or use it")
    match: str = Field(default="", description="ID of the existing concept it is, or empty when it is new")


class ConceptsOutput(BaseModel):
    concepts: list[FoundConcept]


def _batches(chunks: list[Chunk], max_words: int) -> list[list[Chunk]]:
    batches: list[list[Chunk]] = [[]]
    words = 0
    for c in chunks:
        n = len(c.text.split())
        if batches[-1] and words + n > max_words:
            batches.append([])
            words = 0
        batches[-1].append(c)
        words += n
    return [b for b in batches if b]


def candidates(concepts: list[Concept], text: str, limit: int) -> list[Concept]:
    """The existing concepts sharing the most words with the text."""
    words = set(tokenize(text))
    scored = [(len(words & set(tokenize(f"{c.name} {c.description}"))), c) for c in concepts]
    scored = [(s, c) for s, c in scored if s > 0]
    scored.sort(key=lambda p: (-p[0], p[1].name))
    return [c for _, c in scored[:limit]]


def extract_concepts(
    backend: LLMBackend, role: Role, settings: Settings, db: ProfileDB, material: Material, chunks: list[Chunk]
) -> int:
    """Extract and store the material's concepts; returns how many it was linked to."""
    cfg = settings.concepts
    linked: set[str] = set()
    created = 0
    for batch in _batches(chunks, cfg.batch_words):
        text = " ".join(c.text for c in batch)
        known = candidates(list_concepts(db), text, cfg.candidates)
        known_text = "\n".join(f"- {c.id}: {c.name}. {c.description}" for c in known) or "(none yet)"
        prompt = (
            f"# Concepts already in the table\n\n{known_text}\n\n"
            f"# Passages from {material.filename}\n\n{format_passages(batch)}\n\n"
            f"Return at most {cfg.max_per_material} concepts."
        )
        out = backend.complete_structured(role, load_prompt("concepts"), prompt, ConceptsOutput)
        valid = {c.id for c in batch}
        with db.connect() as con:
            for found in out.concepts[: cfg.max_per_material]:
                chunk_ids = clean_sources(found.chunk_ids, valid)
                if not found.name.strip() or not chunk_ids:
                    continue
                # Any concept in the table counts, shown with this batch or not.
                concept_id = resolve(con, found.match.strip()) if found.match.strip() else None
                if concept_id is None:
                    concept_id = add_concept(con, found.name, found.description, "inference",
                                             reason=f"found in {material.filename}")  # fmt: skip
                    created += 1
                link_sources(con, concept_id, material.id, chunk_ids)
                linked.add(concept_id)
    with db.connect() as con:
        con.execute(
            "INSERT OR REPLACE INTO extractions (material_id, at, concepts) VALUES (?, ?, ?)",
            (material.id, utc_now().isoformat(), len(linked)),
        )
        log_event(con, "concepts.extracted", material.id, "inference",
                  after={"concepts": len(linked), "new": created}, reason=material.filename)  # fmt: skip
    return len(linked)
