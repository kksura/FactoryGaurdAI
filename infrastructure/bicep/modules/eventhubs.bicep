// Event Hubs namespace — deployed only when streaming ingestion is enabled
// (spec §13: 'only if streaming is enabled'; local ingestion stays batch+REST
// per ADR-0021). Local (SAS) auth disabled: producers/consumers use Entra.

param location string
param namePrefix string
param tags object
param logAnalyticsId string
param nameSuffix string

resource namespace 'Microsoft.EventHub/namespaces@2024-01-01' = {
  name: 'evhns-${namePrefix}-${nameSuffix}'
  location: location
  tags: tags
  sku: { name: 'Standard', tier: 'Standard', capacity: 1 }
  properties: {
    disableLocalAuth: true
    minimumTlsVersion: '1.2'
    publicNetworkAccess: 'Disabled'
    isAutoInflateEnabled: true
    maximumThroughputUnits: 4
  }
}

resource telemetryHub 'Microsoft.EventHub/namespaces/eventhubs@2024-01-01' = {
  parent: namespace
  name: 'unit-telemetry'
  properties: {
    partitionCount: 4
    messageRetentionInDays: 1
  }
}

resource consumerGroup 'Microsoft.EventHub/namespaces/eventhubs/consumergroups@2024-01-01' = {
  parent: telemetryHub
  name: 'factoryguard-ingest'
}

resource diagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  name: 'diag-${namespace.name}'
  scope: namespace
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

output namespaceId string = namespace.id
output namespaceName string = namespace.name
