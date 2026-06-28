# Stage 2 deployment plan — published catalog in Azure Blob Storage

> **Status:** Workflow shipped, Bicep ready, **not yet deployed**.
> [`.github/workflows/publish-catalog.yml`](../.github/workflows/publish-catalog.yml)
> exists but will fail until the one-time OIDC setup below is done in the
> ABS tenant. Once the storage account exists and the federated credential
> is wired up, every push to `main` republishes the catalog.

## Goal of Stage 2

Make the registry **discoverable by agents without cloning the repo**. Today
an agent has to read `examples/*.manifest.json` from GitHub. Stage 2 publishes
a single rolled-up catalog JSON to a public-read Azure Storage blob, so any
agent (Copilot Studio, Foundry, ad-hoc Python) can `GET` the catalog and
filter by `capabilityTags`.

That's it. No compute. No Cosmos. No Fabric. No Container Apps. Those are
Stages 3 and 4.

## Architecture

```
GitHub PR merged to main
   │
   ▼
.github/workflows/publish-catalog.yml           ◄── added in Stage 2
   │
   ├─ python prototype-lite/lite.py index --out catalog.json
   │
   └─ az storage blob upload --account-name skillsregistry…
                              --container-name catalog
                              --name catalog.json
                              --overwrite

                          ┌──────────────────────────┐
                          │  Azure Blob Storage      │
                          │  skillsregistry<suffix>  │
                          │  container: catalog      │
                          │  blob: catalog.json      │
                          │  access: public read     │
                          └──────────────────────────┘
                                      ▲
                       agents GET https://…/catalog/catalog.json
```

## Resources to be created

One resource group, one storage account, one container, one blob. That is the
entire footprint.

| Resource          | Name pattern              | SKU             | Why                                         |
|-------------------|---------------------------|-----------------|---------------------------------------------|
| Resource group    | `rg-skillsregistry-uks`   | n/a             | Isolation. UK South to match user tenancy.  |
| Storage account   | `skillsregistry<6 chars>` | Standard_LRS    | Cheapest redundancy that still has SLA.     |
| Blob container    | `catalog`                 | public-read     | Catalog is non-sensitive; auth would block agents. |
| Blob              | `catalog.json`            | n/a             | The output of `lite.py index`.              |

Storage account names must be globally unique + 3-24 chars lowercase. The
Bicep template appends `uniqueString(resourceGroup().id)` to satisfy this.

## Cost estimate

| Line item              | Monthly cost                  |
|------------------------|-------------------------------|
| Storage (Standard_LRS) | ≈ £0.015 / GB / month         |
| Catalog blob size      | ≈ 4 KB → effectively £0       |
| Transactions           | first 50k/month ≈ £0.0003     |
| Egress                 | first 100 GB/month free       |
| **Total expected**     | **< £0.05 / month**           |

Source: Azure Storage retail pricing, UK South, December 2025. The
catalog is < 10 KB so storage cost rounds to zero. The dominant cost is
transactions, which agents will trigger maybe 100x/day. This will not
move the needle on any Azure bill.

## Pre-flight checklist (do this once, manually)

1. Log in to the target tenant and confirm subscription:
   ```bash
   az login
   az account show --query "{tenant:tenantId, sub:name, id:id}"
   ```
2. Confirm the user has `Contributor` on the target subscription (or at
   least `Owner` on a new resource group — the Bicep template creates
   no role assignments).
3. Wire up the OIDC federated credential — see
   [OIDC setup](#one-time-oidc-setup-for-publish-catalogyml) below.

## One-time OIDC setup (for `publish-catalog.yml`)

The workflow uses [GitHub OIDC](https://learn.microsoft.com/en-us/azure/developer/github/connect-from-azure-openid-connect)
to assume an Azure identity at runtime — no long-lived secrets in the repo.

1. **Create a User-Assigned Managed Identity (UAMI)** or App Registration in
   the ABS tenant. UAMI is simpler if the storage account already lives in
   the tenant; both work the same from the workflow's point of view.

   ```bash
   az identity create \
     --resource-group rg-skillsregistry-uks \
     --name uami-skillsregistry-publish \
     --location uksouth
   ```

   Capture the `clientId`, `principalId`, and `tenantId` from the output.

2. **Grant the identity `Storage Blob Data Contributor` on the storage account.**
   The workflow uses `--auth-mode login`, which goes through Entra; the role
   must be on the account (not just the container) for blob upload to work.

   ```bash
   STORAGE_ID=$(az storage account show \
     --resource-group rg-skillsregistry-uks \
     --name <storageAccountName from Bicep outputs> \
     --query id -o tsv)

   az role assignment create \
     --assignee-object-id <principalId from step 1> \
     --assignee-principal-type ServicePrincipal \
     --role "Storage Blob Data Contributor" \
     --scope "$STORAGE_ID"
   ```

3. **Add a federated credential pointing at this repo + `main` branch.**

   ```bash
   az identity federated-credential create \
     --identity-name uami-skillsregistry-publish \
     --resource-group rg-skillsregistry-uks \
     --name github-main \
     --issuer https://token.actions.githubusercontent.com \
     --subject repo:ITSpecialist111/AgenticSkillstoAgents:ref:refs/heads/main \
     --audiences api://AzureADTokenExchange
   ```

   Add a second credential for `workflow_dispatch` if you want manual reruns:
   subject `repo:ITSpecialist111/AgenticSkillstoAgents:ref:refs/heads/main`
   is enough for push runs; for branch-specific runs use
   `repo:ITSpecialist111/AgenticSkillstoAgents:pull_request` etc.

4. **Set the GitHub repo secrets and variables.** Settings → Secrets and
   variables → Actions:

   | Secret | Value |
   |---|---|
   | `AZURE_CLIENT_ID` | UAMI `clientId` from step 1 |
   | `AZURE_TENANT_ID` | tenant id |
   | `AZURE_SUBSCRIPTION_ID` | subscription id |
   | `STAGE2_STORAGE_ACCOUNT` | storage account name from Bicep outputs |

   | Variable | Value |
   |---|---|
   | `STAGE2_CONTAINER` | `catalog` (the default; only set if you renamed the container) |

5. **Trigger the first run** via Actions → publish-catalog → "Run workflow"
   on `main`. The job should green in ~30s and the catalog URL is printed
   in the final step.

## Deployment commands (do not run yet — these are for the handoff)

```bash
# 1. Create the resource group (idempotent).
az group create \
  --name rg-skillsregistry-uks \
  --location uksouth

# 2. Deploy the storage account + container.
az deployment group create \
  --resource-group rg-skillsregistry-uks \
  --template-file infra/stage-2/main.bicep \
  --parameters location=uksouth

# 3. Capture the blob URL the deployment emits.
az deployment group show \
  --resource-group rg-skillsregistry-uks \
  --name main \
  --query properties.outputs.catalogUrl.value -o tsv
```

The first publish is then the manual equivalent of the workflow we will add:

```bash
python prototype-lite/lite.py index --out /tmp/catalog.json
az storage blob upload \
  --account-name <name-from-output> \
  --container-name catalog \
  --name catalog.json \
  --file /tmp/catalog.json \
  --auth-mode login \
  --overwrite
```

## What gets added to the repo in Stage 2 (after first deploy)

1. `.github/workflows/publish-catalog.yml` — runs on push to `main`,
   regenerates `catalog.json`, uploads it. Uses OIDC, no secrets in repo.
   **Shipped.**
2. `infra/stage-2/parameters.uksouth.json` — once the user has chosen
   their resource-group / location, capture the exact parameters so the
   deployment is reproducible. *(Optional — single-line `--parameters
   location=uksouth` works fine.)*
3. A line in the root README pointing agents at the catalog URL. *(Add
   once URL is known.)*

## How the MCP server consumes the catalog

Once the catalog is live, switch the registry MCP server into remote mode
by setting two env vars on its deployment:

```
REGISTRY_CATALOG_MODE=remote
REGISTRY_CATALOG_URL=https://<storageAccountName>.blob.core.windows.net/catalog/catalog.json
```

The server `GET`s the blob on first tool call and caches the result for
`REGISTRY_CATALOG_TTL` seconds (default 60). The blob must be produced by
`python lite.py index` *with full manifests embedded* (the default since
Stage A) — a summary-only catalog is rejected at load time. Payloads
(`SKILL.md`, asset schemas) are not published to Blob in this spike, so
`describe_skill().payloadFiles` is an empty list in remote mode.

`infra/stage-3/main.bicep` already wires both env vars through — pass
`--parameters catalogMode=remote catalogUrl=<url>` at deploy time.

## What deliberately is **not** in Stage 2

| Out of scope     | Why deferred                                                    |
|------------------|-----------------------------------------------------------------|
| Cosmos / Fabric  | The catalog fits in 10 KB. A database is solving a non-problem. |
| Container Apps   | No compute is needed to serve a static blob.                    |
| Auth on catalog  | Catalog metadata is non-sensitive by design. Sensitive material lives in the underlying MCP servers, which already have auth. |
| Copilot Studio   | Until the catalog is live and agents are calling it, Stage 4 has no inputs. |

## Promotion to Stage 3 trigger

Only build Stage 3 (compute) when **at least one** of these is true:
- The catalog has > 50 published skills (Mermaid-by-eye stops scaling).
- An agent needs server-side filtering the blob cannot do.
- A second writer (non-GitHub) needs to publish into the registry.

Until then, Stage 2 is the whole production system.
