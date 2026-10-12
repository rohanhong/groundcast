"""API backend: the Anthropic API with the user's own key (optional extra "api")."""

from __future__ import annotations

import os
from typing import Any

from groundcast.llm.base import LLMBackend, LLMError, Role

_TOOL_NAME = "submit"


class AnthropicAPIBackend(LLMBackend):
    def __init__(
        self,
        api_key_env: str,
        models: dict[str, str],
        max_tokens: int,
        timeout_s: int,
        max_attempts: int,
        retry_backoff_s: float = 0.0,
    ) -> None:
        super().__init__(max_attempts, retry_backoff_s)
        try:
            import anthropic
        except ImportError as exc:
            raise LLMError('the API backend needs the "api" extra: pip install -e ".[api]"') from exc
        key = os.environ.get(api_key_env)
        if not key:
            raise LLMError(f"environment variable {api_key_env} is not set", retryable=False)
        self._anthropic = anthropic
        self._client = anthropic.Anthropic(api_key=key, timeout=timeout_s)
        self.models = models
        self.max_tokens = max_tokens

    def _create(self, role: Role, system: str, prompt: str, **extra: Any) -> Any:
        try:
            return self._client.messages.create(
                model=self.models.get(role.model, role.model),
                max_tokens=self.max_tokens,
                system=system,
                messages=[{"role": "user", "content": prompt}],
                **extra,
            )
        except (self._anthropic.AuthenticationError, self._anthropic.PermissionDeniedError) as exc:
            raise LLMError(f"API error: {exc}", retryable=False) from exc
        except self._anthropic.APIError as exc:
            raise LLMError(f"API error: {exc}") from exc

    def complete(self, role: Role, system: str, prompt: str) -> str:
        message = self._create(role, system, prompt)
        return "".join(block.text for block in message.content if block.type == "text")

    def _complete_json(self, role: Role, system: str, prompt: str, schema: dict[str, Any]) -> Any:
        # A forced tool call is the API's structured-output channel.
        message = self._create(
            role,
            system,
            prompt,
            tools=[{"name": _TOOL_NAME, "description": "Submit the result.", "input_schema": schema}],
            tool_choice={"type": "tool", "name": _TOOL_NAME},
        )
        for block in message.content:
            if block.type == "tool_use" and block.name == _TOOL_NAME:
                return block.input
        raise LLMError("API response had no structured result")
