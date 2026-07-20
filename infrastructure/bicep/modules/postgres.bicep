// Azure Database for PostgreSQL Flexible Server: Entra-only authentication
// (password auth disabled — no database passwords exist anywhere), private
// endpoint access only, TLS required by the platform.

param location string
param namePrefix string
param tags object
param logAnalyticsId string
param nameSuffix string

param skuName string = 'Standard_D2ds_v5'
param skuTier string = 'GeneralPurpose'
param storageSizeGb int = 128
param highAvailabilityMode string = 'Disabled' // 'ZoneRedundant' in prod
param geoRedundantBackup string = 'Disabled' // 'Enabled' in prod

@description('Entra object id set as the PostgreSQL Entra administrator (a group is recommended).')
param entraAdminObjectId string

@description('Display name of that principal.')
param entraAdminPrincipalName string

@allowed(['Group', 'User', 'ServicePrincipal'])
param entraAdminPrincipalType string = 'Group'

resource server 'Microsoft.DBforPostgreSQL/flexibleServers@2024-08-01' = {
  name: 'psql-${namePrefix}-${nameSuffix}'
  location: location
  tags: tags
  sku: { name: skuName, tier: skuTier }
  properties: {
    version: '16'
    authConfig: {
      activeDirectoryAuth: 'Enabled'
      passwordAuth: 'Disabled'
      tenantId: tenant().tenantId
    }
    network: {
      publicNetworkAccess: 'Disabled'
    }
    storage: {
      storageSizeGB: storageSizeGb
      autoGrow: 'Enabled'
    }
    backup: {
      backupRetentionDays: 14
      geoRedundantBackup: geoRedundantBackup
    }
    highAvailability: {
      mode: highAvailabilityMode
    }
  }
}

resource entraAdmin 'Microsoft.DBforPostgreSQL/flexibleServers/administrators@2024-08-01' = {
  parent: server
  name: entraAdminObjectId
  properties: {
    principalType: entraAdminPrincipalType
    principalName: entraAdminPrincipalName
    tenantId: tenant().tenantId
  }
}

resource database 'Microsoft.DBforPostgreSQL/flexibleServers/databases@2024-08-01' = {
  parent: server
  name: 'factoryguard'
  properties: {
    charset: 'UTF8'
    collation: 'en_US.utf8'
  }
}

resource diagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  name: 'diag-${server.name}'
  scope: server
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

output serverId string = server.id
output serverName string = server.name
output serverFqdn string = server.properties.fullyQualifiedDomainName
