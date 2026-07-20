// FactoryGuard AI — subscription-scope entrypoint. Creates the spoke resource
// group, cost guardrails, and the delete lock, then hands off to stack.bicep.
//
//   az deployment sub what-if  --location <region> --template-file main.bicep \
//     --parameters environments/dev.bicepparam        # plan (CI job: plan-only)
//   az deployment sub create ...                       # apply (gated, see runbook)
//
// NEVER deployed from the GB10 development environment (spec §13): execution
// requires explicit subscription, credentials, and cost approval.

targetScope = 'subscription'

@description('Environment name, part of every resource name.')
@allowed(['dev', 'staging', 'prod'])
param env string

param location string

@description('Monthly budget (in the subscription currency) for the spoke RG.')
param monthlyBudgetAmount int

@description('Budget/alert notification recipients.')
param alertEmails array

@description('First day of the current month, required by Consumption budgets.')
param budgetStartDate string

@description('CanNotDelete lock on the RG (prod).')
param enableDeleteLock bool = false

// Pass-through parameters for stack.bicep (see that file for docs).
param vnetAddressPrefix string
param containerAppsSubnetPrefix string
param privateEndpointsSubnetPrefix string
param egressRouteTableId string = ''
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
param entraAdminObjectId string
param entraAdminPrincipalName string
param entraAdminPrincipalType string = 'Group'
param authTenantId string
param authAudience string = 'api://factoryguard'
param githubRepository string = ''
param githubEnvironment string = ''
param apiImage string
param dashboardImage string
param workerImage string

var namePrefix = 'fg-${env}'
var tags = {
  project: 'factoryguard-ai'
  environment: env
  managedBy: 'bicep'
  repo: empty(githubRepository) ? 'local' : githubRepository
}

resource resourceGroup 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: 'rg-${namePrefix}'
  location: location
  tags: tags
}

module stack 'stack.bicep' = {
  name: 'factoryguard-stack'
  scope: resourceGroup
  params: {
    location: location
    namePrefix: namePrefix
    tags: tags
    vnetAddressPrefix: vnetAddressPrefix
    containerAppsSubnetPrefix: containerAppsSubnetPrefix
    privateEndpointsSubnetPrefix: privateEndpointsSubnetPrefix
    egressRouteTableId: egressRouteTableId
    deployEventHubs: deployEventHubs
    deployModelRegistry: deployModelRegistry
    gpuClusterVmSize: gpuClusterVmSize
    postgresSkuName: postgresSkuName
    postgresSkuTier: postgresSkuTier
    postgresHaMode: postgresHaMode
    postgresGeoBackup: postgresGeoBackup
    logRetentionInDays: logRetentionInDays
    storageSkuName: storageSkuName
    policyEnforcementMode: policyEnforcementMode
    zoneRedundant: zoneRedundant
    apiMinReplicas: apiMinReplicas
    apiMaxReplicas: apiMaxReplicas
    hbiWorkspace: hbiWorkspace
    entraAdminObjectId: entraAdminObjectId
    entraAdminPrincipalName: entraAdminPrincipalName
    entraAdminPrincipalType: entraAdminPrincipalType
    authTenantId: authTenantId
    authAudience: authAudience
    githubRepository: githubRepository
    githubEnvironment: githubEnvironment
    apiImage: apiImage
    dashboardImage: dashboardImage
    workerImage: workerImage
  }
}

module budget 'modules/budget.bicep' = {
  name: 'budget'
  params: {
    namePrefix: namePrefix
    resourceGroupName: resourceGroup.name
    amount: monthlyBudgetAmount
    startDate: budgetStartDate
    contactEmails: alertEmails
  }
}

module lock 'modules/lock.bicep' = if (enableDeleteLock) {
  name: 'rg-lock'
  scope: resourceGroup
  params: {}
}

output resourceGroupName string = resourceGroup.name
output apiFqdn string = stack.outputs.apiFqdn
output amlWorkspaceName string = stack.outputs.amlWorkspaceName
output acrLoginServer string = stack.outputs.acrLoginServer
output keyVaultName string = stack.outputs.keyVaultName
