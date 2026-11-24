# GENESIS: complete implementation guide

This guide explains how GENESIS is assembled from a blank project, what each maintained file is for, how a demo run moves through the code, and how the Azure path works. It is written for a hackathon walkthrough and for the next developer who needs to change the prototype.

> Current implementation note: this guide records the earlier prototype and some sections below predate the multi-tool Investigator, Reviewer citation gate, shared Copilot tools, Terraform repair loop, and 72-resource estate. For the current code and limits, use [architecture.md](architecture.md) and the root [README](../README.md) as the source of truth.

## 1. What we are building

GENESIS is a cloud-estate onboarding assistant. A managed-services team receives an Azure or AWS environment whose original design is unclear. GENESIS reads a read-only inventory, infers resource links, groups resources into suggested areas, checks a small set of exposed security signals, maps the resources it knows to Terraform, and creates an import package for a cloud architect to review.

The supplied presentation is the product brief. Its useful cloud workflow is on slides 2–4 and 6. Slide 5 is an unrelated ITSM diagram. The “2–3 months to 3–4 days” figures are a target from the brief, not a result measured by this prototype. The app preserves that distinction.

The demo is deliberately useful before an Azure account is configured: it starts with fictional sample data and runs the complete workflow locally. Azure is the primary real-cloud connector and deployment environment. AWS is retained as an optional secondary connector.

## 2. Build it from an empty folder

The project uses React and TypeScript for the browser interface, Vite for development and frontend builds, and FastAPI for the Python API. Azure’s Python SDK provides Resource Graph discovery and identity. The AzureRM Terraform provider is the target for Azure import files.

### Step 1: create the browser application

Create a private npm project with React, React DOM, TypeScript, Vite, the React Vite plugin, and Lucide icons. `package.json` defines the developer commands. `package-lock.json` freezes the exact npm dependency tree so another machine gets the same compatible package versions. `tsconfig.json` enables strict TypeScript checks. `vite.config.ts` starts the browser app and forwards `/api` calls to the local FastAPI server. `index.html` is the Vite entry document.

The UI implementation lives in `frontend/src/`. `main.tsx` finds the root HTML element and renders the React app. `App.tsx` owns the client-workspace selector, views, API calls, state, resource graph, findings, evidence-cited Copilot, review gate, and package preview. `styles.css` owns layout, colors, typography, responsive behavior, and component states.

### Step 2: create the API and a single inventory contract

Create a Python virtual environment and install `api/requirements.txt`. FastAPI handles HTTP, Uvicorn runs the app, Azure Identity supplies Entra credentials, Azure Resource Graph reads inventory, Boto3 keeps the secondary AWS connector usable, and the OpenAI SDK is only used if optional Azure OpenAI settings are present.

The central contract is a provider-neutral JSON object with environment metadata, a `resources` array, and optional `relationships`. Each resource has an ID, provider resource type, name, region, tags, and properties. `api/main.py` normalizes Azure Resource Graph, AWS SDK, sample, and imported JSON data into that shape. All later analysis operates on the normalized records.

### Step 3: add the reviewable analysis path

The API normalizes and redacts resource properties, infers relationships, classifies each resource into one suggested module, produces supported Terraform blocks, creates skipped-resource reasons, and evaluates inventory-based findings. The mapping is explicit: when a resource type or required properties are not supported, GENESIS leaves it visible instead of pretending it was configured.

### Step 4: add the agent workflow

The first five specialist stages are Explorer, Architect, Strategist, Coder, and Validator. They run predictable local analysis and Terraform generation. The sixth stage is the reviewer in `api/agent_orchestrator.py`.

That reviewer is a bounded tool-using agent. Its only tools read local run evidence: a topology summary, the static findings, and the reasons resources were omitted from Terraform. In the default no-model mode, it chooses which evidence tools to call based on counts and findings, records the tool trace, and builds a reproducible review plan. This provides a no-key demo with an auditable fallback.

If both `AZURE_OPENAI_ENDPOINT` and `AZURE_OPENAI_CHAT_DEPLOYMENT` are set, the reviewer instead calls an existing Azure OpenAI deployment through the Responses API. The model may select from the same three allow-listed read-only functions. The server validates the tool name and empty argument schema, caps the loop at four calls, requests structured output, and links each recommendation to evidence. Requests use `store=false`; the short conversation is carried in API memory. The Azure model service still processes submitted evidence, so follow company data-handling requirements. Model errors fall back to the deterministic path. Neither the AI nor its tools can call Azure control-plane write APIs, run Terraform, approve a package, or apply changes.

### Step 5: connect Azure and package the demo

The Azure connector calls Resource Graph only after the user starts a scan. On a developer machine, `DefaultAzureCredential` can use Azure CLI sign-in. On App Service, it can use the system-assigned managed identity. The deployment does not grant Reader automatically: the operator must secure the site with Entra sign-in, then grant the app identity Reader at the narrowest approved scope.

The App Service serves the Vite build and FastAPI API from one Linux site. That keeps the hackathon deployment small. It uses a B1 plan by default and may consume the provided credits. It does not create an Azure OpenAI resource or model deployment because availability and quota vary by tenant and region.

## 3. How one run moves through the project

```text
Azure sample / imported JSON / Azure Resource Graph / optional AWS scan
                              │
                              ▼
                     POST /api/analyze
                              │
                              ▼
        normalize, redact, infer relationships, classify resources
                              │
              ┌───────────────┴─────────────────┐
              ▼                                 ▼
     explicit Terraform mapping          static inventory checks
       + skipped manifest                + findings and evidence
              └───────────────┬─────────────────┘
                              ▼
             bounded reviewer chooses evidence tools
                Azure OpenAI or local fallback
                              │
                              ▼
   overview, graph, findings, agent-review.json, Terraform files
                              │
                              ▼
   architect checks files → acknowledges review → downloads ZIP
```

1. `App.tsx` first requests `GET /api/clients` for the signed-in employee's allowed workspaces. The local demo exposes one fictional workspace. The user can then load its sample, import JSON, or start a read-only cloud scan.
2. The UI posts the active inventory to `POST /api/analyze`.
3. `normalize_inventory` in `api/main.py` checks the root and resources, canonicalizes fields, redacts common secret-shaped values, and infers relationships from known Azure ARM references and common AWS IDs.
4. `classify` proposes a module such as Network, Application, Data, Identity, or Supporting.
5. `api/azure_terraform.py` maps supported Azure types to AzureRM HCL. The AWS path remains in `api/main.py`. Unsupported and incomplete items receive an explicit reason.
6. `build_findings` checks only fields present in the input. It does not claim to certify a resource or subscription.
7. `run_agentic_review` builds a review summary and exposes only three local read functions. It records the chosen mode, tool steps, recommendations, and human-approval boundary.
8. `audit-report.json`, `agent-review.json`, `inventory-manifest.json`, `dependency-graph.json`, `skipped-resources.json`, Terraform files, and a generated README are returned in the API result.
9. Acknowledging the UI review calls `POST /api/runs/{run_id}/approve`. The ZIP route checks that acknowledgement before returning a download. This state is held in API memory, so it is only a local demo approval, not an enterprise audit record.

10. The Copilot page sends a question and the active run ID to `POST /api/runs/{run_id}/ask`. The server retrieves a small set of matching inventory records, relationships, findings, and skipped-resource reasons from that run. Local deterministic answers are the default. An administrator can separately opt in to bounded Azure OpenAI synthesis; the model gets selected redacted evidence and its citations must match supplied evidence IDs.

## 4. File-by-file reference

### Project root

| File | What it contains and why it exists |
| --- | --- |
| `.gitignore` | Excludes local dependencies, virtual environments, generated builds, Python bytecode, local Azure CLI cache, environment files, Terraform local providers/state/variable files, crash logs, and ZIPs. These contain machine-specific artifacts or may contain secrets. |
| `README.md` | The short operator guide: local start, Azure scan, optional model mode, Azure deployment, business-value assumptions, limits, and API routes. |
| `index.html` | Browser document shell. Vite injects the compiled asset references when it builds. FastAPI serves this same built page on App Service. |
| `package.json` | Project name, npm scripts, and direct frontend dependencies. `dev` starts both API and Vite; `check` runs TypeScript; `build` compiles the frontend. |
| `package-lock.json` | Exact npm dependency versions and dependency integrity data. Keep it in the project so `npm ci` installs a repeatable tree. |
| `tsconfig.json` | TypeScript compiler options. Strict mode catches UI/API shape mistakes before a build. |
| `vite.config.ts` | Installs the React Vite plugin and sends local `/api` browser requests to FastAPI on port 8000. Production does not need this proxy because one FastAPI site serves both assets and routes. |

### Browser source: `frontend/src/`

| File | What it contains and why it exists |
| --- | --- |
| `main.tsx` | React entry point. It imports the app and stylesheet, finds `#root` in `index.html`, and mounts the UI. |
| `App.tsx` | The product behavior. It loads employee workspaces, handles import, scan, analysis, question, approval, and download requests, and renders Overview, Inventory, Copilot, Dependency Graph, IaC Package, and Guardrails views. The `AgentReviewPanel` exposes reviewer mode, evidence, and tool trace. |
| `styles.css` | Visual system and responsive layout. It styles the navigation, summary metrics, workflow stages, graph, evidence panel, tables, dialogs, guardrails, and package viewer. Media queries adapt it for tablet and phone widths. |

### API source: `api/`

| File | What it contains and why it exists |
| --- | --- |
| `main.py` | FastAPI app and main workflow. It normalizes provider inventories, redacts sensitive-looking keys, infers links, classifies resources, generates provider configuration and package metadata, runs findings, calls the reviewer, stores the latest 20 runs in memory, and defines the HTTP routes. It serves `dist/` if a production frontend build exists. |
| `auth.py` | Local-demo/Easy Auth identity boundary. In protected deployment mode it requires the platform principal header, checks the company tenant, and maps an employee object ID to named client workspaces and allowed cloud scopes. |
| `estate_copilot.py` | Bounded retrieval, local deterministic answers, optional Azure OpenAI synthesis, and citation validation for one active run. It has no cloud or Terraform tools. |
| `agent_orchestrator.py` | Evidence tools and bounded reviewer. The deterministic mode chooses local tool calls from the run signals. The optional Azure OpenAI mode uses Entra authentication and a bounded Responses API function-call loop, validates structured output, and falls back if the model cannot complete. This is the file that turns the named stages into an inspectable tool-using review process. |
| `azure_provider.py` | Read-only Azure Resource Graph adapter. It builds a subscription query, optionally filters by resource group, follows continuation pages, caps inventory size, flattens subnet metadata embedded in virtual networks, and returns the common inventory shape. It instantiates `DefaultAzureCredential` only when a scan starts. |
| `azure_terraform.py` | Explicit AzureRM resource type mapping and HCL builders. Each supported type has a predictable conversion and preconditions. Unsupported or incomplete fields return a reason rather than a guessed resource block. |
| `azure_sample_inventory.py` | Fictional Azure records and relationships for no-credential demo runs. Its IDs are samples, not a real subscription. |
| `sample_inventory.py` | Fictional AWS secondary demo data retained from the earlier prototype. |
| `requirements.txt` | Python package ranges for FastAPI, Uvicorn, AWS Boto3, Azure Identity, Resource Graph, and optional Azure OpenAI Responses API support. The model package is imported only when model settings are configured. |

### Example data: `samples/`

| File | What it contains and why it exists |
| --- | --- |
| `inventory.json` | Example Azure inventory using the API's provider-neutral JSON contract. Use it as a starting point for a small, redacted export. |
| `aws-inventory.json` | Example AWS records and VPC/subnet relationships for the secondary connector. |

The format contract is explained in `docs/inventory-format.md`. Do not use a JSON export as a place to upload keys, passwords, private keys, connection strings, or Terraform state.

### Azure deployment: `infra/`

| File | What it contains and why it exists |
| --- | --- |
| `main.bicep` | Infrastructure declaration for a Linux App Service plan, Python web app, HTTPS-only configuration, system-assigned managed identity, frontend/backend startup command, and app settings. Optional model endpoint/deployment values are parameters. It does not assign Reader or create an AI resource. |
| `deploy.ps1` | Windows PowerShell deployment helper. It verifies CLI/npm availability and login, builds and type-checks the frontend, creates the resource group, deploys Bicep, stages only API source/requirements and the compiled frontend, ZIP-deploys, polls the `/api/health` endpoint, and removes its uniquely named temporary files after path checks. It prints the identity details but deliberately does not grant cloud permissions. |
| `README.md` | Deployment steps and the required order for App Service Entra authentication, managed-identity Reader permissions, optional Azure OpenAI access, and production hardening. |

The App Service identity should receive Reader only after the site is protected by Entra sign-in, the company tenant and employee-to-client scope map are configured, and the authorized user can sign in. Assign Reader only at an approved scope. Azure OpenAI mode also needs the **Cognitive Services OpenAI User** role at the configured model resource. These assignments are manual and visible to the subscription owner.

### Design and project notes: `docs/`

| File | What it contains and why it exists |
| --- | --- |
| `architecture.md` | Runtime components, trust boundaries, data flow, Azure identity, IaC limits, and known limitations. |
| `inventory-format.md` | Required JSON fields, examples, relationship rules, provider details, and data-handling guidance. |
| `deck-analysis.md` | Which slides informed the prototype and which brief numbers remain targets rather than results. |
| `build-log-and-design-decisions.md` | Decisions and rationale recorded during the prototype build. It explains the local-first path, canonical inventory, explicit mappings, and review boundary. |
| `FROM-SCRATCH-IMPLEMENTATION-GUIDE.md` | This full file-level explanation, build sequence, end-to-end data flow, business-value calculation, demo script, and operational boundaries. |

### Generated files and local-only folders

| Path | Role |
| --- | --- |
| `dist/` | Vite build output used by FastAPI for a single-site Azure deployment. Regenerate it with `npm run build`; do not hand-edit hashed assets. |
| `node_modules/` | npm-installed JavaScript dependencies. Recreate it with `npm ci`; it is not source code. |
| `.venv/` | Python virtual environment. Recreate it with the setup command and `api/requirements.txt`. |
| `api/__pycache__/` and `*.pyc` | Python bytecode cache. It is disposable and not source. |
| `.azure/` | Optional Azure CLI local deployment context. It can contain local machine/subscription metadata and is ignored. |

The source presentation `MergeResult_2026_09_29_11_18_50 (1).pptx` is in the parent hackathon folder, outside `genesis/`; it is the input brief and is not required to run the application.

## 5. Azure connection and hosting details

### Local live scan

1. Install Azure CLI and sign in with `az login`.
2. Make sure the signed-in user has Reader at the subscription or resource-group scope.
3. Start GENESIS and enter the subscription GUID in the Azure scan dialog. The current connector scans one subscription per run.
4. Optionally provide the resource group if you want a narrow query. Repeat for each separately authorized subscription; this POC does not merge their Terraform output into a single provider package.

The UI sends only the subscription ID and optional group name. The API performs the Resource Graph call using the credential chain available to the API process. Access tokens and client secrets are not sent to the browser.

### Azure App Service

The deploy helper packages the frontend build alongside FastAPI so the App Service exposes one origin. FastAPI's `main.py` serves `dist/index.html` and `/assets/*`; the API routes stay under `/api/*`. The system-assigned managed identity is the hosted credential.

The Bicep template sets `GENESIS_AUTH_MODE=easy_auth` and does not grant Reader. Protected routes fail closed until App Service Authentication is enabled, the company tenant is pinned, and the employee/client scope map is configured. The API checks the caller and selected cloud scope before a scan or imported inventory run. Then authorize the app identity at a narrow scope.

The app uses in-memory run state and approval flags. Keep the hackathon deployment to one instance; multiple workers/instances can split runs and approvals between processes. A production version should move runs and audit history to durable storage, add tenant-aware authorization, protect logs, and document retention.

### Azure OpenAI reviewer

Configure the endpoint and model deployment name; do not configure a key. On a developer machine, `DefaultAzureCredential` can use CLI sign-in. In App Service, it can use managed identity. Assign the model role at the Azure OpenAI resource scope. The model sees a starting summary; if it calls a tool, the tool returns limited run evidence such as finding details or skipped-resource reasons. No full credential, cloud token, or Terraform state is sent.

If the model deployment cannot answer, the API catches the model failure and completes the run with the deterministic review. The UI labels that fallback. The model is optional so the sample can be replayed offline and the core demo does not depend on quota or model availability.

Copilot Q&A has a distinct `GENESIS_COPILOT_USE_AZURE_OPENAI` setting, which defaults to `false`. When enabled, each question sends a bounded redacted evidence packet to the configured deployment; selected evidence citations are shown in the UI. Otherwise answers use local evidence rules and no model service is called for questions.

## 6. Measurable value without overstating the POC

The source deck proposes 2–3 months down to 3–4 days. Using the explicit assumption of 20 working days per month:

- Baseline: `2 × 20` through `3 × 20` = 40–60 working days.
- Target workflow: 3–4 working days.
- Calculated scenario reduction: `1 - (target days / baseline days)` = 90% to 95%.
- Potential days released: 36 to 57 working days per onboarding.

Those values are a scenario derived from the brief, not a measured pilot result. The working POC reports reproducible operational facts: records processed, relationships resolved, modules suggested, Terraform blocks emitted, mapping coverage, findings, resources needing manual mapping, reviewer tool calls, and `analysis_seconds` (API pipeline runtime to three decimal places). Machine runtime is not the same as analyst time saved. The demo's fictional inventory is not evidence about customer estates.

Two local API smoke runs used the included fictional Azure sample and each returned 9 resources, 15 inferred relationships, 8 generated Terraform blocks (89% block coverage), 2 inventory findings, and 1 resource marked for manual mapping. Their API analysis runtime ranged from 0.001 to 0.005 seconds on this local machine. A separate AWS sample smoke run emitted 12 of 12 blocks. This proves that the sample workflows produced those outputs; it does not measure a production onboarding or analyst time saved.

For an evidence-backed hackathon result, time the same representative estate twice: current manual discovery and GENESIS-assisted discovery. Record the people/roles, active human minutes, inventory size, run and review times, number of exceptions, and Terraform blocks accepted or rejected. Report both the measured POC result and the 90–95% scenario target as separate figures.

## 7. Live demo narration (about four minutes)

1. **Problem (30 seconds):** explain that an inherited cloud account contains resources but not a trustworthy map of how they fit together.
2. **Start with data (20 seconds):** say the demo uses a fictional Azure inventory so the workflow is repeatable; optionally run a live read-only Azure query if authentication is already set up.
3. **Run the agents (60 seconds):** click discovery. Show resource grouping and dependency links, then the six stages. Explain that the reviewer selected read-only tools based on findings and mapping gaps.
4. **Show agent differentiation (45 seconds):** show the mode badge, tool trace, evidence-linked actions, and local fallback option. Explain that model output is constrained to a small structured review; it cannot make changes.
5. **Show measurable outputs (45 seconds):** report actual sample resource count, relationship count, generated Terraform blocks, block coverage, skipped count, and findings. State the 90–95% time reduction as a target calculation with assumptions, not a measured result.
6. **Show enterprise handoff (40 seconds):** inspect `imports.tf`, `audit-report.json`, `agent-review.json`, and `skipped-resources.json`. Acknowledge the architect gate and download the package. Say an engineer must validate and plan it in a protected Terraform workspace.
7. **Azure applicability (20 seconds):** explain that Resource Graph is the read-only connector, managed identity is the hosted identity, and the normalized inventory/tools/mapping registry can be extended to other accounts and providers.

## 8. Run and verify locally

From the project root:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r api\requirements.txt
npm ci
npm run check
npm run build
.\.venv\Scripts\python.exe -m py_compile api\main.py api\auth.py api\estate_copilot.py api\agent_orchestrator.py api\azure_provider.py api\azure_terraform.py
npm run dev
```

Then open the Vite address and run the sample. The local build can verify the frontend and API code path. It cannot verify access to the company's Azure tenant, the Azure OpenAI deployment, App Service deployment, Terraform CLI validity, or a cloud plan unless those are separately configured and run.
