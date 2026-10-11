"""LLM backends behind one interface (spec section 7)."""

from __future__ import annotations

from groundcast.config import LLMSettings
from groundcast.llm.base import LLMBackend, LLMError, Role

__all__ = ["LLMBackend", "LLMError", "Role", "make_backend", "roles"]


def make_backend(settings: LLMSettings) -> LLMBackend:
    if settings.backend == "claude-cli":
        from groundcast.llm.claude_cli import ClaudeCLIBackend

        return ClaudeCLIBackend(settings.claude_bin, settings.timeout_s, settings.max_attempts, settings.retry_backoff_s)
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
        "tutor": Role("tutor", settings.tutor_model, settings.tutor_effort),
        "quiz": Role("quiz", settings.quiz_model, settings.quiz_effort),
    }
