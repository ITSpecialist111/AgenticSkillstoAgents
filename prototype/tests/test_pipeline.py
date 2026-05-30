"""Smoke tests for Part B: the six-gate pipeline state machine."""

from __future__ import annotations

import pytest

from chassis.registry import GateError, Registry, Stage


def test_register_validates_and_sets_registered(invoice_extract, as_draft):
    reg = Registry()
    m = reg.register(as_draft(invoice_extract))
    assert m["lifecycle"]["stage"] == Stage.REGISTERED.value


def test_full_happy_path_to_published(invoice_extract, as_draft):
    reg = Registry()
    sid = invoice_extract["identity"]["id"]
    reg.register(as_draft(invoice_extract))
    certified = reg.certify(sid, approver="coe.reviewer")
    assert certified["lifecycle"]["stage"] == Stage.CERTIFIED.value
    assert certified["lifecycle"]["certifiedBy"] == "coe.reviewer"
    assert certified["lifecycle"]["certifiedAt"]
    published = reg.publish(sid)
    assert published["lifecycle"]["stage"] == Stage.PUBLISHED.value


def test_certify_requires_human_approver(invoice_extract, as_draft):
    reg = Registry()
    sid = invoice_extract["identity"]["id"]
    reg.register(as_draft(invoice_extract))
    with pytest.raises(GateError):
        reg.certify(sid, approver="")


def test_cannot_publish_before_certify(invoice_extract, as_draft):
    reg = Registry()
    sid = invoice_extract["identity"]["id"]
    reg.register(as_draft(invoice_extract))
    with pytest.raises(GateError):
        reg.publish(sid)


def test_duplicate_capability_scan_blocks_certify(invoice_extract, as_draft):
    reg = Registry()
    # Publish the original.
    sid = invoice_extract["identity"]["id"]
    reg.register(as_draft(invoice_extract))
    reg.certify(sid, approver="coe.reviewer")
    reg.publish(sid)

    # A near-copy with the same capability tag but a different id.
    clone = as_draft(invoice_extract)
    clone["identity"]["id"] = "finance/invoice-extract-2"
    reg.register(clone)
    with pytest.raises(GateError, match="duplicate-capability"):
        reg.certify("finance/invoice-extract-2", approver="coe.reviewer")


def test_unresolved_dependency_blocks_certify(po_match, as_draft):
    reg = Registry()
    sid = po_match["identity"]["id"]
    reg.register(as_draft(po_match))
    # invoice.extract capability has not been registered yet -> unresolved.
    with pytest.raises(GateError, match="unresolved dependency"):
        reg.certify(sid, approver="coe.reviewer")


def test_dependency_resolves_once_provider_registered(
    invoice_extract, po_match, as_draft
):
    reg = Registry()
    reg.register(as_draft(invoice_extract))  # provides invoice.extract
    reg.register(as_draft(po_match))
    certified = reg.certify(po_match["identity"]["id"], approver="coe.reviewer")
    assert certified["lifecycle"]["stage"] == Stage.CERTIFIED.value


def test_retire_path(invoice_extract, as_draft):
    reg = Registry()
    sid = invoice_extract["identity"]["id"]
    reg.register(as_draft(invoice_extract))
    reg.certify(sid, approver="coe.reviewer")
    reg.publish(sid)
    reg.deprecate(sid, superseded_by="finance/invoice-extract@2.0.0")
    assert reg.get(sid)["lifecycle"]["supersededBy"] == "finance/invoice-extract@2.0.0"
    retired = reg.retire(sid)
    assert retired["lifecycle"]["stage"] == Stage.RETIRED.value


def test_find_by_capability_and_lineage(invoice_extract, as_draft):
    reg = Registry()
    sid = invoice_extract["identity"]["id"]
    reg.register(as_draft(invoice_extract))
    reg.certify(sid, approver="coe.reviewer")
    reg.publish(sid)
    hits = reg.find_by_capability("invoice.extract")
    assert [h["identity"]["id"] for h in hits] == [sid]
    assert reg.lineage(sid)["id"] == sid


def test_double_register_rejected(invoice_extract, as_draft):
    reg = Registry()
    reg.register(as_draft(invoice_extract))
    with pytest.raises(GateError):
        reg.register(as_draft(invoice_extract))
