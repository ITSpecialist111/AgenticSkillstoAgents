# Stage 2 deployment plan — published catalog in Azure Blob Storage

> **Status:** PLAN ONLY. Nothing in this document has been deployed. The Bicep
> template at [`infra/stage-2/main.bicep`](../infra/stage-2/main.bicep) is
> ready, but it is **not** wired into CI and no `az deployment` command has
> been run. Stage 1 (the GitHub Actions Register gate) is the only thing live
> today.

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
3. Confirm the GitHub repo has a `Microsoft Azure` federated credential
   for the workflow (OIDC, not a long-lived SP secret). This is the
   one piece that requires a portal click; see
   [Microsoft Learn: GitHub OIDC](https://learn.microsoft.com/en-us/azure/developer/github/connect-from-azure-openid-connect).

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
2. `infra/stage-2/parameters.uksouth.json` — once the user has chosen
   their resource-group / location, capture the exact parameters so the
   deployment is reproducible.
3. A line in the root README pointing agents at the catalog URL.

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
