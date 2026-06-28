"""Unit tests for the registry MCP server's pure tool functions.

We deliberately test ``tool_*`` directly (no FastMCP, no transport) so the
suite runs in CI without the MCP SDK doing any I/O. ``build_server`` and
``build_http_app`` get smoke-imported separately to catch wiring drift.
"""

from __future__ import annotations

import json
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


# --- remote catalog backend --------------------------------------------------


class _FakeBlobClient:
    """Returns a canned catalog payload for GET requests. Counts calls so the
    TTL cache can be verified."""

    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code
        self.get_calls = 0

    def get(self, url):
        self.get_calls += 1
        return _FakeResponse(self.status_code, self.payload)

    def close(self):
        pass


def _bundled_catalog():
    """Use the on-disk examples to produce a real catalog payload so tests
    exercise the actual index() shape, not a hand-rolled stub."""
    import lite as _lite

    return _lite.Registry.from_dir(EXAMPLES).index()


def test_load_remote_registry_round_trips():
    """Remote mode must return a Registry that answers the same discovery
    queries as the local backend — that's the whole point of Stage 2."""
    server._clear_remote_cache()
    catalog = _bundled_catalog()
    fake = _FakeBlobClient(catalog)
    reg = server._load_remote_registry(
        "https://example/catalog.json", http_client=fake, now=0.0
    )
    assert "finance/invoice-extract" in reg.skills
    hits = server.tool_find_skill_by_capability(reg, "invoice.extract")
    assert [h["id"] for h in hits] == ["finance/invoice-extract"]


def test_load_remote_registry_uses_ttl_cache():
    server._clear_remote_cache()
    fake = _FakeBlobClient(_bundled_catalog())
    url = "https://example/catalog-ttl.json"
    # First call hits the network.
    server._load_remote_registry(url, http_client=fake, now=0.0, ttl_seconds=60)
    # Second call within TTL must NOT hit the network again.
    server._load_remote_registry(url, http_client=fake, now=30.0, ttl_seconds=60)
    assert fake.get_calls == 1
    # After TTL elapses, we fetch again.
    server._load_remote_registry(url, http_client=fake, now=120.0, ttl_seconds=60)
    assert fake.get_calls == 2


def test_load_remote_registry_propagates_http_error():
    server._clear_remote_cache()
    fake = _FakeBlobClient({"message": "not found"}, status_code=404)
    with pytest.raises(server.CatalogError, match="404"):
        server._load_remote_registry(
            "https://example/missing.json", http_client=fake, now=0.0
        )


def test_load_remote_registry_rejects_summary_only_catalog():
    """A catalog produced with include_manifests=False can answer
    find_skill_by_capability but not describe_skill, so we refuse it loudly
    at load time instead of failing per-tool-call later."""
    server._clear_remote_cache()
    import lite as _lite

    compact = _lite.Registry.from_dir(EXAMPLES).index(include_manifests=False)
    fake = _FakeBlobClient(compact)
    with pytest.raises(server.CatalogError, match="manifests"):
        server._load_remote_registry(
            "https://example/compact.json", http_client=fake, now=0.0
        )


def test_remote_mode_via_env(monkeypatch):
    """End-to-end: env vars switch the backend to remote and load_registry
    plumbs the URL through. Uses monkeypatch to inject the fake client."""
    server._clear_remote_cache()
    monkeypatch.setenv("REGISTRY_CATALOG_MODE", "remote")
    monkeypatch.setenv("REGISTRY_CATALOG_URL", "https://example/env-cat.json")
    fake = _FakeBlobClient(_bundled_catalog())
    monkeypatch.setattr(
        server,
        "_load_remote_registry",
        lambda url, ttl_seconds, http_client=None, now=None: server.lite.Registry.from_catalog(
            fake.get(url).json()
        ),
    )
    reg = server.load_registry()
    assert "finance/invoice-extract" in reg.skills


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
    manifest = server.tool_describe_skill(
        registry, "finance/invoice-extract", examples_dir=EXAMPLES
    )
    # Full manifest, not the summary shape.
    assert manifest["identity"]["id"] == "finance/invoice-extract"
    assert "governance" in manifest
    assert "scoring" in manifest


def test_describe_skill_unknown_raises(registry):
    with pytest.raises(KeyError):
        server.tool_describe_skill(registry, "finance/does-not-exist")


def test_describe_skill_lists_payload_files(registry):
    """describe_skill must surface skill:// URIs for payload files (SKILL.md +
    assets). Resources don't count against Cowork's 20-tool cap, so this is
    how agents read narrative + schemas without inflating the system prompt."""
    manifest = server.tool_describe_skill(
        registry, "finance/invoice-extract", examples_dir=EXAMPLES
    )
    files = manifest.get("payloadFiles")
    assert isinstance(files, list) and files, "expected payloadFiles to be populated"
    paths = {f["path"]: f for f in files}
    assert "SKILL.md" in paths
    assert paths["SKILL.md"]["uri"] == "skill://finance-invoice-extract/SKILL.md"
    assert paths["SKILL.md"]["mimeType"] == "text/markdown"
    assert "assets/output-schema.json" in paths
    assert paths["assets/output-schema.json"]["mimeType"] == "application/json"


def test_list_capabilities_is_sorted_and_indexed(registry):
    idx = server.tool_list_capabilities(registry)
    assert "invoice.extract" in idx
    assert idx["invoice.extract"] == ["finance/invoice-extract"]
    # Both tags and skill-ids per tag are sorted for deterministic output.
    assert list(idx) == sorted(idx)
    for sids in idx.values():
        assert sids == sorted(sids)


def test_read_payload_file_reads_skill_md():
    data, mime = server._read_payload_file(
        EXAMPLES, "finance/invoice-extract", "SKILL.md"
    )
    assert mime == "text/markdown"
    assert b"finance/invoice-extract" in data


def test_read_payload_file_rejects_traversal():
    with pytest.raises(KeyError):
        server._read_payload_file(
            EXAMPLES, "finance/invoice-extract", "../invoice-extract.manifest.json"
        )


def test_read_payload_file_missing():
    with pytest.raises(KeyError):
        server._read_payload_file(EXAMPLES, "finance/invoice-extract", "nope.txt")


def test_build_server_registers_four_tools_and_payload_resources():
    """Smoke-test the FastMCP wiring: the four tools and at least one skill://
    resource per payload file must show up."""
    srv = server.build_server(examples_dir=EXAMPLES)
    tool_names = {t.name for t in srv._tool_manager.list_tools()}
    assert {
        "find_skill_by_capability",
        "describe_skill",
        "list_capabilities",
        "submit_skill_draft",
    } <= tool_names

    resource_uris = {str(r.uri) for r in srv._resource_manager.list_resources()}
    assert "skill://finance-invoice-extract/SKILL.md" in resource_uris
    assert "skill://finance-invoice-extract/assets/output-schema.json" in resource_uris


def test_build_server_mounts_streamable_http_at_api_mcp():
    srv = server.build_server(examples_dir=EXAMPLES)
    assert srv.settings.streamable_http_path == server.MCP_HTTP_PATH == "/api/mcp"


def test_http_app_exposes_probe_and_health():
    """The wrapper Starlette app must answer GET /api/mcp and GET /health so
    Cowork-side probes (and Container Apps liveness checks) don't 404."""
    from starlette.testclient import TestClient

    app = server.build_http_app(server=server.build_server(examples_dir=EXAMPLES))
    client = TestClient(app)

    probe = client.get(server.MCP_HTTP_PATH)
    assert probe.status_code == 200
    body = probe.json()
    assert body["service"] == "skills-registry-mcp"
    assert set(body["tools"]) == {
        "find_skill_by_capability",
        "describe_skill",
        "list_capabilities",
        "submit_skill_draft",
    }

    health = client.get("/health")
    assert health.status_code == 200
    assert health.json() == {"status": "ok"}


# --- submit_skill_draft ------------------------------------------------------


def _minimal_manifest(skill_id: str = "team/widget-thing") -> dict:
    """Build a manifest that passes the canonical schema. Mirrors the fields
    used in examples/invoice-extract.manifest.json without copying any text."""
    return {
        "apiVersion": "skills.dev/v1",
        "kind": "Skill",
        "identity": {
            "id": skill_id,
            "name": "Widget Thing",
            "version": "0.1.0",
            "description": "Test fixture skill submitted via the MCP tool.",
            "owner": {
                "handle": "test.user",
                "team": "Test Team",
                "contact": "test.user@example.com",
            },
            "skillType": "deterministic-tool",
            "tags": ["test"],
        },
        "capability": {
            "summary": "Test capability",
            "capabilityTags": ["test.widget"],
            "inputs": [
                {"name": "x", "type": "string", "required": True, "description": "in"}
            ],
            "outputs": [
                {"name": "y", "type": "string", "required": True, "description": "out"}
            ],
            "preconditions": [],
            "effects": [],
        },
        "scoring": {
            "determinism": "high",
            "risk": "low",
            "reversible": True,
            "rationale": "Test fixture, no side effects.",
        },
        "dependencies": [],
        "mcp": {
            "server": "test-server",
            "toolName": "widget_thing",
            "namespace": "example-org",
            "transport": "http",
        },
        "governance": {
            "visibility": "org",
            "rbac": ["test.reader"],
            "dataClassification": "internal",
            "cost": {"unit": "usd-per-1k-calls", "estimate": 0.0},
            "audit": {"logged": True, "retentionDays": 30},
        },
        "lifecycle": {
            "stage": "draft",
        },
    }


class _FakeResponse:
    def __init__(self, status_code: int, payload):
        self.status_code = status_code
        self._payload = payload
        self.text = json.dumps(payload) if not isinstance(payload, str) else payload

    def json(self):
        return self._payload


class _FakeHttpClient:
    """Records the calls submit_skill_draft makes and replays canned responses
    in the order GitHub's REST API would actually return them."""

    def __init__(self):
        self.calls = []  # (method, url, json)

    def get(self, url, headers=None):
        self.calls.append(("GET", url, None))
        return _FakeResponse(200, {"object": {"sha": "deadbeef"}})

    def post(self, url, headers=None, json=None):
        self.calls.append(("POST", url, json))
        if url.endswith("/git/refs"):
            return _FakeResponse(201, {"ref": json["ref"], "object": {"sha": "deadbeef"}})
        if url.endswith("/pulls"):
            return _FakeResponse(
                201,
                {
                    "html_url": "https://github.com/owner/repo/pull/42",
                    "number": 42,
                },
            )
        return _FakeResponse(500, {"message": f"unexpected POST {url}"})

    def put(self, url, headers=None, json=None):
        self.calls.append(("PUT", url, json))
        return _FakeResponse(
            201, {"content": {"path": url.split("/contents/", 1)[1].split("?", 1)[0]}}
        )

    def close(self):
        pass


def test_submit_skill_draft_happy_path(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "fake-token")
    monkeypatch.setenv("GITHUB_REPO", "owner/repo")

    fake = _FakeHttpClient()
    result = server.tool_submit_skill_draft(
        manifest=_minimal_manifest(),
        payload={"SKILL.md": "# hi\n", "assets/schema.json": "{}"},
        title="Test PR",
        body="please review",
        http_client=fake,
    )

    assert result["pr_url"] == "https://github.com/owner/repo/pull/42"
    assert result["pr_number"] == 42
    assert result["branch"].startswith("agent/submit-team-widget-thing-")
    assert "examples/widget-thing.manifest.json" in result["files_added"]
    assert "examples/team-widget-thing/SKILL.md" in result["files_added"]
    assert "examples/team-widget-thing/assets/schema.json" in result["files_added"]

    methods = [c[0] for c in fake.calls]
    # GET base ref, POST new branch, PUT each file (3), POST PR.
    assert methods == ["GET", "POST", "PUT", "PUT", "PUT", "POST"]


def test_submit_skill_draft_no_token(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    with pytest.raises(server.SubmitError, match="GITHUB_TOKEN"):
        server.tool_submit_skill_draft(
            manifest=_minimal_manifest(), http_client=_FakeHttpClient()
        )


def test_submit_skill_draft_invalid_manifest(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "fake-token")
    bad = _minimal_manifest()
    del bad["identity"]["version"]  # schema violation
    with pytest.raises(server.SubmitError, match="schema validation"):
        server.tool_submit_skill_draft(manifest=bad, http_client=_FakeHttpClient())


def test_submit_skill_draft_rejects_payload_traversal(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "fake-token")
    with pytest.raises(server.SubmitError, match="unsafe payload path"):
        server.tool_submit_skill_draft(
            manifest=_minimal_manifest(),
            payload={"../evil.txt": "x"},
            http_client=_FakeHttpClient(),
        )


def test_submit_skill_draft_github_error_propagates(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "fake-token")

    class _BrokenClient(_FakeHttpClient):
        def get(self, url, headers=None):
            return _FakeResponse(404, {"message": "Not Found"})

    with pytest.raises(server.SubmitError, match="GET base ref failed"):
        server.tool_submit_skill_draft(
            manifest=_minimal_manifest(), http_client=_BrokenClient()
        )
