// Log Analytics + workspace-based Application Insights (spec §20).
// OTel from the API flows to App Insights via the connection string exposed
// as an output (a connection string is routing metadata, not a credential —
// ingestion is further protected by Entra auth when enforced below).

param location string
param namePrefix string
param tags object

@minValue(30)
@maxValue(730)
param retentionInDays int = 90

@description('Daily ingestion cap in GB; -1 disables the cap (prod).')
param dailyQuotaGb int = -1

resource logAnalytics 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: 'log-${namePrefix}'
  location: location
  tags: tags
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: retentionInDays
    workspaceCapping: { dailyQuotaGb: dailyQuotaGb }
    features: { disableLocalAuth: false } // Container Apps env log export still needs the shared key
    publicNetworkAccessForIngestion: 'Enabled' // AMPLS documented as the hardening step, docs/architecture/network-topology.md
    publicNetworkAccessForQuery: 'Enabled'
  }
}

resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: 'appi-${namePrefix}'
  location: location
  tags: tags
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: logAnalytics.id
    IngestionMode: 'LogAnalytics'
    DisableLocalAuth: true // OTel exporters authenticate with Entra (managed identity), not instrumentation keys
    publicNetworkAccessForIngestion: 'Enabled'
    publicNetworkAccessForQuery: 'Enabled'
  }
}

output logAnalyticsId string = logAnalytics.id
output logAnalyticsName string = logAnalytics.name
output logAnalyticsCustomerId string = logAnalytics.properties.customerId
output appInsightsId string = appInsights.id
output appInsightsConnectionString string = appInsights.properties.ConnectionString
