"""Installation check (`groundcast doctor`, GET /api/doctor).

Each check reports ok, missing (a required part is absent: the doctor exits
non-zero), optional (an optional part is not installed), or warn (it works,
but not as well as it could, such as PyTorch on the CPU next to a GPU that
could run it), with the command that fixes it. PyTorch and CTranslate2 are
probed in a separate Python process, so a broken CUDA install cannot take
this process down and the web app does not load them just to check.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel

from groundcast.config import Settings
from groundcast.install import Gpu, detect_gpu, is_installed, load_options, recommend_build

Status = Literal["ok", "missing", "optional", "warn"]

SETUP = "groundcast setup"
ENV_UPDATE = "conda env update -f environment.yml"
PROBE_TIMEOUT_S = 180

_PROBE = """
import importlib.util, json
out = {}
if importlib.util.find_spec("torch"):
    import torch
    cuda = torch.cuda.is_available()
    out["torch"] = {"version": torch.__version__, "cuda": cuda, "device": torch.cuda.get_device_name(0) if cuda else ""}
if importlib.util.find_spec("ctranslate2"):
    import ctranslate2
    out["ctranslate2"] = {"cuda_devices": ctranslate2.get_cuda_device_count()}
print(json.dumps(out))
"""


class Check(BaseModel):
    name: str
    status: Status
    detail: str
    fix: str = ""


def probe_runtime() -> dict[str, Any]:
    """PyTorch's version and CUDA device, and CTranslate2's CUDA device count, from a child process."""
    try:
        proc = subprocess.run([sys.executable, "-c", _PROBE], capture_output=True, text=True,
                              timeout=PROBE_TIMEOUT_S)  # fmt: skip
        return json.loads(proc.stdout.strip().splitlines()[-1]) if proc.returncode == 0 else {"error": proc.stderr}
    except (OSError, subprocess.SubprocessError, ValueError, IndexError) as exc:
        return {"error": str(exc)}


def has_module(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def _writable(folder: Path) -> str:
    """An empty string when files can be written in folder, else the error."""
    try:
        folder.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryFile(dir=folder):
            return ""
    except OSError as exc:
        return str(exc)


def _tool(name: str, binary: str, what: str, which: Callable[[str], str | None], required: bool) -> Check:
    path = which(binary)
    if path:
        return Check(name=name, status="ok", detail=path)
    return Check(name=name, status="missing" if required else "optional", detail=f"{binary} not found ({what})",
                 fix=ENV_UPDATE)  # fmt: skip


def run_checks(
    settings: Settings,
    config_path: Path,
    which: Callable[[str], str | None] = shutil.which,
    module: Callable[[str], bool] = has_module,
    probe: Callable[[], dict[str, Any]] | None = None,
    gpu: Callable[[], Gpu | None] | None = None,
    installed: Callable[[str], bool] = is_installed,
    environ: dict[str, str] | None = None,
) -> list[Check]:
    environ = dict(os.environ if environ is None else environ)
    options = load_options()
    found_gpu = (gpu or (lambda: detect_gpu(options.nvidia_smi)))()
    runtime = (probe or probe_runtime)()
    checks: list[Check] = []

    version = ".".join(map(str, sys.version_info[:3]))
    checks.append(Check(name="Python", status="ok" if sys.version_info[:2] == (3, 12) else "missing",
                        detail=f"{version} ({sys.executable})", fix="conda env create -f environment.yml"))  # fmt: skip
    checks.append(_tool("ffmpeg", settings.audio.ffmpeg_bin, "audio encoding and decoding", which, True))
    checks.append(_tool("poppler", settings.ingest.pdftotext_bin, "PDF text", which, True))
    checks.append(_tool("Tesseract", settings.ocr.tesseract_bin, "text in scans and images", which,
                        settings.ocr.engine == "tesseract"))  # fmt: skip

    # Speech synthesis and PyTorch
    engine = settings.tts.engine
    kokoro = engine == "kokoro"
    piper = settings.tts.piper_command[0]
    if kokoro:
        ready = module("kokoro")
        detail = "Kokoro" if ready else "Kokoro is not installed"
        checks.append(Check(name="Speech synthesis", status="ok" if ready else "missing", detail=detail,
                            fix="" if ready else SETUP))  # fmt: skip
    elif engine == "piper":
        path = which(piper)
        detail = f"Piper ({path})" if path else f"Piper not found ({piper})"
        checks.append(Check(name="Speech synthesis", status="ok" if path else "missing", detail=detail,
                            fix="" if path else f"{SETUP} --piper"))  # fmt: skip
    else:
        checks.append(Check(name="Speech synthesis", status="warn", detail=f"tts.engine is {engine}: no speech"))
    torch = runtime.get("torch")
    recommended = recommend_build(options, found_gpu)
    if torch is None:
        detail = "not installed" + (f" ({runtime['error'].strip().splitlines()[-1]})" if runtime.get("error") else "")
        checks.append(Check(name="PyTorch", status="missing" if kokoro else "optional", detail=detail, fix=SETUP))
    elif torch["cuda"]:
        checks.append(Check(name="PyTorch", status="ok", detail=f"{torch['version']} on {torch['device']}"))
    elif found_gpu is not None and recommended is not None and recommended.cuda is not None:
        detail = f"{torch['version']} runs on the CPU; {found_gpu.name} could run the {recommended.name} build"
        checks.append(Check(name="PyTorch", status="warn", detail=detail, fix=f"{SETUP} --torch {recommended.name}"))
    else:
        checks.append(Check(name="PyTorch", status="ok", detail=f"{torch['version']} on the CPU"))

    # Speech recognition
    asr = options.components["asr"]
    if settings.asr.engine == "none":
        checks.append(Check(name="Speech recognition", status="optional", detail="asr.engine is none"))
    elif not module("faster_whisper"):
        checks.append(Check(name="Speech recognition", status="optional",
                            detail="faster-whisper is not installed (video and audio materials)",
                            fix=f"{SETUP} --asr"))  # fmt: skip
    else:
        devices = (runtime.get("ctranslate2") or {}).get("cuda_devices", 0)
        libs = all(installed(p) for p in asr.gpu_packages)
        if found_gpu is not None and devices and not libs:
            checks.append(Check(name="Speech recognition", status="warn",
                                detail="faster-whisper runs on the CPU: the CUDA 12 libraries are missing",
                                fix=f"{SETUP} --asr"))  # fmt: skip
        else:
            where = "the GPU" if devices and libs else "the CPU"
            checks.append(Check(name="Speech recognition", status="ok", detail=f"faster-whisper on {where}"))

    # Piper, when it is not the main engine
    if engine != "piper":
        path = which(piper)
        checks.append(Check(name="Piper fallback", status="ok" if path else "optional",
                            detail=path or f"{piper} not found", fix="" if path else f"{SETUP} --piper"))  # fmt: skip

    # LLM backend
    llm = settings.llm
    if llm.backend == "claude-cli":
        path = which(llm.claude_bin)
        if path:
            detail = f"Claude Code CLI at {path} (sign-in not checked)"
            checks.append(Check(name="LLM backend", status="ok", detail=detail))
        else:
            fix = 'install Claude Code and sign in, or set llm.backend = "anthropic-api"'
            detail = f"Claude Code CLI not found ({llm.claude_bin})"
            checks.append(Check(name="LLM backend", status="missing", detail=detail, fix=fix))
    else:
        problems = ([] if module("anthropic") else ["the anthropic package is not installed"]) + (
            [] if environ.get(llm.api_key_env) else [f"{llm.api_key_env} is not set"])  # fmt: skip
        checks.append(Check(name="LLM backend", status="missing" if problems else "ok",
                            detail="; ".join(problems) or f"Anthropic API ({llm.api_key_env} set)",
                            fix=f"{SETUP} --api, then set {llm.api_key_env}" if problems else ""))  # fmt: skip

    # Data and settings
    error = _writable(settings.data_dir)
    checks.append(Check(name="Data directory", status="missing" if error else "ok",
                        detail=f"{settings.data_dir}" + (f": {error}" if error else ""),
                        fix="set GROUNDCAST_DATA_DIR to a writable folder" if error else ""))  # fmt: skip
    checks.append(Check(name="Config file", status="ok",
                        detail=str(config_path) if config_path.is_file() else
                        f"{config_path} not found; defaults apply (see config/groundcast.example.toml)"))  # fmt: skip
    return checks


def format_checks(checks: list[Check]) -> str:
    lines = []
    for c in checks:
        lines.append(f"[{c.status:>8}] {c.name}: {c.detail}")
        if c.fix and c.status != "ok":
            lines.append(f"{'':11}fix: {c.fix}")
    return "\n".join(lines)


def failed(checks: list[Check]) -> bool:
    return any(c.status == "missing" for c in checks)
