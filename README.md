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
| [`docs/intake.md`](docs/intake.md) | The intake layer: turning real `SKILL.md` folders into draft manifests (the on-ramp to Register) |
| [`docs/packaging.md`](docs/packaging.md) | How the prototype is packaged into an installable, persistent, deployable product (CLI + API + storage + CI/CD) |
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
six-gate pipeline state machine, the Ontology Builder Agent contract, and the
**intake** on-ramp that turns real `SKILL.md` folders into draft manifests) plus
smoke tests lives in [`prototype/`](prototype). It is packaged as an installable
product — a **Skill Registry & Graduation service** with a `chassis` CLI, durable
storage (SQLite), an optional HTTP/MCP API, container deployment, and CI — built
*behind* the stable Manifest / six-gate / Ontology-Builder contracts. See
[`docs/packaging.md`](docs/packaging.md). Quick start:

```bash
cd prototype
pip install -e '.[dev]' && python -m pytest -q     # install + test
chassis walkthrough                                 # six-gate demo
chassis register ../examples/invoice-extract.manifest.json --db sqlite:///registry.db
chassis serve --db sqlite:///registry.db            # HTTP/MCP API (needs the api extra)
```

## Status

Concept / architecture phase, with an installable reference product. Targets
Microsoft Fabric IQ (Ontology, Preview), OneLake, and Copilot Studio custom
engine agents, with GitHub as the skill system-of-record.
