"""Seeded-error test for the Verifier (spec section 13).

An evaluation set is a JSON file listing self-written materials and script
sentences with the label the Verifier should give. Each item locates the chunk
the Writer would have cited by a quote from it. An item from a two-host
script names its speaker, and its context names the other host's line. Runs are repeated because a
single LLM run is noisy; the report gives the mean and range per metric, and
the rates per item tag (for example the harder items, or one error type).
"""

from __future__ import annotations

import json
import re
import statistics
import tempfile
from collections.abc import Callable
from pathlib import Path

from pydantic import BaseModel, Field

from groundcast.config import EvaluationSettings, Settings
from groundcast.ingest import ingest_file
from groundcast.llm import LLMBackend, roles
from groundcast.models import PASSING_LABELS, Chunk, Label, Sentence, SentenceKind, Speaker
from groundcast.pipeline.run import check_sentences
from groundcast.storage import Store


class EvalItem(BaseModel):
    id: str
    expected: Label
    quote: str
    text: str
    context: str = ""
    speaker: Speaker | None = None
    tags: list[str] = Field(default_factory=list)


class EvalSet(BaseModel):
    description: str = ""
    materials: list[str]
    items: list[EvalItem]


class RunMetrics(BaseModel):
    detection_rate: float  # seeded errors flagged / seeded errors
    false_flag_rate: float  # correct sentences flagged / correct sentences
    label_accuracy: float  # exact label matches / items
    # Mean of detection and of correct sentences passed, so a set with more
    # errors than correct sentences cannot hide false flags (S18, S19).
    balanced_accuracy: float


class Summary(BaseModel):
    mean: float
    min: float
    max: float


class TagMetrics(BaseModel):
    errors: int
    correct: int
    detection_rate: float | None  # over all runs; None when the tag has no seeded errors
    false_flag_rate: float | None  # over all runs; None when the tag has no correct sentences


class EvalReport(BaseModel):
    set_path: str
    verifier_model: str
    verifier_effort: str
    runs: list[RunMetrics]
    summary: dict[str, Summary]
    by_tag: dict[str, TagMetrics] = Field(default_factory=dict)
    # Per item: how many runs flagged it, and every label it received.
    items: dict[str, dict[str, object]] = Field(default_factory=dict)
    # Expected label -> label given -> count, over all runs.
    confusion: dict[str, dict[str, int]] = Field(default_factory=dict)


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def resolve_quote(quote: str, chunks: list[Chunk]) -> str:
    matches = [c.id for c in chunks if _norm(quote) in _norm(c.text)]
    if len(matches) != 1:
        raise ValueError(f"quote {quote!r} matches {len(matches)} chunks; it must match exactly one")
    return matches[0]


def _flagged(label: Label) -> bool:
    return label not in PASSING_LABELS


def _flag_share(items: list[EvalItem], labels: dict[str, list[str]]) -> float | None:
    verdicts = [Label(lbl) for i in items for lbl in labels[i.id]]
    return sum(map(_flagged, verdicts)) / len(verdicts) if verdicts else None


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
            Sentence(
                id=item.id,
                text=item.text,
                kind=SentenceKind.CLAIM,
                sources=[resolve_quote(item.quote, chunks)],
                speaker=item.speaker,
            ),
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
        detection = sum(_flagged(verdicts[i.id].label) for i in errors) / max(1, len(errors))
        false_flags = sum(_flagged(verdicts[i.id].label) for i in correct) / max(1, len(correct))
        run_metrics.append(
            RunMetrics(
                detection_rate=detection,
                false_flag_rate=false_flags,
                label_accuracy=sum(verdicts[i.id].label == i.expected for i in eval_set.items) / len(eval_set.items),
                balanced_accuracy=(detection + 1 - false_flags) / 2,
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
    confusion: dict[str, dict[str, int]] = {}
    for i in eval_set.items:
        row = confusion.setdefault(i.expected.value, {})
        for lbl in labels[i.id]:
            row[lbl] = row.get(lbl, 0) + 1
    by_tag = {}
    for tag in sorted({t for i in eval_set.items for t in i.tags}):
        tagged = [i for i in eval_set.items if tag in i.tags]
        by_tag[tag] = TagMetrics(
            errors=sum(_flagged(i.expected) for i in tagged),
            correct=sum(not _flagged(i.expected) for i in tagged),
            detection_rate=_flag_share([i for i in tagged if _flagged(i.expected)], labels),
            false_flag_rate=_flag_share([i for i in tagged if not _flagged(i.expected)], labels),
        )
    return EvalReport(
        set_path=str(set_path),
        verifier_model=role.model,
        verifier_effort=role.effort,
        runs=run_metrics,
        summary=summary,
        by_tag=by_tag,
        items=items,
        confusion=confusion,
    )


def format_report(report: EvalReport) -> str:
    lines = [f"Verifier {report.verifier_model} ({report.verifier_effort}), {len(report.runs)} run(s)"]
    for name, s in report.summary.items():
        lines.append(f"  {name:16} mean {s.mean:.3f}  min {s.min:.3f}  max {s.max:.3f}")
    if report.by_tag:
        lines.append("Per tag, over all runs (detection on seeded errors, false flags on correct sentences):")
    for tag, t in report.by_tag.items():
        det = "-" if t.detection_rate is None else f"{t.detection_rate:.3f}"
        ff = "-" if t.false_flag_rate is None else f"{t.false_flag_rate:.3f}"
        lines.append(f"  {tag:16} detection {det:5} ({t.errors} errors)  false flags {ff:5} ({t.correct} correct)")
    if report.confusion:
        lines.append("Labels given (rows: expected label), over all runs:")
        for expected, row in sorted(report.confusion.items()):
            given = ", ".join(f"{lbl} {n}" for lbl, n in sorted(row.items(), key=lambda kv: -kv[1]))
            lines.append(f"  {expected:18} {given}")
    misses = [
        f"  {item_id}: expected {d['expected']}, got {', '.join(d['labels'])}"  # type: ignore[arg-type]
        for item_id, d in report.items.items()
        if any(lbl != d["expected"] for lbl in d["labels"])  # type: ignore[union-attr]
    ]
    if misses:
        lines.append("Items with a label other than the expected one:")
        lines.extend(misses)
    return "\n".join(lines)


def threshold_failures(report: EvalReport, limits: EvaluationSettings) -> list[str]:
    """Each pass threshold the report misses, as a sentence; empty when it passes."""
    failures = []
    detection = report.summary["detection_rate"].mean
    if detection < limits.min_detection_rate:
        failures.append(f"detection rate {detection:.3f} is below {limits.min_detection_rate:.3f}")
    false_flags = report.summary["false_flag_rate"].mean
    if false_flags > limits.max_false_flag_rate:
        failures.append(f"false-flag rate {false_flags:.3f} is above {limits.max_false_flag_rate:.3f}")
    hard = report.by_tag.get(limits.hard_tag)
    if hard is None or hard.detection_rate is None:
        failures.append(f"no seeded errors carry the tag {limits.hard_tag!r}")
    elif hard.detection_rate < limits.min_hard_detection_rate:
        failures.append(
            f"{limits.hard_tag!r} detection rate {hard.detection_rate:.3f} is below {limits.min_hard_detection_rate:.3f}"
        )
    return failures


def save_report(report: EvalReport, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report.model_dump(), indent=1), encoding="utf-8")
