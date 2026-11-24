# GENESIS — Submission Checklist

**Solution Title:** GENESIS — Azure Cloud Blueprint Studio
**Team:** Kyndryl

---

## Solution Overview

GENESIS is a read-only cloud estate analysis tool that normalizes an Azure (or AWS) inventory, infers a dependency graph, runs a bounded AI-assisted investigation, generates policy findings, produces a draft Terraform package, and gates all output behind a human review checkpoint. It demonstrates an assisted cloud onboarding workflow using a fictional 72-resource Azure estate with no Azure credentials or model deployment required.

---

## Implemented and Verifiable

- [ ] Application runs locally at `http://127.0.0.1:5173` with `npm run dev`
- [ ] 72-resource fictional Azure estate loads and completes analysis via `GET /api/demo` + `POST /api/analyze`
- [ ] Dependency graph displays inferred relationships (~124 for the synthetic estate)
- [ ] Guardrail findings display with severity classification (critical, high, medium, low)
- [ ] Investigator output shows workload groupings with cited resource IDs
- [ ] Copilot answers questions and displays evidence citations linked to real resource IDs
- [ ] IaC Package tab shows Terraform coverage, module breakdown, and skipped-resource list
- [ ] Human review acknowledgement checkbox gates ZIP download
- [ ] API health endpoint responds at `http://127.0.0.1:8000/api/health`
- [ ] All 6 agent roles have hard limits on tool calls, tokens, and wall time (verified in source)
- [ ] Deterministic fallback works without Azure OpenAI (default mode in demo)
- [ ] Secret-shaped inventory keys are redacted before browser display

---

## Supporting Evidence

- [ ] `README.md` — project overview, API routes, run instructions, measurement context
- [ ] `docs/architecture.md` — runtime flow, agent roles, data boundaries, Terraform limits
- [ ] `docs/CLOUDLABS-DEMO-RUNBOOK.md` — demo flow, suggested presentation steps
- [ ] `docs/deck-analysis.md` — brief analysis and goal assumptions clearly labeled
- [ ] `docs/inventory-format.md` — JSON input contract
- [ ] `docs/FROM-SCRATCH-IMPLEMENTATION-GUIDE.md` — full implementation documentation
- [ ] `api/main.py` — normalization, findings, Terraform generation, all API routes
- [ ] `api/investigator.py` — Investigator agent with citation enforcement
- [ ] `api/estate_copilot.py` — Copilot with citation validation
- [ ] `api/agent_orchestrator.py` — Reviewer with citation enforcement
- [ ] `api/terraform_writer.py` — bounded Terraform writer
- [ ] `api/agentic_tools.py` — shared read-only tool registry
- [ ] `api/azure_provider.py` — Azure Resource Graph connector
- [ ] `samples/kyndryl-synthetic-estate.json` — fictional 72-resource demo estate
- [ ] `infra/main.bicep` + `infra/deploy.ps1` — optional App Service deployment

---

## Screenshots to Capture

Capture these screenshots from the running application at `http://127.0.0.1:5173`:

- [ ] **Overview page** after discovery completes — showing resource count (72), relationships (~124), modules (5), findings (~21 with 1 critical)
- [ ] **Inventory tab** — showing resource list with types, modules, and categories
- [ ] **Dependency graph tab** — showing nodes and edges; one node selected with relationships highlighted
- [ ] **Investigator / Workloads tab** — showing 8 inferred workloads with resource citations
- [ ] **Guardrails tab** — showing findings list with the 1 critical finding visible
- [ ] **Copilot tab** — showing a question submitted and an answer with evidence citations at the bottom
- [ ] **IaC Package tab** — showing ~42% coverage, module list, skipped resources (~42), and the acknowledgement checkbox

---

## Architecture Document

- [ ] `submission/ARCHITECTURE_DIAGRAM.md` — Mermaid diagrams of system data flow, component relationships, and read-only/human-approval boundaries
- [ ] `submission/ARCHITECTURE_AND_TECHNICAL_OVERVIEW.md` — full technical overview with component table, API routes, findings table, Terraform type table, security boundary table

---

## Technical Overview

- [ ] `submission/HACKATHON_SUBMISSION_OVERVIEW.md` — concise submission summary with capabilities table, demonstrated results table, limitations table, and business-value framing

---

## Demo Video / Presentation

- [ ] Demo video or live walkthrough follows `submission/DEMO_SCRIPT.md`
- [ ] `submission/PRESENTATION_OUTLINE.md` — 8–10 slide outline with bullet points, speaker notes, and screenshot recommendations per slide

---

## Final Verification Before Submission

- [ ] Application starts without errors with `npm run dev`
- [ ] Discovery completes successfully on the fictional estate
- [ ] All 7 UI tabs/sections are accessible and show data
- [ ] Copilot returns a cited answer to at least one test question
- [ ] ZIP download works after checking the acknowledgement
- [ ] No real Azure credentials, customer data, or subscription IDs are present in any committed file
- [ ] `.gitignore` excludes `.venv`, `node_modules`, `dist`, `.env`, and Terraform state files
- [ ] All numbers in submission documents match the fictional estate, with appropriate disclaimers

---

## Items That Must NOT Be Claimed

> [!CAUTION]
> Do not present the following as proven facts in the submission:

- ❌ **Do not claim** the 2–3 month → 3–4 day reduction is a measured GENESIS result — it is a goal assumption from the original brief
- ❌ **Do not claim** the 72-resource estate is a real Kyndryl or customer environment — it is a fictional synthetic inventory
- ❌ **Do not claim** Terraform coverage means configuration parity or that imports are safe to apply without further validation
- ❌ **Do not claim** guardrail findings constitute a compliance determination
- ❌ **Do not claim** Azure OpenAI was used in the demo if running in deterministic fallback mode
- ❌ **Do not claim** GENESIS has been deployed to Azure unless `infra/deploy.ps1` has been executed and the site is accessible
- ❌ **Do not claim** the solution has been tested against a live Azure subscription unless `az login` and a live scan were performed
- ❌ **Do not claim** machine processing time (sub-second for the demo pipeline) equals analyst time saved

---

## Disclaimer Template for Submission

> GENESIS is a prototype demonstrating an AI-assisted cloud estate analysis workflow. All demo figures (72 resources, 124 relationships, 5 modules, 21 findings, 42% Terraform coverage) are from a fictional synthetic inventory and are not from a real Kyndryl or customer environment. The 90–95% onboarding time reduction is a goal assumption from the project brief, not a measured result. A timed pilot on a representative approved estate is required to establish actual time savings.
