// Reusable private endpoint + DNS zone group. The zones must already exist in
// this resource group (created by private-dns.bicep); AML uses two zones on a
// single endpoint, hence the array.

param location string
param name string
param subnetId string
param targetResourceId string
param groupId string
param privateDnsZoneNames array
param tags object

resource dnsZones 'Microsoft.Network/privateDnsZones@2020-06-01' existing = [
  for zone in privateDnsZoneNames: {
    name: zone
  }
]

resource privateEndpoint 'Microsoft.Network/privateEndpoints@2024-05-01' = {
  name: name
  location: location
  tags: tags
  properties: {
    subnet: { id: subnetId }
    privateLinkServiceConnections: [
      {
        name: name
        properties: {
          privateLinkServiceId: targetResourceId
          groupIds: [groupId]
        }
      }
    ]
  }
}

resource dnsZoneGroup 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-05-01' = {
  parent: privateEndpoint
  name: 'default'
  properties: {
    privateDnsZoneConfigs: [
      for (zone, i) in privateDnsZoneNames: {
        name: replace(zone, '.', '-')
        properties: { privateDnsZoneId: dnsZones[i].id }
      }
    ]
  }
}

output privateEndpointId string = privateEndpoint.id
