"""Part C - the Ontology Builder Agent (the replaceable keystone).

Implements the measurable contract from ``docs/ontology-builder-agent.md``::

    sync_meaning(manifests, ontology) -> {
        proposals:   GraphChange[]   # entities + relationships to add
        confidence:  float[]         # per-proposal 0..1
        flags:       {duplicates, conflicts}
        review_queue: GraphChange[]  # changes withheld for human approval
    }

This reference implementation is a deterministic *heuristic* matcher. Because the
chassis depends on the contract and not the implementation, this agent can be
swapped for an LLM/hybrid without disturbing Parts A and B.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from .manifest import Manifest, capability_tags, iope_signature, skill_id

# Confidence below which any proposal is routed to human review.
CONFIDENCE_THRESHOLD = 0.75

# Relationship verbs (see docs/ontology-builder-agent.md step 3).
PROVIDES = "PROVIDES"
CONSUMES = "CONSUMES"
PRODUCES = "PRODUCES"
REQUIRES = "REQUIRES"
CAUSES = "CAUSES"
DEPENDS_ON = "DEPENDS_ON"
SUPERSEDES = "SUPERSEDES"
DUPLICATE_OF = "DUPLICATE_OF"


@dataclass(frozen=True)
class GraphChange:
    """A single proposed graph mutation (entity or relationship add)."""

    kind: str  # "entity" | "relationship"
    # For entities: (type, key). For relationships: subject node key.
    subject: str
    # entity type for entities; relationship verb for relationships
    predicate: str
    obj: Optional[str] = None  # relationship object node key
    reason: str = ""

    def key(self) -> Tuple[str, str, str, Optional[str]]:
        return (self.kind, self.subject, self.predicate, self.obj)


@dataclass
class Ontology:
    """A tiny in-memory knowledge graph: typed nodes + verb-labelled edges."""

    nodes: Set[Tuple[str, str]] = field(default_factory=set)  # (type, key)
    edges: Set[Tuple[str, str, str]] = field(default_factory=set)  # (subj, verb, obj)

    def has_node(self, node_type: str, key: str) -> bool:
        return (node_type, key) in self.nodes

    def has_edge(self, subject: str, verb: str, obj: str) -> bool:
        return (subject, verb, obj) in self.edges

    def apply(self, change: GraphChange) -> None:
        """Merge a single :class:`GraphChange` into the graph."""
        if change.kind == "entity":
            self.nodes.add((change.predicate, change.subject))
        elif change.kind == "relationship":
            self.edges.add((change.subject, change.predicate, change.obj))
        else:  # pragma: no cover - guarded by construction
            raise ValueError(f"unknown change kind: {change.kind}")

    def skill_keys(self) -> Set[str]:
        return {key for (ntype, key) in self.nodes if ntype == "Skill"}


@dataclass
class SyncResult:
    """The agent's output bundle for one sync run."""

    proposals: List[GraphChange]
    confidence: List[float]
    flags: Dict[str, list]
    review_queue: List[GraphChange]

    @property
    def auto_merge(self) -> List[GraphChange]:
        """Proposals safe to auto-merge (everything not in the review queue)."""
        held = {c.key() for c in self.review_queue}
        return [c for c in self.proposals if c.key() not in held]


class OntologyBuilderAgent:
    """Heuristic implementation of the Ontology Builder Agent contract."""

    def __init__(self, confidence_threshold: float = CONFIDENCE_THRESHOLD) -> None:
        self.confidence_threshold = confidence_threshold

    def sync_meaning(
        self, manifests: List[Manifest], ontology: Optional[Ontology] = None
    ) -> SyncResult:
        """Propose graph updates for ``manifests`` against ``ontology``."""
        ontology = ontology or Ontology()

        proposals: List[GraphChange] = []
        confidence: List[float] = []
        review: List[GraphChange] = []
        seen: Set[Tuple[str, str, str, Optional[str]]] = set()

        # Context for duplicate/conflict detection across both new + known skills.
        sig_index: Dict[Tuple, List[Tuple[str, Set[str]]]] = {}
        tag_scoring: Dict[str, List[Tuple[str, str, str]]] = {}

        def add(change: GraphChange, conf: float, force_review: bool = False) -> None:
            if change.key() in seen:
                return
            # Skip entities/edges already present in the ontology.
            if change.kind == "entity" and ontology.has_node(change.predicate, change.subject):
                return
            if change.kind == "relationship" and ontology.has_edge(
                change.subject, change.predicate, change.obj
            ):
                return
            seen.add(change.key())
            proposals.append(change)
            confidence.append(conf)
            if force_review or conf < self.confidence_threshold:
                review.append(change)

        for manifest in manifests:
            sid = skill_id(manifest)
            restricted = (
                manifest.get("governance", {}).get("dataClassification") == "restricted"
            )
            scoring = manifest.get("scoring", {})

            # 1-3: entities + relationships from the manifest.
            add(GraphChange("entity", sid, "Skill", reason="skill identity"), 0.99, restricted)

            for tag in capability_tags(manifest):
                add(GraphChange("entity", tag, "Capability", reason="capabilityTag"), 0.95, restricted)
                add(GraphChange("relationship", sid, PROVIDES, tag, "provides capability"), 0.95, restricted)
                tag_scoring.setdefault(tag, []).append(
                    (sid, scoring.get("determinism", ""), scoring.get("risk", ""))
                )

            capability = manifest.get("capability", {})
            for inp in capability.get("inputs", []):
                add(GraphChange("entity", inp["type"], "DataType", reason="input type"), 0.9, restricted)
                add(GraphChange("relationship", sid, CONSUMES, inp["type"], "consumes input"), 0.9, restricted)
            for out in capability.get("outputs", []):
                add(GraphChange("entity", out["type"], "DataType", reason="output type"), 0.9, restricted)
                add(GraphChange("relationship", sid, PRODUCES, out["type"], "produces output"), 0.9, restricted)
            for cond in capability.get("preconditions", []):
                add(GraphChange("entity", cond, "Condition", reason="precondition"), 0.85, restricted)
                add(GraphChange("relationship", sid, REQUIRES, cond, "requires precondition"), 0.85, restricted)
            for eff in capability.get("effects", []):
                add(GraphChange("entity", eff, "Condition", reason="effect"), 0.85, restricted)
                add(GraphChange("relationship", sid, CAUSES, eff, "causes effect"), 0.85, restricted)

            for dep in manifest.get("dependencies", []):
                add(GraphChange("relationship", sid, DEPENDS_ON, dep["ref"], "declared dependency"), 0.9, restricted)

            lifecycle = manifest.get("lifecycle", {})
            if lifecycle.get("supersedes"):
                add(GraphChange("relationship", sid, SUPERSEDES, lifecycle["supersedes"], "lineage"), 0.95, restricted)

            # Index for duplicate detection (IOPE signature + overlapping tags).
            sig = iope_signature(manifest)
            sig_index.setdefault(sig, []).append((sid, set(capability_tags(manifest))))

        # 5: duplicate detection - same IOPE signature AND overlapping tags.
        duplicates: List[Tuple[str, str]] = []
        for entries in sig_index.values():
            for i in range(len(entries)):
                for j in range(i + 1, len(entries)):
                    sid_a, tags_a = entries[i]
                    sid_b, tags_b = entries[j]
                    if tags_a & tags_b:
                        duplicates.append((sid_a, sid_b))
                        # DUPLICATE_OF proposals are ALWAYS held for human review.
                        add(
                            GraphChange("relationship", sid_a, DUPLICATE_OF, sid_b, "same IOPE signature + overlapping tags"),
                            0.6,
                            force_review=True,
                        )

        # 4: determinism/risk conflicts among providers of the same capability.
        conflicts: List[Dict[str, object]] = []
        for tag, providers in tag_scoring.items():
            determinisms = {d for (_, d, _) in providers if d}
            risks = {r for (_, _, r) in providers if r}
            if len(providers) > 1 and (len(determinisms) > 1 or len(risks) > 1):
                conflicts.append(
                    {
                        "capability": tag,
                        "providers": [sid for (sid, _, _) in providers],
                        "determinism": sorted(determinisms),
                        "risk": sorted(risks),
                    }
                )

        flags = {"duplicates": duplicates, "conflicts": conflicts}
        return SyncResult(proposals, confidence, flags, review)
