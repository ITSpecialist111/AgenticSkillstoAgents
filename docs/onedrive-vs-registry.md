# OneDrive-native skills vs Skills Registry plugin

> Companion to [`registry-evidence.md`](./registry-evidence.md) §9 and [`cowork-plugin-limitations.md`](./cowork-plugin-limitations.md).
> Captures the high-level tradeoff and a worked migration path, using `legal/msa-redlining` as the proof case (head-to-head run 2026-06-29).

---

## TL;DR

| Question | Answer |
|---|---|
| Can OneDrive skills be moved to the Skills Registry plugin? | **Yes — proven end-to-end with parity output.** The `legal-msa-redlining` skill lives in both delivery patterns and *both produce the same `MSA_UK_EU_Draft.docx`*. Pattern B reproduced across two independent runs (2026-06-29). |
| Which pattern is cheaper *per skill*? | **OneDrive-native**, when you have <20 skills and no central-governance needs. |
| Which pattern scales? | **Registry**, by design — O(1) tool surface regardless of catalog size. |
| When does the tradeoff flip? | At the **20-skill ceiling**, when central RBAC/audit becomes a requirement, or when you need one source of truth across users. |

---

## The two delivery patterns

### Pattern A — Cowork-native (OneDrive-backed)

- Author uploads SKILL.md (+ assets) to *Customize → Skills* in the Cowork UI.
- Cowork persists it to the user's OneDrive and re-indexes per user.
- On every task, Cowork loads the SKILL.md verbatim into the model's context if the description matches.
- Each skill effectively consumes one of Cowork's **20 tool slots per connector**.

### Pattern B — Skills Registry plugin (MCP-served)

- Author writes a schema-valid manifest (`examples/<id>.manifest.json`) + SKILL.md (`examples/<id>/SKILL.md`).
- `catalog.json` is regenerated; image is rebuilt and the Container App revision is rolled.
- The agent uses **four fixed tools** (`list_capabilities`, `find_skill_by_capability`, `describe_skill`, plus any bound execution tool) to discover skills on demand.
- `describe_skill` returns the SKILL.md body **inline as `content`** (text payloads ≤64 KB), so the agent reads instructions in the same call and can either invoke a bound MCP tool or execute the SKILL.md against Cowork's own tools (docx, file, web).
- Tool surface is **constant**: 4 of the 20 slots are used regardless of whether the catalog holds 22 or 220 skills.

---

## Pros / cons / tradeoffs

| Dimension | OneDrive-native | Skills Registry plugin |
|---|---|---|
| **Per-skill discovery cost** | Zero MCP overhead — skill loads inline | ~3 credits + 1 approval per `find`/`describe` (≈40 credits for full discovery, see registry-evidence §8 rows D+E) |
| **Tool-surface cost** | One slot per skill — caps at 20 | 4 slots total, O(1) — proven flat from 22 → 200 skills |
| **Catalog ceiling** | 20 skills per connector (Cowork hard limit) | None observed; tested to 23 today, math holds to 200+ |
| **Source of truth** | Per-user OneDrive — drift across users | Central git repo + image — one version, all users |
| **Rollout of a new skill** | Each user re-uploads or waits for Cowork re-index | `git push` → `az acr build` → revision roll; all users see it on next `list_capabilities` |
| **RBAC / governance** | Cowork user-level only | Manifest-declared `governance.rbac`, `dataClassification`, `audit.retentionDays` |
| **Audit trail** | Cowork task log only | Manifest `audit.logged: true` + Container App logs + commit history |
| **Approval prompts per task** | 1 per execution tool call | 2 per registry call (per-tool consent) + per-tool approvals for downstream execution; reducible via "always allow" |
| **Composability across skills** | Manual — author copies clauses between SKILL.md files | Manifest `dependencies[]` + capability tags — agent can chain |
| **Failure mode observed** | None in head-to-head | **Resolved 2026-06-29 (image `:v4`)** — `describe_skill` now inlines text payload `content`. Pre-fix, the agent tried `Read("skill://...")` and `web_fetch("skill://...")` before falling back to local read. Inline content removes this detour and unlocks full E2E asset generation. |
| **Authoring friction** | Drag-and-drop SKILL.md to UI | Write manifest + SKILL.md + regenerate catalog + rebuild image |
| **Best for** | Personal productivity skills, prototypes, single-user pilots | Enterprise rollouts, governed skills, catalogs that will grow past 20 |

### The structural tradeoff

**Discovery overhead vs scale ceiling.** Native OneDrive is cheaper per skill but the host caps you at 20. The registry costs ~3 credits per discovery call but stays flat as the catalog grows — and only the registry gives you central RBAC, audit, and instant rollout to every user.

The 20-skill ceiling is the inflection point. Below it, with no governance requirements, native OneDrive wins on raw cost. Above it — or the moment compliance/RBAC/audit enters the conversation — the registry pattern is the only viable shape.

---

## Migration walkthrough — OneDrive → Skills Registry plugin

Proven with `legal-msa-redlining` (2026-06-29). The skill was authored natively in Cowork OneDrive first, then mirrored into the registry; both versions resolved the same prompt successfully.

### Step 1 — Extract the SKILL.md

Pull the SKILL.md body out of OneDrive (Cowork *Customize → Skills* → download).

Place it at:

```
examples/<id>/SKILL.md
```

Keep the YAML frontmatter (`name`, `description`) intact — `description` is what triggers Cowork's matcher, and the registry surfaces it via `describe_skill`.

### Step 2 — Write a schema-valid manifest

Create `examples/<id>.manifest.json` against [`schemas/skill-manifest.schema.json`](../schemas/skill-manifest.schema.json). Required blocks:

- `identity` — id, name, version, owner, skillType, tags
- `capability` — summary, capabilityTags, inputs/outputs, preconditions/effects
- `scoring` — determinism, risk, reversible, rationale
- `dependencies[]` — references to other skills/tools the agent will need
- `governance` — visibility, rbac, dataClassification, cost, audit
- `lifecycle` — stage, certifiedBy, certifiedAt

The capability tags are what `find_skill_by_capability` resolves against, so name them deliberately (verb-noun, lowercase, dotted, e.g. `legal.redline`, `msa.draft`).

### Step 3 — Add three `catalog.json` entries

The registry serves three views of every skill:

1. **Slim list entry** in `catalog.json` `skills[]` — id, name, version, stage, capabilityTags, mcp binding.
2. **Capability index** — each tag in `capabilityTags[]` must appear in the inverted-index map.
3. **Full manifest** — served on demand by `describe_skill` from the manifest file.

Regenerate the catalog (or hand-edit if the generator isn't run):

```bash
node tools/build-catalog.mjs   # or your equivalent generator
```

### Step 4 — Rebuild image and roll the Container App

```bash
az acr build \
  --registry crcowork5a2c14 \
  --image skills-registry-mcp:vN \
  --file Dockerfile .

az containerapp update \
  --name ca-cowork-mcp \
  --resource-group rg-cowork-spike-uks \
  --image crcowork5a2c14.azurecr.io/skills-registry-mcp:vN
```

The MCP endpoint stays the same:
`https://ca-cowork-mcp.lemonsea-9c8971ad.uksouth.azurecontainerapps.io/api/mcp`

### Step 5 — Verify

From any MCP client (or `tools/registry-evidence-suite.sh`):

```bash
curl -s -X POST $ENDPOINT \
  -H 'content-type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"find_skill_by_capability","arguments":{"capabilityTag":"legal.redline"}}}'
```

Expect `skill_id: legal/msa-redlining` + version + tags in <250 ms.

### Step 6 — (Optional) Deprecate the OneDrive copy

Once the registry version is live and users have the Skills Registry connector enabled, delete the OneDrive-uploaded SKILL.md from each user's *Customize → Skills* tab to avoid drift between the two versions.

---

## When to keep OneDrive

Not everything should be migrated. Keep OneDrive-native when:

- The skill is **personal-productivity** (one user, no sharing).
- It's a **prototype** still being iterated on faster than `az acr build` cycles allow.
- The skill has **no governance, RBAC, or audit requirement**.
- The total catalog will **never exceed 20 skills** and there's no plan to grow it.

For anything beyond that — anything where multiple people, compliance, or scale enters the picture — move it to the registry.

---

## Live evidence

- **Pattern A run**: Cowork task `abb62ecb-5205-470f-8aac-4e34ed6ecd02` — produced `MSA_UK_EU_Draft.docx` with UK governing law, EU GDPR Art. 28 DPA as Schedule 1, UK IDTA as Schedule 2, Negotiation Summary cover page.
- **Pattern B discovery-only run** (pre-inline-fix): Cowork task `e26fd4c3-b53c-436c-8aea-abc1c9aa626f` — discovered `legal/msa-redlining` v1.0.0 via the registry, returned full capability tags + governance + faithful UK/EU clause guidance, with zero prior agent knowledge.
- **Pattern B full E2E runs** (post-inline-fix, image `:v4`): Cowork tasks `208c409c-755f-4750-8c97-005e42c9310e` and `b98ec511-ec3e-45e6-ab83-db4ea892cb7b` — both produced `MSA_UK_EU_Draft.docx` with the same UK + EU schedule set as Pattern A. 4/4 green steps. ~483.4 Copilot Credits per run. **Output parity with Pattern A, reproducible.**

Catalog at time of runs: `:v3` (23 skills / 66 tags) for the early runs;
`:v4` (23 skills / 66 tags + inline `content` in `describe_skill`) for
the full E2E runs. Full numbers in
[`registry-evidence.md`](./registry-evidence.md) §9.
