# prototype-lite

A deliberately minimal counter-implementation of the same construct that lives in
[`../prototype/`](../prototype). Same canonical manifest, same bundled example
skills, same kind of registry — but built from the **opposite assumption**:

> **Build the registry so it works without the Ontology Builder Agent.**
> Add the agent later, behind a measurable contract, only if hand-curation
> actually breaks down.

This branch exists to make the trade-off concrete. Run both side-by-side and
decide which weight of machinery your context justifies.

## Side-by-side

| | `prototype/` (full chassis) | `prototype-lite/` (this) |
|---|---|---|
| Files of code | 4 modules, ~600 LOC | **1 file, 178 LOC** |
| Tests | 25 | 8 |
| Lifecycle stages | 6 (`draft` → `registered` → `certified` → `published` → `deprecated` → `retired`) | **3** (`draft` / `published` / `archived`) |
| Pipeline gates | 6 (Register, Certify, Publish, Meaning-sync, Compose, Retire) | **2** (load = Register; `certify()` = Certify; publish/retire are just stage values) |
| Ontology layer | `OntologyBuilderAgent`, `GraphChange`, `SyncResult`, `auto_merge`, `review_queue` | **Capability tags are the ontology** |
| Duplicate detection | Heuristic agent emitting `DUPLICATE_OF` edges with confidence scores | **One pass over (IOPE signature, tags); blocks `certify()` on clash** |
| "Meaning" graph | In-memory typed-node/edge graph + Mermaid emitter | Inverted index `tag -> [skill ids]` printed by `lite.py list` |
| Audit log | Lifecycle fields | **`git log` on the manifests folder** |
| Human approval | `certifiedBy` field set by the registry | **`certifiedBy` field set by the GitHub PR review** that merges the manifest |
| Schema | The same `schemas/skill-manifest.schema.json` | The same `schemas/skill-manifest.schema.json` |
| Example manifests | The same `examples/*.manifest.json` | The same `examples/*.manifest.json` |

The canonical manifest and the example skills are deliberately shared. The
manifest *is* the load-bearing artifact — neither branch disputes that.

## What lite drops, and why

| Cut | Why it's safe to drop now |
|---|---|
| 4-layer architecture (Storage / Meaning / Reasoning / Composition) | "Reasoning" is just graph queries over Meaning. "Composition" is the caller's job (Copilot Studio agent, etc.) — not the registry's. Collapse to Storage + caller. |
| `OntologyBuilderAgent` | The docs themselves call this "the unproven part." Below ~50 skills, capability tags + manual duplicate scan at PR review delivers the same outcome. |
| `GraphChange` / `SyncResult` / `auto_merge` / `review_queue` | Contract surface for an agent that doesn't exist yet. The caller can decide what to escalate. |
| `registered` / `certified` / `deprecated` stages | Three states model the same lifecycle: `draft` (in PR), `published` (merged), `archived` (marked for removal). Deprecation lineage is a manifest field, not a stage. |
| Meaning-sync gate | If tags ARE the meaning, there's nothing to sync. |
| Compose gate | The composing agent is downstream; it doesn't need a gate in the registry's pipeline. |

## What lite keeps (the load-bearing minimum)

1. **The canonical Manifest schema.** Unchanged — it's the real artifact.
2. **Register gate.** `lite.load()` validates against the schema.
3. **Certify gate.** `Registry.certify(sid, approver)` requires a human approver and runs the duplicate-capability scan against already-published skills. In production this is a GitHub PR review editing the manifest file.
4. **Capability search.** `Registry.find_by_capability(tag)` — the one query a composing agent actually needs.
5. **Duplicate detection.** `Registry.duplicates()` — IOPE signature + tag overlap, returned as data the caller can act on.

That's the README's thesis ("centralise capabilities + meaning + trust, cap the
number of agents, let them compose from a registry"). 178 lines.

## Install and run

```bash
cd prototype-lite
# Same deps as the full prototype.
python -m pip install jsonschema pytest

# CLI: see the catalog
python lite.py list
python lite.py find invoice.extract
python lite.py dupes

# Smoke tests
python -m pytest -q
```

## When to graduate to the full chassis

Promote pieces of `prototype/` over lite **when you have evidence**, not on
principle:

- **Reintroduce `OntologyBuilderAgent`** when you have ≥50 skills *and*
  measurable evidence that humans miss duplicate/conflict cases at PR review.
- **Reintroduce intermediate lifecycle stages** when you need a state the
  manifest can't carry as a flag (e.g. a long-running certification cycle
  with multiple sign-offs).
- **Reintroduce the graph layer** when capability tags can no longer answer
  composition queries — e.g. when callers need to reason over preconditions
  and effects, not just tag equality.

Until then, lite is the chassis. See
[`../docs/complexity-review.md`](../docs/complexity-review.md) for the full
review that motivated this branch.
