# GENESIS — Azure Cloud Blueprint Studio

[![Live Demo](https://img.shields.io/badge/Live%20Demo-genesis--cloud--onboarding.onrender.com-brightgreen?style=for-the-badge&logo=render)](https://genesis-cloud-onboarding.onrender.com)
[![GitHub](https://img.shields.io/badge/GitHub-Praveenkammala%2Fgenesis--cloud--onboarding-blue?style=for-the-badge&logo=github)](https://github.com/Praveenkammala/genesis-cloud-onboarding)

> 🚀 **[Try the live app → genesis-cloud-onboarding.onrender.com](https://genesis-cloud-onboarding.onrender.com)**

GENESIS helps a managed-services or cloud platform team understand an inherited cloud estate. A bounded Investigator explores inventory, dependency, impact, finding, and mapping tools; Copilot uses those same tools for questions such as “what breaks if I remove this?”; a Reviewer drops recommendations without real resource citations; and a Terraform writer drafts selected skipped Azure types for local validation. This makes GENESIS relevant to Kyndryl’s cloud onboarding and managed-operations work while keeping this demo’s customer estate entirely fictional.

Azure is the primary connector and Terraform target. AWS remains available as a secondary connector. Discovery is read-only; GENESIS never runs `terraform apply` or changes cloud resources.

## Hackathon demo

The project opens with a 72-resource fictional Azure estate across four workloads, so the full demo works without credentials or Azure spend. The original nine-resource Northstar sample remains available as the baseline comparison:

1. Run discovery from the home screen.
2. Inspect the inventory, inferred dependency graph, Investigator tool trace, workload groups, evidence-linked risks, policy findings, and skipped resource list.
3. Ask Copilot questions about the discovered run. Local evidence mode is the default; an administrator can separately opt in to Azure OpenAI synthesis.
4. Review the generated Terraform and audit files.
5. Acknowledge the human review gate to download the ZIP package.

The plain-code supervisor normalizes the estate, runs the Investigator, bounds the Terraform writer, runs the Reviewer, and leaves approval to a human. With Azure OpenAI configured, the Investigator and Reviewer select allow-listed read-only functions through the Responses API; Copilot can do the same when its opt-in is enabled. Without a deployment, deterministic local agents call the same tools. Each discovery run is capped at 90 seconds, 6,000 model output tokens, and 28 model requests; the Investigator is capped at 12 tool calls, the Reviewer at 4, Copilot at 8 per question, and the Terraform writer at two drafts with up to three repair retries each. No role can write to Azure, execute Terraform, or approve the package.

## Run locally

Requirements: Python 3.10+, Node.js 18+, and npm. Azure CLI is only needed for a live Azure scan.

```powershell
cd C:\path\to\genesis
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r api\requirements.txt
.\.venv\Scripts\Activate.ps1
npm ci
npm run dev
```

Activate `.venv` before `npm run dev`; the API command uses the active `python` from `PATH`. Open the Vite URL printed in the terminal, usually `http://127.0.0.1:5173`. The FastAPI API is at `http://127.0.0.1:8000`; interactive API documentation is at `/docs`.

## Connect Azure Resource Graph

For a local scan, sign in using the same Windows account that runs the API and grant that identity Reader at the scope you intend to scan:

```powershell
az login
az account set --subscription <subscription-guid>
```

In GENESIS, choose **Configure a read-only Azure scan**, enter the subscription GUID, optionally add a resource-group filter, and click **Run read-only scan**. The connector uses `DefaultAzureCredential`, so the browser never receives a secret. On Azure App Service the same credential chain can use the app's system-assigned managed identity.

The Resource Graph adapter pages through results and caps a run at 1,500 resources. Azure Resource Graph is an indexed snapshot and may lag a recent change. The connector does not create, update, or delete cloud resources.

## Enable Azure OpenAI tool calling (optional)

The deterministic sample and review agent work without a model. To use an existing Azure OpenAI resource and deployed model, set these environment values in the API process:

```powershell
$env:AZURE_OPENAI_ENDPOINT = 'https://<resource>.openai.azure.com'
$env:AZURE_OPENAI_CHAT_DEPLOYMENT = '<deployment-name>'
npm run dev
```

Sign in with a Microsoft Entra credential that has **Cognitive Services OpenAI User** on that model resource. App Service uses its managed identity; grant that role only if the model mode is enabled. Do not add API keys or credentials to source control. The Investigator runs only during an explicit Analyze/Run action and can make up to 12 read-only tool calls. The Reviewer can make four. If auth, capacity, or structured-output validation fails, local tool agents take over and the UI records the fallback mode.

The configured deployment must support the Responses API's function calling and structured output features. The Overview page has a **Check connection** control that makes a low-token, two-request probe of Entra authentication, tool calling, structured output, and deployment availability; it classifies role/authentication, deployment/region, quota/capacity, feature-support, and timeout failures. Requests set `store=false` and carry bounded tool context in the API process rather than stored response IDs. The model service processes the submitted inventory evidence; review your organization’s Azure data-handling requirements before enabling it. This project does not create a model resource or deployment. Model availability, quotas, region, and token charges depend on the company subscription.

Copilot uses the same read-only inventory tools as the Investigator. It stays in local tool mode by default, even when Azure OpenAI is configured. To allow the model to select those tools and synthesize the results, set `GENESIS_COPILOT_USE_AZURE_OPENAI=true` for the API process (or use the protected deployment option below). The UI shows tool calls and checks every model citation against the resource IDs returned by those calls. Do not enable it until your client data-handling review approves that processing path.

## Deploy the demo to Azure

The single-site deployment hosts the Vite build and FastAPI API together on Linux App Service. Follow [infra/README.md](infra/README.md) for requirements, deployment, Entra authentication, managed-identity access, optional Azure OpenAI setup, and teardown guidance.

```powershell
az login
az account set --subscription <subscription-guid>
.\infra\deploy.ps1 -AppName <globally-unique-name> -SubscriptionId <subscription-guid> -Location eastus
```

The script uses a Basic B1 plan by default, so the deployment can consume the hackathon credits. Confirm the current price in your chosen region and the event's credit terms before running it. It does not grant Reader access automatically. Configure Microsoft Entra sign-in for App Service **before** assigning Reader to its identity; see the deployment guide. The sample app uses no Azure resources before deployment.

## Business value and measurement

The supplied brief describes onboarding shrinking from 2–3 months to 3–4 days. Using 20 working days per month, that is a scenario target of 40–60 days down to 3–4 days: a calculated 90–95% reduction, or 36–57 working days released per onboarding. These are goal assumptions from the brief, not measured GENESIS results.

Two local API smoke runs against the included **fictional** Azure sample processed 9 resources, inferred 15 relationships, emitted 8 Terraform blocks (89% block coverage), returned 2 inventory findings, and marked 1 resource for manual mapping. The recorded API runtime varied from 0.001 to 0.005 seconds; machine runtime is not analyst time saved, and the sample is not a customer estate. A separate AWS sample smoke run emitted 12 of 12 blocks.

Run the included offline benchmark with `.\.venv\Scripts\python.exe scripts\measure_agentic_value.py`. It compares the original nine-resource baseline and the 72-resource fictional Kyndryl managed-services estate, reporting Terraform coverage before and after the writer, distinct Terraform types, writer status, tool calls, citation validity, and run time. Current local results are 89% → 89% on the baseline (7 types) and 39% → 42% on the 72-resource estate (6 → 8 types); all 7/7 and 7/7 reviewer citations checked against real resource/finding IDs. The synthetic run took about 0.017 seconds in the API pipeline and 0.029 seconds wall time on this machine. These numbers measure the offline demo path, not Azure latency or analyst time saved. To claim time saved, compare the same representative customer estate with a timed current workflow and a timed GENESIS-assisted workflow, and report human review time and assumptions.

## Fit for Kyndryl managed services

GENESIS targets the handoff work around onboarding and operating inherited Azure estates: assembling a workload map, tracing likely dependency blast radius, surfacing configuration risks and missing ownership metadata, and preparing a reviewed starting point for IaC migration. That can help Kyndryl cloud and platform teams spend less time collecting inventory evidence and more time validating client-specific architecture and controls. The prototype does not prove savings or replace an architect; the next credible company-impact measure is a read-only pilot on an approved representative estate with engineers timing current and assisted review.

## What the generator supports

AzureRM output is intentionally explicit and selective. The base mappings cover resource groups, virtual networks, subnets, network security groups, public IP addresses, network interfaces, and storage accounts when required fields are present. The bounded writer can add Key Vault and App Service blocks after its local static checks. Unsupported or incomplete types stay in `skipped-resources.json` with a reason. The provider constraint is `>= 5.5, < 6.0`.

Generated import blocks associate existing objects with Terraform addresses. They do not prove that every remote setting is represented. A later Terraform plan may include updates even when `prevent_destroy` is present. Inspect every generated file, validate it with the Terraform CLI, and review a plan in a protected state workspace before considering any apply. GENESIS does not run Terraform validation, plan, or apply.

## Reuse across accounts and providers

Azure discovery currently accepts one subscription per run, with an optional resource-group filter. Run each authorized subscription separately; the prototype does not merge multiple subscriptions into one Terraform provider package. Azure and AWS inputs normalize to the same inventory and relationship shape, while provider-specific adapters and Terraform mappings remain separate. That split is the extension point for adding another account connector or cloud without replacing the review UI and evidence workflow. A production multi-account service would add durable run aggregation and tenant-aware access controls.

## API routes

| Route | Purpose |
| --- | --- |
| `GET /api/health` | Health and configured reviewer mode |
| `GET /api/clients` | Client workspaces assigned to the current employee |
| `GET /api/demo` | 72-resource fictional Azure managed-services inventory |
| `GET /api/demo/baseline` | Original nine-resource estate for measurement |
| `GET /api/demo/aws` | Fictional AWS sample inventory |
| `POST /api/analyze` | Normalize, analyze, orchestrate review, and generate package files |
| `POST /api/providers/azure/discover` | Explicit read-only Azure Resource Graph scan |
| `POST /api/providers/aws/discover` | Explicit read-only AWS scan |
| `POST /api/runs/{run_id}/approve` | Record the local demo review acknowledgement |
| `POST /api/runs/{run_id}/ask` | Ask a bounded, evidence-cited question about the active run |
| `POST /api/model/check` | Probe configured Azure OpenAI authentication, function calls, and structured outputs |
| `GET /api/runs/{run_id}/package` | Download an approved in-memory run as a ZIP |

## Validation commands

```powershell
npm run check
npm run build
python -m py_compile api\main.py api\auth.py api\estate_copilot.py api\agent_orchestrator.py api\azure_provider.py api\azure_terraform.py
```

These local checks do not prove Azure sign-in, Resource Graph access, App Service deployment, Azure OpenAI model availability, Terraform CLI validity, or plan safety. Those require the relevant Azure tenant/subscription and a configured model deployment.

## Data and operational boundaries

- Cloud scanning begins only after the user clicks the scan action. Resource Graph calls are read-only.
- Azure credentials remain in the local Azure CLI or App Service identity; the browser does not receive them.
- Common secret-shaped inventory keys are redacted, but this is not a general-purpose secret scanner. Do not upload credentials or state files.
- A model-enabled review sends a minimal run summary first. The model can request only the allow-listed local evidence tools; it cannot execute Azure commands or modify the package.
- Run results and approval acknowledgements are process memory and are lost on restart. The Azure demo is intended for one App Service instance. It is not a production multi-user audit service.
- Local mode has no employee authentication and is for fictional sample data only. The App Service template sets `GENESIS_AUTH_MODE=easy_auth`; stateful API actions fail closed unless App Service Authentication is enabled, the company tenant is pinned, and the employee-to-cloud-scope map is configured. Runs, Q&A, approval, and package export are bound to the creating employee.
- Protected imported inventories are checked against each employee's allowed Azure subscription IDs or AWS account IDs. The environment-variable access map is a pilot control, not a durable tenant registry or replacement for a production authorization database and isolated client cells.
- The App Service deployment has no cloud Reader permission by default. Configure site authentication before assigning that permission.
- AWS discovery is a secondary example and uses the local Boto3 credential chain. AWS credentials are never collected in the browser.

## Project map and detailed build guide

The implementation and every file's role are documented in [docs/FROM-SCRATCH-IMPLEMENTATION-GUIDE.md](docs/FROM-SCRATCH-IMPLEMENTATION-GUIDE.md). The supplied brief analysis is in [docs/deck-analysis.md](docs/deck-analysis.md), the architecture and limitations in [docs/architecture.md](docs/architecture.md), and the import JSON contract in [docs/inventory-format.md](docs/inventory-format.md).

For the CloudLabs hackathon environment, use [docs/CLOUDLABS-DEMO-RUNBOOK.md](docs/CLOUDLABS-DEMO-RUNBOOK.md) for the low-cost local demo, optional read-only Azure scan, GitHub setup, and hosting cost boundaries.
