# GENESIS — Azure Cloud Blueprint Studio
## Hackathon Submission Package

**Team:** Kyndryl
**Category:** Cloud Operations / AI-Assisted Infrastructure Automation

---

## What This Folder Contains

```
hackathon_upload/
├── README_SUBMISSION.md          ← This file — start here
├── docs/
│   ├── HACKATHON_SUBMISSION_OVERVIEW.md        ← READ THIS FIRST — concise submission summary
│   ├── ARCHITECTURE_AND_TECHNICAL_OVERVIEW.md  ← Full technical deep-dive
│   ├── ARCHITECTURE_DIAGRAM.md                 ← Mermaid architecture diagrams
│   ├── DEMO_SCRIPT.md                          ← 3–5 min step-by-step demo guide
│   ├── PRESENTATION_OUTLINE.md                 ← 10-slide deck outline with speaker notes
│   └── SUBMISSION_CHECKLIST.md                 ← Final verification checklist
└── screenshots/
    ├── 01_overview_dashboard.png   ← Discovery complete — 72 resources, 124 deps, 21 findings
    ├── 02_inventory_view.png       ← Full resource inventory with module categories
    ├── 03_dependency_graph.png     ← Interactive dependency graph — 124 relationships
    ├── 04_investigator_workloads.png ← AI Investigator — 8 inferred workloads with citations
    ├── 05_guardrails_findings.png  ← 21 policy findings including 1 Critical NSG rule
    ├── 06_copilot_qa.png           ← Copilot answering impact question with evidence
    ├── 07_iac_package.png          ← IaC Package — 42% coverage, human review gate
    └── 08_architecture_diagram.png ← System architecture overview
```

---

## One-Line Summary

> GENESIS is a read-only cloud estate analysis tool that discovers an Azure environment, infers its dependency graph, investigates workloads with bounded AI agents, flags policy risks, generates draft Terraform modules, and gates all output behind a human review checkpoint — with no Azure credentials required for the demo.

---

## Key Demo Numbers (Fictional Estate)

| Metric | Value | Note |
|---|---|---|
| Resources | 72 | Fictional synthetic estate |
| Dependency relationships | ~124 | Inferred automatically |
| Terraform modules | 5 | network, app, data, identity, supporting |
| Terraform coverage | ~42% | 30 of 72 resources |
| Review findings | ~21 | Metadata signal checks |
| Critical findings | 1 | Public inbound NSG rule |
| Inferred workloads | 8 | Investigator agent output |
| Resources needing manual mapping | ~42 | Skipped-resource manifest |

> ⚠️ All numbers above are from the **fictional demo estate** (`samples/kyndryl-synthetic-estate.json`). They are not from a real Kyndryl or customer environment.

---

## How to Run the Demo

```
1. npm run dev          (starts frontend :5173 + API :8000)
2. Open http://127.0.0.1:5173
3. Click "Run Discovery" on the Overview page
4. Walk through: Inventory → Dependency Graph → Investigator → Guardrails → Copilot → IaC Package
```

Full demo steps: see `docs/DEMO_SCRIPT.md`

---

## Important Disclaimers

- The 2–3 month → 3–4 day onboarding reduction is a **goal assumption from the brief**, not a measured GENESIS result
- GENESIS **never applies Terraform**, never writes to Azure, never creates or deletes resources
- Azure OpenAI is **optional** — the full demo runs in deterministic mode without any model deployment
- The 72-resource estate is **entirely fictional** — no real Kyndryl or customer data
