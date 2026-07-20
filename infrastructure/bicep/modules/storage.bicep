// Storage account (generic: called once for the ADLS Gen2 data lake and once
// for the blob artifacts/AML-default account — AML default storage cannot have
// hierarchical namespace enabled). Shared-key access is off everywhere: all
// data-plane access is Entra + RBAC (spec §13 'no storage keys').

param location string
param tags object
param logAnalyticsId string

@description('Globally unique storage account name (3-24 lowercase alphanumeric).')
param accountName string

@description('Enable hierarchical namespace (ADLS Gen2).')
param hnsEnabled bool

param skuName string = 'Standard_ZRS'

@description('Blob containers to create.')
param containers array = []

@description('File shares to create (AML workspace needs one on its default account).')
param fileShares array = []

resource storageAccount 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: accountName
  location: location
  tags: tags
  sku: { name: skuName }
  kind: 'StorageV2'
  properties: {
    isHnsEnabled: hnsEnabled
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
    allowBlobPublicAccess: false
    allowSharedKeyAccess: false
    defaultToOAuthAuthentication: true
    publicNetworkAccess: 'Disabled'
    networkAcls: {
      defaultAction: 'Deny'
      bypass: 'AzureServices'
    }
    encryption: {
      keySource: 'Microsoft.Storage' // CMK documented for high assurance, docs/architecture/security-architecture.md
      services: {
        blob: { enabled: true }
        file: { enabled: true }
      }
    }
  }
}

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: storageAccount
  name: 'default'
  properties: {
    deleteRetentionPolicy: { enabled: true, days: 14 }
    containerDeleteRetentionPolicy: { enabled: true, days: 14 }
  }
}

resource blobContainers 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = [
  for container in containers: {
    parent: blobService
    name: container
    properties: { publicAccess: 'None' }
  }
]

resource fileService 'Microsoft.Storage/storageAccounts/fileServices@2023-05-01' = {
  parent: storageAccount
  name: 'default'
}

resource shares 'Microsoft.Storage/storageAccounts/fileServices/shares@2023-05-01' = [
  for share in fileShares: {
    parent: fileService
    name: share
  }
]

resource blobDiagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  name: 'diag-${accountName}-blob'
  scope: blobService
  properties: {
    workspaceId: logAnalyticsId
    logs: [
      { categoryGroup: 'audit', enabled: true }
    ]
    metrics: [
      { category: 'Transaction', enabled: true }
    ]
  }
}

output storageAccountId string = storageAccount.id
output storageAccountName string = storageAccount.name
output blobEndpoint string = storageAccount.properties.primaryEndpoints.blob
