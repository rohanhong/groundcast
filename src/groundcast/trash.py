"""The trash: deleted materials, sessions, questions, quizzes, and concepts, kept until restored or purged.

<data_dir>/trash/<item id>/
  item.json   TrashItem: what was deleted, when, and the profile rows taken with it
  files/      the moved files and folders, at their paths under the data directory

A delete writes item.json first and then moves the files (a material's
record first, so it leaves the lists at once), so an interrupted delete still
leaves an item that restores. Profile rows tied to an item leave the profile
with it, so concept mastery and suggestions stop counting them, and come back
on restore: a material's concept links, a session's feedback and quiz
results, a quiz's or a concept's results. Restored rows follow concept
merges made in the meantime. Questions and quizzes live in their session's
qa.json and quiz.json, so their item keeps the content; the caller
serialises calls that touch those files. A concept has no files: its row is
marked removed (groundcast.profile.concepts), and purging its item keeps the
row, so extraction never finds it again. Items older than trash.keep_days
are purged when the service starts.
"""

from __future__ import annotations

import secrets
import shutil
import sqlite3
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from groundcast.models import SessionRecord, SessionStatus, utc_now
from groundcast.profile.concepts import resolve, set_removed
from groundcast.profile.db import ProfileDB, log_event
from groundcast.qa import QAExchange, load_history, save_history
from groundcast.quiz import Quiz, QuizAttempt, load_quizzes, save_quizzes
from groundcast.storage import Store, check_id, move_path, read_model, write_model

TRASH_DIR = "trash"
ITEM_FILE = "item.json"
FILES_DIR = "files"

TrashKind = Literal["material", "session", "question", "quiz", "concept"]
ACTIVE = (SessionStatus.QUEUED, SessionStatus.RUNNING)
# Profile tables whose rows can go into the trash, with the columns that identify a row.
ROW_KEYS = {
    "concept_sources": ("concept_id", "chunk_id"),
    "extractions": ("material_id",),
    "feedback": ("session_id",),
    "quiz_results": ("concept_id", "attempt_id", "question_id"),
}

Where = tuple[str, tuple[object, ...]]  # an SQL condition and its parameters


class TrashConflict(Exception):
    """The item cannot be deleted or restored now; the message says why."""


class TrashItem(BaseModel):
    id: str
    kind: TrashKind
    subject: str  # the ID of the material, session, exchange, quiz, or concept
    label: str  # file name, session title, question, quiz description, or concept name
    session_id: str = ""  # questions and quizzes: the session they belong to
    session_label: str = ""
    deleted_at: datetime = Field(default_factory=utc_now)
    files: list[str] = Field(default_factory=list)  # POSIX paths under the data directory, in move order
    rows: dict[str, list[dict[str, Any]]] = Field(default_factory=dict)  # profile table -> rows taken out
    content: dict[str, Any] | None = None  # a question's exchange, or a quiz with its attempts


class TrashEntry(BaseModel):
    """An item as the web app lists it."""

    id: str
    kind: TrashKind
    label: str
    session_id: str
    session_label: str
    deleted_at: datetime
    purge_at: datetime | None  # None while items are kept until the trash is emptied


def session_label(record: SessionRecord) -> str:
    return record.title or record.brief.title or record.brief.focus


class Trash:
    def __init__(self, store: Store, profile: ProfileDB) -> None:
        self.store = store
        self.profile = profile
        self.root = store.root / TRASH_DIR
        self.root.mkdir(parents=True, exist_ok=True)

    def _dir(self, item_id: str) -> Path:
        return self.root / check_id(item_id)

    def get(self, item_id: str) -> TrashItem:
        return read_model(self._dir(item_id) / ITEM_FILE, TrashItem)

    def items(self) -> list[TrashItem]:
        """Newest first."""
        found = [read_model(p, TrashItem) for p in self.root.glob(f"*/{ITEM_FILE}")]
        return sorted(found, key=lambda i: i.deleted_at, reverse=True)

    @staticmethod
    def entry(item: TrashItem, keep_days: float) -> TrashEntry:
        purge_at = item.deleted_at + timedelta(days=keep_days) if keep_days > 0 else None
        return TrashEntry(**item.model_dump(include=set(TrashEntry.model_fields) - {"purge_at"}), purge_at=purge_at)

    # Deleting

    def delete_material(self, material_id: str) -> TrashItem:
        material = self.store.get_material(material_id)
        if material.status == "processing":
            raise TrashConflict(f"{material.filename} is still being read; delete it once that is done.")
        if any(s.status in ACTIVE and material.id in s.brief.material_ids for s in self.store.list_sessions()):
            raise TrashConflict(f"A session being made uses {material.filename}; delete it once that is done.")
        where = ("material_id = ?", (material.id,))
        item = TrashItem(id=_new_id(), kind="material", subject=material.id, label=material.filename)
        return self._delete(item, self.store.material_files(material), {"concept_sources": where, "extractions": where})

    def delete_session(self, record: SessionRecord) -> TrashItem:
        if record.status in ACTIVE:
            raise TrashConflict("This session is still being made; delete it once it is done or has failed.")
        where = ("session_id = ?", (record.id,))
        item = TrashItem(id=_new_id(), kind="session", subject=record.id, label=session_label(record))
        return self._delete(item, [self.store.session_dir(record.id)], {"feedback": where, "quiz_results": where})

    def delete_question(self, record: SessionRecord, exchange_id: str) -> TrashItem:
        history = load_history(self.store, record.id)
        exchange = next((x for x in history.exchanges if x.id == exchange_id), None)
        if exchange is None:
            raise KeyError(f"no question {exchange_id!r} in session {record.id}")
        item = TrashItem(id=_new_id(), kind="question", subject=exchange.id, label=exchange.question,
                         session_id=record.id, session_label=session_label(record),
                         content=exchange.model_dump(mode="json"))  # fmt: skip

        def take_out() -> None:
            history.exchanges.remove(exchange)
            save_history(self.store, record.id, history)

        return self._delete(item, [], {}, take_out)

    def delete_quiz(self, record: SessionRecord, quiz_id: str) -> TrashItem:
        data = load_quizzes(self.store, record.id)
        quiz = next((q for q in data.quizzes if q.id == quiz_id), None)
        if quiz is None:
            raise KeyError(f"no quiz {quiz_id!r} in session {record.id}")
        attempts = [a for a in data.attempts if a.quiz_id == quiz.id]
        n = len(quiz.questions)
        item = TrashItem(id=_new_id(), kind="quiz", subject=quiz.id,
                         label=f"Quiz of {n} question{'' if n == 1 else 's'}", session_id=record.id,
                         session_label=session_label(record),
                         content={"quiz": quiz.model_dump(mode="json"),
                                  "attempts": [a.model_dump(mode="json") for a in attempts]})  # fmt: skip
        attempt_ids = tuple(a.id for a in attempts)
        marks = ", ".join("?" * len(attempt_ids))
        wheres = {"quiz_results": (f"session_id = ? AND attempt_id IN ({marks})", (record.id, *attempt_ids))}

        def take_out() -> None:
            data.quizzes.remove(quiz)
            data.attempts = [a for a in data.attempts if a.quiz_id != quiz.id]
            save_quizzes(self.store, record.id, data)

        return self._delete(item, [], wheres if attempt_ids else {}, take_out)

    def delete_concept(self, concept_id: str) -> TrashItem:
        with self.profile.connect() as con:
            row = con.execute("SELECT name FROM concepts WHERE id = ? AND merged_into IS NULL AND removed_at IS NULL",
                              (concept_id,)).fetchone()  # fmt: skip
        if row is None:
            raise KeyError(f"no concept {concept_id!r}")
        item = TrashItem(id=_new_id(), kind="concept", subject=concept_id, label=row["name"])

        def take_out() -> None:
            with self.profile.connect() as con:
                set_removed(con, concept_id, True)

        return self._delete(item, [], {"quiz_results": ("concept_id = ?", (concept_id,))}, take_out)

    def _delete(self, item: TrashItem, paths: list[Path], wheres: dict[str, Where],
                take_out: Callable[[], None] | None = None) -> TrashItem:  # fmt: skip
        folder = self._dir(item.id)
        present = [p for p in paths if p.exists()]
        item.files = [p.relative_to(self.store.root).as_posix() for p in present]
        write_model(folder / ITEM_FILE, item)
        moved: list[Path] = []
        try:
            for path in present:
                move_path(path, folder / FILES_DIR / path.relative_to(self.store.root))
                moved.append(path)
            if take_out is not None:
                take_out()
        except Exception:
            # A file in use (an MP3 being played, on Windows) leaves everything as it was.
            for path in reversed(moved):
                move_path(folder / FILES_DIR / path.relative_to(self.store.root), path)
            shutil.rmtree(folder, ignore_errors=True)
            raise
        if not wheres:
            return item
        with self.profile.connect() as con:
            for table, (where, params) in wheres.items():
                rows = con.execute(f"SELECT * FROM {table} WHERE {where}", params).fetchall()  # noqa: S608
                item.rows[table] = [dict(r) for r in rows]
                con.execute(f"DELETE FROM {table} WHERE {where}", params)  # noqa: S608
            log_event(con, f"{item.kind}.removed", item.subject, "user",
                      before={"label": item.label, **{t: len(r) for t, r in item.rows.items()}})  # fmt: skip
            # Written before the commit: a crash in between leaves the rows in both places, and restoring skips them.
            write_model(folder / ITEM_FILE, item)
        return item

    # Restoring

    def restore(self, item_id: str) -> TrashItem:
        item = self.get(item_id)
        folder = self._dir(item.id)
        if item.session_id and not (self.store.session_dir(item.session_id) / "session.json").is_file():
            raise TrashConflict(f'Its session "{item.session_label}" is not in the list; restore the session first.')
        if item.kind == "concept":
            with self.profile.connect() as con:
                if con.execute("SELECT 1 FROM concepts WHERE id = ?", (item.subject,)).fetchone() is None:
                    raise TrashConflict(f'"{item.label}" went with the deleted profile; delete it for good.')
                set_removed(con, item.subject, False)
        pending = [(folder / FILES_DIR / f, self.store.root / f) for f in item.files]
        pending = [(src, dst) for src, dst in pending if src.exists()]
        if any(dst.exists() for _, dst in pending):
            raise TrashConflict(f"{item.label} is in the list again; delete that one before restoring this one.")
        back: list[tuple[Path, Path]] = []
        try:
            for src, dst in reversed(pending):  # the record last, so the item shows only once it is whole
                move_path(src, dst)
                back.append((src, dst))
        except Exception:
            for src, dst in reversed(back):
                move_path(dst, src)
            raise
        if item.kind == "question" and item.content:
            self._return_question(item.session_id, QAExchange.model_validate(item.content))
        elif item.kind == "quiz" and item.content:
            self._return_quiz(item.session_id, Quiz.model_validate(item.content["quiz"]),
                              [QuizAttempt.model_validate(a) for a in item.content["attempts"]])  # fmt: skip
        if item.rows:
            with self.profile.connect() as con:
                counts = {t: _return_rows(con, t, rows) for t, rows in item.rows.items()}
                log_event(con, f"{item.kind}.restored", item.subject, "user", after={"label": item.label, **counts})
        shutil.rmtree(folder)
        return item

    def _return_question(self, session_id: str, exchange: QAExchange) -> None:
        history = load_history(self.store, session_id)
        if all(x.id != exchange.id for x in history.exchanges):
            history.exchanges = sorted([*history.exchanges, exchange], key=lambda x: x.asked_at)
            save_history(self.store, session_id, history)

    def _return_quiz(self, session_id: str, quiz: Quiz, attempts: list[QuizAttempt]) -> None:
        data = load_quizzes(self.store, session_id)
        if all(q.id != quiz.id for q in data.quizzes):
            data.quizzes = sorted([*data.quizzes, quiz], key=lambda q: q.created_at)
        known = {a.id for a in data.attempts}
        data.attempts += [a for a in attempts if a.id not in known]
        data.attempts.sort(key=lambda a: a.created_at)
        save_quizzes(self.store, session_id, data)

    # Purging

    def purge(self, item_id: str) -> list[str]:
        """Delete an item for good; a session takes its trashed questions and quizzes with it."""
        item = self.get(item_id)
        gone = [item.id]
        if item.kind == "session":
            gone += [i.id for i in self.items() if i.session_id == item.subject]
        if item.kind == "concept":
            # The row stays, marked removed, so extraction keeps skipping it; what hangs on it goes.
            with self.profile.connect() as con:
                for table in ("quiz_results", "concept_sources"):
                    con.execute(f"DELETE FROM {table} WHERE concept_id = ?", (item.subject,))  # noqa: S608
        for i in gone:
            shutil.rmtree(self._dir(i))
        return gone

    def empty(self) -> int:
        items = self.items()
        for item in items:
            if (self._dir(item.id) / ITEM_FILE).is_file():  # not already gone with its session
                self.purge(item.id)
        for folder in self.root.iterdir():
            shutil.rmtree(folder)
        return len(items)

    def purge_expired(self, keep_days: float, now: datetime | None = None) -> list[str]:
        """Purge items older than keep_days (none when it is 0), and folders a delete left without item.json."""
        for folder in self.root.iterdir():
            if not (folder / ITEM_FILE).is_file():
                shutil.rmtree(folder)  # interrupted before anything moved
        if keep_days <= 0:
            return []
        cutoff = (now or utc_now()) - timedelta(days=keep_days)
        gone: list[str] = []
        for item in self.items():
            if item.deleted_at < cutoff and item.id not in gone:
                gone += self.purge(item.id)
        return gone


def _new_id() -> str:
    return f"{utc_now():%Y%m%d-%H%M%S}-{secrets.token_hex(3)}"


def _return_rows(con: sqlite3.Connection, table: str, rows: list[dict[str, Any]]) -> int:
    """Put rows back, following concept merges; rows already there, or whose concept is gone, are skipped."""
    keys = ROW_KEYS.get(table)
    if keys is None:
        return 0
    columns = {r["name"] for r in con.execute(f"PRAGMA table_info({table})")}
    count = 0
    for row in rows:
        row = {k: v for k, v in row.items() if k in columns}
        if "concept_id" in row:
            active = resolve(con, row["concept_id"])
            if active is None:  # deleted with the profile
                continue
            row["concept_id"] = active
        match = " AND ".join(f"{k} = ?" for k in keys)
        if con.execute(f"SELECT 1 FROM {table} WHERE {match}", [row[k] for k in keys]).fetchone():  # noqa: S608
            continue
        names = ", ".join(row)
        marks = ", ".join("?" * len(row))
        con.execute(f"INSERT INTO {table} ({names}) VALUES ({marks})", list(row.values()))  # noqa: S608
        count += 1
    return count
