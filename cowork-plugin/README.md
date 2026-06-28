# Cowork plugin — Skills Registry

A Microsoft Teams app package that exposes the [skills registry](../README.md)
to Microsoft Copilot Cowork as a plugin. Three read-only MCP tools:

- `find_skill_by_capability(tag)` — "who can do X?"
- `describe_skill(skill_id)` — full manifest with governance + scoring
- `list_capabilities()` — the inventory

The plugin is a thin wrapper. The actual MCP server lives in
[`mcp-server/`](../mcp-server) and is hosted on Azure Container Apps via
[`infra/stage-3/main.bicep`](../infra/stage-3). See
[`docs/cowork-plugin-spike.md`](../docs/cowork-plugin-spike.md) for the
full spec, including the TomTom POC pattern this is modelled on.

## Files

| File | Purpose |
|---|---|
| `manifest.json` | Teams app manifest v1.28. Declares `agentSkills` + `agentConnectors`. |
| `toolDescription.json` | Tool schemas the host LLM reads (name, description, input schema, annotations). |
| `skills/skills-registry/SKILL.md` | The "skill card" — tells the host LLM *when* to reach for this plugin. |
| `color.png` | 192×192 colour icon (placeholder — replace before public release). |
| `outline.png` | 32×32 outline icon (placeholder — replace before public release). |

## Build + upload

1. **Deploy the MCP server** to Azure Container Apps. From the repo root:
   ```bash
   az deployment group create \
     --resource-group rg-skillsregistry-uks \
     --template-file infra/stage-3/main.bicep \
     --query properties.outputs
   ```
   Capture the `mcpServerUrl` output — it'll look like
   `https://ca-skills-registry-mcp.<region>.azurecontainerapps.io/api/mcp`.

2. **Edit `manifest.json`** — replace the placeholder
   `REPLACE-ME.azurecontainerapps.io` in
   `agentConnectors[0].remoteMcpServer.mcpServerUrl` and the
   `validDomains` entry with the real host.

3. **Zip the contents** (not the folder itself):
   ```bash
   cd cowork-plugin
   zip -r ../skills-registry-plugin.zip .
   ```

4. **Upload** to the ABS tenant via the Microsoft 365 admin centre or the
   Teams Developer Portal as a custom app.

5. **Install in Cowork** against a test agent. Try:
   - *"What skills do we have for invoice processing?"*
   - *"Find me anything that can do PO matching."*
   - *"What can this org do? Give me the full inventory."*

## Auth

The connector declares `authorization.type: "None"`. Discovery metadata is
non-sensitive — sensitive material lives in the *underlying* skill servers
referenced in each manifest's `mcp` block, which carry their own auth. If
the live test demands Entra auth on the discovery layer too, the TomTom
POC's `/api/connector` path shows the pattern.

## Updating

Every change to `toolDescription.json` or `SKILL.md` should be paired with
a re-upload to keep the tenant's installed copy in sync. The MCP server
itself can be redeployed independently — the URL stays stable.
