# Roadmap — 2026 Q3

> Written 2026-06-28 in response to Graham's prompt: *"Could we have something
> Microsoft WorkIQ for agentic understanding and processing of the skills?
> Would like to have something like this for the future."*
>
> Audience: Graham, returning next session to pick a stage. Companion to
> [`handoff.md`](handoff.md) (state) and [`roadmap.md`](roadmap.md) (the
> longer phased view). This doc is the quarter-scoped slice.

## 1. What "Microsoft WorkIQ" means

It almost certainly means **Work IQ** — Microsoft's workplace intelligence
layer for Microsoft 365 Copilot and Agent 365 (preview, GA path actively
shipping). One word, two layers: a *concept* and an *API surface*.

- **The concept.** Work IQ is described as "the intelligence layer that
  grounds Microsoft 365 Copilot and your agents in real-time, shared
  context across your organization." Three layers: **Data** (signals across
  M365 — mail, calendar, files, chats), **Memory / Context** (persistent
  understanding of how people and teams work), and **Skills & Tools /
  Inference** (the things agents actually call).
  <https://learn.microsoft.com/microsoft-365/copilot/extensibility/work-iq>
- **The API surface.** A remote MCP server, an A2A endpoint, and a REST
  API. The Work IQ MCP is the load-bearing piece — it collapses *hundreds*
  of M365 operations into **10 generic tools** (`fetch`, `create_entity`,
  `update_entity`, `delete_entity`, `do_action`, `call_function`, `ask`,
  `list_agents`, `get_schema`, `search_paths`). Resource *paths* identify
  what; tools are the verbs. Two design principles worth memorising:
  *"Fewer tools, more paths"* and *"Introspection over enumeration."*
  <https://learn.microsoft.com/microsoft-365/copilot/extensibility/work-iq/mcp/overview>
- **The family.** Work IQ sits inside **Microsoft IQ** alongside **Fabric
  IQ** (business-entity context, the ontology workload we already cite),
  **Foundry IQ** (authoritative-docs context), and **Web IQ**. Work IQ is
  the one most agents in Copilot Studio see; Fabric IQ Ontology is the one
  with a knowledge-graph shape closest to ours.
  <https://learn.microsoft.com/microsoft-copilot-studio/agents-experience/use-microsoft-iq>

**Candidate disambiguation.** There is also **Viva Insights** (workplace
analytics — meeting load, focus time, Copilot adoption dashboards). The
phrase "WorkIQ" appears nowhere in Viva docs; Viva's "intelligence" framing
is people-analytics, not agent grounding. Given the user said *"agentic
understanding and processing of the skills"*, the Work IQ family is the
match. Viva Insights is the wrong target: it answers *"how is the workforce
spending time?"*, not *"what does this skill mean and when should an agent
reach for it?"*.

## 2. How Work IQ relates to this project

Not a replacement. Not a consumer. **An adjacency we should consciously
mirror in one place and consciously deconflict from in another.**

| Layer of theirs | Layer of ours | Relationship |
|---|---|---|
| Work IQ MCP (10 generic tools, paths) | `mcp-server/server.py` (3 read-only tools) | **Mirror the design**: keep our tool count tiny, push variability into resource paths/inputs, not into new tools. |
| Work IQ Data + Context | Manifest + ontology graph | **Distinct**. Theirs is "how people work"; ours is "what skills exist and what they mean". The two are complementary, not overlapping. |
| Work IQ Skills (Business skills, Dataverse) | Our Skill manifests | **Same word, different scope**. Their "skill" = a NL instruction layer over Dataverse/M365. Ours = a registered, governed, deterministic capability with IOPE. Do not conflate them — call ours **Capability Skills** when speaking to anyone Microsoft-fluent. |
| Fabric IQ Ontology MCP | Our future ontology MCP tool | **Pattern to copy.** Their Fabric IQ Ontology MCP server exposes "query organizational knowledge graphs to discover entities and relationships." That is exactly what our `prototype/out/ontology.json` should expose once it's served. |
| Work IQ Memory | (nothing today) | **Future surface.** Memory of which skills succeeded/failed/were-skipped is the agentic-understanding layer the user is asking about. See §4. |

The honest framing for a stakeholder conversation: *"This registry is a
domain-specific IQ — Skill IQ — that sits next to Work IQ and Fabric IQ. It
grounds agents in the org's deterministic capabilities the same way Work IQ
grounds them in M365 signals."*

## 3. The next five stages (priority order)

Where the repo actually is, 2026-06-28: Stage 1 live (Register gate in CI),
Stage 2 planned (Blob catalog Bicep ready), Cowork spike merged (3-tool MCP
server + Container Apps Bicep), with steps 2+3 of the spike in flight —
MCP **resources** for skill payloads and a `submit_skill_draft` tool that
opens PRs. The next five stages assume those finish.

### Stage A — Ship Stage 2 (Blob catalog) and wire the MCP server to it

(a) **Goal.** Get a single authoritative `catalog.json` in Azure Blob,
auto-published on every merge to `main`, and switch
`REGISTRY_CATALOG_MODE=remote` on the MCP server.

(b) **Missing-middle thesis it advances.** Centralising the **storage** of
capabilities (layer 1 of the four-layer model). Without this, every
consumer parses GitHub or bundles examples — the registry is not really
shared.

(c) **Success criterion.** A second machine (a Container App, a local
laptop, anything) can read the catalog without cloning the repo, and the
catalog updates within five minutes of a merge.

(d) **Effort.** Half a day. Bicep is written. Workflow is not — but
follows the existing `validate-manifests.yml` shape. The one moving part
is the GitHub OIDC federated credential (one portal click).

### Stage B — Live-test the Cowork plugin in the ABS tenant

(a) **Goal.** Deploy the MCP server to Container Apps (Stage 3 Bicep),
upload the Teams plugin zip to ABS, install it into one Cowork agent,
prove an end-to-end discovery query works.

(b) **Missing-middle thesis it advances.** Proves the **switchboard** —
the registry as a discoverable plugin rather than a repo to clone. This is
the unlock for "any number of agents, capped agents, grow the registry."

(c) **Success criterion.** A Cowork agent in ABS answers *"what skills do
we have for invoice processing?"* by calling `find_skill_by_capability`
and returning a real `SkillSummary[]`. Screen recording + one
[`docs/`](.) note is enough.

(d) **Effort.** Half a day for the deploy + plugin upload, plus whatever
tenant-admin queueing is needed in ABS. Risk is organisational, not
technical.

### Stage C — Add a second real skill from outside the maker

(a) **Goal.** Have someone other than Graham contribute a manifest through
the CONTRIBUTING.md flow. Stress-test CODEOWNERS, the PR template, the
Certify gate, the duplicate-capability scan.

(b) **Missing-middle thesis it advances.** Phase 1's exit gate from
[`roadmap.md`](roadmap.md) — *"≥ 20 skills published; baseline maintenance
effort recorded."* We are at three (the bundled finance examples). One
external contribution is the smallest experiment that breaks symmetry.

(c) **Success criterion.** A merged PR from a non-`@ITSpecialist111`
author, with a manifest that resolves cleanly through `lite.py validate`
and `lite.py dupes`. Bonus: the contributor writes a one-paragraph
postmortem of where the docs were unclear.

(d) **Effort.** One conversation. Code work is minutes. The hard part is
finding the right person inside ABS.

### Stage D — Skill IQ MCP: an ontology-query tool on top of Stage 2

(a) **Goal.** Add a fourth MCP tool to `mcp-server/`:
`query_ontology(seed_capability, relation, depth)` that returns the
neighbourhood of a capability in the graph. Backed by
`prototype/out/ontology.json` (which the chassis already builds).

(b) **Missing-middle thesis it advances.** This is where the **reasoning
layer** starts. Today an agent can ask *"who can do X?"* (one hop). With
this it can ask *"if I need `ap.intake`, what chain of capabilities does
that compose into, and which conditions must hold?"* — i.e. the
matchmaking query from [`ontology-schema.md`](ontology-schema.md) made
callable.

(c) **Success criterion.** A Cowork agent calls
`query_ontology(seed="ap.intake", relation="DEPENDS_ON", depth=2)` and
gets back the `invoice-extract → po-match` chain that
`graduation-walkthrough.md` describes by hand. Three unit tests; one
end-to-end test against the deployed Container App.

(d) **Effort.** Two days. The graph is already built (`ontology.mmd`,
`ontology.json`). The work is: a tiny graph-query helper in
`prototype-lite/` or `prototype/`, an MCP tool wrapper, and skill-card
copy for `cowork-plugin/`.

### Stage E — Telemetry loop: record which skills get found, picked, succeeded

(a) **Goal.** Add a single append-only telemetry table — one row per MCP
call from any agent: `{timestamp, agent_id, tool_name, args_hash, result,
latency_ms}`. Land it in OneLake (preferred) or App Insights (faster).
Build one Grafana/Power BI panel that shows, per capability, how often it
is *found*, how often the agent *describes* it next (a proxy for "pick"),
and which capabilities are dark (no traffic for N days).

(b) **Missing-middle thesis it advances.** The **observability** half of
the meaning layer. Today the chassis is open-loop. Telemetry is what makes
the Ontology Builder Agent's Phase 2 exit-gate metrics
(`acceptance rate`, `drift < 5%`, `duplicate precision/recall`) actually
measurable on real data instead of synthetic harnesses.

(c) **Success criterion.** Two weeks of real traffic with at least three
distinct agents calling at least five distinct capabilities, summarised in
one dashboard. The graph view of "dark capabilities" highlights at least
one skill that should be retired or renamed.

(d) **Effort.** Three to four days. Telemetry sink: half a day.
Dashboard: a day. The rest is the patience of waiting for usage. Cannot
start until Stage B is real, because synthetic traffic teaches nothing.

### Why this order

A is infra-blocking — nothing else is real without it. B is the
ABS-political milestone that justifies all subsequent effort. C is the
cheapest way to break the toy-project smell. D is the first piece of
genuinely new agentic behaviour and the spiritual sibling of Fabric IQ
Ontology MCP. E is the only honest way to prove or kill the ontology bet.

## 4. The "Work IQ for skills" hypothesis

The user's actual question is the most interesting one in the doc and
deserves the most direct answer.

**Claim.** The ontology layer should grow from a static graph (what
exists, how it links) into an **agentic layer** that reasons about
*usage*, *governance attention*, and *combination outcomes*. Borrow Work
IQ's three-layer shape — **Data, Memory, Inference** — and apply it to
skills:

- **Data.** Already partly there: the manifests are the data. Add
  telemetry (Stage E) and the data layer is complete.
- **Memory.** A new artefact: a rolling state of *which skills are used
  by whom, in what combinations, with what success rates, against what
  preconditions*. Stored in OneLake; the unit of memory is a
  *capability-invocation episode*, not a manifest.
- **Inference.** New agentic behaviours exposed as MCP tools (so the
  registry continues to be a switchboard, not an executor). See below.

### Three concrete agentic behaviours

Map onto the existing ontology shape — `Skill / Capability / DataType /
Condition` with `PROVIDES / CONSUMES / PRODUCES / REQUIRES / CAUSES` (see
[`prototype/out/ontology.mmd`](../prototype/out/ontology.mmd) and
[`docs/ontology-schema.md`](ontology-schema.md)).

#### 1. `suggest_compose(goal_capability)` — composition reasoning

> *"To get `ap.intake` I need something that PRODUCES `InvoiceFields` and
> something that CONSUMES it and PROVIDES `invoice.match`. Here is a chain
> with confidence 0.94. The chain's REQUIRES set is `{document.readable,
> erp.reachable, user.authenticated}` — check these before invoking."*

Pure graph traversal over `PRODUCES → CONSUMES` chains, with `REQUIRES`
roll-up. No LLM needed for the algorithm — but an LLM is useful to render
the result as natural language to the requesting agent. This is the
DataType-chaining rule from `ontology-schema.md` made callable.

**Surfaces as.** New MCP tool on the existing server. No new infra.

#### 2. `governance_attention()` — duplicate / drift / orphan flagging

> *"Three capabilities (`invoice.extract`, `invoice.parse`,
> `document.invoice`) have ≥ 0.8 semantic similarity but distinct
> manifests. One has had 47 calls in 30 days; the others have had zero.
> Recommend: merge tags, promote the used one, deprecate the others."*

Combines (i) the duplicate-capability scan (already in `lite.py dupes`),
(ii) Stage E telemetry, (iii) drift detection — manifests not refreshed
in N days whose providers have not been invoked. This is exactly the
**review queue** the Ontology Builder Agent doc
([`ontology-builder-agent.md`](ontology-builder-agent.md)) promises but
does not yet wire to real usage.

**Surfaces as.** Both. An MCP tool (`list_governance_flags()`) for
agents that want to self-police; a Power BI / Fabric dashboard for the
human Certify-gate reviewer (the CODEOWNER) so the queue is visual not
JSON.

#### 3. `predict_outcome(skill_id, context)` — success-rate inference

> *"`finance/po-match` has a 92% success rate when called after
> `finance/invoice-extract` with `K_erp_reachable=true`, but 31% when
> `K_erp_reachable` is unknown. Refuse, or run a precondition check
> first."*

Joins the ontology's `REQUIRES`/`CAUSES` edges with telemetry episodes
to produce a conditional success-rate estimate. This is the part that
genuinely earns the word *agentic* — it is the first signal that lets a
composing agent decide *not* to call a skill, instead of always trying
and failing.

**Surfaces as.** MCP tool, with a strong `riskHint=true` annotation. The
underlying model can start as a simple frequency table and graduate to
a learned predictor only if the simpler version proves insufficient
(same shape as the Ontology Builder Agent's measurable-contract
discipline).

### What this is NOT

- **Not Work IQ itself.** We are not building a competitor to a Microsoft
  service. We are building a Skill-domain analogue with the same shape,
  callable alongside Work IQ from the same Cowork or Copilot Studio
  agent. If Microsoft ships a "Skill IQ" first, our registry becomes the
  catalog they query, not the layer they replace.
- **Not a new agent.** All three behaviours are tools on the existing
  registry MCP server. The chassis principle "cap agents, grow the
  registry" still holds.
- **Not a guess.** The Ontology Builder Agent doc already specifies the
  measurable bet (≥ 80% proposal acceptance, ≥ 0.9 dup precision, < 5%
  drift). These three behaviours are the **operationalisation** of that
  bet — they generate the data that proves or kills it.

## Suggested decision for next session

Do **Stage A** (Ship Stage 2 and wire the MCP server to it). It is small,
already paid for in design, and gates every other stage. Until the MCP
server reads from a remote catalog, "deploy to Container Apps" is
deploying a toy. After Stage A, the natural follow-up in the same week is
Stage B (the ABS live-test). Stage D — `query_ontology` — is the first
piece of the §4 vision and should be the first thing built *after* Stage
B clears.

If Stage A is already done by the time you read this: do Stage D first,
because that is the smallest experiment that earns the project the word
*"agentic"* and the §4 hypothesis hinges on it.

## Links

- Work IQ overview — <https://learn.microsoft.com/microsoft-365/copilot/extensibility/work-iq>
- Work IQ MCP overview (10-tool design) — <https://learn.microsoft.com/microsoft-365/copilot/extensibility/work-iq/mcp/overview>
- Work IQ MCP in Copilot Studio — <https://learn.microsoft.com/microsoft-copilot-studio/use-work-iq>
- Agent 365 tools catalog (incl. Fabric IQ Ontology MCP) — <https://learn.microsoft.com/microsoft-agent-365/tooling-servers-overview>
- Microsoft IQ for agents (Work IQ + Fabric IQ + Foundry IQ) — <https://learn.microsoft.com/microsoft-copilot-studio/agents-experience/use-microsoft-iq>
- Fabric IQ overview — <https://learn.microsoft.com/fabric/iq/overview>
- Fabric IQ Ontology (preview) — <https://learn.microsoft.com/fabric/iq/ontology/overview>
- Work IQ policy governance — <https://learn.microsoft.com/microsoft-365/copilot/extensibility/work-iq/mcp/policy-governance-mcp>
