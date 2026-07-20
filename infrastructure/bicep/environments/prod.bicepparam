// Production spoke: zone redundancy, HA PostgreSQL, enforced policies, delete
// lock, digest-pinned images (spec §14). Placeholders (<...>) block deploy.sh
// until replaced with real org values.
using '../main.bicep'

param env = 'prod'
param location = 'westeurope'

param monthlyBudgetAmount = 3000
param alertEmails = ['<ops-alias@example.com>', '<finops-alias@example.com>']
param budgetStartDate = '2026-08-01'
param enableDeleteLock = true

param vnetAddressPrefix = '10.21.0.0/22'
param containerAppsSubnetPrefix = '10.21.0.0/23'
param privateEndpointsSubnetPrefix = '10.21.2.0/24'
param egressRouteTableId = '' // set to the hub-firewall route table id (assumption A11)

param deployEventHubs = false // flip only when streaming ingestion is approved (ADR-0021)
param deployModelRegistry = true
param gpuClusterVmSize = '<gpu-vm-size>' // choose from docs/performance/gb10-benchmark.md sizing guidance
param postgresSkuName = 'Standard_D4ds_v5'
param postgresSkuTier = 'GeneralPurpose'
param postgresHaMode = 'ZoneRedundant'
param postgresGeoBackup = 'Enabled'
param logRetentionInDays = 90
param storageSkuName = 'Standard_ZRS'
param policyEnforcementMode = 'Default'
param zoneRedundant = true
param apiMinReplicas = 2
param apiMaxReplicas = 10
param hbiWorkspace = true

param entraAdminObjectId = '<entra-group-object-id>'
param entraAdminPrincipalName = '<entra-group-name>'
param authTenantId = '<tenant-id>'
param githubRepository = '<owner>/<repo>'
param githubEnvironment = 'production' // GitHub environment with required reviewers (ADR-0014)

// Digest-pinned (spec §14: digest pinning in production manifests).
param apiImage = 'factoryguard/api@sha256:<digest>'
param dashboardImage = 'factoryguard/dashboard@sha256:<digest>'
param workerImage = 'factoryguard/worker@sha256:<digest>'
