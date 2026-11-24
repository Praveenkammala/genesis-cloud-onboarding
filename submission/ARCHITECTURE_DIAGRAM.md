# GENESIS — Architecture Diagram

## System Data Flow

```mermaid
flowchart TD
    subgraph INPUT["Inventory Sources"]
        A1["Fictional Azure Sample\n72-resource estate\n(GET /api/demo)"]
        A2["Fictional Baseline Sample\n9-resource estate\n(GET /api/demo/baseline)"]
        A3["Fictional AWS Sample\n(GET /api/demo/aws)"]
        A4["Uploaded JSON Inventory\n(POST /api/analyze)"]
        A5["Live Azure Resource Graph\n(POST /api/providers/azure/discover)\n⚠ Requires Reader role + az login"]
    end

    subgraph READONLY["Read-Only Boundary — No cloud writes"]
        B["FastAPI Normalization\nnormalize_inventory()\n• Standardize fields\n• Redact secret-shaped keys\n• Resolve ARM IDs\n• Infer relationships"]
    end

    subgraph ANALYSIS["Analysis Pipeline (api/main.py)"]
        C["Dependency Graph\nbuild_relationships()\n• ARM ID hierarchy\n• Property reference walks\n• Explicit edge list"]
        D["Resource Classification\nclassify()\n• network / application\n• data / identity / supporting"]
        E["Base Terraform Generator\nterraform_for_provider()\n• Resource Groups, VNets, Subnets\n• NSGs, Public IPs, NICs\n• Storage Accounts"]
        F["Guardrails / Findings\nbuild_findings()\n• NSG public inbound rules\n• Missing owner tags\n• Public storage, weak TLS\n• SQL/KeyVault/AppService signals"]
    end

    subgraph AGENTS["Bounded Agent Pipeline"]
        G["Investigator\ninvestigator.py\nup to 12 tool calls\n• Workload grouping\n• Risk identification\n• Open questions"]
        H["Terraform Writer\nterraform_writer.py\n• Selects ≤1 KeyVault + ≤1 AppService\n• Static HCL validation\n• Up to 3 repair retries"]
        I["Reviewer\nagent_orchestrator.py\nup to 4 tool calls\n• Evidence-cited recommendations\n• Drops uncited claims"]
    end

    subgraph TOOLREG["Shared Read-Only Estate Tools\nagentic_tools.py — EstateTools registry"]
        T1["list_resources"]
        T2["get_neighbors"]
        T3["impact_of"]
        T4["get_findings"]
        T5["get_unmapped_resources"]
        T6["get_estate_summary"]
    end

    subgraph AIPATH["Optional: Azure OpenAI\n(AZURE_OPENAI_ENDPOINT + AZURE_OPENAI_CHAT_DEPLOYMENT)"]
        AI["Azure OpenAI\nResponses API\nfunction calling\nstore=false\nDefaultAzureCredential"]
    end

    subgraph COPILOT["Copilot (independent, per question)"]
        CP["estate_copilot.py\nup to 8 tool calls / question\n45 sec / 2800 tokens\nLocal mode default\nAzure OpenAI opt-in only"]
    end

    subgraph HUMANGATE["Human Review Gate"]
        HR["User Inspects:\n• Inventory view\n• Dependency graph\n• Guardrails / Findings\n• Investigator workloads\n• IaC Package\n• Copilot Q&A"]
        APPROVE["POST /api/runs/{id}/approve\nAcknowledgement checkbox\n(demo gate, not enterprise SoD)"]
    end

    subgraph OUTPUT["Output Package (in-memory ZIP)"]
        O1["versions.tf"]
        O2["main.tf"]
        O3["imports.tf"]
        O4["modules/network/main.tf"]
        O5["modules/application/main.tf"]
        O6["modules/data/main.tf"]
        O7["skipped-resources.json"]
        O8["audit.json"]
    end

    subgraph NEVER["NEVER Performed by GENESIS"]
        N1["❌ terraform apply"]
        N2["❌ Azure write operations"]
        N3["❌ Resource creation/deletion"]
        N4["❌ Auto-approval"]
    end

    %% Input → Normalization
    A1 --> B
    A2 --> B
    A3 --> B
    A4 --> B
    A5 --> B

    %% Normalization → Analysis
    B --> C
    B --> D
    B --> E
    B --> F

    %% Analysis → Agents
    C --> G
    D --> E
    E --> H
    F --> G
    F --> I

    %% Agents ↔ Tool Registry
    G <--> TOOLREG
    H <--> TOOLREG
    I <--> TOOLREG

    %% Optional AI path
    G <-.->|"Optional\nAzure OpenAI\npath"| AI
    I <-.->|"Optional\nAzure OpenAI\npath"| AI
    AI <-.->|"Tool calls\n(read-only)"| TOOLREG

    %% Copilot
    CP <--> TOOLREG
    CP <-.->|"Opt-in only\nGENESIS_COPILOT_USE_AZURE_OPENAI=true"| AI

    %% Agents → Human Gate
    G --> HR
    H --> HR
    I --> HR
    F --> HR
    E --> HR

    %% Human Gate → Output
    HR --> APPROVE
    APPROVE --> OUTPUT

    %% Style
    classDef readonly fill:#1a3a5c,stroke:#4a9eff,color:#fff
    classDef agent fill:#2d4a1e,stroke:#6abf5e,color:#fff
    classDef ai fill:#4a2d6b,stroke:#a07be0,color:#fff
    classDef gate fill:#5c3a00,stroke:#ffa500,color:#fff
    classDef output fill:#1a3a3a,stroke:#4acfcf,color:#fff
    classDef never fill:#3a1a1a,stroke:#ff6060,color:#fff
    classDef input fill:#2a2a2a,stroke:#888,color:#ddd

    class B,TOOLREG readonly
    class G,H,I agent
    class AI,CP ai
    class HR,APPROVE gate
    class OUTPUT,O1,O2,O3,O4,O5,O6,O7,O8 output
    class NEVER,N1,N2,N3,N4 never
    class INPUT,A1,A2,A3,A4,A5 input
```

---

## Component Relationships

```mermaid
graph LR
    subgraph FRONTEND["Frontend (React/TypeScript)"]
        F1["App.tsx\nSingle-page app\nVite + TypeScript"]
    end

    subgraph API["Backend (Python/FastAPI)"]
        M["main.py\nRoutes + normalization\n+ analysis pipeline"]
        INV["investigator.py\nBounded investigator agent"]
        AO["agent_orchestrator.py\nReviewer agent"]
        EC["estate_copilot.py\nCopilot Q&A"]
        TW["terraform_writer.py\nHCL writer + validator"]
        AR["agentic_runtime.py\nModelBudget + response_tool_agent"]
        AT["agentic_tools.py\nEstateTools registry"]
        AZT["azure_terraform.py\nAzure HCL generator"]
        AZP["azure_provider.py\nResource Graph connector"]
        AU["auth.py\nActor + scope checking"]
    end

    subgraph AZURE["Azure Services (optional)"]
        RG["Azure Resource Graph\n(read-only scan)"]
        AOAI["Azure OpenAI\nResponses API\n(optional)"]
        AS["App Service\n(optional hosting)"]
    end

    subgraph DATA["Sample Data"]
        S1["samples/kyndryl-synthetic-estate.json\n72-resource fictional Azure estate"]
        S2["samples/inventory.json\n9-resource baseline (AWS)"]
        S3["samples/aws-inventory.json\nAWS sample"]
    end

    F1 -->|"HTTP /api/*"| M
    M --> INV
    M --> AO
    M --> EC
    M --> TW
    M --> AZT
    M --> AZP
    M --> AU
    INV --> AR
    AO --> AR
    EC --> AR
    TW --> AR
    INV --> AT
    AO --> AT
    EC --> AT
    AR -->|"Optional"| AOAI
    AZP -->|"Read-only"| RG
    S1 --> M
    S2 --> M
    S3 --> M
    AS -.->|"Hosts (optional)"| M
    AS -.->|"Hosts (optional)"| F1
```

---

## Read-Only and Human Approval Boundaries

```mermaid
flowchart LR
    subgraph SAFE["Safe — Read-Only Zone"]
        direction TB
        SCAN["Azure Resource Graph scan\n(Reader role, indexed snapshot)"]
        TOOLS["EstateTools registry\n(list, neighbor, impact, findings only)"]
        MODEL["Azure OpenAI Responses API\n(store=false, bounded prompts)"]
        CRED["DefaultAzureCredential\n(CLI or managed identity — never in browser)"]
    end

    subgraph HUMAN["Human Approval Zone"]
        direction TB
        REVIEW["User reviews all outputs\nin the GENESIS UI"]
        ACK["Acknowledgement checkbox\nPOST /api/runs/{id}/approve"]
        DOWNLOAD["ZIP download enabled\nGET /api/runs/{id}/package"]
    end

    subgraph NEVER2["Explicitly Out of Scope"]
        direction TB
        NA["No terraform apply"]
        NB["No Azure write APIs"]
        NC["No auto-approve"]
        ND["No resource creation"]
        NE["No credential exposure\nto browser"]
    end

    SAFE --> HUMAN
    HUMAN -->|"Only after\nacknowledgement"| DOWNLOAD
    NEVER2 -. "blocked" .- SAFE
    NEVER2 -. "blocked" .- HUMAN
```

---

## Notes on Diagram Accuracy

- **Azure Resource Graph** is shown as optional because the full demo runs without Azure credentials using the fictional sample.
- **Azure OpenAI** is shown as optional because all agents have deterministic local fallbacks; the system is fully functional without a model deployment.
- **App Service hosting** is optional; the demo runs locally on `http://127.0.0.1:5173`.
- The **72 resources / 124 relationships / 5 modules / 21 findings** values are from the fictional `kyndryl-synthetic-estate.json` demo estate, not from a real Kyndryl or customer environment.
- The **1 critical finding** shown in the UI corresponds to a public inbound NSG rule in the fictional synthetic estate.
