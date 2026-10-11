"""LLMBackend: the only way the pipeline reaches a model (spec section 7)."""

from __future__ import annotations

import json
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

log = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class LLMError(RuntimeError):
    """A failed model call. retryable=False means trying again cannot help
    (usage limit reached, not signed in, invalid key)."""

    def __init__(self, message: str, retryable: bool = True) -> None:
        super().__init__(message)
        self.retryable = retryable


@dataclass(frozen=True)
class Role:
    """Model and effort for one pipeline role."""

    name: str
    model: str
    effort: str


def inline_refs(schema: dict[str, Any]) -> dict[str, Any]:
    """Return schema with local $ref pointers replaced by their definitions.

    Pydantic emits $defs and $ref; inlining them gives one self-contained
    schema that every backend accepts.
    """
    defs = schema.get("$defs", {})

    def resolve(node: Any) -> Any:
        if isinstance(node, dict):
            ref = node.get("$ref")
            if isinstance(ref, str) and ref.startswith("#/$defs/"):
                merged = dict(defs[ref.removeprefix("#/$defs/")])
                merged.update({k: v for k, v in node.items() if k != "$ref"})
                return resolve(merged)
            return {k: resolve(v) for k, v in node.items() if k != "$defs"}
        if isinstance(node, list):
            return [resolve(v) for v in node]
        return node

    return resolve(schema)


class LLMBackend(ABC):
    def __init__(self, max_attempts: int, retry_backoff_s: float = 0.0) -> None:
        self.max_attempts = max_attempts
        self.retry_backoff_s = retry_backoff_s

    @abstractmethod
    def complete(self, role: Role, system: str, prompt: str) -> str:
        """Return plain text."""

    @abstractmethod
    def _complete_json(self, role: Role, system: str, prompt: str, schema: dict[str, Any]) -> Any:
        """Return a parsed JSON value that should match schema."""

    def complete_structured(self, role: Role, system: str, prompt: str, output: type[T]) -> T:
        """Return a validated instance of output, retrying on invalid output."""
        schema = inline_refs(output.model_json_schema())
        last_error: Exception | None = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                value = self._complete_json(role, system, prompt, schema)
                if isinstance(value, str):
                    value = json.loads(value)
                return output.model_validate(value)
            except LLMError as exc:
                if not exc.retryable:
                    raise LLMError(f"{role.name}: {exc}", retryable=False) from exc
                last_error = exc
                log.warning("%s: attempt %d/%d failed: %s", role.name, attempt, self.max_attempts, exc)
                if attempt < self.max_attempts:
                    time.sleep(self.retry_backoff_s * attempt)
            except (ValidationError, json.JSONDecodeError) as exc:
                # Invalid output: ask again at once.
                last_error = exc
                log.warning("%s: attempt %d/%d failed: %s", role.name, attempt, self.max_attempts, exc)
        raise LLMError(f"{role.name}: no valid output after {self.max_attempts} attempts: {last_error}")
