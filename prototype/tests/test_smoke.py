"""End-to-end smoke test: the worked six-gate graduation walkthrough.

Mirrors docs/graduation-walkthrough.md - one skill travels all gates and a
second composes onto it, then the Ontology Builder Agent syncs meaning.
"""

from __future__ import annotations

from chassis.cli import main as cli_main
from chassis.ontology import DEPENDS_ON, OntologyBuilderAgent
from chassis.registry import Registry, Stage


def test_worked_walkthrough(invoice_extract, po_match, ap_intake, as_draft):
    reg = Registry()

    # Gate 1-3 for invoice-extract: register -> certify -> publish.
    ie_id = invoice_extract["identity"]["id"]
    reg.register(as_draft(invoice_extract))
    reg.certify(ie_id, approver="coe.reviewer")
    reg.publish(ie_id)
    assert reg.get(ie_id)["lifecycle"]["stage"] == Stage.PUBLISHED.value

    # po-match graduates and composes onto invoice.extract.
    pm_id = po_match["identity"]["id"]
    reg.register(as_draft(po_match))
    reg.certify(pm_id, approver="coe.reviewer")
    reg.publish(pm_id)

    # ap-intake registers (composite, still draft -> registered).
    ai_id = ap_intake["identity"]["id"]
    reg.register(as_draft(ap_intake))
    assert reg.get(ai_id)["lifecycle"]["stage"] == Stage.REGISTERED.value

    # Gate 4 - Meaning-sync across the published catalog.
    agent = OntologyBuilderAgent()
    result = agent.sync_meaning(reg.all())

    rels = {(c.subject, c.predicate, c.obj) for c in result.proposals if c.kind == "relationship"}
    # Composition path: ap-intake depends on invoice.extract.
    assert (ai_id, DEPENDS_ON, "invoice.extract") in rels
    # Clean catalog: no duplicate capability sprawl.
    assert result.flags["duplicates"] == []


def test_cli_validate_and_walkthrough(capsys):
    import os

    examples = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "examples",
    )
    rc = cli_main(["validate", os.path.join(examples, "invoice-extract.manifest.json")])
    assert rc == 0
    assert "valid" in capsys.readouterr().out

    rc = cli_main(["walkthrough"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "six gates" in out
    assert "Ontology Builder Agent proposals" in out
