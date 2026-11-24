# GENESIS CloudLabs demo runbook

This runbook gets the existing project ready to demonstrate with the CloudLabs Azure hackathon environment while keeping Azure spend low.

## What the supplied screenshots show

- The CloudLabs guide describes an Azure sandbox with a pre-created Entra user and Owner access to a subscription. The screenshots do not show its subscription GUID or prove that any resources have been created.
- The Azure portal screenshot shows no recently viewed resources. That is not proof that the subscription is empty; use the supplied fictional inventory for a predictable demo.
- GitHub is managed by CloudLabs and the account is shown as a member of `CL-Labs-04`. The screenshot shows no repositories in the personal-account view. Switch to the organization before deciding whether a project repository already exists.

## Recommended: run the complete demo locally at no Azure hosting cost

The dashboard, analysis API, fictional Azure inventory, dependency graph, evidence-based Copilot, review findings, and Terraform ZIP generation run locally. This path creates no Azure resources and does not require Azure OpenAI.

Requirements: Windows PowerShell, Python 3.10 or newer, Node.js 18 or newer, and npm. The supplied project already includes a `.venv` and `node_modules`; recreate/install them only if they are missing or broken.

From PowerShell:

```powershell
cd C:\Users\numad\OneDrive\Desktop\hack\genesis
.\.venv\Scripts\Activate.ps1
npm run dev
```

If `.venv` does not exist, create and populate it before activation:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r api\requirements.txt
.\.venv\Scripts\Activate.ps1
npm ci
npm run dev
```

Keep that terminal open. Open `http://127.0.0.1:5173` in the browser. The API health page is `http://127.0.0.1:8000/api/health`; interactive API docs are at `http://127.0.0.1:8000/docs`.

If PowerShell blocks the activation script, do not change the machine's execution policy. In that terminal use the project interpreter directly for the API:

```powershell
.\.venv\Scripts\python.exe -m uvicorn main:app --app-dir api --reload --host 127.0.0.1 --port 8000
```

Then open a second PowerShell terminal, go to the project folder, and run `npm run web`. Keep both terminals open.

## Suggested presentation flow

1. Start on **Overview** and click **Run discovery** using the default fictional Azure inventory.
2. Open **Inventory** to show that individual cloud resources and their inferred module categories remain visible.
3. Open **Dependency graph** and select a node to explain its recorded relationships.
4. Open **Guardrails** and discuss the review findings. The sample intentionally flags a public inbound network rule and keeps one virtual machine in the skipped-resource list.
5. Open **Copilot** and ask a question grounded in the active run, such as “Which resources need manual Terraform mapping?” or “What should I review in the public inbound rule?” The default answer mode is local evidence retrieval and it displays citations.
6. Open **IaC package** to inspect the generated Terraform and audit files. Review the skipped-resource reasons and all HCL before using it elsewhere.
7. Acknowledge the human review gate only after inspecting the package, then download the ZIP. Do not run `terraform apply` from this demo.

One local sample run returned 9 resources, 15 inferred relationships, 4 suggested modules, 8 Terraform resource blocks (89% block coverage), 2 findings, and 1 skipped virtual machine. Those are measurements from the supplied fictional sample, not from the company subscription. Block coverage is not configuration parity or proof that an import plan is safe.

## Optional: read-only scan of the CloudLabs subscription

Use this only if the hackathon rules allow scanning the assigned subscription. It does not create Azure resources, but requires Azure CLI on the computer running the API and a signed-in identity with Reader access to the chosen scope. The screenshots do not include the subscription GUID.

1. In the Azure portal, open **Subscriptions**, select the CloudLabs sandbox subscription, and copy its **Subscription ID**. Do not share the ID or sign-in credentials publicly.
2. Install Azure CLI from Microsoft's official Windows instructions if it is not already installed. Open PowerShell and sign in with the CloudLabs Entra account:

   ```powershell
   az login
   az account set --subscription <subscription-guid>
   az account show --output table
   ```

3. Start GENESIS from the same PowerShell session after activating `.venv`, so the API can use the Azure CLI credential.
4. In GENESIS choose **Configure a read-only Azure scan**, enter the subscription GUID, optionally enter a resource group to narrow scope, and select **Run read-only scan**.
5. Start discovery after the resources are read. If the scan returns no resources, use the fictional sample for the demo; do not create resources just to make the dashboard look populated.

The scan uses Azure Resource Graph and is capped at 1,500 resources per run. Resource Graph is an indexed view and can lag recent changes. The connector is read-only. If `az` is not recognized, skip the live scan until Azure CLI is installed; the local sample workflow remains fully usable.

## Copilot scope

The current Copilot answers questions about evidence in the active cloud-estate run and cites that evidence. It is not an employee directory or an unrestricted cloud-architecture encyclopedia, and it will say when the run lacks evidence. It does not know company-specific architect biographies or policies unless that information is added as an approved knowledge source.

Azure OpenAI synthesis is optional and off by default. It requires an existing model deployment, permission to use it, and review of the organization's data-handling rules. Model use may consume credits. The sample review agent works without a model, so leave model settings empty for a no-model-cost presentation.

## GitHub organization setup

The project folder is not currently a Git repository and no GENESIS repository was visible in the CloudLabs organization view supplied. First sign in to the CloudLabs-managed GitHub account, open the `CL-Labs-04` organization, and check its repositories. If no project repository exists, ask the organization owner to create a private repository or create one there if your account is allowed to do so.

After a private repository has been created, run these commands from the `genesis` folder. Replace the remote URL if the organization assigned a different repository name:

```powershell
cd C:\Users\numad\OneDrive\Desktop\hack\genesis
git init -b main
git add .
git status --short
git commit -m "Initial GENESIS cloud blueprint studio"
git remote add origin https://github.com/CL-Labs-04/genesis-cloud-blueprint-studio.git
git push -u origin main
```

Review `git status --short` before committing. `.gitignore` excludes `.venv`, `node_modules`, `dist`, local environment files, Azure CLI cache, and Terraform state. Never commit cloud credentials, API keys, customer inventories, Terraform state, or real client resource details to a public repository.

## Optional: host the dashboard in Azure

The supplied `infra/deploy.ps1` creates a Linux App Service and defaults to a paid Basic B1 plan. It can consume the limited sandbox credits, and Azure credits are not a hard budget cap. For this hackathon, use the local presentation flow unless the team specifically requires a hosted URL and has checked the sandbox's remaining credit and regional pricing.

If hosting is approved, follow [infra/README.md](../infra/README.md) end to end. The script does not enable Entra sign-in or grant Reader access for you. Configure and verify authentication and the employee-to-scope map before assigning the app's managed identity Reader. The site is intended for a single App Service instance; run data is held in memory and is lost on restart.

When an approved hosted demo is finished, verify that the dedicated resource group contains only GENESIS demo resources, then remove that group using the teardown instructions in `infra/README.md`.
