"""Tests for the HTTP API. Skipped entirely if the optional api extra is absent."""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from chassis.api import create_app  # noqa: E402
from chassis.registry import Registry  # noqa: E402
from chassis.store import SqliteStore  # noqa: E402


@pytest.fixture
def client():
    return TestClient(create_app(Registry(SqliteStore(":memory:"))))


def test_healthz(client):
    assert client.get("/healthz").json() == {"status": "ok"}


def test_full_gate_path_over_http(client, invoice_extract, as_draft):
    sid = invoice_extract["identity"]["id"]
    assert client.post("/skills", json=as_draft(invoice_extract)).status_code == 201
    assert client.get(f"/skills/{sid}").json()["lifecycle"]["stage"] == "registered"
    assert (
        client.post(f"/skills/{sid}/certify", json={"approver": "coe.reviewer"}).status_code
        == 200
    )
    assert client.post(f"/skills/{sid}/publish").json()["lifecycle"]["stage"] == "published"
    # Published skill is discoverable via MCP catalog + capability matchmaking.
    tools = client.get("/mcp/tools").json()["tools"]
    assert any(t["_meta"]["skillId"] == sid for t in tools)
    caps = client.get("/capabilities", params={"tag": "invoice.extract"}).json()
    assert caps and caps[0]["skillId"] == sid


def test_register_rejects_invalid_manifest(client):
    assert client.post("/skills", json={"not": "a manifest"}).status_code == 422


def test_certify_conflict_without_approver(client, invoice_extract, as_draft):
    sid = invoice_extract["identity"]["id"]
    client.post("/skills", json=as_draft(invoice_extract))
    assert client.post(f"/skills/{sid}/certify", json={"approver": ""}).status_code == 409


def test_unknown_skill_is_404(client):
    assert client.get("/skills/no/such").status_code == 404


def test_metrics_endpoint(client, invoice_extract, as_draft):
    client.post("/skills", json=as_draft(invoice_extract))
    body = client.get("/metrics").json()
    assert "registry" in body and "meaning" in body
