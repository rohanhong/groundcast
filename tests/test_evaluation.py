import json
from pathlib import Path
from typing import Any

import pytest

from groundcast.config import EvaluationSettings, Settings
from groundcast.evaluation.seeded import EvalSet, resolve_quote, run_seeded, threshold_failures
from groundcast.ingest import ingest_file
from groundcast.llm.base import Role
from groundcast.storage import Store

from .conftest import FakeBackend, items_in

SEEDED = Path(__file__).resolve().parent.parent / "evals" / "seeded" / "items.json"


def test_seeded_set_quotes_resolve(settings: Settings, store: Store) -> None:
    eval_set = EvalSet.model_validate_json(SEEDED.read_text(encoding="utf-8"))
    chunks = []
    for rel in eval_set.materials:
        chunks += store.get_chunks(ingest_file(SEEDED.parent / rel, store, settings).id)
    for item in eval_set.items:
        resolve_quote(item.quote, chunks)
    assert len({i.id for i in eval_set.items}) == len(eval_set.items)


def test_run_seeded_metrics(settings: Settings) -> None:
    expected = {i["id"]: i["expected"] for i in json.loads(SEEDED.read_text(encoding="utf-8"))["items"]}
    flip = "wc-01"  # one supported sentence the fake Verifier wrongly flags

    def verify(role: Role, prompt: str, schema: dict[str, Any]) -> dict[str, Any]:
        out = []
        for i in items_in(prompt):
            label = "unsupported" if i["sentence_id"] == flip else expected[i["sentence_id"]]
            out.append({"sentence_id": i["sentence_id"], "label": label})
        return {"verdicts": out}

    report = run_seeded(SEEDED, settings, FakeBackend({"VerifierOutput": verify}), runs=2, progress=lambda m: None)
    correct = sum(1 for v in expected.values() if v in ("supported", "framing_ok", "no_claim"))
    assert report.summary["detection_rate"].mean == 1.0
    assert report.summary["false_flag_rate"].mean == pytest.approx(1 / correct)
    assert report.items[flip]["flagged_runs"] == 2
    hard = report.by_tag["hard"]
    assert (hard.detection_rate, hard.false_flag_rate) == (1.0, 0.0)  # the flipped item is not tagged hard
    assert report.by_tag["causal"].false_flag_rate is None  # a tag with seeded errors only
    assert threshold_failures(report, settings.evaluation) == []
    strict = EvaluationSettings(max_false_flag_rate=0.0, hard_tag="missing")
    failures = threshold_failures(report, strict)
    assert len(failures) == 2 and "false-flag" in failures[0] and "'missing'" in failures[1]
