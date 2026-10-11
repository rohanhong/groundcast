from groundcast.config import Settings
from groundcast.llm import roles
from groundcast.models import Brief, Chunk, Material
from groundcast.pipeline.run import Pipeline
from groundcast.transcript import render_transcript

from .conftest import scripted_backend

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
