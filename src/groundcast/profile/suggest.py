"""Inferred preferences and ranked session suggestions (spec 8.1, 8.2; M4).

Inferred preferences come from the briefs of the learner's own sessions.
Each session counts with a weight that halves every suggest.half_life_days,
so an old habit fades unless it is chosen again. A value's confidence is its
share of the weight, scaled down until suggest.min_evidence sessions' worth
of weight is in. Inferred values are never applied silently: they only
prefill a suggestion, which says why, and the learner accepts or edits it.
An explicit preference always wins, and inference can be switched off.

Suggestions are ranked: revise the concepts with the weakest quiz results,
repeat the last session, or start a material not studied yet. Accepting a
suggestion unchanged or editing it is logged; the share of suggestions
accepted without edits is the personalisation measure of spec section 13.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel

from groundcast.config import Settings
from groundcast.models import MAX_MINUTES, MIN_MINUTES, Brief, Material, SessionRecord, SessionStatus, utc_now
from groundcast.profile.concepts import Concept, list_concepts
from groundcast.profile.db import ProfileDB, log_event
from groundcast.profile.feedback import get_feedback
from groundcast.profile.preferences import BRIEF_KEYS, Preferences, defaults, load_preferences

LABELS = {"minutes": "length", "format": "format", "recall_prompts": "recall questions", "context": "context",
          "level": "level"}  # fmt: skip
# Fields compared when a suggestion turns into a session.
COMPARED = ("focus", "material_ids", *BRIEF_KEYS)


class Inferred(BaseModel):
    key: str
    value: Any
    confidence: float  # 0 to 1
    sessions: int  # sessions that chose this value
    of_sessions: int  # sessions considered
    last_chosen: datetime
    applied: bool  # confident enough to prefill suggestions


class Suggestion(BaseModel):
    id: str  # kind plus what it is about
    kind: Literal["weak_topics", "same_as_last", "new_material"]
    title: str
    why: list[str]
    brief: Brief
    score: float


class Acceptance(BaseModel):
    accepted: int
    edited: int
    rate: float | None  # accepted without edits / all outcomes


class SuggestionView(BaseModel):
    suggestions: list[Suggestion]
    inferred: list[Inferred]
    acceptance: Acceptance
    inference_on: bool


def mastery(c: Concept) -> float:
    """Estimated share answered right, starting from one right and one wrong (Laplace)."""
    return (c.right + 1) / (c.asked + 2)


def _show(key: str, value: Any) -> str:
    if key == "minutes":
        return f"{value} minutes"
    if key == "recall_prompts":
        return "yes" if value else "no"
    if key == "format":
        return "two hosts" if value == "two_hosts" else "one narrator"
    return str(value)


def infer(sessions: list[SessionRecord], settings: Settings, now: datetime | None = None) -> list[Inferred]:
    """The most chosen value of each brief setting, weighted toward recent sessions."""
    cfg = settings.suggest
    now = now or utc_now()
    chosen = [s for s in sessions if s.status != SessionStatus.FAILED]
    out = []
    for key in BRIEF_KEYS:
        weights: dict[str, float] = defaultdict(float)
        counts: dict[str, int] = defaultdict(int)
        last: dict[str, datetime] = {}
        for s in chosen:
            value = json.dumps(getattr(s.brief, key))
            age_days = max(0.0, (now - s.created_at).total_seconds() / 86400)
            weights[value] += 0.5 ** (age_days / cfg.half_life_days)
            counts[value] += 1
            last[value] = max(last.get(value, s.created_at), s.created_at)
        total = sum(weights.values())
        if not total:
            continue
        best = max(weights, key=lambda v: (weights[v], last[v]))
        confidence = weights[best] / total * min(1.0, total / cfg.min_evidence)
        out.append(
            Inferred(
                key=key,
                value=json.loads(best),
                confidence=round(confidence, 3),
                sessions=counts[best],
                of_sessions=len(chosen),
                last_chosen=last[best],
                applied=confidence >= cfg.min_confidence,
            )
        )
    return out


def refresh_inferred(db: ProfileDB, inferred: list[Inferred]) -> None:
    """Log each inferred value that started or stopped applying, or changed (source: inference)."""
    with db.connect() as con:
        rows = {r["key"]: json.loads(r["value"]) for r in con.execute("SELECT key, value FROM inferred")}
        now_applied = {i.key: i.value for i in inferred if i.applied}
        for key in sorted(set(rows) | set(now_applied)):
            before, after = rows.get(key), now_applied.get(key)
            if before == after:
                continue
            if after is None:
                con.execute("DELETE FROM inferred WHERE key = ?", (key,))
            else:
                con.execute("INSERT OR REPLACE INTO inferred (key, value, updated_at) VALUES (?, ?, ?)",
                            (key, json.dumps(after), utc_now().isoformat()))  # fmt: skip
            log_event(con, "preference.inferred", key, "inference", before={"value": before},
                      after={"value": after}, reason="from the briefs of your sessions")  # fmt: skip


def _defaults(settings: Settings, prefs: Preferences, inferred: list[Inferred]) -> tuple[dict[str, Any], list[str]]:
    """Brief settings for a new suggestion: preference > confident inference > configuration."""
    values = {k: defaults(settings)[k] for k in BRIEF_KEYS}
    why = []
    for i in inferred:
        if i.applied and getattr(prefs, i.key) is None:
            values[i.key] = i.value
            why.append(f"{LABELS[i.key].capitalize()} {_show(i.key, i.value)}: you chose it in {i.sessions} of "
                       f"your last {i.of_sessions} sessions.")  # fmt: skip
    for key in BRIEF_KEYS:
        if getattr(prefs, key) is not None:
            values[key] = getattr(prefs, key)
    return values, why


def suggest(
    db: ProfileDB, settings: Settings, materials: list[Material], sessions: list[SessionRecord]
) -> SuggestionView:
    prefs = load_preferences(db)
    on = prefs.infer_preferences if prefs.infer_preferences is not None else settings.suggest.infer
    inferred = infer(sessions, settings) if on else []
    if on:
        refresh_inferred(db, inferred)
    base, base_why = _defaults(settings, prefs, inferred)
    ready = {m.id: m for m in materials if m.status == "ready"}
    out: list[Suggestion] = []

    # Revise the weakest concepts, from the materials they were found in.
    weak = [c for c in list_concepts(db) if c.asked and mastery(c) < settings.suggest.weak_mastery]
    weak = [c for c in sorted(weak, key=mastery) if set(c.material_ids) & set(ready)][: settings.suggest.weak_topics]
    if weak:
        material_ids = sorted({m for c in weak for m in c.material_ids if m in ready})
        values = {**base, "context": "revision", "recall_prompts": True}
        why = [f"Quiz results on {c.name}: {c.right} of {c.asked} right." for c in weak]
        why.append("Revision with recall questions, since answering questions helps you remember.")
        out.append(Suggestion(
            id="weak_topics:" + ",".join(c.id for c in weak), kind="weak_topics",
            title="Revise " + ", ".join(c.name for c in weak),
            why=why + base_why,
            brief=Brief(focus="Revise " + "; ".join(f"{c.name}: {c.description}".rstrip(": ") for c in weak),
                        material_ids=material_ids, **values),
            score=0.9 - 0.5 * mastery(weak[0]),
        ))  # fmt: skip

    # The last finished session again, if its materials are still here, adjusted by its feedback.
    last = next((s for s in sessions if s.status == SessionStatus.DONE), None)
    if last is not None and all(m in ready for m in last.brief.material_ids):
        brief, why, score = last.brief, [f"Your last session, on {last.created_at:%Y-%m-%d}."], 0.6
        fb = get_feedback(db, last.id)
        if fb is not None and fb.length in ("too_long", "too_short"):
            factor = settings.suggest.length_step if fb.length == "too_short" else 1 / settings.suggest.length_step
            minutes = min(MAX_MINUTES, max(MIN_MINUTES, round(brief.minutes * factor)))
            brief = brief.model_copy(update={"minutes": minutes})
            why.append(f"{minutes} minutes, since you said it was {fb.length.replace('_', ' ')}.")
        if fb is not None and fb.rating is not None and fb.rating <= settings.suggest.low_rating:
            score = 0.3
            why.append(f"You rated it {fb.rating} of 5, so it comes after the others.")
        out.append(Suggestion(
            id=f"same_as_last:{last.id}", kind="same_as_last",
            title=f"Same as last time: {last.brief.title or last.brief.focus}",
            why=why, brief=brief, score=score,
        ))  # fmt: skip

    # Materials no session has used yet, newest first.
    used = {m for s in sessions for m in s.brief.material_ids}
    for m in sorted((m for m in ready.values() if m.id not in used), key=lambda m: m.added_at, reverse=True)[:2]:
        out.append(Suggestion(
            id=f"new_material:{m.id}", kind="new_material", title=f"Start {m.filename}",
            why=["You have not had a session on this material yet."] + base_why,
            brief=Brief(focus=f"An overview of the main ideas in {m.filename}", material_ids=[m.id], **base),
            score=0.5,
        ))  # fmt: skip
    out.sort(key=lambda s: -s.score)
    return SuggestionView(
        suggestions=out[: settings.suggest.max_suggestions],
        inferred=inferred,
        acceptance=acceptance(db),
        inference_on=on,
    )


def record_outcome(db: ProfileDB, suggestion: Suggestion, final: Brief) -> bool:
    """Log whether a suggestion became a session unchanged; returns True when it did."""
    before = {k: getattr(suggestion.brief, k) for k in COMPARED}
    after = {k: getattr(final, k) for k in COMPARED}
    changed = {k for k in COMPARED if before[k] != after[k]}
    with db.connect() as con:
        log_event(con, "suggestion.edited" if changed else "suggestion.accepted", suggestion.id, "user",
                  before={k: before[k] for k in changed} or None, after={k: after[k] for k in changed} or None,
                  reason=suggestion.title)  # fmt: skip
    return not changed


def acceptance(db: ProfileDB) -> Acceptance:
    with db.connect() as con:
        rows = dict(con.execute(
            "SELECT kind, COUNT(*) FROM events WHERE kind IN ('suggestion.accepted', 'suggestion.edited') "
            "GROUP BY kind").fetchall())  # fmt: skip
    accepted, edited = rows.get("suggestion.accepted", 0), rows.get("suggestion.edited", 0)
    total = accepted + edited
    return Acceptance(accepted=accepted, edited=edited, rate=accepted / total if total else None)
