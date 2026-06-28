// Stage 2: publishes the rolled-up skill catalog as a single public-read blob.
// Footprint: one storage account, one container. Expected cost < £0.05/month.
// See ../../docs/stage-2-plan.md for the full rationale.
//
// NOT YET DEPLOYED. Validate locally before any `az deployment group create`:
//   az bicep build --file infra/stage-2/main.bicep
//
// To deploy (after the pre-flight checklist in stage-2-plan.md):
//   az deployment group create \
//     --resource-group rg-skillsregistry-uks \
//     --template-file infra/stage-2/main.bicep \
//     --parameters location=uksouth

@description('Azure region for all resources.')
param location string = resourceGroup().location

@description('Base name for the storage account. A 6-char hash is appended so the result is globally unique.')
@minLength(3)
@maxLength(18)
param storageBaseName string = 'skillsregistry'

@description('Name of the blob container that holds catalog.json.')
param containerName string = 'catalog'

@description('Tag applied to every resource for cost tracking.')
param costCenter string = 'skills-registry'

var storageAccountName = toLower('${storageBaseName}${uniqueString(resourceGroup().id)}')

resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: storageAccountName
  location: location
  sku: {
    name: 'Standard_LRS'
  }
  kind: 'StorageV2'
  properties: {
    accessTier: 'Hot'
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
    allowBlobPublicAccess: true
    allowSharedKeyAccess: false
  }
  tags: {
    costCenter: costCenter
    stage: 'stage-2'
    managedBy: 'bicep'
  }
}

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: storage
  name: 'default'
  properties: {
    deleteRetentionPolicy: {
      enabled: true
      days: 7
    }
  }
}

// Public-read container: the catalog is non-sensitive metadata and agents
// need to fetch it without auth. Sensitive material lives in the underlying
// MCP servers, which already have their own auth.
resource container 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobService
  name: containerName
  properties: {
    publicAccess: 'Blob'
  }
}

@description('Public URL the catalog blob will be served from once uploaded.')
output catalogUrl string = '${storage.properties.primaryEndpoints.blob}${containerName}/catalog.json'

@description('Storage account name — feed into `az storage blob upload --account-name`.')
output storageAccountName string = storage.name

@description('Container name — feed into `az storage blob upload --container-name`.')
output containerName string = containerName
