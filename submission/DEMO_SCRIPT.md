# GENESIS — Demo Script

**Duration:** 3–5 minutes
**Application URL:** http://127.0.0.1:5173
**Prerequisites:** `npm run dev` running (both frontend on :5173 and API on :8000)

> **Presenter note:** All demo steps use the fictional 72-resource Azure estate built into the application. No Azure credentials, no Azure spend, and no model deployment are required.

---

## Step 1 — Introduce the Problem (30 seconds)

**What to say:**
> "When Kyndryl onboards a new managed Azure account, the team typically inherits an estate that was built manually — no IaC, no dependency map, missing ownership tags, and no policy baseline. Assembling that picture can take weeks of analyst time before anyone can safely operate the environment. GENESIS is a prototype that provides a structured, read-only starting point for that work."

**What to show:** Keep the application unopened or show the Overview landing page.

---

## Step 2 — Open GENESIS and Run Discovery (30–45 seconds)

**What to click:**
1. Open `http://127.0.0.1:5173` in the browser
2. The **Overview** page loads with the fictional Azure estate pre-selected
3. Click **Run discovery** (or **Run analysis** — the main action button on the Overview page)

**What to say:**
> "GENESIS ships with a 72-resource fictional Azure estate that represents a realistic multi-workload managed environment. I'll click Run discovery now. The analysis normalizes the inventory, infers dependency relationships, runs the Investigator agent, checks policy signals, and generates a draft Terraform package — all locally, all read-only."

**What it demonstrates:** The full analysis pipeline runs in seconds against the fictional inventory. No Azure credentials are involved.

> **Presenter note:** While the analysis runs, briefly explain that in a real engagement, the team would use the Azure Resource Graph connector (read-only, requires Reader role) to scan the actual client subscription. For this demo, the fictional inventory gives a fully predictable result.

---

## Step 3 — Show the Discovery Overview (30 seconds)

**What to show:** After the run completes, the Overview page displays:
- Total resources discovered (72)
- Inferred dependency relationships (~124)
- Suggested Terraform modules (5)
- Review findings count (~21, including 1 critical)

**What to say:**
> "The analysis found 72 resources, inferred approximately 124 dependency relationships, grouped them into 5 Terraform modules, and flagged 21 policy findings including one critical — a public inbound network rule. Everything here traces back to actual resource IDs in the inventory."

**What it demonstrates:** High-level estate summary in a single view.

---

## Step 4 — Show the Inventory (30 seconds)

**What to click:** Navigate to the **Inventory** tab or section

**What to show:**
- The list of individual cloud resources with their types, names, regions, and resource groups
- The module category assigned to each resource (network, application, data, identity, supporting)
- Any resources flagged with findings

**What to say:**
> "Every resource from the estate is visible here with its type, region, and assigned module category. The classifier grouped them into five categories — network, application, data, identity, and supporting — which map directly to the Terraform module structure we'll see later."

**What it demonstrates:** Normalized, searchable inventory view organized by category.

---

## Step 5 — Show the Dependency Graph (30 seconds)

**What to click:** Navigate to the **Dependency graph** tab or section

**What to show:**
- The visual dependency graph with nodes and edges
- Select one node (e.g., a virtual machine or network interface) to highlight its relationships

**What to say:**
> "The dependency graph shows ~124 inferred relationships. These are built automatically from ARM ID hierarchies and property references — not manually drawn. If I select this resource, I can see which subnets, NSGs, or public IPs it connects to. This is the same graph the Copilot uses to answer 'what breaks if I remove this?'"

**What it demonstrates:** Automated dependency inference; blast-radius visibility.

---

## Step 6 — Show the Investigator / Workloads and Risks (45 seconds)

**What to click:** Navigate to the **Investigator** tab or the **Workloads** section

**What to show:**
- The 8 inferred workload groupings with their resource members
- The cited risk items (each linked to real resource IDs or finding IDs)
- The open questions raised by the Investigator
- The agent mode badge (deterministic tool fallback or Azure OpenAI)

**What to say:**
> "The Investigator agent explored the inventory using the same read-only tools that power the Copilot. It grouped the 72 resources into 8 inferred workloads — each tied to real resource IDs, not invented labels. It also surfaced risks with citations. If Azure OpenAI were configured, the model would select and sequence these tool calls; without it, the deterministic fallback runs the same tools in code. Either way, every workload and risk must cite a real resource ID or it's filtered out before you see it."

**What it demonstrates:** Bounded, evidence-grounded AI investigation; automatic workload grouping; citation enforcement.

---

## Step 7 — Show the Copilot (45 seconds)

**What to click:** Navigate to the **Copilot** tab

**What to show / type:** Ask one of these questions:
- `Which resources need manual Terraform mapping?`
- `What breaks if I remove the virtual network?`
- `What should I review in the public inbound rule?`

**What to show after submitting:**
- The answer text
- The cited resource evidence cards at the bottom (linked to real resource IDs)
- The tool call trace (if visible)

**What to say:**
> "The Copilot works against the active run. I'll ask: 'What breaks if I remove the virtual network?' It walks the dependency graph using the same read-only tools — no internet search, no general knowledge, only the inventory we just discovered. Every citation at the bottom links to an actual resource ID returned by those tools. The UI validates that before showing you the answer."

**What it demonstrates:** Evidence-cited Q&A; dependency/impact tracing; Copilot citation validation.

> **Presenter note:** Copilot runs in local tool mode by default. Azure OpenAI synthesis is an opt-in that requires explicit configuration. This keeps the demo free of model cost and latency.

---

## Step 8 — Show the Guardrails / Policy Review (30 seconds)

**What to click:** Navigate to the **Guardrails** tab

**What to show:**
- The list of findings with severity levels (critical, high, medium, low)
- The critical finding: public inbound NSG rule
- The low-severity missing-owner-tag findings across multiple resources

**What to say:**
> "The Guardrails panel shows 21 policy findings. The critical one is a public inbound network rule in the fictional estate — the kind of configuration that needs immediate review before a managed team takes responsibility for it. All findings come from metadata signal checks against the inventory fields. This is not a live Azure Policy evaluation — it's a starting point for the architect's review."

**What it demonstrates:** Automated policy signal checks; severity-classified findings; transparent limitations.

---

## Step 9 — Show the IaC / Terraform Package (45 seconds)

**What to click:** Navigate to the **IaC Package** tab

**What to show:**
- The Terraform coverage percentage (~42%)
- The module structure (network, application, data, identity, supporting)
- A sample HCL block from one of the modules
- The skipped-resource list showing resources that need manual mapping (~42)
- The human review acknowledgement checkbox

**What to say:**
> "The IaC package covers about 42% of the 72 resources with Terraform blocks — the 7 Azure types the base generator supports, plus Key Vault and App Service from the bounded writer. The other 42 resources are in the skipped-resource manifest with specific reasons, so an architect knows exactly what still needs hand-crafting. Every block has an import statement so the resources can be brought under Terraform management. I need to check this acknowledgement before the download activates — that's the human review gate."

**What it demonstrates:** Draft IaC generation; transparent coverage limits; skipped-resource manifest; human review gate.

---

## Step 10 — Explain Read-Only and Human-Review Controls (20 seconds)

**What to say:**
> "Before I download, I want to highlight the safety boundaries. GENESIS only reads — it uses Azure Resource Graph read calls and never touches the control plane. The agent tool registry has no write functions. Azure credentials stay in the CLI or App Service identity and never reach the browser. And this checkbox isn't just UX — the ZIP download is locked until you explicitly acknowledge that you've reviewed the package. GENESIS never runs terraform apply."

**What it demonstrates:** Read-only boundary; human approval gate; credential isolation.

---

## Step 11 — Close with the Value Proposition (20 seconds)

**What to say:**
> "GENESIS gives a managed-services team a structured, evidence-grounded starting point for onboarding an inherited Azure estate: a normalized inventory, a dependency map, an AI-investigated workload breakdown, flagged policy risks, and a draft Terraform package — all produced in seconds from a read-only scan. The goal from the brief is to compress weeks of manual work into a reviewable starting point. The next step is a timed pilot on an approved representative estate to measure the actual before-and-after for Kyndryl engineers. Thank you."

---

## Quick Reference — Supported Copilot Questions

| Question pattern | What it exercises |
|---|---|
| "Which resources need manual Terraform mapping?" | `get_unmapped_resources` tool |
| "What breaks if I remove [resource name]?" | `impact_of` tool (dependency walk) |
| "What should I review in the public inbound rule?" | `get_findings` tool |
| "How many resources are in the estate?" | `get_estate_summary` tool |
| "What are the connections for [resource name]?" | `get_neighbors` tool |
| "Show me all network resources" | `list_resources` tool with module filter |

---

## Troubleshooting

| Issue | Resolution |
|---|---|
| `http://127.0.0.1:5173` shows blank | Confirm `npm run dev` is running in the terminal |
| API error on discovery | Check the terminal for FastAPI errors; confirm `.venv` Python is on PATH |
| Copilot says "not enough evidence" | The question may not match inventory terms; try a resource name from the Inventory view |
| Coverage shows 0% | Discovery may not have completed; re-run from the Overview |
