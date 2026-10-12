"""LLM backends behind one interface."""

from __future__ import annotations

import shutil
from collections.abc import Callable
from dataclasses import dataclass

from groundcast.config import LLMSettings
from groundcast.llm.base import LLMBackend, LLMError, Role
from groundcast.llm.codex_cli import find_codex

__all__ = ["BackendCLI", "LLMBackend", "LLMError", "Role", "find_cli", "make_backend", "roles"]


@dataclass(frozen=True)
class BackendCLI:
    """The program a CLI backend runs; path is None when it was not found."""

    name: str
    setting: str
    path: str | None
    fix: str


def find_cli(settings: LLMSettings, which: Callable[[str], str | None] | None = None) -> BackendCLI | None:
    """Return the configured backend's program, or None for the API backend."""
    which = which or shutil.which
    if settings.backend == "claude-cli":
        return BackendCLI("Claude Code CLI", settings.claude_bin, which(settings.claude_bin),
                          'install Claude Code and sign in, or set llm.backend = "anthropic-api"')  # fmt: skip
    if settings.backend == "codex-cli":
        return BackendCLI("Codex CLI", settings.codex_bin,
                          find_codex(settings.codex_bin, settings.codex_bin_globs, which),
                          "install Codex and sign in (codex login), or set llm.codex_bin to its path")  # fmt: skip
    return None


def make_backend(settings: LLMSettings) -> LLMBackend:
    if settings.backend == "claude-cli":
        from groundcast.llm.claude_cli import ClaudeCLIBackend

        return ClaudeCLIBackend(settings.claude_bin, settings.timeout_s, settings.max_attempts, settings.retry_backoff_s)
    if settings.backend == "codex-cli":
        from groundcast.llm.codex_cli import CodexCLIBackend

        return CodexCLIBackend(
            settings.codex_bin,
            settings.codex_bin_globs,
            settings.codex_models,
            settings.codex_disable_features,
            settings.codex_config,
            settings.timeout_s,
            settings.max_attempts,
            settings.retry_backoff_s,
        )
    from groundcast.llm.anthropic_api import AnthropicAPIBackend

    return AnthropicAPIBackend(
        settings.api_key_env,
        settings.api_models,
        settings.api_max_tokens,
        settings.timeout_s,
        settings.max_attempts,
        settings.retry_backoff_s,
    )


def roles(settings: LLMSettings) -> dict[str, Role]:
    return {
        "writer": Role("writer", settings.writer_model, settings.writer_effort),
        "verifier": Role("verifier", settings.verifier_model, settings.verifier_effort),
        "editor": Role("editor", settings.editor_model, settings.editor_effort),
        "elicitor": Role("elicitor", settings.elicitor_model, settings.elicitor_effort),
        "tutor": Role("tutor", settings.tutor_model, settings.tutor_effort),
        "quiz": Role("quiz", settings.quiz_model, settings.quiz_effort),
        "concepts": Role("concepts", settings.concepts_model, settings.concepts_effort),
        "judge": Role("judge", settings.judge_model, settings.judge_effort),
    }
