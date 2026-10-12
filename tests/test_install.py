import argparse
import subprocess
import sys
from pathlib import Path

import pytest

from groundcast.config import Settings
from groundcast.doctor import Check, failed, format_checks, run_checks
from groundcast.install import (
    KEEP,
    Choices,
    Gpu,
    build_plan,
    current_build,
    default_torch,
    detect_gpu,
    load_options,
    parse_gpu,
    recommend_build,
    run_setup,
)
from groundcast.web.app import create_app

from .test_web import local_client

QUERY = "NVIDIA GeForce RTX 3070 Laptop GPU, 595.97, 8.6\n"
HEADER = """+-----------------------------------------------------------------------------------------+
| NVIDIA-SMI 595.97                 Driver Version: 595.97         CUDA Version: 13.2     |
+-----------------------------------------+------------------------+----------------------+
"""
OPTIONS = load_options()


def gpu(cuda: tuple[int, int], cc: tuple[int, int] = (8, 6)) -> Gpu:
    return Gpu("GPU", "1.0", cuda, cc)


def test_nvidia_smi_output_is_parsed() -> None:
    assert parse_gpu(QUERY, HEADER) == Gpu("NVIDIA GeForce RTX 3070 Laptop GPU", "595.97", (13, 2), (8, 6))
    assert parse_gpu("", HEADER) is None and parse_gpu(QUERY, "no header") is None
    assert parse_gpu("GPU, 1.0, [N/A]", HEADER) is None

    def run(args: list[str], **kw: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args, 0, QUERY if len(args) > 1 else HEADER, "")

    assert detect_gpu("nvidia-smi", run) is not None

    def missing(args: list[str], **kw: object) -> subprocess.CompletedProcess[str]:
        raise FileNotFoundError(args[0])

    assert detect_gpu("nvidia-smi", missing) is None


@pytest.mark.parametrize(
    ("found", "platform", "expected"),
    [
        (gpu((13, 2)), "win32", "cu132"),
        (gpu((13, 1)), "linux", "cu130"),
        (gpu((12, 8)), "win32", "cu126"),
        (gpu((13, 2), cc=(6, 1)), "win32", "cu126"),  # CUDA 13 dropped this GPU
        (gpu((12, 2)), "linux", "cpu"),
        (None, "win32", "cpu"),
        (None, "darwin", "pypi"),
    ],
)
def test_the_newest_runnable_build_is_recommended(found: Gpu | None, platform: str, expected: str) -> None:
    assert recommend_build(OPTIONS, found, platform).name == expected  # type: ignore[union-attr]


def test_an_installed_build_that_suits_the_machine_is_kept() -> None:
    assert current_build(OPTIONS, "2.14.1+cu130", "win32").name == "cu130"  # type: ignore[union-attr]
    assert current_build(OPTIONS, "2.14.1", "darwin").name == "pypi"  # type: ignore[union-attr]
    assert default_torch(OPTIONS, gpu((13, 2)), "2.14.1+cu130", "win32") == KEEP
    assert default_torch(OPTIONS, gpu((13, 2)), "2.14.1+cpu", "win32") == "cu132"  # a GPU it does not use
    assert default_torch(OPTIONS, None, "2.14.1+cpu", "linux") == KEEP
    assert default_torch(OPTIONS, None, None, "linux") == "cpu"


def test_the_plan_installs_only_what_is_missing() -> None:
    have = {"kokoro", "en_core_web_sm"}

    def installed(requirement: str) -> bool:
        return requirement.split(">")[0].split("@")[0].split("=")[0].strip() in have

    choices = Choices("cu130", {"asr": True, "piper": False, "api": False})
    plan = build_plan(OPTIONS, choices, gpu((13, 2)), "2.14.1+cpu", installed)
    assert plan[0].args == ["install", "torch==2.14.1+cu130", "--index-url", "https://download.pytorch.org/whl/cu130"]
    [asr] = plan[1:]
    assert asr.args[1].startswith("faster-whisper") and "nvidia-cudnn-cu12>=9,<10" in asr.args
    # Without a GPU the CUDA libraries are left out; the right build is not installed again.
    plan = build_plan(OPTIONS, choices, None, "2.14.1+cu130", installed)
    assert [s.args[1].split(">")[0] for s in plan] == ["faster-whisper"]
    assert build_plan(OPTIONS, Choices(KEEP, {"piper": True}), None, None, installed)[0].args == ["install", "piper-tts"]


def _args(**kw: object) -> argparse.Namespace:
    base = {"yes": False, "dry_run": False, "torch": None, "asr": None, "piper": None, "api": None, "config": None,
            "claude_bin": "claude", "backend": "claude-cli"}  # fmt: skip
    return argparse.Namespace(**{**base, **kw})


def test_dry_run_prints_the_commands_and_installs_nothing() -> None:
    lines: list[str] = []
    ran: list[list[str]] = []

    def run(args: list[str], **kw: object) -> subprocess.CompletedProcess[str]:
        ran.append(args)
        return subprocess.CompletedProcess(args, 0, "", "")

    status = run_setup(_args(dry_run=True, torch="cpu", piper=True), out=lines.append, run=run,
                       which=lambda name: None, installed=lambda r: False, detect=lambda smi: None,
                       torch_version=lambda: None)  # fmt: skip
    text = "\n".join(lines)
    assert status == 0 and ran == []
    assert "python -m pip install torch==2.14.1+cpu --index-url https://download.pytorch.org/whl/cpu" in text
    assert "piper-tts" in text and "Dry run" in text
    assert "anthropic" in text  # no Claude Code CLI: the API backend is recommended


def test_interactive_setup_asks_then_runs_pip_and_the_doctor() -> None:
    answers = iter(["", "n", "y", "n", ""])  # recommended build; no ASR; Piper; no API; run
    ran: list[list[str]] = []

    def run(args: list[str], **kw: object) -> subprocess.CompletedProcess[str]:
        ran.append(args)
        return subprocess.CompletedProcess(args, 0, "", "")

    status = run_setup(_args(), out=lambda line: None, ask=lambda prompt: next(answers), run=run,
                       which=lambda name: "/bin/claude", installed=lambda r: False,
                       detect=lambda smi: gpu((13, 2)), torch_version=lambda: None)  # fmt: skip
    assert status == 0
    expected = "cu132" if sys.platform != "darwin" else None
    pip = [a for a in ran if a[1:3] == ["-m", "pip"]]
    if expected:
        assert any(f"torch==2.14.1+{expected}" in a for a in pip)
    assert any("piper-tts" in a for a in pip) and not any(any("faster-whisper" in x for x in a) for a in pip)
    assert ran[-1][-1] == "doctor"


def test_an_unknown_build_is_refused() -> None:
    lines: list[str] = []
    assert run_setup(_args(yes=True, torch="cu999"), out=lines.append, which=lambda n: None,
                     detect=lambda smi: None, torch_version=lambda: None) == 2  # fmt: skip
    assert "Unknown PyTorch build" in lines[-1]


def _checks(settings: Settings, tmp_path: Path, **kw: object) -> list[Check]:
    defaults: dict[str, object] = {
        "which": lambda name: f"/usr/bin/{name}",
        "module": lambda name: True,
        "probe": lambda: {"torch": {"version": "2.14.1+cpu", "cuda": False, "device": ""},
                          "ctranslate2": {"cuda_devices": 0}},
        "gpu": lambda: None,
        "installed": lambda requirement: True,
        "environ": {},
    }  # fmt: skip
    return run_checks(settings, tmp_path / "absent.toml", **{**defaults, **kw})  # type: ignore[arg-type]


def test_doctor_reports_each_part_with_a_fix(settings: Settings, tmp_path: Path) -> None:
    checks = _checks(settings, tmp_path)
    by_name = {c.name: c for c in checks}
    assert not failed(checks) and by_name["PyTorch"].detail == "2.14.1+cpu on the CPU"
    assert by_name["Speech synthesis"].status == "warn"  # the test settings use the silent engine
    assert "defaults apply" in by_name["Config file"].detail

    missing = _checks(settings, tmp_path, which=lambda name: None, gpu=lambda: gpu((13, 2)))
    by_name = {c.name: c for c in missing}
    assert failed(missing)
    assert by_name["ffmpeg"].status == "missing" and by_name["ffmpeg"].fix == "conda env update -f environment.yml"
    assert by_name["LLM backend"].status == "missing"
    assert by_name["Piper fallback"].status == "optional" and by_name["Piper fallback"].fix.endswith("--piper")
    assert by_name["PyTorch"].status == "warn" and by_name["PyTorch"].fix.endswith("--torch cu132")
    assert "fix: conda env update" in format_checks(missing)


def test_doctor_checks_kokoro_and_the_api_backend(settings: Settings, tmp_path: Path) -> None:
    kokoro = settings.model_copy(update={"tts": settings.tts.model_copy(update={"engine": "kokoro"}),
                                         "llm": settings.llm.model_copy(update={"backend": "anthropic-api"})})  # fmt: skip
    checks = _checks(kokoro, tmp_path, module=lambda name: name != "kokoro", probe=lambda: {})
    by_name = {c.name: c for c in checks}
    assert by_name["Speech synthesis"].status == "missing" and by_name["PyTorch"].status == "missing"
    assert by_name["LLM backend"].detail == "ANTHROPIC_API_KEY is not set"
    ready = _checks(kokoro, tmp_path, environ={"ANTHROPIC_API_KEY": "x"})
    assert {c.name: c for c in ready}["LLM backend"].status == "ok"


def test_doctor_endpoint(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    import groundcast.doctor as doctor

    monkeypatch.setattr(doctor, "probe_runtime", lambda: {})
    monkeypatch.setattr(doctor, "detect_gpu", lambda smi: None)
    with local_client(create_app(settings, runner=object())) as client:  # type: ignore[arg-type]
        rows = client.get("/api/doctor").json()
    assert {"Python", "ffmpeg", "LLM backend", "Data directory"} <= {r["name"] for r in rows}
    assert all(set(r) == {"name", "status", "detail", "fix"} for r in rows)
    assert all(r["status"] in ("ok", "missing", "optional", "warn") for r in rows)
