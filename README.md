# AgenticSkillstoAgents

> Closing the missing middle between individual **Skills** and org-wide **Agents** —
> proven end-to-end inside Microsoft Copilot Cowork.

**Full thesis:** [`docs/ontology-skills-thesis.md`](docs/ontology-skills-thesis.md) — the centralization argument + live evidence.

## TL;DR

This repo is a **spike that became a working system**. It demonstrates a pattern
for taking individual Copilot/Cowork **Skills** (the new Access databases) and
turning them into a **governed, discoverable, composable** capability layer that
an agent can reason over at runtime — without rebuilding each skill as a bespoke
custom engine agent.

As of **2026-06-29** the end-to-end loop runs live inside Microsoft Copilot
Cowork against a real Azure Container App in **two distinct patterns**:

1. **Cross-connector composition** — an agent asks the registry *"who can do
   invoice extraction?"*, gets back a binding, and then invokes the bound tool
   on a **different MCP connector** in the same conversation.
2. **Registry-as-library** — the agent asks for a skill (e.g.
   `legal.redline`), `describe_skill` returns the **SKILL.md body inline**,
   and the agent follows those instructions using Cowork's own tools (docx,
   file, web) to produce a real deliverable. Reproduced twice — both runs
   produced `MSA_UK_EU_Draft.docx` with the required UK + EU clause set at
   **~483 Copilot Credits** end-to-end.

See [`docs/cowork-plugin-limitations.md`](docs/cowork-plugin-limitations.md)
and [`docs/registry-evidence.md`](docs/registry-evidence.md) §9 for the test
results.

## The problem

Modern AI tooling (GitHub Copilot, Copilot Cowork, Copilot Studio) gives
individuals the power to build **Skills** — repeatable processes wired to
deterministic tools. This is brilliant for the individual, but it stops there.

There are two stable end-states today, and **nothing in between**:

| | Individual Skill | Custom Engine Agent |
|---|---|---|
| **Owner** | One person (maker) | Org / platform team |
| **Reuse** | Personal, copy-paste | Centrally deployed, multi-user |
| **Determinism** | High (deterministic tools) | Variable (LLM orchestration) |
| **Governance** | None | Full (RBAC, audit, lifecycle) |
| **Cost to build** | Minutes | Weeks + a platform team |

A Skill makes a process **repeatable**. But unless it is shared, it stays a
**singular solution**. To make it org-wide today you must rebuild it as a full
custom engine agent — a leap most ideas never survive.

### The Access-database analogy

This is the **Access database era** all over again. Skills are the new Access
DBs: powerful, local, repeatable — and invisible, ungoverned, and un-scalable.
The historical fix was **centralisation**: Access → SQL Server → OneLake.

But the naive "agent version" of that fix — **build 10,000 agents** — is wrong.
That is just shadow IT with an LLM on top. We did not solve Access by giving
everyone their own SQL Server; we **centralised the data and the meaning**.

## The thesis

The missing middle is **not a new kind of agent**. It is a **graduation
pipeline** built on top of a **shared, governed capability registry** and — 
critically — a **semantic (ontology) layer** that lets a *small number* of
agents reason over a *large pool* of governed skills.

We centralise **three things**, not one:

1. **Capabilities** — the deterministic tools/skills themselves (storage + governance).
2. **Meaning** — what each skill *is* and how it relates (the **ontology**).
3. **Trust** — identity, audit, cost, lifecycle.

Cap the number of agents. Grow the registry. Let agents **compose** from it.

## How it works (the running system)

```
┌──────────────────────────────────────────────────────────────────┐
│  Microsoft Copilot Cowork (the host)                              │
│                                                                   │
│  agent ──► mcp__skills-registry-mcp__find_skill_by_capability     │
│       ◄── { skill_id, mcp: { server, toolName, url } }            │
│       ──► mcp__skills-registry-mcp__describe_skill                │
│       ◄── full manifest + payloadFiles[] (SKILL.md inlined)       │
│       ──► mcp__finance-tools-mcp__invoice_extract  ◄─── routed    │
│       ◄── structured invoice fields                  by binding   │
│                                                                   │
│  ── OR — registry-as-library path:                                │
│       agent reads inlined SKILL.md from describe_skill            │
│       executes via Cowork's own tools (docx/file/web)             │
│       produces a real deliverable (e.g. MSA_UK_EU_Draft.docx)     │
└──────────────────────────────────────────────────────────────────┘
            │                                          │
            ▼                                          ▼
   Skills Registry plugin                    Finance Tools plugin
   (cowork-plugin-registry/)                 (cowork-plugin-finance/)
            │                                          │
            └──────────────┬───────────────────────────┘
                           ▼
            Azure Container App (mcp-server/)
            ┌──────────────────────────────────┐
            │  POST /api/mcp                   │  ← registry discovery
            │  POST /api/skills/<slug>/mcp     │  ← per-skill tool servers
            │  FastMCP / Streamable-HTTP       │
            └──────────────────────────────────┘
                           │
                           ▼
            Skill manifests (examples/*.manifest.json)
            validated against schemas/skill-manifest.schema.json
```

Two **separate** Teams plugin packages, each with **one** MCP connector,
both pointing at the same Container App on different paths. The agent
treats each as a distinct namespace (`mcp__<connector-id>__<tool>`),
which is what lets registry discovery and bound-tool invocation compose
cleanly inside a single Cowork conversation. (Splitting was forced by an
empirically-confirmed Cowork per-host connector dedup — see the
limitations doc.)

## The four-layer architecture

```
┌────────────────────────────────────────────────────────────┐
│  Composition Layer   — few org agents compose certified     │
│                        skills at runtime (custom engine)    │
├────────────────────────────────────────────────────────────┤
│  Reasoning Layer     — "which skill answers this need?"     │
│                        graph queries + data agents          │
├────────────────────────────────────────────────────────────┤
│  Meaning Layer       — Ontology / knowledge graph           │
│   (Fabric IQ)          Skill · Capability · Agent · Scope   │
├────────────────────────────────────────────────────────────┤
│  Storage / Governance — manifests, telemetry, lineage       │
│   (OneLake + GitHub)   versioning, RBAC, audit, cost        │
└────────────────────────────────────────────────────────────┘
        ▲
        │  Ontology Builder Agent (the "agentic code")
        └─ keeps the meaning layer in sync automatically
```

## Repository layout

| Path | What's in it |
|---|---|
| [`schemas/`](schemas/) | `skill-manifest.schema.json` — the canonical Skill manifest contract. |
| [`examples/`](examples/) | Validated example skills (`finance/invoice-extract`, `finance/po-match`, `finance/ap-intake`). |
| [`prototype/`](prototype/) | Full reference implementation: manifest loader, six-gate state machine, Ontology Builder Agent contract, CLI, smoke tests. |
| [`prototype-lite/`](prototype-lite/) | Deliberately minimal counter-implementation — same manifest, **one 178-line file**, no agent, no graph. Promotion criteria in [`docs/complexity-review.md`](docs/complexity-review.md). |
| [`mcp-server/`](mcp-server/) | FastMCP server wrapping the registry. Streamable-HTTP transport. Dual-mount: `/api/mcp` (discovery) and `/api/skills/<slug>/mcp` (per-skill tool servers). Dockerised. |
| [`cowork-plugin-registry/`](cowork-plugin-registry/) | Teams plugin v1.28 — exposes the registry's three read-only discovery tools. |
| [`cowork-plugin-finance/`](cowork-plugin-finance/) | Teams plugin v1.28 — exposes the worked-example `invoice_extract` tool that the registry's `finance/invoice-extract` binding points to. |
| [`cowork-plugin/`](cowork-plugin/) | **Superseded** combo plugin (one package, two connectors). Kept for reference; the per-host dedup issue is documented in the limitations doc. |
| [`infra/stage-2/`](infra/stage-2/) | Bicep for the planned public catalog blob (Azure Storage + GitHub Action publisher). |
| [`infra/stage-3/`](infra/stage-3/) | Bicep for the live Container App + ACR (deployed: `rg-cowork-spike-uks` / `ca-cowork-mcp`). |
| [`tools/`](tools/) | Build helpers — `build-cowork-plugin.py` and `smoke-test-mcp.py`. |
| [`docs/`](docs/) | Full design + spec + spike write-ups (see table below). |
| [`*-plugin*.zip`](.) | Pre-built plugin packages ready to upload via the Teams Developer Portal. |

## Screenshots — what it looks like end-to-end

Captured 2026-06-30 against image `:v7` (2 348 nodes / 20 440 edges) and the
`skills_ontology` Fabric Lakehouse. Full thesis with embedded context:
[`docs/ontology-skills-thesis.md`](docs/ontology-skills-thesis.md).

**Cowork — agent picking + composing two registry tools unprompted**

| Screenshot | What it shows |
|---|---|
| [`cowork-task-prompt-and-tool-calls.png`](examples/screenshots/cowork-task-prompt-and-tool-calls.png) | One natural-language brief → agent fires `list_org_entities` **and** `query_ontology` in parallel against the registry connector. |
| [`cowork-call1-list-org-entities-json.png`](examples/screenshots/cowork-call1-list-org-entities-json.png) | Raw envelope from `list_org_entities(entity_type="Person", limit=10)` — 10 people with `data_classification` per row. |
| [`cowork-call2-person-table-and-query-args.png`](examples/screenshots/cowork-call2-person-table-and-query-args.png) | Agent's rendered Person table + the spilled `query_ontology` envelope (`totalPaths:50, suppressedByClassification:18, maxHopsApplied:4`). |
| [`cowork-architect-skill-reach-analysis.png`](examples/screenshots/cowork-architect-skill-reach-analysis.png) | Agent's own breakdown: direct `HOLDS_SKILL` vs `WORKED_ON → EMPLOYED → HOLDS_SKILL` vs `WORKED_ON → REQUIRED → SATISFIED_BY`, including the call-out that 18 suppressed paths are the internal-clearance view. |

**Fabric Lakehouse — the same parquet projection the MCP server reads**

| Screenshot | What it shows |
|---|---|
| [`fabric-onelake-nodes-table.png`](examples/screenshots/fabric-onelake-nodes-table.png) | `skills_ontology.dbo.nodes` — node id / type / label / properties. |
| [`fabric-onelake-edges-table.png`](examples/screenshots/fabric-onelake-edges-table.png) | `skills_ontology.dbo.edges` — src / edge_type / dst / confidence / **data_classification** (the per-edge governance fence). |
| [`fabric-onelake-manifests-table.png`](examples/screenshots/fabric-onelake-manifests-table.png) | `skills_ontology.dbo.manifests` — flat manifest projection (id, name, version, stage, tags, owner, classification, determinism, risk). |

## Documentation

| Doc | What it covers |
|---|---|
| [`docs/architecture.md`](docs/architecture.md) | Four-layer model, the six-gate graduation pipeline, target platform, components. |
| [`docs/technical-spec.md`](docs/technical-spec.md) | Canonical Manifest, state machine, APIs, build. |
| [`docs/ontology-schema.md`](docs/ontology-schema.md) | Entity-relationship model for skills/capabilities/agents (IOPE). Stage F Phase 1 adds Person/Project/Training/Cert/Role/Team. |
| [`docs/ontology-builder-agent.md`](docs/ontology-builder-agent.md) | The agentic code that builds/maintains the ontology — and the measurable bet. |
| [`docs/roadmap.md`](docs/roadmap.md) | Phased graduation pipeline, milestones, success metrics. |
| [`docs/prior-art.md`](docs/prior-art.md) | What we learned from MCP / OWL-S / MLflow / RPA CoEs and how we differ. |
| [`docs/graduation-walkthrough.md`](docs/graduation-walkthrough.md) | A worked example: one skill traveling all six gates. |
| [`docs/cowork-plugin-spike.md`](docs/cowork-plugin-spike.md) | Full spec of the Cowork plugin + MCP contract. |
| [`docs/cowork-plugin-limitations.md`](docs/cowork-plugin-limitations.md) | **Live test results** + observed Cowork constraints (per-host dedup, approval gating, write-tool suppression, context cost). |
| [`docs/registry-evidence.md`](docs/registry-evidence.md) | **Token/credits/latency evidence** for the registry pattern, with the reproducible suite under [`tools/registry-evidence-suite.sh`](tools/registry-evidence-suite.sh). |
| [`docs/stage-2-plan.md`](docs/stage-2-plan.md) | Stage 2 (public catalog blob) plan. |
| [`docs/stage-b-runbook.md`](docs/stage-b-runbook.md) | Operational runbook for the deployed Container App. |
| [`docs/complexity-review.md`](docs/complexity-review.md) | Why the lite + full prototypes both exist, and when to promote. |
| [`docs/handoff.md`](docs/handoff.md) / [`docs/session-log-2026-06-28.md`](docs/session-log-2026-06-28.md) | Recent build state and session notes. |
| [`docs/stage-f-phase1-evidence.md`](docs/stage-f-phase1-evidence.md) | Stage F Phase 1 cross-domain ontology: generators, projection output, bench results, worked Person→Skill traversal. |

## The construct (the repeatable chassis)

The construct is delivered as **specifications + a canonical manifest + a
worked example** — three nested parts:

- **Part A — The Manifest:** one declarative spec every skill carries so the
  same unit travels every stage unchanged. Schema:
  [`schemas/skill-manifest.schema.json`](schemas/skill-manifest.schema.json);
  validated examples: [`examples/`](examples).
- **Part B — The Pipeline:** six fixed stage gates (Register → Certify →
  Publish → Meaning-sync → Compose → Retire) identical for every skill.
- **Part C — The Ontology Builder Agent:** the load-bearing, **unproven** part
  — isolated with a measurable contract behind a human gate. See
  [`docs/ontology-builder-agent.md`](docs/ontology-builder-agent.md).

## The MCP contract

Three read-only discovery tools (on the registry connector) + one worked-example
tool (on the finance connector). Invocation of business skills is out of scope
for the registry — the agent uses the `mcp` binding in each returned skill to
call the underlying skill server directly.

| Tool | Connector | Purpose |
|---|---|---|
| `find_skill_by_capability(tag, published_only=True)` | `skills-registry-mcp` | "Who can do X?" Returns `SkillSummary[]` including the MCP binding. |
| `describe_skill(skill_id)` | `skills-registry-mcp` | Full schema-validated manifest + `payloadFiles[]`. **Text payloads (SKILL.md, JSON ≤64 KB) are returned inline as `content`**; binary/oversized files retain a `skill://` URI. This is what lets a host without `skill://` resolution (e.g. Cowork) run a skill end-to-end. |
| `list_capabilities()` | `skills-registry-mcp` | `{tag: [skill_id, …]}` inventory. |
| `query_ontology(seed, relation, max_hops, caller_classification, node_type_filter)` | `skills-registry-mcp` | Graph traversal over the registry. Returns paths (each hop = src/edge/dst/confidence/classification) so an agent can answer "what depends on `legal.redline`?" or "which skills produce `DocxDocument`?". Backed by DuckDB-over-parquet locally; swaps to Fabric SQL endpoint via `ONTOLOGY_BACKEND=fabric` ([runbook](docs/fabric-iq-setup.md)). With Stage F Phase 1 ([evidence](docs/stage-f-phase1-evidence.md)) seeds may be `person/…`, `project/…`, `training/…`, or `cert/…`, and `node_type_filter` constrains terminal node types (e.g. `["Skill"]`). |
| `list_org_entities(entity_type, limit=50)` | `skills-registry-mcp` | Surfaces Stage F Phase 1 cross-domain entities (Person, Project, Training, Certification, Role, Team) so an agent can pick a seed for `query_ontology`. Read-only, paginated. |
| `invoice_extract(document_url)` | `finance-tools-mcp` | Worked example. Returns vendor/number/dates/line-items/totals (stubbed in the spike). |
| `submit_skill_draft(...)` | (server only) | Opens a GitHub PR. **Not surfaced inside Cowork** — see limitations doc. |

## Storage and scale

### Where skills live today

The same manifest travels three tiers — same schema, same slug, same payload
contract — so a skill is portable from a contributor's branch all the way to
a live agent without rewriting.

| Tier | Where | What's there | Refresh |
|---|---|---|---|
| **1. System-of-record** | This git repo — [`examples/*.manifest.json`](examples/) + payload folders `examples/<slug>/SKILL.md` | **23 manifests** at commit `1c85fef` (17 added this session: research, content, productivity, dev-loop, design, office, legal). Each manifest is JSON-Schema-validated by CI on every PR. | Per PR; CODEOWNERS-gated. |
| **2. Container image** | [`mcp-server/Dockerfile`](mcp-server/Dockerfile) generates the 1000-skill synth catalog (`synth_skills --count 1000 --seed 42`) **into** `/app/examples` at build time, alongside a 500-person synth org, and projects both to parquet — baked into `crcowork5a2c14.azurecr.io/skills-registry-mcp:v7` | Live image the Container App runs (revision `ca-cowork-mcp--0000007`). With `REGISTRY_CATALOG_MODE=local` (the current setting) the registry serves the 1000 synth skills directly from this baked copy — no external dependency at request time. `:v7` swaps the 22 curated examples for the 1000 synth catalog so the at-scale ontology (2 348 nodes / 20 440 edges) is what Cowork sees in production. The curated examples are still in git (`examples/` source-of-record) and remain the basis for the synth generator's domain/capability pools. | Per `az acr build` + `az containerapp update`. |
| **3. Public catalog blob** | Azure Storage `stcowork5a2c14` / `catalog/catalog.json`, refreshed by [`.github/workflows/publish-catalog.yml`](.github/workflows/publish-catalog.yml) | Read-only flattened catalog for out-of-band consumers and the planned Stage 2 public read API. Server can be flipped to `REGISTRY_CATALOG_MODE=remote` to fetch this with a 60 s TTL cache. | Per push to `main` touching `examples/**`. |

Live FQDN serving tiers 1+2 right now:
`ca-cowork-mcp.lemonsea-9c8971ad.uksouth.azurecontainerapps.io`.

### Why the catalog scales past 20 skills

The fear with adding skills to an agent is that each skill costs a tool slot
on the host, and tool schemas are loaded into the model's context on every
turn. At N=20 that already hurts; at N=200 it's untenable.

The registry pattern **inverts this**: the host only ever sees the registry's
small fixed set of *discovery* tools. Every business skill lives behind those
tools as data, not as a tool schema, and is fetched **on demand**.

Measured against the live endpoint (commit `1c85fef`, image `:v4`,
`REGISTRY_CATALOG_MODE=local`, 23 skills indexed):

| What the host pays for | Naive "one tool per skill" | Registry pattern (this repo) |
|---|---|---|
| Tool schemas loaded every turn | **N** (grows with catalog) | **4**, fixed (`find_skill_by_capability`, `describe_skill`, `list_capabilities`, `invoice_extract`). Measured `tools/list` payload: **2902 bytes** for the whole list. |
| Cost to ask "who can do X?" | Pay for all N schemas every turn whether used or not | One tool call. `find_skill_by_capability("meeting.summarise")` → **605 bytes** envelope, **231-byte** inner payload. |
| Cost to read a skill's full contract | Loaded eagerly | One tool call when needed. `describe_skill("comms/meeting-insights")` → ~4.4–5.0 KB envelope. **Text payload files (SKILL.md, JSON ≤64 KB) are inlined as `content`** so the agent can act on the body without a second fetch; binary/oversized files retain a `skill://` URI for lazy read. |
| Inventory of every tag | Implicit in tool list (huge) | `list_capabilities()` → ~6.6 KB for **66 tags across 23 skills** — one call, returns the whole index. |

Net: per-turn context cost is **O(1) in catalog size**. Adding the 17th, 50th
or 200th skill changes the data the registry indexes, **not** the tool surface
the host sees.

Live proof, today (2026-06-29): a Cowork agent was given just the registry
connector, asked for `meeting.summarise`, and correctly returned
`skill_id: meeting-insights` with its capability tags and summary — a skill
added this session that the agent had no prior knowledge of. The same loop
works for any of the 66 tags. A separate 4-call cross-connector run
(`list_capabilities` → `find_skill_by_capability` → `describe_skill` →
`invoice_extract`) cost **77.7 Copilot Credits** end-to-end measured via
Cowork's `/cost`. And — proven twice, reproducibly — a full
**registry-as-library** run against `legal.redline` produced an actual
`MSA_UK_EU_Draft.docx` deliverable with UK + EU schedules in **~483
credits** (task `b98ec511-…`, 4/4 green steps), with no prior agent
knowledge of the skill. Full numbers + reproducible test suite in
[`docs/registry-evidence.md`](docs/registry-evidence.md); runtime constraints
in [`docs/cowork-plugin-limitations.md`](docs/cowork-plugin-limitations.md).

## Running it

### Local — prototype + tests

```bash
cd prototype
pip install -r requirements.txt
python -m chassis.cli walkthrough          # graduate example skills end-to-end
python -m pytest -q                        # smoke tests
```

### Local — MCP server

```bash
cd mcp-server
pip install -r requirements.txt
python -m pytest -q                        # 20 tests, no MCP client needed

# stdio transport (Claude Desktop, MCP Inspector, etc.)
python -m server

# Streamable HTTP (what Cowork connects to)
MCP_TRANSPORT=http PORT=8000 python -m server
```

### Deploy to Azure (Stage 3)

```bash
# Provision Container App + ACR
az deployment group create \
  -g rg-cowork-spike-uks \
  --template-file infra/stage-3/main.bicep

# Build + push the image (build context is the repo root)
az acr build \
  --registry <acrName from outputs> \
  --image skills-registry-mcp:latest \
  --file mcp-server/Dockerfile \
  .
```

The live deployment is at
`https://ca-cowork-mcp.lemonsea-9c8971ad.uksouth.azurecontainerapps.io`.

### Install the plugins in Cowork

1. Upload **both** packages via the Teams Developer Portal (custom app):
   - `skills-registry-only-plugin.zip` — provides discovery tools.
   - `finance-tools-only-plugin.zip` — provides the worked-example `invoice_extract`.
2. In Cowork → Customize → enable both connectors against a test agent.
3. Try:
   - *"What skills do we have for invoice processing?"*
   - *"Use the registry to find a skill that extracts invoices, describe it, then call the bound tool with this document URL …"*

**Note on packaging:** install both plugins (not the legacy combo
`cowork-plugin/`). Cowork's runtime de-duplicates connectors that share a host
even if their paths differ — the split is what makes both endpoints addressable
in the same conversation.

## Status

| Stage | What | State |
|---|---|---|
| **1 — Register** | Manifest schema, CI validation, duplicate-cap scan, CODEOWNERS, PR template | **Live.** Every PR runs [`.github/workflows/validate-manifests.yml`](.github/workflows/validate-manifests.yml) (45 tests across lite + full + MCP server). |
| **2 — Publish catalog** | Public read-only `catalog.json` blob in Azure Storage, refreshed by a GitHub Action | **Planned.** Bicep + plan ready, nothing deployed. See [`docs/stage-2-plan.md`](docs/stage-2-plan.md). |
| **3 — Cowork plugin spike** | Registry surfaced as MCP plugin inside Microsoft Copilot Cowork | **Live and proven end-to-end (2026-06-29).** Both shapes confirmed: (a) registry discovery + cross-connector composition for `invoice.extract`, and (b) registry-as-library for `legal.redline` producing a real `MSA_UK_EU_Draft.docx` deliverable at ~483 credits, reproducible across runs. Constraints documented in [`docs/cowork-plugin-limitations.md`](docs/cowork-plugin-limitations.md). |
| **4 — Copilot Studio at scale** | Composition Layer of the four-layer model | **Deferred** until Stage 2 has real consumers. |

Target platform when Stage 4 ships: Microsoft Fabric IQ (Ontology, Preview),
OneLake, and Copilot Studio custom engine agents, with GitHub as the skill
system-of-record.

## What we learned from the live Cowork test

The spike's main result is that the **missing-middle pattern survives contact
with Cowork's runtime**, with three non-obvious findings:

1. **One MCP host per plugin** — Cowork dedups connectors that share a host
   even on different paths, so each MCP server gets its own plugin package.
2. **Read-only by default in Cowork** — write-side tools (e.g.
   `submit_skill_draft`) are filtered out of the agent's tool list at runtime;
   write paths need a separate channel (CLI, GitHub Action, separately-authed
   connector).
3. **Inline SKILL.md content unlocks "registry-as-library"** — Cowork
   doesn't natively resolve `skill://` URIs, so the first cut of
   `describe_skill` (which returned only URIs) limited Pattern B to *describing*
   a skill. Inlining text payloads as `content` in `payloadFiles[]` (text/markdown
   + JSON ≤64 KB) is what lets the agent read the SKILL.md body in the same call
   and then execute via Cowork's own docx/file/web tools to produce real
   deliverables. Reproduced twice with `legal/msa-redlining` → `MSA_UK_EU_Draft.docx`.

Inside those constraints, both loops — *agent asks the registry who can do X,
gets a binding, calls the bound tool on a different connector* AND *agent asks
the registry who can do Y, gets inlined SKILL.md, follows it with its own
tools* — work in production Cowork against a real Azure Container App.
Per-loop context cost is ~6–8 KB for the discovery-only path; full E2E
docx-producing path measured at ~483 Copilot Credits. Approval friction
(a modal per tool call) is the largest open UX issue.

## Prior art and how we differ

We learned from **MCP** (transport + tool contract), **OWL-S / WSMO** (IOPE
matchmaking), **MLflow Model Registry** (staged graduation), and **RPA CoEs**
(governance gates). We differ in one specific bet: we treat the **ontology as
an agent-maintained artifact**, not a hand-curated one. That bet is isolated
behind a measurable contract — see
[`docs/ontology-builder-agent.md`](docs/ontology-builder-agent.md) and
[`docs/prior-art.md`](docs/prior-art.md).

## Contributing

New contributors: read [`CONTRIBUTING.md`](CONTRIBUTING.md). The Register gate
is enforced on every PR by CI + CODEOWNERS; the Certify gate is enforced by
human review against the criteria in [`docs/architecture.md`](docs/architecture.md).

## Licence + acknowledgements

Patterned on the proven
[TomTom Map Cowork POC](https://github.com/ITSpecialist111/CopilotStudio_TomTom_Map_MCP_POC)
for the Teams app manifest v1.28 + remote MCP server envelope.
