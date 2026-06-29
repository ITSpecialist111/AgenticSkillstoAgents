"""Smoke tests for the lite chassis. Mirrors the meaningful checks from
prototype/tests/ without the ceremony the lite version intentionally drops."""

from __future__ import annotations

import copy
import json
import os

import pytest

import lite


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXAMPLES = os.path.join(REPO_ROOT, "examples")


def test_loads_all_bundled_examples():
    reg = lite.Registry.from_dir(EXAMPLES)
    assert {
        "finance/invoice-extract",
        "finance/po-match",
        "finance/ap-intake",
    } <= set(reg.skills)


def test_invalid_manifest_rejected(tmp_path):
    bad = tmp_path / "bad.manifest.json"
    bad.write_text(json.dumps({"apiVersion": "skills.dev/v1"}))
    with pytest.raises(lite.ManifestError):
        lite.load(str(bad))


def test_find_by_capability_filters_to_published():
    reg = lite.Registry.from_dir(EXAMPLES)
    hits = reg.find_by_capability("invoice.extract")
    assert [m["identity"]["id"] for m in hits] == ["finance/invoice-extract"]


def test_list_capabilities_inverts_index():
    reg = lite.Registry.from_dir(EXAMPLES)
    idx = reg.list_capabilities()
    assert "invoice.extract" in idx
    assert "finance/invoice-extract" in idx["invoice.extract"]


def test_no_duplicates_in_bundle():
    reg = lite.Registry.from_dir(EXAMPLES)
    assert reg.duplicates() == []


def test_duplicate_detection_fires_on_clone():
    reg = lite.Registry.from_dir(EXAMPLES)
    clone = copy.deepcopy(reg.skills["finance/invoice-extract"])
    clone["identity"]["id"] = "finance/invoice-extract-v2"
    reg.skills["finance/invoice-extract-v2"] = clone
    dupes = reg.duplicates()
    assert any(
        {a, b} == {"finance/invoice-extract", "finance/invoice-extract-v2"}
        for (a, b, _tag) in dupes
    )


def test_certify_blocks_duplicate_tag_against_published_skill():
    reg = lite.Registry.from_dir(EXAMPLES)
    clone = copy.deepcopy(reg.skills["finance/invoice-extract"])
    clone["identity"]["id"] = "finance/invoice-extract-v2"
    clone["lifecycle"] = {"stage": "draft"}
    reg.skills["finance/invoice-extract-v2"] = clone
    with pytest.raises(lite.ManifestError, match="duplicate capability"):
        reg.certify("finance/invoice-extract-v2", approver="reviewer")


def test_certify_requires_approver():
    reg = lite.Registry.from_dir(EXAMPLES)
    with pytest.raises(lite.ManifestError):
        reg.certify("finance/invoice-extract", approver="")


def test_index_shape_is_stage2_catalog():
    reg = lite.Registry.from_dir(EXAMPLES)
    idx = reg.index()
    assert idx["schemaVersion"] == "skills.dev/v1"
    assert idx["generatedAt"].endswith("Z")
    ids = [s["id"] for s in idx["skills"]]
    assert ids == sorted(ids)
    assert "invoice.extract" in idx["capabilityIndex"]
    assert idx["capabilityIndex"]["invoice.extract"] == ["finance/invoice-extract"]
    # Every published-skill entry carries the MCP binding agents need to call it.
    extract = next(s for s in idx["skills"] if s["id"] == "finance/invoice-extract")
    assert "toolName" in extract["mcp"]


def test_index_embeds_full_manifests_by_default():
    """The Stage 2 catalog needs full manifests so the MCP server's remote
    backend can answer describe_skill without falling back to GitHub."""
    reg = lite.Registry.from_dir(EXAMPLES)
    idx = reg.index()
    assert "manifests" in idx
    assert "finance/invoice-extract" in idx["manifests"]
    full = idx["manifests"]["finance/invoice-extract"]
    assert full["identity"]["id"] == "finance/invoice-extract"
    assert "governance" in full
    assert "scoring" in full


def test_index_without_manifests_is_compact():
    reg = lite.Registry.from_dir(EXAMPLES)
    idx = reg.index(include_manifests=False)
    assert "manifests" not in idx
    assert "skills" in idx  # summaries still present


def test_from_catalog_round_trips():
    """index() + from_catalog() must produce a registry that answers the same
    discovery queries as the original. This is what makes remote mode work."""
    original = lite.Registry.from_dir(EXAMPLES)
    catalog = original.index()
    rebuilt = lite.Registry.from_catalog(catalog)
    assert set(rebuilt.skills) == set(original.skills)
    # Same find_by_capability results.
    a = [m["identity"]["id"] for m in original.find_by_capability("invoice.extract")]
    b = [m["identity"]["id"] for m in rebuilt.find_by_capability("invoice.extract")]
    assert a == b


def test_from_catalog_rejects_summary_only_payload():
    reg = lite.Registry.from_dir(EXAMPLES)
    compact = reg.index(include_manifests=False)
    with pytest.raises(lite.ManifestError, match="manifests"):
        lite.Registry.from_catalog(compact)
