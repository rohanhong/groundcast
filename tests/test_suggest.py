from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from groundcast.config import Settings
from groundcast.models import Brief, Chunk, Material, SessionRecord, SessionStatus, utc_now
from groundcast.profile.concepts import add_concept, link_sources, record_quiz
from groundcast.profile.db import ProfileDB, list_events
from groundcast.profile.preferences import set_preferences
from groundcast.profile.suggest import acceptance, infer, record_outcome, suggest
from groundcast.storage import Store
from groundcast.web.app import create_app

Tides = tuple[Material, list[Chunk]]


@pytest.fixture
def db(settings: Settings) -> ProfileDB:
    return ProfileDB(settings.data_dir)


def _session(material_id: str, days_ago: float, status: SessionStatus = SessionStatus.DONE, **brief: object) -> SessionRecord:
    return SessionRecord(id=f"s{days_ago}-{len(brief)}-{status.value}", status=status,
                         brief=Brief(focus="tides", material_ids=[material_id], **brief),  # type: ignore[arg-type]
                         created_at=utc_now() - timedelta(days=days_ago))  # fmt: skip


def test_inference_weighs_recent_sessions_and_needs_evidence(settings: Settings) -> None:
    sessions = [_session("m", d, minutes=15) for d in (1, 2, 3)] + [_session("m", 200, minutes=30)]
    sessions.append(_session("m", 0, SessionStatus.FAILED, minutes=45))  # a failed session is ignored
    minutes = next(i for i in infer(sessions, settings) if i.key == "minutes")
    assert (minutes.value, minutes.sessions, minutes.of_sessions, minutes.applied) == (15, 3, 4, True)
    assert minutes.confidence > 0.95  # the 200-day-old session weighs almost nothing
    one = next(i for i in infer(sessions[:1], settings) if i.key == "minutes")
    assert one.applied is False and one.confidence == pytest.approx(1 / settings.suggest.min_evidence, abs=0.01)


def test_suggestions_rank_weak_topics_then_last_then_new(settings: Settings, store: Store, db: ProfileDB,
                                                         tides: Tides) -> None:  # fmt: skip
    material, chunks = tides
    with db.connect() as con:
        cid = add_concept(con, "Spring tide", "A large tide at full and new moon.", "inference")
        link_sources(con, cid, material.id, [chunks[0].id])
    record_quiz(db, "s1", "a1", [(cid, "q1", False), (cid, "q2", False), (cid, "q3", True)])
    sessions = [_session(material.id, d, minutes=20, format="two_hosts") for d in (1, 2, 3)]
    view = suggest(db, settings, store.list_materials(), sessions)
    assert [s.kind for s in view.suggestions] == ["weak_topics", "same_as_last"]  # the only material is used
    weak = view.suggestions[0]
    assert weak.brief.context == "revision" and weak.brief.recall_prompts and weak.brief.minutes == 20
    assert "Spring tide: 1 of 3 right." in " ".join(weak.why).replace("Quiz results on ", "")
    assert any("you chose it in 3 of your last 3 sessions" in w for w in weak.why)
    assert not any(w.startswith(("Recall questions", "Context")) for w in weak.why)  # overridden by revision
    # An explicit preference wins over the inferred value, and inference can be switched off.
    set_preferences(db, settings, {"minutes": 12})
    assert suggest(db, settings, store.list_materials(), sessions).suggestions[0].brief.minutes == 12
    set_preferences(db, settings, {"infer_preferences": False, "minutes": None})
    off = suggest(db, settings, store.list_materials(), sessions)
    assert off.inferred == [] and off.suggestions[0].brief.format == "narrator" and not off.inference_on


def test_new_material_is_suggested_and_inferred_changes_are_logged(settings: Settings, store: Store,
                                                                   db: ProfileDB, tides: Tides) -> None:  # fmt: skip
    material, _ = tides
    view = suggest(db, settings, store.list_materials(), [])
    assert [s.id for s in view.suggestions] == [f"new_material:{material.id}"]
    sessions = [_session("other", d, level="advanced") for d in (1, 2, 3)]
    suggest(db, settings, store.list_materials(), sessions)
    events = [e for e in list_events(db, 20) if e.kind == "preference.inferred"]
    assert {e.subject for e in events} >= {"level"} and all(e.source == "inference" for e in events)
    count = len(events)
    suggest(db, settings, store.list_materials(), sessions)  # nothing changed: nothing new logged
    assert len([e for e in list_events(db, 20) if e.kind == "preference.inferred"]) == count


def test_outcomes_give_the_acceptance_rate(settings: Settings, store: Store, db: ProfileDB, tides: Tides) -> None:
    material, _ = tides
    [s] = suggest(db, settings, store.list_materials(), []).suggestions
    assert record_outcome(db, s, s.brief) is True
    assert record_outcome(db, s, s.brief.model_copy(update={"minutes": 25})) is False
    assert acceptance(db).model_dump() == {"accepted": 1, "edited": 1, "rate": 0.5}
    edited = list_events(db, 1)[0]
    assert edited.kind == "suggestion.edited" and edited.after == {"minutes": 25}


def test_suggestions_api(settings: Settings, tides: Tides) -> None:
    app = create_app(settings, runner=object())  # type: ignore[arg-type]
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        view = client.get("/api/suggestions").json()
        [s] = view["suggestions"]
        r = client.post("/api/suggestions/outcome", json={"suggestion": s, "brief": s["brief"]})
        assert r.json() == {"accepted": True}
        assert client.get("/api/suggestions").json()["acceptance"]["rate"] == 1.0


def test_feedback_changes_the_repeat_suggestion(settings: Settings, store: Store, db: ProfileDB, tides: Tides) -> None:
    from groundcast.profile.feedback import Feedback, get_feedback, set_feedback

    material, _ = tides
    last = _session(material.id, 1, minutes=20)
    set_feedback(db, last.id, Feedback(rating=2, length="too_long", comment="dragged"))
    repeat = next(s for s in suggest(db, settings, store.list_materials(), [last]).suggestions
                  if s.kind == "same_as_last")  # fmt: skip
    assert repeat.brief.minutes == 16 and repeat.score == 0.3
    assert any("too long" in w for w in repeat.why) and any("2 of 5" in w for w in repeat.why)
    set_feedback(db, last.id, Feedback(rating=5, length="right"))
    assert get_feedback(db, last.id).comment == ""
    events = [e for e in list_events(db, 5) if e.kind == "session.feedback"]
    assert events[0].before["comment"] == "dragged" and events[0].after["rating"] == 5


def test_feedback_api(settings: Settings, store: Store, tides: Tides) -> None:
    material, _ = tides
    done = _session(material.id, 1)
    store.save_session(done)
    queued = _session(material.id, 0, SessionStatus.QUEUED)
    store.save_session(queued)
    app = create_app(settings, runner=object())  # type: ignore[arg-type]
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        assert client.get(f"/api/sessions/{done.id}/feedback").json() is None
        r = client.put(f"/api/sessions/{done.id}/feedback", json={"rating": 4, "length": "right", "comment": "good"})
        assert r.status_code == 200 and client.get(f"/api/sessions/{done.id}/feedback").json()["rating"] == 4
        assert client.put(f"/api/sessions/{done.id}/feedback", json={"rating": 9}).status_code == 422
        assert client.put(f"/api/sessions/{queued.id}/feedback", json={"rating": 3}).status_code == 409
        assert client.get("/api/sessions/nope/feedback").status_code == 404
