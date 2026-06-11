"""Tests for the durable storage layer and registry persistence."""

from __future__ import annotations

import os

import pytest

from chassis.registry import Registry, Stage
from chassis.store import InMemoryStore, SqliteStore, open_store


def test_open_store_routing(tmp_path):
    assert isinstance(open_store(None), InMemoryStore)
    assert isinstance(open_store("memory"), InMemoryStore)
    assert isinstance(open_store(":memory:"), SqliteStore)
    db = os.path.join(tmp_path, "r.db")
    assert isinstance(open_store(f"sqlite:///{db}"), SqliteStore)
    assert isinstance(open_store(db), SqliteStore)


def test_sqlite_put_get_roundtrip(invoice_extract):
    store = SqliteStore(":memory:")
    store.put(invoice_extract)
    sid = invoice_extract["identity"]["id"]
    assert store.exists(sid)
    got = store.get(sid)
    assert got["identity"]["id"] == sid
    # Mutating the returned dict must not affect stored state (sqlite re-reads).
    got["identity"]["name"] = "mutated"
    assert store.get(sid)["identity"]["name"] != "mutated"


def test_sqlite_get_missing_raises():
    store = SqliteStore(":memory:")
    with pytest.raises(KeyError):
        store.get("nope/none")


def test_sqlite_all_and_delete(invoice_extract, po_match):
    store = SqliteStore(":memory:")
    store.put(invoice_extract)
    store.put(po_match)
    assert len(store.all()) == 2
    store.delete(invoice_extract["identity"]["id"])
    assert len(store.all()) == 1


def test_registry_persists_across_instances(tmp_path, invoice_extract, as_draft):
    db = os.path.join(tmp_path, "reg.db")
    sid = invoice_extract["identity"]["id"]

    reg1 = Registry(open_store(db))
    reg1.register(as_draft(invoice_extract))
    reg1.certify(sid, approver="coe.reviewer")
    reg1.publish(sid)

    # A brand-new registry over the same file sees the published skill.
    reg2 = Registry(open_store(db))
    assert reg2.get(sid)["lifecycle"]["stage"] == Stage.PUBLISHED.value


def test_registry_on_sqlite_full_gate_path(invoice_extract, as_draft):
    reg = Registry(SqliteStore(":memory:"))
    sid = invoice_extract["identity"]["id"]
    reg.register(as_draft(invoice_extract))
    reg.certify(sid, approver="coe.reviewer")
    reg.publish(sid)
    reg.deprecate(sid, superseded_by="finance/invoice-extract@2.0.0")
    assert reg.get(sid)["lifecycle"]["supersededBy"] == "finance/invoice-extract@2.0.0"
    reg.retire(sid)
    assert reg.get(sid)["lifecycle"]["stage"] == Stage.RETIRED.value
