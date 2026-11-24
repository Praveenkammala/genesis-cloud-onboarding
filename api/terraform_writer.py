"""Bounded, never-applied Terraform drafting for selected skipped Azure types."""

from __future__ import annotations

import json
import re
from typing import Any

from agentic_runtime import ModelBudget, model_is_configured, model_config, make_client, create_response


MAX_DRAFTS_PER_RUN = 2
MAX_REPAIR_RETRIES = 3
SUPPORTED_DRAFT_TYPES = {
    "microsoft.keyvault/vaults": "azurerm_key_vault",
    "microsoft.web/sites": "azurerm_linux_web_app",
}


def _output_schema() -> dict[str, Any]:
    return {"format": {"type": "json_schema", "name": "genesis_terraform_draft", "strict": True, "schema": {
        "type": "object", "properties": {"hcl": {"type": "string"}},
        "required": ["hcl"], "additionalProperties": False,
    }}}


def _strip_fences(hcl: str) -> str:
    value = hcl.strip()
    value = re.sub(r"^```(?:hcl|terraform)?\s*", "", value, flags=re.IGNORECASE)
    value = re.sub(r"\s*```$", "", value)
    return value.strip() + "\n"


def validate_hcl(hcl: str, expected_type: str, label: str) -> list[str]:
    """Check HCL delimiters and required arguments without claiming terraform validate."""
    errors: list[str] = []
    text = hcl.strip()
    escaped = False
    quoted = False
    stack: list[str] = []
    closing = {"}": "{", "]": "[", ")": "("}
    for char in text:
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
            continue
        if char == '"':
            quoted = True
        elif char in "{[(":
            stack.append(char)
        elif char in "}])":
            if not stack or stack.pop() != closing[char]:
                errors.append("Unbalanced HCL braces, brackets, or parentheses.")
                break
    if quoted or stack:
        errors.append("HCL has an unterminated string or unbalanced delimiter.")
    if re.search(r"\b(local-exec|remote-exec|provisioner|terraform\s*\{|data\s+\"external\")", text, re.IGNORECASE):
        errors.append("Draft contains an execution-capable or out-of-scope block.")
    block_pattern = rf'resource\s+"{re.escape(expected_type)}"\s+"{re.escape(label)}"\s*\{{'
    if not re.search(block_pattern, text):
        errors.append(f"Expected one resource block: {expected_type} {label}.")
    if len(re.findall(r"\bresource\s+\"", text)) != 1:
        errors.append("Draft must contain exactly one resource block.")
    required = {
        "azurerm_key_vault": ["name", "location", "resource_group_name", "tenant_id", "sku_name"],
        "azurerm_linux_web_app": ["name", "location", "resource_group_name", "service_plan_id", "site_config"],
    }.get(expected_type, [])
    for argument in required:
        if argument == "site_config":
            present = bool(re.search(r"\bsite_config\s*\{", text))
        else:
            present = bool(re.search(rf"^  {argument}\s*=", text, re.MULTILINE))
        if not present:
            errors.append(f"Required argument or block is missing: {argument}.")
    if not re.search(r"lifecycle\s*\{[^}]*prevent_destroy\s*=\s*true", text, re.DOTALL):
        errors.append("Lifecycle block must set prevent_destroy = true.")
    return list(dict.fromkeys(errors))


def _local_template(resource: dict[str, Any], terraform_type: str, label: str) -> str:
    props = resource.get("properties", {}) if isinstance(resource.get("properties"), dict) else {}
    tags = resource.get("tags", {}) if isinstance(resource.get("tags"), dict) else {}
    name = json.dumps(str(resource.get("name", "resource")), ensure_ascii=False)
    region = json.dumps(str(resource.get("region", "")), ensure_ascii=False)
    group = json.dumps(str(resource.get("resource_group", "")), ensure_ascii=False)
    lines = [f'resource "{terraform_type}" "{label}" {{', f"  name = {name}", f"  location = {region}", f"  resource_group_name = {group}"]
    if terraform_type == "azurerm_key_vault":
        tenant_id = props.get("tenantId", props.get("tenant_id"))
        sku = props.get("sku", {}) if isinstance(props.get("sku"), dict) else {}
        sku_name = sku.get("name", props.get("sku_name", "standard"))
        if tenant_id:
            lines.append(f"  tenant_id = {json.dumps(str(tenant_id))}")
        lines.append(f"  sku_name = {json.dumps(str(sku_name).lower())}")
        if isinstance(props.get("purgeProtectionEnabled"), bool):
            lines.append(f"  purge_protection_enabled = {str(props['purgeProtectionEnabled']).lower()}")
    elif terraform_type == "azurerm_linux_web_app":
        service_plan_id = props.get("serverFarmId", props.get("service_plan_id", ""))
        if service_plan_id:
            lines.append(f"  service_plan_id = {json.dumps(str(service_plan_id))}")
        if isinstance(props.get("httpsOnly"), bool):
            lines.append(f"  https_only = {str(props['httpsOnly']).lower()}")
        lines.append("  site_config {")
        lines.append("    always_on = true")
        lines.append("  }")
    if tags:
        lines.append("  tags = {")
        for key, value in sorted(tags.items()):
            if not any(token in str(key).lower() for token in ("secret", "password", "token", "key")):
                lines.append(f"    {json.dumps(str(key))} = {json.dumps(str(value))}")
        lines.append("  }")
    lines.extend(["", "  lifecycle {", "    prevent_destroy = true", "  }", "}"])
    return "\n".join(lines) + "\n"


def _model_draft(resource: dict[str, Any], terraform_type: str, label: str, previous_hcl: str, errors: list[str], budget: ModelBudget) -> str:
    endpoint, deployment = model_config()
    if not endpoint or not deployment:
        raise RuntimeError("No Azure OpenAI deployment is configured.")
    client = make_client(endpoint, budget)
    properties = resource.get("properties", {}) if isinstance(resource.get("properties"), dict) else {}
    safe_properties = {
        str(key): "[REDACTED]" if any(word in str(key).lower() for word in ("secret", "password", "token", "key", "connectionstring", "sas")) else value
        for key, value in list(properties.items())[:24]
    }
    prompt = {
        "task": "Draft one import-oriented AzureRM resource block. Do not emit variables, data sources, provisioners, or apply instructions.",
        "resource": {"id": resource.get("id"), "name": resource.get("name"), "type": resource.get("type"), "region": resource.get("region"), "resource_group": resource.get("resource_group"), "tags": resource.get("tags", {}), "properties": safe_properties},
        "required_type": terraform_type, "required_label": label,
        "previous_draft": previous_hcl, "validator_errors_to_fix": errors,
    }
    response = create_response(
        client, budget, max_output_tokens=700, model=deployment,
        input=[
            {"role": "system", "content": (
                "You are a Terraform draft writer for GENESIS. Return one AzureRM HCL resource block as JSON. "
                "Include all required arguments supported by the supplied inventory and lifecycle prevent_destroy = true. "
                "Never add provisioners, external data sources, credentials, or commands. If a required value is absent, leave it absent for validation to reject; do not invent it."
            )},
            {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
        ], text=_output_schema(),
    )
    payload = json.loads(response.output_text)
    return _strip_fences(str(payload.get("hcl", "")))


def write_skipped_resources(skipped: list[dict[str, Any]], resources_by_id: dict[str, dict[str, Any]], budget: ModelBudget) -> list[dict[str, Any]]:
    candidates = []
    seen_types = set()
    for item in skipped:
        mapped_type = SUPPORTED_DRAFT_TYPES.get(str(item.get("type", "")).casefold())
        if not mapped_type or mapped_type in seen_types:
            continue
        resource = resources_by_id.get(str(item.get("id", "")))
        if not resource:
            continue
        seen_types.add(mapped_type)
        candidates.append((item, resource, mapped_type))
        if len(candidates) >= MAX_DRAFTS_PER_RUN:
            break

    results = []
    for skipped_item, resource, terraform_type in candidates:
        label = str(resource.get("terraform_label", re.sub(r"[^A-Za-z0-9_]", "_", resource.get("name", "resource"))))
        hcl = ""
        errors: list[str] = []
        attempts = 0
        provenance = "local_template"
        use_model = model_is_configured()
        if use_model:
            provenance = "azure_openai"
            for attempt in range(MAX_REPAIR_RETRIES + 1):
                attempts += 1
                try:
                    hcl = _model_draft(resource, terraform_type, label, hcl, errors, budget)
                    errors = validate_hcl(hcl, terraform_type, label)
                except Exception as error:
                    errors = [f"Model draft request failed: {type(error).__name__}."]
                    break
                if not errors:
                    break
        else:
            hcl = _local_template(resource, terraform_type, label)
            errors = validate_hcl(hcl, terraform_type, label)
            attempts = 1

        status = "validated" if not errors else "unverified"
        results.append({
            "resource_id": str(resource.get("id", "")), "name": str(resource.get("name", "")),
            "source_type": str(resource.get("type", "")), "terraform_type": terraform_type,
            "label": label, "status": status, "provenance": provenance, "attempts": attempts,
            "validation": "local_syntax_and_required_arguments" if not errors else "failed_local_static_check",
            "errors": errors, "hcl": hcl,
        })
    return results
