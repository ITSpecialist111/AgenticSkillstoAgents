"""Smoke tests for Part C: the Ontology Builder Agent contract."""

from __future__ import annotations

import copy

from chassis.ontology import (
    DUPLICATE_OF,
    PRODUCES,
    PROVIDES,
    Ontology,
    OntologyBuilderAgent,
)


def test_sync_returns_contract_shape(invoice_extract):
    agent = OntologyBuilderAgent()
    result = agent.sync_meaning([invoice_extract])
    assert len(result.proposals) == len(result.confidence)
    assert set(result.flags) == {"duplicates", "conflicts"}
    assert all(0.0 <= c <= 1.0 for c in result.confidence)


def test_proposes_skill_capability_and_io_edges(invoice_extract):
    agent = OntologyBuilderAgent()
    result = agent.sync_meaning([invoice_extract])
    sid = invoice_extract["identity"]["id"]
    rels = {(c.subject, c.predicate, c.obj) for c in result.proposals if c.kind == "relationship"}
    ents = {(c.predicate, c.subject) for c in result.proposals if c.kind == "entity"}
    assert ("Skill", sid) in ents
    assert ("Capability", "invoice.extract") in ents
    assert (sid, PROVIDES, "invoice.extract") in rels
    assert (sid, PRODUCES, "InvoiceFields") in rels


def test_high_confidence_low_risk_automerges(invoice_extract):
    agent = OntologyBuilderAgent()
    result = agent.sync_meaning([invoice_extract])
    # Nothing flagged for this clean, non-restricted skill.
    assert result.review_queue == []
    assert result.auto_merge


def test_duplicate_detection_flags_and_holds_for_review(invoice_extract):
    clone = copy.deepcopy(invoice_extract)
    clone["identity"]["id"] = "finance/invoice-extract-clone"
    agent = OntologyBuilderAgent()
    result = agent.sync_meaning([invoice_extract, clone])
    assert result.flags["duplicates"], "expected a duplicate pair"
    dup_changes = [c for c in result.proposals if c.predicate == DUPLICATE_OF]
    assert dup_changes
    # DUPLICATE_OF is always withheld for human review.
    for c in dup_changes:
        assert c in result.review_queue


def test_no_duplicate_when_io_differs(invoice_extract, po_match):
    agent = OntologyBuilderAgent()
    result = agent.sync_meaning([invoice_extract, po_match])
    assert result.flags["duplicates"] == []


def test_determinism_risk_conflict_flagged(invoice_extract):
    a = copy.deepcopy(invoice_extract)
    b = copy.deepcopy(invoice_extract)
    b["identity"]["id"] = "finance/invoice-extract-b"
    # Same capability tag, different risk -> conflict.
    b["scoring"]["risk"] = "high"
    # Make IO differ so it is a conflict but not flagged as a duplicate.
    b["capability"]["outputs"][0]["type"] = "InvoiceFieldsV2"
    agent = OntologyBuilderAgent()
    result = agent.sync_meaning([a, b])
    conflicts = result.flags["conflicts"]
    assert any(c["capability"] == "invoice.extract" for c in conflicts)


def test_restricted_data_routes_to_review(invoice_extract):
    invoice_extract["governance"]["dataClassification"] = "restricted"
    agent = OntologyBuilderAgent()
    result = agent.sync_meaning([invoice_extract])
    assert result.review_queue, "restricted-scope changes must be reviewed"


def test_existing_ontology_nodes_not_reproposed(invoice_extract):
    agent = OntologyBuilderAgent()
    ontology = Ontology()
    first = agent.sync_meaning([invoice_extract], ontology)
    for change in first.auto_merge:
        ontology.apply(change)
    # Second sync against the now-populated ontology should propose nothing new.
    second = agent.sync_meaning([invoice_extract], ontology)
    assert second.proposals == []
