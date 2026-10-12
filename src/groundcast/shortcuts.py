"""Desktop and menu shortcuts that start groundcast with `groundcast launch`, no terminal needed.

Windows: .lnk files on the desktop and in the Start menu, made through the
WScript.Shell COM object in PowerShell; they run the environment's
pythonw.exe, which opens no console. Linux: a .desktop entry in the
applications menu, copied to the desktop. macOS: a small groundcast.app in
~/Applications. The icon files are drawn by groundcast.icon into the data
directory.
"""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from groundcast.config import Settings
from groundcast.icon import write_icons

ICON_FOLDER = "app"  # inside the data directory
DESCRIPTION = "Study audio, grounded in your materials"
# PowerShell that makes or removes one shortcut per special folder; values come in environment variables.
WINDOWS_SCRIPT = r"""
$shell = New-Object -ComObject WScript.Shell
foreach ($where in $env:GC_WHERE.Split(',')) {
  $path = Join-Path ([Environment]::GetFolderPath($where)) ($env:GC_NAME + '.lnk')
  if ($env:GC_REMOVE -eq '1') {
    if (Test-Path -LiteralPath $path) { Remove-Item -LiteralPath $path; Write-Output $path }
    continue
  }
  $link = $shell.CreateShortcut($path)
  $link.TargetPath = $env:GC_TARGET
  $link.Arguments = $env:GC_ARGS
  $link.WorkingDirectory = $env:GC_WORKDIR
  $link.IconLocation = $env:GC_ICON + ',0'
  $link.Description = $env:GC_DESC
  $link.Save()
  Write-Output $path
}
"""

Runner = Callable[..., Any]


def launch_command(config: str | None = None, prefix: Path | None = None, platform: str = sys.platform) -> list[str]:
    """The program and arguments a shortcut runs; on Windows pythonw.exe, so no console opens."""
    python = Path(sys.executable)
    if platform == "win32":
        windowless = (prefix or python.parent) / "pythonw.exe"
        python = windowless if windowless.is_file() else python
    command = [str(python), "-m", "groundcast"]
    if config:
        command += ["--config", str(Path(config).resolve())]
    return command + ["launch"]


def windows_shortcuts(
    command: list[str], icon: Path, name: str, desktop: bool, remove: bool = False, run: Runner = subprocess.run
) -> list[str]:
    where = ["Programs"] + (["Desktop"] if desktop else [])
    env = {
        **os.environ, "GC_WHERE": ",".join(where), "GC_NAME": name, "GC_TARGET": command[0],
        "GC_ARGS": subprocess.list2cmdline(command[1:]), "GC_WORKDIR": str(Path.home()), "GC_ICON": str(icon),
        "GC_DESC": DESCRIPTION, "GC_REMOVE": "1" if remove else "0",
    }  # fmt: skip
    result = run(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command",
                  WINDOWS_SCRIPT], env=env, capture_output=True, text=True)  # fmt: skip
    if result.returncode:
        raise OSError(f"PowerShell could not make the shortcuts: {result.stderr.strip()}")
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def desktop_entry(command: list[str], icon: Path, name: str) -> str:
    return "\n".join([
        "[Desktop Entry]", "Type=Application", f"Name={name}", f"Comment={DESCRIPTION}",
        f"Exec={shlex.join(command)}", f"Icon={icon}", "Terminal=false", "Categories=Education;", "",
    ])  # fmt: skip


def linux_desktop_dir(run: Runner = subprocess.run) -> Path | None:
    try:
        out = run(["xdg-user-dir", "DESKTOP"], capture_output=True, text=True).stdout.strip()
    except OSError:
        out = ""
    folder = Path(out) if out else Path.home() / "Desktop"
    return folder if folder.is_dir() and folder != Path.home() else None


def linux_shortcuts(
    command: list[str], icon: Path, name: str, desktop: bool, remove: bool = False, run: Runner = subprocess.run
) -> list[str]:
    data_home = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    targets = [data_home / "applications" / "groundcast.desktop"]
    folder = linux_desktop_dir(run) if desktop else None
    if folder:
        targets.append(folder / "groundcast.desktop")
    done = []
    for path in targets:
        if remove:
            if path.exists():
                path.unlink()
                done.append(str(path))
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(desktop_entry(command, icon, name), encoding="utf-8")
        path.chmod(0o755)  # desktops start only executable entries
        done.append(str(path))
    return done


def mac_bundle(command: list[str], icns: Path, name: str, folder: Path, remove: bool = False) -> list[str]:
    import shutil

    app = folder / f"{name}.app"
    if remove:
        if app.exists():
            shutil.rmtree(app)
            return [str(app)]
        return []
    (app / "Contents" / "MacOS").mkdir(parents=True, exist_ok=True)
    (app / "Contents" / "Resources").mkdir(parents=True, exist_ok=True)
    script = app / "Contents" / "MacOS" / "groundcast"
    script.write_text(f"#!/bin/sh\nexec {shlex.join(command)}\n", encoding="utf-8")
    script.chmod(0o755)
    shutil.copyfile(icns, app / "Contents" / "Resources" / "groundcast.icns")
    plist = {"CFBundleName": name, "CFBundleExecutable": "groundcast", "CFBundleIconFile": "groundcast",
             "CFBundleIdentifier": "local.groundcast", "CFBundlePackageType": "APPL"}  # fmt: skip
    entries = "".join(f"<key>{k}</key><string>{v}</string>" for k, v in plist.items())
    (app / "Contents" / "Info.plist").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n<plist version="1.0"><dict>' + entries + "</dict></plist>\n",
        encoding="utf-8",
    )
    return [str(app)]


def make_shortcuts(
    settings: Settings,
    desktop: bool = True,
    remove: bool = False,
    config: str | None = None,
    platform: str = sys.platform,
    run: Runner = subprocess.run,
) -> list[str]:
    """Make (or remove) the shortcuts for this platform; return the paths touched."""
    command = launch_command(config, platform=platform)
    name = settings.launcher.shortcut_name
    icons = write_icons(settings.data_dir / ICON_FOLDER) if not remove else {}
    if platform == "win32":
        return windows_shortcuts(command, icons.get("ico", Path()), name, desktop, remove, run)
    if platform == "darwin":
        return mac_bundle(command, icons.get("icns", Path()), name, Path.home() / "Applications", remove)
    return linux_shortcuts(command, icons.get("png", Path()), name, desktop, remove, run)
