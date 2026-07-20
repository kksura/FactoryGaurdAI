// Azure ML workspace (managed network isolation, ADR-0009/0011), CPU compute
// cluster (GPU cluster flag-gated), and the AML registry for approved models.
// No outbound FQDN rules: dependencies and pretrained weights bake into the
// training image at build time (spec §14 supply chain) — training jobs need no
// internet egress at run time.

param location string
param namePrefix string
param tags object
param logAnalyticsId string

param storageAccountId string
param keyVaultId string
param appInsightsId string
param containerRegistryId string
param trainingIdentityId string

@description('True marks the workspace high business impact (reduced telemetry).')
param hbiWorkspace bool = true

param cpuClusterVmSize string = 'Standard_D4s_v5'
param cpuClusterMaxNodes int = 2

@description('GPU cluster VM size; empty skips the GPU cluster. Sizing derives from the GB10 benchmark, not a named-SKU assumption (docs/performance/gb10-benchmark.md).')
param gpuClusterVmSize string = ''
param gpuClusterMaxNodes int = 1

@description('Deploy the AML registry for approved models (one per org is typical; disable if it exists elsewhere).')
param deployModelRegistry bool = true

resource workspace 'Microsoft.MachineLearningServices/workspaces@2024-10-01' = {
  name: 'mlw-${namePrefix}'
  location: location
  tags: tags
  identity: { type: 'SystemAssigned' }
  properties: {
    friendlyName: 'FactoryGuard ${namePrefix}'
    storageAccount: storageAccountId
    keyVault: keyVaultId
    applicationInsights: appInsightsId
    containerRegistry: containerRegistryId
    hbiWorkspace: hbiWorkspace
    publicNetworkAccess: 'Disabled'
    // Real workspace property (GA 2024-04-01+); the bundled Bicep type for this
    // apiVersion omits it — required because shared-key access is off on storage.
    #disable-next-line BCP037
    systemDatastoresAuthMode: 'identity'
    managedNetwork: {
      isolationMode: 'AllowOnlyApprovedOutbound'
    }
    primaryUserAssignedIdentity: null
  }
}

resource cpuCluster 'Microsoft.MachineLearningServices/workspaces/computes@2024-10-01' = {
  parent: workspace
  name: 'cpu-cluster'
  location: location
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: { '${trainingIdentityId}': {} }
  }
  properties: {
    computeType: 'AmlCompute'
    properties: {
      vmSize: cpuClusterVmSize
      vmPriority: 'Dedicated'
      scaleSettings: {
        minNodeCount: 0
        maxNodeCount: cpuClusterMaxNodes
        nodeIdleTimeBeforeScaleDown: 'PT15M'
      }
      remoteLoginPortPublicAccess: 'Disabled'
      osType: 'Linux'
    }
  }
}

resource gpuCluster 'Microsoft.MachineLearningServices/workspaces/computes@2024-10-01' = if (!empty(gpuClusterVmSize)) {
  parent: workspace
  name: 'gpu-cluster'
  location: location
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: { '${trainingIdentityId}': {} }
  }
  properties: {
    computeType: 'AmlCompute'
    properties: {
      vmSize: gpuClusterVmSize
      vmPriority: 'Dedicated'
      scaleSettings: {
        minNodeCount: 0
        maxNodeCount: gpuClusterMaxNodes
        nodeIdleTimeBeforeScaleDown: 'PT15M'
      }
      remoteLoginPortPublicAccess: 'Disabled'
      osType: 'Linux'
    }
  }
  dependsOn: [cpuCluster] // serialize compute creation; parallel create intermittently races on workspace provisioning
}

resource modelRegistry 'Microsoft.MachineLearningServices/registries@2024-10-01' = if (deployModelRegistry) {
  name: 'mlreg-${replace(namePrefix, '-', '')}'
  location: location
  tags: tags
  identity: { type: 'SystemAssigned' }
  properties: {
    publicNetworkAccess: 'Disabled'
    regionDetails: [
      {
        location: location
        storageAccountDetails: [
          {
            systemCreatedStorageAccount: {
              storageAccountType: 'Standard_ZRS'
              allowBlobPublicAccess: false
            }
          }
        ]
        acrDetails: [
          {
            systemCreatedAcrAccount: { acrAccountSku: 'Premium' }
          }
        ]
      }
    ]
  }
}

resource diagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  name: 'diag-${workspace.name}'
  scope: workspace
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

output workspaceId string = workspace.id
output workspaceName string = workspace.name
output workspacePrincipalId string = workspace.identity.principalId
output modelRegistryId string = deployModelRegistry ? modelRegistry.id : ''
