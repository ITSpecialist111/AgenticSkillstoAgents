# Stage 3 — Container Apps hosting for the registry MCP server

> **Status:** Spike infrastructure. The Bicep template is here; nothing has
> been deployed. Hosting only matters if the Cowork ABS-tenant live test
> confirms the plugin shape is what Cowork expects. See
> [`docs/cowork-plugin-spike.md`](../../docs/cowork-plugin-spike.md).

## What this template creates

| Resource | SKU | Why |
|---|---|---|
| `acrskills<suffix>` (Container Registry) | Basic | Holds the MCP server image. |
| `law-skills-<suffix>` (Log Analytics) | PerGB2018 | Container Apps logs (30-day retention). |
| `cae-skills-<suffix>` (Container Apps Environment) | Consumption | Shared env. |
| `ca-skills-registry-mcp` (Container App) | 0.25 vCPU / 0.5 GiB, scale 0–1 | The MCP server. Public ingress on 8000. `/api/mcp` is the Cowork connector URL. |

Estimated cost: Container Apps Consumption gives the first ~180k vCPU-seconds
and ~360k GiB-seconds free monthly. At realistic registry traffic
(<<1 req/min) the bill is effectively **£0**. ACR Basic adds ~£3.80/month.

## Pre-flight

1. The resource group from Stage 2 (`rg-skillsregistry-uks`) exists — Stage 3
   reuses it. If not, create it: `az group create -n rg-skillsregistry-uks -l uksouth`.
2. `az` is logged into the correct tenant: `az account show --query "{tenant:tenantId, sub:name}"`.
3. Bicep CLI is available: `az bicep version` (auto-installed on first use).

## Deploy

```bash
# 1. Stand up the infra (ACR, env, app). Image won't exist yet on first run —
#    the app will keep restarting until step 2. That's expected.
az deployment group create \
  --resource-group rg-skillsregistry-uks \
  --template-file infra/stage-3/main.bicep \
  --query properties.outputs

# 2. Build + push the image. From the repo root so the build context can
#    see prototype-lite/, schemas/, and examples/ alongside mcp-server/.
az acr build \
  --registry <acrName from step 1 outputs> \
  --image skills-registry-mcp:latest \
  --file mcp-server/Dockerfile \
  .

# 3. The Container App auto-pulls latest on its next revision. Force a
#    refresh if needed:
az containerapp revision restart \
  --resource-group rg-skillsregistry-uks \
  --name ca-skills-registry-mcp \
  --revision $(az containerapp revision list -g rg-skillsregistry-uks -n ca-skills-registry-mcp --query "[0].name" -o tsv)

# 4. Smoke-test the public endpoint.
curl https://<mcpServerUrl from outputs>            # GET probe — JSON
curl https://<containerAppFqdn>/health              # liveness — {"status":"ok"}
```

The `mcpServerUrl` output is what you paste into
[`cowork-plugin/manifest.json`](../../cowork-plugin/manifest.json).

## Parameters

| Param | Default | When to override |
|---|---|---|
| `nameSuffix` | `uniqueString(rg.id)` | Pin only if you want predictable names across redeploys. |
| `location` | rg location | Override per region. |
| `imageTag` | `latest` | Pin to a digest in promotion-path workflows. |
| `catalogMode` | `local` | Switch to `remote` once Stage 2 is live to pull the catalog from blob. |
| `catalogUrl` | `''` | Required when `catalogMode = remote`. The Stage 2 `catalog.json` public URL. |

## Lint locally (no Azure needed)

```bash
az bicep build --file infra/stage-3/main.bicep --stdout > /dev/null
```

A clean exit means the template compiles.

## Promotion path

1. Switch ACR auth from admin-user (current) to managed identity.
2. Add `.github/workflows/deploy-mcp.yml` to rebuild + redeploy on every push
   to `main` via OIDC. Mirrors the structure of the (future)
   `publish-catalog.yml` workflow from Stage 2.
3. Bump `scale.maxReplicas` if real traffic warrants it; the promotion
   criteria are in [`docs/complexity-review.md`](../../docs/complexity-review.md).

## What's not here

- No Application Insights — Log Analytics is enough for the spike. Add `ai`
  if you start needing distributed-trace correlation.
- No custom domain / TLS cert — the default `*.azurecontainerapps.io` host
  works for Cowork; a real product would front this with API Management.
- No Entra auth on `/api/mcp` itself — the threat model is the same as
  Stage 2 (public catalog metadata). The TomTom POC's `/api/connector`
  path shows the pattern to copy if that changes.
