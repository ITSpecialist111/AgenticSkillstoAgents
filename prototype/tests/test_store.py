"""Tests for pluggable registry persistence backends."""

from __future__ import annotations

from pathlib import Path

from chassis.registry import Registry
from chassis.store import InMemoryStore, SqliteStore, open_store


def test_open_store_memory_default():
    assert isinstance(open_store(), InMemoryStore)
    assert isinstance(open_store("memory"), InMemoryStore)


def test_open_store_sqlite(tmp_path: Path):
    db = tmp_path / "skills.db"
    store = open_store(f"sqlite:///{db}")
    assert isinstance(store, SqliteStore)


def test_registry_persists_with_sqlite(invoice_extract, as_draft, tmp_path: Path):
    db = tmp_path / "skills.db"
    dsn = f"sqlite:///{db}"
    sid = invoice_extract["identity"]["id"]

    reg1 = Registry(open_store(dsn))
    reg1.register(as_draft(invoice_extract))
    reg1.certify(sid, approver="coe.reviewer")
    reg1.publish(sid)

    reg2 = Registry(open_store(dsn))
    loaded = reg2.get(sid)
    assert loaded["lifecycle"]["stage"] == "published"


def test_open_store_rejects_unknown_dsn():
    try:
        open_store("postgres://example")
    except ValueError as exc:
        assert "unsupported store DSN" in str(exc)
    else:  # pragma: no cover - defensive
        raise AssertionError("expected ValueError for unsupported dsn")
