"""Authentication boundary for local demos and Azure App Service deployments."""

from __future__ import annotations

import base64
import binascii
import json
import os
import re
from dataclasses import dataclass
from typing import Any

from fastapi import Header, HTTPException


@dataclass(frozen=True)
class Actor:
    """Authenticated owner used to scope discovery runs and their artifacts."""

    subject: str
    tenant_id: str
    clients: dict[str, dict[str, Any]]


def current_actor(
    client_principal: str | None = Header(default=None, alias="X-MS-CLIENT-PRINCIPAL"),
    identity_provider: str | None = Header(default=None, alias="X-MS-CLIENT-PRINCIPAL-IDP"),
) -> Actor:
    """Read the platform-verified Easy Auth principal, or allow local demo mode."""
    mode = os.getenv("GENESIS_AUTH_MODE", "local").strip().lower()
    if mode == "local":
        return Actor(subject="local-demo-user", tenant_id="local", clients={"demo": {"name": "Sample workspace", "azure_subscription_ids": [], "aws_account_ids": []}})
    if mode != "easy_auth":
        raise HTTPException(status_code=503, detail="GENESIS_AUTH_MODE is invalid; stateful API operations are disabled.")

    # This is a platform-owned, read-only setting. Requiring it prevents a
    # caller-supplied header from being treated as identity before Easy Auth is on.
    if os.getenv("WEBSITE_AUTH_ENABLED", "").strip().lower() != "true":
        raise HTTPException(status_code=503, detail="App Service Authentication is not enabled. Configure Microsoft Entra sign-in before using this deployment.")
    if identity_provider is None or identity_provider.strip().lower() != "aad":
        raise HTTPException(status_code=401, detail="Sign in with the configured company Microsoft Entra identity.")
    if not client_principal or len(client_principal) > 32_000:
        raise HTTPException(status_code=401, detail="An authenticated Microsoft Entra principal is required.")

    try:
        decoded = base64.b64decode(client_principal, validate=True)
        principal = json.loads(decoded.decode("utf-8"))
    except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise HTTPException(status_code=401, detail="The App Service identity header is invalid.") from error

    claims = principal.get("claims") if isinstance(principal, dict) else None
    if not isinstance(claims, list):
        raise HTTPException(status_code=401, detail="The App Service identity did not include claims.")

    values: dict[str, str] = {}
    for claim in claims:
        if not isinstance(claim, dict):
            continue
        claim_type = str(claim.get("typ", "")).strip().lower()
        short_type = claim_type.rsplit("/", 1)[-1].rsplit(":", 1)[-1]
        claim_value = str(claim.get("val", "")).strip()
        if short_type in {"tid", "tenantid"} and claim_value:
            values["tenant_id"] = claim_value
        elif short_type in {"oid", "objectidentifier"} and claim_value:
            values["object_id"] = claim_value

    allowed_tenant = os.getenv("GENESIS_ALLOWED_TENANT_ID", "").strip()
    tenant_id = values.get("tenant_id", "")
    object_id = values.get("object_id", "")
    if not allowed_tenant:
        raise HTTPException(status_code=503, detail="Set GENESIS_ALLOWED_TENANT_ID before enabling protected API operations.")
    if not tenant_id or tenant_id.casefold() != allowed_tenant.casefold():
        raise HTTPException(status_code=403, detail="This Microsoft Entra tenant is not allowed to use this GENESIS deployment.")
    if not object_id:
        raise HTTPException(status_code=401, detail="The authenticated principal has no stable object ID claim.")

    try:
        scope_map = json.loads(os.getenv("GENESIS_USER_SCOPES_JSON", "{}"))
    except json.JSONDecodeError as error:
        raise HTTPException(status_code=503, detail="GENESIS_USER_SCOPES_JSON is not valid JSON; protected operations are disabled.") from error
    if not isinstance(scope_map, dict):
        raise HTTPException(status_code=503, detail="GENESIS_USER_SCOPES_JSON must be an object keyed by employee object ID.")
    employee = next((value for key, value in scope_map.items() if str(key).casefold() == object_id.casefold()), None)
    if not isinstance(employee, dict):
        raise HTTPException(status_code=403, detail="Your account is authenticated but has no client cloud scopes assigned in GENESIS.")

    configured_clients = employee.get("clients")
    if not isinstance(configured_clients, dict) or not configured_clients:
        raise HTTPException(status_code=403, detail="Your account has no client workspaces assigned in GENESIS.")
    clients: dict[str, dict[str, Any]] = {}
    for client_id, client in configured_clients.items():
        normalized_id = str(client_id).strip().lower()
        if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,63}", normalized_id) or not isinstance(client, dict):
            raise HTTPException(status_code=503, detail="GENESIS_USER_SCOPES_JSON contains an invalid client workspace entry.")
        azure_scopes = client.get("azure_subscription_ids", [])
        azure_groups = client.get("azure_resource_groups", [])
        aws_scopes = client.get("aws_account_ids", [])
        if not isinstance(azure_scopes, list) or not isinstance(azure_groups, list) or not isinstance(aws_scopes, list):
            raise HTTPException(status_code=503, detail="Employee cloud scopes must be arrays in GENESIS_USER_SCOPES_JSON.")
        if any(not isinstance(item, str) or not item.strip() for item in azure_scopes + azure_groups + aws_scopes):
            raise HTTPException(status_code=503, detail="Employee cloud scope IDs must be non-empty strings.")
        clients[normalized_id] = {
            "name": str(client.get("name", normalized_id)).strip()[:100] or normalized_id,
            "azure_subscription_ids": [item.strip().casefold() for item in azure_scopes],
            "azure_resource_groups": [item.strip().strip("/").casefold() for item in azure_groups],
            "aws_account_ids": [item.strip() for item in aws_scopes],
        }

    return Actor(
        subject=f"{tenant_id.casefold()}:{object_id.casefold()}",
        tenant_id=tenant_id,
        clients=clients,
    )
