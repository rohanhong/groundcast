"""S4 Verify and S7 Re-verify.

The Verifier sees only each sentence, the sentence before it for reference
resolution, and the passages: the ones the Writer cited plus the BM25 top-k
(spec sections 5 and 6). It never sees the Writer's reasoning or labels.
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, Field

from groundcast.llm import LLMBackend, Role
from groundcast.models import Chunk, Label, Sentence, Verdict
from groundcast.pipeline.common import format_passages, load_prompt
from groundcast.retrieval import BM25Index


class VerdictOut(BaseModel):
    sentence_id: str
    label: Label
    evidence: list[str] = Field(default_factory=list)
    rationale: str = ""


class VerifierOutput(BaseModel):
    verdicts: list[VerdictOut]


@dataclass(frozen=True)
class CheckItem:
    sentence_id: str
    text: str
    context: str
    passages: list[Chunk]


def passages_for(text: str, cited: list[str], by_id: dict[str, Chunk], index: BM25Index, top_k: int) -> list[Chunk]:
    cited_chunks = [by_id[c] for c in cited if c in by_id]
    extra = index.top_k(text, top_k, exclude={c.id for c in cited_chunks})
    return cited_chunks + extra


def build_items(
    sentences: list[tuple[Sentence, str]], by_id: dict[str, Chunk], index: BM25Index, top_k: int
) -> list[CheckItem]:
    """sentences: (sentence, previous sentence text) pairs."""
    return [
        CheckItem(s.id, s.text, context, passages_for(s.text, s.sources, by_id, index, top_k))
        for s, context in sentences
    ]


def _prompt(items: list[CheckItem]) -> str:
    pool: dict[str, Chunk] = {}
    blocks = []
    for item in items:
        for c in item.passages:
            pool.setdefault(c.id, c)
        blocks.append(
            f"sentence_id: {item.sentence_id}\n"
            f"previous sentence: {item.context or '(none)'}\n"
            f"sentence: {item.text}\n"
            f"check against: {', '.join(c.id for c in item.passages) or '(no passages)'}"
        )
    return (
        "# Passages\n\n"
        f"{format_passages(pool.values())}\n\n"
        "# Items\n\n" + "\n\n".join(blocks) + "\n\nReturn one verdict per item."
    )


def verify_items(backend: LLMBackend, role: Role, items: list[CheckItem], batch_size: int) -> dict[str, Verdict]:
    verdicts: dict[str, Verdict] = {}
    pending = list(items)
    # A second pass re-asks for items the model skipped in the first.
    for _ in range(2):
        for start in range(0, len(pending), batch_size):
            batch = pending[start : start + batch_size]
            wanted = {i.sentence_id for i in batch}
            out = backend.complete_structured(role, load_prompt("verifier"), _prompt(batch), VerifierOutput)
            for v in out.verdicts:
                if v.sentence_id in wanted and v.sentence_id not in verdicts:
                    verdicts[v.sentence_id] = Verdict(**v.model_dump())
        pending = [i for i in pending if i.sentence_id not in verdicts]
        if not pending:
            break
    for item in pending:
        verdicts[item.sentence_id] = Verdict(
            sentence_id=item.sentence_id, label=Label.UNSUPPORTED, rationale="The Verifier returned no verdict."
        )
    return verdicts
