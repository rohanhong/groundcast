"""Local web service: JSON API, static UI, and read-only access to session files."""

from __future__ import annotations

import json
import shutil
import tempfile
import threading
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from importlib import resources
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request, Response, UploadFile
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from groundcast.config import Settings
from groundcast.ingest import ExtractionError, ingest_file
from groundcast.elicit import ChatTurn, ElicitResult, elicit, outline
from groundcast.llm import LLMBackend, make_backend, roles
from groundcast.models import Brief, Chunk, Material, Script, SessionRecord, SessionStatus
from groundcast.profile.concepts import Concept, forget_material, list_concepts, merge, record_quiz, rename
from groundcast.profile.db import Event, ProfileDB, list_events
from groundcast.profile.extract import extract_concepts
from groundcast.qa import QAExchange, answer_question, load_history, save_history
from groundcast.quiz import AttemptResult, QuizView, grade, load_quizzes, make_quiz, save_quizzes, view
from groundcast.sessions import REPORT_FILE, SCRIPT_FILE, SessionRunner, fail_interrupted, new_session
from groundcast.storage import read_model
from groundcast.storage import Store


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


class Question(BaseModel):
    question: str


class Answers(BaseModel):
    answers: list[int | None]


class Rename(BaseModel):
    name: str


class Merge(BaseModel):
    into: str


class Conversation(BaseModel):
    messages: list[ChatTurn]
    material_ids: list[str] = []  # selected in the form


def create_app(
    settings: Settings, runner: SessionRunner | None = None, backend: LLMBackend | None = None
) -> FastAPI:
    store = Store(settings.data_dir)
    profile = ProfileDB(settings.data_dir)
    # One question or quiz at a time keeps each session's qa.json and quiz.json consistent.
    files_lock = threading.Lock()

    @asynccontextmanager
    async def lifespan(app: FastAPI):  # type: ignore[no-untyped-def]
        fail_interrupted(store)
        app.state.runner = runner or SessionRunner(store, settings)
        yield

    app = FastAPI(title="groundcast", lifespan=lifespan)
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
        return await call_next(request)

    def _not_found(exc: Exception) -> HTTPException:
        return HTTPException(status_code=404, detail=str(exc))

    @app.get("/api/settings")
    def get_settings() -> dict[str, object]:
        return {
            "llm_backend": settings.llm.backend,
            "tts_engine": settings.tts.engine,
            "voice": settings.tts.voice,
            "speed": settings.tts.speed,
            "words_per_minute": settings.pipeline.words_per_minute,
        }

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
                    added.append(ingest_file(path, store, settings, filename=name))
                except ExtractionError as exc:
                    raise HTTPException(status_code=422, detail=f"{name}: {exc}") from exc
        return added

    @app.get("/api/materials/{material_id}/chunks")
    def material_chunks(material_id: str) -> list[Chunk]:
        try:
            return store.get_chunks(material_id)
        except (FileNotFoundError, ValueError) as exc:
            raise _not_found(exc) from exc

    @app.delete("/api/materials/{material_id}")
    def delete_material(material_id: str) -> dict[str, str]:
        try:
            store.delete_material(material_id)
        except (FileNotFoundError, ValueError) as exc:
            raise _not_found(exc) from exc
        forget_material(profile, material_id)
        return {"deleted": material_id}

    @app.post("/api/elicit")
    def elicit_brief(body: Conversation) -> ElicitResult:
        limit = settings.elicit.max_message_chars
        if not body.messages or body.messages[-1].role != "user" or not body.messages[-1].text.strip():
            raise HTTPException(status_code=422, detail="The conversation must end with the learner's message.")
        if any(len(t.text) > limit for t in body.messages):
            raise HTTPException(status_code=422, detail=f"Keep each message under {limit} characters.")
        materials = store.list_materials()
        outlines = {m.id: outline(store.get_chunks(m.id), settings.elicit.outline_words) for m in materials}
        last = next((r.brief for r in store.list_sessions() if r.status == SessionStatus.DONE), None)
        return elicit(
            backend or make_backend(settings.llm),
            roles(settings.llm)["elicitor"],
            settings,
            materials,
            outlines,
            body.messages,
            body.material_ids,
            last,
        )

    @app.post("/api/sessions")
    def create_session(brief: Brief) -> SessionRecord:
        try:
            record = new_session(store, brief)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        app.state.runner.submit(record)
        return record

    @app.get("/api/sessions")
    def list_sessions() -> list[SessionRecord]:
        return store.list_sessions()

    @app.get("/api/sessions/{session_id}")
    def get_session(session_id: str) -> SessionRecord:
        try:
            return store.get_session(session_id)
        except (FileNotFoundError, ValueError) as exc:
            raise _not_found(exc) from exc

    @app.get("/api/sessions/{session_id}/report")
    def get_report(session_id: str) -> dict[str, object]:
        try:
            path = store.session_dir(session_id) / REPORT_FILE
            return json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, ValueError) as exc:
            raise _not_found(exc) from exc

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
            quiz = make_quiz(backend or make_backend(settings.llm), roles(settings.llm), settings, script, chunks,
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
        with files_lock:
            extract_concepts(backend or make_backend(settings.llm), roles(settings.llm)["concepts"], settings,
                             profile, material, chunks)  # fmt: skip
        return list_concepts(profile, [material_id])

    @app.get("/api/events")
    def get_events() -> list[Event]:
        return list_events(profile, settings.concepts.events_shown)

    # Session files (MP3, transcript) and the materials they link to.
    app.mount("/data/materials", StaticFiles(directory=store.materials_dir), name="materials")
    app.mount("/data/sessions", StaticFiles(directory=store.sessions_dir), name="sessions")
    static_dir = resources.files("groundcast.web").joinpath("static")
    app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="ui")
    return app
