# Fabric IQ — Ontology setup runbook

> Goal: stand up the Microsoft Fabric footprint that backs the registry's
> `query_ontology` MCP tool. After this runs, an agent can ask
> *"what depends on `legal.redline`?"* and the answer comes from a Fabric
> Lakehouse instead of local parquet.
>
> **You don't need this to demo `query_ontology` today** — the tool ships with
> a local DuckDB backend that reads `prototype/out/fabric/*.parquet` directly.
> Fabric is the production swap, not a prerequisite.

---

## What gets provisioned

| Layer | Resource | Bicep | Manual |
|---|---|---|---|
| Fabric capacity | F64 trial (60 days free) | — | portal |
| OneLake shortcut | parquet → Lakehouse → SQL endpoint | — | portal |
| ADLS Gen2 (parquet drop) | storage account + filesystem | ✅ | — |
| Service principal | `skills-ontology-reader` | — | `az ad sp create-for-rbac` |
| RBAC | SP → Storage Blob Data Reader; SP → Key Vault Secrets User | ✅ | — |
| Key Vault | holds SP secret + Fabric SQL URI | ✅ | — |

Bicep covers everything that has a control-plane API. Fabric capacity, OneLake
shortcuts, and SP creation each require a portal/CLI step the ARM API doesn't
expose.

---

## Section 1 — Enrol in the Fabric free trial

1. Go to <https://app.fabric.microsoft.com/>.
2. Sign in with the tenant you want the ontology to live in.
3. Click your profile (top-right) → **Start trial** under *Microsoft Fabric (Free)*.
4. Confirm the **F64** trial capacity gets provisioned (it shows up under
   *Admin portal → Capacity settings → Fabric capacity*). Note the
   **workspace name** and **capacity name** — you'll need them in section 3.

The trial runs 60 days. If you let it lapse without buying capacity, the
Lakehouse goes read-only and your parquet stays put — no data loss, but
`query_ontology` against Fabric stops answering until capacity is reinstated.
Local DuckDB mode keeps working either way.

---

## Section 2 — Run the Bicep

Pre-flight:

```bash
# 1. Create the service principal the MCP server will use to query Fabric SQL.
az ad sp create-for-rbac --name skills-ontology-reader --skip-assignment
# Note the appId, password, and tenant in the output. Stash the password — it
# is shown ONCE. We will load it into Key Vault in section 4.

# 2. Grab the SP's object id (NOT the appId — Bicep needs the object id):
az ad sp show --id <appId> --query id -o tsv

# 3. Create the resource group:
az group create --name rg-skillsregistry-fabric-uks --location uksouth

# 4. Fill in parameters.example.json (mcpServerPrincipalObjectId in particular)
#    and save as parameters.json (gitignored).
cp infra/fabric-iq/parameters.example.json infra/fabric-iq/parameters.json
# edit parameters.json: paste the SP object id you got in step 2.
```

Validate before deploy:

```bash
az bicep build --file infra/fabric-iq/main.bicep
```

Deploy:

```bash
az deployment group create \
  --resource-group rg-skillsregistry-fabric-uks \
  --template-file infra/fabric-iq/main.bicep \
  --parameters @infra/fabric-iq/parameters.json
```

The deployment outputs three things you need next:

* `storageAccountName` — for the parquet upload.
* `dfsEndpoint` — the source URL for the OneLake shortcut.
* `keyVaultUri` — for the Container App secrets mount.

---

## Section 3 — Upload parquet + create the OneLake shortcut

Build the parquet locally and push to ADLS:

```bash
python -m prototype.chassis.fabric_export --out prototype/out/fabric/

ACCOUNT=$(az deployment group show \
  --resource-group rg-skillsregistry-fabric-uks \
  --name main \
  --query properties.outputs.storageAccountName.value -o tsv)

for f in nodes.parquet edges.parquet manifests.parquet _schema_version.txt; do
  az storage blob upload \
    --account-name "$ACCOUNT" \
    --container-name ontology \
    --file "prototype/out/fabric/$f" \
    --name "$f" \
    --auth-mode login \
    --overwrite
done
```

Now wire the parquet into Fabric via a OneLake shortcut (portal step — no API):

1. In <https://app.fabric.microsoft.com/>, open your workspace.
2. **+ New item → Lakehouse**. Name it `skills_ontology`.
3. In the new Lakehouse, **Files → ... → New shortcut → Azure Data Lake
   Storage Gen2**.
4. URL = the `dfsEndpoint` from section 2 (e.g.
   `https://skillsont….dfs.core.windows.net/ontology`).
5. Auth = **Organizational account** (your user) for the shortcut creation;
   the SP you provisioned in section 2 is what the MCP server uses at runtime.
6. Once the shortcut shows three parquet files, click each one and pick
   **Load to tables** so a SQL view materialises (nodes, edges, manifests).

The Lakehouse auto-provisions a **SQL analytics endpoint**. Open the
Lakehouse, click the **SQL endpoint** toggle (top-right), and copy the
connection string. That's `FABRIC_SQL_ENDPOINT`.

---

## Section 4 — Wire the MCP server

Load the SP password and SQL endpoint into Key Vault:

```bash
KV_URI=$(az deployment group show \
  --resource-group rg-skillsregistry-fabric-uks \
  --name main \
  --query properties.outputs.keyVaultUri.value -o tsv)
KV_NAME=$(echo "$KV_URI" | sed -E 's|https://([^.]+)\..*|\1|')

# SP secret (the password you stashed in section 2):
az keyvault secret set \
  --vault-name "$KV_NAME" \
  --name skills-ontology-reader-secret \
  --value "<sp-password>"

# Fabric SQL endpoint (copied from the Lakehouse in section 3):
az keyvault secret set \
  --vault-name "$KV_NAME" \
  --name fabric-sql-endpoint \
  --value "<your-fabric-sql-endpoint>"
```

Update the Container App env vars:

```
ONTOLOGY_BACKEND=fabric
FABRIC_SQL_ENDPOINT=<from-key-vault>     # or reference the KV secret
AZURE_CLIENT_ID=<sp-appId>
AZURE_TENANT_ID=<sp-tenant>
AZURE_CLIENT_SECRET=<from-key-vault>
```

Restart the revision. `GET /api/mcp` should still list `query_ontology` in
the tools array; tool calls now route to Fabric SQL.

---

## Section 5 — Smoke test

From any MCP client (Cowork, Claude Desktop, curl):

```bash
curl -s -X POST https://<your-container-app>/api/mcp \
  -H 'content-type: application/json' \
  -H 'accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call",
       "params":{"name":"query_ontology",
                 "arguments":{"seed":"legal/msa-redlining",
                              "relation":"DEPENDS_ON",
                              "max_hops":3,
                              "caller_classification":"confidential"}}}'
```

Expect a JSON envelope with `paths` listing the `legal/msa-redlining
→ DEPENDS_ON → docx.create` hop. Latency target: < 2s for a 10k-node graph
(Fabric Direct Lake hits this comfortably; DuckDB local is ~50ms on this
size catalog).

---

## Rollback / teardown

```bash
# Delete the Fabric workspace from the portal (the Lakehouse + shortcut go
# with it). Capacity stays until trial expiry — no charge.

# Tear down the Azure footprint:
az group delete --name rg-skillsregistry-fabric-uks --yes --no-wait

# Revoke the SP:
az ad sp delete --id <appId>

# Flip the MCP server back to local DuckDB:
#   ONTOLOGY_BACKEND=local
```

The parquet files in `prototype/out/fabric/` are local artifacts; they stay
on disk and `ONTOLOGY_BACKEND=local` keeps answering queries against them.
