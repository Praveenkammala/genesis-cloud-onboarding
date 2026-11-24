[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[a-z0-9](?:[a-z0-9-]{0,58}[a-z0-9])$')]
    [string]$AppName,

    [string]$SubscriptionId,
    [string]$ResourceGroupName = 'rg-genesis-hackathon',
    [string]$Location = 'eastus',
    [ValidateSet('B1')]
    [string]$SkuName = 'B1',
    [string]$AzureOpenAIEndpoint = '',
    [string]$AzureOpenAIDeployment = '',
    [string]$CompanyTenantId = '',
    [switch]$EnableCopilotModel
)

$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$templatePath = Join-Path $PSScriptRoot 'main.bicep'

function Invoke-Az {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$AzArguments)
    & az @AzArguments
    if ($LASTEXITCODE -ne 0) {
        throw "Azure CLI failed: az $($AzArguments -join ' ')"
    }
}

if (-not (Get-Command az -ErrorAction SilentlyContinue)) {
    throw 'Azure CLI was not found. Install it, open a new PowerShell window, and run az login.'
}
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    throw 'Node.js/npm was not found. Install Node.js 18 or newer before building the frontend.'
}
if ([bool]$AzureOpenAIEndpoint -ne [bool]$AzureOpenAIDeployment) {
    throw 'Set both AzureOpenAIEndpoint and AzureOpenAIDeployment, or leave both empty.'
}
if ($EnableCopilotModel -and -not $AzureOpenAIEndpoint) {
    throw 'EnableCopilotModel requires an existing Azure OpenAI endpoint and deployment. Q&A model use is otherwise off.'
}

$null = & az account show --output none 2>$null
if ($LASTEXITCODE -ne 0) {
    throw 'No Azure CLI sign-in was found. Run az login, then run this script again.'
}
if ($SubscriptionId) {
    Invoke-Az account set --subscription $SubscriptionId
}

Push-Location $projectRoot
$tempRoot = [System.IO.Path]::GetTempPath()
$stagePath = Join-Path $tempRoot "genesis-deploy-$([guid]::NewGuid().ToString('N'))"
$zipPath = "$stagePath.zip"
try {
    npm ci
    if ($LASTEXITCODE -ne 0) { throw 'npm ci failed.' }
    npm run check
    if ($LASTEXITCODE -ne 0) { throw 'The TypeScript check failed.' }
    npm run build
    if ($LASTEXITCODE -ne 0) { throw 'The Vite production build failed.' }

    Invoke-Az group create --name $ResourceGroupName --location $Location --output none
    Invoke-Az deployment group create --resource-group $ResourceGroupName --template-file $templatePath --parameters "appName=$AppName" "location=$Location" "skuName=$SkuName" "azureOpenAIEndpoint=$AzureOpenAIEndpoint" "azureOpenAIDeployment=$AzureOpenAIDeployment" "companyTenantId=$CompanyTenantId" "enableCopilotModel=$([bool]$EnableCopilotModel)" --output none

    New-Item -ItemType Directory -Path (Join-Path $stagePath 'api') -Force | Out-Null
    New-Item -ItemType Directory -Path (Join-Path $stagePath 'dist') -Force | Out-Null
    New-Item -ItemType Directory -Path (Join-Path $stagePath 'samples') -Force | Out-Null
    Get-ChildItem -LiteralPath (Join-Path $projectRoot 'api') -File | Where-Object { $_.Extension -eq '.py' -or $_.Name -eq 'requirements.txt' } | Copy-Item -Destination (Join-Path $stagePath 'api')
    Copy-Item -LiteralPath (Join-Path $projectRoot 'api\requirements.txt') -Destination (Join-Path $stagePath 'requirements.txt')
    Copy-Item -Path (Join-Path $projectRoot 'dist\*') -Destination (Join-Path $stagePath 'dist') -Recurse -Force
    Copy-Item -LiteralPath (Join-Path $projectRoot 'samples\kyndryl-synthetic-estate.json') -Destination (Join-Path $stagePath 'samples')
    Compress-Archive -Path (Join-Path $stagePath '*') -DestinationPath $zipPath -Force

    Invoke-Az webapp deploy --resource-group $ResourceGroupName --name $AppName --src-path $zipPath --type zip
    $webAppUrl = "https://$AppName.azurewebsites.net"
    $health = $null
    for ($attempt = 1; $attempt -le 18; $attempt++) {
        try {
            $health = Invoke-RestMethod -Uri "$webAppUrl/api/health" -TimeoutSec 10
            if ($health.status -eq 'ok') { break }
        }
        catch {
            $health = $null
        }
        if ($attempt -lt 18) { Start-Sleep -Seconds 5 }
    }
    if (-not $health -or $health.status -ne 'ok') {
        throw "The App Service deployment completed, but $webAppUrl/api/health did not become healthy. Check App Service logs before using it."
    }
    Write-Host "GENESIS is healthy: $webAppUrl"
    Write-Host "Review mode configured: $($health.review_agent)"
    Write-Host 'Protected API operations fail closed until App Service Authentication is enabled, the company tenant is set, and employee cloud scopes are configured.'
    Write-Host 'The app identity has no cloud Reader role by default. Configure Entra authentication before granting it Reader access.'
    Write-Host "Identity details: az webapp identity show --resource-group $ResourceGroupName --name $AppName --output table"
    Write-Host 'After authentication is enabled, grant Reader only at the intended scan scope. See infra/README.md.'
}
finally {
    if (Test-Path -LiteralPath $stagePath) {
        $resolvedStage = [System.IO.Path]::GetFullPath($stagePath)
        $resolvedTempRoot = [System.IO.Path]::GetFullPath($tempRoot)
        if ($resolvedStage.StartsWith($resolvedTempRoot, [System.StringComparison]::OrdinalIgnoreCase) -and $resolvedStage -match 'genesis-deploy-[0-9a-f]{32}$') {
            Remove-Item -LiteralPath $resolvedStage -Recurse -Force
        }
    }
    if (Test-Path -LiteralPath $zipPath) {
        Remove-Item -LiteralPath $zipPath -Force
    }
    Pop-Location
}
