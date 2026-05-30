# Architecture

> The construct: a **repeatable chassis** that moves an individual **Skill** into an
> org-wide **Agent** capability — without rebuilding it as a bespoke custom agent each
> time. This document describes the four-layer model, the graduation pipeline (the
> process/flow), the target platform, and how the parts bolt together.

See also: [`technical-spec.md`](technical-spec.md) (the Manifest frame),
[`ontology-schema.md`](ontology-schema.md) (the meaning model),
[`ontology-builder-agent.md`](ontology-builder-agent.md) (the load-bearing component),
[`prior-art.md`](prior-art.md) (what we learned from and how we differ),
[`roadmap.md`](roadmap.md) (phases + the falsifiable bet).

## Design verdict

We have **enough learnings to build the chassis**, not enough to claim it is proven. The
chassis is therefore designed so the one unproven bet — a **self-maintaining ontology** —
is **isolated and measurable**, behind a human-in-the-loop gate, rather than assumed.

| Question | Confidence | Source |
|---|---|---|
| What a skill→agent graduation pipeline looks like | High | MLflow Model Registry, RPA CoE graduation gates |
| How to store/govern/discover capabilities | High | MCP Registry + Copilot Studio / OneLake |
| What the meaning layer should model | High | OWL-S / WSMO IOPE + capability matchmaking |
| Will an agent-maintained ontology survive at scale? | **Open bet** | No prior art succeeded — this is what we prove |
| What "Skill" precisely means | Needs care | Disambiguated in [`prior-art.md`](prior-art.md) |

## The construct in three nested parts

- **Part A — The Manifest.** One declarative spec that every skill carries, so the same
  unit travels every stage unchanged. It is the chassis *frame*. Defined in
  [`technical-spec.md`](technical-spec.md); schema at
  [`../schemas/skill-manifest.schema.json`](../schemas/skill-manifest.schema.json).
- **Part B — The Pipeline.** A fixed set of stage gates every skill passes through. The
  flow is identical for every skill — that is what makes it a chassis, not a bespoke build.
- **Part C — The Ontology Builder Agent.** The agentic code that keeps the meaning layer
  in sync. Isolated as a replaceable component with a measurable contract. See
  [`ontology-builder-agent.md`](ontology-builder-agent.md).

## The four-layer architecture

```
┌────────────────────────────────────────────────────────────┐
│  Composition Layer   — a CAPPED number of org agents        │
│                        compose certified skills at runtime  │
├────────────────────────────────────────────────────────────┤
│  Reasoning Layer     — "which skill answers this need?"     │
│                        graph queries + capability matchmaking│
├────────────────────────────────────────────────────────────┤
│  Meaning Layer       — Ontology / knowledge graph           │
│   (Fabric IQ)          Skill · Capability · Agent · Scope   │
├────────────────────────────────────────────────────────────┤
│  Storage / Governance — MCP-compatible registry + manifests │
│   (OneLake + GitHub    + telemetry, lineage, RBAC, audit,   │
│    + MCP Registry)       versioning, cost                   │
└────────────────────────────────────────────────────────────┘
        ▲
        │  Ontology Builder Agent (the "agentic code")
        └─ keeps the meaning layer in sync automatically
```

We centralise **three things**: capabilities (the tools/skills), meaning (the ontology),
and trust (identity, audit, cost, lifecycle). We **cap the number of agents** and **grow
the registry**; agents compose from it. Building 10,000 agents is the anti-pattern — that
is shadow IT with an LLM on top.

## Part B — the graduation pipeline (the repeatable process/flow)

Every skill passes through the same six gates. Each gate has explicit **entry** and
**exit** criteria, so the flow is repeatable for any skill regardless of domain. The
`lifecycle.stage` field in the Manifest records exactly where a skill sits.

| # | Gate | Entry criteria | What happens | Exit criteria (`stage`) |
|---|---|---|---|---|
| 1 | **Register** | A manifest exists | Skill submitted to the registry | `draft` → `registered` |
| 2 | **Certify** | `registered` | Automated checks (schema valid, determinism/risk scored, duplicate-capability detection) **+ human approval** | `registered` → `certified` (sets `certifiedBy`/`certifiedAt`) |
| 3 | **Publish** | `certified` | Promoted into the governed, MCP-compatible catalog | `certified` → `published` |
| 4 | **Meaning-sync** | `published` | Ontology Builder Agent ingests the manifest, proposes entities/relationships, flags duplicates/conflicts to a review queue | Ontology updated (no stage change) |
| 5 | **Compose** | `published` + in ontology | A capped set of org agents query the ontology and compose certified skills at runtime | Runtime use |
| 6 | **Retire / version** | `published` | Lifecycle + lineage tracking; supersede or retire | `deprecated` / `retired` (sets `supersededBy`) |

A worked example of a single skill traveling all six gates is in
[`graduation-walkthrough.md`](graduation-walkthrough.md).

### Stage model (mirrors MLflow + RPA CoE)

```
draft ─Register▶ registered ─Certify(+human)▶ certified ─Publish▶ published
                                                                      │
                                          Meaning-sync ◀──────────────┤
                                          Compose      ◀──────────────┤
                                                                      ▼
                                                       deprecated ─▶ retired
```

## Target platform

| Layer | Target component | Role |
|---|---|---|
| Storage / Governance | **GitHub** (system-of-record for manifests) + **OneLake** (telemetry/lineage) + **MCP Registry** (discovery) | Versioning, RBAC, audit, cost, discovery |
| Meaning | **Microsoft Fabric IQ** (Ontology, Preview) | Knowledge graph of Skill/Capability/Agent/Scope |
| Reasoning | Graph queries + data agents over Fabric IQ | Capability matchmaking |
| Composition | **Copilot Studio** custom engine agents (capped) | Runtime composition of certified skills |

## Guardrails (baked into the chassis)

1. **Ride MCP** for storage/discovery/governance — do not rebuild it. Spend the novelty
   budget on meaning.
2. **Human approval gate is mandatory** at Certify — hybrid beat full automation in every
   prior attempt (OWL-S/WSMO, RPA CoE).
3. **Cap agents, grow the registry** — enforced at the Compose stage.
4. **Lead with the Ontology Builder Agent** — it is the explicit answer to why
   hand-maintained ontologies historically died.
