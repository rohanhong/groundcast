"""Speech synthesis engines."""

from __future__ import annotations

from groundcast.config import Settings
from groundcast.tts.base import SilentSynthesizer, Synthesizer, TTSError

__all__ = ["Synthesizer", "TTSError", "make_synthesizer"]


def make_synthesizer(settings: Settings) -> Synthesizer:
    tts = settings.tts
    if tts.engine == "silent":
        return SilentSynthesizer(tts.sample_rate, settings.pipeline.words_per_minute)
    from groundcast.tts.kokoro_engine import KokoroSynthesizer

    return KokoroSynthesizer(tts.repo_id, tts.lang_code, tts.device, settings.model_dir, tts.sample_rate, tts.espeak_bin)
