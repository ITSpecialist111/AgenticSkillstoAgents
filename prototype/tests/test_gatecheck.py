"""Tests for the headless gate checks (pipeline-as-CI) and MCP projection."""

from __future__ import annotations

import copy

from chassis.gatecheck import check_manifests, summarize
from chassis.mcp import published_catalog, to_mcp_tool


def test_gate_passes_clean_examples(invoice_extract, po_match):
    checks = check_manifests([("a", invoice_extract), ("b", po_match)])
    assert all(c.passed for c in checks)
    assert summarize(checks)  # non-empty report


def test_gate_flags_schema_error(invoice_extract):
    broken = copy.deepcopy(invoice_extract)
    del broken["scoring"]
    checks = check_manifests([("bad", broken)])
    assert checks[0].passed is False
    assert any("schema" in e for e in checks[0].errors)


def test_gate_flags_duplicate_capability_in_changeset(invoice_extract):
    clone = copy.deepcopy(invoice_extract)
    clone["identity"]["id"] = "finance/invoice-extract-2"
    checks = check_manifests([("a", invoice_extract), ("b", clone)])
    # One keeps the tag; the other is flagged as a duplicate-capability failure.
    assert any(not c.passed for c in checks)
    assert any("duplicate-capability" in e for c in checks for e in c.errors)


def test_gate_warns_on_unresolved_dependency(po_match):
    # po-match depends on invoice.extract, absent from this single-item changeset.
    checks = check_manifests([("only", po_match)])
    assert checks[0].passed  # warning, not failure
    assert any("not resolved" in w for w in checks[0].warnings)


def test_mcp_tool_projection_shape(invoice_extract):
    tool = to_mcp_tool(invoice_extract)
    assert tool["name"] == "invoice_extract"
    assert tool["inputSchema"]["type"] == "object"
    assert "document" in tool["inputSchema"]["properties"]
    assert tool["_meta"]["skillId"] == "finance/invoice-extract"


def test_mcp_catalog_only_includes_published(invoice_extract, po_match):
    pub = copy.deepcopy(invoice_extract)
    pub["lifecycle"]["stage"] = "published"
    draft = copy.deepcopy(po_match)
    draft["lifecycle"]["stage"] = "registered"
    catalog = published_catalog([pub, draft])
    names = [t["_meta"]["skillId"] for t in catalog["tools"]]
    assert names == ["finance/invoice-extract"]
