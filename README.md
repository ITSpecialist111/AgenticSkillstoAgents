# AgenticSkillstoAgents

> Closing the missing middle between individual **Skills** and org-wide **Agents**.

## The problem

Modern AI tooling (GitHub Copilot, Copilot "Cowork", Copilot Studio, ClawPilot-style
setups) gives individuals the power to build **Skills** — repeatable processes wired to
deterministic tools. This is brilliant for the individual, but it stops there.

There are two stable end-states today, and **nothing in between**:

| | Individual Skill | Custom Engine Agent |
|---|---|---|
| **Owner** | One person (maker) | Org / platform team |
| **Reuse** | Personal, copy-paste | Centrally deployed, multi-user |
| **Determinism** | High (deterministic tools) | Variable (LLM orchestration) |
| **Governance** | None | Full (RBAC, audit, lifecycle) |
| **Cost to build** | Minutes | Weeks + a platform team |

A Skill makes a process **repeatable**. But unless it is shared, it stays a **singular
solution**. To make it org-wide today you must rebuild it as a full custom engine agent —
a large, manual leap most ideas never survive.

### The Access-database analogy

This is the **Access database era** all over again. Skills are the new Access DBs:
powerful, local, repeatable — and invisible, ungoverned, and un-scalable. The historical
fix was **centralisation**: Access → SQL Server → OneLake.

But the naive "agent version" of that fix — **build 10,000 agents** — is wrong. That is
just shadow IT with an LLM on top. We did not solve Access by giving everyone their own
SQL Server; we **centralised the data and the meaning**.

## The thesis

The missing middle is **not a new kind of agent**. It is a **graduation pipeline** built
on top of a **shared, governed capability registry** and — critically — a **semantic
(ontology) layer** that lets a *small number* of agents reason over a *large pool* of
governed skills.

We centralise **three things**, not one:

1. **Capabilities** — the deterministic tools/skills themselves (storage + governance).
2. **Meaning** — what each skill *is* and how it relates (the **ontology**).
3. **Trust** — identity, audit, cost, lifecycle.

Cap the number of agents. Grow the registry. Let agents **compose** from it.

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

## The keystone: an Ontology Builder Agent

Hand-maintained ontologies die. The thing that makes this real is **agentic code that
builds and maintains the ontology for you** — reading skill manifests, proposing entities
and relationships, scoring determinism/risk, and detecting duplicate capabilities. See
[`docs/ontology-builder-agent.md`](docs/ontology-builder-agent.md).

## Documents

| Doc | What it covers |
|---|---|
| [`docs/architecture.md`](docs/architecture.md) | Four-layer model, the six-gate graduation pipeline, target platform, components |
| [`docs/ontology-schema.md`](docs/ontology-schema.md) | Entity-relationship model for skills/capabilities/agents (IOPE) |
| [`docs/ontology-builder-agent.md`](docs/ontology-builder-agent.md) | The agentic code that builds/maintains the ontology — and the measurable bet |
| [`docs/technical-spec.md`](docs/technical-spec.md) | True technical spec: the canonical Manifest, state machine, APIs, build |
| [`docs/roadmap.md`](docs/roadmap.md) | Phased graduation pipeline, milestones, success metrics |
| [`docs/prior-art.md`](docs/prior-art.md) | What we learned from MCP / OWL-S / MLflow / RPA CoEs and how we differ |
| [`docs/graduation-walkthrough.md`](docs/graduation-walkthrough.md) | A worked example: one skill traveling all six gates |

## The construct (the repeatable chassis)

The construct is delivered as **specifications + a canonical manifest + a worked example**
— three nested parts:

- **Part A — The Manifest:** one declarative spec every skill carries so the same unit
  travels every stage unchanged. Schema:
  [`schemas/skill-manifest.schema.json`](schemas/skill-manifest.schema.json); validated
  examples: [`examples/`](examples).
- **Part B — The Pipeline:** six fixed stage gates (Register → Certify → Publish →
  Meaning-sync → Compose → Retire) identical for every skill. See
  [`docs/architecture.md`](docs/architecture.md).
- **Part C — The Ontology Builder Agent:** the load-bearing, **unproven** part — isolated
  with a measurable contract behind a human gate. See
  [`docs/ontology-builder-agent.md`](docs/ontology-builder-agent.md).

## Prototype

An executable reference implementation of the chassis (manifest validation, the
six-gate pipeline state machine, and the Ontology Builder Agent contract) plus
smoke tests lives in [`prototype/`](prototype). Run it with
`cd prototype && pip install -r requirements.txt && python -m pytest -q`, or try
`python -m chassis.cli walkthrough`.

A deliberately minimal counter-implementation — the same manifest and example
skills, but in **one 178-line file** with no agent and no graph — lives in
[`prototype-lite/`](prototype-lite). The rationale for keeping both, and the
promotion criteria for graduating from lite to the full chassis, are in
[`docs/complexity-review.md`](docs/complexity-review.md).

## Status

**Stage 1 (Register gate) — live.** Every PR that touches a manifest runs
[`.github/workflows/validate-manifests.yml`](.github/workflows/validate-manifests.yml):
schema validation, the lite + full + MCP-server test suites (45 tests), and a
duplicate-capability scan. CODEOWNERS + the PR template enforce the Certify gate
on the human side. New contributors follow [`CONTRIBUTING.md`](CONTRIBUTING.md).

**Stage 2 (published catalog) — planned, not deployed.** A ready-to-deploy
Bicep template lives at [`infra/stage-2/main.bicep`](infra/stage-2/main.bicep)
and the full plan (resources, cost < £0.05/mo, exact commands) is in
[`docs/stage-2-plan.md`](docs/stage-2-plan.md). Nothing in Azure has been
created.

**Cowork plugin spike — built, not yet deployed.** A Microsoft Copilot Cowork
plugin that surfaces the registry as three read-only MCP tools (`find_skill_by_capability`,
`describe_skill`, `list_capabilities`) lives in [`cowork-plugin/`](cowork-plugin),
backed by an MCP server in [`mcp-server/`](mcp-server) and a Container Apps
Bicep template in [`infra/stage-3/main.bicep`](infra/stage-3/main.bicep).
Full spec: [`docs/cowork-plugin-spike.md`](docs/cowork-plugin-spike.md).
Patterned on the proven [TomTom Map Cowork POC](https://github.com/ITSpecialist111/CopilotStudio_TomTom_Map_MCP_POC).

Stage 4 (Copilot Studio integration at scale) is intentionally deferred until
the Stage 2 catalog has real consumers and the Cowork spike has cleared a live
test in the ABS tenant. Target platform when it ships: Microsoft Fabric IQ
(Ontology, Preview), OneLake, and Copilot Studio custom engine agents, with
GitHub as the skill system-of-record.
