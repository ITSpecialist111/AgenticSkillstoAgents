# Stage B runbook — deploy the MCP server + live-test the Cowork plugin

> **Audience:** Graham (or anyone with `Contributor` on the ABS tenant
> subscription). End-to-end walkthrough: from a clean shell to a Cowork
> agent answering "who can extract invoices?" against a real Azure-hosted
> MCP server.
>
> **Time budget:** ~25 minutes wall-clock. ~15 minutes of that is
> `az acr build` + first Container App revision warming up.

## What you'll end up with

```
GitHub repo (main)
   │ python lite.py index --out catalog.json
   │ (publish-catalog.yml — already wired)
   ▼
Azure Blob Storage  ──────►  Azure Container Apps  ──────►  Cowork agent
catalog.json                 ca-skills-registry-mcp        (Skills Registry plugin)
                             /api/mcp (Streamable HTTP)
```

Stage 2 is the blob. Stage 3 is the container. Stage B is the
end-to-end live test that proves the two halves connect to Cowork.

## Prerequisites

1. **Stage 2 catalog is live** (skip if you're testing in `CATALOG_MODE=local`
   on first deploy — recommended for first run). If using remote mode:
   - `publish-catalog.yml` has run at least once green on `main`
   - `https://<storage>.blob.core.windows.net/catalog/catalog.json` returns 200
   - Capture that URL — Stage 3 takes it as `CATALOG_URL`.
2. **Local tools installed:**
   - `az` CLI ≥ 2.60 (`az version`)
   - Python 3.10+ with `httpx` for the smoke test (`pip install httpx`)
   - `bash` (Git Bash on Windows is fine)
3. **Azure login + subscription:**
   ```bash
   az login
   az account set --subscription "<sub-name-or-id>"
   az account show --query "{tenant:tenantId, sub:name}"
   ```
4. **Teams Developer Portal access** at <https://dev.teams.microsoft.com>
   for the ABS tenant (you need to upload the plugin zip).

## Step 1 — deploy Stage 3 (Container Apps + ACR + image)

From the repo root:

```bash
# First run: local catalog mode. Safer — proves the image works before
# adding the blob dependency.
./infra/stage-3/deploy.sh

# Or, with the Stage 2 blob:
CATALOG_MODE=remote \
CATALOG_URL=https://<storage>.blob.core.windows.net/catalog/catalog.json \
  ./infra/stage-3/deploy.sh
```

The script is idempotent — re-run safely if a step fails partway.

Expected output (last few lines):

```
==============================================================
  MCP server URL: https://ca-skills-registry-mcp.<region>.azurecontainerapps.io/api/mcp
  FQDN:           ca-skills-registry-mcp.<region>.azurecontainerapps.io
==============================================================
```

**Copy the `MCP server URL`** — every following step needs it. Call it
`$MCP_URL` from here on.

```bash
export MCP_URL="https://ca-skills-registry-mcp.<region>.azurecontainerapps.io/api/mcp"
```

### If the first deploy doesn't print a URL

- `az deployment group show -g rg-skillsregistry-uks -n main --query properties.outputs`
  shows the same outputs; the script just failed to print them.
- The Container App can take ~60s after the first image push before
  `/health` answers. Wait, then re-run the smoke test — don't redeploy.

## Step 2 — smoke-test the MCP server

```bash
python tools/smoke-test-mcp.py "$MCP_URL"
```

Expected (every line begins `OK`):

```
OK   GET https://.../health -> 200
OK   /health returns {status: ok}
OK   GET https://.../api/mcp -> 200
OK   probe service = skills-registry-mcp
OK   probe lists all four tools
OK   initialize returned a result
OK   tools/list contains all four tools (saw [...])
OK   tools/call find_skill_by_capability returned content for tag='invoice.extract'
     hits: ['finance-invoice-extract']

All checks passed.
```

If any line is `FAIL:` the script exits non-zero and prints the offending
response. Common causes:

| Symptom | Likely cause | Fix |
|---|---|---|
| `/health` 404 | App hasn't restarted into the new image | Wait 60s; or `az containerapp revision restart` |
| `probe service` mismatch | Old image still running | Re-run `az containerapp update --image ...` from `deploy.sh` |
| `tools/call` empty content | Remote mode but blob unreachable | `az storage blob show` against the catalog blob; check `validDomains` |

## Step 3 — build the Cowork plugin zip

```bash
python tools/build-cowork-plugin.py "$MCP_URL"
```

That writes `./skills-registry-plugin.zip` (≈ 5 KB). It:

- Reads `cowork-plugin/manifest.json` from the repo
- Replaces the `REPLACE-ME` placeholder in `agentConnectors[0].remoteMcpServer.mcpServerUrl`
- Rewrites `validDomains` to match the actual host (`*.azurecontainerapps.io` + the literal FQDN)
- Zips everything **at the root** (manifest.json is not nested in a folder — that's
  the layout Teams Developer Portal requires)

Sanity-check the contents:

```bash
unzip -l skills-registry-plugin.zip
# Should list: manifest.json, color.png, outline.png, toolDescription.json,
# skills/skills-registry/...
```

## Step 4 — upload the plugin to the ABS tenant

There are two upload paths. Pick one.

### Option A — Teams Developer Portal (recommended for the spike)

1. Browse to <https://dev.teams.microsoft.com>.
2. Sign in with an ABS tenant identity that has app-upload rights.
3. **Apps → Import app → Replace** (or **Import an existing app** if first time).
4. Select `skills-registry-plugin.zip`.
5. Open the imported app → **Validation → Run validation**. Should pass with
   no blockers; warnings about icons are fine.
6. **Publish → Publish to your org** (the org-app catalogue). Approval may
   need a tenant admin in some configurations — if so, the request
   appears in the M365 admin centre under Teams apps → Manage apps → Pending.

### Option B — M365 admin centre (if Developer Portal is locked down)

1. M365 admin centre → **Teams apps → Manage apps → Upload new app**.
2. Upload the zip. It lands as a custom app.
3. Approve it (your account needs Teams Service Admin or Global Admin).

Either way, the plugin then needs to be **installed** on the Cowork
agent before it's visible in chat.

## Step 5 — install the plugin on a Cowork agent

1. In Cowork (or Copilot Studio if that's the agent host), open the agent
   that will gain the skill.
2. **Tools → Add → From your organisation → Skills Registry**.
3. Approve any consent prompts. The connector is `authorization.type: None`
   in the manifest, so there's no token exchange to configure.

## Step 6 — live test

In the Cowork agent's chat, run these prompts and verify the agent uses
the registry rather than hallucinating:

| Prompt | Expected tool call | Expected answer hints |
|---|---|---|
| "What skills are there for extracting invoices?" | `find_skill_by_capability(tag="invoice.extract")` | One hit: `finance-invoice-extract`, version 0.1.0, stage `published` |
| "List every capability the org has." | `list_capabilities()` | Map of tags → skill IDs; covers all manifests in `examples/` |
| "Tell me everything about finance-invoice-extract." | `describe_skill(skill_id="finance-invoice-extract")` | Full manifest JSON + (in `local` mode only) `payloadFiles: ["skill://finance-invoice-extract/SKILL.md", ...]` |

If the agent answers without calling a tool, the connector isn't bound —
re-check Step 5.

## Step 7 — capture evidence + tear down (optional)

For the live-test write-up:

```bash
# Re-run smoke test and capture the trace
python tools/smoke-test-mcp.py "$MCP_URL" > docs/stage-b-evidence.txt
```

Drop a screenshot of the Cowork conversation into
`docs/stage-b-evidence/` (gitignored binary; the markdown referencing it
is enough for the PR write-up).

If you're tearing the spike down to keep costs at zero:

```bash
az group delete --name rg-skillsregistry-uks --yes --no-wait
```

That removes Stage 2 + Stage 3 in one shot. To keep Stage 2 (the catalog
is < £0.05/month) and only kill Stage 3:

```bash
az resource delete \
  --resource-group rg-skillsregistry-uks \
  --name ca-skills-registry-mcp \
  --resource-type Microsoft.App/containerApps
az resource delete \
  --resource-group rg-skillsregistry-uks \
  --name $(az containerapp env list -g rg-skillsregistry-uks --query "[0].name" -o tsv) \
  --resource-type Microsoft.App/managedEnvironments
# ACR + Log Analytics last:
az acr delete -g rg-skillsregistry-uks -n <acrName> --yes
az monitor log-analytics workspace delete \
  -g rg-skillsregistry-uks --workspace-name <workspaceName> --yes
```

## What "done" looks like for Stage B

- [ ] `./infra/stage-3/deploy.sh` ran clean and printed an `mcpServerUrl`
- [ ] `python tools/smoke-test-mcp.py $MCP_URL` exits 0
- [ ] `python tools/build-cowork-plugin.py $MCP_URL` produced a zip
- [ ] Zip uploaded + approved in the ABS tenant
- [ ] Cowork agent successfully called all three read tools
- [ ] (Optional) screenshot + smoke-test transcript saved as evidence

Once those six boxes are ticked, Stage B is closed. The next decision —
documented in [`docs/complexity-review.md`](complexity-review.md) — is
whether to promote any of this beyond the spike, or to keep it as the
template-of-record while the real work moves into the customer's
production tenancy.

## Troubleshooting cheat-sheet

| Failure mode | Where to look |
|---|---|
| `az acr build` permission denied | `az role assignment list --assignee <upn> --scope $(az acr show -n <acr> --query id -o tsv)` — needs `AcrPush` or `Contributor` |
| Container App stuck in `Activating` | `az containerapp logs show -g rg-skillsregistry-uks -n ca-skills-registry-mcp --follow` — usually an import error in `mcp-server/server.py` |
| Smoke test fails on `initialize` | The image is older than the FastMCP version expected. Re-run `az acr build` then `az containerapp update --image <acr>.azurecr.io/skills-registry-mcp:latest` |
| Teams Developer Portal rejects zip | The zip layout is wrong (manifest.json must be at root, not nested). `unzip -l skills-registry-plugin.zip` should show `manifest.json` first, no leading folder |
| Cowork agent never calls a tool | Plugin isn't installed on the *agent* even though it's published to the tenant. Step 5. |
| Remote-mode `describe_skill` empty | Catalog at `CATALOG_URL` is summary-only. Re-run `lite.py index` (it embeds full manifests by default) and re-upload |
