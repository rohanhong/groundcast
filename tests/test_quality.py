import json
from pathlib import Path
from typing import Any

from groundcast.config import Settings
from groundcast.evaluation.quality import ALL_CRITERIA, QualitySet, format_quality, render_for_judge, run_quality
from groundcast.llm.base import Role
from groundcast.models import Brief

from .conftest import FIXTURES, scripted_backend

QUALITY = Path(__file__).resolve().parent.parent / "evals" / "quality" / "briefs.json"


def test_repository_quality_set_is_valid() -> None:
    quality_set = QualitySet.model_validate_json(QUALITY.read_text(encoding="utf-8"))
    assert len({b.id for b in quality_set.briefs}) == len(quality_set.briefs)
    for brief in quality_set.briefs:
        for rel in brief.materials:
            assert (QUALITY.parent / rel).is_file()
    assert {b.format for b in quality_set.briefs} == {"narrator", "two_hosts"}
    assert any(b.recall_prompts for b in quality_set.briefs)


def test_run_quality_scores_and_averages(settings: Settings, tmp_path: Path) -> None:
    set_path = tmp_path / "briefs.json"
    set_path.write_text(json.dumps({"briefs": [
        {"id": "tides", "materials": [str(FIXTURES / "tides.md")], "focus": "tides", "minutes": 2},
    ]}), encoding="utf-8")  # fmt: skip
    prompts: list[str] = []
    runs = iter([4, 2, 5, 5])

    def judge(role: Role, prompt: str, schema: dict[str, Any]) -> dict[str, Any]:
        prompts.append(prompt)
        score = next(runs)
        out = [{"criterion": c, "score": score, "reason": "line 1"} for c in ALL_CRITERIA]
        out.append({"criterion": "made_up", "score": 5, "reason": "ignored"})
        return {"scores": out}

    backend = scripted_backend()
    backend.handlers["JudgeOutput"] = judge
    report = run_quality(set_path, settings, backend, judge_runs=2, out_dir=tmp_path / "out", progress=lambda m: None)
    [brief] = report.briefs
    assert brief.scores["opening"] == 3.0  # mean of 4 and 2
    assert brief.scores["dialogue"] is None and brief.scores["recall"] is None  # narrator, no recall
    assert report.axes["structure"] == 3.0 and report.axes["format"] is None
    assert 0 < brief.first_pass_rate < 1 and brief.dropped >= 1
    assert "[framing]" in prompts[0] and "# Brief" in prompts[0]
    assert (tmp_path / "out" / "tides.script.json").is_file()
    assert "structure 3.00" in format_quality(report)

    twice = run_quality(set_path, settings, backend, judge_runs=1, out_dir=tmp_path / "two", progress=lambda m: None,
                        generations=2)  # fmt: skip
    assert [(b.id, b.generation) for b in twice.briefs] == [("tides", 1), ("tides", 2)]
    assert twice.axes["structure"] == 5.0 and (tmp_path / "two" / "tides-2.script.json").is_file()


def test_render_names_hosts_and_kinds(settings: Settings) -> None:
    from groundcast.models import Script, Segment, Sentence, SentenceKind

    script = Script(title="T", format="two_hosts", segments=[Segment(id="g1", heading="H", sentences=[
        Sentence(id="s1", text="What is a tide?", kind=SentenceKind.CLAIM, speaker="B"),
        Sentence(id="s2", text="Which body pulls the sea?", kind=SentenceKind.RECALL, speaker="B"),
    ])])  # fmt: skip
    text = render_for_judge(Brief(focus="f", material_ids=["a"], format="two_hosts", recall_prompts=True), script, 300)
    assert "1. Host B: What is a tide?" in text and "2. [recall] Host B:" in text and "about 300 words" in text
