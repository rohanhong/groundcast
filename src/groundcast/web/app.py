"""Local web service: JSON API, static UI, and read-only access to session files."""

from __future__ import annotations

import json
import logging
import shutil
import os
import tempfile
import threading
import time
from collections.abc import Awaitable, Callable, Iterator
from contextlib import asynccontextmanager, contextmanager
from importlib import resources
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request, Response, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from groundcast.config import Settings, config_file_path
from groundcast.doctor import Check, run_checks
from groundcast.icon import digest as icon_digest
from groundcast.ingest import (
    ExtractionError,
    ingest_file,
    ingest_url,
    interrupted_recognitions,
    recognise_material,
    review_material,
)
from groundcast.ingest.asr import Transcriber
from groundcast.elicit import ChatTurn, ElicitResult, elicit, outline
from groundcast.llm import LLMBackend, make_backend, roles
from groundcast.models import Brief, Chunk, Material, Script, SessionRecord, SessionStatus
from groundcast.profile.concepts import Concept, list_concepts, merge, record_quiz, rename
from groundcast.profile.db import Event, ProfileDB, list_events
from groundcast.profile.preferences import (
    BRIEF_KEYS,
    PreferenceView,
    apply_preferences,
    defaults,
    delete_profile,
    effective,
    export_profile,
    load_preferences,
    set_preferences,
    undo,
    voice_choices,
)
from groundcast.profile.extract import extract_concepts
from groundcast.profile.feedback import Feedback, StoredFeedback, get_feedback, set_feedback
from groundcast.profile.suggest import Suggestion, SuggestionView, record_outcome, suggest
from groundcast.qa import QAExchange, answer_question, load_history, save_history
from groundcast.quiz import AttemptResult, QuizView, grade, load_quizzes, make_quiz, save_quizzes, view
from groundcast.sessions import (
    REPORT_FILE,
    SCRIPT_FILE,
    TIMINGS_FILE,
    SessionRunner,
    fail_interrupted,
    new_session,
)
from groundcast.storage import read_model
from groundcast.storage import Store
from groundcast.transcript import TranscriptView, transcript_view
from groundcast.trash import Trash, TrashConflict, TrashEntry, TrashItem


log = logging.getLogger(__name__)

LOOPBACK_NAMES = frozenset({"127.0.0.1", "localhost", "::1"})
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def _hostname(host_header: str) -> str:
    """Host header without the port; IPv6 literals lose their brackets."""
    if host_header.startswith("["):
        return host_header[1 : host_header.find("]")]
    return host_header.rsplit(":", 1)[0]


def local_request_problem(
    host: str, method: str, origin: str | None, fetch_site: str | None, allowed: frozenset[str], port: int
) -> str | None:
    """Return why a request must be refused, or None.

    Binding to 127.0.0.1 keeps other machines out, but not other web pages in
    the owner's browser: a page can post forms to the app (cross-site request
    forgery) or rebind its own domain to 127.0.0.1 and read the API (DNS
    rebinding). Requests must name a loopback host, and requests that change
    state must not come from another origin.
    """
    if _hostname(host) not in allowed:
        return f"host {host!r} is not a loopback name"
    if method in SAFE_METHODS:
        return None
    if fetch_site is not None and fetch_site not in ("same-origin", "none"):
        return f"cross-site {method} request"
    if origin is not None:
        parts = urlsplit(origin)
        if parts.scheme != "http" or parts.hostname not in allowed or (parts.port or 80) != port:
            return f"{method} from foreign origin {origin!r}"
    return None


class PageCheckIn(BaseModel):
    page: str = Field(min_length=1, max_length=64)  # a random ID per open page
    open: bool = True


class Presence:
    """Which groundcast pages are open, from their check-ins; the launcher stops the service when none are."""

    def __init__(self, page_timeout_s: float, clock: Callable[[], float] = time.monotonic) -> None:
        self.page_timeout_s = page_timeout_s
        self.clock = clock
        self.ever_open = False
        self._pages: dict[str, float] = {}
        self._empty_since: float = clock()
        self._lock = threading.Lock()

    def check_in(self, page: str, is_open: bool) -> None:
        with self._lock:
            self._prune()
            if is_open:
                self._pages[page] = self.clock()
                self.ever_open = True
            elif self._pages.pop(page, None) is not None and not self._pages:
                self._empty_since = self.clock()

    def _prune(self) -> None:
        """Drop pages that stopped checking in; they count as closed when they were last seen."""
        if not self._pages:
            return
        live = {p: t for p, t in self._pages.items() if self.clock() - t < self.page_timeout_s}
        if not live:
            self._empty_since = max(self._pages.values())
        self._pages = live

    def closed_for(self) -> float | None:
        """Seconds since the last page closed, or None while a page is open or before any was."""
        with self._lock:
            self._prune()
            if self._pages or not self.ever_open:
                return None
            return self.clock() - self._empty_since


class Question(BaseModel):
    question: str


class Address(BaseModel):
    url: str


class Review(BaseModel):
    corrections: dict[str, str] = {}  # chunk ID -> corrected text; empty text drops the passage


class Answers(BaseModel):
    answers: list[int | None]


class PreferenceChanges(BaseModel):
    changes: dict[str, object]  # preference name -> new value; null clears it


class Rename(BaseModel):
    name: str


class Merge(BaseModel):
    into: str


class Outcome(BaseModel):
    suggestion: Suggestion
    brief: Brief  # the brief the session was started with


class Conversation(BaseModel):
    messages: list[ChatTurn]
    material_ids: list[str] = []  # selected in the form


def create_app(
    settings: Settings,
    runner: SessionRunner | None = None,
    backend: LLMBackend | None = None,
    transcriber: Transcriber | None = None,
) -> FastAPI:
    store = Store(settings.data_dir)
    profile = ProfileDB(settings.data_dir)
    trash = Trash(store, profile)
    # One question, quiz, or trash change at a time keeps each session's qa.json and quiz.json consistent.
    files_lock = threading.Lock()

    def queue_recognition(material_id: str) -> None:
        def task() -> None:
            try:
                recognise_material(store, settings, material_id, transcriber)
            except ExtractionError as exc:  # recorded on the material
                log.warning("speech recognition of %s failed: %s", material_id, exc)

        app.state.runner.submit_task(task)

    @asynccontextmanager
    async def lifespan(app: FastAPI):  # type: ignore[no-untyped-def]
        fail_interrupted(store)
        trash.purge_expired(settings.trash.keep_days)
        app.state.runner = runner or SessionRunner(store, settings)
        for material in interrupted_recognitions(store):
            queue_recognition(material.id)
        yield

    app = FastAPI(title="Groundcast", lifespan=lifespan)
    app.state.presence = Presence(settings.launcher.page_timeout_s)
    # Set by whoever runs the server (groundcast serve or launch) to stop it from the UI.
    app.state.request_shutdown = None
    allowed_hosts = LOOPBACK_NAMES | {settings.server.host}

    @app.middleware("http")
    async def local_only(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        problem = local_request_problem(
            request.headers.get("host", ""),
            request.method,
            request.headers.get("origin"),
            request.headers.get("sec-fetch-site"),
            allowed_hosts,
            settings.server.port,
        )
        if problem:
            return JSONResponse({"detail": f"Refused: {problem}."}, status_code=403)
        response = await call_next(request)
        if request.url.path.startswith("/data/materials/") and request.url.path.lower().endswith((".html", ".htm")):
            # A saved web page is someone else's HTML: show it without its scripts and
            # outside the app's origin, so it cannot call the API.
            response.headers["Content-Security-Policy"] = "sandbox"
        return response

    def _not_found(exc: Exception) -> HTTPException:
        return HTTPException(status_code=404, detail=str(exc))

    @app.get("/api/settings")
    def get_settings() -> dict[str, object]:
        current = apply_preferences(settings, load_preferences(profile))  # what the next session uses
        return {
            "llm_backend": current.llm.backend,
            "tts_engine": current.tts.engine,
            "voice": current.tts.voice,
            "second_voice": current.tts.second_voice,
            "speed": current.tts.speed,
            "words_per_minute": current.pipeline.words_per_minute,
            "review_below": current.asr.review_below,
            "ocr_review_below": current.ocr.review_below,
            "weak_mastery": current.suggest.weak_mastery,
            "heartbeat_s": settings.launcher.heartbeat_s,
            "trash_keep_days": settings.trash.keep_days,
        }

    @app.get("/api/health")
    def health() -> dict[str, object]:
        """Lets the launcher tell a running groundcast from another program on the port."""
        return {"app": "groundcast", "pid": os.getpid(), "can_stop": app.state.request_shutdown is not None}

    @app.post("/api/presence")
    def check_in(body: PageCheckIn) -> dict[str, bool]:
        app.state.presence.check_in(body.page, body.open)
        return {"ok": True}

    @app.post("/api/shutdown")
    def shutdown() -> dict[str, bool]:
        stop = app.state.request_shutdown
        if stop is None:
            raise HTTPException(status_code=409, detail="This server cannot be stopped from here.")
        threading.Timer(0.3, stop).start()  # after this response has gone out
        return {"stopping": True}

    @app.get("/api/doctor")
    def get_doctor() -> list[Check]:
        """The installation check of `groundcast doctor`; it takes a few seconds (it loads PyTorch elsewhere)."""
        return run_checks(settings, config_file_path())

    @app.get("/api/materials")
    def list_materials() -> list[Material]:
        return store.list_materials()

    @app.post("/api/materials")
    def upload_materials(files: list[UploadFile]) -> list[Material]:
        added = []
        with tempfile.TemporaryDirectory(prefix="groundcast-upload-") as tmp:
            for upload in files:
                name = Path(upload.filename or "upload").name
                path = Path(tmp) / name
                with path.open("wb") as fh:
                    shutil.copyfileobj(upload.file, fh)
                try:
                    material = ingest_file(path, store, settings, filename=name, defer=True)
                except ExtractionError as exc:
                    raise HTTPException(status_code=422, detail=f"{name}: {exc}") from exc
                if material.status == "processing":
                    queue_recognition(material.id)
                added.append(material)
        return added

    @app.post("/api/materials/url")
    def add_web_page(body: Address) -> Material:
        try:
            return ingest_url(body.url, store, settings)
        except ExtractionError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/materials/{material_id}/review")
    def confirm_material(material_id: str, body: Review) -> Material:
        try:
            return review_material(store, material_id, body.corrections)
        except FileNotFoundError as exc:
            raise _not_found(exc) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/materials/{material_id}/retry")
    def retry_material(material_id: str) -> Material:
        try:
            material = store.get_material(material_id)
        except (FileNotFoundError, ValueError) as exc:
            raise _not_found(exc) from exc
        if material.status != "failed":
            raise HTTPException(status_code=409, detail=f"{material.filename} is {material.status}, not failed")
        material.status, material.error = "processing", ""
        store.save_material(material, [])
        queue_recognition(material.id)
        return material

    @app.get("/api/materials/{material_id}/chunks")
    def material_chunks(material_id: str) -> list[Chunk]:
        try:
            return store.get_chunks(material_id)
        except (FileNotFoundError, ValueError) as exc:
            raise _not_found(exc) from exc

    @contextmanager
    def trash_change() -> Iterator[None]:
        """Serialise a change to the trash and turn its errors into HTTP answers."""
        with files_lock:
            try:
                yield
            except (FileNotFoundError, KeyError, ValueError) as exc:
                detail = exc.args[0] if isinstance(exc, KeyError) else exc  # a KeyError's str() adds quotes
                raise HTTPException(status_code=404, detail=str(detail)) from exc
            except TrashConflict as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            except PermissionError as exc:  # Windows: a file is open, such as an MP3 being played
                raise HTTPException(status_code=409, detail=f"A file of it is in use; try again. ({exc})") from exc

    def _entry(item: TrashItem) -> TrashEntry:
        return trash.entry(item, settings.trash.keep_days)

    # A delete answers with the trash entry, so the UI can offer to restore it.
    @app.delete("/api/materials/{material_id}")
    def delete_material(material_id: str) -> TrashEntry:
        with trash_change():
            return _entry(trash.delete_material(material_id))

    @app.post("/api/elicit")
    def elicit_brief(body: Conversation) -> ElicitResult:
        limit = settings.elicit.max_message_chars
        if not body.messages or body.messages[-1].role != "user" or not body.messages[-1].text.strip():
            raise HTTPException(status_code=422, detail="The conversation must end with the learner's message.")
        if any(len(t.text) > limit for t in body.messages):
            raise HTTPException(status_code=422, detail=f"Keep each message under {limit} characters.")
        materials = [m for m in store.list_materials() if m.status == "ready"]
        outlines = {m.id: outline(store.get_chunks(m.id), settings.elicit.outline_words) for m in materials}
        last = next((r.brief for r in store.list_sessions() if r.status == SessionStatus.DONE), None)
        prefs = load_preferences(profile)
        preferred = {k: v for k, v in prefs.model_dump().items() if k in BRIEF_KEYS and v is not None}
        return elicit(
            backend or make_backend(settings.llm),
            roles(settings.llm)["elicitor"],
            settings,
            materials,
            outlines,
            body.messages,
            body.material_ids,
            last,
            preferred,
        )

    @app.post("/api/sessions")
    def create_session(brief: Brief) -> SessionRecord:
        try:
            record = new_session(store, brief)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        app.state.runner.submit(record)
        return record

    def titled(record: SessionRecord) -> SessionRecord:
        # Sessions made before records kept the title take it from their script.
        script = store.session_dir(record.id) / SCRIPT_FILE
        if not record.title and script.is_file():
            try:
                record.title = read_model(script, Script).title
            except (OSError, ValueError):
                pass
        return record

    @app.get("/api/sessions")
    def list_sessions() -> list[SessionRecord]:
        return [titled(r) for r in store.list_sessions()]

    @app.get("/api/sessions/{session_id}")
    def get_session(session_id: str) -> SessionRecord:
        try:
            return titled(store.get_session(session_id))
        except (FileNotFoundError, ValueError) as exc:
            raise _not_found(exc) from exc

    @app.delete("/api/sessions/{session_id}")
    def delete_session(session_id: str) -> TrashEntry:
        with trash_change():
            return _entry(trash.delete_session(titled(store.get_session(session_id))))

    @app.get("/api/sessions/{session_id}/report")
    def get_report(session_id: str) -> dict[str, object]:
        try:
            path = store.session_dir(session_id) / REPORT_FILE
            return json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, ValueError) as exc:
            raise _not_found(exc) from exc

    @app.get("/api/sessions/{session_id}/transcript")
    def get_transcript(session_id: str) -> TranscriptView:
        record = _done_session(session_id, "Transcripts")
        session_dir = store.session_dir(session_id)
        script = read_model(session_dir / SCRIPT_FILE, Script)
        timings_path = session_dir / TIMINGS_FILE
        timings = json.loads(timings_path.read_text(encoding="utf-8")) if timings_path.is_file() else []
        materials: dict[str, Material] = {}
        chunks: dict[str, Chunk] = {}
        for material_id in record.brief.material_ids:  # a removed material only loses its links
            try:
                materials[material_id] = store.get_material(material_id)
                chunks.update((c.id, c) for c in store.get_chunks(material_id))
            except (FileNotFoundError, ValueError):
                continue
        return transcript_view(script, timings, chunks, materials)

    def _done_session(session_id: str, what: str) -> SessionRecord:
        try:
            record = store.get_session(session_id)
        except (FileNotFoundError, ValueError) as exc:
            raise _not_found(exc) from exc
        if record.status != SessionStatus.DONE:
            raise HTTPException(status_code=409, detail=f"{what} open once the session is done.")
        return record

    def _session_sources(record: SessionRecord) -> tuple[dict[str, Material], list[Chunk]]:
        try:
            materials = {m: store.get_material(m) for m in record.brief.material_ids}
            chunks = [c for m in record.brief.material_ids for c in store.get_chunks(m)]
        except (FileNotFoundError, ValueError) as exc:
            raise HTTPException(status_code=409, detail=f"A material of this session is gone: {exc}") from exc
        return materials, chunks

    @app.get("/api/sessions/{session_id}/feedback")
    def read_feedback(session_id: str) -> StoredFeedback | None:
        try:
            store.get_session(session_id)
        except (FileNotFoundError, ValueError) as exc:
            raise _not_found(exc) from exc
        return get_feedback(profile, session_id)

    @app.put("/api/sessions/{session_id}/feedback")
    def write_feedback(session_id: str, body: Feedback) -> StoredFeedback:
        _done_session(session_id, "Feedback")
        return set_feedback(profile, session_id, body)

    @app.get("/api/sessions/{session_id}/questions")
    def list_questions(session_id: str) -> list[QAExchange]:
        try:
            store.get_session(session_id)
            return load_history(store, session_id).exchanges
        except (FileNotFoundError, ValueError) as exc:
            raise _not_found(exc) from exc

    @app.post("/api/sessions/{session_id}/questions")
    def ask_question(session_id: str, body: Question) -> QAExchange:
        question = body.question.strip()
        if not question or len(question) > settings.qa.max_question_chars:
            raise HTTPException(
                status_code=422, detail=f"Ask a question of 1 to {settings.qa.max_question_chars} characters."
            )
        record = _done_session(session_id, "Questions")
        with files_lock:
            materials, chunks = _session_sources(record)
            history = load_history(store, session_id)
            exchange = answer_question(
                backend or make_backend(settings.llm),
                roles(settings.llm),
                settings,
                chunks,
                materials,
                question,
                history.exchanges,
            )
            history.exchanges.append(exchange)
            save_history(store, session_id, history)
        return exchange

    @app.delete("/api/sessions/{session_id}/questions/{exchange_id}")
    def delete_question(session_id: str, exchange_id: str) -> TrashEntry:
        with trash_change():
            return _entry(trash.delete_question(titled(store.get_session(session_id)), exchange_id))

    @app.get("/api/sessions/{session_id}/quizzes")
    def list_quizzes(session_id: str) -> list[QuizView]:
        try:
            store.get_session(session_id)
            data = load_quizzes(store, session_id)
        except (FileNotFoundError, ValueError) as exc:
            raise _not_found(exc) from exc
        return [view(q, data.attempts) for q in data.quizzes]

    @app.post("/api/sessions/{session_id}/quizzes")
    def new_quiz(session_id: str) -> QuizView:
        record = _done_session(session_id, "Quizzes")
        with files_lock:
            materials, chunks = _session_sources(record)
            script = read_model(store.session_dir(session_id) / SCRIPT_FILE, Script)
            concepts = list_concepts(profile, record.brief.material_ids)
            current = apply_preferences(settings, load_preferences(profile))
            quiz = make_quiz(backend or make_backend(settings.llm), roles(settings.llm), current, script, chunks,
                             materials, concepts)  # fmt: skip
            if not quiz.questions:
                raise HTTPException(status_code=502, detail="No question passed the check; try again.")
            data = load_quizzes(store, session_id)
            data.quizzes.append(quiz)
            save_quizzes(store, session_id, data)
        return view(quiz, [])

    @app.post("/api/sessions/{session_id}/quizzes/{quiz_id}/attempts")
    def answer_quiz(session_id: str, quiz_id: str, body: Answers) -> AttemptResult:
        _done_session(session_id, "Quizzes")
        with files_lock:
            data = load_quizzes(store, session_id)
            quiz = next((q for q in data.quizzes if q.id == quiz_id), None)
            if quiz is None:
                raise HTTPException(status_code=404, detail=f"no quiz {quiz_id!r} in session {session_id}")
            try:
                result = grade(quiz, body.answers)
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            data.attempts.append(result.attempt)
            save_quizzes(store, session_id, data)
        answered = [
            (concept, q.id, r.right)
            for q, r in zip(quiz.questions, result.results)
            if r.chosen is not None
            for concept in q.concepts
        ]
        record_quiz(profile, session_id, result.attempt.id, answered)
        return result

    @app.delete("/api/sessions/{session_id}/quizzes/{quiz_id}")
    def delete_quiz(session_id: str, quiz_id: str) -> TrashEntry:
        with trash_change():
            return _entry(trash.delete_quiz(titled(store.get_session(session_id)), quiz_id))

    @app.get("/api/trash")
    def list_trash() -> list[TrashEntry]:
        return [_entry(i) for i in trash.items()]

    @app.post("/api/trash/{item_id}/restore")
    def restore_trash(item_id: str) -> TrashEntry:
        with trash_change():
            return _entry(trash.restore(item_id))

    @app.delete("/api/trash/{item_id}")
    def purge_trash(item_id: str) -> dict[str, list[str]]:
        with trash_change():
            return {"deleted": trash.purge(item_id)}

    @app.delete("/api/trash")
    def empty_trash() -> dict[str, int]:
        with trash_change():
            return {"deleted": trash.empty()}

    @app.get("/api/concepts")
    def get_concepts() -> list[Concept]:
        return list_concepts(profile)

    @app.post("/api/concepts/{concept_id}/rename")
    def rename_concept(concept_id: str, body: Rename) -> list[Concept]:
        try:
            rename(profile, concept_id, body.name)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"no concept {concept_id!r}") from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return list_concepts(profile)

    @app.delete("/api/concepts/{concept_id}")
    def delete_concept(concept_id: str) -> TrashEntry:
        with trash_change():
            return _entry(trash.delete_concept(concept_id))

    @app.post("/api/concepts/{concept_id}/merge")
    def merge_concept(concept_id: str, body: Merge) -> list[Concept]:
        try:
            merge(profile, concept_id, body.into)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"no concept {exc.args[0]!r}") from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return list_concepts(profile)

    @app.post("/api/materials/{material_id}/concepts")
    def find_concepts(material_id: str) -> list[Concept]:
        try:
            material = store.get_material(material_id)
            chunks = store.get_chunks(material_id)
        except (FileNotFoundError, ValueError) as exc:
            raise _not_found(exc) from exc
        if material.status != "ready":
            raise HTTPException(status_code=409, detail=f"{material.filename} is {material.status}, not ready")
        with files_lock:
            extract_concepts(backend or make_backend(settings.llm), roles(settings.llm)["concepts"], settings,
                             profile, material, chunks)  # fmt: skip
        return list_concepts(profile, [material_id])

    @app.get("/api/events")
    def get_events() -> list[Event]:
        return list_events(profile, settings.concepts.events_shown)

    def _preference_view() -> PreferenceView:
        prefs = load_preferences(profile)
        return PreferenceView(preferences=prefs, effective=effective(settings, prefs),
                              voice_choices=voice_choices(settings), defaults=defaults(settings))  # fmt: skip

    @app.get("/api/preferences")
    def get_preferences() -> PreferenceView:
        return _preference_view()

    @app.put("/api/preferences")
    def put_preferences(body: PreferenceChanges) -> PreferenceView:
        try:
            set_preferences(profile, settings, body.changes)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return _preference_view()

    @app.post("/api/events/{event_id}/undo")
    def undo_event(event_id: int) -> PreferenceView:
        try:
            undo(profile, settings, event_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"no event {event_id}") from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return _preference_view()

    @app.get("/api/suggestions")
    def get_suggestions() -> SuggestionView:
        return suggest(profile, settings, store.list_materials(), store.list_sessions())

    @app.post("/api/suggestions/outcome")
    def suggestion_outcome(body: Outcome) -> dict[str, bool]:
        return {"accepted": record_outcome(profile, body.suggestion, body.brief)}

    @app.get("/api/profile/export")
    def get_profile_export() -> dict[str, list[dict[str, object]]]:
        return export_profile(profile)

    @app.delete("/api/profile")
    def remove_profile() -> dict[str, str]:
        delete_profile(profile)
        return {"deleted": "profile"}

    # Session files (MP3, transcript) and the materials they link to.
    app.mount("/data/materials", StaticFiles(directory=store.materials_dir), name="materials")
    app.mount("/data/sessions", StaticFiles(directory=store.sessions_dir), name="sessions")
    static_dir = resources.files("groundcast.web").joinpath("static")

    @app.get("/", include_in_schema=False)
    @app.get("/index.html", include_in_schema=False)
    def page() -> HTMLResponse:
        # The icon addresses carry the drawing's digest: browsers keep a favicon by its address, and an
        # app window shows it as the window icon, so a changed icon would otherwise stay old there.
        html = static_dir.joinpath("index.html").read_text(encoding="utf-8")
        for name in ("favicon.svg", "logo.svg"):
            html = html.replace(f'"{name}"', f'"{name}?v={icon_digest()}"')
        return HTMLResponse(html, headers={"Cache-Control": "no-cache"})

    app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="ui")
    return app
