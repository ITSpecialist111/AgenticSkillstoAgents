# Chassis prototype

An executable, dependency-light reference implementation of the graduation
**chassis** described in this repo's docs. It exists to make the specification
*runnable and testable* — it is a heuristic, in-memory reference, not a
production registry.

It maps 1:1 onto the three parts of the construct:

| Part | Spec | Module |
|---|---|---|
| **A — Manifest** | [`schemas/skill-manifest.schema.json`](../schemas/skill-manifest.schema.json), [`docs/technical-spec.md`](../docs/technical-spec.md) | [`chassis/manifest.py`](chassis/manifest.py) — load + JSON-Schema validation + IOPE signature |
| **B — Pipeline** | [`docs/architecture.md`](../docs/architecture.md) (six gates) | [`chassis/registry.py`](chassis/registry.py) — registry + state machine with gate exit checks |
| **C — Ontology Builder Agent** | [`docs/ontology-builder-agent.md`](../docs/ontology-builder-agent.md) | [`chassis/ontology.py`](chassis/ontology.py) — `sync_meaning(manifests, ontology)` |

## Install

```bash
cd prototype
pip install -r requirements.txt
```

## Run the CLI

```bash
# Validate manifests against the canonical schema (Register gate)
python -m chassis.cli validate ../examples/*.manifest.json

# Graduate the bundled example skills through all six gates + meaning-sync
python -m chassis.cli walkthrough
```

## Run the smoke tests

```bash
cd prototype
python -m pytest -q
```

The smoke tests cover manifest validation, the six-gate state machine (including
the duplicate-capability scan and dependency resolution at the Certify gate),
and the Ontology Builder Agent contract (entity/relationship proposals,
duplicate + determinism/risk conflict flags, and the human-review queue).

## Ontology Builder Agent contract

```
sync_meaning(manifests, ontology) -> SyncResult(
    proposals,     # GraphChange[]  (entities + relationships)
    confidence,    # float[]        (per-proposal, 0..1)
    flags,         # {duplicates, conflicts}
    review_queue,  # GraphChange[]  (held for human approval)
)
```

`DUPLICATE_OF` proposals, determinism/risk conflicts, `restricted`-scope changes,
and any proposal below the confidence threshold are routed to the review queue
— everything else is available via `result.auto_merge`. The implementation is a
deterministic heuristic and is freely replaceable (LLM/hybrid) because the
chassis depends on this contract, not the implementation.
