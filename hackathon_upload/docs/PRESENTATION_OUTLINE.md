# GENESIS — Presentation Outline

**Hackathon Presentation: 8–10 Slides**
**Recommended duration:** 8–12 minutes

---

## Slide 1 — Title

**Slide Title:** GENESIS — Azure Cloud Blueprint Studio

**Bullet Points:**
- AI-assisted read-only cloud estate analysis
- Automated dependency mapping, policy review, and IaC generation
- Designed for Kyndryl managed-services onboarding workflows
- Prototype with a full local demo — no Azure credentials required

**Recommended Visual:**
- GENESIS application Overview page screenshot after a completed discovery run
- Or: the GENESIS logo/name against a dark background with the subtitle "Azure Cloud Blueprint Studio"

**Speaker Notes:**
> "GENESIS addresses a real friction point in managed-services delivery: understanding and documenting an inherited cloud estate before you can safely operate it. Today we'll walk through the prototype, what it does, how it works, and what the right next step would be to validate business value."

---

## Slide 2 — The Problem

**Slide Title:** The Inherited Cloud Problem

**Bullet Points:**
- Inherited Azure estates are built manually — no IaC baseline, no dependency map
- Ownership metadata is missing: no tags, no workload assignments
- Manual policy review against exported CSVs takes days per engagement
- Writing Terraform from scratch before lifecycle controls can be applied
- Brief target: compress a 2–3 month onboarding to 3–4 days *(stated goal, not a measured result)*

**Recommended Visual:**
- Simple before/after diagram: "Months of manual review" → "Structured starting point"
- Or: a text callout showing the brief's scenario target clearly labeled as a goal assumption

**Speaker Notes:**
> "The source brief frames this as a 90–95% reduction in onboarding time. That's the design goal, not a measured GENESIS result. What we built is the prototype that would enable a timed pilot to gather that evidence. The problem itself is real — Kyndryl engineers inherit complex estates regularly, and the current process is manual."

---

## Slide 3 — The Solution

**Slide Title:** GENESIS: Read-Only Estate Analysis

**Bullet Points:**
- Accepts: fictional sample, uploaded JSON inventory, or live Azure Resource Graph scan (read-only)
- Normalizes resources and infers dependency relationships automatically
- Runs bounded AI-assisted investigation (up to 12 tool calls)
- Generates policy findings from metadata signals
- Produces modular draft Terraform with import blocks
- Gates all output behind a human review checkpoint

**Recommended Visual:**
- High-level flow diagram: Inventory → Analysis → Agents → Human Review → ZIP Package
- Or: screenshot of the Overview page showing the 4 key metrics (resources, relationships, modules, findings)

**Speaker Notes:**
> "GENESIS never writes to Azure, never applies Terraform, and never auto-approves anything. The human architect reviews every output before downloading the package. The AI agents are bounded — hard limits on tool calls, tokens, and time — so the system behaves predictably."

---

## Slide 4 — Architecture

**Slide Title:** Technical Architecture

**Bullet Points:**
- React/TypeScript frontend (Vite) + Python FastAPI backend
- Shared read-only EstateTools registry: 6 functions, all read-only
- Three bounded agent roles: Investigator (12 calls), Reviewer (4 calls), Terraform Writer (2 drafts)
- Copilot: 8 tool calls per question, 45-second limit
- Azure OpenAI optional — deterministic fallback always available
- Optional: Azure App Service deployment via Bicep + PowerShell

**Recommended Visual:**
- Mermaid system diagram from `submission/ARCHITECTURE_DIAGRAM.md`
- Or: component table from `submission/ARCHITECTURE_AND_TECHNICAL_OVERVIEW.md`

**Speaker Notes:**
> "The architecture is intentionally constrained. Every agent operates against the same read-only tool registry — there are no write functions available to any agent. If Azure OpenAI is not configured, the system uses deterministic code that calls the same tools in a fixed sequence. The demo you're about to see runs entirely without an Azure subscription or model deployment."

---

## Slide 5 — Discovery and Inventory

**Slide Title:** Estate Discovery and Inventory

**Bullet Points:**
- 72-resource fictional Azure estate (4 workloads: VMs, SQL, networking, App Service)
- ~124 inferred dependency relationships from ARM ID hierarchy + property walks
- 5 resource categories: network, application, data, identity, supporting
- Azure Resource Graph connector for live scans (read-only, requires Reader role)
- Secret-shaped inventory fields redacted before display or model transmission

**Recommended Visual:**
- Screenshot: **Inventory tab** showing resources with types and module categories
- Screenshot: **Dependency graph** with one node selected showing its relationships

**Speaker Notes:**
> "The 72-resource estate is entirely fictional — the tenant, subscription, resource names, and customer data are invented. It was designed to represent a realistic multi-workload managed environment with the kinds of gaps — missing tags, public rules, mixed resource types — that show up in real onboarding work. In production, you'd point GENESIS at the client's subscription with a Reader role."

---

## Slide 6 — AI Investigation and Copilot

**Slide Title:** AI-Assisted Investigation and Evidence-Cited Copilot

**Bullet Points:**
- Investigator groups 72 resources into **8 inferred workloads** with cited resource IDs
- Every workload and risk must cite a real resource ID — uncited claims are filtered out
- Copilot answers questions using the same read-only tools: impact analysis, topology, findings
- Both run in deterministic tool mode by default; Azure OpenAI is opt-in
- Citation enforcement: Copilot UI validates every resource citation against tool-returned IDs

**Recommended Visual:**
- Screenshot: **Investigator / Workloads tab** showing workload list with resource citations
- Screenshot: **Copilot tab** with a submitted question and evidence citation cards

**Speaker Notes:**
> "The citation enforcement is a key design decision. Any agent output that doesn't link to a real resource ID in the inventory is dropped before you see it. This prevents hallucinated references. The Copilot can answer questions like 'what breaks if I remove this virtual network?' by walking the dependency graph — it's not doing a web search, it's reasoning over the specific inventory we just discovered."

---

## Slide 7 — Dependency and Risk Analysis

**Slide Title:** Dependency Graph and Policy Findings

**Bullet Points:**
- ~124 inferred relationships: ARM ID hierarchy, subnet/NSG/VNet property walks, explicit edges
- Dependency graph supports blast-radius analysis via `impact_of` tool
- **~21 guardrail findings** from metadata signal checks (critical → low severity)
- **1 critical finding**: public inbound NSG rule allowing port 22/3389 from internet
- Checks cover: NSG rules, missing owner tags, public storage, weak TLS, exposed SQL/Key Vault

**Recommended Visual:**
- Screenshot: **Dependency graph** with the network topology visible
- Screenshot: **Guardrails tab** showing the finding list with severity badges and the critical finding highlighted

**Speaker Notes:**
> "The 21 findings and 1 critical are from the fictional estate. The NSG critical is intentional — the sample was designed to include the kinds of configuration gaps that need immediate review during onboarding. These checks are metadata-only; they tell you what to look at, not whether the estate is compliant. That determination still requires a human architect."

---

## Slide 8 — Terraform / IaC Generation

**Slide Title:** Draft Infrastructure-as-Code Generation

**Bullet Points:**
- Base generator covers 7 Azure types: resource groups, VNets, subnets, NSGs, public IPs, NICs, storage accounts
- Bounded writer adds Key Vault and App Service (selected from skipped list)
- **~42% coverage** of 72 resources (~30 blocks emitted post-writer)
- **~42 resources** in skipped-resource manifest with specific reasons
- Generated import blocks link existing resource IDs to Terraform addresses
- `prevent_destroy = true` on all blocks; still requires `terraform validate` and plan

**Recommended Visual:**
- Screenshot: **IaC Package tab** showing coverage percentage, module list, and skipped-resource count
- Or: a sample HCL snippet from one of the generated module files

**Speaker Notes:**
> "42% coverage means 42% of the 72 resources have an emitted Terraform resource block — not that those blocks are configuration-complete or safe to apply. The 42 skipped resources are listed with specific reasons, so the architect knows exactly what still needs hand-crafting. The package is a starting point and a draft: review every file, run terraform validate, inspect a plan in a protected workspace before considering any apply. GENESIS does none of that itself."

---

## Slide 9 — Security and Governance

**Slide Title:** Security Boundaries and Governance Controls

**Bullet Points:**
- **Read-only**: Azure Resource Graph and AWS Boto3 describe/list calls only; no write APIs
- **Credential isolation**: Azure credentials never reach the browser
- **Secret redaction**: common secret-shaped keys removed before display or model transmission
- **Human review gate**: ZIP download locked until explicit acknowledgement
- **Agent limits**: hard caps on tool calls, tokens, wall time, and model requests per role
- **Citation enforcement**: uncited agent recommendations automatically dropped
- **`store=false`**: model requests do not persist on Azure OpenAI service

**Recommended Visual:**
- Read-only boundary diagram from `submission/ARCHITECTURE_DIAGRAM.md`
- Or: a table of security controls from `submission/ARCHITECTURE_AND_TECHNICAL_OVERVIEW.md`

**Speaker Notes:**
> "These boundaries are enforced in code, not just policy. The agent tool registry literally has no write functions. The approval gate is not just a UI checkbox — the ZIP endpoint returns 403 until `POST /api/runs/{id}/approve` has been called. When we configured App Service for a hosted demo, those controls extend to binding each run to its creating employee's Entra identity."

---

## Slide 10 — Impact and Next Steps

**Slide Title:** Business Impact and Path Forward

**Bullet Points:**
- **Demonstrated**: structured estate starting point in seconds from a read-only scan
- **Demonstrated**: evidence-cited workload map, risk findings, and draft IaC
- **Goal assumption** (from brief): 90–95% onboarding time reduction — requires a timed pilot to verify
- **Next step 1**: timed pilot — compare manual vs. GENESIS-assisted workflow on an approved representative estate
- **Next step 2**: expand Terraform type coverage (VMs, SQL, AKS, Cosmos DB)
- **Next step 3**: production hardening (durable storage, multi-subscription, private networking, audit retention)

**Recommended Visual:**
- Overview page screenshot showing the 4 key demo metrics: 72 resources, 124 relationships, 5 modules, 21 findings
- Or: a simple roadmap showing current state → pilot → production hardening

**Speaker Notes:**
> "GENESIS gives a managed-services engineer a structured, evidence-grounded starting point instead of a blank page. The goal assumption of 90–95% time reduction is directionally compelling, but the right next step is a real pilot: take a representative approved estate, time the current manual workflow, run GENESIS, time the assisted review, and report what actually changed — including human review time. That's where GENESIS earns its place in the Kyndryl delivery toolkit."

---

## Presentation Tips

| Tip | Detail |
|---|---|
| Lead with the demo | Show the application before the architecture slide if possible |
| Label assumptions clearly | The 2–3 month → 3–4 day figure must always be introduced as a goal, not a result |
| Distinguish fictional from real | Remind the audience the 72 resources are a fictional demo estate |
| Show the human gate | The acknowledgement checkbox is a talking point about responsibility and governance |
| Show Copilot live | A live Copilot question (typed and answered) is more compelling than a screenshot |
| Acknowledge limits | Proactively stating that coverage ≠ parity builds credibility |
