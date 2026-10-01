# ==============================================================================
# AWS Teardown Script (reverses infra/aws/setup.ps1 + the Lambda created by deploy.yml)
# ==============================================================================
# Safe to re-run: resources that are already gone are skipped.
# The GitHub OIDC provider is account-wide (other repos may use it), so it is
# only removed when -DeleteOidcProvider is passed.
param(
    [string]$Region = "us-east-1",
    [string]$AppName = "ragprod",
    [string]$FunctionName = "ragprod-api",
    [string]$EcrRepoName = "rag-api",
    [string]$GitHubRoleName = "github-actions-ragprod-aws-role",
    [string[]]$SecretNames = @("GROQ_API_KEY", "GOOGLE_API_KEY"),
    [switch]$DeleteOidcProvider,
    [switch]$Force
)

# Helper function to execute AWS CLI commands safely and verify exit code
function Invoke-AwsCmd {
    param(
        [string[]]$CmdArgs
    )
    $output = & aws @CmdArgs 2>&1
    if ($LASTEXITCODE -ne 0) {
        $errorMsg = ($output | Out-String).Trim()
        throw "AWS CLI command failed (aws $($CmdArgs -join ' ')):`n$errorMsg"
    }
    return $output
}

# Helper function to test if an AWS resource exists without throwing native errors
function Test-AwsResourceExists {
    param(
        [string[]]$CmdArgs
    )
    $null = & aws @CmdArgs 2>$null
    return ($LASTEXITCODE -eq 0)
}

# Helper function to run a delete command, treating "not found" as already deleted
function Invoke-AwsDelete {
    param(
        [string]$Description,
        [string[]]$CmdArgs
    )
    $output = & aws @CmdArgs 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Host "   Deleted $Description." -ForegroundColor Green
    } elseif (($output | Out-String) -match "NotFound|NoSuchEntity|does not exist") {
        Write-Host "   $Description not found, skipping." -ForegroundColor DarkGray
    } else {
        throw "Failed to delete $Description (aws $($CmdArgs -join ' ')):`n$(($output | Out-String).Trim())"
    }
}

# Helper function to delete an IAM role (policies must be detached/deleted first)
function Remove-IamRole {
    param(
        [string]$RoleName
    )
    if (-not (Test-AwsResourceExists -CmdArgs @("iam", "get-role", "--role-name", $RoleName))) {
        Write-Host "   IAM Role '$RoleName' not found, skipping." -ForegroundColor DarkGray
        return
    }
    $attached = Invoke-AwsCmd -CmdArgs @("iam", "list-attached-role-policies", "--role-name", $RoleName, "--query", "AttachedPolicies[].PolicyArn", "--output", "text")
    foreach ($policyArn in (($attached | Out-String) -split "\s+" | Where-Object { $_ -and $_ -ne "None" })) {
        Invoke-AwsCmd -CmdArgs @("iam", "detach-role-policy", "--role-name", $RoleName, "--policy-arn", $policyArn) | Out-Null
    }
    $inline = Invoke-AwsCmd -CmdArgs @("iam", "list-role-policies", "--role-name", $RoleName, "--query", "PolicyNames", "--output", "text")
    foreach ($policyName in (($inline | Out-String) -split "\s+" | Where-Object { $_ -and $_ -ne "None" })) {
        Invoke-AwsCmd -CmdArgs @("iam", "delete-role-policy", "--role-name", $RoleName, "--policy-name", $policyName) | Out-Null
    }
    Invoke-AwsCmd -CmdArgs @("iam", "delete-role", "--role-name", $RoleName) | Out-Null
    Write-Host "   Deleted IAM Role '$RoleName'." -ForegroundColor Green
}

# Helper function to write UTF-8 files WITHOUT Byte Order Mark (BOM)
function Write-JsonFileNoBOM {
    param(
        [string]$FilePath,
        [string]$JsonContent
    )
    $utf8NoBom = [System.Text.UTF8Encoding]::new($false)
    [System.IO.File]::WriteAllText($FilePath, $JsonContent, $utf8NoBom)
}

Write-Host "1. Checking AWS CLI authentication..." -ForegroundColor Cyan
$callerIdentityJson = Invoke-AwsCmd -CmdArgs @("sts", "get-caller-identity", "--output", "json")
$callerIdentity = $callerIdentityJson | ConvertFrom-Json
$awsAccountId = $callerIdentity.Account
Write-Host "   Authenticated to AWS Account ID: $awsAccountId (Region: $Region)" -ForegroundColor Green

$lambdaRoleName = "LambdaExecutionRole-$AppName"
$logGroupName = "/aws/lambda/$FunctionName"
$oidcProviderArn = "arn:aws:iam::${awsAccountId}:oidc-provider/token.actions.githubusercontent.com"
$stateBucket = "$AppName-state-$awsAccountId"

Write-Host "`nThe following resources will be PERMANENTLY deleted:" -ForegroundColor Yellow
Write-Host "   Lambda function + Function URL:  $FunctionName"
Write-Host "   CloudWatch log group:            $logGroupName"
Write-Host "   ECR repository (all images):     $EcrRepoName"
Write-Host "   S3 state bucket (all versions):  $stateBucket"
Write-Host "   Secrets Manager (no recovery):   $($SecretNames -join ', ')"
Write-Host "   IAM roles:                       $lambdaRoleName, $GitHubRoleName"
if ($DeleteOidcProvider) {
    Write-Host "   GitHub OIDC provider:            $oidcProviderArn"
}

if (-not $Force) {
    $answer = Read-Host "`nType 'delete' to continue"
    if ($answer -ne "delete") {
        Write-Host "Aborted. Nothing was deleted." -ForegroundColor Yellow
        exit 1
    }
}

Write-Host "`n2. Deleting Lambda function (also removes its Function URL and permissions)..." -ForegroundColor Cyan
Invoke-AwsDelete -Description "Lambda function '$FunctionName'" -CmdArgs @("lambda", "delete-function", "--function-name", $FunctionName, "--region", $Region)

Write-Host "`n3. Deleting CloudWatch log group..." -ForegroundColor Cyan
Invoke-AwsDelete -Description "log group '$logGroupName'" -CmdArgs @("logs", "delete-log-group", "--log-group-name", $logGroupName, "--region", $Region)

Write-Host "`n4. Deleting ECR repository and all its images..." -ForegroundColor Cyan
Invoke-AwsDelete -Description "ECR repository '$EcrRepoName'" -CmdArgs @("ecr", "delete-repository", "--repository-name", $EcrRepoName, "--force", "--region", $Region)

Write-Host "`n4b. Emptying and deleting the S3 state bucket (all snapshot versions)..." -ForegroundColor Cyan
if (Test-AwsResourceExists -CmdArgs @("s3api", "head-bucket", "--bucket", $stateBucket)) {
    # A versioned bucket can only be deleted once every object version and delete marker is gone
    $listing = Invoke-AwsCmd -CmdArgs @("s3api", "list-object-versions", "--bucket", $stateBucket, "--output", "json") | ConvertFrom-Json
    $toDelete = @(@($listing.Versions) + @($listing.DeleteMarkers) | Where-Object { $_ } | ForEach-Object { @{ Key = $_.Key; VersionId = $_.VersionId } })
    for ($i = 0; $i -lt $toDelete.Count; $i += 1000) {  # delete-objects accepts at most 1000 per call
        $batch = @{ Objects = @($toDelete[$i..([Math]::Min($i + 999, $toDelete.Count - 1))]); Quiet = $true } | ConvertTo-Json -Depth 4
        $tempBatch = [System.IO.Path]::GetTempFileName()
        try {
            Write-JsonFileNoBOM -FilePath $tempBatch -JsonContent $batch
            Invoke-AwsCmd -CmdArgs @("s3api", "delete-objects", "--bucket", $stateBucket, "--delete", "file://$tempBatch") | Out-Null
        } finally {
            Remove-Item $tempBatch -ErrorAction SilentlyContinue
        }
    }
    Invoke-AwsCmd -CmdArgs @("s3api", "delete-bucket", "--bucket", $stateBucket, "--region", $Region) | Out-Null
    Write-Host "   Deleted S3 bucket '$stateBucket' ($($toDelete.Count) object versions)." -ForegroundColor Green
} else {
    Write-Host "   S3 bucket '$stateBucket' not found, skipping." -ForegroundColor DarkGray
}

Write-Host "`n5. Deleting Secrets Manager secrets (immediately, without recovery window)..." -ForegroundColor Cyan
foreach ($secretName in $SecretNames) {
    Invoke-AwsDelete -Description "secret '$secretName'" -CmdArgs @("secretsmanager", "delete-secret", "--secret-id", $secretName, "--force-delete-without-recovery", "--region", $Region)
}

Write-Host "`n6. Deleting IAM roles..." -ForegroundColor Cyan
Remove-IamRole -RoleName $lambdaRoleName
Remove-IamRole -RoleName $GitHubRoleName

if ($DeleteOidcProvider) {
    Write-Host "`n7. Deleting GitHub OIDC provider..." -ForegroundColor Cyan
    Invoke-AwsDelete -Description "GitHub OIDC provider" -CmdArgs @("iam", "delete-open-id-connect-provider", "--open-id-connect-provider-arn", $oidcProviderArn)
} else {
    Write-Host "`n7. Keeping GitHub OIDC provider (account-wide). Pass -DeleteOidcProvider to remove it." -ForegroundColor DarkGray
}

Write-Host "`n=== AWS TEARDOWN COMPLETE ===" -ForegroundColor Green
Write-Host "Optionally remove these from GitHub (Settings -> Secrets and variables -> Actions):" -ForegroundColor Yellow
Write-Host "Secret:    AWS_ROLE_TO_ASSUME"
Write-Host "Variables: AWS_REGION, AWS_ECR_REPO, AWS_LAMBDA_ROLE_ARN"
