# mcp-server — Skills Registry MCP server

A thin MCP adapter over [`prototype-lite/lite.py:Registry`](../prototype-lite/lite.py).
Exposes three read-only discovery tools that any MCP client can call:

| Tool | Returns |
|---|---|
| `find_skill_by_capability(tag, published_only=True)` | List of skill summaries (id, name, version, stage, capability tags, MCP binding). |
| `describe_skill(skill_id)` | Full schema-validated manifest including governance and scoring. |
| `list_capabilities()` | `{tag: [skill_id, …]}` inverted index. |

See [`docs/cowork-plugin-spike.md`](../docs/cowork-plugin-spike.md) for the
contract and the Cowork plugin that wraps this server.

## Quickstart

```bash
cd mcp-server
python -m pip install -r requirements.txt
python -m pytest -q          # 11 tests, no MCP client needed
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

- Not a write API. New skills land via GitHub PR (Stage 1 Register gate).
- Not an executor. Each summary contains the `mcp` binding the agent
  uses to call the underlying skill server directly.
- Not auth-gated. Discovery metadata is non-sensitive; sensitive material
  lives on the underlying skill servers and carries its own auth.
