"""Capability matchmaking - the Reasoning Layer read surface.

The Composition Layer (a few org agents) does not bind to individual skills; it
asks *"which published skill answers this need?"* and binds to a **capability**.
This module turns that question into a ranked, typed answer using the same IOPE
signature the Ontology Builder Agent uses for duplicate detection, so the two
stay consistent.

Match grades (per ``docs/architecture.md`` / ``docs/ontology-schema.md``):

* ``exact``   - provides the tag *and* its IOPE inputs/outputs satisfy the need.
* ``plug-in`` - provides the tag; IOPE compatible but not identical (extra I/O).
* ``partial`` - provides the tag only (I/O could not be confirmed compatible).
* ``fail``    - no published skill provides the tag.

Cost-aware ordering: among equally-graded matches the lower-cost, higher-
determinism skill ranks first, so agents prefer the cheapest reliable option.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional, Set

from .manifest import Manifest, capability_tags, skill_id

_DETERMINISM_RANK = {"high": 0, "medium": 1, "low": 2}
_RISK_RANK = {"low": 0, "medium": 1, "high": 2}


class MatchGrade(str, Enum):
    EXACT = "exact"
    PLUG_IN = "plug-in"
    PARTIAL = "partial"
    FAIL = "fail"


@dataclass(frozen=True)
class Need:
    """What a composing agent is looking for."""

    tag: str
    inputs: Set[str] = frozenset()  # logical input types the agent can supply
    outputs: Set[str] = frozenset()  # logical output types the agent needs back


@dataclass(frozen=True)
class Match:
    """A single graded candidate for a :class:`Need`."""

    skill_id: str
    grade: MatchGrade
    determinism: str
    risk: str
    cost: Optional[float]

    def as_dict(self) -> Dict[str, object]:
        return {
            "skillId": self.skill_id,
            "grade": self.grade.value,
            "determinism": self.determinism,
            "risk": self.risk,
            "cost": self.cost,
        }


def _io_types(manifest: Manifest, side: str) -> Set[str]:
    cap = manifest.get("capability", {})
    return {p["type"] for p in cap.get(side, [])}


def _unit_cost(manifest: Manifest) -> Optional[float]:
    cost = manifest.get("governance", {}).get("cost")
    if isinstance(cost, dict):
        value = cost.get("perCallUsd", cost.get("estimate"))
        if isinstance(value, (int, float)):
            return float(value)
    if isinstance(cost, (int, float)):
        return float(cost)
    return None


def _grade(manifest: Manifest, need: Need) -> MatchGrade:
    if need.tag not in capability_tags(manifest):
        return MatchGrade.FAIL
    if not need.inputs and not need.outputs:
        return MatchGrade.PARTIAL
    provided_in = _io_types(manifest, "inputs")
    provided_out = _io_types(manifest, "outputs")
    # The need's required outputs must be produced, and the skill must not demand
    # inputs the agent cannot supply.
    outputs_ok = need.outputs.issubset(provided_out) if need.outputs else True
    inputs_ok = provided_in.issubset(need.inputs) if provided_in else True
    if not outputs_ok:
        return MatchGrade.PARTIAL
    if inputs_ok and provided_in == need.inputs and provided_out == need.outputs:
        return MatchGrade.EXACT
    if inputs_ok:
        return MatchGrade.PLUG_IN
    return MatchGrade.PARTIAL


_GRADE_RANK = {
    MatchGrade.EXACT: 0,
    MatchGrade.PLUG_IN: 1,
    MatchGrade.PARTIAL: 2,
    MatchGrade.FAIL: 3,
}


def match(published: List[Manifest], need: Need) -> List[Match]:
    """Return graded, cost-ordered matches for ``need`` over ``published``.

    Only the manifests passed in are considered; callers supply the *published*
    catalog (e.g. ``registry.find_by_capability`` or a stage filter) so this
    function stays a pure ranking step with no registry coupling.
    """
    matches: List[Match] = []
    for manifest in published:
        grade = _grade(manifest, need)
        if grade is MatchGrade.FAIL:
            continue
        scoring = manifest.get("scoring", {})
        matches.append(
            Match(
                skill_id=skill_id(manifest),
                grade=grade,
                determinism=scoring.get("determinism", ""),
                risk=scoring.get("risk", ""),
                cost=_unit_cost(manifest),
            )
        )

    def sort_key(m: Match):
        return (
            _GRADE_RANK[m.grade],
            m.cost if m.cost is not None else float("inf"),
            _DETERMINISM_RANK.get(m.determinism, 3),
            _RISK_RANK.get(m.risk, 3),
            m.skill_id,
        )

    return sorted(matches, key=sort_key)


def best_match(published: List[Manifest], need: Need) -> Match:
    """Return the single best match, or a synthetic ``fail`` match if none."""
    ranked = match(published, need)
    if ranked:
        return ranked[0]
    return Match(skill_id="", grade=MatchGrade.FAIL, determinism="", risk="", cost=None)


__all__ = ["MatchGrade", "Need", "Match", "match", "best_match"]
