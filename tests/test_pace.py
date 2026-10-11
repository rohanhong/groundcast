import json

import pytest

from groundcast.config import Settings
from groundcast.models import Brief, Chunk, Material, SessionStatus
from groundcast.pipeline.writer import Pacing
from groundcast.profile.db import ProfileDB
from groundcast.profile.pace import RenderStats, pacing_for, record_pace
from groundcast.sessions import REPORT_FILE, new_session, run_session
from groundcast.storage import Store
from groundcast.tts.base import SilentSynthesizer

from .conftest import scripted_backend

Tides = tuple[Material, list[Chunk]]


@pytest.fixture
def db(settings: Settings) -> ProfileDB:
    return ProfileDB(settings.data_dir)


def _stats(voice: str, words: int, speech_s: float, pause_s: float, speed: float = 1.0) -> RenderStats:
    return RenderStats(speed=speed, words={voice: words}, speech_s={voice: speech_s}, pause_s=pause_s)


def test_configured_pacing_keeps_the_words_per_minute_model() -> None:
    pacing = Pacing.configured(125, 1.2)
    assert pacing.target_words(Brief(focus="x", material_ids=["a"], minutes=10)) == 1500
    recall = Brief(focus="x", material_ids=["a"], minutes=4, recall_prompts=True)
    assert pacing.target_words(recall, recall_questions=3, recall_pause_s=6) == round((240 - 18) / (60 / 150))


def test_measured_pace_needs_enough_words(settings: Settings, db: ProfileDB) -> None:
    settings.tts.engine = "kokoro"
    record_pace(db, "kokoro", _stats("af_bella", 100, 40.0, 10.0), decay=0.7)
    assert pacing_for(db, settings, ["af_bella"]) is None  # under pace_min_words
    record_pace(db, "kokoro", _stats("af_bella", 100, 40.0, 10.0), decay=0.7)
    settings.tts.speed = 1.25
    pacing = pacing_for(db, settings, ["af_bella"])
    assert pacing is not None
    # 0.4 s of speech per word at speed 1.0 becomes 0.32 s at 1.25; pauses (0.1 s per word) do not scale.
    assert pacing.seconds_per_word == pytest.approx(0.32 + 0.1)
    assert pacing.fixed_s == pytest.approx(len(settings.tts.disclaimer.split()) * 0.32)
    assert "af_bella" in pacing.source
    # Records are per engine: the silent engine has none.
    settings.tts.engine = "silent"
    assert pacing_for(db, settings, ["af_bella"]) is None


def test_speech_is_scaled_to_speed_one_and_recent_sessions_count_more(settings: Settings, db: ProfileDB) -> None:
    settings.tts.engine = "kokoro"
    settings.pipeline.pace_min_words = 1
    record_pace(db, "kokoro", _stats("am_adam", 100, 50.0, 0.0, speed=0.8), decay=0.5)  # 0.4 s per word at 1.0
    record_pace(db, "kokoro", _stats("am_adam", 100, 30.0, 0.0, speed=1.0), decay=0.5)  # 0.3 s per word
    pacing = pacing_for(db, settings, ["am_adam"])
    assert pacing is not None
    assert pacing.seconds_per_word == pytest.approx((0.5 * 40 + 30) / (0.5 * 100 + 100))


def test_two_hosts_average_their_voices(settings: Settings, db: ProfileDB) -> None:
    settings.tts.engine = "kokoro"
    settings.pipeline.pace_min_words = 1
    stats = RenderStats(speed=1.0, words={"af_heart": 200, "am_adam": 100}, speech_s={"af_heart": 80, "am_adam": 50},
                        pause_s=30.0)  # fmt: skip
    record_pace(db, "kokoro", stats, decay=0.7)
    pacing = pacing_for(db, settings, ["af_heart", "am_adam"])
    assert pacing is not None
    # 0.4 and 0.5 s of speech per word; the silence is shared by words, 0.1 s per word for each voice.
    assert pacing.seconds_per_word == pytest.approx(0.45 + 0.1)
    assert pacing_for(db, settings, ["af_heart", "am_echo"]) is None  # a voice with no record


def test_a_slow_voice_gets_a_shorter_script_next_time(settings: Settings, store: Store, tides: Tides) -> None:
    material, _ = tides
    settings.pipeline.pace_min_words = 1
    slow = settings.pipeline.words_per_minute // 2  # the voice speaks at half the configured pace

    def factory(s: Settings) -> SilentSynthesizer:
        return SilentSynthesizer(s.tts.sample_rate, slow)

    targets = []
    for _ in range(2):
        brief = Brief(focus="tides", material_ids=[material.id], minutes=4)
        record = run_session(new_session(store, brief), store, settings, scripted_backend(), synth_factory=factory)
        assert record.status == SessionStatus.DONE, record.error
        report = json.loads((store.session_dir(record.id) / REPORT_FILE).read_text(encoding="utf-8"))
        targets.append((report["target_words"], report["pacing"]))
    assert targets[0] == (4 * settings.pipeline.words_per_minute, f"configured {settings.pipeline.words_per_minute} "
                                                                    "words per minute")  # fmt: skip
    assert "measured pace of af_heart" in targets[1][1]
    assert targets[1][0] < targets[0][0] * 0.6  # half the speech rate, so far fewer words
