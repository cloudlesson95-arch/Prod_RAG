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
var storageAccountName = 'st${namingSuffix}'
var stateContainerName = 'rag-state'

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

// 7. Container App (scale-to-zero; single replica because the state snapshot has one writer)
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
            cpu: json('1.0')
            memory: '2.0Gi'
          }
          env: [
            {
              name: 'AZURE_CLIENT_ID'
              value: managedIdentity.properties.clientId
            }
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
            {
              // Public endpoint: the MCP SDK's localhost-only Host check would reject the cloud hostname (421)
              name: 'MCP_DNS_REBINDING_PROTECTION'
              value: 'false'
            }
            {
              name: 'STATE_BACKEND'
              value: 'azure_blob'
            }
            {
              name: 'AZURE_STORAGE_ACCOUNT_URL'
              value: storageAccount.properties.primaryEndpoints.blob
            }
            {
              name: 'AZURE_STATE_CONTAINER'
              value: stateContainerName
            }
            {
              name: 'LOCAL_DIR'
              value: '/tmp/state/.local'
            }
            {
              name: 'DATA_DIR'
              value: '/tmp/state/data'
            }
          ]
        }
      ]
      scale: {
        minReplicas: 0
        maxReplicas: 1
      }
    }
  }
}

// 8. Storage account for the state snapshot (Entra ID only: no account keys, no public blobs)
resource storageAccount 'Microsoft.Storage/storageAccounts@2023-01-01' = {
  name: storageAccountName
  location: location
  kind: 'StorageV2'
  sku: {
    name: 'Standard_LRS'
  }
  properties: {
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
    allowBlobPublicAccess: false
    allowSharedKeyAccess: false
  }
}

// Versioning keeps every previous snapshot, so a bad write can be rolled back
resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2023-01-01' = {
  parent: storageAccount
  name: 'default'
  properties: {
    isVersioningEnabled: true
  }
}

resource stateContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-01-01' = {
  parent: blobService
  name: stateContainerName
  properties: {
    publicAccess: 'None'
  }
}

// Old snapshot versions are deleted after 30 days, so storage doesn't grow with every write
resource stateLifecycle 'Microsoft.Storage/storageAccounts/managementPolicies@2023-01-01' = {
  parent: storageAccount
  name: 'default'
  properties: {
    policy: {
      rules: [
        {
          name: 'expire-old-snapshot-versions'
          enabled: true
          type: 'Lifecycle'
          definition: {
            actions: {
              version: {
                delete: {
                  daysAfterCreationGreaterThan: 30
                }
              }
            }
            filters: {
              blobTypes: [
                'blockBlob'
              ]
            }
          }
        }
      ]
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
output storageAccountName string = storageAccount.name
output stateContainerId string = stateContainer.id
