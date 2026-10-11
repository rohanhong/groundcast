"""Session lifecycle: brief -> pipeline -> audio and transcript (S3 to S9)."""

from __future__ import annotations

import ctypes
import json
import logging
import os
import queue
import secrets
import sys
import threading
from collections.abc import Callable
from datetime import datetime

import numpy as np

from groundcast.audio import Chapter, encode_mp3, silence, write_wav
from groundcast.config import Settings
from groundcast.llm import LLMBackend, make_backend, roles
from groundcast.models import Brief, Chunk, Material, Script, SentenceKind, SessionRecord, SessionStatus, utc_now
from groundcast.pipeline.common import Progress
from groundcast.pipeline.run import Pipeline
from groundcast.profile.concepts import is_extracted
from groundcast.profile.db import ProfileDB
from groundcast.profile.extract import extract_concepts
from groundcast.storage import Store, write_model, write_text_atomic
from groundcast.transcript import render_transcript
from groundcast.tts import Synthesizer, make_synthesizer

log = logging.getLogger(__name__)

SCRIPT_FILE = "script.json"
REPORT_FILE = "report.json"
TIMINGS_FILE = "timings.json"
AUDIO_FILE = "session.mp3"
TRANSCRIPT_FILE = "transcript.html"


def pid_alive(pid: int) -> bool:
    if sys.platform == "win32":
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        code = ctypes.c_ulong()
        ok = kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
        kernel32.CloseHandle(handle)
        return bool(ok) and code.value == 259  # STILL_ACTIVE
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def fail_interrupted(store: Store) -> list[str]:
    """Mark sessions whose process has gone as failed; they can never finish."""
    failed = []
    for record in store.list_sessions():
        if record.status not in (SessionStatus.QUEUED, SessionStatus.RUNNING):
            continue
        if record.pid is not None and record.pid != os.getpid() and pid_alive(record.pid):
            continue
        record.status = SessionStatus.FAILED
        record.error = "Interrupted: the process running it stopped before the session finished."
        record.finished_at = utc_now()
        store.save_session(record)
        failed.append(record.id)
    return failed


def new_session(store: Store, brief: Brief) -> SessionRecord:
    missing = [m for m in brief.material_ids if not store.has_material(m)]
    if missing:
        raise ValueError(f"unknown material IDs: {', '.join(missing)}")
    if not brief.material_ids:
        raise ValueError("the brief selects no materials")
    session_id = f"{datetime.now():%Y%m%d-%H%M%S}-{secrets.token_hex(2)}"
    record = SessionRecord(id=session_id, brief=brief, pid=os.getpid())
    store.save_session(record)
    return record


def render_audio(
    script: Script, synth: Synthesizer, settings: Settings, progress: Progress
) -> tuple[np.ndarray, list[dict[str, object]], list[Chapter]]:
    """Return samples, the start time of every sentence, and one chapter per segment."""
    tts = settings.tts
    voices = {None: tts.voice, "A": tts.voice, "B": tts.second_voice}
    rate = synth.sample_rate
    parts = [synth.synthesize(tts.disclaimer, tts.voice, tts.speed), silence(tts.segment_pause_s, rate)]
    position = sum(len(p) for p in parts)
    timings: list[dict[str, object]] = []
    starts: list[float] = []
    total = len(script.sentences())
    done = 0
    for seg in script.segments:
        # The first chapter also holds the spoken disclaimer before it.
        starts.append(0.0 if not starts else position / rate)
        for s in seg.sentences:
            audio = synth.synthesize(s.text, voices[s.speaker], tts.speed)
            timings.append(
                {"sentence_id": s.id, "segment_id": seg.id, "speaker": s.speaker, "start_s": round(position / rate, 3)}
            )
            pause = tts.recall_pause_s if s.kind == SentenceKind.RECALL else tts.sentence_pause_s
            parts += [audio, silence(pause, rate)]
            position += len(audio) + len(parts[-1])
            done += 1
            if done % 10 == 0:
                progress("render", f"Rendered {done} of {total} sentences")
        parts.append(silence(tts.segment_pause_s, rate))
        position += len(parts[-1])
    ends = starts[1:] + [position / rate]
    chapters = [Chapter(seg.heading, a, b) for seg, a, b in zip(script.segments, starts, ends)]
    return np.concatenate(parts), timings, chapters


def extract_new_concepts(
    backend: LLMBackend, settings: Settings, store: Store, materials: list[Material], progress: Progress
) -> None:
    """Extract the concepts of materials seen for the first time; a failure does not stop the session."""
    db = ProfileDB(settings.data_dir)
    for material in materials:
        if is_extracted(db, material.id):
            continue
        progress("concepts", f"Finding the concepts in {material.filename}")
        try:
            n = extract_concepts(backend, roles(settings.llm)["concepts"], settings, db, material,
                                 store.get_chunks(material.id))  # fmt: skip
            progress("concepts", f"{material.filename}: linked to {n} concepts")
        except Exception as exc:  # noqa: BLE001 - concepts are optional for a session
            log.warning("concept extraction for %s failed", material.id, exc_info=True)
            progress("concepts", f"Skipped concepts for {material.filename}: {exc}")


def run_session(
    record: SessionRecord,
    store: Store,
    settings: Settings,
    backend: LLMBackend | None = None,
    synth_factory: Callable[[Settings], Synthesizer] = make_synthesizer,
    on_update: Callable[[SessionRecord], None] | None = None,
) -> SessionRecord:
    session_dir = store.session_dir(record.id)

    def save() -> None:
        # A failed status write must not end the session; the next save
        # carries the same record.
        try:
            store.save_session(record)
        except OSError as exc:
            log.warning("%s: could not save session status: %s", record.id, exc)

    def progress(stage: str, message: str) -> None:
        record.stage = stage
        record.log.append(f"{utc_now():%H:%M:%S} {message}")
        save()
        log.info("%s: %s", record.id, message)
        if on_update:
            on_update(record)

    record.status = SessionStatus.RUNNING
    record.pid = os.getpid()
    try:
        brief = record.brief
        chunks: list[Chunk] = []
        materials = {}
        for material_id in brief.material_ids:
            materials[material_id] = store.get_material(material_id)
            chunks.extend(store.get_chunks(material_id))
        backend = backend or make_backend(settings.llm)
        if settings.concepts.extract_on_session:
            extract_new_concepts(backend, settings, store, list(materials.values()), progress)
        result = Pipeline(settings, backend, roles(settings.llm)).run(brief, chunks, progress)
        write_model(session_dir / SCRIPT_FILE, result.script)
        write_model(session_dir / REPORT_FILE, result.report)

        progress("render", f"Rendering {result.script.word_count()} words to speech ({settings.tts.engine})")
        synth = synth_factory(settings)
        try:
            samples, timings, chapters = render_audio(result.script, synth, settings, progress)
            rate = synth.sample_rate
        finally:
            synth.close()
        write_text_atomic(session_dir / TIMINGS_FILE, json.dumps(timings, indent=1))
        wav_path = session_dir / "session.wav"
        write_wav(wav_path, samples, rate)
        try:
            encode_mp3(
                wav_path,
                session_dir / AUDIO_FILE,
                settings.audio.ffmpeg_bin,
                settings.audio.mp3_bitrate,
                {"title": result.script.title, "artist": "groundcast", "comment": settings.tts.disclaimer},
                chapters,
            )
        finally:
            wav_path.unlink(missing_ok=True)

        html = render_transcript(
            result.script, {c.id: c for c in chunks}, materials, record.created_at, settings.tts.disclaimer
        )
        write_text_atomic(session_dir / TRANSCRIPT_FILE, html)
        record.status = SessionStatus.DONE
        minutes = len(samples) / rate / 60
        pace = result.script.word_count() / minutes if minutes else 0.0
        progress("done", f"Done: {minutes:.1f} minutes of audio, {pace:.0f} words per minute")
    except Exception as exc:
        log.exception("session %s failed", record.id)
        record.status = SessionStatus.FAILED
        record.error = f"{type(exc).__name__}: {exc}"
        progress("failed", record.error)
    finally:
        record.finished_at = utc_now()
        save()
    return record


class SessionRunner:
    """Runs sessions one at a time in a background thread (one GPU, one CLI)."""

    def __init__(self, store: Store, settings: Settings) -> None:
        self.store = store
        self.settings = settings
        self._queue: queue.Queue[str] = queue.Queue()
        self._thread = threading.Thread(target=self._work, name="session-runner", daemon=True)
        self._thread.start()

    def submit(self, record: SessionRecord) -> None:
        self._queue.put(record.id)

    def _work(self) -> None:
        while True:
            session_id = self._queue.get()
            try:
                run_session(self.store.get_session(session_id), self.store, self.settings)
            except Exception:
                log.exception("session %s crashed", session_id)
            finally:
                self._queue.task_done()
