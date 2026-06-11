"""Tests for capability matchmaking (the Reasoning Layer read surface)."""

from __future__ import annotations

from chassis.matchmaking import MatchGrade, Need, best_match, match


def _publish(reg, manifest, as_draft, approver="coe.reviewer"):
    reg.register(as_draft(manifest))
    sid = manifest["identity"]["id"]
    reg.certify(sid, approver=approver)
    return reg.publish(sid)


def test_exact_match_on_full_io(invoice_extract, as_draft):
    from chassis.registry import Registry

    reg = Registry()
    _publish(reg, invoice_extract, as_draft)
    published = reg.find_by_capability("invoice.extract")
    need = Need(tag="invoice.extract", inputs={"InvoiceDocument"}, outputs={"InvoiceFields"})
    m = best_match(published, need)
    assert m.grade is MatchGrade.EXACT
    assert m.skill_id == "finance/invoice-extract"


def test_partial_when_io_unspecified(invoice_extract, as_draft):
    from chassis.registry import Registry

    reg = Registry()
    _publish(reg, invoice_extract, as_draft)
    published = reg.find_by_capability("invoice.extract")
    m = best_match(published, Need(tag="invoice.extract"))
    assert m.grade is MatchGrade.PARTIAL


def test_fail_when_no_provider(invoice_extract, as_draft):
    from chassis.registry import Registry

    reg = Registry()
    _publish(reg, invoice_extract, as_draft)
    published = reg.find_by_capability("nonexistent.tag")
    assert match(published, Need(tag="nonexistent.tag")) == []
    assert best_match(published, Need(tag="nonexistent.tag")).grade is MatchGrade.FAIL


def test_plug_in_when_outputs_satisfied_but_extra(invoice_extract, as_draft):
    from chassis.registry import Registry

    reg = Registry()
    _publish(reg, invoice_extract, as_draft)
    published = reg.find_by_capability("invoice.extract")
    # Agent can supply more inputs than the skill needs; only needs the output.
    need = Need(tag="invoice.extract", inputs={"InvoiceDocument", "Extra"}, outputs={"InvoiceFields"})
    assert best_match(published, need).grade is MatchGrade.PLUG_IN


def test_cost_orders_equal_grades():
    cheap = {
        "identity": {"id": "x/cheap"},
        "capability": {"capabilityTags": ["t"], "inputs": [], "outputs": []},
        "scoring": {"determinism": "high", "risk": "low"},
        "governance": {"cost": {"estimate": 1.0}},
    }
    pricey = {
        "identity": {"id": "x/pricey"},
        "capability": {"capabilityTags": ["t"], "inputs": [], "outputs": []},
        "scoring": {"determinism": "high", "risk": "low"},
        "governance": {"cost": {"estimate": 9.0}},
    }
    ranked = match([pricey, cheap], Need(tag="t"))
    assert [m.skill_id for m in ranked] == ["x/cheap", "x/pricey"]
