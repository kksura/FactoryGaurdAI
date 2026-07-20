// Private DNS zones for every private-link service in use, linked to the
// spoke VNet (ADR-0011). Registration stays disabled: records are managed by
// the private-endpoint zone groups, never by VM auto-registration.

param vnetId string
param zoneNames array
param tags object

resource zones 'Microsoft.Network/privateDnsZones@2020-06-01' = [
  for zone in zoneNames: {
    name: zone
    location: 'global'
    tags: tags
  }
]

resource links 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2020-06-01' = [
  for (zone, i) in zoneNames: {
    parent: zones[i]
    name: 'link-spoke'
    location: 'global'
    tags: tags
    properties: {
      registrationEnabled: false
      virtualNetwork: { id: vnetId }
    }
  }
]

output zoneIds array = [for (zone, i) in zoneNames: zones[i].id]
