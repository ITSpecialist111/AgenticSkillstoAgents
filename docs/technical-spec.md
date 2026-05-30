# Technical Specification

> The true technical spec for the chassis: the **canonical Manifest schema** (Part A — the
> frame), the stage-gate state machine (Part B), the Ontology Builder Agent interface
> (Part C), and the registry/API surface. The machine-readable schema lives at
> [`../schemas/skill-manifest.schema.json`](../schemas/skill-manifest.schema.json).

## Part A — The Skill Manifest (the chassis frame)

Every Skill carries exactly **one** manifest. The same document travels every stage of the
pipeline unchanged except for its `lifecycle` block. This single fact is what makes the
flow repeatable.

### Top-level structure

```jsonc
{
  "apiVersion": "skills.dev/v1",
  "kind": "Skill",
  "identity":    { /* who/what: id, name, version, owner, skillType, tags */ },
  "capability":  { /* IOPE: summary, capabilityTags, inputs, outputs, preconditions, effects */ },
  "scoring":     { /* determinism, risk, reversible, rationale */ },
  "dependencies":[ /* refs to other skills/capabilities */ ],
  "mcp":         { /* server, toolName, namespace, transport */ },
  "governance":  { /* visibility, rbac, dataClassification, cost, audit */ },
  "lifecycle":   { /* stage, certifiedBy, certifiedAt, supersedes, supersededBy */ }
}
```

### Field reference

| Block | Field | Required | Notes |
|---|---|---|---|
| root | `apiVersion` | ✅ | Schema version, e.g. `skills.dev/v1`. |
| root | `kind` | ✅ | Always `Skill`. |
| identity | `id` | ✅ | Immutable `namespace/name`; the de-duplication key. |
| identity | `name`, `version` | ✅ | Display name; semver. |
| identity | `owner.handle` | ✅ | Accountable identity for RBAC + hand-off. |
| identity | `skillType` | — | Disambiguates the overloaded word "Skill" (see [`prior-art.md`](prior-art.md)). |
| capability | `summary` | ✅ | One-line capability statement. |
| capability | `capabilityTags` | — | Canonical concepts for matchmaking/dedupe. |
| capability | `inputs` / `outputs` | ✅ | Typed I/O (I, O of IOPE). |
| capability | `preconditions` / `effects` | — | P and E of IOPE. |
| scoring | `determinism` | ✅ | `high` \| `medium` \| `low`. |
| scoring | `risk` | ✅ | `low` \| `medium` \| `high` \| `critical`. |
| dependencies | `ref` | ✅* | Skill id or capability tag (per item). |
| mcp | `server`, `toolName`, `namespace`, `transport` | — | Ride MCP for discovery/governance. |
| governance | `visibility` | ✅ | `private` \| `team` \| `org` \| `public`. |
| lifecycle | `stage` | ✅ | The pipeline position (state machine below). |

The IOPE shape (Inputs, Outputs, Preconditions, Effects) is deliberately borrowed from
OWL-S so the Meaning Layer can do capability matchmaking; see
[`ontology-schema.md`](ontology-schema.md).

### Validation

```bash
pip install jsonschema
python - <<'PY'
import json
from jsonschema import Draft202012Validator
schema = json.load(open("schemas/skill-manifest.schema.json"))
manifest = json.load(open("examples/invoice-extract.manifest.json"))
Draft202012Validator(schema).validate(manifest)
print("valid")
PY
```

All three bundled manifests in [`../examples/`](../examples) validate against the schema
and are used in the worked walkthrough.

## Part B — The pipeline state machine

`lifecycle.stage` is the single source of truth for where a skill sits.

```
draft ──Register──▶ registered ──Certify(automated checks + human approval)──▶ certified
certified ──Publish──▶ published
published ──(Meaning-sync: ontology updated, stage unchanged)
published ──(Compose: runtime use by capped agents)
published ──Deprecate──▶ deprecated ──Retire──▶ retired
```

### Gate exit criteria

| Gate | Automated exit checks | Human gate |
|---|---|---|
| Register | Manifest validates against schema | — |
| **Certify** | determinism/risk scored & consistent; duplicate-capability scan; dependency refs resolve | **Required** — sets `certifiedBy`, `certifiedAt` |
| Publish | `stage == certified`; MCP namespace verified | — |
| Meaning-sync | Ontology Builder Agent proposals queued | Required for dupes/conflicts (see Part C) |
| Compose | Agent count under cap; scope permits caller | — |
| Retire/version | Lineage links set (`supersededBy`) | Optional |

## Part C — Ontology Builder Agent interface

Pure, replaceable function (full detail in
[`ontology-builder-agent.md`](ontology-builder-agent.md)):

```
syncMeaning(manifests: Manifest[], ontology: Graph) -> {
  proposals: GraphChange[],      // entities + relationships to add/update
  confidence: number[],          // per-proposal 0..1
  flags: { duplicates: Edge[], conflicts: Issue[] },
  reviewQueue: GraphChange[]     // changes withheld for human approval
}
```

The chassis depends on this **contract**, not the implementation — so the unproven part is
swappable without disturbing Parts A and B.

## Registry & API surface (MCP-compatible)

The registry is an **MCP-compatible catalog**, not a new store. Minimum operations:

| Operation | Purpose |
|---|---|
| `POST /skills` | Register a manifest (→ `registered`). |
| `POST /skills/{id}/certify` | Run checks + record human approval (→ `certified`). |
| `POST /skills/{id}/publish` | Promote to the MCP catalog (→ `published`). |
| `GET /capabilities?tag=` | Matchmaking query for the Reasoning Layer. |
| `GET /skills/{id}/lineage` | Supersede chain + dependency graph. |

## Build / system-of-record

- **GitHub** is the manifest system-of-record (versioning, PR review = the Certify human
  gate in practice).
- **OneLake** stores telemetry/lineage; **Fabric IQ** holds the ontology.
- **Copilot Studio** hosts the capped composition agents.
