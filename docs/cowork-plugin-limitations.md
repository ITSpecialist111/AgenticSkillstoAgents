# Cowork plugin limitations — empirical notes from the 2026-06-28 spike

> **Scope:** what we learned while making the Skills Registry + Finance Tools
> spike actually work inside Microsoft Copilot Cowork (M365 Copilot agent
> runtime). Companion to [`cowork-plugin-spike.md`](./cowork-plugin-spike.md).
> Status: all four limitations below were observed live; mitigations were
> either proved end-to-end or have a concrete next step.

## 1. Per-host connector dedup (proved + mitigated)

**Symptom.** A single plugin (`cowork-plugin/manifest.json` v0.3.0) declared
two `agentConnectors` whose `mcpServerUrl` shared the same host
(`ca-cowork-mcp.lemonsea-9c8971ad.uksouth.azurecontainerapps.io`) but
different paths (`/api/mcp` vs `/api/skills/finance-tools/mcp`). Both
appeared in the install UI; only one ever produced an MCP session at
runtime. Container logs showed exactly one `ListToolsRequest` per task —
the second connector was silently dropped.

**Mitigation (proved).** Split into two single-connector plugins, each with
its own GUID and display name:
- `cowork-plugin-registry/` → `/api/mcp` (5 read-only discovery tools after Stage F Phase 1: `find_skill_by_capability`, `describe_skill`, `list_capabilities`, `query_ontology`, `list_org_entities`)
- `cowork-plugin-finance/` → `/api/skills/finance-tools/mcp` (`invoice_extract`)

After installing both, logs at `20:40:11` showed concurrent
`POST /api/mcp` *and* `POST /api/skills/finance-tools/mcp`, each followed
by `Processing request of type ListToolsRequest`. Both connectors became
addressable as `mcp__skills-registry-mcp__*` and `mcp__finance-tools-mcp__*`.

**Implication for the registry-as-front-door thesis.** "One plugin per
skill server" is the unit of distribution, not "one plugin per org". The
registry is its own plugin; each skill server gets its own plugin. The
registry's job is to tell the agent *which* connector to call.

## 2. Cross-skill composition works (proved)

**Question.** Once the registry tells the agent the binding URL for
`finance/invoice-extract`, can the agent actually route the next call
through the *finance* connector, not the registry connector?

**Test.** In a single Cowork task, asked the agent to:
1. `mcp__skills-registry-mcp__list_capabilities`
2. `mcp__skills-registry-mcp__find_skill_by_capability` with `tag='invoice.extract'`
3. `mcp__skills-registry-mcp__describe_skill` with the returned skill_id
4. `mcp__finance-tools-mcp__invoice_extract` with `document_url=...`

**Result.** All four fired. Container logs confirmed the fourth call hit
`POST /api/skills/finance-tools/mcp` → `CallToolRequest`, not the registry
endpoint. The agent returned vendor/invoice-number/total/line-items from
the stub and — notably — flagged that it was stubbed spike data, showing
it actually read the tool's description metadata, not just its name.

**Implication.** The registry pattern composes inside Cowork: an agent
can discover a capability it didn't know about at session start, then
invoke it via a *different* MCP connector in the same conversation,
without any plugin reconfiguration. This is the missing-middle thesis
working as designed.

## 3. Per-call approval gating (observed, no mitigation today)

**Behaviour.** Cowork prompts the user to **Approve** every single MCP
tool call individually, even for tools annotated `readOnlyHint: true`,
`idempotentHint: true`, `openWorldHint: false`. The four-step test above
required four separate Approve clicks. There is no batch approval, no
"trust this tool" toggle visible to the user, and no per-session
authorisation that I could find in the connector schema.

**Cost.** For a discovery-then-invoke pattern this is 3–4 modal prompts
per task. For agents that branch ("try cap X, fall back to Y"), the
prompt count grows linearly with attempts. This is the single biggest
friction point in the user experience and the largest practical blocker
to "agent autonomously stitches skills together".

**Mitigations to investigate (not yet tested).**
- Whether `agentSkills` SKILL.md narrative can pre-authorise the agent to
  use specific tools, or whether Cowork honours an org-level allow-list.
- Whether `authorization.type` other than `None` (e.g. OAuth with a
  consented scope) changes the per-call gating behaviour.
- Whether Copilot Studio (vs Cowork) has different gating defaults — the
  same MCP server should plug into either host.

## 4. Write-side tools blocked at runtime (observed)

**Symptom.** `submit_skill_draft` (the only non-read-only tool on the
registry server) was successfully advertised by the MCP server but never
became callable from the Cowork surface — it didn't appear in the
agent's available tool list. The three read-only tools beside it in
`toolDescription.json` did appear.

**Hypothesis.** Cowork filters the tool list it exposes to the agent
based on annotations or trust signals (`readOnlyHint: false` →
suppressed). Have not confirmed by reading Cowork source; the workaround
is to gate write paths behind a separately-authenticated connector or to
trigger drafts out-of-band (CLI / GitHub Action), keeping the in-Cowork
surface read-only.

**Implication for governance.** This is actually convenient — it means
the Cowork-visible registry is read-only by default, and any draft/submit
flow needs an explicit second channel. That matches what we'd want for a
governed registry anyway: "agents discover, humans (or a CI bot) write".

## 5. Context window cost of the discovery loop (rough estimate)

Per the four-step test above, what the agent loads into its working
context across the loop:

| Step | Payload | Approx. bytes |
| --- | --- | --- |
| Session start: registry connector tool list | 3 tools × ~600 B | ~1.8 KB |
| Session start: finance connector tool list | 1 tool × ~700 B | ~0.7 KB |
| `list_capabilities` result | 5 tag → skill rows | ~0.4 KB |
| `find_skill_by_capability('invoice.extract')` | 1 skill summary inc. binding | ~0.6 KB |
| `describe_skill('invoice-extract')` | full manifest + `payloadFiles[]` with text payloads inlined as `content` | ~5–10 KB (manifest + SKILL.md body) |
| `invoice_extract(...)` response | stub invoice JSON | ~0.6 KB |
| **Total loaded for one end-to-end loop** | | **~8–15 KB** |

This is small. The thing that would balloon it would be eager-loading
every skill in the catalog at session start; the registry deliberately
gates the SKILL.md body behind `describe_skill` so it only enters
context when the agent commits to inspecting a specific skill.

**Update (2026-06-29, image `:v4`):** text payload files (SKILL.md and
JSON ≤64 KB) are now inlined as `content` in `payloadFiles[]`. Earlier
shipped only `skill://` URIs, which Cowork cannot natively resolve —
agents were observed trying `Read("skill://...")` and `web_fetch(...)`
before giving up. Inlining the content lets Cowork use the registry as
a **library**: discover a skill, get its SKILL.md body in the same
call, and execute via Cowork's own docx/file/web tools. Binary or
oversized files still ship as `skill://` URIs for clients that can
resolve them. Proven E2E with `legal/msa-redlining` producing
`MSA_UK_EU_Draft.docx` at ~483 Copilot Credits, reproduced across two
runs.

**Implication.** Context cost is not a blocker for the registry pattern.
The pattern that *would* be costly — eager-loading every skill manifest
into context at session start — is exactly what the registry is designed
to avoid.

## 6. Plugin install UX quirks (observed)

- Cowork's plugin list shows multiple plugins with the same display name
  side-by-side; install is by GUID, not name. Old versions stay installed
  until explicitly disabled. After re-upload, the *old* package may still
  be the enabled one — verify by toggling and checking the connector tool
  list, not by name alone.
- Send button in the Cowork chat input is a `<button aria-label="Send">`;
  for automation, `b.scrollIntoView(); b.focus(); b.click()` is reliable
  where a plain `.click()` sometimes no-ops on first attempt.

## 7. Ontology query tool: per-edge governance fence works (proved)

**Test (2026-06-29, image `:v5`, plugin v0.2.0).** Stage D added
`query_ontology(seed, relation, max_hops, caller_classification)` as the
fourth registry tool. Two Cowork tasks against the deployed Container
App, identical seed and hops, only `caller_classification` changed:

| Caller clearance | totalPaths | suppressedByClassification |
| --- | --- | --- |
| `confidential` | 1 (`msa-redlining → DEPENDS_ON → docx.create`) | 0 |
| `internal` | 0 | 14 |

The agent picked the tool unprompted from the connector advertisement,
hit one Approve modal (per §3), and rendered the path table verbatim.
At `internal` clearance the same query returns zero paths but reports 14
edges suppressed — every dependency edge for `msa-redlining` is
classified `confidential` or above, so a lower-cleared caller learns
nothing about its graph neighbourhood.

**Implication.** `dataClassification` is not advisory metadata; it gates
traversal at the edge level inside the MCP server before any response
reaches the agent. A registry that contains confidential pipeline skills
can still be safely discoverable by lower-cleared agents — they get
suppression counts, not silent denials, and never see the confidential
endpoints. Full evidence: [`stage-d-evidence.md`](stage-d-evidence.md).

## Summary for the missing-middle thesis

The registry-as-Cowork-plugin pattern survives contact with Cowork's
runtime, with three non-obvious findings:

1. **One MCP host per plugin** (split connectors across plugins).
2. **Read-only by default in Cowork** (write paths need a separate
   channel or different auth model).
3. **Cowork doesn't resolve `skill://` URIs** — fixed in image `:v4` by
   inlining text payload content in `describe_skill`. Without that fix,
   the registry could only *describe* skills inside Cowork; with it, the
   registry doubles as a **library** the agent can read SKILL.md from
   and then execute via Cowork's own tools.

Inside those constraints, two end-to-end loops work in production
Cowork against a real Azure Container App:

- **Cross-connector composition** — *agent asks the registry who can do
  X, gets back an MCP binding, calls the bound tool on a different
  connector, gets back structured data*.
- **Registry-as-library** — *agent asks the registry who can do Y, gets
  back inlined SKILL.md, follows it with Cowork's own docx/file/web
  tools to produce a real deliverable*. Reproduced twice with
  `legal/msa-redlining` → `MSA_UK_EU_Draft.docx`, ~483 credits per run.

That's the spike's main result.
