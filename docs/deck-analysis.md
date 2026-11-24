# Supplied deck analysis

The source PowerPoint contains eight slides. The project scope comes from the GENESIS cloud reverse-engineering brief:

- **Slide 1:** product summary and team details.
- **Slide 2:** problem context: undocumented, manually built AWS/Azure estates delay managed-services onboarding.
- **Slide 3:** proposed solution: read-only inventory, dependency graph, semantic grouping, Terraform generation, validation loop, and architect approval. It states an intended reduction from 2–3 months to 3–4 days.
- **Slide 4:** agent roles: Explorer, Architect, Strategist, Coder, Validator. GENESIS implements those specialists and adds a Review agent that selects evidence tools and prepares an approval checklist.
- **Slide 5:** the prose and diagram describe an ITSM workflow. That does not match the GENESIS cloud use case, so it is treated as a template fragment.
- **Slide 6:** proposed layers: cloud inventory, orchestration, model, data, dashboard, and Git output.
- **Slide 7:** 3 days, 100% IaC coverage, and 0 hours of manual detective work. Slide 8 says performance data is illustrative, so the UI presents onboarding time as a target and reports actual inventory mapping coverage separately.
- **Slide 8:** closing slide and illustrative-performance caveat.

The prototype implements the reviewable path in the brief while labeling model, inventory, and Terraform validation limits. Azure Resource Graph and AzureRM are the primary integration and Terraform output; AWS is retained as a secondary path. The Review agent uses Azure OpenAI tool calling when configured and a deterministic tool-selecting fallback otherwise. It cannot change cloud resources or approve Terraform.

Using 20 working days per month, the deck's 2–3 month baseline and 3–4 day target calculate to 40–60 versus 3–4 business days. That implies a scenario target of 90–95% less time (36–57 working days released per onboarding). This arithmetic is presented as an assumption-based target, not an observed POC result. The app reports actual run counts and analysis runtime so a timed pilot can gather evidence.

