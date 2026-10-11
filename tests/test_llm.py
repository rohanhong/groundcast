import json
import subprocess
from typing import Any

import pytest
from pydantic import BaseModel

from groundcast.llm.base import LLMError, Role, inline_refs
from groundcast.llm.claude_cli import ClaudeCLIBackend
from groundcast.pipeline.verifier import VerifierOutput

from .conftest import FakeBackend

ROLE = Role("verifier", "sonnet", "low")


def test_inline_refs_removes_defs() -> None:
    schema = inline_refs(VerifierOutput.model_json_schema())
    text = json.dumps(schema)
    assert "$ref" not in text and "$defs" not in text
    assert "supported" in text


class Out(BaseModel):
    n: int


def test_structured_output_retries_then_succeeds() -> None:
    answers = iter([{"n": "not a number"}, {"n": 3}])
    backend = FakeBackend({"Out": lambda role, prompt, schema: next(answers)})
    assert backend.complete_structured(ROLE, "sys", "prompt", Out).n == 3
    assert len(backend.calls) == 2


def test_structured_output_gives_up() -> None:
    backend = FakeBackend({"Out": lambda role, prompt, schema: {"wrong": 1}})
    with pytest.raises(LLMError):
        backend.complete_structured(ROLE, "sys", "prompt", Out)


def test_claude_cli_parses_structured_output(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    def fake_run(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        seen["args"] = args
        seen["input"] = kwargs["input"]
        payload = {"is_error": False, "result": "", "structured_output": {"n": 7}}
        return subprocess.CompletedProcess(args, 0, json.dumps(payload).encode(), b"")

    monkeypatch.setattr("groundcast.llm.claude_cli.shutil.which", lambda name: "/usr/bin/claude")
    monkeypatch.setattr("groundcast.llm.claude_cli.subprocess.run", fake_run)
    backend = ClaudeCLIBackend("claude", timeout_s=5, max_attempts=1)
    assert backend.complete_structured(ROLE, "system text", "the prompt", Out).n == 7
    args = seen["args"]
    assert args[args.index("--model") + 1] == "sonnet"
    assert args[args.index("--tools") + 1] == ""
    assert "--strict-mcp-config" in args and "--no-session-persistence" in args
    assert seen["input"] == b"the prompt"


def test_claude_cli_error_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        payload = {"is_error": True, "result": "usage limit reached"}
        return subprocess.CompletedProcess(args, 1, json.dumps(payload).encode(), b"")

    monkeypatch.setattr("groundcast.llm.claude_cli.shutil.which", lambda name: "/usr/bin/claude")
    monkeypatch.setattr("groundcast.llm.claude_cli.subprocess.run", fake_run)
    backend = ClaudeCLIBackend("claude", timeout_s=5, max_attempts=1)
    with pytest.raises(LLMError, match="usage limit"):
        backend.complete_structured(ROLE, "s", "p", Out)


def _cli_backend(monkeypatch: pytest.MonkeyPatch, payload: dict[str, Any], calls: list[int]) -> ClaudeCLIBackend:
    def fake_run(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        calls.append(1)
        return subprocess.CompletedProcess(args, 1, json.dumps(payload).encode(), b"")

    monkeypatch.setattr("groundcast.llm.claude_cli.shutil.which", lambda name: "/usr/bin/claude")
    monkeypatch.setattr("groundcast.llm.claude_cli.subprocess.run", fake_run)
    return ClaudeCLIBackend("claude", timeout_s=5, max_attempts=3, retry_backoff_s=0)


@pytest.mark.parametrize(
    "payload",
    [
        {"is_error": True, "result": "Claude AI usage limit reached|1760000000"},
        {"is_error": True, "result": "Invalid API key. Please run /login"},
        {"is_error": True, "result": "request failed", "api_error_status": 401},
    ],
)
def test_permanent_errors_are_not_retried(monkeypatch: pytest.MonkeyPatch, payload: dict[str, Any]) -> None:
    calls: list[int] = []
    backend = _cli_backend(monkeypatch, payload, calls)
    with pytest.raises(LLMError) as info:
        backend.complete_structured(ROLE, "s", "p", Out)
    assert not info.value.retryable
    assert len(calls) == 1


def test_transient_errors_are_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []
    backend = _cli_backend(monkeypatch, {"is_error": True, "result": "Overloaded", "api_error_status": 529}, calls)
    with pytest.raises(LLMError):
        backend.complete_structured(ROLE, "s", "p", Out)
    assert len(calls) == 3
