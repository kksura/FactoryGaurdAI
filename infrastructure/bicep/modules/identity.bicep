// User-assigned managed identities, one per role (spec §13): runtime (Container
// Apps), training (AML compute), deploy (CI/CD via workload identity federation,
// ADR-0014). Role assignments live in rbac.bicep so grants are reviewable in
// one place.

param location string
param namePrefix string
param tags object

@description('GitHub repository (owner/name) for OIDC federation; empty skips the federated credentials.')
param githubRepository string = ''

@description('GitHub environment name gated by reviewers for deploys (ADR-0014).')
param githubEnvironment string = ''

resource runtimeIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-${namePrefix}-runtime'
  location: location
  tags: tags
}

resource trainingIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-${namePrefix}-training'
  location: location
  tags: tags
}

resource deployIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-${namePrefix}-deploy'
  location: location
  tags: tags
}

// Subject filter pinned to repo + environment exactly (ADR-0014): a run only
// gets this identity after the environment's required reviewers approve.
resource deployFederation 'Microsoft.ManagedIdentity/userAssignedIdentities/federatedIdentityCredentials@2023-01-31' = if (!empty(githubRepository) && !empty(githubEnvironment)) {
  parent: deployIdentity
  name: 'github-${githubEnvironment}'
  properties: {
    issuer: 'https://token.actions.githubusercontent.com'
    subject: 'repo:${githubRepository}:environment:${githubEnvironment}'
    audiences: ['api://AzureADTokenExchange']
  }
}

output runtimeIdentityId string = runtimeIdentity.id
output runtimeClientId string = runtimeIdentity.properties.clientId
output runtimePrincipalId string = runtimeIdentity.properties.principalId
output trainingIdentityId string = trainingIdentity.id
output trainingPrincipalId string = trainingIdentity.properties.principalId
output deployIdentityId string = deployIdentity.id
output deployPrincipalId string = deployIdentity.properties.principalId
