import os
import struct
import subprocess
import threading
from pathlib import Path
from typing import Any

from groundcast.config import Settings
from groundcast.icon import ico, icns, png
from groundcast.launcher import (
    find_browser,
    health,
    open_window,
    prepare_environment,
    server_url,
    should_stop,
    window_command,
)
from groundcast.shortcuts import desktop_entry, launch_command, linux_shortcuts, mac_bundle, windows_shortcuts


def test_environment_gets_the_conda_folders_once(tmp_path: Path) -> None:
    for d in ("Library/bin", "Scripts", "Library/ssl/certs"):
        (tmp_path / d).mkdir(parents=True)
    (tmp_path / "Library/ssl/cacert.pem").write_text("x")
    env = {"PATH": os.pathsep.join([r"C:\Windows", str(tmp_path / "Scripts")])}
    added = prepare_environment(env, tmp_path, "win32")
    assert added == [str(tmp_path), str(tmp_path / "Library/bin")]  # missing folders and known ones are skipped
    assert env["PATH"].split(os.pathsep)[:2] == added
    assert env["SSL_CERT_FILE"].endswith("cacert.pem") and env["CONDA_PREFIX"] == str(tmp_path)
    prepare_environment(env, tmp_path, "win32")
    assert env["PATH"].count(str(tmp_path / "Library/bin")) == 1


def test_browser_search_expands_paths_and_falls_back_to_names(monkeypatch: Any) -> None:
    monkeypatch.setenv("GC_TEST_DIR", "/opt/edge")
    found = find_browser(["$GC_TEST_DIR/msedge", "%UNSET_GC_VAR%/chrome", "chromium"],
                         which=lambda n: f"/usr/bin/{n}", is_file=lambda p: p == "/opt/edge/msedge")  # fmt: skip
    assert found == "/opt/edge/msedge"
    assert find_browser(["%UNSET_GC_VAR%/chrome", "chromium"], which=lambda n: f"/usr/bin/{n}",
                        is_file=lambda p: True) == "/usr/bin/chromium"  # an unexpanded variable is no path
    assert find_browser(["nothing"], which=lambda n: None) is None


def test_window_opens_as_an_app_or_a_tab(settings: Settings) -> None:
    url = server_url(settings)
    started: list[list[str]] = []
    tabs: list[str] = []
    did = open_window(settings, url, popen=lambda cmd, **kw: started.append(cmd), open_tab=tabs.append,
                      browser_finder=lambda c: "/usr/bin/chromium")  # fmt: skip
    assert started == [window_command("/usr/bin/chromium", url)] and "--app=" + url in started[0]
    assert "app window" in did and tabs == []
    open_window(settings, url, popen=lambda cmd, **kw: started.append(cmd), open_tab=tabs.append,
                browser_finder=lambda c: None)  # fmt: skip
    assert tabs == [url]  # no Chromium-family browser: a tab in the default browser
    quiet = settings.model_copy(update={"launcher": settings.launcher.model_copy(update={"window": "none"})})
    assert "no window" in open_window(quiet, url, popen=lambda *a, **k: 1 / 0, open_tab=lambda u: 1 / 0)


def test_stop_waits_for_the_grace_time_and_for_running_work() -> None:
    assert not should_stop(None, 15, lambda: False)  # a page is open, or none ever was
    assert not should_stop(5.0, 15, lambda: False)
    assert not should_stop(20.0, 15, lambda: True)  # a session is still being made
    assert should_stop(20.0, 15, lambda: False)


def test_health_tells_groundcast_from_other_programs(settings: Settings) -> None:
    import uvicorn

    from groundcast.launcher import make_server
    from groundcast.web.app import create_app

    quiet = settings.model_copy(update={"server": settings.server.model_copy(update={"port": 8791})})
    url = server_url(quiet)
    assert health(url, timeout=0.2) is None
    server = make_server(quiet, create_app(quiet, runner=object()))  # type: ignore[arg-type]
    server.config.log_level = "warning"
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        for _ in range(100):
            if server.started:
                break
            threading.Event().wait(0.05)
        body = health(url)
        assert body and body["can_stop"] is True
    finally:
        server.should_exit = True
        thread.join(10)
    assert isinstance(server, uvicorn.Server) and not thread.is_alive()


def test_icons_are_valid_files() -> None:
    data = png(32)
    assert data[:8] == b"\x89PNG\r\n\x1a\n" and struct.unpack(">II", data[16:24]) == (32, 32)
    icon = ico((16, 256))
    assert struct.unpack("<HHH", icon[:6]) == (0, 1, 2) and icon[6] == 16 and icon[22] == 0  # 0 means 256
    assert icns({128: b"ic07"})[:4] == b"icns"


def test_windows_shortcut_runs_pythonw_with_launch(tmp_path: Path) -> None:
    (tmp_path / "pythonw.exe").write_text("")
    command = launch_command(None, prefix=tmp_path, platform="win32")
    assert command[0] == str(tmp_path / "pythonw.exe") and command[1:] == ["-m", "groundcast", "launch"]
    calls: list[dict[str, Any]] = []

    def run(args: list[str], **kw: Any) -> subprocess.CompletedProcess[str]:
        calls.append({"args": args, **kw})
        return subprocess.CompletedProcess(args, 0, "C:\\Desktop\\groundcast.lnk\n", "")

    made = windows_shortcuts(command, tmp_path / "groundcast.ico", "groundcast", desktop=True, run=run)
    env = calls[0]["env"]
    assert made == ["C:\\Desktop\\groundcast.lnk"] and env["GC_WHERE"] == "Programs,Desktop"
    assert env["GC_TARGET"].endswith("pythonw.exe") and env["GC_ARGS"] == "-m groundcast launch"
    assert "CreateShortcut" in calls[0]["args"][-1]


def test_linux_and_mac_shortcuts(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "share"))
    desk = tmp_path / "Desk"
    desk.mkdir()
    run = lambda args, **kw: subprocess.CompletedProcess(args, 0, str(desk), "")  # noqa: E731
    command = ["/env/bin/python", "-m", "groundcast", "launch"]
    made = linux_shortcuts(command, tmp_path / "g.png", "groundcast", desktop=True, run=run)
    assert made == [str(tmp_path / "share/applications/groundcast.desktop"), str(desk / "groundcast.desktop")]
    entry = Path(made[0]).read_text()
    assert entry == desktop_entry(command, tmp_path / "g.png", "groundcast") and "Terminal=false" in entry
    assert linux_shortcuts(command, tmp_path / "g.png", "groundcast", True, remove=True, run=run) == made
    (tmp_path / "g.icns").write_bytes(icns({128: b"ic07"}))
    [app] = mac_bundle(command, tmp_path / "g.icns", "groundcast", tmp_path / "Apps")
    assert (Path(app) / "Contents/MacOS/groundcast").read_text().endswith("groundcast launch\n")
    assert mac_bundle(command, tmp_path / "g.icns", "groundcast", tmp_path / "Apps", remove=True) == [app]
