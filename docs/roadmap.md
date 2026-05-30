# Roadmap

> A phased graduation pipeline that grows the registry while keeping the number of agents
> capped — and, critically, **encodes the falsifiable bet**: does an agent-maintained
> ontology actually beat hand-curation? Each phase has an exit gate; the program does not
> advance until the gate is met.

## Guiding constraints

- **Cap agents, grow the registry.** Success is measured by registry breadth and reuse,
  not agent count.
- **Prove the keystone.** The Ontology Builder Agent
  ([`ontology-builder-agent.md`](ontology-builder-agent.md)) is the one unproven bet; every
  phase tightens its measurement.
- **Ride MCP; don't rebuild it.** See [`prior-art.md`](prior-art.md).

## Phase 0 — Frame (this repository)

**Goal:** a repeatable chassis on paper: spec + schema + worked example.

- [x] Canonical Manifest schema ([`../schemas/skill-manifest.schema.json`](../schemas/skill-manifest.schema.json)).
- [x] Example manifests, validated ([`../examples/`](../examples)).
- [x] Architecture, ontology schema, builder-agent contract, technical spec.
- [x] Worked six-gate walkthrough ([`graduation-walkthrough.md`](graduation-walkthrough.md)).

**Exit gate:** a reader can take a new skill and produce a valid manifest unaided.

## Phase 1 — Registry + Certify (manual meaning)

**Goal:** the pipeline runs end-to-end with a **hand-maintained** ontology, to establish
the baseline the agent must beat.

- Manifests stored in GitHub; PR review **is** the Certify human gate.
- Automated checks: schema validation, dependency resolution, determinism/risk scoring.
- MCP-compatible publish step.
- Ontology curated **by hand** — deliberately, to capture the baseline cost.

**Exit gate:** ≥ 20 skills published; baseline **maintenance effort** (human minutes per
100 skills) recorded.

## Phase 2 — Ontology Builder Agent (the experiment)

**Goal:** introduce the agent at the Meaning-sync gate behind human review and measure it
against the Phase 1 baseline.

- Agent proposes entities/relationships + confidence + duplicate/conflict flags.
- Human-in-the-loop review queue; low-risk/high-confidence auto-merge only.

**Exit gate (the falsifiable bet):**

| Metric | Target |
|---|---|
| Proposal acceptance rate | ≥ 80% accepted unchanged |
| Duplicate-detection precision | ≥ 0.9 |
| Duplicate-detection recall | ≥ 0.7 |
| Maintenance effort | < 50% of Phase 1 hand-curation baseline |
| Ontology drift | < 5% of skills stale > 7 days |

**If the gate is missed, the bet is not yet won:** the agent is iterated or replaced (the
contract makes it swappable) before proceeding. The program does **not** pretend the
ontology is self-maintaining until these numbers hold.

## Phase 3 — Reasoning + capped Composition

**Goal:** a small number of org agents compose certified skills at runtime via graph
queries.

- Capability matchmaking queries (Exact/Plug-in/Partial/Fail).
- Agent cap enforced; agents bind to **capabilities**, not individual skills.
- Cost-aware selection among equivalent skills.

**Exit gate:** ≥ 100 skills, ≤ a fixed small number of agents, with measured **reuse**
(skills composed by more than one agent) trending up.

## Phase 4 — Scale + lifecycle

**Goal:** lineage, deprecation, cost governance at scale.

- Supersede chains, retirement, telemetry-driven pruning.
- Continuous re-measurement of Phase 2 metrics at 10× volume.

**Exit gate:** Phase 2 metrics hold at 10× skill volume (the real scale test that OWL-S
failed).

## Success metrics (program-level)

| Dimension | Metric |
|---|---|
| Breadth | # published skills, # distinct capabilities |
| Reuse | avg. agents composing each capability; copy-vs-reuse ratio |
| Restraint | agent count (must stay capped) |
| Meaning health | proposal acceptance, duplicate precision/recall, drift |
| Cost | maintenance effort vs. hand-curation baseline |
| Trust | % skills with complete governance + audit metadata |

## Status

Concept / architecture phase (Phase 0 complete). Targets Microsoft Fabric IQ (Ontology,
Preview), OneLake, MCP registries, and Copilot Studio custom engine agents, with GitHub as
the skill system-of-record.
