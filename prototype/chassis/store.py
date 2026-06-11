"""Durable storage for the registry - the repository-pattern persistence layer.

The prototype's :class:`~chassis.registry.Registry` is the system-of-record
*behaviour* (the six gates); this module is the system-of-record *substrate*. It
defines a narrow :class:`SkillStore` interface and two interchangeable backends:

* :class:`InMemoryStore` - the original ephemeral behaviour (default, zero deps).
* :class:`SqliteStore`   - durable, file-backed state that survives restarts.

Keeping persistence behind this interface is deliberate: it is the seam the
architecture docs reserve for a real backend (OneLake / Fabric IQ) later. A
manifest is stored verbatim as its JSON document, keyed by its immutable
``identity.id`` - the registry never depends on *how* it is stored.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from typing import Dict, Iterator, List, Optional, Protocol, runtime_checkable

from .manifest import Manifest, skill_id


@runtime_checkable
class SkillStore(Protocol):
    """The minimal persistence contract the registry depends on."""

    def get(self, sid: str) -> Manifest:
        """Return the manifest for ``sid`` or raise :class:`KeyError`."""

    def put(self, manifest: Manifest) -> None:
        """Insert or replace ``manifest`` (keyed by ``identity.id``)."""

    def exists(self, sid: str) -> bool:
        """Return whether a manifest with id ``sid`` is stored."""

    def all(self) -> List[Manifest]:
        """Return every stored manifest."""

    def delete(self, sid: str) -> None:
        """Remove ``sid`` (no-op if absent)."""


class InMemoryStore:
    """A process-local dict store - the original, dependency-free behaviour."""

    def __init__(self) -> None:
        self._skills: Dict[str, Manifest] = {}

    def get(self, sid: str) -> Manifest:
        if sid not in self._skills:
            raise KeyError(f"unknown skill: {sid}")
        return self._skills[sid]

    def put(self, manifest: Manifest) -> None:
        self._skills[skill_id(manifest)] = manifest

    def exists(self, sid: str) -> bool:
        return sid in self._skills

    def all(self) -> List[Manifest]:
        return list(self._skills.values())

    def delete(self, sid: str) -> None:
        self._skills.pop(sid, None)

    def __len__(self) -> int:  # pragma: no cover - convenience
        return len(self._skills)

    def __iter__(self) -> Iterator[Manifest]:  # pragma: no cover - convenience
        return iter(self.all())


class SqliteStore:
    """A file-backed store - durable registry state that survives restarts.

    Manifests are persisted as their canonical JSON document in a single table
    keyed by ``identity.id``. ``:memory:`` is accepted for tests. Access is
    serialised with a lock so the store is safe to share across the API's
    request handlers.
    """

    def __init__(self, path: str = ":memory:") -> None:
        self.path = path
        # check_same_thread=False + an explicit lock lets a single connection
        # back a multi-threaded server without per-thread reconnects.
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._lock = threading.Lock()
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS skills (
                id        TEXT PRIMARY KEY,
                stage     TEXT NOT NULL,
                document  TEXT NOT NULL
            )
            """
        )
        self._conn.commit()

    # ----- SkillStore -----------------------------------------------------
    def get(self, sid: str) -> Manifest:
        with self._lock:
            row = self._conn.execute(
                "SELECT document FROM skills WHERE id = ?", (sid,)
            ).fetchone()
        if row is None:
            raise KeyError(f"unknown skill: {sid}")
        return json.loads(row[0])

    def put(self, manifest: Manifest) -> None:
        sid = skill_id(manifest)
        stage = manifest.get("lifecycle", {}).get("stage", "")
        document = json.dumps(manifest, separators=(",", ":"), sort_keys=True)
        with self._lock:
            self._conn.execute(
                "INSERT INTO skills (id, stage, document) VALUES (?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET stage = excluded.stage, "
                "document = excluded.document",
                (sid, stage, document),
            )
            self._conn.commit()

    def exists(self, sid: str) -> bool:
        with self._lock:
            row = self._conn.execute(
                "SELECT 1 FROM skills WHERE id = ?", (sid,)
            ).fetchone()
        return row is not None

    def all(self) -> List[Manifest]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT document FROM skills ORDER BY id"
            ).fetchall()
        return [json.loads(row[0]) for row in rows]

    def delete(self, sid: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM skills WHERE id = ?", (sid,))
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()


def open_store(dsn: Optional[str] = None) -> SkillStore:
    """Open a store from a DSN-ish string.

    * ``None`` / empty            -> :class:`InMemoryStore`
    * ``"memory"`` / ``":memory:"`` -> in-memory SQLite
    * ``"sqlite:///path.db"`` or a bare ``path.db`` -> :class:`SqliteStore`
    """
    if not dsn or dsn == "memory":
        return InMemoryStore()
    if dsn == ":memory:":
        return SqliteStore(":memory:")
    if dsn.startswith("sqlite:///"):
        return SqliteStore(dsn[len("sqlite:///"):])
    if dsn.startswith("sqlite://"):  # sqlite://relative.db
        return SqliteStore(dsn[len("sqlite://"):])
    return SqliteStore(dsn)


__all__ = [
    "SkillStore",
    "InMemoryStore",
    "SqliteStore",
    "open_store",
]
