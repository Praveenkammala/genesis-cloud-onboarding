"""Read-only Azure Resource Graph adapter."""

from __future__ import annotations

from typing import Any

from azure.identity import DefaultAzureCredential
from azure.mgmt.resourcegraph import ResourceGraphClient


RESOURCE_LIMIT = 1500
PAGE_SIZE = 1000


def _field(source: Any, name: str, default: Any = None) -> Any:
    if isinstance(source, dict):
        return source.get(name, default)
    return getattr(source, name, default)


def _resource_group_filter(value: str | None) -> str:
    if not value:
        return ""
    # The value is quoted as a Kusto string literal; doubling quotes prevents query injection.
    return f"| where resourceGroup =~ '{value.replace(chr(39), chr(39) * 2)}'"


def discover(subscription_id: str, resource_group: str | None = None) -> dict[str, Any]:
    """Query Azure Resource Graph and return the provider-neutral inventory schema."""
    credential = DefaultAzureCredential(exclude_interactive_browser_credential=True)
    client = ResourceGraphClient(credential=credential)
    query = """Resources
| project id, name, type, location, resourceGroup, subscriptionId, tags, properties, kind=tostring(kind), sku
| union (
    ResourceContainers
    | where type =~ 'microsoft.resources/subscriptions/resourcegroups'
    | project id, name, type, location, resourceGroup=name, subscriptionId, tags, properties, kind=tostring(''), sku=dynamic(null)
)
""" + _resource_group_filter(resource_group) + "\n| order by id asc"

    rows: list[dict[str, Any]] = []
    skip_token: str | None = None
    while True:
        options: dict[str, Any] = {"top": PAGE_SIZE}
        if skip_token:
            options["skip_token"] = skip_token
        response = client.resources(query={"query": query, "subscriptions": [subscription_id], "options": options})
        page = _field(response, "data", []) or []
        rows.extend(item for item in page if isinstance(item, dict))
        if len(rows) > RESOURCE_LIMIT:
            raise ValueError(f"Azure returned more than {RESOURCE_LIMIT} resources. Filter to a resource group and scan again.")
        skip_token = _field(response, "skip_token") or _field(response, "$skipToken")
        truncated = str(_field(response, "result_truncated", "false")).lower() == "true"
        if not skip_token:
            if truncated:
                raise ValueError("Azure Resource Graph returned a truncated result without a continuation token. Narrow the scan scope.")
            break

    if not rows:
        raise LookupError("No resources were returned. Check the subscription and Reader access, or choose another resource group.")

    direct_ids = {
        str(row.get("id") or "").strip().casefold()
        for row in rows if isinstance(row, dict) and row.get("id")
    }
    resources = []
    known_ids: set[str] = set()
    for row in rows:
        resource_id = str(row.get("id") or "").strip()
        resource_type = str(row.get("type") or "").strip()
        if not resource_id or not resource_type:
            continue
        if resource_id.casefold() in known_ids:
            continue
        known_ids.add(resource_id.casefold())
        properties = row.get("properties") if isinstance(row.get("properties"), dict) else {}
        resources.append({
            "id": resource_id,
            "type": resource_type,
            "name": row.get("name") or resource_id.rsplit("/", 1)[-1],
            "provider": "azure",
            "subscription_id": row.get("subscriptionId") or subscription_id,
            "resource_group": row.get("resourceGroup") or "",
            "region": row.get("location") or "unknown",
            "kind": row.get("kind"),
            "sku": row.get("sku"),
            "tags": row.get("tags") if isinstance(row.get("tags"), dict) else {},
            "properties": properties,
        })

        # ARG may return virtual-network subnets only inside the parent VNet's properties.
        # Flatten those child records so the explicit azurerm_subnet mapping can preserve them.
        if resource_type.lower() == "microsoft.network/virtualnetworks":
            subnets = properties.get("subnets", [])
            for subnet in subnets if isinstance(subnets, list) else []:
                if not isinstance(subnet, dict):
                    continue
                subnet_id = str(subnet.get("id") or "").strip()
                if not subnet_id or subnet_id.casefold() in direct_ids or subnet_id.casefold() in known_ids:
                    continue
                known_ids.add(subnet_id.casefold())
                subnet_props = subnet.get("properties") if isinstance(subnet.get("properties"), dict) else {}
                resources.append({
                    "id": subnet_id,
                    "type": "Microsoft.Network/virtualNetworks/subnets",
                    "name": subnet.get("name") or subnet_id.rsplit("/", 1)[-1],
                    "provider": "azure",
                    "subscription_id": row.get("subscriptionId") or subscription_id,
                    "resource_group": row.get("resourceGroup") or "",
                    "region": row.get("location") or "unknown",
                    "tags": {},
                    "properties": subnet_props,
                })

    if not resources:
        raise LookupError("Azure Resource Graph returned records without resource IDs and types.")
    locations = {str(row.get("region", "unknown")).lower() for row in resources}
    return {
        "name": f"Azure subscription {subscription_id} inventory",
        "provider": "azure",
        "region": next(iter(locations)) if len(locations) == 1 else "multiple",
        "subscription_id": subscription_id,
        "resources": resources,
        "relationships": [],
    }
