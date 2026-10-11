"""Speech synthesis engines."""

from __future__ import annotations

from pathlib import Path

from groundcast.config import Settings
from groundcast.tts.base import SilentSynthesizer, Synthesizer, TTSError

__all__ = ["Synthesizer", "TTSError", "make_synthesizer"]


def piper_voices_dir(settings: Settings) -> Path:
    return Path(settings.tts.piper_voices_dir) if settings.tts.piper_voices_dir else settings.model_dir / "piper"


def make_synthesizer(settings: Settings) -> Synthesizer:
    tts = settings.tts
    if tts.engine == "silent":
        return SilentSynthesizer(tts.sample_rate, settings.pipeline.words_per_minute)
    if tts.engine == "piper":
        from groundcast.tts.piper_engine import PiperSynthesizer

        return PiperSynthesizer(tts.piper_command, piper_voices_dir(settings), tts.sample_rate, tts.piper_timeout_s)
    from groundcast.tts.kokoro_engine import KokoroSynthesizer

    return KokoroSynthesizer(tts.repo_id, tts.lang_code, tts.device, settings.model_dir, tts.sample_rate, tts.espeak_bin)
