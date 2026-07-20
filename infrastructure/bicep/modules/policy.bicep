// Policy hooks (spec §13): guardrail assignments at resource-group scope so a
// later portal/CLI change cannot silently reopen a public surface. Dev uses
// DoNotEnforce (audit-style visibility); prod enforces.

param enforcementMode string = 'Default' // 'Default' enforces; 'DoNotEnforce' audits only

// Built-in policy definition ids.
var policies = [
  {
    name: 'deny-storage-public-network'
    displayName: 'Storage accounts should disable public network access'
    definitionId: 'b2982f36-99f2-4db5-8eff-283140c09693'
  }
  {
    name: 'deny-kv-public-network'
    displayName: 'Azure Key Vault should disable public network access'
    definitionId: '405c5871-3e91-4644-8a63-58e19d68ff5b'
  }
  {
    name: 'acr-no-unrestricted-network'
    displayName: 'Container registries should not allow unrestricted network access'
    definitionId: 'd0793b48-0edc-4296-a390-4c75d1bdfd71'
  }
  {
    name: 'kv-purge-protection'
    displayName: 'Key vaults should have deletion protection enabled'
    definitionId: '0b60c0b2-2dc2-4e1c-b5c9-abbed971de53'
  }
]

resource assignments 'Microsoft.Authorization/policyAssignments@2022-06-01' = [
  for policy in policies: {
    name: policy.name
    properties: {
      displayName: policy.displayName
      policyDefinitionId: subscriptionResourceId('Microsoft.Authorization/policyDefinitions', policy.definitionId)
      enforcementMode: enforcementMode
    }
  }
]
