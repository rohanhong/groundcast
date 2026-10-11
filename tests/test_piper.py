import sys
from pathlib import Path

import pytest

from groundcast.config import Settings
from groundcast.profile.db import ProfileDB
from groundcast.profile.preferences import set_preferences, voice_choices
from groundcast.tts import TTSError, make_synthesizer
from groundcast.tts.piper_engine import PiperSynthesizer

# Stands in for the piper program: writes one 16-bit WAV at 22050 Hz per line
# read from stdin, named in order, whose length follows the line's words and
# the --length-scale argument.
FAKE_PIPER = """
import sys, time, wave
from pathlib import Path
args = sys.argv[1:]
out = Path(args[args.index("-d") + 1])
scale = float(args[args.index("--length-scale") + 1])
for line in sys.stdin:
    if not line.strip():
        continue
    frames = int(22050 * 0.4 * len(line.split()) * scale)
    name = "1" if "COLLIDE" in args else str(time.perf_counter_ns())  # COLLIDE: every line overwrites the last
    with wave.open(str(out / f"{name}.wav"), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(22050)
        w.writeframes(b"\\x10\\x00" * frames)
"""


@pytest.fixture
def voices(tmp_path: Path) -> Path:
    folder = tmp_path / "piper"
    folder.mkdir()
    for name in ("en_US-lessac-medium", "en_US-ryan-medium"):
        (folder / f"{name}.onnx").write_bytes(b"model")
        (folder / f"{name}.onnx.json").write_text("{}", encoding="utf-8")
    (folder / "half-downloaded.onnx").write_bytes(b"no config")
    return folder


def test_piper_runs_as_a_separate_program(tmp_path: Path, voices: Path) -> None:
    script = tmp_path / "fake_piper.py"
    script.write_text(FAKE_PIPER, encoding="utf-8")
    synth = PiperSynthesizer([sys.executable, str(script)], voices, 24000, 30)
    audio = synth.synthesize("five words in this line", "en_US-lessac-medium", 1.0)
    assert len(audio) == pytest.approx(24000 * 0.4 * 5, rel=0.01)  # resampled from 22050 Hz to 24000 Hz
    faster = synth.synthesize("five words in this line", "en_US-lessac-medium", 2.0)
    assert len(faster) == pytest.approx(len(audio) / 2, rel=0.01)
    lines = [("one two", "en_US-lessac-medium", 1.0), ("", "en_US-ryan-medium", 1.0),
             ("one two three four", "en_US-ryan-medium", 1.0), ("one", "en_US-lessac-medium", 1.0)]
    many = synth.synthesize_many(lines)  # one process per voice, results in the original order
    assert [round(len(a) / (24000 * 0.4)) for a in many] == [2, 0, 4, 1]
    colliding = PiperSynthesizer([sys.executable, str(script), "COLLIDE"], voices, 24000, 30)
    assert [round(len(a) / (24000 * 0.4)) for a in colliding.synthesize_many(lines)] == [2, 0, 4, 1]
    with pytest.raises(TTSError, match="download_voices"):
        synth.synthesize("hi", "en_GB-missing-low", 1.0)
    missing = PiperSynthesizer(["no-such-piper-program"], voices, 24000, 30)
    with pytest.raises(TTSError, match="pip install piper-tts"):
        missing.synthesize("hi", "en_US-lessac-medium", 1.0)


def test_piper_voices_are_offered_and_checked(settings: Settings, voices: Path) -> None:
    settings.tts.engine = "piper"
    settings.tts.piper_voices_dir = str(voices)
    assert voice_choices(settings) == ["en_US-lessac-medium", "en_US-ryan-medium"]
    assert isinstance(make_synthesizer(settings), PiperSynthesizer)
    db = ProfileDB(settings.data_dir)
    set_preferences(db, settings, {"voice": "en_US-ryan-medium"})
    with pytest.raises(ValueError):
        set_preferences(db, settings, {"voice": "af_heart"})  # a Kokoro voice, not a Piper one
