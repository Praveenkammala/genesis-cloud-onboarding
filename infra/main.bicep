@description('Globally unique DNS name for the GENESIS App Service, 2-60 lowercase letters, numbers, or hyphens.')
@minLength(2)
@maxLength(60)
param appName string

@description('Azure region for the App Service plan and web app.')
param location string = resourceGroup().location

@description('App Service Basic Linux plan size. B1 is the default for a small, always-on hackathon demo.')
@allowed([
  'B1'
])
param skuName string = 'B1'

@description('Optional Azure OpenAI resource endpoint. Leave blank to use the local deterministic reviewer.')
param azureOpenAIEndpoint string = ''

@description('Optional Azure OpenAI model deployment name. It must be configured together with azureOpenAIEndpoint.')
param azureOpenAIDeployment string = ''

@description('Company Microsoft Entra tenant ID used to reject identities from every other tenant.')
param companyTenantId string = ''

@description('JSON map keyed by employee Entra object ID; each client workspace can allow Azure subscriptions, Azure subscription/resource-group pairs, and AWS accounts.')
param userScopesJson string = '{}'

@description('Explicitly allow Copilot questions to send bounded inventory evidence to the configured Azure OpenAI deployment.')
param enableCopilotModel bool = false

var appServicePlanName = '${appName}-plan'

resource plan 'Microsoft.Web/serverfarms@2023-12-01' = {
  name: appServicePlanName
  location: location
  kind: 'linux'
  sku: {
    name: skuName
    tier: 'Basic'
    size: skuName
    family: 'B'
    capacity: 1
  }
  properties: {
    reserved: true
  }
}

resource webApp 'Microsoft.Web/sites@2023-12-01' = {
  name: appName
  location: location
  kind: 'app,linux'
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    serverFarmId: plan.id
    httpsOnly: true
    siteConfig: {
      linuxFxVersion: 'PYTHON|3.12'
      alwaysOn: true
      ftpsState: 'Disabled'
      minTlsVersion: '1.2'
      appCommandLine: 'python -m uvicorn main:app --app-dir api --host 0.0.0.0 --port 8000'
      http20Enabled: true
    }
  }
}

resource appSettings 'Microsoft.Web/sites/config@2023-12-01' = {
  parent: webApp
  name: 'appsettings'
  properties: {
    SCM_DO_BUILD_DURING_DEPLOYMENT: 'true'
    AZURE_OPENAI_ENDPOINT: azureOpenAIEndpoint
    AZURE_OPENAI_CHAT_DEPLOYMENT: azureOpenAIDeployment
    GENESIS_AUTH_MODE: 'easy_auth'
    GENESIS_ALLOWED_TENANT_ID: companyTenantId
    GENESIS_USER_SCOPES_JSON: userScopesJson
    GENESIS_COPILOT_USE_AZURE_OPENAI: string(enableCopilotModel)
  }
}

output webAppUrl string = 'https://${webApp.properties.defaultHostName}'
output managedIdentityPrincipalId string = webApp.identity.principalId
output managedIdentityResourceId string = webApp.id
