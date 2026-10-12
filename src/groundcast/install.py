"""One-step installation of the optional parts (`groundcast setup`).

The choices come from install.toml: the PyTorch builds and the optional
components. Setup finds an NVIDIA GPU with nvidia-smi, recommends the newest
PyTorch build that the GPU and its driver can run (or keeps an installed
build that suits the machine), asks about each optional part (Enter takes
the recommendation; --yes takes every recommendation), shows the pip
commands, and runs them with this Python. PyTorch goes first, so the chosen
build already meets Kokoro's own torch requirement. Only missing packages
are installed; versions already present are left alone.
"""

from __future__ import annotations

import argparse
import importlib.metadata as md
import re
import shlex
import shutil
import subprocess
import sys
import tomllib
from collections.abc import Callable
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path

KEEP = "keep"
Version = tuple[int, int]
Runner = Callable[..., subprocess.CompletedProcess[str]]


@dataclass(frozen=True)
class Gpu:
    name: str
    driver: str
    cuda: Version  # the highest CUDA version the driver supports
    compute_capability: Version


@dataclass(frozen=True)
class TorchBuild:
    name: str
    label: str
    index_url: str  # empty: the default package index, whose versions have no local label
    platforms: list[str]
    cuda: Version | None = None
    min_compute_capability: Version | None = None

    def runs_on(self, gpu: Gpu | None) -> bool:
        if self.cuda is None:
            return True
        if gpu is None or gpu.cuda < self.cuda:
            return False
        return self.min_compute_capability is None or gpu.compute_capability >= self.min_compute_capability


@dataclass(frozen=True)
class Component:
    key: str
    label: str
    extra: str = ""
    packages: list[str] = field(default_factory=list)
    gpu_packages: list[str] = field(default_factory=list)
    gpu_min_cuda: Version | None = None
    required: bool = False
    recommended: bool = False


@dataclass(frozen=True)
class Options:
    nvidia_smi: str
    torch_version: str
    builds: list[TorchBuild]
    components: dict[str, Component]

    def build(self, name: str) -> TorchBuild:
        return next(b for b in self.builds if b.name == name)


@dataclass(frozen=True)
class Step:
    what: str
    args: list[str]  # pip arguments


def _version(text: str) -> Version:
    major, _, minor = text.strip().partition(".")
    return int(major), int(minor or 0)


def load_options(text: str | None = None) -> Options:
    if text is None:
        text = resources.files("groundcast").joinpath("install.toml").read_text(encoding="utf-8")
    data = tomllib.loads(text)
    builds = [
        TorchBuild(
            name=b["name"],
            label=b["label"],
            index_url=b.get("index_url", ""),
            platforms=b["platforms"],
            cuda=_version(b["cuda"]) if "cuda" in b else None,
            min_compute_capability=_version(b["min_compute_capability"]) if "min_compute_capability" in b else None,
        )
        for b in data["torch"]["builds"]
    ]
    components = {
        key: Component(
            key=key,
            label=c["label"],
            extra=c.get("extra", ""),
            packages=c.get("packages", []),
            gpu_packages=c.get("gpu_packages", []),
            gpu_min_cuda=_version(c["gpu_min_cuda"]) if "gpu_min_cuda" in c else None,
            required=c.get("required", False),
            recommended=c.get("recommended", False),
        )
        for key, c in data["components"].items()
    }
    return Options(data["nvidia_smi"], data["torch"]["version"], builds, components)


# Detection


def parse_gpu(query: str, header: str) -> Gpu | None:
    """The first GPU in `nvidia-smi --query-gpu=name,driver_version,compute_cap --format=csv,noheader`,
    with the driver's CUDA version from the header of plain `nvidia-smi`."""
    first = next((line for line in query.splitlines() if line.strip()), "")
    parts = [p.strip() for p in first.split(",")]
    cuda = re.search(r"CUDA Version:\s*(\d+\.\d+)", header)
    if len(parts) < 3 or cuda is None:
        return None
    try:
        return Gpu(parts[0], parts[1], _version(cuda.group(1)), _version(parts[2]))
    except ValueError:
        return None


def detect_gpu(nvidia_smi: str, run: Runner = subprocess.run) -> Gpu | None:
    try:
        query = run([nvidia_smi, "--query-gpu=name,driver_version,compute_cap", "--format=csv,noheader"],
                    capture_output=True, text=True, timeout=30)  # fmt: skip
        header = run([nvidia_smi], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    if query.returncode or header.returncode:
        return None
    return parse_gpu(query.stdout, header.stdout)


def platform_builds(options: Options, platform: str = sys.platform) -> list[TorchBuild]:
    return [b for b in options.builds if any(platform.startswith(p) for p in b.platforms)]


def recommend_build(options: Options, gpu: Gpu | None, platform: str = sys.platform) -> TorchBuild | None:
    """The newest CUDA build the GPU and driver can run, else the platform's build without CUDA."""
    builds = platform_builds(options, platform)
    runnable = [b for b in builds if b.cuda is not None and b.runs_on(gpu)]
    if runnable:
        return max(runnable, key=lambda b: b.cuda or (0, 0))
    return next((b for b in builds if b.cuda is None), None)


def installed_version(name: str) -> str | None:
    try:
        return md.version(name)
    except md.PackageNotFoundError:
        return None


def current_build(options: Options, version: str | None, platform: str = sys.platform) -> TorchBuild | None:
    """The build of an installed torch version, from its local label (2.14.1+cu130 is cu130)."""
    if version is None:
        return None
    label = version.partition("+")[2]
    for b in platform_builds(options, platform):
        if (b.name == label) if b.index_url else not label:
            return b
    return None


def default_torch(options: Options, gpu: Gpu | None, version: str | None, platform: str = sys.platform) -> str:
    """Keep an installed build that suits this machine (GPU or not, as it can be); else the recommended one."""
    recommended = recommend_build(options, gpu, platform)
    current = current_build(options, version, platform)
    if recommended is None:
        return KEEP
    if current is not None and current.runs_on(gpu) and (current.cuda is None) == (recommended.cuda is None):
        return KEEP
    return recommended.name


def torch_requirement(options: Options, build: TorchBuild) -> str:
    local = f"+{build.name}" if build.index_url else ""
    return f"torch=={options.torch_version}{local}"


def extra_requirements(extra: str) -> list[str]:
    """The requirements of one of this package's extras: from pyproject.toml in a source checkout
    (an editable install's metadata goes stale when the extras change), else from the installed metadata."""
    pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
    if pyproject.is_file():
        project = tomllib.loads(pyproject.read_text(encoding="utf-8")).get("project", {})
        if project.get("name") == "groundcast":
            return list(project.get("optional-dependencies", {}).get(extra, []))
    out = []
    for line in md.requires("groundcast") or []:
        requirement, _, marker = line.partition(";")
        if re.search(r"""extra\s*==\s*["']%s["']""" % re.escape(extra), marker):
            out.append(requirement.strip())
    return out


def is_installed(requirement: str) -> bool:
    name = re.match(r"\s*([A-Za-z0-9][A-Za-z0-9._-]*)", requirement)
    return name is not None and installed_version(name.group(1)) is not None


# The plan


@dataclass
class Choices:
    torch: str  # a build name, or KEEP
    components: dict[str, bool]


def component_requirements(component: Component, gpu: Gpu | None) -> list[str]:
    reqs = (extra_requirements(component.extra) if component.extra else []) + component.packages
    if component.gpu_packages and gpu is not None and gpu.cuda >= (component.gpu_min_cuda or (0, 0)):
        reqs += component.gpu_packages
    return reqs


def build_plan(
    options: Options,
    choices: Choices,
    gpu: Gpu | None,
    torch_version: str | None,
    installed: Callable[[str], bool] = is_installed,
) -> list[Step]:
    steps = []
    if choices.torch != KEEP:
        build = options.build(choices.torch)
        requirement = torch_requirement(options, build)
        if torch_version != requirement.partition("==")[2]:
            index = ["--index-url", build.index_url] if build.index_url else []
            steps.append(Step(f"PyTorch {options.torch_version}, {build.label}", ["install", requirement, *index]))
    for key, component in options.components.items():
        if component.required or choices.components.get(key):
            missing = [r for r in component_requirements(component, gpu) if not installed(r)]
            if missing:
                steps.append(Step(component.label, ["install", *missing]))
    return steps


def pip_command(step: Step) -> list[str]:
    return [sys.executable, "-m", "pip", *step.args]


# The wizard


def _ask(prompt: str) -> str:
    try:
        return input(prompt).strip()
    except EOFError:  # no terminal: take the default
        return ""


def ask_choice(
    question: str, options: list[tuple[str, str]], default: str, ask: Callable[[str], str], out: Callable[[str], None]
) -> str:
    """Numbered options; Enter takes the default. Returns the chosen key."""
    out(question)
    keys = [key for key, _ in options]
    for n, (key, label) in enumerate(options, start=1):
        out(f"  {n}. {label}{'  (recommended)' if key == default else ''}")
    while True:
        answer = ask(f"Choose 1-{len(options)} [Enter: {keys.index(default) + 1}]: ")
        if not answer:
            return default
        if answer.isdigit() and 1 <= int(answer) <= len(options):
            return keys[int(answer) - 1]
        if answer in keys:
            return answer
        out("Please type one of the numbers.")


def ask_yes(question: str, default: bool, ask: Callable[[str], str], out: Callable[[str], None]) -> bool:
    while True:
        answer = ask(f"{question} [{'Y/n' if default else 'y/N'}]: ").lower()
        if not answer:
            return default
        if answer in ("y", "yes", "n", "no"):
            return answer.startswith("y")
        out("Please answer y or n.")


def _short(v: Version) -> str:
    return f"{v[0]}.{v[1]}"


def run_setup(
    args: argparse.Namespace,
    out: Callable[[str], None] = print,
    ask: Callable[[str], str] = _ask,
    run: Runner = subprocess.run,
    which: Callable[[str], str | None] = shutil.which,
    installed: Callable[[str], bool] = is_installed,
    options: Options | None = None,
    detect: Callable[[str], Gpu | None] | None = None,
    torch_version: Callable[[], str | None] = lambda: installed_version("torch"),
) -> int:
    """args: yes, dry_run, torch, asr/piper/api (True, False, or None to ask), config, claude_bin, backend."""
    options = options or load_options()
    gpu = (detect or (lambda smi: detect_gpu(smi, run)))(options.nvidia_smi)
    current = torch_version()
    interactive = not (args.yes or args.dry_run)

    out(f"System: {sys.platform}, Python {sys.version.split()[0]}")
    if gpu is not None:
        out(f"GPU: {gpu.name} (driver {gpu.driver}, CUDA up to {_short(gpu.cuda)}, "
            f"compute capability {_short(gpu.compute_capability)})")  # fmt: skip
    else:
        out("GPU: no NVIDIA GPU found (nvidia-smi did not answer)")
    out(f"PyTorch: {current or 'not installed'}")
    claude = which(args.claude_bin)
    out(f"Claude Code CLI: {claude or 'not found'}")
    out("")

    builds = platform_builds(options)
    default = default_torch(options, gpu, current)
    if args.torch:
        if args.torch != KEEP and args.torch not in {b.name for b in builds}:
            out(f"Unknown PyTorch build for {sys.platform}: {args.torch}; choose from "
                + ", ".join([b.name for b in builds] + [KEEP]))  # fmt: skip
            return 2
        torch_choice = args.torch
    elif interactive:
        menu = [(b.name, b.label + ("" if b.runs_on(gpu) else " (this GPU or driver cannot run it)")) for b in builds]
        menu.append((KEEP, f"Keep what is installed ({current or 'nothing yet; Kokoro then brings its own'})"))
        torch_choice = ask_choice(f"PyTorch {options.torch_version} build for speech synthesis:", menu, default,
                                  ask, out)  # fmt: skip
    else:
        torch_choice = default

    chosen: dict[str, bool] = {}
    for key, component in options.components.items():
        if component.required:
            continue
        recommended = component.recommended or any(installed(r) for r in component_requirements(component, None))
        if key == "api" and args.backend == "claude-cli" and claude is None:
            recommended = True  # without the CLI, an API key is the way to an LLM
        flag = getattr(args, key, None)
        if flag is not None:
            chosen[key] = flag
        elif interactive:
            chosen[key] = ask_yes(f"Add {component.label}?", recommended, ask, out)
        else:
            chosen[key] = recommended

    plan = build_plan(options, Choices(torch_choice, chosen), gpu, current, installed)
    out("")
    if not plan:
        out("Nothing to install: everything chosen is already here.")
    else:
        out("Planned commands:")
        for step in plan:
            out(f"  # {step.what}")
            out(f"  {shlex.join(['python', '-m', 'pip', *step.args])}")
    if args.dry_run:
        out("Dry run: nothing was installed. `groundcast doctor` checks the installation.")
        return 0
    if plan and interactive and not ask_yes("Run these commands?", True, ask, out):
        out("Nothing was installed.")
        return 1
    for step in plan:
        out(f"\n== {step.what}")
        result = run(pip_command(step))
        if result.returncode:
            out(f"pip failed (exit status {result.returncode}); fix the problem above and run setup again.")
            return result.returncode
    out("\n== Checking the installation")
    config = ["--config", args.config] if args.config else []
    return run([sys.executable, "-m", "groundcast.cli", *config, "doctor"]).returncode
