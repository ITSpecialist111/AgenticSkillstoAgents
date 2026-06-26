"""Registry persistence backends for the chassis prototype.

The prototype defaults to an in-memory store for tests and walkthroughs, but
can also persist registry state in SQLite via a DSN:

    sqlite:///absolute/path/to/skills.db
"""

from __future__ import annotations

import json
import sqlite3
from abc import ABC, abstractmethod
from typing import Dict, List

from .manifest import Manifest, skill_id


class SkillStore(ABC):
    """Abstract persistence contract used by :class:`chassis.registry.Registry`."""

    @abstractmethod
    def exists(self, sid: str) -> bool: ...

    @abstractmethod
    def get(self, sid: str) -> Manifest: ...

    @abstractmethod
    def all(self) -> List[Manifest]: ...

    @abstractmethod
    def put(self, manifest: Manifest) -> None: ...


class InMemoryStore(SkillStore):
    """Simple dictionary-backed store used by default."""

    def __init__(self) -> None:
        self._skills: Dict[str, Manifest] = {}

    def exists(self, sid: str) -> bool:
        return sid in self._skills

    def get(self, sid: str) -> Manifest:
        return self._skills[sid]

    def all(self) -> List[Manifest]:
        return list(self._skills.values())

    def put(self, manifest: Manifest) -> None:
        self._skills[skill_id(manifest)] = manifest


class SqliteStore(SkillStore):
    """SQLite-backed store for local persistence between runs."""

    def __init__(self, path: str) -> None:
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS skills (
                id TEXT PRIMARY KEY,
                manifest_json TEXT NOT NULL
            )
            """
        )
        self._conn.commit()

    def exists(self, sid: str) -> bool:
        row = self._conn.execute("SELECT 1 FROM skills WHERE id = ?", (sid,)).fetchone()
        return row is not None

    def get(self, sid: str) -> Manifest:
        row = self._conn.execute(
            "SELECT manifest_json FROM skills WHERE id = ?",
            (sid,),
        ).fetchone()
        if row is None:
            raise KeyError(sid)
        return json.loads(row[0])

    def all(self) -> List[Manifest]:
        rows = self._conn.execute(
            "SELECT manifest_json FROM skills ORDER BY id"
        ).fetchall()
        return [json.loads(row[0]) for row in rows]

    def put(self, manifest: Manifest) -> None:
        sid = skill_id(manifest)
        payload = json.dumps(manifest, sort_keys=True)
        self._conn.execute(
            """
            INSERT INTO skills (id, manifest_json)
            VALUES (?, ?)
            ON CONFLICT(id) DO UPDATE SET manifest_json = excluded.manifest_json
            """,
            (sid, payload),
        )
        self._conn.commit()


def open_store(dsn: str | None = None) -> SkillStore:
    """Open a store from DSN.

    Supported values:
    - ``None`` or ``memory``: in-memory store.
    - ``sqlite:///absolute/path.db``: SQLite persistence.
    """

    if not dsn or dsn == "memory":
        return InMemoryStore()
    if dsn.startswith("sqlite:///"):
        path = dsn[len("sqlite:///") :]
        if not path:
            raise ValueError("sqlite DSN requires an absolute database path")
        return SqliteStore(path)
    raise ValueError(f"unsupported store DSN: {dsn!r}")
