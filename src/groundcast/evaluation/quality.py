"""Script-quality evaluation (spec sections 9.2 and 13).

A quality set lists briefs on self-written materials. For each brief the
pipeline writes, verifies, and edits a script (no audio), and an LLM judge
scores it against the fixed criteria in prompts/judge.md, several times,
since one judging run is noisy. Scripts vary more than judgements: with
prompts unchanged, one brief's axis scores moved by up to 0.6 between two
scripts, so a comparison of prompts should write several scripts per brief
(generations). The judge's criteria do not change when the
Writer's prompts change, so two runs of this evaluation compare prompts.
Correctness comes from the pipeline's own verification report.
"""

from __future__ import annotations

import json
import statistics
import tempfile
from collections.abc import Callable
from pathlib import Path

from pydantic import BaseModel, Field

from groundcast.config import Settings
from groundcast.ingest import ingest_file
from groundcast.llm import LLMBackend, roles
from groundcast.models import PASSING_LABELS, Brief, Context, Label, Level, Script, ScriptFormat
from groundcast.pipeline.common import load_prompt
from groundcast.pipeline.run import Pipeline
from groundcast.storage import Store

CRITERIA: dict[str, list[str]] = {
    "structure": ["opening", "build_up", "segments", "recaps", "coherence", "fit"],
    "fluency": ["sentences", "spoken", "terms", "evidence"],
    "vividness": ["concrete", "framing", "pull"],
    "format": ["dialogue", "recall"],
}
ALL_CRITERIA = [c for names in CRITERIA.values() for c in names]


class QualityBrief(BaseModel):
    id: str
    materials: list[str]  # paths relative to the set file
    focus: str
    minutes: int = 4
    context: Context = "commute"
    level: Level = "introductory"
    format: ScriptFormat = "narrator"
    recall_prompts: bool = False


class QualitySet(BaseModel):
    description: str = ""
    briefs: list[QualityBrief]


class CriterionScore(BaseModel):
    criterion: str = Field(description="One of the criterion names in the instructions")
    score: int | None = Field(description="1 to 5, or null where the criterion does not apply")
    reason: str = Field(description="One sentence with the strongest evidence and line numbers")


class JudgeOutput(BaseModel):
    scores: list[CriterionScore]


class BriefResult(BaseModel):
    id: str
    generation: int = 1  # which script for this brief, when several are written
    words: int
    target_words: int
    sentences: int  # written by the Writer
    first_pass_rate: float  # share of the Writer's sentences that passed the first verification
    dropped: int  # sentences removed because they failed verification
    scores: dict[str, float | None]  # criterion -> mean over judging runs
    runs: list[dict[str, int | None]]  # criterion -> score, per judging run
    reasons: dict[str, str]  # criterion -> the first run's reason


class QualityReport(BaseModel):
    set_path: str
    writer_model: str
    judge_model: str
    judge_runs: int
    generations: int = 1
    briefs: list[BriefResult]
    axes: dict[str, float | None]  # axis -> mean of its criteria over briefs
    criteria: dict[str, float | None]  # criterion -> mean over briefs
    first_pass_rate: float
    length_ratio: float  # mean of words / target words


def _mean(values: list[float | None]) -> float | None:
    present = [v for v in values if v is not None]
    return statistics.fmean(present) if present else None


def render_for_judge(brief: Brief, script: Script, target_words: int) -> str:
    lines = [
        "# Brief",
        f"focus: {brief.focus}",
        f"length: {brief.minutes} minutes (about {target_words} words)",
        f"level: {brief.level}; listening context: {brief.context}",
        f"format: {'two hosts' if brief.format == 'two_hosts' else 'one narrator'}"
        + ("; ends with recall questions" if brief.recall_prompts else ""),
        "",
        f"# Script: {script.title} ({script.word_count()} words)",
    ]
    n = 0
    for number, seg in enumerate(script.segments, start=1):
        lines.append(f"\n## Segment {number}: {seg.heading}")
        for s in seg.sentences:
            n += 1
            mark = f"[{s.kind.value}] " if s.kind.value in ("framing", "recall") else ""
            lines.append(f"{n}. {mark}{s.line()}")
    return "\n".join(lines)


def judge_script(backend: LLMBackend, settings: Settings, brief: Brief, script: Script, target: int) -> dict:
    role = roles(settings.llm)["judge"]
    prompt = render_for_judge(brief, script, target) + "\n\nScore every criterion named in the instructions."
    out = backend.complete_structured(role, load_prompt("judge"), prompt, JudgeOutput)
    scores: dict[str, int | None] = {c: None for c in ALL_CRITERIA}
    reasons: dict[str, str] = {}
    for item in out.scores:
        if item.criterion in scores:
            scores[item.criterion] = min(5, max(1, item.score)) if item.score is not None else None
            reasons[item.criterion] = item.reason
    # Format criteria apply only to their format; the judge cannot opt in or out.
    if brief.format != "two_hosts":
        scores["dialogue"] = None
    if not brief.recall_prompts:
        scores["recall"] = None
    return {"scores": scores, "reasons": reasons}


def run_quality(
    set_path: Path,
    settings: Settings,
    backend: LLMBackend,
    judge_runs: int,
    out_dir: Path,
    progress: Callable[[str], None] = print,
    generations: int = 1,
) -> QualityReport:
    quality_set = QualitySet.model_validate_json(set_path.read_text(encoding="utf-8"))
    out_dir.mkdir(parents=True, exist_ok=True)
    results = []
    with tempfile.TemporaryDirectory(prefix="groundcast-quality-") as tmp:
        store = Store(Path(tmp))
        for qb, generation in ((qb, g) for qb in quality_set.briefs for g in range(1, generations + 1)):
            materials = [ingest_file(set_path.parent / rel, store, settings) for rel in qb.materials]
            chunks = [c for m in materials for c in store.get_chunks(m.id)]
            brief = Brief(focus=qb.focus, material_ids=[m.id for m in materials], minutes=qb.minutes,
                          context=qb.context, level=qb.level, format=qb.format, recall_prompts=qb.recall_prompts)  # fmt: skip
            label = qb.id if generations == 1 else f"{qb.id} #{generation}"
            progress(f"{label}: writing and checking a {qb.minutes}-minute script")
            result = Pipeline(settings, backend, roles(settings.llm)).run(brief, chunks)
            report = result.report
            name = qb.id if generations == 1 else f"{qb.id}-{generation}"
            (out_dir / f"{name}.script.json").write_text(result.model_dump_json(indent=1), encoding="utf-8")
            runs = []
            reasons: dict[str, str] = {}
            for n in range(1, judge_runs + 1):
                progress(f"{label}: judging, run {n}/{judge_runs}")
                judged = judge_script(backend, settings, brief, result.script, report.target_words)
                runs.append(judged["scores"])
                reasons = reasons or judged["reasons"]
            passed = sum(v for k, v in report.first_pass.items() if Label(k) in PASSING_LABELS)
            dropped = sum(1 for e in report.events if e.outcome == "dropped")
            results.append(
                BriefResult(
                    id=qb.id,
                    generation=generation,
                    words=result.script.word_count(),
                    target_words=report.target_words,
                    sentences=report.writer_sentences,
                    first_pass_rate=passed / max(1, report.writer_sentences),
                    dropped=dropped,
                    scores={c: _mean([r[c] for r in runs]) for c in ALL_CRITERIA},
                    runs=runs,
                    reasons=reasons,
                )
            )
    criteria = {c: _mean([r.scores[c] for r in results]) for c in ALL_CRITERIA}
    return QualityReport(
        set_path=str(set_path),
        writer_model=roles(settings.llm)["writer"].model,
        judge_model=roles(settings.llm)["judge"].model,
        judge_runs=judge_runs,
        generations=generations,
        briefs=results,
        axes={axis: _mean([criteria[c] for c in names]) for axis, names in CRITERIA.items()},
        criteria=criteria,
        first_pass_rate=statistics.fmean(r.first_pass_rate for r in results),
        length_ratio=statistics.fmean(r.words / max(1, r.target_words) for r in results),
    )


def format_quality(report: QualityReport) -> str:
    def f(v: float | None) -> str:
        return "  -  " if v is None else f"{v:.2f}"

    lines = [
        f"Writer {report.writer_model}, judge {report.judge_model}, {report.generations} script(s) per brief, "
        f"{report.judge_runs} judging run(s) per script",
        f"  first-pass verification {report.first_pass_rate:.3f}, length {report.length_ratio:.2f} of target",
        "  " + "  ".join(f"{axis} {f(v)}" for axis, v in report.axes.items()),
        "Per criterion (mean over briefs):",
    ]
    for axis, names in CRITERIA.items():
        lines.append(f"  {axis:10} " + "  ".join(f"{c} {f(report.criteria[c])}" for c in names))
    lines.append("Per brief:")
    for b in report.briefs:
        weakest = sorted((v, c) for c, v in b.scores.items() if v is not None)[:3]
        name = b.id if report.generations == 1 else f"{b.id} #{b.generation}"
        lines.append(f"  {name:17} {b.words}/{b.target_words} words, first pass {b.first_pass_rate:.2f}, "
                     f"dropped {b.dropped}; weakest: " + ", ".join(f"{c} {v:.1f}" for v, c in weakest))  # fmt: skip
    return "\n".join(lines)


def save_quality(report: QualityReport, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report.model_dump(), indent=1), encoding="utf-8")
