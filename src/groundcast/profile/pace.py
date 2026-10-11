"""Speaking pace per voice, measured from rendered sessions.

Voices differ: at the same speed one may speak a fifth faster than another,
so a single words-per-minute setting misjudges session length. Rendering
knows how long every sentence took, so each session records, per voice, the
words spoken and the seconds of speech (scaled to speed 1.0), plus the
silence between sentences and segments. Recall pauses and the spoken
disclaimer are left out, since the length target accounts for them
separately. Older sessions count less (pipeline.pace_decay). Records are
kept per speech engine and voice, so dry runs with the silent engine never
mix with real ones.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from statistics import fmean

from groundcast.config import Settings
from groundcast.models import utc_now
from groundcast.pipeline.writer import Pacing
from groundcast.profile.db import ProfileDB


@dataclass
class RenderStats:
    """What one rendered session says about pace."""

    speed: float
    words: dict[str, int] = field(default_factory=dict)  # per voice
    speech_s: dict[str, float] = field(default_factory=dict)  # per voice, at the session's speed
    pause_s: float = 0.0  # silence between sentences and segments


def _key(engine: str, voice: str) -> str:
    return f"{engine}:{voice}"


def record_pace(db: ProfileDB, engine: str, stats: RenderStats, decay: float) -> None:
    total_words = sum(stats.words.values())
    if not total_words:
        return
    with db.connect() as con:
        for voice, words in stats.words.items():
            if not words:
                continue
            key = _key(engine, voice)
            speech = stats.speech_s[voice] * stats.speed  # seconds at speed 1.0
            pause = stats.pause_s * words / total_words  # the voice's share of the silence
            row = con.execute("SELECT * FROM voice_pace WHERE key = ?", (key,)).fetchone()
            old = (row["words"], row["speech_s"], row["pause_s"], row["sessions"]) if row else (0.0, 0.0, 0.0, 0.0)
            con.execute(
                "INSERT OR REPLACE INTO voice_pace (key, words, speech_s, pause_s, sessions, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    key,
                    old[0] * decay + words,
                    old[1] * decay + speech,
                    old[2] * decay + pause,
                    old[3] * decay + 1,
                    utc_now().isoformat(),
                ),
            )


def pacing_for(db: ProfileDB, settings: Settings, voices: list[str]) -> Pacing | None:
    """Pacing from the measured pace of these voices, or None while any lacks enough data."""
    cfg, tts = settings.pipeline, settings.tts
    rows = []
    with db.connect() as con:
        for voice in voices:
            row = con.execute("SELECT * FROM voice_pace WHERE key = ?", (_key(tts.engine, voice),)).fetchone()
            if row is None or row["words"] < cfg.pace_min_words:
                return None
            rows.append(row)
    # Speech scales with speed; the pauses between sentences do not.
    speech_per_word = [r["speech_s"] / r["words"] / tts.speed for r in rows]
    pause_per_word = [r["pause_s"] / r["words"] for r in rows]
    disclaimer_s = len(tts.disclaimer.split()) * speech_per_word[0]  # spoken by the first voice
    sessions = min(r["sessions"] for r in rows)
    return Pacing(
        seconds_per_word=fmean(speech_per_word) + fmean(pause_per_word),
        fixed_s=disclaimer_s,
        source=f"measured pace of {' and '.join(voices)} (about {sessions:.1f} session(s))",
    )
