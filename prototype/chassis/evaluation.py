"""Phase 2 evaluation harness - scoring the falsifiable bet.

``docs/roadmap.md`` Phase 2 frames the one unproven claim of the whole construct:
*does an agent-maintained ontology beat hand-curation?* That claim is only
meaningful if it is measured the same way every time and compared against a
recorded Phase 1 baseline. This module turns an Ontology Builder Agent run into
the five gated numbers and scores each against its roadmap target:

==============================  ===========================================  ===========
Metric                          Definition                                   Target
==============================  ===========================================  ===========
proposal_acceptance_rate        share of proposals not held for human review  >= 0.80
duplicate_precision             correct DUPLICATE_OF flags / all flagged      >= 0.90
duplicate_recall                correct DUPLICATE_OF flags / all true dups    >= 0.70
maintenance_effort_ratio        agent minutes-per-100 / hand-curation base    <  0.50
ontology_drift                  published skills still pending in review      <  0.05
==============================  ===========================================  ===========

The agent is the *replaceable keystone* (``chassis.ontology``); this harness is
how a candidate implementation - heuristic, LLM or hybrid - is judged before it
is allowed past the Meaning-sync gate. Nothing here mutates state.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from typing import Dict, FrozenSet, List, Optional, Sequence, Set, Tuple

from .manifest import Manifest, skill_id
from .ontology import OntologyBuilderAgent, SyncResult
from .registry import Stage

# Roadmap Phase 2 exit-gate targets (docs/roadmap.md).
TARGET_ACCEPTANCE = 0.80
TARGET_DUP_PRECISION = 0.90
TARGET_DUP_RECALL = 0.70
TARGET_EFFORT_RATIO = 0.50  # agent effort must be < 50% of the baseline
TARGET_DRIFT = 0.05

# Default cost model for human disposition of a withheld proposal.
DEFAULT_MINUTES_PER_REVIEW = 3.0

_PACKAGED_BASELINE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "phase1-baseline.json"
)

DuplicatePair = FrozenSet[str]


def load_baseline(path: Optional[str] = None) -> Dict[str, object]:
    """Load the recorded Phase 1 hand-curation baseline.

    Resolution order: explicit ``path`` -> ``CHASSIS_BASELINE_PATH`` env var ->
    the copy packaged inside the distribution. Raises ``FileNotFoundError`` if
    none is available so a missing baseline fails loudly rather than silently
    scoring the bet against nothing.
    """
    resolved = path or os.environ.get("CHASSIS_BASELINE_PATH") or _PACKAGED_BASELINE
    with open(resolved, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _norm_pairs(pairs: Sequence[Sequence[str]]) -> Set[DuplicatePair]:
    """Normalise ``[[a, b], ...]`` into a set of unordered ``frozenset`` pairs."""
    out: Set[DuplicatePair] = set()
    for pair in pairs:
        members = [str(p) for p in pair]
        if len(members) != 2:
            raise ValueError(f"duplicate pair must have exactly 2 members: {pair!r}")
        out.add(frozenset(members))
    return out


def load_labels(path: str) -> Set[DuplicatePair]:
    """Load ground-truth duplicate pairs from a labels JSON file."""
    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    return _norm_pairs(data.get("duplicate_pairs", []))


def flagged_pairs(result: SyncResult) -> Set[DuplicatePair]:
    """Return the set of unordered skill pairs the agent flagged as duplicates."""
    return _norm_pairs(result.flags.get("duplicates", []))


@dataclass
class MetricScore:
    """One gated metric: its measured value, target, comparison and verdict."""

    name: str
    value: float
    target: float
    comparison: str  # ">=" or "<"
    passed: bool
    detail: str = ""


@dataclass
class EvaluationReport:
    """The full Phase 2 scorecard for one Ontology Builder Agent run."""

    skills_evaluated: int = 0
    published_skills: int = 0
    metrics: List[MetricScore] = field(default_factory=list)
    baseline: Dict[str, object] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        """True only if every gated metric meets its target."""
        return bool(self.metrics) and all(m.passed for m in self.metrics)

    def to_dict(self) -> Dict[str, object]:
        return {
            "skills_evaluated": self.skills_evaluated,
            "published_skills": self.published_skills,
            "passed": self.passed,
            "baseline": self.baseline,
            "metrics": [asdict(m) for m in self.metrics],
        }


def duplicate_precision_recall(
    predicted: Set[DuplicatePair], truth: Set[DuplicatePair]
) -> Tuple[float, int, int, int]:
    """Return ``(precision, recall, tp, fp, fn)`` for duplicate detection.

    Precision is defined as 1.0 when nothing was flagged (no false positives);
    recall is defined as 1.0 when there are no true duplicates to find. This
    keeps a clean catalog from being scored as a failure.
    """
    tp = len(predicted & truth)
    fp = len(predicted - truth)
    fn = len(truth - predicted)
    precision = tp / (tp + fp) if (tp + fp) else 1.0
    recall = tp / (tp + fn) if (tp + fn) else 1.0
    return precision, recall, tp, fp, fn


def proposal_acceptance(result: SyncResult) -> float:
    """Share of proposals not withheld for human review (acceptance proxy).

    With no human in the loop, auto-merge share is the deterministic stand-in
    for "accepted unchanged": the agent's policy already withholds low-confidence,
    duplicate, conflict and restricted-scope changes.
    """
    total = len(result.proposals)
    if not total:
        return 1.0
    return len(result.auto_merge) / total


def agent_maintenance_effort(
    result: SyncResult,
    skills: int,
    minutes_per_review: float = DEFAULT_MINUTES_PER_REVIEW,
) -> float:
    """Agent-assisted human minutes per 100 skills.

    Only the review queue costs human time; auto-merged proposals are free. The
    figure is normalised to 100 skills so it is directly comparable to the
    recorded hand-curation baseline.
    """
    if skills <= 0:
        return 0.0
    minutes = len(result.review_queue) * minutes_per_review
    return (minutes / skills) * 100.0


def ontology_drift(manifests: Sequence[Manifest], result: SyncResult) -> float:
    """Fraction of published skills whose Skill entity is still pending review.

    A published skill is "in sync" once its ``Skill`` node can be auto-merged
    into the ontology; if the node is held in the review queue the skill's
    meaning is stale until a human acts, which is exactly the drift the roadmap
    measures.
    """
    published = [m for m in manifests if m.get("lifecycle", {}).get("stage") == Stage.PUBLISHED.value]
    if not published:
        return 0.0
    auto_skill_nodes = {
        c.subject for c in result.auto_merge if c.kind == "entity" and c.predicate == "Skill"
    }
    stale = sum(1 for m in published if skill_id(m) not in auto_skill_nodes)
    return stale / len(published)


def evaluate(
    manifests: Sequence[Manifest],
    *,
    truth_pairs: Optional[Set[DuplicatePair]] = None,
    agent: Optional[OntologyBuilderAgent] = None,
    baseline: Optional[Dict[str, object]] = None,
    minutes_per_review: Optional[float] = None,
) -> EvaluationReport:
    """Run ``agent`` over ``manifests`` and score the Phase 2 exit-gate metrics.

    ``truth_pairs`` is the human-labelled ground truth for duplicate detection;
    when omitted the duplicate metrics are scored against an empty truth set
    (any flag is then a false positive). ``baseline`` defaults to the recorded
    Phase 1 baseline; ``minutes_per_review`` defaults to the baseline's recorded
    review-action cost.
    """
    agent = agent or OntologyBuilderAgent()
    baseline = baseline if baseline is not None else load_baseline()
    truth_pairs = truth_pairs or set()

    result = agent.sync_meaning(list(manifests))

    if minutes_per_review is None:
        minutes_per_review = float(
            baseline.get("minutes_per_review_action", DEFAULT_MINUTES_PER_REVIEW)
        )

    skills = len(manifests)
    published = sum(
        1 for m in manifests if m.get("lifecycle", {}).get("stage") == Stage.PUBLISHED.value
    )

    acceptance = proposal_acceptance(result)
    precision, recall, tp, fp, fn = duplicate_precision_recall(
        flagged_pairs(result), truth_pairs
    )
    effort = agent_maintenance_effort(result, skills, minutes_per_review)
    baseline_value = float(baseline.get("value", 0.0))
    effort_ratio = (effort / baseline_value) if baseline_value else 0.0
    drift = ontology_drift(manifests, result)

    metrics = [
        MetricScore(
            "proposal_acceptance_rate", round(acceptance, 4), TARGET_ACCEPTANCE, ">=",
            acceptance >= TARGET_ACCEPTANCE,
            f"{len(result.auto_merge)}/{len(result.proposals)} proposals auto-merged",
        ),
        MetricScore(
            "duplicate_precision", round(precision, 4), TARGET_DUP_PRECISION, ">=",
            precision >= TARGET_DUP_PRECISION,
            f"tp={tp} fp={fp} fn={fn}",
        ),
        MetricScore(
            "duplicate_recall", round(recall, 4), TARGET_DUP_RECALL, ">=",
            recall >= TARGET_DUP_RECALL,
            f"tp={tp} fp={fp} fn={fn}",
        ),
        MetricScore(
            "maintenance_effort_ratio", round(effort_ratio, 4), TARGET_EFFORT_RATIO, "<",
            effort_ratio < TARGET_EFFORT_RATIO,
            f"{round(effort, 2)} vs baseline {baseline_value} min/100 skills",
        ),
        MetricScore(
            "ontology_drift", round(drift, 4), TARGET_DRIFT, "<",
            drift < TARGET_DRIFT,
            f"{round(drift * published)} of {published} published skills pending",
        ),
    ]

    return EvaluationReport(
        skills_evaluated=skills,
        published_skills=published,
        metrics=metrics,
        baseline=dict(baseline),
    )


__all__ = [
    "MetricScore",
    "EvaluationReport",
    "evaluate",
    "load_baseline",
    "load_labels",
    "flagged_pairs",
    "duplicate_precision_recall",
    "proposal_acceptance",
    "agent_maintenance_effort",
    "ontology_drift",
    "TARGET_ACCEPTANCE",
    "TARGET_DUP_PRECISION",
    "TARGET_DUP_RECALL",
    "TARGET_EFFORT_RATIO",
    "TARGET_DRIFT",
]
