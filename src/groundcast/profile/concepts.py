"""The global concept table (spec 8.1, Q13).

One table for all materials, so quiz results add up across them. A concept's
ID is the slug of its name when it was created and never changes; renaming
changes only the name. Merging moves a concept's sources and quiz results to
another concept and keeps the merged row, pointing at the one it went into.
Every change by the learner goes into the event log.
"""

from __future__ import annotations

import re
import sqlite3
import unicodedata
from collections.abc import Iterable
from datetime import datetime

from pydantic import BaseModel, Field

from groundcast.models import utc_now
from groundcast.profile.db import EventSource, ProfileDB, log_event


class Concept(BaseModel):
    id: str
    name: str
    description: str = ""
    created_at: datetime
    material_ids: list[str] = Field(default_factory=list)
    chunks: int = 0  # passages it was found in
    asked: int = 0  # quiz answers on it
    right: int = 0


def slugify(name: str) -> str:
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", ascii_name.lower()).strip("-") or "concept"


_SELECT = """
SELECT c.id, c.name, c.description, c.created_at,
       (SELECT GROUP_CONCAT(DISTINCT s.material_id) FROM concept_sources s WHERE s.concept_id = c.id) AS materials,
       (SELECT COUNT(*) FROM concept_sources s WHERE s.concept_id = c.id) AS chunks,
       (SELECT COUNT(*) FROM quiz_results q WHERE q.concept_id = c.id) AS asked,
       (SELECT COALESCE(SUM(q.right), 0) FROM quiz_results q WHERE q.concept_id = c.id) AS right
FROM concepts c
WHERE c.merged_into IS NULL
"""


def _concept(row: sqlite3.Row) -> Concept:
    data = dict(row)
    materials = data.pop("materials")
    return Concept(**data, material_ids=sorted(materials.split(",")) if materials else [])


def list_concepts(db: ProfileDB, material_ids: Iterable[str] | None = None) -> list[Concept]:
    """Active concepts, by name; with material_ids, only those found in one of them."""
    with db.connect() as con:
        rows = con.execute(_SELECT + " ORDER BY c.name COLLATE NOCASE").fetchall()
    concepts = [_concept(r) for r in rows]
    if material_ids is not None:
        wanted = set(material_ids)
        concepts = [c for c in concepts if wanted & set(c.material_ids)]
    return concepts


def resolve(con: sqlite3.Connection, concept_id: str) -> str | None:
    """The active concept an ID now stands for, following merges; None when unknown."""
    seen = set()
    while concept_id not in seen:
        seen.add(concept_id)
        row = con.execute("SELECT merged_into FROM concepts WHERE id = ?", (concept_id,)).fetchone()
        if row is None:
            return None
        if row["merged_into"] is None:
            return concept_id
        concept_id = row["merged_into"]
    return None


def add_concept(con: sqlite3.Connection, name: str, description: str, source: EventSource, reason: str = "") -> str:
    base = slugify(name)
    concept_id, n = base, 1
    while con.execute("SELECT 1 FROM concepts WHERE id = ?", (concept_id,)).fetchone():
        n += 1
        concept_id = f"{base}-{n}"
    con.execute(
        "INSERT INTO concepts (id, name, description, created_at) VALUES (?, ?, ?, ?)",
        (concept_id, name.strip(), description.strip(), utc_now().isoformat()),
    )
    log_event(con, "concept.created", concept_id, source, after={"name": name.strip()}, reason=reason)
    return concept_id


def link_sources(con: sqlite3.Connection, concept_id: str, material_id: str, chunk_ids: Iterable[str]) -> None:
    con.executemany(
        "INSERT OR IGNORE INTO concept_sources (concept_id, material_id, chunk_id) VALUES (?, ?, ?)",
        [(concept_id, material_id, c) for c in chunk_ids],
    )


def rename(db: ProfileDB, concept_id: str, name: str) -> None:
    name = name.strip()
    if not name:
        raise ValueError("a concept name cannot be empty")
    with db.connect() as con:
        row = con.execute("SELECT name FROM concepts WHERE id = ? AND merged_into IS NULL", (concept_id,)).fetchone()
        if row is None:
            raise KeyError(concept_id)
        con.execute("UPDATE concepts SET name = ? WHERE id = ?", (name, concept_id))
        log_event(con, "concept.renamed", concept_id, "user", before={"name": row["name"]}, after={"name": name})


def merge(db: ProfileDB, source_id: str, target_id: str) -> None:
    """Merge source into target: its sources and quiz results become the target's."""
    if source_id == target_id:
        raise ValueError("a concept cannot be merged into itself")
    with db.connect() as con:
        names = {}
        for cid in (source_id, target_id):
            row = con.execute("SELECT name FROM concepts WHERE id = ? AND merged_into IS NULL", (cid,)).fetchone()
            if row is None:
                raise KeyError(cid)
            names[cid] = row["name"]
        con.execute(
            "INSERT OR IGNORE INTO concept_sources (concept_id, material_id, chunk_id) "
            "SELECT ?, material_id, chunk_id FROM concept_sources WHERE concept_id = ?",
            (target_id, source_id),
        )
        con.execute("DELETE FROM concept_sources WHERE concept_id = ?", (source_id,))
        con.execute("UPDATE quiz_results SET concept_id = ? WHERE concept_id = ?", (target_id, source_id))
        con.execute("UPDATE concepts SET merged_into = ? WHERE merged_into = ?", (target_id, source_id))
        con.execute("UPDATE concepts SET merged_into = ? WHERE id = ?", (target_id, source_id))
        log_event(
            con,
            "concept.merged",
            source_id,
            "user",
            before={"id": source_id, "name": names[source_id]},
            after={"id": target_id, "name": names[target_id]},
        )


def is_extracted(db: ProfileDB, material_id: str) -> bool:
    with db.connect() as con:
        return con.execute("SELECT 1 FROM extractions WHERE material_id = ?", (material_id,)).fetchone() is not None


def forget_material(db: ProfileDB, material_id: str) -> None:
    """Drop a deleted material's passages; its concepts and quiz results stay."""
    with db.connect() as con:
        removed = con.execute("DELETE FROM concept_sources WHERE material_id = ?", (material_id,)).rowcount
        con.execute("DELETE FROM extractions WHERE material_id = ?", (material_id,))
        log_event(con, "material.removed", material_id, "user", before={"concept_sources": removed})


def record_quiz(db: ProfileDB, session_id: str, attempt_id: str, results: Iterable[tuple[str, str, bool]]) -> None:
    """results: (concept ID, question ID, answered right) for every answered question and concept."""
    at = utc_now().isoformat()
    with db.connect() as con:
        rows = []
        for concept_id, question_id, right in results:
            active = resolve(con, concept_id)
            if active is not None:
                rows.append((active, session_id, question_id, attempt_id, int(right), at))
        con.executemany(
            "INSERT INTO quiz_results (concept_id, session_id, question_id, attempt_id, right, at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            rows,
        )
