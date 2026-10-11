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
    TRANSCRIPT_FILE,
    fail_interrupted,
    new_session,
    run_session,
)
from groundcast.storage import Store, write_text_atomic

from .conftest import scripted_backend

Tides = tuple[Material, list[Chunk]]


def test_session_produces_mp3_and_transcript(settings: Settings, store: Store, tides: Tides) -> None:
    material, _ = tides
    record = new_session(store, Brief(focus="tides", material_ids=[material.id], minutes=2))
    record = run_session(record, store, settings, backend=scripted_backend())
    assert record.status == SessionStatus.DONE, record.error
    d: Path = store.session_dir(record.id)
    for name in (SCRIPT_FILE, REPORT_FILE, AUDIO_FILE, TRANSCRIPT_FILE):
        assert (d / name).is_file(), name
    assert not (d / "session.wav").exists()
    html = (d / TRANSCRIPT_FILE).read_text(encoding="utf-8")
    assert f"../../materials/{material.stored_name}" in html
    assert settings.tts.disclaimer in html


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
