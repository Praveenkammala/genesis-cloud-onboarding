# GENESIS build log and design decisions

This is the project’s implementation record: what was built, in what order, what each part does, and the engineering reasons for the choices. It is intended to help you explain and extend the code. It records observable decisions and their rationale, not private internal chain-of-thought.

## 1. Read the source brief before coding

The supplied PowerPoint was read as an eight-slide product brief. The useful project path is: inspect an inherited cloud estate, infer dependencies, group resources into modules, create Terraform import configuration, run checks, and leave the final decision to an architect.

Two accuracy decisions came directly from the deck:

- The slide 3 statement about reducing onboarding from months to 3–4 days is an intended target. The app presents it as a target and does not claim the demo measured that improvement.
- Slide 5’s diagram describes an ITSM workflow rather than cloud inventory. It was treated as an unrelated template fragment rather than implemented as product behavior.
- Slide 7 contains illustrative values and slide 8 carries the illustrative-data caveat. These figures are not presented as measured coverage or performance.

The full source-specific notes are in [`deck-analysis.md`](deck-analysis.md). The source brief also mentions AWS and Azure, so the first local prototype kept an AWS connector as a working example. Your later instruction made Azure the primary target, so the sample, first-run UI, connector, and main Terraform output were pivoted to Azure; AWS remains available as a secondary connector.

## 2. Establish a runnable local application

The project uses a React/TypeScript frontend and a FastAPI backend. That combination was selected for the prototype because it supports a responsive review UI and a small typed Python API without requiring cloud services or a model deployment just to demonstrate the sample workflow.

The UI is under `frontend/src/`. The API and provider adapters are under `api/`. Vite proxies `/api` requests to FastAPI during development, so the browser can talk to the API without a separate production identity system. `npm run dev` starts both local servers for the hackathon demo.

The sample remains local-first so it can run without Azure spend. The current project also includes `infra/main.bicep` and `infra/deploy.ps1` for a single-site Linux App Service deployment. That path uses a paid B1 plan by default, creates a system-assigned managed identity, and deliberately assigns no cloud Reader role. The operator must enable Entra authentication before granting that identity read access. See [`infra/README.md`](../infra/README.md).

## 3. Use one canonical inventory shape

Cloud APIs return different object shapes. `normalize_inventory` in `api/main.py` converts the supported inputs into a common record with:

- `id`, `type`, `name`, and `provider`;
- `region`, `subscription_id`, and `resource_group` where available;
- `tags` and `properties`;
- normalized graph relationships.

This keeps the graph, classification, review UI, and package builder provider-neutral. The provider-specific generator still sees the original provider-specific properties when it needs to emit HCL.

Azure ARM IDs are case-insensitive in practice, so duplicate detection and graph lookups use case-folded IDs. Subscription and resource-group names can be extracted from an ARM ID if an imported JSON record omits those fields. If the input contains inconsistent subscription IDs, resources outside the selected subscription are excluded from Terraform output rather than silently placed in the wrong provider configuration.

The normalizer also redacts common secret-shaped property keys before scan results go to the browser. This is a precaution, not a general secret scanner. The best input is still inventory metadata that does not contain credentials.

## 4. Make Azure discovery read-only and explicit

### What the user does

1. Install Azure CLI and sign in with `az login`.
2. Obtain Reader access at the intended subscription or resource-group scope.
3. Open **Configure a read-only Azure scan**.
4. Enter the subscription GUID and optionally a resource-group filter.
5. Click **Run read-only scan** to start the query.

### What the code does

`frontend/src/App.tsx` sends the subscription ID and optional resource group to `POST /api/providers/azure/discover`. It never asks for a password, client secret, access token, or key.

`api/azure_provider.py` creates `DefaultAzureCredential` only after the request. It constructs the Azure Resource Graph client, filters the query to the selected subscription, unions normal resources with resource-group containers, sorts by ID, and fetches result pages with the SDK’s `top` and `skip_token` options. It also flattens VNet-embedded subnet metadata when Resource Graph does not return those child IDs as separate rows, while preferring full child rows when they are available. It stops at 1,500 returned records and asks the user to narrow the scope if a larger result is returned. This cap keeps response size and local graph work predictable.

The response is passed through `normalize_inventory` before it reaches the browser. That both produces the canonical shape and applies secret-key redaction. API errors distinguish common sign-in and permission problems so the next action is visible.

### Why this connector

Resource Graph is a read-only inventory query service that lets the app discover many resource types without building a separate list call for every Azure product. The SDK uses the standard Azure credential chain, so local Azure CLI sign-in can be reused without placing secrets into the code or browser. Reader is the intended least-privilege role for this inventory view; an administrator may need to grant it at subscription or resource-group scope.

Official references: [Azure Python SDK authorization](https://learn.microsoft.com/en-us/azure/developer/python/sdk/authorization/overview), [Resource Graph overview and access](https://learn.microsoft.com/en-us/azure/governance/resource-graph/overview), [Resource Graph query API](https://learn.microsoft.com/en-us/rest/api/azureresourcegraph/resourcegraph/resources/resources?view=rest-azureresourcegraph-resourcegraph-2024-04-01), [Python SDK overview](https://learn.microsoft.com/en-us/python/api/overview/azure/resource-graph?view=azure-python).

Resource Graph is indexed rather than strongly consistent, so a newly created or changed resource can take time to show up. Treat the returned inventory as a discovery snapshot, not a transactional view of the subscription.

## 5. Normalize relationships and group resources

The normalizer first adds explicit `relationships` (or `edges`) supplied by an import. It then looks for known references. The AWS path understands fields such as VPC, subnet, and security-group IDs. The Azure path walks property objects for ARM `id` references and infers parent-child relationships from ARM paths when both endpoints are present in the inventory.

Relationships are only added when both resources are present. This avoids drawing a false edge to an object that was outside the scan scope. Unresolved user-supplied relationships are reported for review.

`classify` groups resources into five named areas: Network, Application, Data, Identity, and Supporting. The checks use resource type/name text rather than a model so a user can reproduce the same output. The classification is a suggested organization, not a claim about the resource’s true business function.

## 6. Generate a selective AzureRM package

`api/azure_terraform.py` is a deliberately explicit mapping table plus one HCL builder per supported Azure type. Current mappings are:

| Azure resource type | Terraform type | Notes |
| --- | --- | --- |
| Resource group | `azurerm_resource_group` | Uses group name and location |
| Virtual network | `azurerm_virtual_network` | Requires resource group, location, and address space |
| VNet subnet | `azurerm_subnet` | Requires parent VNet name and address prefixes; advanced association/delegation details are skipped |
| Network security group | `azurerm_network_security_group` | Emits nested rules only when required rule fields are present |
| Public IP address | `azurerm_public_ip` | Requires supported allocation method, location, and resource group |
| Network interface | `azurerm_network_interface` | Emits available IP configuration; NIC-level NSG association needs a separate mapping |
| Storage account | `azurerm_storage_account` | Derives tier/replication from SKU and emits selected access/TLS properties |

The synthetic virtual machine is not generated. A Terraform VM block commonly requires additional configuration that is not safe to invent from this sample (for example, image/disk details and OS credential handling). It stays visible in the inventory and `skipped-resources.json` with a reason. This is preferable to producing plausible-looking but incomplete IaC.

The generated package has a root `main.tf`, provider/version config, example variables, one module folder per resource category, import blocks, an inventory manifest, graph JSON, audit report, skipped-resource report, and README. Import blocks point at the generated `azurerm_*` resource address and preserve the original ARM ID as the import ID.

The Azure provider constraint is `>= 5.5, < 6.0`, and the generated config asks for `azure_subscription_id`. The 5.5 floor is required for the storage account `public_network_access` setting emitted by this generator; 5.5 release notes announce that field. The major-version upper bound reduces the chance a future provider breaking change silently alters the package. Confirm the provider version in the target environment and commit its dependency lock file there. References: [AzureRM provider documentation](https://registry.terraform.io/providers/hashicorp/azurerm/latest/docs/index), [provider 5.5 release notes](https://github.com/hashicorp/terraform-provider-azurerm/releases).

### Why Terraform import code stops at generation

The app does not have permission to modify cloud resources and does not need that permission for the hackathon demo. It prepares a review artifact only. It does not run `terraform import`, `terraform plan`, or `terraform apply`. A package can omit provider-specific settings; after importing, Terraform may still propose changes. `prevent_destroy` does not suppress updates. The architect must inspect the source inventory, generated HCL, validation output, and plan before any apply.

## 7. Keep AWS usable as a secondary path

The AWS path was kept because the brief discusses AWS as well as Azure and the existing prototype already had a useful Boto3 scanner. `GET /api/demo/aws` supplies its fictional sample, and `POST /api/providers/aws/discover` uses the local credential chain or a named AWS profile with describe/list calls. The provider tabs put Azure first. The package chooses AWS, Azure, or both providers based on the resources for which Terraform blocks were actually generated.

Retaining AWS avoids throwing away the prototype while making Azure the first-run and primary hackathon workflow. AWS resource-region checks remain provider-specific; Azure resources can be spread across multiple regions in one subscription.

## 8. Add review findings without overstating them

`build_findings` recognizes selected inventory signals. For Azure it flags inbound NSG allow rules from public source ranges and reports storage settings for blob public access and older TLS versions. For AWS it retains selected public access, database, and S3 checks. Partial Terraform mapping is itself a finding so unsupported resources are not hidden by a high mapping score.

These are static rules over fields the inventory happened to contain. They are not a full Azure Policy evaluation, not compliance certification, and not proof of safety. Missing fields should be read as “not checked,” not “secure.”

## 9. Add the human review and export gate

An analysis run is stored in the FastAPI process memory. The UI lets the architect inspect resources, graph, generated file text, findings, and skipped records. Only a reviewed run can be downloaded as a ZIP. Restarting the API loses the run and its approval; this gate exists for the local demonstration, not enterprise audit requirements.

No remote Git push, Terraform state upload, or cloud apply is performed. This keeps the generated output under the user’s control.

## 10. Cost and credit decisions

The user reports that the company hackathon account has $250 in Microsoft credits. The exact event terms are not included in the project files, so verify expiry, eligible products, and any usage restrictions in the account before deploying.

No Azure infrastructure has been provisioned and no credits have been spent in this workspace. The deployment script now prepares an App Service, but it has not been run because Azure CLI and a signed-in subscription are not available here. The local sample uses no Azure resources. Resource Graph is queried only after an explicit scan action. Check regional pricing and hackathon credit terms before deploying; an Azure budget alert is not a hard spending cap. [Microsoft budget guidance](https://learn.microsoft.com/en-us/azure/cost-management-billing/costs/tutorial-acm-create-budgets).

## 11. Local setup and daily use

From the project root in PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r api\requirements.txt
npm ci
npm run dev
```

For a local Azure scan, in that Windows user session run `az login`, then use the Azure tab in the app. If the scan fails:

- Authentication message: run `az login` again in the same user session that starts the API.
- Authorization message: ask an administrator to grant Reader access at the selected scope.
- No results: confirm the subscription ID and access; try a known resource group.
- Too many results: enter a resource group to reduce the query scope.
- Terraform skipped a resource: read `skipped-resources.json`; the mapping may need more inventory fields or a reviewed generator extension.

The full local verification commands are in the project `README.md`. They type-check/build the frontend and compile Python sources. Terraform CLI validation and live Azure scans require tools/account access beyond those local checks.

## 12. Current verified scope and remaining work

The current build adds a bounded evidence-tool review agent, optional Azure OpenAI Responses API tool calling with a deterministic fallback, a visible tool trace and action list, an analysis runtime metric, and a deployment path to Azure App Service. The App Service uses managed identity and receives no Reader permission from Bicep. The generated package includes `agent-review.json`. The Azure sample and AWS secondary sample remain available.

The frontend type check and production build passed, Python source compilation passed, and local sample API flows were smoke-checked. Across two runs, the fictional Azure sample produced 9 resources, 15 relationships, 8 Terraform blocks (89% block coverage), 2 findings, 1 skipped mapping, and analysis runtimes of 0.001–0.005 seconds. A secondary AWS sample run emitted 12 of 12 blocks. Not verified in this environment: a real Azure sign-in, live subscription discovery, App Service deployment, actual role assignment, Azure OpenAI model response, `terraform validate`, or a cloud plan. Azure CLI is not installed and no company subscription was signed in, so no claim is made that the deployed resource path has been exercised against your hackathon account.

## 13. Agentic estate exploration revision

The project now has a plain-code supervisor and shared typed read-only tools for the Investigator, Reviewer, and Copilot. The Investigator explores resources, neighbors, reverse impact, findings, and unmapped types; the Reviewer drops recommendations without a real resource ID; and Copilot uses the same tools for dependency questions. The Terraform writer drafts Key Vault and App Service blocks with up to three repair attempts and labels results validated or unverified after local syntax and required-argument checks. AI output is never applied.

The default demo is now a 72-resource fictional four-workload Azure estate; the original nine-resource inventory remains available as the comparison. `scripts/measure_agentic_value.py` reports 39% to 42% resource-block coverage and six to eight emitted Terraform types on the synthetic estate; the original sample remains 89% and seven types. Both estates had all reviewer citations resolve to inventory resource/finding IDs in the offline benchmark. The frontend type check, production build, Python compilation, local API route smoke flow, and requested benchmark passed. A deletion-impact question traced the NSG to its NIC and VM through two tool calls.

Live deployment and Azure OpenAI verification remain untested: Azure CLI is not installed and the workspace has no signed-in subscription or configured model endpoint/deployment. The Overview now provides a connection probe that exercises Entra authentication, function calling, and structured output once those settings and the model role are in place. Terraform CLI is also unavailable here, so `terraform validate` and plan safety remain unverified.
