"""Seeded-error test for the Verifier (spec section 13).

An evaluation set is a JSON file listing self-written materials and script
sentences with the label the Verifier should give. Each item locates the chunk
the Writer would have cited by a quote from it. Runs are repeated because a
single LLM run is noisy; the report gives the mean and range per metric.
"""

from __future__ import annotations

import json
import re
import statistics
import tempfile
from collections.abc import Callable
from pathlib import Path

from pydantic import BaseModel, Field

from groundcast.config import Settings
from groundcast.ingest import ingest_file
from groundcast.llm import LLMBackend, roles
from groundcast.models import PASSING_LABELS, Chunk, Label, Sentence, SentenceKind
from groundcast.pipeline.run import check_sentences
from groundcast.storage import Store


class EvalItem(BaseModel):
    id: str
    expected: Label
    quote: str
    text: str
    context: str = ""


class EvalSet(BaseModel):
    description: str = ""
    materials: list[str]
    items: list[EvalItem]


class RunMetrics(BaseModel):
    detection_rate: float  # seeded errors flagged / seeded errors
    false_flag_rate: float  # correct sentences flagged / correct sentences
    label_accuracy: float  # exact label matches / items


class Summary(BaseModel):
    mean: float
    min: float
    max: float


class EvalReport(BaseModel):
    set_path: str
    verifier_model: str
    verifier_effort: str
    runs: list[RunMetrics]
    summary: dict[str, Summary]
    # Per item: how many runs flagged it, and every label it received.
    items: dict[str, dict[str, object]] = Field(default_factory=dict)


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def resolve_quote(quote: str, chunks: list[Chunk]) -> str:
    matches = [c.id for c in chunks if _norm(quote) in _norm(c.text)]
    if len(matches) != 1:
        raise ValueError(f"quote {quote!r} matches {len(matches)} chunks; it must match exactly one")
    return matches[0]


def _flagged(label: Label) -> bool:
    return label not in PASSING_LABELS


def run_seeded(
    set_path: Path,
    settings: Settings,
    backend: LLMBackend,
    runs: int,
    progress: Callable[[str], None] = print,
) -> EvalReport:
    eval_set = EvalSet.model_validate_json(set_path.read_text(encoding="utf-8"))
    role = roles(settings.llm)["verifier"]
    with tempfile.TemporaryDirectory(prefix="groundcast-eval-") as tmp:
        store = Store(Path(tmp))
        chunks: list[Chunk] = []
        for rel in eval_set.materials:
            material = ingest_file(set_path.parent / rel, store, settings)
            chunks.extend(store.get_chunks(material.id))
    pairs = [
        (
            Sentence(id=item.id, text=item.text, kind=SentenceKind.CLAIM, sources=[resolve_quote(item.quote, chunks)]),
            item.context,
        )
        for item in eval_set.items
    ]
    errors = [i for i in eval_set.items if _flagged(i.expected)]
    correct = [i for i in eval_set.items if not _flagged(i.expected)]
    run_metrics: list[RunMetrics] = []
    labels: dict[str, list[str]] = {i.id: [] for i in eval_set.items}
    for run in range(1, runs + 1):
        progress(f"Run {run}/{runs}: checking {len(pairs)} sentences")
        verdicts = check_sentences(backend, role, settings, chunks, pairs)
        for item in eval_set.items:
            labels[item.id].append(verdicts[item.id].label.value)
        run_metrics.append(
            RunMetrics(
                detection_rate=sum(_flagged(verdicts[i.id].label) for i in errors) / max(1, len(errors)),
                false_flag_rate=sum(_flagged(verdicts[i.id].label) for i in correct) / max(1, len(correct)),
                label_accuracy=sum(verdicts[i.id].label == i.expected for i in eval_set.items) / len(eval_set.items),
            )
        )
    summary = {}
    for metric in RunMetrics.model_fields:
        values = [getattr(m, metric) for m in run_metrics]
        summary[metric] = Summary(mean=statistics.fmean(values), min=min(values), max=max(values))
    items = {
        i.id: {
            "expected": i.expected.value,
            "flagged_runs": sum(_flagged(Label(lbl)) for lbl in labels[i.id]),
            "labels": labels[i.id],
        }
        for i in eval_set.items
    }
    return EvalReport(
        set_path=str(set_path),
        verifier_model=role.model,
        verifier_effort=role.effort,
        runs=run_metrics,
        summary=summary,
        items=items,
    )


def format_report(report: EvalReport) -> str:
    lines = [f"Verifier {report.verifier_model} ({report.verifier_effort}), {len(report.runs)} run(s)"]
    for name, s in report.summary.items():
        lines.append(f"  {name:16} mean {s.mean:.3f}  min {s.min:.3f}  max {s.max:.3f}")
    misses = [
        f"  {item_id}: expected {d['expected']}, got {', '.join(d['labels'])}"  # type: ignore[arg-type]
        for item_id, d in report.items.items()
        if any(lbl != d["expected"] for lbl in d["labels"])  # type: ignore[union-attr]
    ]
    if misses:
        lines.append("Items with a label other than the expected one:")
        lines.extend(misses)
    return "\n".join(lines)


def save_report(report: EvalReport, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report.model_dump(), indent=1), encoding="utf-8")
