"""Start groundcast without a terminal: `groundcast launch`, which the desktop shortcut runs.

The shortcut starts Python from the conda environment without activating it,
so the environment's program folders go on PATH first (ffmpeg, Tesseract,
and poppler live there). If groundcast already answers on its port, only a
window opens. Otherwise the service starts, a window opens once it answers,
and the service stops again when no groundcast page has been open for a
while and no work is running. Without a console, output goes to a log file
in the data directory and a start failure shows a message box.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from collections.abc import Callable, MutableMapping
from pathlib import Path
from typing import TYPE_CHECKING, Any, TextIO

from groundcast.config import Settings

if TYPE_CHECKING:
    import uvicorn
    from fastapi import FastAPI

log = logging.getLogger(__name__)

LOG_FILE = "launcher.log"
WATCH_INTERVAL_S = 2.0
WINDOW_TITLE_SUFFIX = "| groundcast"  # app.js titles every view "<view> | groundcast"
BUSY_HEALTH_TIMEOUT_S = 5.0  # a running groundcast may be slow to answer while it voices a session
# Folders `conda activate` puts on PATH, relative to the environment.
CONDA_DIRS_WINDOWS = ("", "Library/mingw-w64/bin", "Library/usr/bin", "Library/bin", "Scripts", "bin")
CONDA_DIRS_POSIX = ("bin",)
# Variables the environment's activation scripts set (openssl), relative to the environment.
CONDA_VARS_WINDOWS = {"SSL_CERT_FILE": "Library/ssl/cacert.pem", "SSL_CERT_DIR": "Library/ssl/certs"}
CONDA_VARS_POSIX = {"SSL_CERT_FILE": "ssl/cacert.pem", "SSL_CERT_DIR": "ssl/certs"}


def prepare_environment(
    environ: MutableMapping[str, str], prefix: Path | None = None, platform: str = sys.platform
) -> list[str]:
    """Do what `conda activate` does for the programs groundcast runs; return the folders added to PATH."""
    prefix = prefix or Path(sys.prefix)
    windows = platform == "win32"
    dirs = [str(prefix / d) if d else str(prefix) for d in (CONDA_DIRS_WINDOWS if windows else CONDA_DIRS_POSIX)]
    current = environ.get("PATH", "").split(os.pathsep) if environ.get("PATH") else []
    known = {os.path.normcase(p) for p in current}
    added = [d for d in dirs if Path(d).is_dir() and os.path.normcase(d) not in known]
    environ["PATH"] = os.pathsep.join(added + current)
    environ.setdefault("CONDA_PREFIX", str(prefix))
    for name, rel in (CONDA_VARS_WINDOWS if windows else CONDA_VARS_POSIX).items():
        if not environ.get(name) and (prefix / rel).exists():
            environ[name] = str(prefix / rel)
    return added


def server_url(settings: Settings) -> str:
    host = settings.server.host
    return f"http://{'[' + host + ']' if ':' in host else host}:{settings.server.port}/"


def health(url: str, timeout: float = 1.0) -> dict[str, Any] | None:
    """What a groundcast service on url says about itself; None when nothing (or something else) answers."""
    try:
        with urllib.request.urlopen(url + "api/health", timeout=timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
    except (OSError, ValueError):
        return None
    return body if isinstance(body, dict) and body.get("app") == "groundcast" else None


def port_free(host: str, port: int) -> bool:
    """Whether nothing listens on host:port. Binding answers at once, where connecting to a closed port
    waits for a timeout on Windows (that cost every start two seconds)."""
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    with socket.socket(family, socket.SOCK_STREAM) as probe:
        try:
            probe.bind((host, port))
        except OSError:
            return False
    return True


def find_browser(
    candidates: list[str],
    which: Callable[[str], str | None] = shutil.which,
    is_file: Callable[[str], bool] = os.path.isfile,
) -> str | None:
    """The first candidate that exists: a path (with %VARS%, $VARS, and ~ expanded) or a program on PATH."""
    for candidate in candidates:
        if any(sep in candidate for sep in ("/", "\\")):
            path = os.path.expanduser(os.path.expandvars(candidate))
            if "%" not in path and "$" not in path and is_file(path):
                return path
        else:
            found = which(candidate)
            if found:
                return found
    return None


def window_command(browser: str, url: str) -> list[str]:
    """A Chromium-family browser showing url as an app: its own window, no tabs or address bar."""
    return [browser, f"--app={url}", "--new-window"]


def focus_window(title_suffix: str = WINDOW_TITLE_SUFFIX, platform: str = sys.platform) -> bool:
    """Bring an open groundcast app window to the front (Windows); False when there is none.

    An app window's title is the page title alone, so a browser window that merely has a groundcast tab
    (its title ends with the browser's name) does not match.
    """
    if platform != "win32":
        return False
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32  # type: ignore[attr-defined]
    found: list[int] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def each(hwnd: int, _: int) -> bool:
        if user32.IsWindowVisible(hwnd):
            length = user32.GetWindowTextLengthW(hwnd)
            title = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, title, length + 1)
            if title.value.endswith(title_suffix):
                found.append(hwnd)
        return True

    user32.EnumWindows(each, 0)
    if not found:
        return False
    if user32.IsIconic(found[0]):
        user32.ShowWindow(found[0], 9)  # SW_RESTORE
    user32.SetForegroundWindow(found[0])
    return True


def open_window(
    settings: Settings,
    url: str,
    popen: Callable[..., Any] = subprocess.Popen,
    open_tab: Callable[[str], bool] = webbrowser.open,
    browser_finder: Callable[[list[str]], str | None] = find_browser,
) -> str:
    """Open the UI as settings.launcher.window says; return what was done, for the log."""
    mode = settings.launcher.window
    if mode == "none":
        return "no window (launcher.window = none)"
    if mode == "app":
        browser = browser_finder(settings.launcher.browsers)
        if browser:
            popen(window_command(browser, url), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                  stderr=subprocess.DEVNULL, close_fds=True)  # fmt: skip
            return f"app window in {browser}"
    open_tab(url)
    return "a tab in the default browser"


def busy(settings: Settings) -> bool:
    """Whether stopping now would cut work short: a session being made, or speech or text being recognised."""
    from groundcast.models import SessionStatus
    from groundcast.storage import Store

    store = Store(settings.data_dir)
    if any(s.status in (SessionStatus.QUEUED, SessionStatus.RUNNING) for s in store.list_sessions()):
        return True
    return any(m.status == "processing" for m in store.list_materials())


def should_stop(closed_for: float | None, grace_s: float, is_busy: Callable[[], bool]) -> bool:
    """Stop once every page has been closed for grace_s and nothing is running (is_busy is checked last)."""
    return closed_for is not None and closed_for >= grace_s and not is_busy()


def make_server(settings: Settings, app: FastAPI) -> uvicorn.Server:
    """A uvicorn server whose app can stop it (POST /api/shutdown)."""
    import uvicorn

    server = uvicorn.Server(uvicorn.Config(app, host=settings.server.host, port=settings.server.port, log_level="info"))

    def stop() -> None:
        server.should_exit = True

    app.state.request_shutdown = stop
    return server


def _log_to_file(settings: Settings) -> TextIO | None:
    """Without a console (pythonw), send output to <data>/logs/launcher.log."""
    if sys.stderr is not None and sys.stdout is not None:
        return None
    folder = settings.data_dir / "logs"
    folder.mkdir(parents=True, exist_ok=True)
    stream = open(folder / LOG_FILE, "a", encoding="utf-8", buffering=1)  # noqa: SIM115 - open until exit
    sys.stdout = sys.stderr = stream
    return stream


def tell(message: str, error: bool = False) -> None:
    """Show a message: in the console when there is one, else in a message box (Windows) and the log."""
    print(message, flush=True)
    if sys.platform == "win32" and (sys.__stderr__ is None or not sys.__stderr__.isatty()):
        try:
            import ctypes

            box = ctypes.windll.user32.MessageBoxW  # type: ignore[attr-defined]
            box(None, message, "groundcast", 0x10 if error else 0x40)  # error or information icon
        except (AttributeError, OSError):
            pass


def launch(settings: Settings, window: str | None = None) -> int:
    """Open groundcast: reuse a running service or start one; stop it when its pages are closed."""
    if window:
        settings = settings.model_copy(update={"launcher": settings.launcher.model_copy(update={"window": window})})
    stream = _log_to_file(settings)
    if stream is not None:  # the handlers made at start-up point at the missing console
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                            stream=stream, force=True)  # fmt: skip
    added = prepare_environment(os.environ)
    log.info("launch: python %s, PATH additions %s", sys.executable, added)
    url = server_url(settings)

    if not port_free(settings.server.host, settings.server.port):
        if health(url, timeout=BUSY_HEALTH_TIMEOUT_S):
            if settings.launcher.window == "app" and focus_window():
                log.info("groundcast already runs at %s; brought its window to the front", url)
            else:
                log.info("groundcast already runs at %s; opening %s", url, open_window(settings, url))
            return 0
        tell(f"Another program uses {url}. Close it, or set another port in the groundcast settings "
             f"(server.port).", error=True)  # fmt: skip
        return 1

    from groundcast.web.app import create_app

    app = create_app(settings)
    server = make_server(settings, app)
    cfg = settings.launcher

    def watch() -> None:
        deadline = time.monotonic() + cfg.ready_timeout_s
        while not server.started:
            if server.should_exit or time.monotonic() > deadline:
                if not server.should_exit:
                    tell(f"groundcast did not start within {cfg.ready_timeout_s:g} s; see {LOG_FILE}.", error=True)
                    server.should_exit = True
                return
            time.sleep(0.1)
        log.info("serving %s; opening %s", url, open_window(settings, url))
        if not cfg.stop_when_closed or cfg.window == "none":
            return
        while not server.should_exit:
            time.sleep(WATCH_INTERVAL_S)
            if should_stop(app.state.presence.closed_for(), cfg.close_grace_s, lambda: busy(settings)):
                log.info("no groundcast page is open and no work is running; stopping")
                server.should_exit = True

    threading.Thread(target=watch, name="groundcast-launcher", daemon=True).start()
    try:
        server.run()
    except SystemExit as exc:  # uvicorn exits when it cannot bind the port
        tell(f"groundcast could not start the service at {url} (exit status {exc.code}).", error=True)
        return 1
    finally:
        if stream is not None:
            stream.flush()
    return 0
