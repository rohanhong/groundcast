from typing import Any

from fastapi.testclient import TestClient

from groundcast.config import Settings
from groundcast.elicit import BriefProposal, ChatTurn, elicit, outline, to_brief
from groundcast.llm import Role, roles
from groundcast.models import MAX_MINUTES, Brief, Chunk, Material, SessionRecord
from groundcast.storage import Store
from groundcast.web.app import create_app

from .conftest import FakeBackend

Tides = tuple[Material, list[Chunk]]


def proposing(brief: dict[str, Any], ready: bool = True, reply: str = "Here is the plan.") -> FakeBackend:
    return FakeBackend({"ElicitorOutput": lambda role, prompt, schema: {"reply": reply, "ready": ready, "brief": brief}})


def test_proposal_is_made_valid() -> None:
    known = {"aaa", "bbb"}
    p = BriefProposal(focus=" ice ", material_ids=["zzz", "bbb", "bbb"], minutes=500)
    brief = to_brief(p, known, selected=["aaa"])
    assert brief is not None
    assert brief.material_ids == ["bbb"]  # unknown and repeated IDs removed
    assert brief.minutes == MAX_MINUTES and brief.focus == "ice"
    assert to_brief(BriefProposal(focus="ice", material_ids=["zzz"]), known, ["aaa"]).material_ids == ["aaa"]
    assert to_brief(BriefProposal(focus=" ", material_ids=["aaa"]), known, []) is None
    assert to_brief(BriefProposal(focus="ice"), known, []) is None


def test_outline_keeps_first_sentences_within_budget(tides: Tides) -> None:
    _, chunks = tides
    text = outline(chunks, 12)
    assert len(text.replace("|", " ").split()) <= 12
    assert text and text.split(" | ")[0] in chunks[0].text


def test_elicitor_sees_materials_and_last_brief(settings: Settings, tides: Tides) -> None:
    material, _ = tides
    backend = proposing({"focus": "tides", "material_ids": [material.id]}, ready=False, reply="How long?")
    last = Brief(focus="spring tides", material_ids=[material.id], minutes=15, context="exercise")
    result = elicit(backend, roles(settings.llm)["elicitor"], settings, [material], {material.id: "The Moon pulls."},
                    [ChatTurn(role="user", text="Tides for my run")], [material.id], last)  # fmt: skip
    prompt = backend.calls[0][2]
    assert f"- {material.id}: tides.md" in prompt and "(selected in the form)" in prompt
    assert "Outline: The Moon pulls." in prompt
    assert "focus=spring tides" in prompt and "context=exercise" in prompt
    assert f"You have asked 0 of at most {settings.elicit.max_questions} questions." in prompt
    assert result.reply == "How long?" and not result.ready
    assert result.brief is not None and result.questions_left == settings.elicit.max_questions - 1


def test_elicitor_must_propose_after_the_last_question(settings: Settings, tides: Tides) -> None:
    material, _ = tides
    settings.elicit.max_questions = 1
    backend = proposing({"focus": "tides", "material_ids": [material.id]}, ready=False)
    turns = [ChatTurn(role="user", text="tides"), ChatTurn(role="assistant", text="How long?"),
             ChatTurn(role="user", text="ten minutes")]  # fmt: skip
    result = elicit(backend, roles(settings.llm)["elicitor"], settings, [material], {}, turns, [], None)
    assert "Propose the brief now" in backend.calls[0][2]
    assert result.ready and result.questions_left == 0


def test_elicit_api(settings: Settings, store: Store, tides: Tides) -> None:
    material, _ = tides
    store.save_session(SessionRecord(id="old", brief=Brief(focus="neap tides", material_ids=[material.id]),
                                     status="done"))  # fmt: skip
    seen: list[str] = []

    def reply(role: Role, prompt: str, schema: dict[str, Any]) -> dict[str, Any]:
        seen.append(prompt)
        return {"reply": "Ten minutes on tides, then.", "ready": True,
                "brief": {"focus": "tides", "material_ids": ["nope"], "minutes": 10}}  # fmt: skip

    app = create_app(settings, runner=object(), backend=FakeBackend({"ElicitorOutput": reply}))  # type: ignore[arg-type]
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        body = {"messages": [{"role": "user", "text": "Ten minutes on tides"}], "material_ids": [material.id]}
        r = client.post("/api/elicit", json=body)
        assert r.status_code == 200, r.text
        assert r.json()["ready"] and r.json()["brief"]["material_ids"] == [material.id]
        assert "focus=neap tides" in seen[0]  # the last finished session's brief
        ends_with_reply = {"messages": [{"role": "assistant", "text": "Hi"}]}
        assert client.post("/api/elicit", json=ends_with_reply).status_code == 422
        too_long = {"messages": [{"role": "user", "text": "x" * (settings.elicit.max_message_chars + 1)}]}
        assert client.post("/api/elicit", json=too_long).status_code == 422
