@description('Location for all resources.')
param location string = resourceGroup().location

@description('Suffix for resource names to ensure global uniqueness.')
param environmentName string = 'ragprod'

var namingSuffix = uniqueString(resourceGroup().id, environmentName)
var acrName = 'acr${namingSuffix}'
var keyVaultName = 'kv-${namingSuffix}'
var containerAppName = 'app-${namingSuffix}'
var appEnvName = 'env-${namingSuffix}'
var logAnalyticsName = 'log-${namingSuffix}'
var appInsightsName = 'appinsights-${namingSuffix}'
var identityName = 'id-${namingSuffix}'

// 1. User-Assigned Managed Identity
resource managedIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: identityName
  location: location
}

// 2. Azure Container Registry (ACR)
resource acr 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: acrName
  location: location
  sku: {
    name: 'Basic'
  }
  properties: {
    adminUserEnabled: false
  }
}

// 3. Log Analytics Workspace
resource logAnalytics 'Microsoft.OperationalInsights/workspaces@2022-10-01' = {
  name: logAnalyticsName
  location: location
  properties: {
    sku: {
      name: 'PerGB2018'
    }
    retentionInDays: 30
  }
}

// 4. Application Insights
resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: appInsightsName
  location: location
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: logAnalytics.id
  }
}

// 5. Key Vault (RBAC authorized)
resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: keyVaultName
  location: location
  properties: {
    tenantId: subscription().tenantId
    sku: {
      family: 'A'
      name: 'standard'
    }
    enableRbacAuthorization: true
    enableSoftDelete: true
  }
}

// 6. Container Apps Environment
resource appEnv 'Microsoft.App/managedEnvironments@2023-05-01' = {
  name: appEnvName
  location: location
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logAnalytics.properties.customerId
        sharedKey: logAnalytics.listKeys().primarySharedKey
      }
    }
  }
}

// 7. Container App (with scale-to-zero minReplicas: 0)
resource containerApp 'Microsoft.App/containerApps@2023-05-01' = {
  name: containerAppName
  location: location
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${managedIdentity.id}': {}
    }
  }
  properties: {
    managedEnvironmentId: appEnv.id
    configuration: {
      ingress: {
        external: true
        targetPort: 8000
        transport: 'auto'
      }
    }
    template: {
      containers: [
        {
          name: 'rag-api'
          image: 'mcr.microsoft.com/k8se/quickstart:latest'
          resources: {
            cpu: json('0.5')
            memory: '1.0Gi'
          }
          env: [
            {
              name: 'SECRET_BACKEND'
              value: 'azure_keyvault'
            }
            {
              name: 'AZURE_KEYVAULT_URL'
              value: keyVault.properties.vaultUri
            }
            {
              name: 'APPLICATIONINSIGHTS_CONNECTION_STRING'
              value: appInsights.properties.ConnectionString
            }
            {
              name: 'ROUTING_METHOD'
              value: 'classical'
            }
            {
              name: 'MAIN_LLM_MODEL'
              value: 'groq'
            }
          ]
        }
      ]
      scale: {
        minReplicas: 0
        maxReplicas: 3
      }
    }
  }
}

output acrLoginServer string = acr.properties.loginServer
output acrName string = acr.name
output keyVaultName string = keyVault.name
output keyVaultUrl string = keyVault.properties.vaultUri
output containerAppUrl string = containerApp.properties.configuration.ingress.fqdn
output containerAppName string = containerApp.name
output managedIdentityPrincipalId string = managedIdentity.properties.principalId
output managedIdentityId string = managedIdentity.id
