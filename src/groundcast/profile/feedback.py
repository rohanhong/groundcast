"""Explicit feedback on a session.

After listening, the learner can rate a session, say whether it was too
short or too long, and leave a comment. One record per session; a change
replaces it and is logged with its old and new value. Suggestions use it:
a poorly rated session is not offered again first, and "too long" or "too
short" changes the length offered for the same session.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from groundcast.models import utc_now
from groundcast.profile.db import ProfileDB, log_event

LengthVerdict = Literal["too_short", "right", "too_long"]


class Feedback(BaseModel):
    rating: int | None = Field(default=None, ge=1, le=5)
    length: LengthVerdict | None = None
    comment: str = Field(default="", max_length=1000)


class StoredFeedback(Feedback):
    session_id: str
    at: datetime


def get_feedback(db: ProfileDB, session_id: str) -> StoredFeedback | None:
    with db.connect() as con:
        row = con.execute("SELECT * FROM feedback WHERE session_id = ?", (session_id,)).fetchone()
    return StoredFeedback(**dict(row)) if row else None


def set_feedback(db: ProfileDB, session_id: str, feedback: Feedback) -> StoredFeedback:
    before = get_feedback(db, session_id)
    stored = StoredFeedback(session_id=session_id, at=utc_now(), **feedback.model_dump())
    with db.connect() as con:
        con.execute(
            "INSERT OR REPLACE INTO feedback (session_id, rating, length, comment, at) VALUES (?, ?, ?, ?, ?)",
            (session_id, feedback.rating, feedback.length, feedback.comment, stored.at.isoformat()),
        )
        log_event(con, "session.feedback", session_id, "user",
                  before=before.model_dump(include={"rating", "length", "comment"}) if before else None,
                  after=feedback.model_dump())  # fmt: skip
    return stored
