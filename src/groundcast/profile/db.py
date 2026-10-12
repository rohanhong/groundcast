"""SQLite access for the profile, and the append-only event log.

Each call opens its own connection, so the web service's worker threads and
the session runner can share the file; SQLite serialises the writes.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel

from groundcast.models import utc_now

PROFILE_FILE = "profile.sqlite3"

SCHEMA = """
CREATE TABLE IF NOT EXISTS concepts (
    id TEXT PRIMARY KEY,           -- slug of the normalised name when created; never changes
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    merged_into TEXT REFERENCES concepts(id),  -- set when merged; the row stays for history
    removed_at TEXT                -- set when moved to the trash; the row stays so extraction skips it
);
CREATE TABLE IF NOT EXISTS concept_sources (
    concept_id TEXT NOT NULL REFERENCES concepts(id),
    material_id TEXT NOT NULL,
    chunk_id TEXT NOT NULL,
    PRIMARY KEY (concept_id, chunk_id)
);
CREATE TABLE IF NOT EXISTS extractions (
    material_id TEXT PRIMARY KEY,  -- materials whose concepts have been extracted
    at TEXT NOT NULL,
    concepts INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS quiz_results (
    concept_id TEXT NOT NULL REFERENCES concepts(id),
    session_id TEXT NOT NULL,
    question_id TEXT NOT NULL,
    attempt_id TEXT NOT NULL,
    right INTEGER NOT NULL,
    at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS preferences (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,           -- JSON
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS feedback (
    session_id TEXT PRIMARY KEY,
    rating INTEGER,                -- 1 to 5
    length TEXT,                   -- too_short, right, or too_long
    comment TEXT NOT NULL DEFAULT '',
    at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS inferred (
    key TEXT PRIMARY KEY,          -- a brief setting whose inferred value is confident enough to use
    value TEXT NOT NULL,           -- JSON
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS voice_pace (
    key TEXT PRIMARY KEY,          -- <speech engine>:<voice>
    words REAL NOT NULL,           -- these four are sums in which older sessions count less
    speech_s REAL NOT NULL,        -- seconds of speech, scaled to speed 1.0
    pause_s REAL NOT NULL,         -- the voice's share of the silence between sentences and segments
    sessions REAL NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    at TEXT NOT NULL,
    kind TEXT NOT NULL,            -- for example concept.created, concept.merged
    subject TEXT NOT NULL,         -- what changed, for example a concept ID
    before TEXT,                   -- JSON
    after TEXT,                    -- JSON
    reason TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL           -- user, inference, or system
);
"""

EventSource = Literal["user", "inference", "system"]


class Event(BaseModel):
    id: int
    at: datetime
    kind: str
    subject: str
    before: Any = None
    after: Any = None
    reason: str = ""
    source: EventSource


class ProfileDB:
    def __init__(self, data_dir: Path) -> None:
        self.path = data_dir / PROFILE_FILE
        data_dir.mkdir(parents=True, exist_ok=True)
        with self.connect() as con:
            con.executescript(SCHEMA)
            if "removed_at" not in {r["name"] for r in con.execute("PRAGMA table_info(concepts)")}:
                con.execute("ALTER TABLE concepts ADD COLUMN removed_at TEXT")  # profiles made before it existed

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        """A connection whose work is committed on success and rolled back on error."""
        con = sqlite3.connect(self.path, timeout=30)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys = ON")
        try:
            with con:
                yield con
        finally:
            con.close()


def log_event(
    con: sqlite3.Connection,
    kind: str,
    subject: str,
    source: EventSource,
    before: Any = None,
    after: Any = None,
    reason: str = "",
) -> None:
    """Append to the event log, inside the caller's transaction."""
    con.execute(
        "INSERT INTO events (at, kind, subject, before, after, reason, source) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            utc_now().isoformat(),
            kind,
            subject,
            None if before is None else json.dumps(before),
            None if after is None else json.dumps(after),
            reason,
            source,
        ),
    )


def _event(row: sqlite3.Row) -> Event:
    return Event(
        **{
            **dict(row),
            "before": json.loads(row["before"]) if row["before"] else None,
            "after": json.loads(row["after"]) if row["after"] else None,
        }
    )


def list_events(db: ProfileDB, limit: int) -> list[Event]:
    """The newest events first."""
    with db.connect() as con:
        rows = con.execute("SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [_event(r) for r in rows]


def get_event(db: ProfileDB, event_id: int) -> Event:
    with db.connect() as con:
        row = con.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
    if row is None:
        raise KeyError(event_id)
    return _event(row)
