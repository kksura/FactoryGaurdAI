// Resource-group-scope orchestration of the FactoryGuard spoke. Deployed by
// main.bicep; see infrastructure/bicep/README.md for the module map.

param location string
param namePrefix string
param tags object

// Network
param vnetAddressPrefix string
param containerAppsSubnetPrefix string
param privateEndpointsSubnetPrefix string
param egressRouteTableId string = ''

// Feature flags / sizing
param deployEventHubs bool = false
param deployModelRegistry bool = true
param gpuClusterVmSize string = ''
param postgresSkuName string = 'Standard_D2ds_v5'
param postgresSkuTier string = 'GeneralPurpose'
param postgresHaMode string = 'Disabled'
param postgresGeoBackup string = 'Disabled'
param logRetentionInDays int = 90
param storageSkuName string = 'Standard_ZRS'
param policyEnforcementMode string = 'Default'
param zoneRedundant bool = false
param apiMinReplicas int = 1
param apiMaxReplicas int = 5
param hbiWorkspace bool = true

// Identity / auth
param entraAdminObjectId string
param entraAdminPrincipalName string
param entraAdminPrincipalType string = 'Group'
param authTenantId string
param authAudience string = 'api://factoryguard'
param githubRepository string = ''
param githubEnvironment string = ''

// Images (prod: digest-pinned)
param apiImage string
param dashboardImage string
param workerImage string

var nameSuffix = uniqueString(resourceGroup().id)
var storagePrefix = replace(namePrefix, '-', '')

var privateDnsZoneNames = [
  'privatelink.blob.${az.environment().suffixes.storage}'
  'privatelink.dfs.${az.environment().suffixes.storage}'
  'privatelink.file.${az.environment().suffixes.storage}'
  'privatelink.vaultcore.azure.net'
  'privatelink.azurecr.io'
  'privatelink.api.azureml.ms'
  'privatelink.notebooks.azure.net'
  'privatelink.postgres.database.azure.com'
  'privatelink.servicebus.windows.net'
]

module network 'modules/network.bicep' = {
  name: 'network'
  params: {
    location: location
    namePrefix: namePrefix
    tags: tags
    vnetAddressPrefix: vnetAddressPrefix
    containerAppsSubnetPrefix: containerAppsSubnetPrefix
    privateEndpointsSubnetPrefix: privateEndpointsSubnetPrefix
    egressRouteTableId: egressRouteTableId
  }
}

module privateDns 'modules/private-dns.bicep' = {
  name: 'private-dns'
  params: {
    vnetId: network.outputs.vnetId
    zoneNames: privateDnsZoneNames
    tags: tags
  }
}

module monitoring 'modules/monitoring.bicep' = {
  name: 'monitoring'
  params: {
    location: location
    namePrefix: namePrefix
    tags: tags
    retentionInDays: logRetentionInDays
  }
}

module identity 'modules/identity.bicep' = {
  name: 'identity'
  params: {
    location: location
    namePrefix: namePrefix
    tags: tags
    githubRepository: githubRepository
    githubEnvironment: githubEnvironment
  }
}

module keyVault 'modules/keyvault.bicep' = {
  name: 'keyvault'
  params: {
    location: location
    namePrefix: namePrefix
    tags: tags
    logAnalyticsId: monitoring.outputs.logAnalyticsId
    nameSuffix: nameSuffix
  }
}

// ADLS Gen2: curated + raw synthetic data (HNS on).
module dataLake 'modules/storage.bicep' = {
  name: 'storage-datalake'
  params: {
    location: location
    tags: tags
    logAnalyticsId: monitoring.outputs.logAnalyticsId
    accountName: take('st${storagePrefix}data${nameSuffix}', 24)
    hnsEnabled: true
    skuName: storageSkuName
    containers: ['curated', 'raw', 'quarantine']
  }
}

// Blob: model artifacts, images, MLflow artifacts; AML default storage
// (HNS must stay off) with the file share AML requires.
module artifacts 'modules/storage.bicep' = {
  name: 'storage-artifacts'
  params: {
    location: location
    tags: tags
    logAnalyticsId: monitoring.outputs.logAnalyticsId
    accountName: take('st${storagePrefix}ml${nameSuffix}', 24)
    hnsEnabled: false
    skuName: storageSkuName
    containers: ['models', 'images', 'mlflow-artifacts', 'prediction-logs']
    fileShares: ['azureml-filestore']
  }
}

module acr 'modules/acr.bicep' = {
  name: 'acr'
  params: {
    location: location
    namePrefix: namePrefix
    tags: tags
    logAnalyticsId: monitoring.outputs.logAnalyticsId
    nameSuffix: nameSuffix
  }
}

module postgres 'modules/postgres.bicep' = {
  name: 'postgres'
  params: {
    location: location
    namePrefix: namePrefix
    tags: tags
    logAnalyticsId: monitoring.outputs.logAnalyticsId
    nameSuffix: nameSuffix
    skuName: postgresSkuName
    skuTier: postgresSkuTier
    highAvailabilityMode: postgresHaMode
    geoRedundantBackup: postgresGeoBackup
    entraAdminObjectId: entraAdminObjectId
    entraAdminPrincipalName: entraAdminPrincipalName
    entraAdminPrincipalType: entraAdminPrincipalType
  }
}

module aml 'modules/aml.bicep' = {
  name: 'aml'
  params: {
    location: location
    namePrefix: namePrefix
    tags: tags
    logAnalyticsId: monitoring.outputs.logAnalyticsId
    storageAccountId: artifacts.outputs.storageAccountId
    keyVaultId: keyVault.outputs.keyVaultId
    appInsightsId: monitoring.outputs.appInsightsId
    containerRegistryId: acr.outputs.registryId
    trainingIdentityId: identity.outputs.trainingIdentityId
    hbiWorkspace: hbiWorkspace
    gpuClusterVmSize: gpuClusterVmSize
    deployModelRegistry: deployModelRegistry
  }
}

module eventHubs 'modules/eventhubs.bicep' = if (deployEventHubs) {
  name: 'eventhubs'
  params: {
    location: location
    namePrefix: namePrefix
    tags: tags
    logAnalyticsId: monitoring.outputs.logAnalyticsId
    nameSuffix: nameSuffix
  }
}

module containerApps 'modules/container-apps.bicep' = {
  name: 'container-apps'
  params: {
    location: location
    namePrefix: namePrefix
    tags: tags
    infrastructureSubnetId: network.outputs.containerAppsSubnetId
    logAnalyticsName: monitoring.outputs.logAnalyticsName
    appInsightsConnectionString: monitoring.outputs.appInsightsConnectionString
    acrLoginServer: acr.outputs.loginServer
    runtimeIdentityId: identity.outputs.runtimeIdentityId
    runtimeClientId: identity.outputs.runtimeClientId
    postgresFqdn: postgres.outputs.serverFqdn
    keyVaultUri: keyVault.outputs.keyVaultUri
    artifactsBlobEndpoint: artifacts.outputs.blobEndpoint
    authTenantId: authTenantId
    authAudience: authAudience
    apiImage: apiImage
    dashboardImage: dashboardImage
    workerImage: workerImage
    apiMinReplicas: apiMinReplicas
    apiMaxReplicas: apiMaxReplicas
    zoneRedundant: zoneRedundant
  }
  dependsOn: [rbac] // AcrPull must exist before the apps try to pull
}

module rbac 'modules/rbac.bicep' = {
  name: 'rbac'
  params: {
    runtimePrincipalId: identity.outputs.runtimePrincipalId
    trainingPrincipalId: identity.outputs.trainingPrincipalId
    deployPrincipalId: identity.outputs.deployPrincipalId
    workspacePrincipalId: aml.outputs.workspacePrincipalId
    acrName: acr.outputs.registryName
    keyVaultName: keyVault.outputs.keyVaultName
    dataLakeAccountName: dataLake.outputs.storageAccountName
    artifactsAccountName: artifacts.outputs.storageAccountName
    workspaceName: aml.outputs.workspaceName
  }
}

module policy 'modules/policy.bicep' = {
  name: 'policy'
  params: {
    enforcementMode: policyEnforcementMode
  }
}

// -- private endpoints -------------------------------------------------------

module peKeyVault 'modules/private-endpoint.bicep' = {
  name: 'pe-keyvault'
  params: {
    location: location
    name: 'pe-${namePrefix}-kv'
    subnetId: network.outputs.privateEndpointsSubnetId
    targetResourceId: keyVault.outputs.keyVaultId
    groupId: 'vault'
    privateDnsZoneNames: ['privatelink.vaultcore.azure.net']
    tags: tags
  }
  dependsOn: [privateDns]
}

module peDataLakeBlob 'modules/private-endpoint.bicep' = {
  name: 'pe-datalake-blob'
  params: {
    location: location
    name: 'pe-${namePrefix}-data-blob'
    subnetId: network.outputs.privateEndpointsSubnetId
    targetResourceId: dataLake.outputs.storageAccountId
    groupId: 'blob'
    privateDnsZoneNames: ['privatelink.blob.${az.environment().suffixes.storage}']
    tags: tags
  }
  dependsOn: [privateDns]
}

module peDataLakeDfs 'modules/private-endpoint.bicep' = {
  name: 'pe-datalake-dfs'
  params: {
    location: location
    name: 'pe-${namePrefix}-data-dfs'
    subnetId: network.outputs.privateEndpointsSubnetId
    targetResourceId: dataLake.outputs.storageAccountId
    groupId: 'dfs'
    privateDnsZoneNames: ['privatelink.dfs.${az.environment().suffixes.storage}']
    tags: tags
  }
  dependsOn: [privateDns]
}

module peArtifactsBlob 'modules/private-endpoint.bicep' = {
  name: 'pe-artifacts-blob'
  params: {
    location: location
    name: 'pe-${namePrefix}-ml-blob'
    subnetId: network.outputs.privateEndpointsSubnetId
    targetResourceId: artifacts.outputs.storageAccountId
    groupId: 'blob'
    privateDnsZoneNames: ['privatelink.blob.${az.environment().suffixes.storage}']
    tags: tags
  }
  dependsOn: [privateDns]
}

module peArtifactsFile 'modules/private-endpoint.bicep' = {
  name: 'pe-artifacts-file'
  params: {
    location: location
    name: 'pe-${namePrefix}-ml-file'
    subnetId: network.outputs.privateEndpointsSubnetId
    targetResourceId: artifacts.outputs.storageAccountId
    groupId: 'file'
    privateDnsZoneNames: ['privatelink.file.${az.environment().suffixes.storage}']
    tags: tags
  }
  dependsOn: [privateDns]
}

module peAcr 'modules/private-endpoint.bicep' = {
  name: 'pe-acr'
  params: {
    location: location
    name: 'pe-${namePrefix}-acr'
    subnetId: network.outputs.privateEndpointsSubnetId
    targetResourceId: acr.outputs.registryId
    groupId: 'registry'
    privateDnsZoneNames: ['privatelink.azurecr.io']
    tags: tags
  }
  dependsOn: [privateDns]
}

module peAml 'modules/private-endpoint.bicep' = {
  name: 'pe-aml'
  params: {
    location: location
    name: 'pe-${namePrefix}-aml'
    subnetId: network.outputs.privateEndpointsSubnetId
    targetResourceId: aml.outputs.workspaceId
    groupId: 'amlworkspace'
    privateDnsZoneNames: ['privatelink.api.azureml.ms', 'privatelink.notebooks.azure.net']
    tags: tags
  }
  dependsOn: [privateDns]
}

module pePostgres 'modules/private-endpoint.bicep' = {
  name: 'pe-postgres'
  params: {
    location: location
    name: 'pe-${namePrefix}-psql'
    subnetId: network.outputs.privateEndpointsSubnetId
    targetResourceId: postgres.outputs.serverId
    groupId: 'postgresqlServer'
    privateDnsZoneNames: ['privatelink.postgres.database.azure.com']
    tags: tags
  }
  dependsOn: [privateDns]
}

module peEventHubs 'modules/private-endpoint.bicep' = if (deployEventHubs) {
  name: 'pe-eventhubs'
  params: {
    location: location
    name: 'pe-${namePrefix}-evh'
    subnetId: network.outputs.privateEndpointsSubnetId
    targetResourceId: eventHubs!.outputs.namespaceId // guarded: same deployEventHubs condition as the module
    groupId: 'namespace'
    privateDnsZoneNames: ['privatelink.servicebus.windows.net']
    tags: tags
  }
  dependsOn: [privateDns]
}

output apiFqdn string = containerApps.outputs.apiFqdn
output amlWorkspaceName string = aml.outputs.workspaceName
output acrLoginServer string = acr.outputs.loginServer
output keyVaultName string = keyVault.outputs.keyVaultName
output dataLakeAccountName string = dataLake.outputs.storageAccountName
output artifactsAccountName string = artifacts.outputs.storageAccountName
output postgresFqdn string = postgres.outputs.serverFqdn
