from typing import Any

import numpy as np
import pytest
from fastapi.testclient import TestClient

from groundcast.config import Settings
from groundcast.llm import Role
from groundcast.models import Brief, Chunk, Material, SessionStatus
from groundcast.profile.db import ProfileDB, list_events
from groundcast.profile.preferences import (
    apply_preferences,
    delete_profile,
    effective,
    export_profile,
    load_preferences,
    set_preferences,
    undo,
    voice_choices,
)
from groundcast.sessions import new_session, run_session
from groundcast.storage import Store
from groundcast.tts.base import SilentSynthesizer
from groundcast.web.app import create_app

from .conftest import FakeBackend, scripted_backend

Tides = tuple[Material, list[Chunk]]


@pytest.fixture
def db(settings: Settings) -> ProfileDB:
    return ProfileDB(settings.data_dir)


def test_unset_preferences_use_the_configured_defaults(settings: Settings, db: ProfileDB) -> None:
    values = effective(settings, load_preferences(db))
    assert (values["voice"], values["speed"], values["minutes"]) == (settings.tts.voice, settings.tts.speed, 10)
    set_preferences(db, settings, {"speed": 1.2, "minutes": 15, "quiz_questions": 3, "extract_concepts": False})
    prefs = load_preferences(db)
    assert effective(settings, prefs)["minutes"] == 15
    applied = apply_preferences(settings, prefs)
    assert (applied.tts.speed, applied.quiz.questions, applied.concepts.extract_on_session) == (1.2, 3, False)
    assert settings.tts.speed == 1.0  # the configured settings are not changed


def test_changes_are_logged_and_can_be_undone(settings: Settings, db: ProfileDB) -> None:
    set_preferences(db, settings, {"speed": 1.2})
    set_preferences(db, settings, {"speed": 1.2, "level": "advanced"})  # speed unchanged: not logged again
    set_preferences(db, settings, {"speed": None})  # back to the default
    events = list_events(db, 10)
    assert [(e.subject, e.before["value"], e.after["value"]) for e in events] == [
        ("speed", 1.2, None),
        ("level", None, "advanced"),
        ("speed", None, 1.2),
    ]
    undo(db, settings, events[0].id)
    assert load_preferences(db).speed == 1.2
    latest = list_events(db, 1)[0]
    assert latest.reason == f"undo of change {events[0].id}" and latest.source == "user"


@pytest.mark.parametrize(
    "changes",
    [{"voice": "bf_emma"}, {"voice": "../evil"}, {"speed": 9}, {"minutes": 1}, {"colour": "red"}, {"format": "duo"}],
)
def test_invalid_preferences_are_refused(settings: Settings, db: ProfileDB, changes: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        set_preferences(db, settings, changes)
    assert list_events(db, 1) == []


def test_voice_choices_follow_the_language(settings: Settings) -> None:
    assert voice_choices(settings) and all(v.startswith("a") for v in voice_choices(settings))
    settings.tts.lang_code = "b"
    assert "bf_emma" in voice_choices(settings) and "af_heart" not in voice_choices(settings)


def test_export_and_delete_the_whole_profile(settings: Settings, db: ProfileDB) -> None:
    set_preferences(db, settings, {"level": "advanced"})
    exported = export_profile(db)
    assert exported["preferences"][0]["key"] == "level" and len(exported["events"]) == 1
    delete_profile(db)
    assert load_preferences(db).level is None
    assert [e.kind for e in list_events(db, 10)] == ["profile.deleted"]


class Recorder(SilentSynthesizer):
    voices: list[tuple[str, float]] = []

    def synthesize(self, text: str, voice: str, speed: float) -> np.ndarray:
        Recorder.voices.append((voice, speed))
        return super().synthesize(text, voice, speed)


def test_sessions_use_the_preferences(settings: Settings, store: Store, db: ProfileDB, tides: Tides) -> None:
    material, _ = tides
    set_preferences(db, settings, {"voice": "af_bella", "speed": 1.1, "extract_concepts": False})
    backend = scripted_backend()
    Recorder.voices = []
    factory = lambda s: Recorder(s.tts.sample_rate, s.pipeline.words_per_minute)  # noqa: E731
    record = run_session(new_session(store, Brief(focus="tides", material_ids=[material.id], minutes=2)), store,
                         settings, backend, synth_factory=factory)  # fmt: skip
    assert record.status == SessionStatus.DONE, record.error
    assert set(Recorder.voices) == {("af_bella", 1.1)}
    assert not any(t == "ConceptsOutput" for _, t, _ in backend.calls)  # extraction switched off
    assert "af_bella at 1.1x" in " ".join(record.log)


def test_preferences_api(settings: Settings, db: ProfileDB, tides: Tides) -> None:
    material, _ = tides
    prompts: list[str] = []

    def reply(role: Role, prompt: str, schema: dict[str, Any]) -> dict[str, Any]:
        prompts.append(prompt)
        return {"reply": "ok", "ready": False, "brief": {"focus": "tides", "material_ids": [material.id]}}

    backend = FakeBackend({"ElicitorOutput": reply})
    app = create_app(settings, runner=object(), backend=backend)  # type: ignore[arg-type]
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        view = client.get("/api/preferences").json()
        assert view["preferences"]["voice"] is None and view["effective"]["voice"] == settings.tts.voice
        r = client.put("/api/preferences", json={"changes": {"format": "two_hosts", "voice": "am_adam"}})
        assert r.status_code == 200 and r.json()["effective"]["format"] == "two_hosts"
        assert client.get("/api/settings").json()["voice"] == "am_adam"
        assert client.put("/api/preferences", json={"changes": {"speed": 0}}).status_code == 422
        event = client.get("/api/events").json()[0]
        assert client.post(f"/api/events/{event['id']}/undo").status_code == 200
        assert client.post("/api/events/999/undo").status_code == 404
        client.post("/api/elicit", json={"messages": [{"role": "user", "text": "tides"}]})
        assert "format=two_hosts" in prompts[0]  # the Elicitor sees the preferred defaults
        assert set(client.get("/api/profile/export").json()) >= {"preferences", "concepts", "events"}
        assert client.delete("/api/profile").status_code == 200
        assert client.get("/api/preferences").json()["preferences"]["format"] is None
