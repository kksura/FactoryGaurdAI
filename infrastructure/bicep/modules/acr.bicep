// Container registry: Premium (required for private link), admin user off,
// anonymous pull off, pulls happen via managed identity + AcrPull only.

param location string
param namePrefix string
param tags object
param logAnalyticsId string

@minLength(13) // uniqueString() output; the floor keeps the registry name >= 5 chars
param nameSuffix string

resource registry 'Microsoft.ContainerRegistry/registries@2023-11-01-preview' = {
  name: take('cr${replace(namePrefix, '-', '')}${nameSuffix}', 50)
  location: location
  tags: tags
  sku: { name: 'Premium' }
  properties: {
    adminUserEnabled: false
    anonymousPullEnabled: false
    publicNetworkAccess: 'Disabled'
    networkRuleBypassOptions: 'AzureServices' // lets the AML managed network / trusted services pull
    policies: {
      quarantinePolicy: { status: 'disabled' } // enable once a scanner webhook is wired (Phase 8 note)
      retentionPolicy: { status: 'enabled', days: 30 }
      exportPolicy: { status: 'disabled' } // no registry export: images leave only via governed pipelines
    }
  }
}

resource diagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  name: 'diag-${registry.name}'
  scope: registry
  properties: {
    workspaceId: logAnalyticsId
    logs: [
      { categoryGroup: 'allLogs', enabled: true }
    ]
    metrics: [
      { category: 'AllMetrics', enabled: true }
    ]
  }
}

output registryId string = registry.id
output registryName string = registry.name
output loginServer string = registry.properties.loginServer
