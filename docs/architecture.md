# Architecture and review boundaries

## Runtime flow

```text
Fictional inventory / imported JSON / explicit read-only Azure scan
                             ↓
                    FastAPI normalization
                             ↓
Supervisor code: 90 seconds · 6,000 output tokens · 28 model requests
       ┌─────────────────────┼────────────────────┐
       ↓                     ↓                    ↓
 Investigator          Terraform writer        Reviewer
 up to 12 calls         2 selected drafts       up to 4 calls
       └─────────────────────┼────────────────────┘
                             ↓
             Shared typed read-only estate tools
                             ↑
          Copilot: same tools, up to 8 calls/question
                             ↓
            Human review → approved ZIP download
```

In development, Vite serves the React app and proxies `/api` to FastAPI. In Azure, the frontend build is served with the API from one Linux App Service. The app never applies Terraform or changes cloud resources.

## Plain-code supervisor and agent roles

- **Investigator** (`investigator.py`) explores the active inventory instead of consuming a prepared summary. It can call `list_resources`, `get_neighbors`, `impact_of`, `get_findings`, `get_unmapped_resources`, and `get_estate_summary`. It returns workloads, cited risks, and open questions. IDs in workload and risk claims are filtered against the actual inventory; risks without a real resource ID are dropped.
- **Terraform writer** (`terraform_writer.py`) selects at most one Key Vault and one App Service from skipped Azure resources. With the Responses API configured it drafts HCL and sends local validator errors back for up to three retries. Without a model it uses clearly labeled local templates. The validator checks balanced HCL delimiters and required arguments; a passing result is marked `validated` at that limited level. It does not run `terraform validate`, provider schema checks, or plans. Unverified drafts stay outside the importable modules. Every draft is never-applied output.
- **Reviewer** (`agent_orchestrator.py`) checks its recommendations against the same tool registry. Code rejects every recommendation that does not cite at least one exact resource ID from a tool response. If it is based on an inventory finding, the finding ID must also match. A human still approves the package.
- **Copilot** (`estate_copilot.py`) uses the same tools, including a reverse dependency walk for “what breaks if I remove this?” The default local mode uses code-selected tools. Azure OpenAI tool selection and synthesis are opt-in with `GENESIS_COPILOT_USE_AZURE_OPENAI=true`. Its citations must match resource IDs returned by tools in that answer.
- **Architect** (`auth.py`, `/api/clients`) is the human role. Protected deployments bind each run to an authenticated employee and assigned client workspace. The approval checkbox is a demo acknowledgement, not an enterprise separation-of-duties control.
- **Inventory analyst** (`normalize_inventory`, `classify`) normalizes JSON, redacts common secret-shaped keys, infers graph links, and groups resources. `build_findings` checks selected metadata signals only.

The model path uses Azure OpenAI's Responses API, `DefaultAzureCredential`, the `https://ai.azure.com/.default` token scope, and `store=false`. The deployment must support function calling and strict structured outputs. The Overview page's **Check connection** button exercises tool calling and structured output and reports authentication/role, deployment/region, quota/capacity, unsupported feature, and timeout errors. `AZURE_OPENAI_ENDPOINT` and `AZURE_OPENAI_CHAT_DEPLOYMENT` are app settings; the project does not create a model resource or deployment. Review company data-handling requirements before transmitting inventory evidence to the model service.

Each discovery has shared limits of 90 seconds, 6,000 model output tokens, and 28 model requests. Investigator and Reviewer tool-call limits are 12 and 4. Copilot is limited to 45 seconds, 2,800 output tokens, and 8 calls per question. The writer considers two drafts and makes at most four model attempts per draft (one draft plus three repairs). Timeouts or model errors switch to local evidence tools and are visible in the response mode.

## Azure discovery and identity

The Azure scanner uses Azure Resource Graph, which returns indexed resource metadata across one subscription per request. The UI can narrow a scan to one resource group. The adapter follows continuation tokens and caps a run at 1,500 records. Resource Graph is eventually consistent. The scan is read-only and requires Reader at the chosen scope.

`DefaultAzureCredential` is created only after a scan begins. Locally, it can use Azure CLI sign-in. On App Service, it can use the system-assigned managed identity. The Bicep template grants no Reader role. Configure Microsoft Entra authentication and the employee scope map before granting Reader. See [infra/README.md](../infra/README.md).

When Azure OpenAI mode is enabled, the same App Service managed identity (or local signed-in user) needs **Cognitive Services OpenAI User** on the model resource. The endpoint and deployment name are configuration values, not credentials.

## Data handling and state

- Resource results are normalized and common secret-shaped keys are redacted before reaching the browser or model. This is precautionary, not a general secret scanner; do not upload credentials or state files.
- Azure discovery uses Resource Graph read calls only. AWS remains a secondary example using Boto3 describe/list calls.
- The agent tool registry has no cloud write calls, Terraform execution, approval, or package export function.
- Runs, owner/client bindings, and approval acknowledgements are process memory and disappear on restart. Use one App Service instance for this demo.
- The employee-to-scope JSON map is a pilot access control, not durable tenant governance or an isolated client data cell.

## Terraform adoption boundary

The explicit AzureRM generator maps resource groups, virtual networks, subnets, network security groups, public IP addresses, network interfaces, and storage accounts when their required inventory fields are present. The Terraform writer adds selected Key Vault and App Service draft types. Generated block coverage is the share of inventory records with an emitted resource block; it does not measure attribute parity, provider validity, dependency completeness, or safe adoption.

The package is modular by inferred category, not a complete dependency-aware reference rewrite. Import blocks associate remote objects with Terraform addresses but do not prove that generated settings match the live resources. `prevent_destroy` does not prevent proposed updates. Review every file, run Terraform CLI validation, and inspect a plan in a protected state workspace before considering any apply. GENESIS itself does not run Terraform.

## Kyndryl demo estate and measurements

`samples/kyndryl-synthetic-estate.json` contains 72 fictional Azure resources in four workloads, with VMs, SQL, Key Vault, App Service, network topology, missing tags, unusual names, and a public SSH rule. The tenant, customer, subscription, and resource data are invented; they are not a Kyndryl or customer export. `GET /api/demo/baseline` serves the original nine-resource sample.

Run `python scripts/measure_agentic_value.py` (or `.venv/Scripts/python.exe` on Windows) to report both estates' pre-writer and post-writer coverage, Terraform types, drafts, tool calls, citation validity, and runtime. Current offline demo figures are in the root README. Machine runtime is not analyst time saved. A real customer pilot should time comparable manual and assisted workflows and separate human review time from machine processing time.

## Hosting and known limits

App Service uses a paid plan (Basic B1 by default); review current regional price and company credit terms. No Azure model resource, role assignment, live estate, or App Service is created by this repository's local run. In the current workspace Azure CLI is unavailable, so live deployment and the model connection probe still need a signed-in Azure environment. This code has not run `terraform validate`, a cloud plan, or an apply.

Resource Graph only exposes readable indexed metadata, and Azure mappings remain selective. Guardrails do not evaluate all policies, identity paths, effective network routes, or permissions. Durable storage, full tenant-aware authorization, isolated client data cells, audit retention, private networking, and production monitoring remain future hardening work.
