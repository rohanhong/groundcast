"""Data directory layout (spec section 15a).

<data_dir>/
  materials/<id>.<ext>        original files
  materials/<id>.json         Material record
  chunks/<id>.json            list of Chunk records
  sessions/<session id>/      brief, script JSON, verification report, MP3, transcript, Q&A, quizzes
  profile.sqlite3             concept table, quiz results, event log (groundcast.profile)
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import time
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel, TypeAdapter

from groundcast.models import Chunk, Material, SessionRecord

M = TypeVar("M", bound=BaseModel)

_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]+$")

# On Windows, replacing a file fails with PermissionError while another thread
# or process has it open (for example the web UI reading session.json). Such
# reads take milliseconds, so a short retry outlasts them.
_REPLACE_ATTEMPTS = 20
_REPLACE_DELAY_S = 0.05


def _replace(src: str, dst: Path) -> None:
    for attempt in range(1, _REPLACE_ATTEMPTS + 1):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if attempt == _REPLACE_ATTEMPTS:
                raise
            time.sleep(_REPLACE_DELAY_S)


def write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        _replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def write_model(path: Path, model: BaseModel) -> None:
    write_text_atomic(path, model.model_dump_json(indent=2))


def read_model(path: Path, cls: type[M]) -> M:
    return cls.model_validate_json(path.read_text(encoding="utf-8"))


def check_id(value: str) -> str:
    """Reject IDs that could escape the data directory."""
    if not _SAFE_ID.match(value):
        raise ValueError(f"invalid id: {value!r}")
    return value


class Store:
    def __init__(self, data_dir: Path) -> None:
        self.root = data_dir
        self.materials_dir = data_dir / "materials"
        self.chunks_dir = data_dir / "chunks"
        self.sessions_dir = data_dir / "sessions"
        for d in (self.materials_dir, self.chunks_dir, self.sessions_dir):
            d.mkdir(parents=True, exist_ok=True)

    # Materials and chunks

    def material_path(self, material: Material) -> Path:
        return self.materials_dir / material.stored_name

    def save_material(self, material: Material, chunks: list[Chunk]) -> None:
        write_text_atomic(
            self.chunks_dir / f"{check_id(material.id)}.json",
            json.dumps([c.model_dump() for c in chunks], indent=1),
        )
        write_model(self.materials_dir / f"{material.id}.json", material)

    def get_material(self, material_id: str) -> Material:
        return read_model(self.materials_dir / f"{check_id(material_id)}.json", Material)

    def has_material(self, material_id: str) -> bool:
        return (self.materials_dir / f"{check_id(material_id)}.json").is_file()

    def list_materials(self) -> list[Material]:
        items = [read_model(p, Material) for p in self.materials_dir.glob("*.json")]
        return sorted(items, key=lambda m: m.added_at)

    def get_chunks(self, material_id: str) -> list[Chunk]:
        raw = (self.chunks_dir / f"{check_id(material_id)}.json").read_text(encoding="utf-8")
        return TypeAdapter(list[Chunk]).validate_json(raw)

    def delete_material(self, material_id: str) -> None:
        material = self.get_material(material_id)
        self.material_path(material).unlink(missing_ok=True)
        (self.chunks_dir / f"{material.id}.json").unlink(missing_ok=True)
        (self.materials_dir / f"{material.id}.json").unlink(missing_ok=True)

    # Sessions

    def session_dir(self, session_id: str) -> Path:
        return self.sessions_dir / check_id(session_id)

    def save_session(self, record: SessionRecord) -> None:
        write_model(self.session_dir(record.id) / "session.json", record)

    def get_session(self, session_id: str) -> SessionRecord:
        return read_model(self.session_dir(session_id) / "session.json", SessionRecord)

    def list_sessions(self) -> list[SessionRecord]:
        items = [read_model(p, SessionRecord) for p in self.sessions_dir.glob("*/session.json")]
        return sorted(items, key=lambda r: r.created_at, reverse=True)
