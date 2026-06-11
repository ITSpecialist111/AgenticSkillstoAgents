"""Tests for program telemetry / metrics."""

from __future__ import annotations

from chassis.metrics import meaning_metrics, registry_metrics, snapshot
from chassis.ontology import OntologyBuilderAgent
from chassis.registry import Registry


def _graduate(reg, manifest, as_draft):
    reg.register(as_draft(manifest))
    sid = manifest["identity"]["id"]
    reg.certify(sid, approver="coe.reviewer")
    reg.publish(sid)


def test_registry_metrics_counts(invoice_extract, po_match, ap_intake, as_draft):
    reg = Registry()
    _graduate(reg, invoice_extract, as_draft)
    _graduate(reg, po_match, as_draft)
    reg.register(as_draft(ap_intake))  # stays registered

    rm = registry_metrics(reg.all())
    assert rm.skills_total == 3
    assert rm.published_skills == 2
    assert rm.skills_by_stage.get("published") == 2
    assert rm.skills_by_stage.get("registered") == 1
    assert rm.distinct_capabilities >= 2
    # Examples all carry governance.visibility + audit.
    assert rm.governed_skill_ratio == 1.0


def test_meaning_metrics_from_sync(invoice_extract, po_match, as_draft):
    reg = Registry()
    _graduate(reg, invoice_extract, as_draft)
    _graduate(reg, po_match, as_draft)
    result = OntologyBuilderAgent().sync_meaning(reg.all())
    mm = meaning_metrics(result)
    assert mm.proposals == mm.auto_merged + mm.review_queued
    assert 0.0 <= mm.proposal_acceptance_rate <= 1.0


def test_snapshot_is_json_serialisable(invoice_extract, as_draft):
    import json

    reg = Registry()
    _graduate(reg, invoice_extract, as_draft)
    result = OntologyBuilderAgent().sync_meaning(reg.all())
    snap = snapshot(reg.all(), result)
    json.dumps(snap)  # must not raise
    assert "registry" in snap and "meaning" in snap
