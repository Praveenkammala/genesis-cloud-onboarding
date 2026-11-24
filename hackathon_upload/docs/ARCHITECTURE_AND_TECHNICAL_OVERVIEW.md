# GENESIS — Azure Cloud Blueprint Studio
## Architecture and Technical Overview

**Hackathon Submission Document**
**Team:** Kyndryl
**Category:** Cloud Operations / AI-Assisted Infrastructure Automation

---

## Executive Summary

GENESIS is a read-only cloud estate analysis tool that helps managed-services and cloud platform teams understand an inherited Azure (or AWS) cloud environment. It normalizes a cloud inventory, infers a dependency graph, runs a bounded AI-assisted investigation, generates policy findings, produces a draft Terraform package, and gates every output behind a human review checkpoint.

The project targets a known Kyndryl business problem: onboarding a client's undocumented cloud estate currently requires manual inventory collection and architecture review that can extend over weeks. GENESIS provides a structured, evidence-grounded starting point for that work. It does not prove savings; it demonstrates the assisted workflow that a timed pilot could evaluate.

---

## Problem Being Addressed

Managed-services onboarding of an inherited cloud estate involves:

- **No documentation**: Resources are manually built with no IaC baseline.
- **Unknown dependencies**: Blast-radius of a change is unclear without mapping.
- **Missing ownership metadata**: Resources lack tags, owners, and workload assignments.
- **Slow configuration review**: Policy and security review is performed manually against exported CSVs.
- **No IaC starting point**: Teams must write Terraform from scratch before they can apply lifecycle controls.

The source brief for this project describes a scenario target of reducing onboarding time from 2–3 months to 3–4 days. Using 20 working days per month, that arithmetic implies a 90–95% reduction (36–57 working days released per engagement). **This is a goal assumption from the brief, not a measured GENESIS result.** The prototype demonstrates the assisted workflow; a timed pilot on a representative approved estate is the next credible measurement step.

---

## Solution Overview

GENESIS provides a local or App Service–hosted web application that:

1. Accepts a cloud estate via a **fictional sample inventory**, an **uploaded JSON inventory**, or a **live read-only Azure Resource Graph scan**.
2. Normalizes resources and infers dependency relationships from ARM ID structures and property references.
3. Runs a **bounded Investigator agent** (up to 12 tool calls) that groups resources into workloads, identifies risks, and raises open questions — using code-selected read-only tools with an optional Azure OpenAI tool-calling path.
4. Generates **policy/guardrail findings** from metadata signals (open NSG rules, missing tags, public storage, weak TLS, exposed SQL endpoints).
5. Runs a **Terraform writer** that selects up to one Key Vault and one App Service from the skipped-resource list and attempts to draft HCL with local static validation.
6. Runs a **Reviewer agent** (up to 4 tool calls) whose recommendations are filtered to cite only real resource and finding IDs from the inventory.
7. Presents an **evidence-cited Copilot** that answers questions about the active run using the same read-only tools.
8. Gates the final Terraform ZIP package behind a **human review acknowledgement checkpoint**.

**GENESIS never applies Terraform, never writes to Azure, and never creates or deletes cloud resources.**

---

## Architecture

### Component Overview

| Layer | Component | Implementation |
|---|---|---|
| Frontend | React 18 + TypeScript single-page app | `frontend/src/App.tsx` (Vite build) |
| API | FastAPI (Python) REST API | `api/main.py` |
| Investigator | Bounded tool-using agent | `api/investigator.py` |
| Terraform writer | Bounded HCL generator with static validation | `api/terraform_writer.py` |
| Reviewer | Evidence-citation-enforced agent | `api/agent_orchestrator.py` |
| Copilot | Evidence-cited Q&A agent | `api/estate_copilot.py` |
| AI runtime | Azure OpenAI Responses API (optional) | `api/agentic_runtime.py` |
| Estate tools | Shared read-only inventory tool registry | `api/agentic_tools.py` |
| Azure connector | Azure Resource Graph (read-only) | `api/azure_provider.py` |
| AWS connector | Boto3 describe/list (secondary, read-only) | `api/sample_inventory.py` |
| Auth | App Service Easy Auth + scope map | `api/auth.py` |
| Infra | Azure App Service (Bicep + PowerShell) | `infra/main.bicep`, `infra/deploy.ps1` |

### Shared Resource Bounds (per discovery run)

| Limit | Value |
|---|---|
| Total wall time | 90 seconds |
| Total model output tokens | 6,000 |
| Total model requests | 28 |
| Investigator tool calls | 12 |
| Reviewer tool calls | 4 |
| Copilot tool calls per question | 8 |
| Terraform writer drafts | 2 (up to 3 repair retries each) |
| Max resources per run | 1,500 |

---

## End-to-End Workflow

```
1. User selects inventory source
   ├── Fictional 72-resource Azure sample (GET /api/demo)
   ├── Fictional 9-resource baseline (GET /api/demo/baseline)
   ├── Fictional AWS sample (GET /api/demo/aws)
   ├── Uploaded JSON inventory (POST /api/analyze)
   └── Live Azure Resource Graph scan (POST /api/providers/azure/discover)
         └── requires: az login + Reader role at target scope

2. POST /api/analyze
   ├── normalize_inventory()      — standardize fields, redact secrets, infer IDs
   ├── build_relationships()      — ARM ID hierarchy + property reference walks
   ├── classify()                 — assign each resource to network/app/data/identity/supporting
   ├── terraform_for_provider()   — emit HCL for supported types; populate skipped list
   ├── build_findings()           — metadata signal checks (NSG rules, tags, TLS, public access)
   ├── run_investigator()         — workload grouping, risk identification, open questions
   ├── write_skipped_resources()  — attempt Key Vault / App Service HCL from skipped list
   ├── run_agentic_review()       — evidence-citation-validated recommendations
   └── Assemble ZIP package (held in-memory, not written to disk)

3. Human review
   ├── User inspects: inventory, dependency graph, guardrails, Copilot, IaC package
   ├── POST /api/runs/{run_id}/approve  — record acknowledgement
   └── GET /api/runs/{run_id}/package  — download ZIP (only after approval)

4. Copilot (independent, any time after discovery)
   └── POST /api/runs/{run_id}/ask     — bounded, cited Q&A against active run
```

---

## Azure Integration

### Azure Resource Graph (Primary Discovery)

- **Connector**: `api/azure_provider.py` using `azure-mgmt-resourcegraph`
- **Credential**: `DefaultAzureCredential` — Azure CLI locally; system-assigned managed identity on App Service
- **Scope**: One subscription per run; optional resource-group filter
- **Pagination**: Follows continuation tokens; capped at 1,500 resources
- **Consistency**: Resource Graph is an indexed snapshot and may lag recent changes
- **Permissions required**: Azure RBAC **Reader** at the chosen subscription or resource group scope
- **Write operations**: None. The connector calls only read APIs.

### Azure OpenAI (Optional AI Path)

- **API**: Azure OpenAI Responses API with function calling and strict structured output
- **Credential**: Same `DefaultAzureCredential` chain; scope `https://ai.azure.com/.default`
- **Required role**: **Cognitive Services OpenAI User** on the model resource
- **Configuration**: `AZURE_OPENAI_ENDPOINT` and `AZURE_OPENAI_CHAT_DEPLOYMENT` environment variables
- **store=false**: Requests do not persist conversation state on the model service
- **Fallback**: If authentication, quota, region, feature support, or timeout fails, the system switches automatically to deterministic local tool agents; the UI shows the fallback mode
- **Probe**: The Overview page **Check connection** button makes a low-token Responses API probe and classifies failure type

### Azure App Service (Optional Hosting)

- **Template**: `infra/main.bicep` — Linux App Service, Python 3.12, system-assigned managed identity
- **Default SKU**: Basic B1 (paid plan; review regional pricing before deploying)
- **Authentication**: Microsoft Entra Easy Auth must be manually configured before granting any cloud read access
- **No default Reader role**: The Bicep template does not assign Reader access; it must be granted explicitly after authentication is configured
- **Employee scope map**: `GENESIS_USER_SCOPES_JSON` — maps Entra object IDs to allowed Azure subscription or resource-group scopes

---

## AI / Copilot Capabilities

### Investigator (`api/investigator.py`)

- Calls up to 12 read-only tool functions from the shared `EstateTools` registry
- Available tools: `list_resources`, `get_neighbors`, `impact_of`, `get_findings`, `get_unmapped_resources`, `get_estate_summary`
- **Azure OpenAI path**: model selects and sequences tool calls via Responses API; output validated against strict JSON schema; resource and finding IDs filtered against actual inventory before returning
- **Deterministic fallback**: code walks resources in batches, queries findings, infers workload groups from tags/resource groups — same tool registry, no model
- Output: workload groupings, evidence-cited risks, open questions

### Terraform Writer (`api/terraform_writer.py`)

- Selects at most one Key Vault and one App Service from the skipped-resource list
- With Azure OpenAI: drafts HCL and sends local validator errors back for up to 3 repair retries
- Without Azure OpenAI: uses clearly labeled local templates
- Local static validation: checks balanced HCL delimiters and required argument presence
- Passing drafts are marked `validated` (at that limited static-check level only); **does not run `terraform validate`, provider schema checks, or plans**

### Reviewer (`api/agent_orchestrator.py`)

- Checks every recommendation against the same tool registry
- **Enforced citation rule**: every recommendation that does not cite at least one exact resource ID from a tool response is dropped; if based on a finding, the finding ID must also match
- Up to 4 tool calls; same Azure OpenAI / deterministic fallback pattern

### Copilot (`api/estate_copilot.py`)

- Same read-only tool registry as Investigator
- Local evidence mode is default even when Azure OpenAI is configured
- Azure OpenAI synthesis opt-in: `GENESIS_COPILOT_USE_AZURE_OPENAI=true`
- Max 8 tool calls, 45-second wall time, 2,800 output tokens per question
- Supports question types: estate summary, findings/risks, Terraform mapping gaps, deletion-impact graph walk, resource topology, resource detail lookup
- UI checks every model citation against resource IDs returned by tools in that answer

---

## Investigator Workflow (Detail)

The Investigator is the central agentic component:

```
run_investigator(inventory, findings, budget, skipped)
  │
  ├── If Azure OpenAI is configured:
  │     response_tool_agent(
  │       system_prompt: "Explore inventory with read-only tools; cite exact IDs"
  │       user_prompt:   "{N} resources, {M} relationships, {F} findings — explore before reporting"
  │       tools:         TOOL_SCHEMAS (6 read-only functions)
  │       output_schema: genesis_investigation (strict JSON schema)
  │       budget:        shared ModelBudget
  │       max_tool_calls: 12
  │     )
  │     _clean(): filter workload/risk resource IDs against actual inventory
  │     Return: workloads, risks, open_questions, tool_call_trace, mode=azure_openai_tool_calling
  │
  └── Deterministic fallback (always used without model; also fallback on model error):
        list_resources() in batches of 25
        get_findings()
        get_neighbors() on first NSG found
        _local_workloads(): group by tag[application/workload] or resource_group
        Return: workloads, risks from findings, open_questions, mode=deterministic_tool_fallback
```

---

## Dependency Analysis

### Relationship Inference

The normalizer builds relationships by:

1. **Explicit relationships**: from the inventory `relationships` / `edges` array
2. **Property reference walks**: `vpc_id`, `subnet_id`, `security_group_ids`, `subnet_ids`, `depends_on` for AWS; ARM `id` fields in nested property objects for Azure
3. **ARM ID hierarchy**: parent ARM path segments (resource group → virtual network → subnet) inferred from the resource ID string
4. **Relation labels**: `in_resource_group`, `in_virtual_network`, `uses_subnet`, `uses_network_security_group`, `uses_public_ip`, `attached_to`, `child_resource`, `references`

Unresolved user-supplied relationship references are reported as a medium-severity finding.

### Demo Estate Dependency Numbers

The 72-resource fictional Azure sample (`samples/kyndryl-synthetic-estate.json`) produces approximately **124 inferred dependency relationships** in the dependency graph view. These numbers are from the fictional demo estate, not from a real Kyndryl or customer estate.

---

## Guardrails / Policy Review

The `build_findings()` function in `api/main.py` checks the following metadata signals from the inventory:

| Check | Severity | Resource Type |
|---|---|---|
| Missing owner tag | Low | All resources |
| Public inbound NSG rule (port 22/3389/\*) | Critical | `Microsoft.Network/networkSecurityGroups` |
| Public inbound NSG rule (other ports) | High | `Microsoft.Network/networkSecurityGroups` |
| Storage account allows public blob access | High | `Microsoft.Storage/storageAccounts` |
| Storage account minimum TLS below 1.2 | High | `Microsoft.Storage/storageAccounts` |
| Key Vault network default action is Allow | High | `Microsoft.KeyVault/vaults` |
| SQL server public network access enabled | High | `Microsoft.Sql/servers` |
| App Service HTTPS-only disabled or TLS < 1.2 | High | `Microsoft.Web/sites` |
| AWS public inbound SG rule (port 22/3389/-1) | Critical/High | `aws_security_group` |
| AWS database publicly accessible | Critical | `aws_db_instance` |
| AWS database storage encryption off | High | `aws_db_instance` |
| AWS S3 public access not blocked | Critical | `aws_s3_bucket` |
| Unresolved relationship references | Medium | Inventory-level |
| Partial Terraform coverage | Medium | IaC package |

**Important**: these checks evaluate only fields present in the supplied inventory. They do not evaluate effective network routes, identity paths, all Azure Policy assignments, or permissions. They are a starting point for review, not a compliance determination.

---

## Terraform / IaC Generation

### Supported Azure Types (Base Generator — `api/azure_terraform.py`)

| Azure Resource Type | Terraform Resource |
|---|---|
| `Microsoft.Resources/resourceGroups` | `azurerm_resource_group` |
| `Microsoft.Network/virtualNetworks` | `azurerm_virtual_network` |
| `Microsoft.Network/virtualNetworks/subnets` | `azurerm_subnet` |
| `Microsoft.Network/networkSecurityGroups` | `azurerm_network_security_group` |
| `Microsoft.Network/publicIPAddresses` | `azurerm_public_ip` |
| `Microsoft.Network/networkInterfaces` | `azurerm_network_interface` |
| `Microsoft.Storage/storageAccounts` | `azurerm_storage_account` |

### Terraform Writer Additions (bounded — `api/terraform_writer.py`)

The writer selects at most **one Key Vault** and **one App Service** from the skipped list and attempts to draft HCL with static validation and up to 3 repair retries.

### Package Structure

```
<run-id>.zip
  ├── versions.tf              — provider requirements (azurerm >= 5.5, < 6.0)
  ├── main.tf                  — module blocks
  ├── imports.tf               — import blocks (existing resources → Terraform addresses)
  ├── terraform.tfvars.example — variable examples
  ├── modules/
  │   ├── network/main.tf
  │   ├── application/main.tf
  │   ├── data/main.tf
  │   ├── identity/main.tf
  │   └── supporting/main.tf
  ├── skipped-resources.json   — resources not emitted, with reasons
  └── audit.json               — run metadata, findings, review output
```

All generated files include the header: `# Generated from the supplied inventory. Review every field before adoption.`

Generated import blocks associate inventory IDs with Terraform addresses but **do not prove that generated settings match the live resource state**. `prevent_destroy = true` is set on all blocks; a later `terraform plan` may still propose updates. GENESIS does not run `terraform validate`, plan, or apply.

### Demo Coverage Numbers (72-resource fictional estate)

| Metric | Value |
|---|---|
| Total resources | 72 |
| Resources with Terraform blocks (pre-writer) | ~30 |
| Terraform coverage (pre-writer) | ~39% |
| Resources with Terraform blocks (post-writer) | ~30 |
| Terraform coverage (post-writer) | ~42% |
| Distinct Terraform types | 6–8 |
| Resources needing manual mapping | ~42 |

These numbers are measurements from the offline benchmark script (`scripts/measure_agentic_value.py`) against the fictional synthetic estate. They do not represent a customer environment.

---

## Human Review and Approval Model

The approval flow is a **demo acknowledgement gate**, not an enterprise separation-of-duties control:

1. Discovery and analysis run; results are held in API process memory (lost on restart)
2. User inspects inventory, dependency graph, guardrails, Copilot answers, and IaC package
3. User checks the acknowledgement checkbox on the IaC Package page (`POST /api/runs/{run_id}/approve`)
4. Only after approval does the download link activate (`GET /api/runs/{run_id}/package`)
5. No role in the system can approve on behalf of another user
6. No role can apply Terraform or change cloud resources

In App Service protected mode, runs are bound to the creating employee's Entra identity and client workspace. A run, its Q&A history, approval, and package export are scoped to that employee only.

---

## Read-Only / Security Boundaries

| Boundary | Implementation |
|---|---|
| Cloud scanning | Read-only; Azure Resource Graph `query` calls and AWS Boto3 `describe`/`list` calls only |
| Agent tool registry | No write functions, no Terraform execution, no approval or export functions |
| Secret redaction | Common secret-shaped inventory keys redacted before reaching browser or model |
| Azure credential | Stays in CLI / App Service identity; browser never receives credentials |
| Model requests | `store=false`; bounded context; tool calls restricted to allow-listed functions |
| Run data | Process memory only; lost on restart; not persisted to external storage |
| Auth mode | Local (no auth, fictional data only) or App Service Easy Auth (Entra + employee scope map) |

---

## Local Demo Architecture

```
Browser (http://127.0.0.1:5173)
  │
  └── Vite dev server (proxies /api → FastAPI)
        │
        └── FastAPI (http://127.0.0.1:8000)
              ├── In-memory run store (RUNS dict)
              ├── Deterministic tool agents (always available)
              └── [Optional] Azure OpenAI Responses API
                    └── Requires AZURE_OPENAI_ENDPOINT + AZURE_OPENAI_CHAT_DEPLOYMENT
```

No Azure resources are created by the local run. No Azure credentials are required unless the user opts to run a live Azure Resource Graph scan.

---

## Optional Azure OpenAI Architecture

```
Browser → Vite → FastAPI
                   │
                   ├── run_investigator()
                   │     └── response_tool_agent()
                   │           └── Azure OpenAI Responses API
                   │                 ├── Tool call → EstateTools.execute() [local, read-only]
                   │                 ├── Tool call → EstateTools.execute() [local, read-only]
                   │                 └── ... (up to 12 calls)
                   │
                   ├── run_agentic_review()
                   │     └── response_tool_agent() [up to 4 calls]
                   │
                   └── answer_estate_question() [Copilot, opt-in only]
                         └── response_tool_agent() [up to 8 calls per question]
```

The model service receives: normalized inventory evidence, tool call results, and the bounded system prompt. It does not receive raw credentials or state files. Review your organization's data-handling requirements before enabling the Azure OpenAI path.

---

## Deployment Architecture (Supported by Repository)

The repository includes `infra/main.bicep` and `infra/deploy.ps1` to deploy GENESIS as a single Linux App Service:

```
deploy.ps1
  ├── npm run build (TypeScript type-check + Vite production build)
  ├── az deployment group create (main.bicep)
  │     └── Creates: App Service Plan (B1), Web App, System-assigned managed identity
  ├── ZIP deploy (API + built frontend)
  └── Polls /api/health until ready
```

**What the deployment does NOT do**:
- Does not assign Reader role to the managed identity
- Does not configure Entra authentication
- Does not create an Azure OpenAI resource
- Does not run Terraform

Deployment requires: Azure CLI, Node.js/npm, an Azure subscription with permission to create the listed resources, PowerShell. Use a dedicated resource group. Review the Basic B1 plan pricing before deploying.

---

## Technology Stack

| Category | Technology | Version Constraint |
|---|---|---|
| Frontend framework | React | ^18.3.1 |
| Frontend language | TypeScript | ^5.7.3 |
| Frontend build | Vite | ^6.0.7 |
| UI icons | lucide-react | ^0.468.0 |
| API framework | FastAPI | >=0.115, <1.0 |
| API server | Uvicorn | >=0.30, <1.0 |
| Azure connector | azure-mgmt-resourcegraph | >=8.0, <9.0 |
| Azure identity | azure-identity | >=1.19, <2.0 |
| AWS connector | boto3 | >=1.35, <2.0 |
| AI client | openai | >=2.0, <3.0 |
| Terraform provider (Azure) | hashicorp/azurerm | >= 5.5, < 6.0 |
| Terraform provider (AWS) | hashicorp/aws | >= 5.0, < 7.0 |
| Terraform minimum version | Terraform CLI | >= 1.5.0 |
| Infra template | Azure Bicep | — |
| Python minimum | Python | 3.10+ |
| Node.js minimum | Node.js | 18+ |

---

## API / Backend / Frontend Structure

### API Routes

| Route | Method | Purpose | Auth required |
|---|---|---|---|
| `/api/health` | GET | Health check and reviewer mode | No |
| `/api/clients` | GET | Client workspaces for current employee | App Service mode |
| `/api/demo` | GET | 72-resource fictional Azure estate | No |
| `/api/demo/baseline` | GET | 9-resource baseline estate | No |
| `/api/demo/aws` | GET | Fictional AWS sample | No |
| `/api/analyze` | POST | Normalize, analyze, orchestrate, generate package | Yes (scope check) |
| `/api/providers/azure/discover` | POST | Live read-only Azure Resource Graph scan | Yes (scope check) |
| `/api/providers/aws/discover` | POST | Live read-only AWS scan | Yes (scope check) |
| `/api/runs/{run_id}/approve` | POST | Record human review acknowledgement | Yes (run owner) |
| `/api/runs/{run_id}/ask` | POST | Bounded Q&A against active run | Yes (run owner) |
| `/api/model/check` | POST | Probe Azure OpenAI connection | Yes |
| `/api/runs/{run_id}/package` | GET | Download approved run as ZIP | Yes (run owner) |

### Frontend Pages (from `frontend/src/App.tsx`)

The React single-page application includes views for: Overview / Discovery, Inventory, Dependency Graph, Investigator / Workloads, Guardrails / Policy Review, Copilot, and IaC Package.

---

## Important Implementation Limits

- **Coverage percentage** measures emitted Terraform resource blocks as a share of inventory records. It does not measure attribute parity, dependency completeness, or safe adoption.
- **Import blocks** associate existing IDs with Terraform addresses; they do not prove that generated settings match the live resource state.
- **`prevent_destroy = true`** is set but does not prevent proposed updates in a later plan.
- **Findings** are based only on fields present in the supplied inventory. They do not evaluate effective network routes, all Azure Policy assignments, permissions, or live connectivity.
- **Citations** in Reviewer and Copilot outputs are filtered against actual resource and finding IDs from the active run, but this is a syntactic check, not a semantic validation of the claim's accuracy.
- **Run data** is in-memory only; lost on API process restart.
- **Local auth mode** has no employee authentication and is intended for fictional sample data only.

---

## Current Limitations

| Area | Limitation |
|---|---|
| Multi-subscription | One Azure subscription per discovery run; no cross-subscription merge |
| Terraform types | Base generator supports 7 Azure types; writer adds Key Vault and App Service as bounded drafts |
| Terraform validation | Static delimiter and required-argument checks only; no `terraform validate`, no plan |
| Findings | Metadata signal checks only; no live Azure Policy, effective permissions, or network route evaluation |
| Run persistence | In-memory only; single App Service instance; lost on restart |
| Auth | Local mode: no auth. App Service mode: pilot-level scope map; not production identity governance |
| AWS | Secondary example connector; not feature-equivalent with Azure path |
| Azure OpenAI | Not created by repository; requires existing deployment; subject to quota and regional availability |

---

## Future Improvements

- Durable run storage with tenant-aware isolation and audit retention
- Multi-subscription and multi-account inventory merge
- Broader AzureRM type coverage (VMs, SQL, AKS, Cosmos DB)
- Terraform CLI `validate` and `plan` integration in a sandboxed environment
- Azure Policy and RBAC effective-permissions evaluation
- Private networking for App Service
- Production rate limiting and monitoring
- Key Vault integration for deployment secrets
- Comparison between successive discovery runs (drift detection)
