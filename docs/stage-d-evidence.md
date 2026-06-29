# Stage D — Skill IQ ontology MCP tool: end-to-end evidence

> **Status:** complete (2026-06-29). Local DuckDB backend live in production
> Cowork. Fabric SQL endpoint backend stubbed behind `ONTOLOGY_BACKEND=fabric`
> pending user-run of [`fabric-iq-setup.md`](fabric-iq-setup.md).
> Companion to [`roadmap-2026-q3.md`](roadmap-2026-q3.md) §Stage D and
> [`cowork-plugin-limitations.md`](cowork-plugin-limitations.md).

## What shipped

| Component | Path |
| --- | --- |
| Parquet exporter (manifests → graph) | `prototype/chassis/fabric_export.py` |
| Query layer (DuckDB + Fabric stub) | `mcp-server/ontology_query.py` |
| MCP tool `query_ontology` | `mcp-server/server.py` |
| Tests (4 new) | `mcp-server/test_server.py` |
| Bicep + runbook for Fabric backend | `infra/fabric-iq/`, `docs/fabric-iq-setup.md` |
| Cowork plugin surface (4 tools) | `cowork-plugin-registry/toolDescription.json` |

Deployed image: `crcowork5a2c14.azurecr.io/skills-registry-mcp:v5`
Container App revision: `ca-cowork-mcp--0000005`
Plugin manifest version: `cowork-plugin-registry/manifest.json` v0.2.0
Commit: `8d1c4b3` "Stage D: query_ontology MCP tool + Fabric IQ provisioning"

## What the tool does

`query_ontology(seed, relation, max_hops, caller_classification)` returns
graph paths from a seed node (skill id, capability tag, data type, or
condition) outward through a typed edge graph
(PROVIDES / CONSUMES / PRODUCES / REQUIRES / DEPENDS_ON / CAUSES /
SUPERSEDES / DUPLICATE_OF). Per-hop provenance includes confidence and
`dataClassification`. Server-side cap of 5 hops; default 3.

Per-edge `dataClassification` is enforced before the path is returned —
edges classified above `caller_classification` are suppressed and counted
in `suppressedByClassification`. Defaults to `public` (most restrictive
view) when the caller doesn't declare a clearance.

## Evidence 1 — Cowork agent invokes `query_ontology` end-to-end

**Task:** Cowork task `b75355f8-2dd3-476e-8f60-d1edce8c7566`.
**Prompt:** *"Use the skills registry's `query_ontology` tool with
seed='legal/msa-redlining', relation='DEPENDS_ON', max_hops=3,
caller_classification='confidential'."*

**Behaviour observed.**
1. Agent picked `mcp__skills-registry-mcp__query_ontology` unprompted from
   the connector tool list (no fallback to `find_skill_by_capability`).
2. One per-call Approve modal — params filled verbatim from the prompt.
3. Response rendered in the chat surface:

```
Summary
- Total paths: 1
- Max hops requested: 3 / applied: 3
- Suppressed by classification: 0
- Truncated: false

Depth  Source         Edge        Destination   Confidence  Data Classification
1      msa-redlining  DEPENDS_ON  docx.create   0.9         confidential

Endpoint: docx.create
Max classification along path: confidential
```

This confirms: parquet ingest works, DuckDB recursive CTE returns the
right hop, MCP envelope round-trips through Cowork, and the agent
discovers the tool from the connector advertisement.

## Evidence 2 — governance gating fires per edge

**Setup.** Same seed (`legal/msa-redlining`), `max_hops=3`, only the
`caller_classification` changed.

| Caller clearance | totalPaths | suppressedByClassification |
| --- | --- | --- |
| `confidential` | 1 | 0 |
| `internal` | 0 | 14 |

At `internal` clearance the same query returns zero paths but reports 14
edges suppressed — every dependency edge for `msa-redlining` is classified
`confidential` or above, so a lower-cleared caller learns nothing about
its graph neighbourhood. This is the governance fence Stage D was meant
to land: classification is not advisory metadata, it gates traversal at
the edge level inside the MCP server before any response reaches the
agent.

## Why organisations care about an ontology over the registry

Six concrete benefits, each grounded in the same live system:

1. **Impact analysis.** `query_ontology(seed=<capability>, relation=DEPENDS_ON)`
   answers *"if I deprecate this, what breaks?"* in one call. The same
   parquet drives this for any node type — skill, capability, data type.
2. **Governance scoping.** Per-edge `dataClassification` enforcement (see
   Evidence 2) means a registry that contains confidential pipeline
   skills can still be safely discoverable by lower-cleared agents —
   they get suppression counts, not silent denials, and never see the
   confidential endpoints.
3. **Composition planning.** Multi-hop traversal lets an agent build a
   capability chain (`ap.intake → invoice.extract → po.match`) before
   committing to any one skill, instead of probing tools one at a time
   and burning Approve modals.
4. **Duplicate / supersession surfacing.** `SUPERSEDES` and
   `DUPLICATE_OF` are first-class edge types — the same query that finds
   dependencies also surfaces "this skill replaces that one" without a
   second lookup.
5. **Graph reasoning beats tag matching.** A flat tag list answers
   *"who has tag X?"*; an ontology answers *"what chain of skills,
   conditions, and data types gets me from input shape A to output shape
   B?"*. That's the missing-middle reasoning step the chassis was
   designed to enable.
6. **Fabric portability.** The same parquet files are uploaded to
   OneLake via [`fabric-iq-setup.md`](fabric-iq-setup.md); flipping
   `ONTOLOGY_BACKEND=fabric` swaps the local DuckDB query for a Fabric
   SQL endpoint without touching the MCP tool shape. The query layer is
   an interface — the agent never knows which backend served the path.

## Cowork plugin surface evidence

`cowork-plugin-registry/toolDescription.json` advertises four tools after
Stage D:

- `list_capabilities` (Stage 2)
- `find_skill_by_capability` (Stage 2)
- `describe_skill` (Stage 2; text payloads inlined as of `:v4`)
- `query_ontology` (Stage D — this evidence)

All four carry `readOnlyHint: true, idempotentHint: true,
openWorldHint: false`, matching the pattern that survived the
write-side-blocked finding in
[`cowork-plugin-limitations.md` §4](cowork-plugin-limitations.md).

## Local reproduction (no Fabric needed)

```bash
python -m prototype.chassis.fabric_export --out prototype/out/fabric/
pytest mcp-server/test_server.py -k query_ontology -v
python -m mcp_server  # ONTOLOGY_BACKEND=local (default)
```

Then call the tool over MCP streamable HTTP at
`http://localhost:8080/api/mcp` with `tools/call` → `query_ontology`.

## What's still ahead

- **Stage E telemetry** — first slice landed: every MCP tool call emits one
  append-only JSON event (`mcp-server/telemetry.py`). Backends: `null` (default
  for tests), `stdout` (Container Apps deploy — events surface in Log Analytics
  with no extra wiring), `jsonl` (local file, queryable via DuckDB). Per-tool
  extras captured: `resultCount`, `payloadFileCount`, `capabilityCount`,
  `totalPaths`/`suppressedByClassification`/`truncated`/`maxHopsApplied` for
  `query_ontology`, `filesAdded`/`prOpened` for `submit_skill_draft`. Args are
  hashed (16-char sha256 prefix), never logged in the clear. The
  find/pick/succeed panels still need building — sink is wired, dashboard is not.
- **Stage F cross-domain ontology** — adding `Person`, `Project`,
  `TrainingArtifact` node types and the adapters that feed them.
- **Fabric backend** — code path exists; user runs
  `infra/fabric-iq/main.bicep` + the runbook to switch it on. The MCP
  tool shape doesn't change.

## CI

Both Stage D artifacts are now gated by
`.github/workflows/validate-manifests.yml`:

- `python -m prototype.chassis.fabric_export --out prototype/out/fabric/`
  runs before the MCP test step, asserts the three parquet files + schema
  marker exist.
- MCP test step runs `query_ontology` tests, `fabric_export` idempotence
  test, and Stage E telemetry tests (7 new tests) — 36 tests total.
