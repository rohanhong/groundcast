"""Explicit preferences (spec 8.1, 8.3).

The learner sets them; an unset preference falls back to the configured
default. A value given in a session's brief wins over a preference, and a
preference wins over anything inferred (groundcast.profile.suggest) and over
the configuration. Every change is an event with its old and new value, so a change
can be undone; undoing is itself a logged change.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from groundcast.config import Settings
from groundcast.models import MAX_MINUTES, MIN_MINUTES, Brief, Context, Level, ScriptFormat, utc_now
from groundcast.profile.db import EventSource, ProfileDB, get_event, log_event

# Preferences that set a default in the brief form; a brief's own value wins.
BRIEF_KEYS = ("minutes", "format", "recall_prompts", "context", "level")


class Preferences(BaseModel):
    """None means: use the configured default."""

    voice: str | None = None
    second_voice: str | None = None
    speed: float | None = Field(default=None, gt=0.25, le=4.0)
    adapt_pace: bool | None = None  # slower for dense segments, faster for the recap (S8)
    minutes: int | None = Field(default=None, ge=MIN_MINUTES, le=MAX_MINUTES)
    format: ScriptFormat | None = None
    recall_prompts: bool | None = None
    context: Context | None = None
    level: Level | None = None
    quiz_questions: int | None = Field(default=None, ge=1, le=20)
    # Off stops concept extraction from materials.
    extract_concepts: bool | None = None
    # Off stops learning brief defaults from past sessions (8.3: inference can be switched off).
    infer_preferences: bool | None = None


class PreferenceView(BaseModel):
    preferences: Preferences  # what the learner set
    effective: dict[str, Any]  # what applies now, with configured defaults filled in
    voice_choices: list[str]


def defaults(settings: Settings) -> dict[str, Any]:
    """The configured value behind every preference."""
    return {
        "voice": settings.tts.voice,
        "second_voice": settings.tts.second_voice,
        "speed": settings.tts.speed,
        "adapt_pace": settings.tts.adapt_pace,
        **{k: Brief.model_fields[k].default for k in BRIEF_KEYS},
        "quiz_questions": settings.quiz.questions,
        "extract_concepts": settings.concepts.extract_on_session,
        "infer_preferences": settings.suggest.infer,
    }


def voice_choices(settings: Settings) -> list[str]:
    """Voices to offer: Piper's downloaded voices, or Kokoro's configured ones for its language."""
    if settings.tts.engine == "piper":
        from groundcast.tts import piper_voices_dir
        from groundcast.tts.piper_engine import piper_voices

        return piper_voices(piper_voices_dir(settings))
    return [v for v in settings.tts.voice_choices if v.startswith(settings.tts.lang_code)]


def load_preferences(db: ProfileDB) -> Preferences:
    with db.connect() as con:
        rows = con.execute("SELECT key, value FROM preferences").fetchall()
    known = Preferences.model_fields
    return Preferences(**{r["key"]: json.loads(r["value"]) for r in rows if r["key"] in known})


def effective(settings: Settings, prefs: Preferences) -> dict[str, Any]:
    values = defaults(settings)
    values.update({k: v for k, v in prefs.model_dump().items() if v is not None})
    return values


def apply_preferences(settings: Settings, prefs: Preferences) -> Settings:
    """Settings with the learner's preferences in place of the configured defaults."""
    out = settings.model_copy(deep=True)
    if prefs.voice is not None:
        out.tts.voice = prefs.voice
    if prefs.second_voice is not None:
        out.tts.second_voice = prefs.second_voice
    if prefs.speed is not None:
        out.tts.speed = prefs.speed
    if prefs.adapt_pace is not None:
        out.tts.adapt_pace = prefs.adapt_pace
    if prefs.quiz_questions is not None:
        out.quiz.questions = prefs.quiz_questions
    if prefs.extract_concepts is not None:
        out.concepts.extract_on_session = prefs.extract_concepts
    return out


def check(settings: Settings, changes: dict[str, Any]) -> Preferences:
    """Validate changes against the current preferences; raises ValueError."""
    unknown = set(changes) - set(Preferences.model_fields)
    if unknown:
        raise ValueError(f"unknown preference(s): {', '.join(sorted(unknown))}")
    for key in ("voice", "second_voice"):
        value = changes.get(key)
        if value is not None and value not in voice_choices(settings):
            raise ValueError(f"{key} must be one of the offered voices ({settings.tts.engine}), got {value!r}")
    try:
        return Preferences(**changes)
    except ValidationError as exc:
        raise ValueError(str(exc)) from exc


def set_preferences(
    db: ProfileDB, settings: Settings, changes: dict[str, Any], source: EventSource = "user", reason: str = ""
) -> Preferences:
    """Apply changes (None clears a preference) and log each one that changes a value."""
    checked = check(settings, changes)
    current = load_preferences(db)
    with db.connect() as con:
        for key in changes:
            before, after = getattr(current, key), getattr(checked, key)
            if before == after:
                continue
            if after is None:
                con.execute("DELETE FROM preferences WHERE key = ?", (key,))
            else:
                con.execute(
                    "INSERT OR REPLACE INTO preferences (key, value, updated_at) VALUES (?, ?, ?)",
                    (key, json.dumps(after), utc_now().isoformat()),
                )
            log_event(con, "preference.set", key, source, before={"value": before}, after={"value": after},
                      reason=reason)  # fmt: skip
    return load_preferences(db)


def undo(db: ProfileDB, settings: Settings, event_id: int) -> Preferences:
    """Set a preference back to its value before the given change."""
    event = get_event(db, event_id)
    if event.kind != "preference.set":
        raise ValueError(f"only preference changes can be undone, not {event.kind}")
    return set_preferences(db, settings, {event.subject: event.before["value"]}, reason=f"undo of change {event_id}")


# Rows that refer to concepts come before the concepts table, so deleting in order keeps the keys valid.
TABLES = ("preferences", "inferred", "voice_pace", "extractions", "quiz_results", "concept_sources", "concepts", "events")


def export_profile(db: ProfileDB) -> dict[str, list[dict[str, Any]]]:
    """Every row of the profile, table by table (8.3: view and export)."""
    with db.connect() as con:
        return {t: [dict(r) for r in con.execute(f"SELECT * FROM {t}").fetchall()] for t in TABLES}  # noqa: S608


def delete_profile(db: ProfileDB) -> None:
    """Remove everything in the profile; one event records that it happened (8.3: delete)."""
    with db.connect() as con:
        for table in TABLES:
            con.execute(f"DELETE FROM {table}")  # noqa: S608 - fixed table names
        log_event(con, "profile.deleted", "profile", "user")
