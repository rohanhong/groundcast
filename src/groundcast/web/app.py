"""Local web service: JSON API, static UI, and read-only access to session files."""

from __future__ import annotations

import json
import shutil
import tempfile
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from importlib import resources
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request, Response, UploadFile
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from groundcast.config import Settings
from groundcast.ingest import ExtractionError, ingest_file
from groundcast.models import Brief, Chunk, Material, SessionRecord
from groundcast.sessions import REPORT_FILE, SessionRunner, fail_interrupted, new_session
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


def create_app(settings: Settings, runner: SessionRunner | None = None) -> FastAPI:
    store = Store(settings.data_dir)

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
        return {"deleted": material_id}

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

    # Session files (MP3, transcript) and the materials they link to.
    app.mount("/data/materials", StaticFiles(directory=store.materials_dir), name="materials")
    app.mount("/data/sessions", StaticFiles(directory=store.sessions_dir), name="sessions")
    static_dir = resources.files("groundcast.web").joinpath("static")
    app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="ui")
    return app
