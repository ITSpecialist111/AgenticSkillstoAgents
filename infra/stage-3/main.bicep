// Stage 3 - host the registry MCP server on Azure Container Apps so a Cowork
// tenant (or any other MCP client) can reach it over HTTPS.
//
// Topology (mirrors the proven TomTom Map Cowork POC):
//   Azure Container Registry (Basic)  -> holds the image
//   Log Analytics workspace           -> Container Apps logs
//   Container Apps Environment        -> Consumption profile
//   Container App                     -> single replica, public ingress on 8000,
//                                        /api/mcp exposed via the FastMCP
//                                        streamable-HTTP transport.
//
// Estimated cost: Container Apps Consumption gives ~180k vCPU-seconds + 360k
// GiB-seconds free per month. At realistic registry traffic (<<1 req/min) this
// stays effectively £0.
//
// Build + push the image (separate command, outside this template):
//   az acr build \
//     --registry <acrName from outputs> \
//     --image skills-registry-mcp:latest \
//     --file mcp-server/Dockerfile \
//     .

targetScope = 'resourceGroup'

@description('Short suffix to keep resource names unique within the tenant. Defaults to a hash of the resource group id.')
param nameSuffix string = uniqueString(resourceGroup().id)

@description('Azure region. Defaults to the resource group location.')
param location string = resourceGroup().location

@description('Image tag to deploy. Bump on each rebuild.')
param imageTag string = 'latest'

@description('Catalog backend. local = bundled examples baked into the image (default). remote = pull catalog.json from REGISTRY_CATALOG_URL (Stage 2).')
@allowed([
  'local'
  'remote'
])
param catalogMode string = 'local'

@description('Required when catalogMode = remote. The public URL of the Stage 2 catalog.json blob.')
param catalogUrl string = ''

@description('Set false on the first deploy so the Container App is skipped while ACR is still empty. Set true after `az acr build` has pushed the image.')
param deployApp bool = true

var acrName = 'acrskills${nameSuffix}'
var lawName = 'law-skills-${nameSuffix}'
var caeName = 'cae-skills-${nameSuffix}'
var appName = 'ca-skills-registry-mcp'
var imageRef = '${acrName}.azurecr.io/skills-registry-mcp:${imageTag}'

resource acr 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: acrName
  location: location
  sku: {
    name: 'Basic'
  }
  properties: {
    adminUserEnabled: true // simplest auth for the spike; switch to managed identity in promotion
  }
}

resource law 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: lawName
  location: location
  properties: {
    sku: {
      name: 'PerGB2018'
    }
    retentionInDays: 30
  }
}

resource environment 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: caeName
  location: location
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: law.properties.customerId
        sharedKey: law.listKeys().primarySharedKey
      }
    }
  }
}

resource app 'Microsoft.App/containerApps@2024-03-01' = if (deployApp) {
  name: appName
  location: location
  properties: {
    managedEnvironmentId: environment.id
    configuration: {
      ingress: {
        external: true
        targetPort: 8000
        transport: 'auto'
        allowInsecure: false
      }
      registries: [
        {
          server: '${acrName}.azurecr.io'
          username: acr.listCredentials().username
          passwordSecretRef: 'acr-password'
        }
      ]
      secrets: [
        {
          name: 'acr-password'
          value: acr.listCredentials().passwords[0].value
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'mcp'
          image: imageRef
          resources: {
            cpu: json('0.25')
            memory: '0.5Gi'
          }
          env: [
            {
              name: 'MCP_TRANSPORT'
              value: 'http'
            }
            {
              name: 'HOST'
              value: '0.0.0.0'
            }
            {
              name: 'PORT'
              value: '8000'
            }
            {
              name: 'REGISTRY_CATALOG_MODE'
              value: catalogMode
            }
            {
              name: 'REGISTRY_CATALOG_URL'
              value: catalogUrl
            }
          ]
          probes: [
            {
              type: 'Liveness'
              httpGet: {
                path: '/health'
                port: 8000
              }
              initialDelaySeconds: 5
              periodSeconds: 30
            }
          ]
        }
      ]
      scale: {
        minReplicas: 0
        maxReplicas: 1
      }
    }
  }
}

@description('The public HTTPS endpoint Cowork connects to. Empty when deployApp=false. Paste this into cowork-plugin/manifest.json (agentConnectors[0].remoteMcpServer.mcpServerUrl).')
output mcpServerUrl string = deployApp ? 'https://${app.properties.configuration.ingress.fqdn}/api/mcp' : ''

@description('FQDN of the deployed Container App. Empty when deployApp=false.')
output containerAppFqdn string = deployApp ? app.properties.configuration.ingress.fqdn : ''

@description('Name of the Container Registry. Pass to `az acr build --registry <this>`.')
output acrName string = acr.name

@description('Log Analytics workspace name (for `az monitor log-analytics query` follow-ups).')
output logAnalyticsWorkspace string = law.name
