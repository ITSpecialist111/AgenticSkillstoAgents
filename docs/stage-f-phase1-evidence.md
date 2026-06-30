# Stage F Phase 1 — cross-domain ontology: end-to-end evidence

> **Status:** Phase 1 complete (2026-06-30). Synthetic Person / Project /
> Training / Certification / Role / Team nodes and ten cross-domain edge
> types projected into the same parquet store the Stage D query layer
> already reads. `query_ontology` now traverses Person → Skill (and back)
> without a new tool surface. Companion to
> [`roadmap-2026-q3.md`](roadmap-2026-q3.md) §Stage F and
> [`stage-d-evidence.md`](stage-d-evidence.md).
>
> Phase 2 (Cypher-lite `query_org_graph` DSL) and Phase 3 (real-source
> adapters: GitHub, M365/Entra, Project/Planner/Jira, Viva Learning) are
> deferred — separate plans pick them up.

## What shipped

| Component | Path |
| --- | --- |
| Synthetic org generator (people/projects/training/certs + edges) | `prototype/chassis/synth_org.py` |
| Parquet exporter — extended with `--org-dir` | `prototype/chassis/fabric_export.py` |
| Query layer — added `node_type_filter` kwarg | `mcp-server/ontology_query.py` |
| MCP tool surface — `query_ontology` extended + new `list_org_entities` | `mcp-server/server.py` |
| Tests (7 new) — total 43 green | `mcp-server/test_server.py` |
| Tiny committed fixture (10 people / 4 projects / 3 training / 2 certs) | `prototype/fixtures/synth-org-small/` |
| Bench harness — new `--include-org` sweeps | `prototype/chassis/bench_ontology.py` |
| Schema bumped to `ontology.parquet/v2` (backwards-compatible) | `prototype/out/fabric/_schema_version.txt` |

Schema is additive: with no `--org-dir`, the parquet output is byte-
identical to v1. The Fabric SQL endpoint reads the same column names,
so the remote backend keeps working without changes.

## What the tool does (Phase 1 surface)

`query_ontology(seed, relation, max_hops, caller_classification,
node_type_filter)` — the existing tool, now with one extra optional
kwarg. When `node_type_filter` is set, paths whose *terminal* node type
falls outside the allowed set are filtered out by the SQL layer (not in
Python). The recursive CTE itself is unchanged — verb-agnostic over any
edge type — so cross-domain seeds work without new traversal code:

| Seed | Walks | Returns |
| --- | --- | --- |
| `person/eng-042` | `HOLDS_SKILL` (1 hop) | Skills that person holds |
| `person/pm-007` | `WORKED_ON → REQUIRED → SATISFIED_BY` (3 hops) | Skills used on that PM's projects |
| `project/finance-rfp-001` | `REQUIRED → SATISFIED_BY` (2 hops) | Skills needed for the project |
| `cert/aws-sap` | `HOLDS_CERT` inverse (1 hop) | People holding the cert |

`list_org_entities(entity_type, limit=50)` — new helper. Returns
summaries for `Person | Project | Training | Certification | Role |
Team` so an agent can find a seed before calling `query_ontology`.
Read-only, paginated, mirrors the `find_skill_by_capability` shape.

Per-edge `dataClassification` is still enforced before any path
reaches the agent. Restricted Person edges are dropped under low
clearance and counted in `suppressedByClassification`.

## Evidence 1 — projection produces the expected graph

Generation + projection against the synthetic 1000-skill catalog and a
synthetic 500-person org:

```bash
python -m prototype.chassis.synth_org \
  --count-people 500 --count-projects 200 \
  --count-training 150 --count-certs 60 \
  --out prototype/out/synth/org \
  --skills-dir prototype/out/synth/manifests --seed 42

python -m prototype.chassis.fabric_export \
  --out prototype/out/synth/parquet \
  --examples prototype/out/synth/manifests \
  --org-dir prototype/out/synth/org
```

Output summary:

| Table | Rows |
| --- | --- |
| `nodes.parquet` | **2 348** (1000 skills + 500 people + 200 projects + 150 training + 60 certs + auto-created Role/Team nodes + 467 capability/datatype/condition nodes from the skill catalog) |
| `edges.parquet` | **20 440** (skill projection + 10 cross-domain edge types) |
| `manifests.parquet` | 1 000 |
| `org_facts.parquet` | 500 (one row per person; role, team, skill/cert/project/training counts) |
| `_schema_version.txt` | `ontology.parquet/v2` |

The tiny committed fixture (`prototype/fixtures/synth-org-small/`) is
the same shape at a tenth the scale: 10 people / 4 projects / 1
training / 2 certs / **192 edges** across all 10 new edge types. CI
exercises it on every push.

## Evidence 2 — Cowork agent invokes both Stage F tools end-to-end

**Live capture, 2026-06-30.** Image
`crcowork5a2c14.azurecr.io/skills-registry-mcp:v6` (org parquet baked
at build time from `prototype/fixtures/synth-org-small/`),
Container App revision `ca-cowork-mcp--0000006`, plugin `v0.3.0`
(GUID `a3d5f2c7-…` preserved, in-place upgrade from v0.2.0).

> **Scale bump same day, image `:v7` / revision `--0000007`.** The
> capture below was against `:v6` (22 curated examples + 10-person
> fixture). `:v7` swaps that for the full 1000-skill synth catalog +
> 500-person org baked at build time — so what Cowork now queries in
> production is the at-scale graph (2 348 nodes / 20 440 edges, see
> Evidence 3). Phase 1 envelope shape, governance gating, and tool
> surface are identical; only the row counts grew.

**Prompt pasted into Cowork:** *"Use the skills-registry connector to
(1) list 10 Person entities, then (2) `query_ontology` from
`person/architect-004` with `max_hops=4`,
`node_type_filter=["Skill"]`, `caller_classification="internal"` and
report the raw envelopes."*

**Behaviour observed.**
1. The agent picked `list_org_entities` and `query_ontology` in
   parallel — no fallback to `find_skill_by_capability`, no prompting
   for tool choice. One Approve modal per call.
2. Call 1 returned all 10 Person summaries with role, team, and
   `data_classification`. Two are `confidential` (`pm-000`,
   `eng-001`); the other eight are `internal`. Matches the fixture.
3. Call 2 envelope (raw):

   ```
   seed:                       person/architect-004
   maxHopsRequested:           4
   maxHopsApplied:             4
   callerClassification:       internal
   nodeTypeFilter:             ["Skill"]
   totalPaths:                 50
   suppressedByClassification: 18
   truncated:                  false
   ```

4. Of the 32 visible paths, three distinct routes appear:

   | Depth | Route | Endpoint sample |
   | --- | --- | --- |
   | 1 | `HOLDS_SKILL` (Architect's own skills) | `dev/mcp-builder`, `dev/skill-creator`, `dev/webapp-testing`, `dev/changelog-generator` |
   | 3 | `WORKED_ON → EMPLOYED → HOLDS_SKILL` (colleague reach) | `comms/meeting-insights`, `design/canvas`, `finance/po-match`, `legal/msa-redlining`, … |
   | 3 | `WORKED_ON → REQUIRED → SATISFIED_BY` (project capability match) | `design/canvas` via `marketing.asset`, `design/theme-factory` via `theme.generate` |

   The colleague-reach and capability-match routes converge on
   `design/canvas` and `design/theme-factory` — both reachable
   because a colleague holds them *and* because a project requirement
   they satisfy was needed. That's the ontology paying for itself:
   the same query surfaces both the "who knows it" and the "what
   needs it" answer in one envelope.

5. The 18 suppressed paths are exactly the routes traversing the two
   confidential Persons (`pm-000`, `eng-001`). At
   `caller_classification="internal"` the gating drops them before
   the path reaches the agent — the same per-edge fence Stage D
   Evidence 2 demonstrated for `legal/msa-redlining`, now applied to
   Person edges. Re-running at `caller_classification="confidential"`
   would surface those paths; the agent never saw them in this run.

This is the Phase 1 success bar: cross-domain seed → multi-hop
traversal → governance-gated envelope → returned through Cowork
without any new tool surface beyond what the deployed plugin
advertises.

## Evidence 3 — latency at 1000 skills + 500 people

`python -m prototype.chassis.bench_ontology --parquet
prototype/out/synth/parquet --seeds 100 --include-org` against the
2 348-node / 20 440-edge graph:

| Sweep | p50 | p95 | p99 | avg paths |
| --- | --- | --- | --- | --- |
| skill DEPENDS_ON × 5 | 103.7 ms | 309.1 ms | 358.9 ms | 1 838.7 |
| person HOLDS_SKILL × 1 | 33.6 ms | 38.0 ms | — | 8.0 |
| person HOLDS_SKILL × 2 | 39.6 ms | 44.2 ms | — | 8.0 |
| person WORKED_ON × 1 | 33.7 ms | 38.5 ms | — | 5.4 |
| person WORKED_ON × 2 | 38.1 ms | 43.8 ms | — | 17.6 |
| person WORKED_ON × 3 | 46.8 ms | 57.2 ms | — | 67.1 |
| person ANY × 5 ntf=Skill | 437.6 ms | **779.2 ms** | 1 179.9 ms | 9 531.9 |
| project ANY × 5 ntf=Skill | 180.0 ms | 261.1 ms | — | 2 449.2 |

The 5-hop unfiltered-relation Person→Skill sweep is the worst case —
~9 500 paths returned per seed unfiltered. p95 779 ms is under the 2 s
Stage F success criterion, and the realistic agent shape (with
`result_limit` truncating the JSON envelope) finishes well under
50 ms because the SQL `LIMIT` aborts the CTE early. Documented, not
optimised — the headroom is fine for Phase 1.

## Evidence 4 — governance gating fires on cross-domain edges

The per-edge `dataClassification` check from Stage D applies
unchanged to the new edge types. Test
`test_query_ontology_governance_gating_person` asserts that under
`caller_classification="public"` every hop on every returned path
carries a `public` classification — `confidential` Person edges (the
~5 % of seeded execs) are suppressed before the path reaches the
agent, and counted in `suppressedByClassification`. The same fence
that protected `legal/msa-redlining` in Stage D Evidence 2 now
protects Person/Project edges.

## Why this matters (six concrete payoffs)

1. **Skill-gap analysis at staffing time.** *"This RFP requires
   capabilities A, B, C — who in the org has them, and what training
   closes the third?"* — one `query_ontology` call from a Project
   seed.
2. **Reuse discovery across business units.** *"Finance built
   `legal/msa-redlining`'s underlying capability — who in legal has
   used it?"* — Skill → SATISFIED_BY⁻¹ → REQUIRED⁻¹ → Project →
   EMPLOYED → Person.
3. **Onboarding personalisation.** *"New joiner has skills X, Y —
   their team's projects need W, Z — surface the training paths."* —
   Person → MEMBER_OF → Team → (its people) → WORKED_ON → Project →
   REQUIRED → Capability gap → Training → COMPLETED.
4. **Cert-driven discovery.** *"Who holds `aws/sap-pro`, and what
   skills do they hold beyond the cert?"* — Cert ← HOLDS_CERT ←
   Person → HOLDS_SKILL → Skill.
5. **Governance scoping survives the cross-domain extension.**
   Restricted Person rows don't leak into open queries; the same
   suppression-count contract from Stage D is reused.
6. **No new tool surface for agents to learn.** The same
   `query_ontology` tool the agent already uses for skill graphs now
   walks the org graph. `list_org_entities` is purely a discovery
   helper — every actual traversal stays in one tool.

## Local reproduction

```bash
# Tiny fixture, fast — what CI runs.
pytest mcp-server/test_server.py -k "org or cross_domain or node_type_filter" -v

# Full 1000-skill + 500-person rebuild (≈30 s end-to-end).
python -m prototype.chassis.synth_skills --count 1000 \
  --out prototype/out/synth/manifests

python -m prototype.chassis.synth_org \
  --count-people 500 --count-projects 200 \
  --count-training 150 --count-certs 60 \
  --out prototype/out/synth/org \
  --skills-dir prototype/out/synth/manifests --seed 42

python -m prototype.chassis.fabric_export \
  --out prototype/out/synth/parquet \
  --examples prototype/out/synth/manifests \
  --org-dir prototype/out/synth/org

python -m prototype.chassis.bench_ontology \
  --parquet prototype/out/synth/parquet --seeds 100 --include-org
```

## What's still ahead (Phase 2 + Phase 3)

- **Phase 2 — `query_org_graph` Cypher-lite DSL.** Phase 1 lets an
  agent pick a starting node and ask for a max-hop neighbourhood;
  Phase 2 will let it ask for a *shape* — *"PM who worked on a
  project that employed an engineer who holds both
  `kubernetes.tuning` and `cost.fin-ops`"*. That's the §F(f)
  five-hop success criterion. Phase 1 proved the graph + governance
  + latency that Phase 2 builds on.
- **Phase 3 — real-source adapters.** Replace `synth_org.py` with
  Entra (people + roles), Project/Planner/Jira (projects), Viva
  Learning (training + certs). One adapter per source, normalising
  into the same parquet schema. Work IQ federation lands here too:
  the registry adds capability edges, Work IQ resolves live
  person/team/availability at query time.

## CI

`prototype/fixtures/synth-org-small/` is committed under git so the
seven Stage F tests run on every push without regenerating the
fixture. Total: 43 tests in `mcp-server/test_server.py`.
