// Dev spoke: cheapest viable shapes, policies in audit mode, no delete lock.
// Placeholder ids (<...>) are supplied by the deploying org at run time —
// scripts/azure/deploy.sh refuses to run while any placeholder remains.
using '../main.bicep'

param env = 'dev'
param location = 'westeurope'

param monthlyBudgetAmount = 500
param alertEmails = ['<ops-alias@example.com>']
param budgetStartDate = '2026-07-01'
param enableDeleteLock = false

param vnetAddressPrefix = '10.20.0.0/22'
param containerAppsSubnetPrefix = '10.20.0.0/23'
param privateEndpointsSubnetPrefix = '10.20.2.0/24'

param deployEventHubs = false
param deployModelRegistry = true
param gpuClusterVmSize = '' // CPU-only in dev; GB10 benchmark drives the prod GPU sizing
param postgresSkuName = 'Standard_B2ms'
param postgresSkuTier = 'Burstable'
param postgresHaMode = 'Disabled'
param postgresGeoBackup = 'Disabled'
param logRetentionInDays = 30
param storageSkuName = 'Standard_LRS'
param policyEnforcementMode = 'DoNotEnforce'
param zoneRedundant = false
param apiMinReplicas = 1
param apiMaxReplicas = 2
param hbiWorkspace = false

param entraAdminObjectId = '<entra-group-object-id>'
param entraAdminPrincipalName = '<entra-group-name>'
param authTenantId = '<tenant-id>'
param githubRepository = '' // '<owner>/<repo>' enables CI OIDC federation
param githubEnvironment = 'dev'

// Dev may use moving tags; prod pins digests.
param apiImage = 'factoryguard/api:0.1.0'
param dashboardImage = 'factoryguard/dashboard:0.1.0'
param workerImage = 'factoryguard/worker:0.1.0'
