"""Mode B: the owner's installed Claude Code CLI in headless mode.

Each call is a fresh, tool-less, non-persistent session started from an empty
temporary directory, so no project instructions, settings, MCP servers, or
skills reach the model; the system prompt is replaced, not appended to.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from typing import Any

from groundcast.llm.base import LLMBackend, LLMError, Role

# Errors that another attempt cannot fix: the subscription's usage limit, or
# a missing or expired sign-in. Matched against the CLI's error text.
_PERMANENT = re.compile(
    r"usage limit|limit reached|hit your .*limit|/login|not logged in|log ?in again|authenticat|invalid api key",
    re.IGNORECASE,
)
_PERMANENT_STATUS = frozenset({401, 403})


class ClaudeCLIBackend(LLMBackend):
    def __init__(self, claude_bin: str, timeout_s: int, max_attempts: int, retry_backoff_s: float = 0.0) -> None:
        super().__init__(max_attempts, retry_backoff_s)
        resolved = shutil.which(claude_bin)
        if resolved is None:
            raise LLMError(f"Claude Code CLI not found: {claude_bin}")
        self.claude_bin = resolved
        self.timeout_s = timeout_s

    def _run(self, role: Role, system: str, prompt: str, schema: dict[str, Any] | None) -> dict[str, Any]:
        args = [
            self.claude_bin,
            "-p",
            "--output-format", "json",
            "--model", role.model,
            "--effort", role.effort,
            "--system-prompt", system,
            "--tools", "",
            "--setting-sources", "",
            "--strict-mcp-config",
            "--disable-slash-commands",
            "--no-session-persistence",
        ]  # fmt: skip
        if schema is not None:
            args += ["--json-schema", json.dumps(schema, separators=(",", ":"))]
        with tempfile.TemporaryDirectory(prefix="groundcast-llm-") as cwd:
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
                raise LLMError(f"claude timed out after {self.timeout_s} s") from exc
        stdout = proc.stdout.decode("utf-8", errors="replace")
        try:
            payload = json.loads(stdout)
        except json.JSONDecodeError as exc:
            stderr = proc.stderr.decode("utf-8", errors="replace").strip()
            raise LLMError(f"claude exited {proc.returncode} without JSON output: {stderr or stdout[:500]}") from exc
        if payload.get("is_error") or proc.returncode != 0:
            text = str(payload.get("result"))[:500]
            permanent = payload.get("api_error_status") in _PERMANENT_STATUS or bool(_PERMANENT.search(text))
            raise LLMError(f"claude reported an error: {text}", retryable=not permanent)
        return payload

    def complete(self, role: Role, system: str, prompt: str) -> str:
        return str(self._run(role, system, prompt, None).get("result", ""))

    def _complete_json(self, role: Role, system: str, prompt: str, schema: dict[str, Any]) -> Any:
        payload = self._run(role, system, prompt, schema)
        if "structured_output" in payload and payload["structured_output"] is not None:
            return payload["structured_output"]
        return payload.get("result", "")
