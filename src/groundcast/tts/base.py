"""Speech synthesis interface (S9)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable

import numpy as np

Line = tuple[str, str, float]  # text, voice, speed


class TTSError(RuntimeError):
    pass


class Synthesizer(ABC):
    sample_rate: int

    @abstractmethod
    def synthesize(self, text: str, voice: str, speed: float) -> np.ndarray:
        """Return mono float32 samples in [-1, 1] at self.sample_rate."""

    def synthesize_many(self, lines: list[Line], done: Callable[[int], None] | None = None) -> list[np.ndarray]:
        """Samples for each line, in order; done(n) reports progress. Engines may batch."""
        out = []
        for text, voice, speed in lines:
            out.append(self.synthesize(text, voice, speed))
            if done:
                done(len(out))
        return out

    def close(self) -> None:
        """Release model memory (stages share the GPU; spec section 11)."""


class SilentSynthesizer(Synthesizer):
    """Silence of a plausible duration; for tests and dry runs without a model."""

    def __init__(self, sample_rate: int, words_per_minute: int) -> None:
        self.sample_rate = sample_rate
        self.words_per_minute = words_per_minute

    def synthesize(self, text: str, voice: str, speed: float) -> np.ndarray:
        seconds = len(text.split()) * 60.0 / (self.words_per_minute * speed)
        return np.zeros(max(1, int(seconds * self.sample_rate)), dtype=np.float32)
