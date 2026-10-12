import json
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from groundcast.llm.base import LLMError, Role, inline_refs
from groundcast.llm.claude_cli import ClaudeCLIBackend
from groundcast.llm.codex_cli import CodexCLIBackend, drop_nulls, find_codex, strict_schema
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


def test_find_codex_prefers_path_then_the_newest_match(tmp_path: Path) -> None:
    assert find_codex("codex", [], which=lambda name: "/usr/bin/codex") == "/usr/bin/codex"
    old, new = tmp_path / "a" / "codex.exe", tmp_path / "b" / "codex.exe"
    for i, exe in enumerate((old, new)):
        exe.parent.mkdir()
        exe.write_bytes(b"")
        os.utime(exe, (1000 + i, 1000 + i))
    pattern = str(tmp_path / "*" / "codex.exe")
    assert find_codex("codex", [pattern], which=lambda name: None) == str(new)
    assert find_codex("codex", [str(tmp_path / "none" / "*")], which=lambda name: None) is None


def test_strict_schema_requires_every_property() -> None:
    schema = inline_refs(VerifierOutput.model_json_schema())
    strict = strict_schema(schema)
    verdict = strict["properties"]["verdicts"]["items"]
    assert strict["additionalProperties"] is False and verdict["additionalProperties"] is False
    assert set(verdict["required"]) == {"sentence_id", "label", "evidence", "rationale"}
    assert {"type": "null"} in verdict["properties"]["rationale"]["anyOf"]
    assert "default" not in json.dumps(strict)
    # The nulls a strict reply carries for optional fields give way to the defaults.
    reply = {"verdicts": [{"sentence_id": "S1", "label": "supported", "evidence": None, "rationale": None}]}
    out = VerifierOutput.model_validate(drop_nulls(reply, schema))
    assert out.verdicts[0].evidence == [] and out.verdicts[0].rationale == ""


def _events(*events: dict[str, Any]) -> bytes:
    return "\n".join(json.dumps(e) for e in events).encode()


def _codex_backend(
    monkeypatch: pytest.MonkeyPatch, exec_run: Any, max_attempts: int = 1, features: str = "shell_tool  stable  true\n"
) -> CodexCLIBackend:
    def fake_run(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        if args[1:] == ["features", "list"]:
            return subprocess.CompletedProcess(args, 0, features.encode(), b"")
        return exec_run(args, **kwargs)

    monkeypatch.setattr("groundcast.llm.codex_cli._FEATURES", {})
    monkeypatch.setattr("groundcast.llm.codex_cli.subprocess.run", fake_run)
    return CodexCLIBackend(
        "codex",
        [],
        {"sonnet": "gpt-test"},
        ["shell_tool", "gone_feature"],
        ['web_search="disabled"'],
        timeout_s=5,
        max_attempts=max_attempts,
        retry_backoff_s=0,
    )


def test_codex_cli_parses_structured_output(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    def exec_run(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        seen["args"] = args
        seen["input"] = kwargs["input"]
        seen["schema"] = json.loads(Path(args[args.index("--output-schema") + 1]).read_text(encoding="utf-8"))
        instructions = next(a for a in args if a.startswith("model_instructions_file="))
        seen["system"] = Path(json.loads(instructions.split("=", 1)[1])).read_text(encoding="utf-8")
        stdout = _events(
            {"type": "thread.started", "thread_id": "t"},
            {"type": "item.completed", "item": {"type": "agent_message", "text": json.dumps({"n": 7})}},
            {"type": "turn.completed", "usage": {}},
        )
        return subprocess.CompletedProcess(args, 0, stdout, b"")

    monkeypatch.setattr("groundcast.llm.codex_cli.shutil.which", lambda name: "/usr/bin/codex")
    backend = _codex_backend(monkeypatch, exec_run)
    assert backend.complete_structured(ROLE, "system text", "the prompt", Out).n == 7
    args = seen["args"]
    assert args[1] == "exec" and args[-1] == "-"
    assert args[args.index("--model") + 1] == "gpt-test"
    assert args[args.index("--sandbox") + 1] == "read-only"
    assert "--ephemeral" in args and "--ignore-user-config" in args
    assert args.count("--disable") == 1 and args[args.index("--disable") + 1] == "shell_tool"
    assert 'model_reasoning_effort="low"' in args and 'web_search="disabled"' in args
    assert seen["schema"]["additionalProperties"] is False
    assert seen["system"] == "system text" and seen["input"] == b"the prompt"


def test_codex_cli_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("groundcast.llm.codex_cli.shutil.which", lambda name: None)
    with pytest.raises(LLMError, match="Codex CLI not found"):
        CodexCLIBackend("codex", [], {}, [], [], timeout_s=5, max_attempts=1)


@pytest.mark.parametrize(
    ("message", "attempts"),
    [
        ("You've hit your usage limit. Try again later.", 1),
        ('{"type":"error","status":400,"error":{"message":"model is not supported"}}', 1),
        ('{"type":"error","status":401,"error":{"message":"unauthorized"}}', 1),
        ("stream disconnected before completion", 3),
        ("Rate limit reached for gpt-test on tokens per min", 3),
    ],
)
def test_codex_cli_errors(monkeypatch: pytest.MonkeyPatch, message: str, attempts: int) -> None:
    calls: list[int] = []

    def exec_run(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        calls.append(1)
        stdout = _events({"type": "turn.started"}, {"type": "turn.failed", "error": {"message": message}})
        return subprocess.CompletedProcess(args, 1, stdout, b"")

    monkeypatch.setattr("groundcast.llm.codex_cli.shutil.which", lambda name: "/usr/bin/codex")
    backend = _codex_backend(monkeypatch, exec_run, max_attempts=3)
    with pytest.raises(LLMError) as info:
        backend.complete_structured(ROLE, "s", "p", Out)
    assert info.value.retryable == (attempts > 1)
    assert len(calls) == attempts


def test_codex_cli_reads_an_error_event_without_a_failed_turn(monkeypatch: pytest.MonkeyPatch) -> None:
    def exec_run(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        stdout = _events({"type": "error", "message": "You've hit your usage limit."})
        return subprocess.CompletedProcess(args, 1, stdout, b"")

    monkeypatch.setattr("groundcast.llm.codex_cli.shutil.which", lambda name: "/usr/bin/codex")
    backend = _codex_backend(monkeypatch, exec_run, max_attempts=3)
    with pytest.raises(LLMError, match="usage limit") as info:
        backend.complete(ROLE, "s", "p")
    assert not info.value.retryable


def test_codex_features_are_listed_once_and_unknown_ones_logged(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    lists: list[int] = []

    def fake_run(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        lists.append(1)
        return subprocess.CompletedProcess(args, 0, b"shell_tool  stable  true\n", b"")

    monkeypatch.setattr("groundcast.llm.codex_cli._FEATURES", {})
    monkeypatch.setattr("groundcast.llm.codex_cli.shutil.which", lambda name: "/usr/bin/codex")
    monkeypatch.setattr("groundcast.llm.codex_cli.subprocess.run", fake_run)
    for _ in range(2):
        backend = CodexCLIBackend("codex", [], {}, ["shell_tool", "gone_feature"], [], timeout_s=5, max_attempts=1)
    assert backend.disable_features == ["shell_tool"] and len(lists) == 1
    assert "gone_feature" in caplog.text


def test_codex_features_that_cannot_be_listed_stop_the_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(args, 2, b"", b"unrecognized subcommand 'features'")

    monkeypatch.setattr("groundcast.llm.codex_cli._FEATURES", {})
    monkeypatch.setattr("groundcast.llm.codex_cli.shutil.which", lambda name: "/usr/bin/codex")
    monkeypatch.setattr("groundcast.llm.codex_cli.subprocess.run", fake_run)
    with pytest.raises(LLMError, match="codex_disable_features") as info:
        CodexCLIBackend("codex", [], {}, ["shell_tool"], [], timeout_s=5, max_attempts=1)
    assert not info.value.retryable
    # With nothing to switch off, the features are not listed at all.
    assert CodexCLIBackend("codex", [], {}, [], [], timeout_s=5, max_attempts=1).disable_features == []


class Inner(BaseModel):
    a: str = ""


class Outer(BaseModel):
    xs: list[Inner] | None = None


def test_drop_nulls_reaches_items_of_an_optional_list() -> None:
    schema = inline_refs(Outer.model_json_schema())
    out = Outer.model_validate(drop_nulls({"xs": [{"a": None}]}, schema))
    assert out.xs == [Inner()]
