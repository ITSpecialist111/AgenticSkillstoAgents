#!/usr/bin/env bash
# Stage 3 deploy — create the Container Apps stack, build+push the image, then
# print the MCP server URL the Cowork plugin connects to.
#
# Idempotent: every step is safe to re-run. Defaults match docs/stage-b-runbook.md.
#
# Required env (set before running, or accept the defaults):
#   RG               resource group name              (default: rg-skillsregistry-uks)
#   LOCATION         Azure region                     (default: uksouth)
#   CATALOG_MODE     local | remote                   (default: local)
#   CATALOG_URL      Stage 2 blob URL                 (required iff CATALOG_MODE=remote)
#   IMAGE_TAG        image tag                        (default: latest)
#
# Prereqs:
#   - az login completed against the ABS tenant
#   - subscription set: az account set --subscription "<sub-name-or-id>"
#
# Usage:
#   ./infra/stage-3/deploy.sh
#   CATALOG_MODE=remote CATALOG_URL=https://.../catalog.json ./infra/stage-3/deploy.sh

set -euo pipefail

RG="${RG:-rg-skillsregistry-uks}"
LOCATION="${LOCATION:-uksouth}"
CATALOG_MODE="${CATALOG_MODE:-local}"
CATALOG_URL="${CATALOG_URL:-}"
IMAGE_TAG="${IMAGE_TAG:-latest}"

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
REPO_ROOT="$( cd "${SCRIPT_DIR}/../.." && pwd )"
TEMPLATE="${SCRIPT_DIR}/main.bicep"

if [[ "${CATALOG_MODE}" == "remote" && -z "${CATALOG_URL}" ]]; then
  echo "ERROR: CATALOG_MODE=remote needs CATALOG_URL (the Stage 2 blob URL)." >&2
  exit 1
fi

echo "==> Resource group: ${RG} (${LOCATION})"
az group create --name "${RG}" --location "${LOCATION}" --output none

echo "==> Phase 1/3: Bicep deploy (ACR + Log Analytics + Container Apps env, no app yet)"
PHASE1_OUT="$(az deployment group create \
  --resource-group "${RG}" \
  --name stage3-phase1 \
  --template-file "${TEMPLATE}" \
  --parameters \
      location="${LOCATION}" \
      catalogMode="${CATALOG_MODE}" \
      catalogUrl="${CATALOG_URL}" \
      imageTag="${IMAGE_TAG}" \
      deployApp=false \
  --query "properties.outputs" \
  -o json)"

ACR_NAME="$(echo "${PHASE1_OUT}" | python -c "import json,sys;print(json.load(sys.stdin)['acrName']['value'])")"

echo "==> ACR: ${ACR_NAME}"
echo "==> Phase 2/3: Building + pushing image via 'az acr build'"
# --no-logs avoids a Windows-only Azure CLI crash where colorama log-streaming
# can't encode non-cp1252 build output (pip install ASCII-art bars etc.) and
# aborts the local CLI even though the remote build succeeded. PYTHONIOENCODING
# doesn't propagate through az.cmd, so suppressing the stream is the cleanest
# cross-platform fix. Tail logs with: az acr task logs --registry <acr> --run-id <id>
az acr build \
  --registry "${ACR_NAME}" \
  --image "skills-registry-mcp:${IMAGE_TAG}" \
  --file "${REPO_ROOT}/mcp-server/Dockerfile" \
  --no-logs \
  "${REPO_ROOT}"

echo "==> Phase 3/3: Bicep deploy (Container App, now that the image exists)"
DEPLOY_OUT="$(az deployment group create \
  --resource-group "${RG}" \
  --name stage3-phase2 \
  --template-file "${TEMPLATE}" \
  --parameters \
      location="${LOCATION}" \
      catalogMode="${CATALOG_MODE}" \
      catalogUrl="${CATALOG_URL}" \
      imageTag="${IMAGE_TAG}" \
      deployApp=true \
  --query "properties.outputs" \
  -o json)"

MCP_URL="$(echo "${DEPLOY_OUT}" | python -c "import json,sys;print(json.load(sys.stdin)['mcpServerUrl']['value'])")"
FQDN="$(echo "${DEPLOY_OUT}" | python -c "import json,sys;print(json.load(sys.stdin)['containerAppFqdn']['value'])")"

# Re-applying Phase 3 is a no-op when nothing changed; on re-runs (new image
# tag, new env) it picks up the new image without a separate restart.

echo ""
echo "=============================================================="
echo "  MCP server URL: ${MCP_URL}"
echo "  FQDN:           ${FQDN}"
echo "=============================================================="
echo ""
echo "Next steps:"
echo "  1. Smoke-test:  python tools/smoke-test-mcp.py ${MCP_URL}"
echo "  2. Build plugin: python tools/build-cowork-plugin.py ${MCP_URL}"
echo "  3. Upload skills-registry-plugin.zip via Teams Developer Portal."
