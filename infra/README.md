# Deploy GENESIS to Azure App Service

This deployment uses one Linux App Service for the FastAPI API and the compiled React frontend. The app uses a system-assigned managed identity for Azure calls. The deployment script does **not** assign that identity Reader access and does not create an Azure OpenAI resource or model deployment.

## What the deployment creates

- A Linux App Service plan (default SKU: Basic B1, one instance).
- A Python 3.12 App Service web app with HTTPS-only and FTPS disabled.
- A system-assigned managed identity.
- App settings for optional Azure OpenAI endpoint and deployment values.
- A ZIP deployment containing the API, Python requirements, and built frontend.

The plan is a paid Azure resource. Review current regional pricing and your company’s credit terms before deploying. The script accepts no budget cap and Azure credits are not a hard spending limit. Use a dedicated resource group for this demo.

## Deploy

Requirements: Azure CLI, Node.js/npm, an Azure subscription with permission to create the listed resources, and PowerShell.

```powershell
az login
az account set --subscription <subscription-guid>
.\infra\deploy.ps1 -AppName <globally-unique-lowercase-name> -SubscriptionId <subscription-guid> -Location eastus -CompanyTenantId <company-tenant-guid>
```

The script builds and type-checks the frontend, creates the resource group if needed, deploys `main.bicep`, ZIP-deploys the app, and polls `/api/health`. It prints the site address and managed identity lookup command only after the health endpoint responds. The app name must be globally unique because it becomes `<name>.azurewebsites.net`.

To configure Azure OpenAI at deployment time, provide an existing Azure OpenAI resource endpoint and a deployed model name:

```powershell
.\infra\deploy.ps1 -AppName <name> -SubscriptionId <subscription-guid> -Location eastus `
  -AzureOpenAIEndpoint https://<resource>.openai.azure.com `
  -AzureOpenAIDeployment <deployment-name>
```

Do not include a key. The deployment sets the two app settings `AZURE_OPENAI_ENDPOINT` and `AZURE_OPENAI_CHAT_DEPLOYMENT`. The app uses Microsoft Entra credentials from its system-assigned managed identity. Give that identity the **Cognitive Services OpenAI User** role at the model resource scope.

After deployment and role assignment, open the Overview page and click **Check connection**. It exercises the Responses API with a no-op local tool and strict structured output, then reports auth/RBAC, deployment/region, quota/capacity, feature-support, or timeout failures. Run discovery afterward and confirm the Investigator badge says Azure OpenAI; a local fallback is recorded visibly when a model call fails.

Copilot uses the same read-only inventory, graph, impact, findings, and Terraform mapping tools. It stays in local tool mode by default, even when the review agents use Azure OpenAI. To let the model select those tools and synthesize answers, add `-EnableCopilotModel` to the deploy command after your data-processing review approves that path.

## Secure the site before granting cloud read access

The Bicep template sets `GENESIS_AUTH_MODE=easy_auth` and gives the app identity **no Reader role**. Stateful API operations fail closed until App Service Authentication is enabled and the company tenant plus employee scope map are configured. `/api/health` and the fictional sample inventory are the only anonymous API routes. Before granting cloud access, configure Microsoft Entra sign-in for the App Service:

1. Open the web app in the Azure portal and go to **Settings → Authentication → Add identity provider**.
2. Choose **Microsoft** / Microsoft Entra ID. Create or select a single-tenant app registration for the company workforce tenant.
3. Require authentication and use the redirect-to-login action for unauthenticated website requests. Restrict the allowed tenant to the company tenant. Exclude `/api/health`, `/api/demo`, `/api/demo/baseline`, and `/api/demo/aws` from the authentication redirect; only health and fictional sample inventory are anonymous at the API layer. Use the portal-generated client credential or a managed secret reference; do not paste credentials into this repository.
4. Save the provider, open the site, and confirm that an unauthenticated browser is sent to sign-in. Confirm that the intended hackathon account can sign in.
5. Set the App Setting `GENESIS_ALLOWED_TENANT_ID` to the company tenant GUID. The API checks this tenant and the employee object ID from the App Service principal before allowing stateful operations. App Service injects `X-MS-CLIENT-PRINCIPAL` and `X-MS-CLIENT-PRINCIPAL-IDP` after authentication; the API also requires the platform's read-only `WEBSITE_AUTH_ENABLED=true` setting. See [Microsoft's App Service identity header reference](https://learn.microsoft.com/en-us/azure/app-service/configure-authentication-user-identities).
6. Set `GENESIS_USER_SCOPES_JSON` to the access map maintained by the application owner. Example shape:

```json
{
  "<employee-entra-object-id>": {
    "clients": {
      "client-acme-prod": {
        "name": "Acme Production",
        "azure_resource_groups": ["<subscription-guid>/<resource-group>"],
        "aws_account_ids": ["123456789012"]
      }
    }
  }
}
```

The browser shows only the client workspaces assigned to the signed-in employee. Each employee can import or scan only the cloud scopes listed under that workspace. Prefer `azure_resource_groups` for narrow Azure access; use `azure_subscription_ids` only when subscription-wide discovery is approved. The group entry format is `<subscription-guid>/<resource-group>`. A run, its Copilot questions, approval, and export are bound to the creating employee and client workspace. Keep the access map controlled and reviewed; it is a small-pilot configuration mechanism, not production identity governance.
7. Only after authentication, the tenant check, and employee scope map are verified, assign the web app identity Reader at the narrowest intended scan scope.

Get the identity principal ID:

```powershell
$principalId = az webapp identity show --resource-group rg-genesis-hackathon --name <app-name> --query principalId --output tsv
```

For a resource-group-limited scan:

```powershell
az role assignment create --assignee-object-id $principalId --assignee-principal-type ServicePrincipal --role Reader --scope "/subscriptions/<subscription-guid>/resourceGroups/<resource-group>"
```

For subscription-wide discovery, use the subscription scope only when that broader read access is approved:

```powershell
az role assignment create --assignee-object-id $principalId --assignee-principal-type ServicePrincipal --role Reader --scope "/subscriptions/<subscription-guid>"
```

Sign in to the site, choose **Configure a read-only Azure scan**, enter the subscription GUID, and, when Reader was granted at resource-group scope, enter that same resource-group filter. Azure Resource Graph is read-only. The generated Terraform package is not applied.

## Local Azure scans

For a local demo, the API uses `DefaultAzureCredential`. Install Azure CLI, run `az login`, and grant the signed-in identity Reader at the desired scope. Run `npm run dev` from the project root and start a scan from the UI.

## Enterprise hardening work after the hackathon

The prototype keeps run approvals and generated packages in API-process memory and isolates a run to its creating employee. Use one App Service instance for the demo. A production service needs durable, tenant-aware run storage, audit retention, client-cell membership and role-based authorization, private networking if required, Key Vault integration for deployment secrets, rate limits, and reviewed policy controls. Preserve the rule that the AI reviewer and Copilot cannot invoke infrastructure write tools.

## Remove the demo hosting resources

When you are finished, delete only the dedicated resource group created for GENESIS:

```powershell
az group delete --name rg-genesis-hackathon --yes --no-wait
```

This removes all resources inside that resource group, including the App Service plan and site. It does not remove an existing Azure OpenAI resource if you configured one outside this group. Change the resource-group name in the command if you deployed with a different value, and confirm it contains only demo resources before deleting it.
