"""Program telemetry - the falsifiable metrics, measured from registry state.

``docs/roadmap.md`` defines the program-level metrics and, crucially, the
*falsifiable bet*: does an agent-maintained ontology beat hand-curation? Those
numbers only mean something if they are computed the same way every time, so the
measurement lives here (next to the chassis) rather than being reconstructed ad
hoc in a dashboard.

The metrics are derived from two inputs the product already produces:

* the registry catalog (manifests + lifecycle stage), and
* an Ontology Builder Agent :class:`~chassis.ontology.SyncResult`.

Nothing here mutates state; it is a pure read over what the pipeline emitted.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional

from .manifest import Manifest, capability_tags
from .ontology import SyncResult
from .registry import Stage


@dataclass
class RegistryMetrics:
    """Breadth / reuse / restraint / trust, computed from the catalog."""

    skills_total: int = 0
    skills_by_stage: Dict[str, int] = field(default_factory=dict)
    published_skills: int = 0
    distinct_capabilities: int = 0
    # Reuse proxy: capabilities offered by more than one published skill.
    reused_capabilities: int = 0
    avg_providers_per_capability: float = 0.0
    # Trust: share of skills carrying complete governance + audit metadata.
    governed_skill_ratio: float = 0.0


@dataclass
class MeaningMetrics:
    """Meaning-layer health, computed from an Ontology Builder Agent run."""

    proposals: int = 0
    auto_merged: int = 0
    review_queued: int = 0
    proposal_acceptance_rate: float = 0.0  # auto-merge share (proxy)
    duplicate_flags: int = 0
    conflict_flags: int = 0


def _is_governed(manifest: Manifest) -> bool:
    gov = manifest.get("governance", {})
    return bool(gov.get("visibility")) and bool(gov.get("audit"))


def registry_metrics(manifests: List[Manifest]) -> RegistryMetrics:
    """Compute breadth/reuse/restraint/trust metrics over a catalog."""
    by_stage: Counter = Counter()
    provider_count: Counter = Counter()
    governed = 0
    published = 0

    for manifest in manifests:
        stage = manifest.get("lifecycle", {}).get("stage", "")
        by_stage[stage] += 1
        if _is_governed(manifest):
            governed += 1
        if stage == Stage.PUBLISHED.value:
            published += 1
            for tag in capability_tags(manifest):
                provider_count[tag] += 1

    distinct = len(provider_count)
    reused = sum(1 for n in provider_count.values() if n > 1)
    total_providers = sum(provider_count.values())
    avg_providers = (total_providers / distinct) if distinct else 0.0
    total = len(manifests)

    return RegistryMetrics(
        skills_total=total,
        skills_by_stage=dict(by_stage),
        published_skills=published,
        distinct_capabilities=distinct,
        reused_capabilities=reused,
        avg_providers_per_capability=round(avg_providers, 4),
        governed_skill_ratio=round(governed / total, 4) if total else 0.0,
    )


def meaning_metrics(result: SyncResult) -> MeaningMetrics:
    """Compute meaning-layer health from a sync result."""
    proposals = len(result.proposals)
    auto = len(result.auto_merge)
    review = len(result.review_queue)
    acceptance = (auto / proposals) if proposals else 0.0
    return MeaningMetrics(
        proposals=proposals,
        auto_merged=auto,
        review_queued=review,
        proposal_acceptance_rate=round(acceptance, 4),
        duplicate_flags=len(result.flags.get("duplicates", [])),
        conflict_flags=len(result.flags.get("conflicts", [])),
    )


def snapshot(
    manifests: List[Manifest], result: Optional[SyncResult] = None
) -> Dict[str, object]:
    """Return a JSON-serialisable telemetry snapshot for emission/scraping."""
    out: Dict[str, object] = {"registry": asdict(registry_metrics(manifests))}
    if result is not None:
        out["meaning"] = asdict(meaning_metrics(result))
    return out


__all__ = [
    "RegistryMetrics",
    "MeaningMetrics",
    "registry_metrics",
    "meaning_metrics",
    "snapshot",
]
