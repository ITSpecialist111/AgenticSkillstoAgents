# Cowork plugin spike — registry as a Cowork MCP plugin

> **Status:** Spike. Code in [`mcp-server/`](../mcp-server) and
> [`cowork-plugin/`](../cowork-plugin). Patterned on the proven
> [TomTom Map Cowork POC](https://github.com/ITSpecialist111/CopilotStudio_TomTom_Map_MCP_POC):
> Teams app manifest v1.28 envelope (`agentSkills` + `agentConnectors`) wrapped
> around a remote MCP server hosted on Azure Container Apps.

## Why this is the unlock

Today an agent that wants to use one of our skills has to either:
- Clone the GitHub repo and parse `examples/*.manifest.json`, or
- Hit a raw blob (Stage 2, planned) and parse JSON itself.

Neither is how Microsoft Copilot Cowork (or Copilot Studio) plugins work.
Cowork plugins are **Teams app packages** that declare:

- `agentSkills` — markdown files that tell the host LLM *when* to reach for a
  capability (the "skill card").
- `agentConnectors` — pointers to a **remote MCP server** that exposes the
  actual tools via Streamable HTTP (JSON-RPC 2.0 over `POST /api/mcp`).

So the registry's natural front door is exactly that: a tiny Teams plugin
package whose connector points at our MCP server, which exposes the chassis's
existing discovery primitives as three MCP tools.

This is the missing-middle thesis made concrete: one **registry plugin**
that any number of Cowork agents (or Copilot Studio agents) can install,
giving them a governed view over the org's skills.

## The MCP contract

Four tools — three read-only discovery tools plus one write-side tool that
opens a GitHub PR. Invocation of business skills is out of scope (the
agent uses the `mcp` block in each returned skill to call the underlying
skill server directly).

### `find_skill_by_capability`

> "Who in this org can do X?"

| Field | Type | Notes |
|---|---|---|
| **Input** `tag` | string | dotted lowercase, e.g. `invoice.extract` |
| **Input** `published_only` | bool | defaults to true |
| **Output** | `SkillSummary[]` | empty list if nothing matches |
| **Annotations** | `readOnlyHint=true`, `idempotentHint=true` | |

`SkillSummary` is `{id, name, version, stage, capabilityTags, mcp}`. The
`mcp` block is what the agent uses to *call* the skill (server name,
tool name, namespace, transport).

### `describe_skill`

> "Give me the full manifest for this skill so I can decide whether to use it."

| Field | Type | Notes |
|---|---|---|
| **Input** `skill_id` | string | e.g. `finance/invoice-extract` |
| **Output** | `Manifest` + `payloadFiles[]` | the full schema-validated manifest, plus an array of `{path, uri, mimeType}` records pointing at `skill://` resources |
| **Errors** | `NotFound` | if the id is unknown |
| **Annotations** | `readOnlyHint=true`, `idempotentHint=true` | |

Returns the canonical manifest so the agent can read governance, scoring
(determinism/risk), preconditions, and effects before deciding. The
`payloadFiles` array lets the agent pull the narrative `SKILL.md` and any
asset schemas via MCP resources — read on demand, no context-window cost.

### `list_capabilities`

> "What can this org do?"

| Field | Type | Notes |
|---|---|---|
| **Input** | (none) | |
| **Output** | `{tag: [skill_id, ...]}` | inverted index over published skills |
| **Annotations** | `readOnlyHint=true`, `idempotentHint=true` | |

Useful for the agent to ask "what categories of work are available?"
before it has a specific task in mind.

### `submit_skill_draft`

> "Register this new skill on behalf of the user / authoring agent."

| Field | Type | Notes |
|---|---|---|
| **Input** `manifest` | object | must validate against `schemas/skill-manifest.schema.json` |
| **Input** `payload` | `{relPath: utf8Text}` (optional) | `SKILL.md`, `assets/*`, `scripts/*`; paths must not contain `..` or start with `/` |
| **Input** `title`, `body` | string (optional) | PR title/body; defaults to a templated summary |
| **Output** | `{pr_url, pr_number, branch, files_added[]}` | the opened PR |
| **Errors** | `SubmitError` | bad manifest, unsafe path, missing `GITHUB_TOKEN`, GitHub API failure |
| **Annotations** | `readOnlyHint=false`, `idempotentHint=false`, `openWorldHint=true` | |

This is the two-way bridge. An agent (or human via Cowork) submits a
manifest; the server validates it against the schema, branches off `main`,
writes `examples/<last-segment>.manifest.json` + payload files under
`examples/<slug>/`, and opens a PR. **The PR review IS the Register
gate** — nothing on `main` until a human approves.

Server needs `GITHUB_TOKEN` (with `contents:write` + `pull_requests:write`
on the target repo) and `GITHUB_REPO` (defaults to the upstream).

### Resources: `skill://<slug>/<path>`

Each skill's payload folder (`examples/<slug>/`, where the slug is the
skill id with `/` replaced by `-`) is exposed as a set of MCP resources:

| URI | Mime |
|---|---|
| `skill://finance-invoice-extract/SKILL.md` | `text/markdown` |
| `skill://finance-invoice-extract/assets/output-schema.json` | `application/json` |

Resources don't count against Cowork's 20-tool / system-prompt cap.
That's the design lever — narrative + schemas live behind URIs the agent
chooses to fetch, instead of being baked into the system prompt.

## How a Cowork agent uses it

1. Cowork admin uploads the plugin zip (`cowork-plugin/`) to the tenant.
2. Agent gets a user request: *"pull the invoice fields out of this PDF
   and reconcile it against the PO."*
3. The skill card in `cowork-plugin/skills/skills-registry/SKILL.md` tells
   the host LLM to call the registry connector.
4. Agent calls `find_skill_by_capability(tag="invoice.extract")` → gets
   back `finance/invoice-extract` + its `mcp` block.
5. Agent calls `find_skill_by_capability(tag="invoice.match")` → gets
   back `finance/po-match`.
6. Agent reads the returned `mcp` blocks and calls the underlying
   skill servers (out of scope for this plugin — those are the
   tenant's existing finance-tools MCP servers).
7. Agent composes the result.

The registry is the **switchboard**, not the executor.

## Architecture

```
┌──────────────────────┐                     ┌──────────────────────────────┐
│  Cowork host (M365)  │                     │   Azure Container Apps        │
│                      │   POST /api/mcp     │   ca-skills-registry-mcp      │
│  Teams plugin pkg    │ ──── HTTPS ────────►│                               │
│  - manifest.json     │   JSON-RPC 2.0      │   mcp-server/server.py        │
│  - SKILL.md          │                     │   (FastMCP + Starlette)       │
│  - connector ref     │                     │                               │
└──────────────────────┘                     └──────────────┬───────────────┘
                                                            │ reads
                                                            ▼
                                                ┌──────────────────────────┐
                                                │  catalog source          │
                                                │  - bundled examples/     │ (dev / Stage 1)
                                                │  - Stage 2 blob URL      │ (prod)
                                                └──────────────────────────┘
```

Two catalog backends (selected via `REGISTRY_CATALOG_MODE` env var):
- `local` (default): glob `examples/*.manifest.json`. Used for dev, CI,
  and the first ABS-tenant test.
- `remote`: GET the rolled-up `catalog.json` from the Stage 2 blob.
  Used once Stage 2 is deployed.

Both go through `prototype-lite/lite.py:Registry` — the server is a thin
MCP adapter over the chassis, not a reimplementation.

## Transport

The MCP Python SDK's `FastMCP` exposes both transports from the same tool
definitions:

- **stdio** — for local dev (Claude Desktop, MCP Inspector, `pytest`).
  Default when `MCP_TRANSPORT` is unset.
- **Streamable HTTP** (`POST /api/mcp`) — what Cowork's
  `remoteMcpServer.mcpServerUrl` connects to. Active when
  `MCP_TRANSPORT=http`. Wrapped via FastMCP's `streamable_http_app()` and
  served by uvicorn on `PORT` (default `8000`).

A `GET /api/mcp` probe is mounted alongside so the Cowork-side health
check returns a readable response instead of a 404.

## Hosting on Azure Container Apps (Stage 3)

Mirrors the TomTom POC topology:

| Resource | Why |
|---|---|
| `acr-skillsregistry-uks` (Container Registry, Basic) | Holds the server image. |
| `cae-skillsregistry-uks` (Container Apps Environment) | Shared env, Consumption profile. |
| `law-skillsregistry-uks` (Log Analytics) | App logs. |
| `ca-skills-registry-mcp` (Container App) | The server. Single revision, single replica is fine for spike. Public ingress on 8000, transport `auto`. |

Build + push:

```bash
az acr build \
  --registry acrskillsregistry<suffix> \
  --image skills-registry-mcp:latest \
  ./mcp-server
```

Deploy:

```bash
az deployment group create \
  --resource-group rg-skillsregistry-uks \
  --template-file infra/stage-3/main.bicep \
  --query properties.outputs
```

Estimated cost: Container Apps Consumption — first 180k vCPU-seconds /
month free. At realistic registry traffic (<<1 request/min) the bill is
effectively £0.

## How to live-test in the ABS tenant

1. Build the image and deploy via the Bicep above. Capture the
   `mcpServerUrl` output — it'll look like
   `https://ca-skills-registry-mcp.<region>.azurecontainerapps.io/api/mcp`.
2. Edit `cowork-plugin/manifest.json` and replace the placeholder
   `mcpServerUrl` with the real URL from step 1.
3. Zip the `cowork-plugin/` folder contents (not the folder itself):
   `cd cowork-plugin && zip -r ../skills-registry-plugin.zip .`
4. In the Microsoft 365 admin centre (or Teams Developer Portal),
   upload the zip as a custom app to the ABS tenant.
5. In Cowork, install the plugin into an agent. Ask it: *"what skills
   do we have for invoice processing?"* — it should call
   `find_skill_by_capability(tag="invoice.extract")` via the connector.

## What's out of scope for the spike

- **Invocation.** The plugin returns MCP bindings; it doesn't proxy
  calls. Reason: credential delegation and auth boundaries belong with
  the underlying skill server (finance-tools etc.), not the registry.
- **Write operations.** No `register_skill` tool. Skills are added via
  GitHub PR (Stage 1 Register gate) — that's deliberate. The MCP server
  is read-only.
- **Auth on the MCP server.** Discovery metadata is non-sensitive (same
  threat model as the Stage 2 catalog blob). Sensitive material is in
  the *underlying* skill servers and has its own auth. The Cowork plugin
  manifest declares `authorization.type: "None"` for the same reason.
  If the live test demands Entra auth, add it as a follow-up — the
  TomTom POC's `/api/connector` path shows the pattern.
- **Multi-region / autoscale.** Single replica, single region. Re-evaluate
  if traffic warrants it (criteria in `docs/complexity-review.md`).

## Promotion path (after the spike clears)

1. Wire `.github/workflows/deploy-mcp.yml` to rebuild + redeploy on every
   push to `main` via OIDC.
2. Switch `REGISTRY_CATALOG_MODE=remote` + `REGISTRY_CATALOG_URL=<Stage 2 blob>`
   once Stage 2 is live (so the server no longer bakes the examples into
   the image).
3. If Cowork live-test surfaces a different shape (Copilot Studio connector,
   Power Platform custom connector, declarative plugin manifest, etc.),
   the chassis primitives don't change — only the transport wrapper.

## Files in this spike

| Path | What |
|---|---|
| `docs/cowork-plugin-spike.md` | This file. |
| `mcp-server/server.py` | The MCP server (stdio + HTTP). |
| `mcp-server/test_server.py` | Unit tests over pure tool functions. |
| `mcp-server/Dockerfile` | Container image for Container Apps. |
| `mcp-server/requirements.txt` | `mcp`, `jsonschema`, `uvicorn`. |
| `mcp-server/README.md` | Local quickstart + container build. |
| `cowork-plugin/manifest.json` | Teams app v1.28 envelope. |
| `cowork-plugin/toolDescription.json` | Tool schemas for the host LLM. |
| `cowork-plugin/skills/skills-registry/SKILL.md` | Skill card. |
| `cowork-plugin/color.png`, `outline.png` | Required Teams icons (placeholder). |
| `cowork-plugin/README.md` | Upload + install steps. |
| `infra/stage-3/main.bicep` | ACR + Container Apps environment + app. |
| `infra/stage-3/README.md` | Deploy walkthrough. |
