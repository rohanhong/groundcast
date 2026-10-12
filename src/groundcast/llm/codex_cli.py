"""Codex backend: the owner's installed OpenAI Codex CLI in non-interactive mode.

Each call is a fresh, ephemeral `codex exec` run from an empty temporary
directory with the user's config and rules ignored, a read-only sandbox, and
the agent tools switched off; the system prompt replaces Codex's built-in
instructions. Codex may still add the user's global $CODEX_HOME/AGENTS.md, so
that file should hold nothing meant only for coding sessions.
"""

from __future__ import annotations

import glob
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from groundcast.llm.base import LLMBackend, LLMError, Role

log = logging.getLogger(__name__)

# Errors that another attempt cannot fix: the plan's usage limit, a missing or
# expired sign-in, a model the plan does not offer, or a flag this Codex
# version does not know. Matched against the error text.
_PERMANENT = re.compile(
    r"usage limit|hit your .*limit|not logged in|codex login|log ?in again|authenticat"
    r"|invalid api key|not supported when using codex|unknown feature flag|invalid_json_schema",
    re.IGNORECASE,
)
_PERMANENT_STATUS = re.compile(r'"status":\s*(400|401|403)\b')

# Feature names each Codex executable lists, read once per process.
_FEATURES: dict[str, set[str]] = {}


def find_codex(
    codex_bin: str,
    globs: list[str],
    which: Callable[[str], str | None] | None = None,
) -> str | None:
    """Return the Codex executable: codex_bin on PATH, else the newest match of globs.

    The desktop app keeps its CLI in a versioned folder that is not on PATH;
    environment variables in globs are expanded.
    """
    found = (which or shutil.which)(codex_bin)
    if found:
        return found
    matches = [p for pattern in globs for p in glob.glob(os.path.expandvars(pattern)) if os.path.isfile(p)]
    return os.path.normpath(max(matches, key=os.path.getmtime)) if matches else None


def strict_schema(node: Any) -> Any:
    """Return schema in the strict form Codex requires for structured output.

    Every object lists all its properties as required and forbids others; an
    optional property becomes nullable instead, and `drop_nulls` removes the
    nulls again so the model's defaults apply.
    """
    if isinstance(node, list):
        return [strict_schema(v) for v in node]
    if not isinstance(node, dict):
        return node
    out = {k: strict_schema(v) for k, v in node.items() if k != "default"}
    props = out.get("properties")
    if isinstance(props, dict):
        required = set(out.get("required", []))
        for name, sub in props.items():
            if name not in required:
                props[name] = {"anyOf": [sub, {"type": "null"}]}
        out["required"] = list(props)
        out["additionalProperties"] = False
    return out


def drop_nulls(value: Any, schema: dict[str, Any]) -> Any:
    """Remove null values of optional properties, guided by the original schema."""
    branches = [schema, *schema.get("anyOf", []), *schema.get("oneOf", [])]
    if isinstance(value, list):
        items = next((b["items"] for b in branches if isinstance(b.get("items"), dict)), {})
        return [drop_nulls(v, items) for v in value]
    if not isinstance(value, dict):
        return value
    props: dict[str, Any] = {}
    required: set[str] = set()
    for branch in branches:
        props.update(branch.get("properties", {}))
        required |= set(branch.get("required", []))
    return {
        k: drop_nulls(v, props.get(k, {}))
        for k, v in value.items()
        if not (v is None and k in props and k not in required)
    }


class CodexCLIBackend(LLMBackend):
    def __init__(
        self,
        codex_bin: str,
        codex_bin_globs: list[str],
        models: dict[str, str],
        disable_features: list[str],
        config_overrides: list[str],
        timeout_s: int,
        max_attempts: int,
        retry_backoff_s: float = 0.0,
    ) -> None:
        super().__init__(max_attempts, retry_backoff_s)
        resolved = find_codex(codex_bin, codex_bin_globs)
        if resolved is None:
            raise LLMError(f"Codex CLI not found: {codex_bin}", retryable=False)
        self.codex_bin = resolved
        self.models = models
        self.config_overrides = config_overrides
        self.timeout_s = timeout_s
        # Codex refuses a feature name it does not know, so only switch off the
        # features this version lists.
        known = self._known_features() if disable_features else set()
        self.disable_features = [f for f in disable_features if f in known]
        if skipped := [f for f in disable_features if f not in known]:
            log.warning("Codex at %s does not list these features, so they stay as they are: %s",
                        resolved, ", ".join(skipped))  # fmt: skip

    def _known_features(self) -> set[str]:
        if self.codex_bin in _FEATURES:
            return _FEATURES[self.codex_bin]
        hint = "; set llm.codex_disable_features = [] to run Codex with its tools as configured"
        try:
            proc = subprocess.run(
                [self.codex_bin, "features", "list"], capture_output=True, timeout=self.timeout_s, check=False
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise LLMError(f"could not list the Codex features: {exc}{hint}", retryable=False) from exc
        if proc.returncode != 0:
            stderr = proc.stderr.decode("utf-8", errors="replace").strip()[-300:]
            raise LLMError(f"could not list the Codex features: {stderr or proc.returncode}{hint}", retryable=False)
        lines = proc.stdout.decode("utf-8", errors="replace").splitlines()
        _FEATURES[self.codex_bin] = {line.split()[0] for line in lines if line.strip()}
        return _FEATURES[self.codex_bin]

    def _run(self, role: Role, system: str, prompt: str, schema: dict[str, Any] | None) -> str:
        # A helper Codex started can outlive a timeout and hold the directory open.
        with tempfile.TemporaryDirectory(prefix="groundcast-llm-", ignore_cleanup_errors=True) as cwd:
            instructions = Path(cwd) / "instructions.md"
            instructions.write_text(system, encoding="utf-8")
            args = [
                self.codex_bin,
                "exec",
                "--json",
                "--ephemeral",
                "--skip-git-repo-check",
                "--ignore-user-config",
                "--ignore-rules",
                "--sandbox", "read-only",
                "--model", self.models.get(role.model, role.model),
                "-c", f"model_reasoning_effort={json.dumps(role.effort)}",
                "-c", f"model_instructions_file={json.dumps(instructions.as_posix())}",
            ]  # fmt: skip
            for feature in self.disable_features:
                args += ["--disable", feature]
            for override in self.config_overrides:
                args += ["-c", override]
            if schema is not None:
                schema_file = Path(cwd) / "schema.json"
                schema_file.write_text(json.dumps(strict_schema(schema)), encoding="utf-8")
                args += ["--output-schema", str(schema_file)]
            args.append("-")
            try:
                proc = subprocess.run(
                    args,
                    input=prompt.encode("utf-8"),
                    capture_output=True,
                    cwd=cwd,
                    timeout=self.timeout_s,
                    check=False,
                )
            except subprocess.TimeoutExpired as exc:
                raise LLMError(f"codex timed out after {self.timeout_s} s") from exc
        message: str | None = None
        failure: str | None = None
        last_error: str | None = None
        for line in proc.stdout.decode("utf-8", errors="replace").splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            item = event.get("item") or {}
            if event.get("type") == "item.completed" and item.get("type") == "agent_message":
                message = str(item.get("text", ""))
            elif event.get("type") == "turn.failed":
                failure = str((event.get("error") or {}).get("message", "turn failed"))
            elif event.get("type") == "error":
                last_error = str(event.get("message", ""))
        if failure is None and proc.returncode != 0:
            stderr = proc.stderr.decode("utf-8", errors="replace").strip()[-500:]
            failure = last_error or stderr or f"exit status {proc.returncode}"
        if failure is not None:
            permanent = bool(_PERMANENT.search(failure) or _PERMANENT_STATUS.search(failure))
            raise LLMError(f"codex reported an error: {failure[:500]}", retryable=not permanent)
        if message is None:
            raise LLMError("codex finished without a reply")
        return message

    def complete(self, role: Role, system: str, prompt: str) -> str:
        return self._run(role, system, prompt, None)

    def _complete_json(self, role: Role, system: str, prompt: str, schema: dict[str, Any]) -> Any:
        return drop_nulls(json.loads(self._run(role, system, prompt, schema)), schema)
