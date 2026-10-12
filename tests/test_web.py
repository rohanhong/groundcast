import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from groundcast.config import Settings
from groundcast.models import Brief, SessionRecord
from groundcast.storage import Store
from groundcast.web.app import LOOPBACK_NAMES, create_app, local_request_problem

from .conftest import FIXTURES

ORIGIN = "http://127.0.0.1:8765"


def local_client(app: FastAPI) -> TestClient:
    """A client that talks to the app the way the owner's browser does."""
    return TestClient(app, base_url=ORIGIN)


class RecordingRunner:
    def __init__(self) -> None:
        self.submitted: list[str] = []

    def submit(self, record: SessionRecord) -> None:
        self.submitted.append(record.id)


def test_upload_and_session_flow(settings: Settings) -> None:
    runner = RecordingRunner()
    with local_client(create_app(settings, runner=runner)) as client:  # type: ignore[arg-type]
        assert "groundcast" in client.get("/").text
        with (FIXTURES / "tides.md").open("rb") as fh:
            added = client.post("/api/materials", files=[("files", ("tides.md", fh, "text/markdown"))]).json()
        material_id = added[0]["id"]
        assert client.get(f"/api/materials/{material_id}/chunks").json()[0]["id"].startswith(material_id)
        assert client.get(f"/data/materials/{added[0]['stored_name']}").status_code == 200

        bad = client.post("/api/sessions", json={"focus": "x", "material_ids": ["deadbeef"]})
        assert bad.status_code == 422
        created = client.post("/api/sessions", json={"focus": "tides", "material_ids": [material_id]}).json()
        assert runner.submitted == [created["id"]]
        assert client.get(f"/api/sessions/{created['id']}").json()["status"] == "queued"
        assert client.get("/api/sessions/..%2F..%2Fx").status_code == 404


def test_unsupported_upload_rejected(settings: Settings) -> None:
    with local_client(create_app(settings, runner=RecordingRunner())) as client:  # type: ignore[arg-type]
        r = client.post("/api/materials", files=[("files", ("a.docx", b"x", "application/octet-stream"))])
        assert r.status_code == 422


def test_startup_fails_interrupted_sessions(settings: Settings, store: Store) -> None:
    store.save_session(SessionRecord(id="old-1", brief=Brief(focus="x", material_ids=["a"]), status="running"))
    with local_client(create_app(settings, runner=RecordingRunner())):  # type: ignore[arg-type]
        pass
    assert store.get_session("old-1").status == "failed"


def test_older_sessions_take_their_title_from_the_script(settings: Settings, store: Store) -> None:
    from groundcast.models import Script
    from groundcast.sessions import SCRIPT_FILE
    from groundcast.storage import write_model

    store.save_session(SessionRecord(id="old-2", brief=Brief(focus="x", material_ids=["a"]), status="done"))
    write_model(store.session_dir("old-2") / SCRIPT_FILE, Script(title="How the Moon moves the sea", segments=[]))
    with local_client(create_app(settings, runner=RecordingRunner())) as client:  # type: ignore[arg-type]
        assert client.get("/api/sessions").json()[0]["title"] == "How the Moon moves the sea"
        assert client.get("/api/sessions/old-2").json()["title"] == "How the Moon moves the sea"


def test_foreign_host_and_cross_site_requests_refused(settings: Settings) -> None:
    upload = [("files", ("a.txt", b"Tides follow the Moon.", "text/plain"))]
    with local_client(create_app(settings, runner=RecordingRunner())) as client:  # type: ignore[arg-type]
        # DNS rebinding: another domain resolving to 127.0.0.1.
        assert client.get("/api/materials", headers={"Host": "rebind.example"}).status_code == 403
        # Cross-site form post from another page in the browser.
        r = client.post("/api/materials", files=upload, headers={"Origin": "https://evil.example"})
        assert r.status_code == 403
        r = client.post("/api/materials", files=upload, headers={"Sec-Fetch-Site": "cross-site"})
        assert r.status_code == 403
        # The app's own page, and clients that send no Origin, still work.
        assert client.post("/api/materials", files=upload, headers={"Origin": ORIGIN}).status_code == 200
        assert client.post("/api/materials", files=upload).status_code == 200


@pytest.mark.parametrize(
    ("host", "method", "origin", "fetch_site", "refused"),
    [
        ("127.0.0.1:8765", "GET", None, None, False),
        ("localhost:8765", "GET", "https://evil.example", "cross-site", False),  # reads need a loopback host only
        ("[::1]:8765", "POST", "http://[::1]:8765", "same-origin", False),
        ("evil.example:8765", "GET", None, None, True),
        ("127.0.0.1:8765", "DELETE", "http://127.0.0.1:9999", None, True),
        ("127.0.0.1:8765", "POST", "http://127.0.0.1:8765", "same-site", True),
    ],
)
def test_local_request_rules(host: str, method: str, origin: str | None, fetch_site: str | None, refused: bool) -> None:
    problem = local_request_problem(host, method, origin, fetch_site, LOOPBACK_NAMES, 8765)
    assert (problem is not None) == refused, problem


def test_ui_script_uses_only_ids_the_page_defines() -> None:
    import re
    from importlib import resources

    static = resources.files("groundcast.web").joinpath("static")
    page = static.joinpath("index.html").read_text(encoding="utf-8")
    script = static.joinpath("app.js").read_text(encoding="utf-8")
    defined = set(re.findall(r'\bid="([\w-]+)"', page))
    used = set(re.findall(r'\$\("([\w-]+)"\)', script))
    assert used and used <= defined, sorted(used - defined)
    icons = set(re.findall(r'<symbol id="i-([\w-]+)"', page))
    named = set(re.findall(r'\bicon\("([\w-]+)"', script)) | set(re.findall(r'href="#i-([\w-]+)"', page))
    assert named <= icons, sorted(named - icons)


def test_presence_health_and_shutdown(settings: Settings) -> None:
    from groundcast.web.app import Presence

    now = [100.0]
    presence = Presence(page_timeout_s=60, clock=lambda: now[0])
    assert presence.closed_for() is None  # no page yet: never counts as closed
    presence.check_in("a", True)
    presence.check_in("b", True)
    presence.check_in("a", False)
    assert presence.closed_for() is None  # b is still open
    now[0] = 130.0
    presence.check_in("b", False)
    now[0] = 140.0
    assert presence.closed_for() == 10.0
    presence.check_in("c", True)
    now[0] = 260.0  # c went silent: a crashed tab counts as closed after the timeout
    assert presence.closed_for() is not None

    app = create_app(settings, runner=object())  # type: ignore[arg-type]
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        assert client.get("/api/health").json()["app"] == "groundcast"
        assert client.post("/api/presence", json={"page": "p1"}).status_code == 200
        assert app.state.presence.closed_for() is None
        assert client.post("/api/presence", json={"page": ""}).status_code == 422
        assert client.post("/api/shutdown").status_code == 409  # nothing that can stop it
        stopped = []
        app.state.request_shutdown = lambda: stopped.append(True)
        assert client.post("/api/shutdown").json() == {"stopping": True}
    import time

    time.sleep(0.5)
    assert stopped == [True]
