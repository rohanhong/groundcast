import sys

import pytest

from groundcast.tts.base import SilentSynthesizer
from groundcast.tts.kokoro_engine import _block_inprocess_espeak, espeak_to_kokoro


def test_espeak_mapping() -> None:
    # espeak-ng IPA for "glucose", as `espeak-ng --ipa --tie=^` prints it.
    assert espeak_to_kokoro("\u0261lu\u02d0ko^\u028as", british=False) == "\u0261lukOs"


def test_espeak_stub_blocks_gpl_import() -> None:
    _block_inprocess_espeak()
    from misaki import espeak  # type: ignore[attr-defined]

    with pytest.raises(RuntimeError):
        espeak.EspeakFallback(british=False)
    assert "phonemizer" not in sys.modules


def test_silent_synthesizer_duration() -> None:
    synth = SilentSynthesizer(sample_rate=1000, words_per_minute=120)
    assert len(synth.synthesize("one two three four", "any", 1.0)) == 2000
    assert len(synth.synthesize("one two three four", "any", 2.0)) == 1000
