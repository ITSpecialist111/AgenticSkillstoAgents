// Stage D / Fabric IQ: provisions the Azure footprint around a Microsoft
// Fabric workspace so the skills-registry MCP server can query an ontology
// hosted in OneLake.
//
// This template does NOT provision Fabric capacity itself — that is a portal
// click during the free 60-day trial enrolment (see docs/fabric-iq-setup.md).
// Everything else (ADLS Gen2 for the parquet drop, service principal for the
// MCP server to authenticate against the Fabric SQL endpoint, Key Vault for
// the SP secret) is declarative.
//
// Footprint: 1 storage account (HNS-enabled), 1 Key Vault, 1 service principal
// (created via portal/CLI — Bicep cannot create SPs directly). Expected
// cost < £1/month at this scale.
//
// Validate before deploy:
//   az bicep build --file infra/fabric-iq/main.bicep
//
// Deploy (after creating the resource group):
//   az deployment group create \
//     --resource-group rg-skillsregistry-fabric-uks \
//     --template-file infra/fabric-iq/main.bicep \
//     --parameters @infra/fabric-iq/parameters.example.json

@description('Azure region for all resources. Match your Fabric capacity region to avoid egress.')
param location string = resourceGroup().location

@description('Base name for the storage account. A uniqueString hash is appended for global uniqueness; total stays within the 24-char Azure limit.')
@minLength(3)
@maxLength(11)
param storageBaseName string = 'skillsont'

@description('Name of the ADLS Gen2 filesystem (container) that holds nodes/edges/manifests parquet.')
param filesystemName string = 'ontology'

@description('Object ID of the service principal the MCP server uses to query Fabric SQL. Create it first with `az ad sp create-for-rbac --name skills-ontology-reader` and pass its objectId here.')
param mcpServerPrincipalObjectId string

@description('Name of the Key Vault that stores the SP secret + the Fabric SQL endpoint URI.')
@minLength(3)
@maxLength(20)
param keyVaultBaseName string = 'skillsont'

@description('Tag applied to every resource for cost tracking.')
param costCenter string = 'skills-registry'

var storageAccountName = toLower('${storageBaseName}${uniqueString(resourceGroup().id)}')
var keyVaultName = toLower('${keyVaultBaseName}${uniqueString(resourceGroup().id)}')

// ADLS Gen2 storage account: hierarchical namespace is required so Fabric can
// shortcut it into a Lakehouse. NOT public — read access is via the SP only.
resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: storageAccountName
  location: location
  sku: {
    name: 'Standard_LRS'
  }
  kind: 'StorageV2'
  properties: {
    accessTier: 'Hot'
    isHnsEnabled: true                // required for OneLake shortcut
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
    allowBlobPublicAccess: false
    allowSharedKeyAccess: false       // force Entra ID auth — no account keys
  }
  tags: {
    costCenter: costCenter
    stage: 'fabric-iq'
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

resource filesystem 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobService
  name: filesystemName
  properties: {
    publicAccess: 'None'
  }
}

// Grant the MCP server's SP read access on the parquet drop. The Fabric SQL
// endpoint inherits this via the OneLake shortcut for query-time access.
var storageBlobDataReaderRoleId = '2a2b9908-6ea1-4ae2-8e65-a410df84e7d1'

resource spStorageReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: filesystem
  name: guid(filesystem.id, mcpServerPrincipalObjectId, storageBlobDataReaderRoleId)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageBlobDataReaderRoleId)
    principalId: mcpServerPrincipalObjectId
    principalType: 'ServicePrincipal'
  }
}

// Key Vault holds the SP client secret + the Fabric SQL endpoint URI so the
// Container App can mount them as secrets at runtime (no rotation in code).
resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: keyVaultName
  location: location
  properties: {
    tenantId: subscription().tenantId
    sku: {
      family: 'A'
      name: 'standard'
    }
    enableRbacAuthorization: true
    enableSoftDelete: true
    softDeleteRetentionInDays: 7
    publicNetworkAccess: 'Enabled'
  }
  tags: {
    costCenter: costCenter
    stage: 'fabric-iq'
    managedBy: 'bicep'
  }
}

// SP needs to read its own secret out of the vault at startup.
var keyVaultSecretsUserRoleId = '4633458b-17de-408a-b874-0445c86b69e6'

resource spKeyVaultReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: keyVault
  name: guid(keyVault.id, mcpServerPrincipalObjectId, keyVaultSecretsUserRoleId)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', keyVaultSecretsUserRoleId)
    principalId: mcpServerPrincipalObjectId
    principalType: 'ServicePrincipal'
  }
}

@description('Storage account name — feed into `az storage blob upload --account-name`.')
output storageAccountName string = storage.name

@description('ADLS Gen2 filesystem name where parquet files are uploaded.')
output filesystemName string = filesystemName

@description('DFS endpoint — use this as the source URL when creating the OneLake shortcut in the Fabric portal.')
output dfsEndpoint string = '${storage.properties.primaryEndpoints.dfs}${filesystemName}'

@description('Key Vault URI — set MCP_SECRETS_KEYVAULT_URI to this in the Container App.')
output keyVaultUri string = keyVault.properties.vaultUri
