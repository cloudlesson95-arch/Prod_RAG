# ==============================================================================
# Dynamic & Portable AWS Provisioning & GitHub OIDC Setup Script (AWS Lambda Container)
# ==============================================================================
param(
    [string]$Region = "us-east-1",
    [string]$AppName = "ragprod",
    [string]$GitHubRepo = "cloudlesson95-arch/Prod_RAG"
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

# 1. AWS ECR Repository
$ecrRepoName = "rag-api"
Write-Host "`n2. Ensuring ECR Repository '$ecrRepoName' exists..." -ForegroundColor Cyan
if (Test-AwsResourceExists -CmdArgs @("ecr", "describe-repositories", "--repository-names", $ecrRepoName, "--region", $Region)) {
    Write-Host "   ECR Repository '$ecrRepoName' already exists." -ForegroundColor Green
} else {
    Invoke-AwsCmd -CmdArgs @("ecr", "create-repository", "--repository-name", $ecrRepoName, "--region", $Region) | Out-Null
    Write-Host "   Created ECR Repository '$ecrRepoName'." -ForegroundColor Green
}
$ecrUri = "$awsAccountId.dkr.ecr.$Region.amazonaws.com/$ecrRepoName"

# 2. AWS Secrets Manager Seeding
Write-Host "`n3. Seeding secrets into AWS Secrets Manager..." -ForegroundColor Cyan
$groqKey = Read-Host "Enter GROQ_API_KEY (press Enter to skip if already created)"
if ($groqKey) {
    if (Test-AwsResourceExists -CmdArgs @("secretsmanager", "describe-secret", "--secret-id", "GROQ_API_KEY", "--region", $Region)) {
        Invoke-AwsCmd -CmdArgs @("secretsmanager", "put-secret-value", "--secret-id", "GROQ_API_KEY", "--secret-string", $groqKey, "--region", $Region) | Out-Null
        Write-Host "   Updated GROQ_API_KEY in AWS Secrets Manager." -ForegroundColor Green
    } else {
        Invoke-AwsCmd -CmdArgs @("secretsmanager", "create-secret", "--name", "GROQ_API_KEY", "--secret-string", $groqKey, "--region", $Region) | Out-Null
        Write-Host "   Created GROQ_API_KEY in AWS Secrets Manager." -ForegroundColor Green
    }
}

$googleKey = Read-Host "Enter GOOGLE_API_KEY (press Enter to skip if already created)"
if ($googleKey) {
    if (Test-AwsResourceExists -CmdArgs @("secretsmanager", "describe-secret", "--secret-id", "GOOGLE_API_KEY", "--region", $Region)) {
        Invoke-AwsCmd -CmdArgs @("secretsmanager", "put-secret-value", "--secret-id", "GOOGLE_API_KEY", "--secret-string", $googleKey, "--region", $Region) | Out-Null
        Write-Host "   Updated GOOGLE_API_KEY in AWS Secrets Manager." -ForegroundColor Green
    } else {
        Invoke-AwsCmd -CmdArgs @("secretsmanager", "create-secret", "--name", "GOOGLE_API_KEY", "--secret-string", $googleKey, "--region", $Region) | Out-Null
        Write-Host "   Created GOOGLE_API_KEY in AWS Secrets Manager." -ForegroundColor Green
    }
}

# 3. IAM Execution Role for AWS Lambda Container
Write-Host "`n4. Setting up IAM Execution Role for AWS Lambda..." -ForegroundColor Cyan
$lambdaRoleName = "LambdaExecutionRole-$AppName"
$lambdaTrustPolicy = @{
    Version = "2012-10-17"
    Statement = @(
        @{
            Effect = "Allow"
            Principal = @{ Service = "lambda.amazonaws.com" }
            Action = "sts:AssumeRole"
        }
    )
} | ConvertTo-Json -Depth 3

if (Test-AwsResourceExists -CmdArgs @("iam", "get-role", "--role-name", $lambdaRoleName)) {
    Write-Host "   IAM Role '$lambdaRoleName' already exists." -ForegroundColor Green
} else {
    $tempTrust = [System.IO.Path]::GetTempFileName()
    $tempPolicy = [System.IO.Path]::GetTempFileName()
    try {
        Write-JsonFileNoBOM -FilePath $tempTrust -JsonContent $lambdaTrustPolicy
        Invoke-AwsCmd -CmdArgs @("iam", "create-role", "--role-name", $lambdaRoleName, "--assume-role-policy-document", "file://$tempTrust") | Out-Null
        Invoke-AwsCmd -CmdArgs @("iam", "attach-role-policy", "--role-name", $lambdaRoleName, "--policy-arn", "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole") | Out-Null

        $secretsPolicy = @{
            Version = "2012-10-17"
            Statement = @(
                @{
                    Effect = "Allow"
                    Action = @("secretsmanager:GetSecretValue")
                    Resource = "*"
                }
            )
        } | ConvertTo-Json -Depth 3

        Write-JsonFileNoBOM -FilePath $tempPolicy -JsonContent $secretsPolicy
        Invoke-AwsCmd -CmdArgs @("iam", "put-role-policy", "--role-name", $lambdaRoleName, "--policy-name", "SecretsManagerRead", "--policy-document", "file://$tempPolicy") | Out-Null
        Write-Host "   Created IAM Role '$lambdaRoleName'." -ForegroundColor Green
    } finally {
        Remove-Item $tempTrust -ErrorAction SilentlyContinue
        Remove-Item $tempPolicy -ErrorAction SilentlyContinue
    }
}
$lambdaRoleArn = "arn:aws:iam::${awsAccountId}:role/$lambdaRoleName"

# 4. GitHub Actions OIDC Federated Role
Write-Host "`n5. Setting up GitHub Actions OIDC Federated Role..." -ForegroundColor Cyan
$oidcProviderArn = "arn:aws:iam::${awsAccountId}:oidc-provider/token.actions.githubusercontent.com"

if (Test-AwsResourceExists -CmdArgs @("iam", "get-open-id-connect-provider", "--open-id-connect-provider-arn", $oidcProviderArn)) {
    Write-Host "   GitHub OIDC Provider already exists." -ForegroundColor Green
} else {
    Invoke-AwsCmd -CmdArgs @(
        "iam", "create-open-id-connect-provider",
        "--url", "https://token.actions.githubusercontent.com",
        "--client-id-list", "sts.amazonaws.com",
        "--thumbprint-list", "6938fd5d98bab03faadb97b34396831e3780aea1"
    ) | Out-Null
    Write-Host "   Created GitHub OIDC Provider in IAM." -ForegroundColor Green
}

$githubRoleName = "github-actions-ragprod-aws-role"
$githubTrustPolicy = @{
    Version = "2012-10-17"
    Statement = @(
        @{
            Effect = "Allow"
            Principal = @{ Federated = $oidcProviderArn }
            Action = "sts:AssumeRoleWithWebIdentity"
            Condition = @{
                StringEquals = @{ "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com" }
                StringLike = @{ "token.actions.githubusercontent.com:sub" = "repo:${GitHubRepo}:*" }
            }
        }
    )
} | ConvertTo-Json -Depth 5

if (Test-AwsResourceExists -CmdArgs @("iam", "get-role", "--role-name", $githubRoleName)) {
    Write-Host "   GitHub Actions IAM Role '$githubRoleName' already exists." -ForegroundColor Green
} else {
    $tempTrust = [System.IO.Path]::GetTempFileName()
    $tempPolicy = [System.IO.Path]::GetTempFileName()
    try {
        Write-JsonFileNoBOM -FilePath $tempTrust -JsonContent $githubTrustPolicy
        Invoke-AwsCmd -CmdArgs @("iam", "create-role", "--role-name", $githubRoleName, "--assume-role-policy-document", "file://$tempTrust") | Out-Null

        $deployPolicy = @{
            Version = "2012-10-17"
            Statement = @(
                @{
                    Effect = "Allow"
                    Action = @(
                        "ecr:GetAuthorizationToken",
                        "ecr:BatchCheckLayerAvailability",
                        "ecr:GetDownloadUrlForLayer",
                        "ecr:BatchGetImage",
                        "ecr:PutImage",
                        "ecr:InitiateLayerUpload",
                        "ecr:UploadLayerPart",
                        "ecr:CompleteLayerUpload"
                    )
                    Resource = "*"
                },
                @{
                    Effect = "Allow"
                    Action = @(
                        "lambda:CreateFunction",
                        "lambda:UpdateFunctionCode",
                        "lambda:UpdateFunctionConfiguration",
                        "lambda:GetFunction",
                        "lambda:GetFunctionConfiguration",
                        "lambda:CreateFunctionUrlConfig",
                        "lambda:GetFunctionUrlConfig",
                        "lambda:AddPermission"
                    )
                    Resource = "*"
                },
                @{
                    Effect = "Allow"
                    Action = "iam:PassRole"
                    Resource = $lambdaRoleArn
                }
            )
        } | ConvertTo-Json -Depth 5

        Write-JsonFileNoBOM -FilePath $tempPolicy -JsonContent $deployPolicy
        Invoke-AwsCmd -CmdArgs @("iam", "put-role-policy", "--role-name", $githubRoleName, "--policy-name", "GitHubActionsDeployPolicy", "--policy-document", "file://$tempPolicy") | Out-Null
        Write-Host "   Created GitHub Actions OIDC IAM Role '$githubRoleName'." -ForegroundColor Green
    } finally {
        Remove-Item $tempTrust -ErrorAction SilentlyContinue
        Remove-Item $tempPolicy -ErrorAction SilentlyContinue
    }
}
$githubRoleArn = "arn:aws:iam::${awsAccountId}:role/$githubRoleName"

Write-Host "`n=== AWS INFRASTRUCTURE & OIDC SETUP COMPLETE ===" -ForegroundColor Green
Write-Host "Add the following SECRETS to your GitHub Repository (Settings -> Secrets and variables -> Actions):" -ForegroundColor Yellow
Write-Host "AWS_ROLE_TO_ASSUME:    $githubRoleArn"
Write-Host "`nAdd the following VARIABLES (Settings -> Secrets and variables -> Actions -> Variables):" -ForegroundColor Yellow
Write-Host "AWS_REGION:            $Region"
Write-Host "AWS_ECR_REPO:          $ecrUri"
Write-Host "AWS_LAMBDA_ROLE_ARN:   $lambdaRoleArn"
