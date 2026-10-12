import json
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from groundcast.config import Settings
from groundcast.models import Brief, Chunk, Material, SessionRecord, SessionStatus
from groundcast.sessions import (
    AUDIO_FILE,
    REPORT_FILE,
    SCRIPT_FILE,
    TIMINGS_FILE,
    TRANSCRIPT_FILE,
    fail_interrupted,
    new_session,
    run_session,
)
from groundcast.storage import Store, write_text_atomic
from groundcast.tts.base import SilentSynthesizer

from .conftest import recall_backend, scripted_backend

Tides = tuple[Material, list[Chunk]]


def test_session_produces_mp3_and_transcript(settings: Settings, store: Store, tides: Tides) -> None:
    material, _ = tides
    record = new_session(store, Brief(focus="tides", material_ids=[material.id], minutes=2))
    record = run_session(record, store, settings, backend=scripted_backend())
    assert record.status == SessionStatus.DONE, record.error
    script = json.loads((store.session_dir(record.id) / SCRIPT_FILE).read_text(encoding="utf-8"))
    assert store.get_session(record.id).title == script["title"]  # the list shows the Writer's title
    d: Path = store.session_dir(record.id)
    for name in (SCRIPT_FILE, REPORT_FILE, AUDIO_FILE, TRANSCRIPT_FILE):
        assert (d / name).is_file(), name
    assert not (d / "session.wav").exists()
    html = (d / TRANSCRIPT_FILE).read_text(encoding="utf-8")
    assert f"../../materials/{material.id}.view.html#p1-1" in html
    assert settings.tts.disclaimer in html
    # One ID3 chapter per segment, titled with its heading.
    head = (d / AUDIO_FILE).read_bytes()[:4096]
    assert b"CTOC" in head and head.count(b"CHAP") == 2
    assert b"What causes tides" in head and b"Spring tides" in head


def test_session_failure_is_recorded(settings: Settings, store: Store, tides: Tides) -> None:
    material, _ = tides
    backend = scripted_backend()
    backend.handlers["Draft"] = lambda role, prompt, schema: {"title": "x", "segments": []}
    record = run_session(new_session(store, Brief(focus="t", material_ids=[material.id])), store, settings, backend)
    assert record.status == SessionStatus.FAILED
    assert "empty script" in record.error
    assert store.get_session(record.id).status == SessionStatus.FAILED


def test_only_sessions_of_stopped_processes_fail(store: Store) -> None:
    brief = Brief(focus="x", material_ids=["a"])
    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait()
    alive = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        store.save_session(SessionRecord(id="no-pid", brief=brief, status="running"))
        store.save_session(SessionRecord(id="dead-pid", brief=brief, status="running", pid=dead.pid))
        store.save_session(SessionRecord(id="live-pid", brief=brief, status="running", pid=alive.pid))
        assert sorted(fail_interrupted(store)) == ["dead-pid", "no-pid"]
        assert store.get_session("live-pid").status == SessionStatus.RUNNING
    finally:
        alive.kill()
        alive.wait()


def test_status_write_failure_does_not_end_session(
    settings: Settings, store: Store, tides: Tides, monkeypatch: pytest.MonkeyPatch
) -> None:
    material, _ = tides
    record = new_session(store, Brief(focus="tides", material_ids=[material.id], minutes=2))
    real_save = store.save_session
    calls = {"n": 0}

    def flaky_save(r: SessionRecord) -> None:
        calls["n"] += 1
        if calls["n"] == 1:
            raise PermissionError(5, "file in use")
        real_save(r)

    monkeypatch.setattr(store, "save_session", flaky_save)
    record = run_session(record, store, settings, backend=scripted_backend())
    assert record.status == SessionStatus.DONE, record.error
    assert store.get_session(record.id).status == SessionStatus.DONE
    assert "words per minute" in record.log[-1]


def test_atomic_write_waits_for_a_reader(tmp_path: Path) -> None:
    target = tmp_path / "session.json"
    target.write_text("old", encoding="utf-8")
    reader = target.open("r", encoding="utf-8")  # on Windows this blocks os.replace
    threading.Thread(target=lambda: (time.sleep(0.2), reader.close()), daemon=True).start()
    write_text_atomic(target, "new")
    assert target.read_text(encoding="utf-8") == "new"


class VoiceRecorder(SilentSynthesizer):
    def __init__(self, settings: Settings) -> None:
        super().__init__(settings.tts.sample_rate, settings.pipeline.words_per_minute)
        self.voices: list[tuple[str, str]] = []

    def synthesize(self, text: str, voice: str, speed: float):  # type: ignore[no-untyped-def]
        self.voices.append((text, voice))
        return super().synthesize(text, voice, speed)


def test_two_host_session_uses_two_voices(settings: Settings, store: Store, tides: Tides) -> None:
    material, _ = tides
    synths: list[VoiceRecorder] = []

    def factory(s: Settings) -> VoiceRecorder:
        synths.append(VoiceRecorder(s))
        return synths[-1]

    brief = Brief(focus="tides", material_ids=[material.id], minutes=2, format="two_hosts")
    record = run_session(new_session(store, brief), store, settings, scripted_backend(), synth_factory=factory)
    assert record.status == SessionStatus.DONE, record.error
    voices = dict(synths[0].voices)
    assert voices[settings.tts.disclaimer] == settings.tts.voice
    assert voices["It's the Moon that causes tides."] == settings.tts.voice  # Host A
    assert voices["The Moon is the main cause."] == settings.tts.second_voice  # Host B
    html = (store.session_dir(record.id) / TRANSCRIPT_FILE).read_text(encoding="utf-8")
    assert '<span class="speaker">Host B</span>' in html


def test_recall_question_is_followed_by_a_pause(settings: Settings, store: Store, tides: Tides) -> None:
    material, chunks = tides
    brief = Brief(focus="tides", material_ids=[material.id], minutes=2, recall_prompts=True)
    record = run_session(new_session(store, brief), store, settings, recall_backend(chunks[0].id))
    assert record.status == SessionStatus.DONE, record.error
    d = store.session_dir(record.id)
    starts = {t["sentence_id"]: t["start_s"] for t in json.loads((d / TIMINGS_FILE).read_text(encoding="utf-8"))}
    question_words = len("What causes tides?".split())
    spoken = question_words * 60 / settings.pipeline.words_per_minute
    assert starts["s1.3"] - starts["s1.2"] >= spoken + settings.tts.recall_pause_s - 0.01
    assert 'class="recall"' in (d / TRANSCRIPT_FILE).read_text(encoding="utf-8")


def test_transcript_api_times_sentences_and_numbers_sources(settings: Settings, store: Store, tides: Tides) -> None:
    from fastapi.testclient import TestClient

    from groundcast.web.app import create_app

    material, _ = tides
    record = run_session(new_session(store, Brief(focus="tides", material_ids=[material.id], minutes=2)), store,
                         settings, backend=scripted_backend())  # fmt: skip
    queued = new_session(store, Brief(focus="tides", material_ids=[material.id]))
    app = create_app(settings, runner=object())  # type: ignore[arg-type]
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        view = client.get(f"/api/sessions/{record.id}/transcript").json()
        assert client.get(f"/api/sessions/{queued.id}/transcript").status_code == 409
    sentences = [s for seg in view["segments"] for s in seg["sentences"]]
    starts = [s["start_s"] for s in sentences]
    assert starts == sorted(starts) and starts[0] > 0  # the spoken notice comes first
    assert view["segments"][0]["start_s"] == 0.0 and view["segments"][1]["start_s"] > 0
    cited = [n for s in sentences for n in s["sources"]]
    assert cited and set(cited) == set(range(1, len(view["sources"]) + 1))
    assert view["sources"][cited[0] - 1]["path"].startswith(f"materials/{material.id}")
