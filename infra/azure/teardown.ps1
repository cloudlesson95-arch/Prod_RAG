# ==============================================================================
# Azure Teardown Script (reverses infra/azure/setup.ps1)
# ==============================================================================
# Deleting the resource group removes everything main.bicep created (ACR, Key Vault,
# Container App + environment, Log Analytics, App Insights, managed identity) and
# the role assignments scoped to them. Two things live outside the resource group
# and are cleaned up separately:
#   - the soft-deleted Key Vault (purged, so the name can be reused by setup.ps1)
#   - the Entra ID app registration used by GitHub Actions OIDC
# Safe to re-run: resources that are already gone are skipped.
param(
    [string]$ResourceGroupName = "rg-ragprod",
    [string]$GitHubAppName = "github-actions-ragprod",
    [switch]$SkipKeyVaultPurge,
    [switch]$Force
)

Write-Host "1. Checking Azure CLI authentication..." -ForegroundColor Cyan
$account = az account show -o json | ConvertFrom-Json
if ($LASTEXITCODE -ne 0 -or -not $account) {
    throw "Not logged in to Azure CLI. Run 'az login' first."
}
Write-Host "   Subscription: $($account.name) ($($account.id))" -ForegroundColor Green

$rgExists = (az group exists --name $ResourceGroupName) -eq "true"
$appIds = @(az ad app list --display-name $GitHubAppName --query "[].appId" -o tsv | Where-Object { $_ })

Write-Host "`nThe following resources will be PERMANENTLY deleted:" -ForegroundColor Yellow
if ($rgExists) {
    Write-Host "   Resource group '$ResourceGroupName' and everything in it:"
    az resource list --resource-group $ResourceGroupName --query "[].{Name:name, Type:type}" -o table
} else {
    Write-Host "   Resource group '$ResourceGroupName': not found (already deleted)" -ForegroundColor DarkGray
}
if (-not $SkipKeyVaultPurge) {
    Write-Host "   Soft-deleted Key Vault(s) from '$ResourceGroupName' (purged, secrets unrecoverable)"
}
if ($appIds.Count -gt 0) {
    Write-Host "   Entra ID app registration '$GitHubAppName' (appId: $($appIds -join ', '))"
} else {
    Write-Host "   Entra ID app registration '$GitHubAppName': not found" -ForegroundColor DarkGray
}

if (-not $Force) {
    $answer = Read-Host "`nType 'delete' to continue"
    if ($answer -ne "delete") {
        Write-Host "Aborted. Nothing was deleted." -ForegroundColor Yellow
        exit 1
    }
}

Write-Host "`n2. Deleting resource group '$ResourceGroupName' (usually takes 5-15 minutes)..." -ForegroundColor Cyan
if ($rgExists) {
    az group delete --name $ResourceGroupName --yes
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to delete resource group '$ResourceGroupName'."
    }
    Write-Host "   Deleted resource group '$ResourceGroupName'." -ForegroundColor Green
} else {
    Write-Host "   Resource group not found, skipping." -ForegroundColor DarkGray
}

Write-Host "`n3. Purging soft-deleted Key Vault(s)..." -ForegroundColor Cyan
if ($SkipKeyVaultPurge) {
    Write-Host "   Skipped (-SkipKeyVaultPurge). The vault stays recoverable for the retention period (90 days by default)." -ForegroundColor DarkGray
} else {
    $rgPattern = "/resourceGroups/$([regex]::Escape($ResourceGroupName))/"
    $deletedVaults = @(az keyvault list-deleted -o json | ConvertFrom-Json | Where-Object { $_.properties.vaultId -match $rgPattern })
    if ($deletedVaults.Count -eq 0) {
        Write-Host "   No soft-deleted Key Vaults found for '$ResourceGroupName'." -ForegroundColor DarkGray
    }
    foreach ($vault in $deletedVaults) {
        Write-Host "   Purging Key Vault '$($vault.name)' (can take a minute)..."
        az keyvault purge --name $vault.name
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to purge Key Vault '$($vault.name)'."
        }
        Write-Host "   Purged Key Vault '$($vault.name)'." -ForegroundColor Green
    }
}

Write-Host "`n4. Deleting Entra ID app registration '$GitHubAppName'..." -ForegroundColor Cyan
if ($appIds.Count -eq 0) {
    Write-Host "   App registration not found, skipping." -ForegroundColor DarkGray
}
foreach ($appId in $appIds) {
    # Service principal first, then the app registration (which also removes its federated credentials)
    az ad sp delete --id $appId 2>$null
    az ad app delete --id $appId
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to delete app registration '$appId'."
    }
    Write-Host "   Deleted app registration '$appId'." -ForegroundColor Green
}

Write-Host "`n=== AZURE TEARDOWN COMPLETE ===" -ForegroundColor Green
Write-Host "Optionally remove these from GitHub (Settings -> Secrets and variables -> Actions):" -ForegroundColor Yellow
Write-Host "Secrets:   AZURE_CLIENT_ID, AZURE_TENANT_ID, AZURE_SUBSCRIPTION_ID"
Write-Host "Variables: RESOURCE_GROUP, ACR_NAME, CONTAINER_APP_NAME, DEPLOYED_APP_URL"
