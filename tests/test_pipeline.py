import re
from typing import Any

from groundcast.config import Settings
from groundcast.llm import Role, roles
from groundcast.models import Brief, Chunk, Material
from groundcast.pipeline.run import Pipeline
from groundcast.transcript import render_transcript

from .conftest import FakeBackend, items_in, recall_backend, scripted_backend

Tides = tuple[Material, list[Chunk]]


def test_pipeline_write_verify_revise_edit(settings: Settings, tides: Tides) -> None:
    material, chunks = tides
    brief = Brief(focus="tides", material_ids=[material.id], minutes=5)
    result = Pipeline(settings, scripted_backend(), roles(settings.llm)).run(brief, chunks)
    texts = {s.id: s.text for s in result.script.sentences()}

    assert texts["s1.1"] == "It's the Moon that causes tides."  # edit kept
    assert texts["s1.2"] == "The Moon is the main cause."  # revised in round 1
    assert texts["s1.3"] == "Let's start."  # failing edit reverted
    assert "s2.1" not in texts  # still unsupported after the last round: dropped
    assert result.script.segments[0].heading == "What causes tides"
    # Unknown source IDs from the Writer are removed.
    assert all(src.startswith(material.id) for s in result.script.sentences() for src in s.sources)

    r = result.report
    assert r.writer_sentences == 5
    assert r.first_pass == {"supported": 1, "contradicted": 1, "no_claim": 1, "unsupported": 1, "framing_ok": 1}
    assert r.revise_rounds == settings.pipeline.max_revise_rounds
    assert (r.edits_applied, r.edits_reverted) == (1, 1)
    assert all(v.passed for v in r.verdicts.values())
    assert {"dropped", "replaced", "reverted"} <= {e.outcome for e in r.events}
    # A narrator script has no speakers, whatever the Writer returned.
    assert result.script.format == "narrator"
    assert all(s.speaker is None for s in result.script.sentences())


def test_verifier_sees_no_writer_labels(settings: Settings, tides: Tides) -> None:
    material, chunks = tides
    backend = scripted_backend()
    Pipeline(settings, backend, roles(settings.llm)).run(Brief(focus="tides", material_ids=[material.id]), chunks)
    verifier_prompts = [p for role, _, p in backend.calls if role == "verifier"]
    assert verifier_prompts
    for prompt in verifier_prompts:
        assert "kind" not in prompt and "framing" not in prompt and "connective" not in prompt


def test_unresolved_marked_when_configured(settings: Settings, tides: Tides) -> None:
    material, chunks = tides
    settings.pipeline.unresolved = "mark"
    result = Pipeline(settings, scripted_backend(), roles(settings.llm)).run(
        Brief(focus="tides", material_ids=[material.id]), chunks
    )
    marked = [s for s in result.script.sentences() if s.unverified]
    assert [s.id for s in marked] == ["s2.1"]
    html = render_transcript(result.script, {c.id: c for c in chunks}, {material.id: material},
                             material.added_at, "AI-generated.")  # fmt: skip
    assert 'class="claim unverified"' in html


def test_length_target_scales_with_voice_speed(settings: Settings, tides: Tides) -> None:
    material, chunks = tides
    settings.tts.speed = 1.2
    backend = scripted_backend()
    brief = Brief(focus="tides", material_ids=[material.id], minutes=10)
    Pipeline(settings, backend, roles(settings.llm)).run(brief, chunks)
    writer_prompt = next(prompt for _, title, prompt in backend.calls if title == "Draft")
    expected = 10 * round(settings.pipeline.words_per_minute * 1.2)
    assert f"about {expected} spoken words" in writer_prompt


def test_two_hosts_keep_speakers_and_show_them_to_the_checker(settings: Settings, tides: Tides) -> None:
    material, chunks = tides
    backend = scripted_backend()
    brief = Brief(focus="tides", material_ids=[material.id], format="two_hosts")
    result = Pipeline(settings, backend, roles(settings.llm)).run(brief, chunks)
    speakers = {s.id: s.speaker for s in result.script.sentences()}
    assert result.script.format == "two_hosts"
    assert speakers == {"s1.1": "A", "s1.2": "B", "s1.3": "A", "s2.2": "B"}
    assert "Format: two hosts" in next(p for _, t, p in backend.calls if t == "Draft")
    first_check = next(p for role, _, p in backend.calls if role == "verifier")
    assert "sentence_id: s1.2\nspeaker: Host B\nprevious sentence: Host A: The Moon causes tides." in first_check
    edit_prompt = next(p for _, t, p in backend.calls if t == "Edits")
    assert "s1.2: Host B: The Moon is the main cause." in edit_prompt


def _previous_lines(prompt: str) -> dict[str, str]:
    return dict(re.findall(r"^sentence_id: (\S+)\n(?:speaker: .*\n)?previous sentence: (.*)$", prompt, re.M))


def test_answer_checked_again_when_its_question_is_dropped(settings: Settings, tides: Tides) -> None:
    material, chunks = tides
    first = chunks[0].id
    checked: list[tuple[str, str]] = []

    def draft(role: Role, prompt: str, schema: dict[str, Any]) -> dict[str, Any]:
        lines = [
            ("A", "The Moon causes tides."),
            ("B", "How many UNFIXABLE moons pull on the sea?"),
            ("A", "Just one."),
        ]
        return {
            "title": "Tides",
            "segments": [{"heading": "Moons", "sentences": [
                {"text": t, "kind": "claim", "sources": [first], "speaker": sp} for sp, t in lines
            ]}],
        }  # fmt: skip

    def verify(role: Role, prompt: str, schema: dict[str, Any]) -> dict[str, Any]:
        previous = _previous_lines(prompt)
        out = []
        for i in items_in(prompt):
            checked.append((i["text"], previous[i["sentence_id"]]))
            if "UNFIXABLE" in i["text"]:
                label = "unsupported"
            elif i["text"] == "Just one.":
                label = "supported" if "How many" in previous[i["sentence_id"]] else "unsupported"
            else:
                label = "supported"
            out.append({"sentence_id": i["sentence_id"], "label": label})
        return {"verdicts": out}

    def revise(role: Role, prompt: str, schema: dict[str, Any]) -> dict[str, Any]:
        return {"revisions": [{"sentence_id": i["sentence_id"], "action": "drop"} for i in items_in(prompt)]}

    backend = FakeBackend({
        "Draft": draft,
        "VerifierOutput": verify,
        "Revisions": revise,
        "Edits": lambda role, prompt, schema: {"sentences": [], "headings": []},
    })  # fmt: skip
    brief = Brief(focus="tides", material_ids=[material.id], format="two_hosts")
    result = Pipeline(settings, backend, roles(settings.llm)).run(brief, chunks)

    assert [s.text for s in result.script.sentences()] == ["The Moon causes tides."]
    assert ("Just one.", "Host A: The Moon causes tides.") in checked  # checked again without its question
    assert [e.sentence_id for e in result.report.events if e.outcome == "dropped"] == ["s1.2", "s1.3"]


def test_recall_question_dropped_with_its_answer(settings: Settings, tides: Tides) -> None:
    material, chunks = tides
    backend = recall_backend(chunks[0].id)
    brief = Brief(focus="tides", material_ids=[material.id], minutes=4, recall_prompts=True)
    result = Pipeline(settings, backend, roles(settings.llm)).run(brief, chunks)

    writer_prompt = next(p for _, t, p in backend.calls if t == "Draft")
    assert "Recall prompts: end with a recall segment of 3 questions" in writer_prompt
    # The pauses after the questions take time but no words.
    seconds = 4 * 60 - settings.pipeline.recall_questions * settings.tts.recall_pause_s
    assert f"about {round(seconds / 60 * settings.pipeline.words_per_minute)} spoken words" in writer_prompt
    assert [s.text for s in result.script.sentences()] == ["Let's check what stuck.", "What causes tides?", "The Moon."]
    assert [(e.sentence_id, e.stage) for e in result.report.events if e.outcome == "dropped"][-1] == ("s1.4", "recall")
