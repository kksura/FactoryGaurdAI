// Container Apps environment (VNet-integrated, internal-only ingress) plus the
// three FactoryGuard apps: api, dashboard, worker (ADR-0009). Images are pulled
// from ACR with the runtime managed identity; prod parameter files must pin
// images by digest (spec §14). No secrets appear here: PostgreSQL is Entra-only
// and configuration is FG_* environment variables read by the fail-closed
// settings loader.

param location string
param namePrefix string
param tags object

param infrastructureSubnetId string
param logAnalyticsName string
param appInsightsConnectionString string
param acrLoginServer string
param runtimeIdentityId string
param runtimeClientId string
param postgresFqdn string
param keyVaultUri string
param artifactsBlobEndpoint string

@description('Entra tenant id used to build the OIDC issuer for API auth (ADR-0010).')
param authTenantId string

@description('Expected token audience, e.g. api://factoryguard.')
param authAudience string = 'api://factoryguard'

param apiImage string
param dashboardImage string
param workerImage string

param apiMinReplicas int = 1
param apiMaxReplicas int = 5
param zoneRedundant bool = false

resource logAnalytics 'Microsoft.OperationalInsights/workspaces@2023-09-01' existing = {
  name: logAnalyticsName
}

resource environment 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: 'cae-${namePrefix}'
  location: location
  tags: tags
  properties: {
    vnetConfiguration: {
      infrastructureSubnetId: infrastructureSubnetId
      internal: true
    }
    workloadProfiles: [
      { name: 'Consumption', workloadProfileType: 'Consumption' }
    ]
    zoneRedundant: zoneRedundant
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logAnalytics.properties.customerId
        sharedKey: logAnalytics.listKeys().primarySharedKey
      }
    }
  }
}

var commonEnv = [
  { name: 'FG_ENVIRONMENT', value: 'production' }
  { name: 'AZURE_CLIENT_ID', value: runtimeClientId } // DefaultAzureCredential picks the runtime UAMI
  { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: appInsightsConnectionString }
  { name: 'FG_AUTH__ISSUER', value: '${az.environment().authentication.loginEndpoint}${authTenantId}/v2.0' }
  { name: 'FG_AUTH__AUDIENCE', value: authAudience }
  { name: 'FG_DATABASE__HOST', value: postgresFqdn }
  { name: 'FG_DATABASE__NAME', value: 'factoryguard' }
  { name: 'FG_DATABASE__SSLMODE', value: 'require' }
  { name: 'FG_STORAGE__BLOB_ENDPOINT', value: artifactsBlobEndpoint }
  { name: 'FG_KEY_VAULT_URI', value: keyVaultUri }
]

var apps = [
  {
    name: 'api'
    image: apiImage
    port: 8000
    healthLive: '/health/live'
    healthReady: '/health/ready'
    cpu: 2
    memory: '4Gi'
    minReplicas: apiMinReplicas
    maxReplicas: apiMaxReplicas
    scaleRules: [
      {
        name: 'http-concurrency'
        http: { metadata: { concurrentRequests: '50' } }
      }
    ]
  }
  {
    name: 'dashboard'
    image: dashboardImage
    port: 8501
    healthLive: '/'
    healthReady: '/'
    cpu: 1
    memory: '2Gi'
    minReplicas: 1
    maxReplicas: 2
    scaleRules: []
  }
  {
    name: 'worker'
    image: workerImage
    port: 0 // no ingress: drift/monitoring worker is outbound-only
    healthLive: ''
    healthReady: ''
    cpu: 1
    memory: '2Gi'
    minReplicas: 1
    maxReplicas: 1
    scaleRules: []
  }
]

resource containerApps 'Microsoft.App/containerApps@2024-03-01' = [
  for app in apps: {
    name: 'ca-${namePrefix}-${app.name}'
    location: location
    tags: tags
    identity: {
      type: 'UserAssigned'
      userAssignedIdentities: { '${runtimeIdentityId}': {} }
    }
    properties: {
      environmentId: environment.id
      workloadProfileName: 'Consumption'
      configuration: {
        activeRevisionsMode: 'Single'
        ingress: app.port == 0 ? null : {
          external: false
          targetPort: app.port
          transport: 'http'
          allowInsecure: false
        }
        registries: [
          { server: acrLoginServer, identity: runtimeIdentityId }
        ]
      }
      template: {
        containers: [
          {
            name: app.name
            image: app.image
            resources: { cpu: json('${app.cpu}'), memory: app.memory }
            env: commonEnv
            probes: app.port == 0 ? [] : [
              {
                type: 'Liveness'
                httpGet: { path: app.healthLive, port: app.port }
                initialDelaySeconds: 20
                periodSeconds: 15
              }
              {
                type: 'Readiness'
                httpGet: { path: app.healthReady, port: app.port }
                initialDelaySeconds: 10
                periodSeconds: 10
              }
            ]
          }
        ]
        scale: {
          minReplicas: app.minReplicas
          maxReplicas: app.maxReplicas
          rules: app.scaleRules
        }
      }
    }
  }
]

output environmentId string = environment.id
output environmentDefaultDomain string = environment.properties.defaultDomain
output apiFqdn string = containerApps[0].properties.configuration.ingress.fqdn
