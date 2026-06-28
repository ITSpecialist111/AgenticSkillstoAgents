"""Unit tests for the registry MCP server's pure tool functions.

We deliberately test ``tool_*`` directly (no FastMCP, no transport) so the
suite runs in CI without the MCP SDK doing any I/O. ``build_server`` and
``build_http_app`` get smoke-imported separately to catch wiring drift.
"""

from __future__ import annotations

import os
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import server  # noqa: E402

REPO_ROOT = os.path.dirname(_HERE)
EXAMPLES = os.path.join(REPO_ROOT, "examples")


@pytest.fixture(scope="module")
def registry():
    return server.load_registry(examples_dir=EXAMPLES)


def test_load_registry_local_default(monkeypatch):
    monkeypatch.delenv("REGISTRY_CATALOG_MODE", raising=False)
    reg = server.load_registry()
    assert "finance/invoice-extract" in reg.skills


def test_load_registry_unknown_mode(monkeypatch):
    monkeypatch.setenv("REGISTRY_CATALOG_MODE", "spaceship")
    with pytest.raises(server.CatalogError):
        server.load_registry()


def test_load_registry_remote_needs_url(monkeypatch):
    monkeypatch.setenv("REGISTRY_CATALOG_MODE", "remote")
    monkeypatch.delenv("REGISTRY_CATALOG_URL", raising=False)
    with pytest.raises(server.CatalogError):
        server.load_registry()


def test_find_skill_by_capability_hit(registry):
    hits = server.tool_find_skill_by_capability(registry, "invoice.extract")
    assert len(hits) == 1
    only = hits[0]
    assert only["id"] == "finance/invoice-extract"
    # The summary must carry the MCP binding — that's what makes the result
    # actionable to a calling agent.
    assert "mcp" in only and only["mcp"], "summary must include the MCP binding"
    assert "capabilityTags" in only
    assert "invoice.extract" in only["capabilityTags"]


def test_find_skill_by_capability_miss(registry):
    assert server.tool_find_skill_by_capability(registry, "nope.does.not.exist") == []


def test_describe_skill_returns_full_manifest(registry):
    manifest = server.tool_describe_skill(registry, "finance/invoice-extract")
    # Full manifest, not the summary shape.
    assert manifest["identity"]["id"] == "finance/invoice-extract"
    assert "governance" in manifest
    assert "scoring" in manifest


def test_describe_skill_unknown_raises(registry):
    with pytest.raises(KeyError):
        server.tool_describe_skill(registry, "finance/does-not-exist")


def test_list_capabilities_is_sorted_and_indexed(registry):
    idx = server.tool_list_capabilities(registry)
    assert "invoice.extract" in idx
    assert idx["invoice.extract"] == ["finance/invoice-extract"]
    # Both tags and skill-ids per tag are sorted for deterministic output.
    assert list(idx) == sorted(idx)
    for sids in idx.values():
        assert sids == sorted(sids)


def test_build_server_registers_three_tools():
    """Smoke-test the FastMCP wiring: the three discovery tools must show up."""
    srv = server.build_server()
    # FastMCP exposes the registered tools via list_tools (async). Use the
    # underlying tool manager for a sync check.
    names = {t.name for t in srv._tool_manager.list_tools()}
    assert {"find_skill_by_capability", "describe_skill", "list_capabilities"} <= names


def test_build_server_mounts_streamable_http_at_api_mcp():
    srv = server.build_server()
    assert srv.settings.streamable_http_path == server.MCP_HTTP_PATH == "/api/mcp"


def test_http_app_exposes_probe_and_health():
    """The wrapper Starlette app must answer GET /api/mcp and GET /health so
    Cowork-side probes (and Container Apps liveness checks) don't 404."""
    from starlette.testclient import TestClient

    app = server.build_http_app()
    client = TestClient(app)

    probe = client.get(server.MCP_HTTP_PATH)
    assert probe.status_code == 200
    body = probe.json()
    assert body["service"] == "skills-registry-mcp"
    assert set(body["tools"]) == {
        "find_skill_by_capability",
        "describe_skill",
        "list_capabilities",
    }

    health = client.get("/health")
    assert health.status_code == 200
    assert health.json() == {"status": "ok"}
