// Key Vault: RBAC-only, private access, soft delete + purge protection.
// No access policies (RBAC data-plane), no secrets in templates (ADR-0013).

param location string
param namePrefix string
param tags object
param logAnalyticsId string

@description('Purge protection cannot be disabled once on; keep on wherever data matters.')
param enablePurgeProtection bool = true

@description('Deterministic per-subscription suffix keeping the 24-char global name unique.')
param nameSuffix string

resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: take('kv-${namePrefix}-${nameSuffix}', 24)
  location: location
  tags: tags
  properties: {
    tenantId: tenant().tenantId
    sku: { family: 'A', name: 'standard' }
    enableRbacAuthorization: true
    enableSoftDelete: true
    softDeleteRetentionInDays: 90
    enablePurgeProtection: enablePurgeProtection ? true : null
    publicNetworkAccess: 'Disabled'
    networkAcls: {
      defaultAction: 'Deny'
      bypass: 'AzureServices' // trusted-services path for ARM template KV references at deploy time
    }
  }
}

resource diagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  name: 'diag-${keyVault.name}'
  scope: keyVault
  properties: {
    workspaceId: logAnalyticsId
    logs: [
      { categoryGroup: 'audit', enabled: true }
    ]
    metrics: [
      { category: 'AllMetrics', enabled: true }
    ]
  }
}

output keyVaultId string = keyVault.id
output keyVaultName string = keyVault.name
output keyVaultUri string = keyVault.properties.vaultUri
