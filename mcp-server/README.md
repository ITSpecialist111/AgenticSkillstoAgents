# mcp-server — Skills Registry MCP server

A thin MCP adapter over [`prototype-lite/lite.py:Registry`](../prototype-lite/lite.py).
Exposes four tools and a family of `skill://` resources that any MCP client
can call:

| Tool | Returns |
|---|---|
| `find_skill_by_capability(tag, published_only=True)` | List of skill summaries (id, name, version, stage, capability tags, MCP binding). |
| `describe_skill(skill_id)` | Full schema-validated manifest **plus** a `payloadFiles` list of `skill://` resource URIs. |
| `list_capabilities()` | `{tag: [skill_id, …]}` inverted index. |
| `submit_skill_draft(manifest, payload?, title?, body?)` | Opens a GitHub PR adding the manifest (+ optional payload files). Returns `{pr_url, pr_number, branch, files_added}`. The PR review is the Register gate. |

Resources (one per file in each `examples/<slug>/` payload folder):

| URI pattern | Example | Mime |
|---|---|---|
| `skill://<slug>/SKILL.md` | `skill://finance-invoice-extract/SKILL.md` | `text/markdown` |
| `skill://<slug>/assets/<file>` | `skill://finance-invoice-extract/assets/output-schema.json` | guessed from extension |

Resources don't count against Cowork's 20-tool / system-prompt cap, so the
agent can read narrative + schemas on demand without inflating context.

See [`docs/cowork-plugin-spike.md`](../docs/cowork-plugin-spike.md) for the
contract and the Cowork plugin that wraps this server.

## Quickstart

```bash
cd mcp-server
python -m pip install -r requirements.txt
python -m pytest -q          # 20 tests, no MCP client needed
```

## Run it

```bash
# stdio transport — for Claude Desktop, MCP Inspector, local probing
python -m server

# Streamable HTTP transport — what Cowork connects to
MCP_TRANSPORT=http PORT=8000 python -m server
# Then:
curl http://localhost:8000/api/mcp     # GET probe (friendly JSON)
curl http://localhost:8000/health      # liveness for Container Apps
# POST http://localhost:8000/api/mcp  -> JSON-RPC 2.0 (use an MCP client)
```

## Environment

| Var | Default | What it does |
|---|---|---|
| `MCP_TRANSPORT` | `stdio` | `stdio` or `http` (`streamable-http`). |
| `HOST` | `0.0.0.0` | HTTP bind host. |
| `PORT` | `8000` | HTTP bind port. |
| `REGISTRY_CATALOG_MODE` | `local` | `local` (glob `../examples/*.manifest.json`) or `remote` (pull Stage 2 blob — not yet implemented). |
| `REGISTRY_CATALOG_URL` | — | Required when `REGISTRY_CATALOG_MODE=remote`. |
| `GITHUB_TOKEN` | — | Required for `submit_skill_draft`. Needs `contents:write` + `pull_requests:write` on the target repo. |
| `GITHUB_REPO` | `ITSpecialist111/AgenticSkillstoAgents` | Target repo for `submit_skill_draft` PRs. |

## Build the container image

The image is built from the **repo root** so the build context can see
`prototype-lite/`, `schemas/`, and `examples/` alongside `mcp-server/`:

```bash
# Local
docker build -f mcp-server/Dockerfile -t skills-registry-mcp:dev .
docker run --rm -p 8000:8000 skills-registry-mcp:dev

# Azure Container Registry (used by infra/stage-3/main.bicep)
az acr build \
  --registry <acrName from Stage 3 outputs> \
  --image skills-registry-mcp:latest \
  --file mcp-server/Dockerfile \
  .
```

## Probe with MCP Inspector

```bash
npx @modelcontextprotocol/inspector python -m server
```

Opens a browser UI listing the three tools. Try
`find_skill_by_capability(tag="invoice.extract")` — should return one hit.

## What this server is *not*

- Not a free-for-all write API. `submit_skill_draft` opens a PR; the PR
  review IS the Stage 1 Register gate. Nothing reaches `main` without a
  human approver.
- Not an executor. Each summary contains the `mcp` binding the agent
  uses to call the underlying skill server directly.
- Not auth-gated for discovery. Discovery metadata is non-sensitive;
  sensitive material lives on the underlying skill servers and carries
  its own auth. The write path *is* auth-gated (GitHub token).
