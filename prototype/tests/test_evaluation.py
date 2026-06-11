"""Tests for the Phase 2 evaluation harness (the falsifiable-bet scorecard)."""

from __future__ import annotations

import copy
import json
import os

import pytest

from chassis.evaluation import (
    EvaluationReport,
    agent_maintenance_effort,
    duplicate_precision_recall,
    evaluate,
    flagged_pairs,
    load_baseline,
    load_labels,
    ontology_drift,
    proposal_acceptance,
)
from chassis.manifest import load_manifest
from chassis.ontology import OntologyBuilderAgent

EVAL_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "examples",
    "evaluation",
)


def _eval_corpus():
    files = sorted(f for f in os.listdir(EVAL_DIR) if f.endswith(".manifest.json"))
    return [load_manifest(os.path.join(EVAL_DIR, f)) for f in files]


def test_duplicate_precision_recall_basic():
    truth = {frozenset({"a", "b"}), frozenset({"c", "d"})}
    pred = {frozenset({"a", "b"}), frozenset({"e", "f"})}
    precision, recall, tp, fp, fn = duplicate_precision_recall(pred, truth)
    assert (tp, fp, fn) == (1, 1, 1)
    assert precision == 0.5
    assert recall == 0.5


def test_duplicate_precision_recall_empty_is_perfect():
    # No flags and no truth must not be scored as a failure.
    precision, recall, tp, fp, fn = duplicate_precision_recall(set(), set())
    assert precision == 1.0 and recall == 1.0
    assert (tp, fp, fn) == (0, 0, 0)


def test_proposal_acceptance_bounds(invoice_extract):
    result = OntologyBuilderAgent().sync_meaning([invoice_extract])
    rate = proposal_acceptance(result)
    assert 0.0 <= rate <= 1.0
    # Clean, non-restricted skill -> nothing withheld -> full acceptance.
    assert rate == 1.0


def test_maintenance_effort_scales_to_100():
    class _R:
        review_queue = [object()] * 3

    # 3 reviews * 2 min over 6 skills -> 1 min/skill -> 100 min/100 skills.
    assert agent_maintenance_effort(_R(), skills=6, minutes_per_review=2.0) == 100.0
    assert agent_maintenance_effort(_R(), skills=0) == 0.0


def test_ontology_drift_flags_withheld_published(invoice_extract):
    restricted = copy.deepcopy(invoice_extract)
    restricted["governance"]["dataClassification"] = "restricted"
    restricted["lifecycle"]["stage"] = "published"
    result = OntologyBuilderAgent().sync_meaning([restricted])
    # Restricted skill's Skill node is withheld -> stale -> drift 1.0.
    assert ontology_drift([restricted], result) == 1.0


def test_load_baseline_packaged_shape():
    baseline = load_baseline()
    assert baseline["unit"] == "human-minutes-per-100-skills"
    assert float(baseline["value"]) > 0


def test_load_labels_normalises_unordered_pairs():
    pairs = load_labels(os.path.join(EVAL_DIR, "labels.json"))
    assert frozenset({"eval/summarize-fast", "eval/summarize-pro"}) in pairs
    assert len(pairs) == 4


def test_evaluate_labelled_corpus_meets_gate():
    truth = load_labels(os.path.join(EVAL_DIR, "labels.json"))
    report = evaluate(_eval_corpus(), truth_pairs=truth)
    assert isinstance(report, EvaluationReport)
    names = {m.name for m in report.metrics}
    assert names == {
        "proposal_acceptance_rate",
        "duplicate_precision",
        "duplicate_recall",
        "maintenance_effort_ratio",
        "ontology_drift",
    }
    # The heuristic finds 3 of 4 true pairs with no false positives.
    by_name = {m.name: m for m in report.metrics}
    assert by_name["duplicate_precision"].value == 1.0
    assert by_name["duplicate_recall"].value == pytest.approx(0.75)
    assert report.passed


def test_evaluate_to_dict_is_json_serialisable():
    report = evaluate(_eval_corpus(), truth_pairs=load_labels(os.path.join(EVAL_DIR, "labels.json")))
    json.dumps(report.to_dict())  # must not raise


def test_evaluate_without_truth_flags_are_false_positives():
    # With no ground truth, the corpus's real duplicate flags count as FPs,
    # which must drag precision below target (a fail-closed default).
    report = evaluate(_eval_corpus())
    by_name = {m.name: m for m in report.metrics}
    assert by_name["duplicate_precision"].value < 0.9
    assert by_name["duplicate_precision"].passed is False


def test_flagged_pairs_are_unordered():
    clone_a = load_manifest(os.path.join(EVAL_DIR, "summarize-fast.manifest.json"))
    clone_b = load_manifest(os.path.join(EVAL_DIR, "summarize-pro.manifest.json"))
    result = OntologyBuilderAgent().sync_meaning([clone_a, clone_b])
    pairs = flagged_pairs(result)
    assert frozenset({"eval/summarize-fast", "eval/summarize-pro"}) in pairs
