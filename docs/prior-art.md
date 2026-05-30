# Prior Art & How We Differ

> The chassis is grounded in four bodies of prior work. None published this exact framing
> — a graduation pipeline that promotes individual Skills into a *small, capped* number of
> org agents, governed by a capability registry plus an **agent-maintained** ontology — but
> almost every component has strong precedent. This document records what we learned from
> each and where we deliberately differ.

## 1. MCP Registry — storage, discovery, governance (solved; we ride it)

The **Model Context Protocol** (Anthropic, late 2024; donated to the Linux Foundation's
Agentic AI Foundation in 2025) and its registries (official, GitHub, and private/enterprise
catalogs such as Kong's) already provide a canonical capability catalog: verified
namespaces, publish/discover APIs, RBAC/OAuth, audit, and private enterprise mirrors. As of
2025 the ecosystem has thousands of servers.

- **Learned:** capability storage, discovery, RBAC, audit and versioning are a **solved,
  standardized problem**.
- **How we differ:** we do **not** rebuild this. Our registry **is** an MCP-compatible
  catalog (`mcp.*` fields in the Manifest). MCP has **no semantic/ontology reasoning
  layer** — that gap is exactly where we spend our novelty budget.

## 2. OWL-S / WSMO — semantic discovery & composition (the cautionary tale)

In 2003–2007 the Semantic Web Services community (OWL-S, WSMO/WSMX, Paolucci et al.
capability matchmaking) built essentially our Reasoning + Meaning layers: ontology-described
capabilities via **IOPE** (Inputs, Outputs, Preconditions, Effects), automatic discovery,
composition as AI planning, and graded matchmaking (Exact / Plug-in / Subsume / Fail).

- **Learned (the failure modes that matter most to us):**
  - **Hand-maintained ontologies died** — too costly to author and keep current.
  - **Reasoning didn't scale** — description-logic inference over large registries was
    expensive.
  - **Full automation never replaced humans** — hybrid won.
  - **Heavyweight standards lost to lightweight ones** (schema.org, OpenAPI, now MCP).
- **How we differ:**
  - We adopt **IOPE** and matchmaking grades (see [`ontology-schema.md`](ontology-schema.md))
    but keep the ontology **lightweight and query-first**, not inference-heavy.
  - We answer the fatal maintenance cost head-on with the **Ontology Builder Agent**
    ([`ontology-builder-agent.md`](ontology-builder-agent.md)) — and we treat it as an
    explicit, measured **bet**, not a solved fact.
  - We keep a **mandatory human gate** because hybrid beat automation every time.

## 3. MLflow Model Registry — the graduation pattern (we copy it)

MLflow's Model Registry (and feature stores) established the canonical "register → stage →
approve → promote to production" lifecycle with lineage.

- **Learned:** a staged registry with explicit promotion gates and lineage is a proven way
  to move artifacts from personal to production.
- **How we differ:** we apply it to **skills→agents**, with stages
  `draft → registered → certified → published → deprecated → retired` and a mandatory
  human approval at Certify (see [`technical-spec.md`](technical-spec.md)).

## 4. RPA Citizen-Developer Centers of Excellence — the governance template

RPA / Power Platform CoEs already lived our "Access database" analogy: powerful local
automations that must be inventoried, governed, and selectively promoted.

- **Learned:** central **inventory + mandatory registration** kills shadow IT; **quality
  gates + selective graduation** work; **not everything should graduate** — promote by
  business impact/risk.
- **How we differ:** this directly supports **"cap the agents, grow the registry"** — we
  bake the "no 10,000 agents" stance into the Compose stage and use risk/determinism
  scoring to decide what graduates.

## 5. Disambiguating "Skill" (terminology hygiene)

The word "Skill" is overloaded. The Manifest's `identity.skillType` field forces an explicit
choice:

| `skillType` | What it means | Source |
|---|---|---|
| `anthropic-agent-skill` | Folder + `SKILL.md`, progressive disclosure; in-model "how we do it here" knowledge | Anthropic Agent Skills |
| `mcp-tool` | A tool exposed by an MCP server; reaches **external** systems | Model Context Protocol |
| `copilot-skill` | A Copilot Studio / Copilot reusable skill | Microsoft Copilot |
| `deterministic-tool` | A pure, deterministic function/tool | This project's core unit |
| `composite` | A skill composed of other skills | This project |

- **Industry consensus:** Anthropic Skills and MCP are **complementary layers** — Skills
  encode *how work is done here*, MCP *reaches the outside world*. Our "Skill" sits closest
  to a deterministic tool / Anthropic Skill; our registry is MCP-compatible so both fit.

## Summary: crowded vs. novel

| Concern | Status | Our stance |
|---|---|---|
| Capability storage, discovery, RBAC, audit | **Solved** (MCP, Copilot Studio) | Adopt, don't rebuild |
| Ontology-driven discovery & composition | **Scarred** (OWL-S/WSMO stalled) | Adopt IOPE, go lightweight + query-first |
| Graduation pipeline | **Proven** (MLflow, RPA CoE) | Copy the stage-gate pattern |
| **Agent-maintained ontology** | **Open bet** | The novelty — isolated & measured |
| **Cap agents, grow registry** | **Supported** (RPA CoE) | Explicit anti-pattern stance vs. "build 10,000 agents" |
