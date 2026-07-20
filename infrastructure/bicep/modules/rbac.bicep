// Every role grant in one reviewable place, scoped to the specific resource —
// never subscription-wide. The identity-to-resource matrix in
// docs/architecture/security-architecture.md mirrors this file; keep both in
// sync when adding a grant.

param runtimePrincipalId string
param trainingPrincipalId string
param deployPrincipalId string
param workspacePrincipalId string

param acrName string
param keyVaultName string
param dataLakeAccountName string
param artifactsAccountName string
param workspaceName string

// Built-in role definition ids (stable, documented well-known GUIDs).
var roles = {
  acrPull: '7f951dda-4ed3-4680-a7ca-43fe172d538d'
  acrPush: '8311e382-0749-46cb-b1d0-61b1d5b09d05'
  keyVaultSecretsUser: '4633458b-17de-408a-b874-0445c86b69e6'
  storageBlobDataReader: '2a2b9908-6ea1-4ae2-8e65-a410df84e7d1'
  storageBlobDataContributor: 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
  storageFileDataPrivilegedContributor: '69566ab7-960f-475b-8e7c-b3118f30c6bd'
  azureMlDataScientist: 'f6c7c914-8db3-469d-8ca1-694a8f32e121'
  monitoringMetricsPublisher: '3913510d-42f4-4e42-8a64-420c390055eb'
  reader: 'acdd72a7-3385-48ef-bd42-f606fba81ae7'
}

resource acr 'Microsoft.ContainerRegistry/registries@2023-07-01' existing = { name: acrName }
resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' existing = { name: keyVaultName }
resource dataLake 'Microsoft.Storage/storageAccounts@2023-05-01' existing = { name: dataLakeAccountName }
resource artifacts 'Microsoft.Storage/storageAccounts@2023-05-01' existing = { name: artifactsAccountName }
resource workspace 'Microsoft.MachineLearningServices/workspaces@2024-10-01' existing = { name: workspaceName }

// -- runtime (Container Apps: api/worker/dashboard) --------------------------
// Reads models + writes prediction/feedback artifacts; never writes curated data.

resource runtimeAcrPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(acr.id, runtimePrincipalId, roles.acrPull)
  scope: acr
  properties: {
    principalId: runtimePrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.acrPull)
  }
}

resource runtimeKvSecrets 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(keyVault.id, runtimePrincipalId, roles.keyVaultSecretsUser)
  scope: keyVault
  properties: {
    principalId: runtimePrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.keyVaultSecretsUser)
  }
}

resource runtimeArtifactsRw 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(artifacts.id, runtimePrincipalId, roles.storageBlobDataContributor)
  scope: artifacts
  properties: {
    principalId: runtimePrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.storageBlobDataContributor)
  }
}

resource runtimeDataRead 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(dataLake.id, runtimePrincipalId, roles.storageBlobDataReader)
  scope: dataLake
  properties: {
    principalId: runtimePrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.storageBlobDataReader)
  }
}

resource runtimeMetrics 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(resourceGroup().id, runtimePrincipalId, roles.monitoringMetricsPublisher)
  properties: {
    principalId: runtimePrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.monitoringMetricsPublisher)
  }
}

// -- training (AML compute) --------------------------------------------------
// Reads and writes datasets/artifacts through identity-based datastores.

resource trainingDataRw 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(dataLake.id, trainingPrincipalId, roles.storageBlobDataContributor)
  scope: dataLake
  properties: {
    principalId: trainingPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.storageBlobDataContributor)
  }
}

resource trainingArtifactsRw 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(artifacts.id, trainingPrincipalId, roles.storageBlobDataContributor)
  scope: artifacts
  properties: {
    principalId: trainingPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.storageBlobDataContributor)
  }
}

resource trainingAcrPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(acr.id, trainingPrincipalId, roles.acrPull)
  scope: acr
  properties: {
    principalId: trainingPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.acrPull)
  }
}

resource trainingKvSecrets 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(keyVault.id, trainingPrincipalId, roles.keyVaultSecretsUser)
  scope: keyVault
  properties: {
    principalId: trainingPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.keyVaultSecretsUser)
  }
}

// -- deploy (CI/CD via workload identity federation, ADR-0014) ---------------
// Pushes images and drives AML jobs/endpoints. Infra deploys use a separate
// elevated grant applied at pipeline setup, not baked here (see the runbook).

resource deployAcrPush 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(acr.id, deployPrincipalId, roles.acrPush)
  scope: acr
  properties: {
    principalId: deployPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.acrPush)
  }
}

resource deployMlOps 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(workspace.id, deployPrincipalId, roles.azureMlDataScientist)
  scope: workspace
  properties: {
    principalId: deployPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.azureMlDataScientist)
  }
}

resource deployRgReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(resourceGroup().id, deployPrincipalId, roles.reader)
  properties: {
    principalId: deployPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.reader)
  }
}

// -- AML workspace system identity -------------------------------------------
// Needs data-plane access to its associated resources when keys are disabled.

resource workspaceArtifactsRw 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(artifacts.id, workspacePrincipalId, roles.storageBlobDataContributor)
  scope: artifacts
  properties: {
    principalId: workspacePrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.storageBlobDataContributor)
  }
}

resource workspaceFileAccess 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(artifacts.id, workspacePrincipalId, roles.storageFileDataPrivilegedContributor)
  scope: artifacts
  properties: {
    principalId: workspacePrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.storageFileDataPrivilegedContributor)
  }
}

resource workspaceAcrPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(acr.id, workspacePrincipalId, roles.acrPull)
  scope: acr
  properties: {
    principalId: workspacePrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.acrPull)
  }
}
