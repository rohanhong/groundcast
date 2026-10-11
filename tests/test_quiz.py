import re
from typing import Any

import pytest
from fastapi.testclient import TestClient

from groundcast.config import Settings
from groundcast.llm import Role, roles
from groundcast.models import Brief, Chunk, Material, Script, Segment, Sentence, SentenceKind, SessionRecord
from groundcast.quiz import grade, load_quizzes, make_quiz
from groundcast.sessions import SCRIPT_FILE
from groundcast.storage import Store, write_model
from groundcast.web.app import create_app

from .conftest import FakeBackend, items_in

Tides = tuple[Material, list[Chunk]]


def _script(chunks: list[Chunk]) -> Script:
    s = Sentence(id="s1.1", text="The Moon causes tides.", kind=SentenceKind.CLAIM, sources=[chunks[0].id])
    framing = Sentence(id="s1.2", text="Like a tug of war.", kind=SentenceKind.FRAMING, sources=[chunks[0].id])
    return Script(title="Tides", segments=[Segment(id="g1", heading="Causes", sentences=[s, framing])])


def _question(stem: str, source: str, correct: int = 0, true_wrong: bool = False) -> dict[str, Any]:
    options = [
        {"text": "The Moon", "statement": f"{stem} TRUE the Moon."},
        {"text": "The wind", "statement": f"{stem} FALSE the wind."},
        {"text": "Rivers", "statement": f"{stem} {'TRUE' if true_wrong else 'FALSE'} rivers."},
        {"text": "Earthquakes", "statement": f"{stem} FALSE earthquakes."},
    ]
    return {"question": stem, "options": options, "correct": correct, "explanation": "The Moon pulls the sea.",
            "sources": [source, "bogus:p1:1"], "topic": "Causes"}  # fmt: skip


def quiz_backend(questions: Any) -> FakeBackend:
    """The Verifier supports statements marked TRUE and contradicts the rest."""

    def verify(role: Role, prompt: str, schema: dict[str, Any]) -> dict[str, Any]:
        out = []
        for i in items_in(prompt):
            label = "supported" if "TRUE" in i["text"] else "contradicted"
            out.append({"sentence_id": i["sentence_id"], "label": label})
        return {"verdicts": out}

    writer = questions if callable(questions) else (lambda role, prompt, schema: {"questions": questions})
    return FakeBackend({"QuizDraft": writer, "VerifierOutput": verify})


def test_quiz_keeps_only_questions_with_one_supported_answer(settings: Settings, tides: Tides) -> None:
    material, chunks = tides
    src = chunks[0].id

    def writer(role: Role, prompt: str, schema: dict[str, Any]) -> dict[str, Any]:
        assert "## Causes\n- The Moon causes tides." in prompt and "Like a tug of war" not in prompt
        assert f"[{src}]" in prompt
        return {"questions": [
            _question("What causes tides?", src),
            _question("Two right answers?", src, true_wrong=True),  # dropped: a wrong option is supported
            _question("Answer not supported?", src, correct=1),  # dropped: the marked answer fails
            {**_question("Too few options?", src), "options": [{"text": "x", "statement": "TRUE x"}]},  # invalid
        ]}  # fmt: skip

    quiz = make_quiz(quiz_backend(writer), roles(settings.llm), settings, _script(chunks), chunks,
                     {material.id: material})  # fmt: skip
    assert [q.question for q in quiz.questions] == ["What causes tides?"]
    assert quiz.dropped == 3
    q = quiz.questions[0]
    assert q.options[q.correct] == "The Moon"
    assert [s.chunk_id for s in q.sources] == [src]  # the unknown ID is removed
    assert q.sources[0].label == f"tides.md, passage {chunks[0].index}"


def test_options_are_shuffled_with_the_answer_tracked(settings: Settings, tides: Tides) -> None:
    material, chunks = tides
    questions = [_question(f"Question {n}?", chunks[0].id) for n in range(12)]
    quiz = make_quiz(quiz_backend(questions), roles(settings.llm), settings, _script(chunks), chunks,
                     {material.id: material})  # fmt: skip
    assert all(q.options[q.correct] == "The Moon" for q in quiz.questions)
    assert len({q.correct for q in quiz.questions}) > 1  # the Writer always put it first


def test_grading(settings: Settings, tides: Tides) -> None:
    material, chunks = tides
    questions = [_question(f"Question {n}?", chunks[0].id) for n in range(3)]
    quiz = make_quiz(quiz_backend(questions), roles(settings.llm), settings, _script(chunks), chunks,
                     {material.id: material})  # fmt: skip
    right = [q.correct for q in quiz.questions]
    result = grade(quiz, [right[0], (right[1] + 1) % 4, None])
    assert result.attempt.score == 1
    assert [r.right for r in result.results] == [True, False, False]
    with pytest.raises(ValueError):
        grade(quiz, [0])
    with pytest.raises(ValueError):
        grade(quiz, [0, 0, 7])


def test_quiz_api_hides_answers_until_graded(settings: Settings, store: Store, tides: Tides) -> None:
    material, chunks = tides
    store.save_session(SessionRecord(id="s-1", brief=Brief(focus="t", material_ids=[material.id]), status="done"))
    write_model(store.session_dir("s-1") / SCRIPT_FILE, _script(chunks))
    backend = quiz_backend([_question(f"Question {n}?", chunks[0].id) for n in range(2)])
    app = create_app(settings, runner=object(), backend=backend)  # type: ignore[arg-type]
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        quiz = client.post("/api/sessions/s-1/quizzes").json()
        assert len(quiz["questions"]) == 2
        assert not re.search(r'"(correct|explanation)"', client.get("/api/sessions/s-1/quizzes").text)
        r = client.post(f"/api/sessions/s-1/quizzes/{quiz['id']}/attempts", json={"answers": [0, None]})
        assert r.status_code == 200, r.text
        assert len(r.json()["results"]) == 2
        assert client.get("/api/sessions/s-1/quizzes").json()[0]["attempts"][0]["answers"] == [0, None]
        assert client.post(f"/api/sessions/s-1/quizzes/{quiz['id']}/attempts", json={"answers": [0]}).status_code == 422
        assert client.post("/api/sessions/s-1/quizzes/nope/attempts", json={"answers": []}).status_code == 404
    assert len(load_quizzes(store, "s-1").attempts) == 1
