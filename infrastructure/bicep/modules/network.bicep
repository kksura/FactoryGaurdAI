// Spoke VNet with dedicated subnets and deny-by-default NSGs (ADR-0011).
// Hub peering, firewall routes, and Bastion live in the org hub (assumption A11)
// and are out of scope here; the route-table hook is exposed as a parameter.

param location string
param namePrefix string
param tags object

@description('Spoke VNet address space.')
param vnetAddressPrefix string

@description('Container Apps environment infrastructure subnet (>= /23 recommended).')
param containerAppsSubnetPrefix string

@description('Private-endpoints subnet.')
param privateEndpointsSubnetPrefix string

@description('Optional route table id forcing egress via the hub firewall (empty = none).')
param egressRouteTableId string = ''

var routeTableRef = empty(egressRouteTableId) ? null : { id: egressRouteTableId }

// Container Apps subnet: only VNet-internal HTTP(S) reaches the apps; all
// other inbound is denied. Outbound 443 is left open at the NSG because
// egress governance is the hub firewall's job (ADR-0011, A11).
resource nsgContainerApps 'Microsoft.Network/networkSecurityGroups@2024-05-01' = {
  name: 'nsg-${namePrefix}-container-apps'
  location: location
  tags: tags
  properties: {
    securityRules: [
      {
        name: 'AllowVnetInboundHttp'
        properties: {
          priority: 200
          direction: 'Inbound'
          access: 'Allow'
          protocol: 'Tcp'
          sourceAddressPrefix: 'VirtualNetwork'
          sourcePortRange: '*'
          destinationAddressPrefix: 'VirtualNetwork'
          destinationPortRanges: ['443', '8000', '8501']
        }
      }
      {
        name: 'AllowAzureLoadBalancerInbound'
        properties: {
          priority: 300
          direction: 'Inbound'
          access: 'Allow'
          protocol: '*'
          sourceAddressPrefix: 'AzureLoadBalancer'
          sourcePortRange: '*'
          destinationAddressPrefix: '*'
          destinationPortRange: '*'
        }
      }
      {
        name: 'DenyAllInbound'
        properties: {
          priority: 4096
          direction: 'Inbound'
          access: 'Deny'
          protocol: '*'
          sourceAddressPrefix: '*'
          sourcePortRange: '*'
          destinationAddressPrefix: '*'
          destinationPortRange: '*'
        }
      }
      {
        name: 'AllowVnetOutbound'
        properties: {
          priority: 200
          direction: 'Outbound'
          access: 'Allow'
          protocol: '*'
          sourceAddressPrefix: 'VirtualNetwork'
          sourcePortRange: '*'
          destinationAddressPrefix: 'VirtualNetwork'
          destinationPortRange: '*'
        }
      }
      {
        name: 'AllowHttpsOutbound'
        properties: {
          priority: 300
          direction: 'Outbound'
          access: 'Allow'
          protocol: 'Tcp'
          sourceAddressPrefix: 'VirtualNetwork'
          sourcePortRange: '*'
          destinationAddressPrefix: '*'
          destinationPortRange: '443'
        }
      }
      {
        name: 'DenyAllOutbound'
        properties: {
          priority: 4096
          direction: 'Outbound'
          access: 'Deny'
          protocol: '*'
          sourceAddressPrefix: '*'
          sourcePortRange: '*'
          destinationAddressPrefix: '*'
          destinationPortRange: '*'
        }
      }
    ]
  }
}

// Private-endpoints subnet: endpoints only answer VNet-internal callers on the
// service ports (445 is required for AML's file-share datastore mounts).
resource nsgPrivateEndpoints 'Microsoft.Network/networkSecurityGroups@2024-05-01' = {
  name: 'nsg-${namePrefix}-private-endpoints'
  location: location
  tags: tags
  properties: {
    securityRules: [
      {
        name: 'AllowVnetInboundServicePorts'
        properties: {
          priority: 200
          direction: 'Inbound'
          access: 'Allow'
          protocol: 'Tcp'
          sourceAddressPrefix: 'VirtualNetwork'
          sourcePortRange: '*'
          destinationAddressPrefix: 'VirtualNetwork'
          destinationPortRanges: ['443', '445', '5432', '5671', '5672']
        }
      }
      {
        name: 'DenyAllInbound'
        properties: {
          priority: 4096
          direction: 'Inbound'
          access: 'Deny'
          protocol: '*'
          sourceAddressPrefix: '*'
          sourcePortRange: '*'
          destinationAddressPrefix: '*'
          destinationPortRange: '*'
        }
      }
    ]
  }
}

resource vnet 'Microsoft.Network/virtualNetworks@2024-05-01' = {
  name: 'vnet-${namePrefix}'
  location: location
  tags: tags
  properties: {
    addressSpace: {
      addressPrefixes: [vnetAddressPrefix]
    }
    subnets: [
      {
        name: 'snet-container-apps'
        properties: {
          addressPrefix: containerAppsSubnetPrefix
          networkSecurityGroup: { id: nsgContainerApps.id }
          routeTable: routeTableRef
          delegations: [
            {
              name: 'containerapps'
              properties: { serviceName: 'Microsoft.App/environments' }
            }
          ]
        }
      }
      {
        name: 'snet-private-endpoints'
        properties: {
          addressPrefix: privateEndpointsSubnetPrefix
          networkSecurityGroup: { id: nsgPrivateEndpoints.id }
          routeTable: routeTableRef
          privateEndpointNetworkPolicies: 'Enabled'
        }
      }
    ]
  }
}

output vnetId string = vnet.id
output vnetName string = vnet.name
output containerAppsSubnetId string = vnet.properties.subnets[0].id
output privateEndpointsSubnetId string = vnet.properties.subnets[1].id
