# GENESIS — Hackathon Submission Overview

**Solution Title:** GENESIS — Azure Cloud Blueprint Studio
**Submitting Team:** Kyndryl
**Submission Category:** Cloud Operations / AI-Assisted Infrastructure Automation

---

## Problem

Managed-services and cloud platform teams inheriting an Azure estate face a consistent set of obstacles before they can operate it safely:

- Cloud resources are manually built with no Infrastructure-as-Code baseline
- Dependency relationships between resources are undocumented
- Ownership metadata (tags, workload assignments) is incomplete or absent
- Policy and security review must be performed manually against exported CSVs
- Writing Terraform from scratch is time-consuming and error-prone

The source brief for this project describes a scenario target of reducing onboarding time from 2–3 months to 3–4 days. **This target is a goal assumption from the brief, not a measured result of running GENESIS.** A timed pilot on a representative approved estate is the correct next measurement step.

---

## Solution

GENESIS is a read-only cloud estate analysis tool implemented as a local web application (optionally deployable to Azure App Service). It provides:

1. **Estate discovery** — accepts a fictional sample, an uploaded JSON inventory, or a live read-only Azure Resource Graph scan
2. **Dependency graph** — infers relationships from ARM ID structures and property references
3. **AI-assisted investigation** — a bounded agent (up to 12 tool calls) groups resources into workloads, identifies risks, and raises open questions
4. **Policy / guardrail review** — metadata signal checks covering NSG rules, missing tags, public storage, weak TLS, and exposed SQL/Key Vault endpoints
5. **Draft Terraform generation** — produces modular HCL with import blocks; a bounded writer attempts to extend coverage into Key Vault and App Service
6. **Evidence-cited Copilot** — answers questions about the active run using the same read-only inventory tools
7. **Human review gate** — the ZIP package is downloadable only after the user acknowledges review

**GENESIS does not apply Terraform, does not write to Azure, and does not create or delete cloud resources.**

---

## Key Capabilities

| Capability | Implementation | Status |
|---|---|---|
| Fictional demo estate (no Azure credentials required) | 72-resource synthetic JSON inventory | Implemented |
| Azure Resource Graph discovery | `azure_provider.py` + `azure-mgmt-resourcegraph` | Implemented |
| AWS discovery (secondary) | `sample_inventory.py` + boto3 | Implemented |
| Dependency graph inference | ARM ID hierarchy + property reference walk | Implemented |
| Resource classification (5 modules) | Rule-based classifier in `main.py` | Implemented |
| Guardrail / policy findings | Metadata signal checks in `build_findings()` | Implemented |
| Base Terraform generation (7 Azure types) | `azure_terraform.py` | Implemented |
| Bounded Investigator agent | `investigator.py` (12 tool calls max) | Implemented |
| Bounded Reviewer agent | `agent_orchestrator.py` (4 tool calls max) | Implemented |
| Bounded Terraform writer | `terraform_writer.py` (2 drafts, 3 retries each) | Implemented |
| Evidence-cited Copilot | `estate_copilot.py` (8 tool calls max per question) | Implemented |
| Human review gate | Acknowledgement → ZIP download | Implemented |
| Azure OpenAI tool calling | Responses API + `DefaultAzureCredential` | Optional; requires existing deployment |
| Deterministic local fallback | Code-selected tools, no model required | Implemented (always available) |
| App Service deployment | `infra/main.bicep` + `infra/deploy.ps1` | Implemented; not executed in this demo |
| Secret redaction | Common key fragments redacted before browser/model | Implemented |
| Offline benchmark script | `scripts/measure_agentic_value.py` | Implemented |

---

## Implementation Achievements

The following are verified by the repository implementation:

- **Full offline demo** runs with no Azure credentials, no Azure spend, and no model deployment
- **Bounded resource model**: every agent run has hard limits on time (90 sec), tokens (6,000), model requests (28), and tool calls per role
- **Citation enforcement**: the Reviewer drops any recommendation not citing a real resource or finding ID; the Copilot UI validates citations against tool-returned IDs
- **Deterministic fallback**: all three agent roles (Investigator, Reviewer, Copilot) function without Azure OpenAI
- **Modular IaC output**: generated Terraform is split by inferred resource category into named modules
- **Import block generation**: every emitted resource block has a corresponding `import {}` block
- **Secret redaction**: common secret-shaped property keys are removed before inventory reaches the browser or model

---

## Demonstrated Results (Fictional Demo Estate)

The following values are from the fictional 72-resource Azure sample (`samples/kyndryl-synthetic-estate.json`). They are measurements from the demo estate, **not from a real Kyndryl or customer environment**.

| Metric | Value | Source |
|---|---|---|
| Resources in demo estate | 72 | Fictional synthetic inventory |
| Inferred dependency relationships | ~124 | Dependency graph (synthetic estate) |
| Suggested Terraform modules | 5 | (network, application, data, identity, supporting) |
| Terraform block coverage (post-writer) | ~42% | Offline benchmark script |
| Resources needing manual mapping | ~42 | Skipped-resource manifest |
| Review findings | ~21 | Guardrail signal checks |
| Critical findings | 1 | Public inbound NSG rule (fictional estate) |
| Inferred workloads (Investigator) | 8 | Deterministic tool agent |

> [!IMPORTANT]
> These numbers describe the **fictional demo estate**. The tenant, subscription, customer names, and resource data in `kyndryl-synthetic-estate.json` are entirely invented. They are not a Kyndryl or customer export.

---

## Technical Architecture (Summary)

```
Browser (React/TypeScript, Vite)
       ↕ HTTP /api/*
FastAPI (Python)
  ├── normalize_inventory()      — standardize + redact + infer relationships
  ├── build_findings()           — policy/guardrail checks (metadata only)
  ├── terraform_for_provider()   — HCL generation for 7 Azure types
  ├── run_investigator()         — 12-call bounded agent (AI or deterministic)
  ├── write_skipped_resources()  — bounded Terraform writer (KeyVault + AppService)
  ├── run_agentic_review()       — 4-call evidence-citation-enforced reviewer
  └── answer_estate_question()   — 8-call per-question Copilot

Shared read-only tool registry (agentic_tools.py):
  list_resources | get_neighbors | impact_of |
  get_findings | get_unmapped_resources | get_estate_summary
```

---

## Security and Governance

| Control | Implementation |
|---|---|
| Read-only discovery | No write APIs in cloud connector or agent tool registry |
| Credential isolation | Azure credentials never reach the browser |
| Secret redaction | Inventory sanitized before browser or model |
| Human review gate | ZIP download gated behind explicit acknowledgement |
| Agent tool limits | Hard caps on tool calls, tokens, and wall time per role |
| Citation enforcement | Uncited agent recommendations are automatically dropped |
| Scope access control | App Service mode: each employee restricted to assigned client workspaces |
| `store=false` | Model requests do not retain conversation state on Azure OpenAI |
| Run isolation | Each run bound to creating employee (App Service mode) |

---

## AI Capabilities

| Capability | Implementation | Required |
|---|---|---|
| Workload grouping from inventory | Deterministic (tag/resource-group) or Azure OpenAI tool calling | Deterministic always; Azure OpenAI optional |
| Risk identification with citations | Filtered against actual inventory/finding IDs | Both paths |
| Terraform draft repair loop | Azure OpenAI sends errors back for retry; local templates used without model | Azure OpenAI optional |
| Reviewer citation validation | Code enforces resource and finding ID matching | Always enforced |
| Copilot Q&A with tool calls | Local evidence mode default; Azure OpenAI opt-in | Azure OpenAI opt-in |
| Connection probe | `/api/model/check` classifies auth/quota/region/feature errors | Azure OpenAI optional |

---

## Infrastructure Automation

The generated Terraform package:

- Covers 7 Azure resource types in the base generator (resource groups, VNets, subnets, NSGs, public IPs, NICs, storage accounts)
- Extends to Key Vault and App Service via the bounded writer
- Produces modular HCL (5 category modules) with import blocks and provider configuration
- Includes `prevent_destroy = true` on all resource blocks
- **Is never applied by GENESIS**; requires human review, `terraform validate`, and plan inspection

---

## Limitations

| Limitation | Detail |
|---|---|
| Coverage percentage | Counts emitted blocks, not attribute parity or safe adoption |
| Terraform validation | Static checks only; no `terraform validate` or provider plan |
| Findings | Metadata signal checks only; not a compliance determination |
| Run persistence | In-memory only; lost on API restart |
| Multi-subscription | One Azure subscription per discovery run |
| Azure OpenAI | Requires an existing deployment; not created by this repository |
| Auth (local) | No authentication; fictional data only |
| Import blocks | Associate IDs with addresses; do not prove setting accuracy |

---

## Business Value (Stated Goals vs. Demonstrated Capability)

| Claim | Type | Evidence |
|---|---|---|
| Reduces onboarding time 90–95% | **Goal assumption from brief** | Not measured; calculation is from brief's stated 2–3 months → 3–4 days target |
| Provides structured starting point for IaC | **Demonstrated capability** | Generated Terraform package, skipped-resource manifest, audit file |
| Surfaces policy risks from inventory | **Demonstrated capability** | Guardrail findings from metadata signal checks |
| Groups resources into workloads | **Demonstrated capability** | Investigator workload output with cited resource IDs |
| Traces dependency blast radius | **Demonstrated capability** | `impact_of` tool walk shown in Copilot |
| Enables evidence-cited Q&A | **Demonstrated capability** | Copilot answers verified against tool-returned resource IDs |

> [!NOTE]
> To claim time saved, compare the same representative customer estate with a timed current workflow and a timed GENESIS-assisted workflow, reporting human review time and assumptions separately from machine processing time.
