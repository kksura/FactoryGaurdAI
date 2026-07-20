// CanNotDelete lock on the spoke RG (prod). Teardown intentionally requires
// removing this lock first — see scripts/azure/teardown.sh.

resource deleteLock 'Microsoft.Authorization/locks@2020-05-01' = {
  name: 'factoryguard-no-delete'
  properties: {
    level: 'CanNotDelete'
    notes: 'FactoryGuard production resources; remove via the documented teardown procedure only.'
  }
}
