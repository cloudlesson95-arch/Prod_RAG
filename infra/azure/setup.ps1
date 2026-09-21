# ==============================================================================
# Robust One-time Azure Provisioning & OIDC Setup Script
# ==============================================================================
param(
    [string]$ResourceGroupName = "rg-ragprod",
    [string]$Location = "eastus",
    [string]$GitHubRepo = "cloudlesson95-arch/Prod_RAG"
)

$ErrorActionPreference = "Stop"

# Use script directory to locate Bicep files reliably
$bicepFile = Join-Path $PSScriptRoot "main.bicep"
$paramFile = Join-Path $PSScriptRoot "parameters.json"

Write-Host "1. Creating Resource Group '$ResourceGroupName' in '$Location'..." -ForegroundColor Cyan
az group create --name $ResourceGroupName --location $Location | Out-Null

Write-Host "2. Deploying Bicep infrastructure from '$bicepFile'..." -ForegroundColor Cyan
$deployJson = az deployment group create `
    --resource-group $ResourceGroupName `
    --template-file $bicepFile `
    --parameters $paramFile `
    --query "properties.outputs" -o json | ConvertFrom-Json

$kvName = $deployJson.keyVaultName.value
$acrName = $deployJson.acrName.value
$containerAppName = $deployJson.containerAppName.value
$containerAppUrl = $deployJson.containerAppUrl.value
$managedIdentityPrincipalId = $deployJson.managedIdentityPrincipalId.value

Write-Host "   Infrastructure deployed! Key Vault: $kvName | ACR: $acrName" -ForegroundColor Green

Write-Host "3. Setting up RBAC permissions..." -ForegroundColor Cyan
$kvId = (az keyvault show --name $kvName --query id -o tsv)

# Grant Managed Identity read access to Key Vault
az role assignment create --assignee $managedIdentityPrincipalId --role "Key Vault Secrets User" --scope $kvId 2>$null | Out-Null

# Grant Managed Identity AcrPull access to ACR
$acrId = (az acr show --name $acrName --query id -o tsv)
az role assignment create --assignee $managedIdentityPrincipalId --role "AcrPull" --scope $acrId 2>$null | Out-Null

# Grant CURRENT SIGNED-IN USER write access to Key Vault (Key Vault Secrets Officer)
$currentUser = (az ad signed-in-user show --query id -o tsv 2>$null)
if (-not $currentUser) {
    $currentUser = (az account show --query user.name -o tsv)
}
az role assignment create --assignee $currentUser --role "Key Vault Secrets Officer" --scope $kvId 2>$null | Out-Null

Write-Host "   RBAC permissions configured. Waiting 10s for Azure RBAC propagation..." -ForegroundColor Green
Start-Sleep -Seconds 10

Write-Host "4. Seeding secrets into Key Vault '$kvName'..." -ForegroundColor Cyan
$groqKey = Read-Host "Enter GROQ_API_KEY (press Enter to skip if using env fallback)"
if ($groqKey) {
    az keyvault secret set --vault-name $kvName --name "GROQ-API-KEY" --value $groqKey | Out-Null
    Write-Host "   GROQ-API-KEY stored in Key Vault." -ForegroundColor Green
}

$googleKey = Read-Host "Enter GOOGLE_API_KEY (press Enter to skip if using env fallback)"
if ($googleKey) {
    az keyvault secret set --vault-name $kvName --name "GOOGLE-API-KEY" --value $googleKey | Out-Null
    Write-Host "   GOOGLE-API-KEY stored in Key Vault." -ForegroundColor Green
}

Write-Host "5. Setting up OIDC for GitHub Actions ($GitHubRepo)..." -ForegroundColor Cyan
$appName = "github-actions-ragprod"
$app = az ad app list --display-name $appName -o json | ConvertFrom-Json

if ($app.Count -eq 0) {
    $app = az ad app create --display-name $appName --output json | ConvertFrom-Json
} else {
    $app = $app[0]
}
$appId = $app.appId

# Ensure Service Principal exists
$sp = az ad sp list --filter "appId eq '$appId'" -o json | ConvertFrom-Json
if ($sp.Count -eq 0) {
    $sp = az ad sp create --id $appId --output json | ConvertFrom-Json
}

# Grant Contributor role on the resource group to GitHub Actions
$rgId = (az group show --name $ResourceGroupName --query id -o tsv)
az role assignment create --assignee $appId --role "Contributor" --scope $rgId 2>$null | Out-Null

# Grant AcrPush on ACR to GitHub Actions
az role assignment create --assignee $appId --role "AcrPush" --scope $acrId 2>$null | Out-Null

# Ensure Federated Credential exists
$fedCreds = az ad app federated-credential list --id $appId -o json | ConvertFrom-Json
$fedExists = $fedCreds | Where-Object { $_.name -eq "github-actions-main" }

if (-not $fedExists) {
    $params = @{
        name = "github-actions-main"
        issuer = "https://token.actions.githubusercontent.com"
        subject = "repo:${GitHubRepo}:ref:refs/heads/main"
        description = "GitHub Actions OIDC for main branch deploy"
        audiences = @("api://AzureADTokenExchange")
    } | ConvertTo-Json -Depth 3

    $tempFile = [System.IO.Path]::GetTempFileName()
    $params | Out-File -FilePath $tempFile -Encoding utf8
    az ad app federated-credential create --id $appId --parameters $tempFile | Out-Null
    Remove-Item $tempFile
}

$tenantId = (az account show --query tenantId -o tsv)
$subscriptionId = (az account show --query id -o tsv)

Write-Host "`n=== OIDC & INFRASTRUCTURE SETUP COMPLETE ===" -ForegroundColor Green
Write-Host "Add the following SECRETS to your GitHub Repository (Settings -> Secrets and variables -> Actions):" -ForegroundColor Yellow
Write-Host "AZURE_CLIENT_ID:       $appId"
Write-Host "AZURE_TENANT_ID:       $tenantId"
Write-Host "AZURE_SUBSCRIPTION_ID: $subscriptionId"
Write-Host "`nAdd the following VARIABLES (Settings -> Secrets and variables -> Actions -> Variables):" -ForegroundColor Yellow
Write-Host "RESOURCE_GROUP:        $ResourceGroupName"
Write-Host "ACR_NAME:              $acrName"
Write-Host "CONTAINER_APP_NAME:    $containerAppName"
Write-Host "DEPLOYED_APP_URL:      https://$containerAppUrl"
