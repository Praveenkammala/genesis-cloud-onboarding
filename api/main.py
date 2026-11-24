from __future__ import annotations

import json
import os
import re
import time
import uuid
import zipfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from agent_orchestrator import run_agentic_review
from agentic_runtime import ModelBudget, model_is_configured, probe_model
from auth import Actor, current_actor
from azure_provider import discover as discover_azure_resources
from azure_sample_inventory import AZURE_SAMPLE_INVENTORY
from azure_terraform import terraform_for_azure, terraform_type as azure_terraform_type
from estate_copilot import answer_estate_question
from investigator import run_investigator
from sample_inventory import SAMPLE_INVENTORY as AWS_SAMPLE_INVENTORY
from terraform_writer import write_skipped_resources


app = FastAPI(title="GENESIS Discovery API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SYNTHETIC_AZURE_INVENTORY = json.loads((PROJECT_ROOT / "samples" / "kyndryl-synthetic-estate.json").read_text(encoding="utf-8"))
FRONTEND_DIST = PROJECT_ROOT / "dist"
if (FRONTEND_DIST / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

RUNS: dict[str, dict[str, Any]] = {}
RUN_OWNERS: dict[str, str] = {}
RUN_CLIENTS: dict[str, str] = {}
MAX_RESOURCES = 1500

MODULES = {
    "network": "Network",
    "application": "Application",
    "data": "Data",
    "identity": "Identity",
    "supporting": "Supporting",
}

SUPPORTED_AWS_TYPES = {
    "aws_vpc",
    "aws_subnet",
    "aws_security_group",
    "aws_instance",
    "aws_lb",
    "aws_db_instance",
    "aws_db_subnet_group",
    "aws_s3_bucket",
}


def _text(value: Any, default: str = "") -> str:
    return str(value).strip() if value is not None else default


def _pick(source: dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if key in source and source[key] is not None:
            return source[key]
    return default


SENSITIVE_KEY_FRAGMENTS = (
    "password", "secret", "token", "accesskey", "sharedkey", "accountkey",
    "primarykey", "secondarykey", "privatekey", "connectionstring", "clientsecret", "sas",
)


def redact_sensitive(value: Any, parent_key: str = "") -> Any:
    """Remove common secret-shaped values before inventories are returned or packaged."""
    sensitive_parent = any(token in re.sub(r"[^a-z0-9]", "", parent_key.lower()) for token in ("appsettings", "connectionstrings", "clientsecrets"))
    if sensitive_parent:
        return "[REDACTED]"
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            normalized_key = re.sub(r"[^a-z0-9]", "", str(key).lower())
            if any(token in normalized_key for token in SENSITIVE_KEY_FRAGMENTS):
                result[key] = "[REDACTED]"
            else:
                result[key] = redact_sensitive(item, str(key))
        return result
    if isinstance(value, list):
        return [redact_sensitive(item, parent_key) for item in value]
    return value


def normalize_inventory(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("The inventory root must be a JSON object.")

    raw_resources = raw.get("resources", raw.get("Resources"))
    if not isinstance(raw_resources, list):
        raise ValueError("Expected a 'resources' array. See samples/inventory.json for the supported format.")
    if not raw_resources:
        raise ValueError("The inventory contains no resources.")
    if len(raw_resources) > MAX_RESOURCES:
        raise ValueError(f"This demo accepts up to {MAX_RESOURCES} resources per run.")

    account = raw.get("account") if isinstance(raw.get("account"), dict) else {}
    default_provider = _text(_pick(raw, "provider", default=_pick(account, "provider", default="aws"))).lower()
    name = _text(_pick(raw, "name", default=_pick(account, "name", default="Imported environment")))
    region = _text(_pick(raw, "region", default=_pick(account, "region", default="unknown"))).lower() or "unknown"
    subscription_id = _text(_pick(raw, "subscription_id", "subscriptionId", default=_pick(account, "subscription_id", "subscriptionId", default="")))
    account_id = _text(_pick(raw, "account_id", "accountId", default=_pick(account, "account_id", "accountId", "id", default="")))
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()

    for index, item in enumerate(raw_resources):
        if not isinstance(item, dict):
            raise ValueError(f"Resource at index {index} must be an object.")
        resource_id = _text(_pick(item, "id", "resourceId", "resource_id"))
        resource_type = _text(_pick(item, "type", "resourceType", "resource_type"))
        resource_name = _text(_pick(item, "name", "resourceName", "resource_name", default=resource_id))
        if not resource_id or not resource_type:
            raise ValueError(f"Resource at index {index} needs both 'id' and 'type'.")
        if resource_id.casefold() in seen:
            raise ValueError(f"Duplicate resource id: {resource_id}")
        seen.add(resource_id.casefold())
        properties = _pick(item, "properties", "configuration", default={})
        tags = item.get("tags", {})
        if not isinstance(properties, dict):
            properties = {}
        if not isinstance(tags, dict):
            tags = {}
        properties = dict(properties)
        if item.get("kind") is not None:
            properties.setdefault("kind", item["kind"])
        if item.get("sku") is not None:
            properties.setdefault("sku", item["sku"])
        provider = _text(item.get("provider"), "") or ("azure" if resource_type.lower().startswith("microsoft.") else default_provider.lower())
        location = _text(_pick(item, "region", "location"), region).lower() or region
        parsed_subscription = re.search(r"/subscriptions/([^/]+)", resource_id, re.IGNORECASE)
        parsed_group = re.search(r"/resourceGroups/([^/]+)", resource_id, re.IGNORECASE)
        parsed_aws_account = re.match(r"^arn:[^:]+:[^:]+:[^:]*:([0-9]{12}):", resource_id, re.IGNORECASE)
        normalized.append({
            "id": resource_id,
            "type": resource_type,
            "name": resource_name or resource_id,
            "provider": provider.lower(),
            "region": location,
            "resource_group": _text(_pick(item, "resource_group", "resourceGroup", default=parsed_group.group(1) if parsed_group else "")),
            "subscription_id": _text(_pick(item, "subscription_id", "subscriptionId", default=parsed_subscription.group(1) if parsed_subscription else subscription_id)),
            "account_id": _text(_pick(item, "account_id", "accountId", default=parsed_aws_account.group(1) if parsed_aws_account else account_id)),
            "tags": redact_sensitive(tags),
            "properties": redact_sensitive(properties),
        })

    known_regions = {item["region"] for item in normalized if item["region"] != "unknown"}
    if region == "unknown" and len(known_regions) == 1:
        region = next(iter(known_regions))
        for item in normalized:
            if item["region"] == "unknown":
                item["region"] = region

    known_subscriptions = {item["subscription_id"] for item in normalized if item["subscription_id"]}
    if not subscription_id and len(known_subscriptions) == 1:
        subscription_id = next(iter(known_subscriptions))
    known_accounts = {item["account_id"] for item in normalized if item["account_id"]}
    if not account_id and len(known_accounts) == 1:
        account_id = next(iter(known_accounts))

    providers = {item["provider"] for item in normalized}
    if len(providers) == 1:
        default_provider = next(iter(providers))

    id_lookup = {item["id"].casefold(): item["id"] for item in normalized}
    ids = set(id_lookup.values())
    relationships: list[dict[str, str]] = []
    edges_seen: set[tuple[str, str, str]] = set()

    def add_edge(source_id: Any, target_id: Any, relation: str) -> None:
        source = id_lookup.get(_text(source_id).casefold(), _text(source_id))
        target = id_lookup.get(_text(target_id).casefold(), _text(target_id))
        edge = (source, target, relation)
        if source in ids and target in ids and source != target and edge not in edges_seen:
            edges_seen.add(edge)
            relationships.append({"source": source, "target": target, "relation": relation})

    for edge in raw.get("relationships", raw.get("edges", [])):
        if isinstance(edge, dict):
            add_edge(
                _pick(edge, "source", "source_id", "from"),
                _pick(edge, "target", "target_id", "to"),
                _text(_pick(edge, "relation", "type", default="related_to")),
            )

    for resource in normalized:
        props = resource["properties"]
        resource_id = resource["id"]
        for key, relation in (
            ("vpc_id", "in_vpc"),
            ("vpcId", "in_vpc"),
            ("subnet_id", "in_subnet"),
            ("subnetId", "in_subnet"),
            ("db_subnet_group_id", "uses_subnet_group"),
            ("attached_to", "attached_to"),
        ):
            target_id = props.get(key)
            if isinstance(target_id, str):
                add_edge(resource_id, target_id, relation)
        for key, relation in (
            ("security_group_ids", "uses_security_group"),
            ("securityGroupIds", "uses_security_group"),
            ("subnet_ids", "uses_subnet"),
            ("subnetIds", "uses_subnet"),
            ("depends_on", "depends_on"),
        ):
            targets = props.get(key, [])
            if isinstance(targets, list):
                for target_id in targets:
                    add_edge(resource_id, target_id, relation)

        if resource["provider"] == "azure":
            def visit_ids(node: Any, path: tuple[str, ...] = ()) -> None:
                if isinstance(node, dict):
                    node_id = node.get("id")
                    if isinstance(node_id, str):
                        words = " ".join(path).lower()
                        relation = "uses_subnet" if "subnet" in words else "uses_network_security_group" if "securitygroup" in words else "uses_public_ip" if "publicip" in words else "attached_to" if "networkinterface" in words else "in_virtual_network" if "virtualnetwork" in words else "references"
                        add_edge(resource_id, node_id, relation)
                    for key, value in node.items():
                        visit_ids(value, path + (str(key),))
                elif isinstance(node, list):
                    for value in node:
                        visit_ids(value, path)

            visit_ids(props)

            path_parts = resource_id.split("/")
            for index in range(1, len(path_parts)):
                parent_id = "/".join(path_parts[:index])
                parent = id_lookup.get(parent_id.casefold())
                if parent:
                    target_resource = next((item for item in normalized if item["id"] == parent), None)
                    parent_type = str(target_resource.get("type", "")).lower() if target_resource else ""
                    relation = "in_resource_group" if "resourcegroups" in parent_type else "in_virtual_network" if "virtualnetworks" in parent_type else "child_resource"
                    add_edge(resource_id, parent, relation)

    return {
        "name": name,
        "provider": default_provider,
        "region": region,
        "subscription_id": subscription_id,
        "account_id": account_id,
        "resources": normalized,
        "relationships": relationships,
        "synthetic": bool(raw.get("synthetic", False)),
        "notice": _text(raw.get("notice")),
    }


def classify(resource: dict[str, Any]) -> str:
    text = f"{resource['type']} {resource['name']}".lower()
    if "resourcegroups" in text:
        return "supporting"
    # AWS DB subnet groups are database placement metadata, not VPC subnet resources.
    if "db_subnet_group" in text:
        return "data"
    if any(word in text for word in ("vpc", "subnet", "security_group", "route_table", "internet_gateway", "nat_gateway", "network")):
        return "network"
    if any(word in text for word in ("rds", "database", "db_instance", "dynamodb", "s3_bucket", "storage", "bucket", "redis")):
        return "data"
    if any(word in text for word in ("iam", "role", "policy", "identity", "key_vault")):
        return "identity"
    if any(word in text for word in ("instance", "load_balancer", "aws_lb", "asg", "autoscaling", "vm", "virtualmachine", "compute", "web", "app_service")):
        return "application"
    return "supporting"


def safe_label(value: str) -> str:
    label = re.sub(r"[^a-zA-Z0-9_]", "_", value.strip().lower())
    label = re.sub(r"_+", "_", label).strip("_") or "resource"
    if label[0].isdigit():
        label = f"r_{label}"
    return label[:55]


def hcl_string(value: Any) -> str:
    return json.dumps(str(value), ensure_ascii=False)


def hcl_tags(tags: dict[str, Any], name: str) -> str:
    values = {str(k): str(v) for k, v in tags.items() if v is not None and str(k).lower() not in {"password", "secret", "token", "access_key"}}
    values.setdefault("Name", name)
    lines = [f"    {hcl_string(key)} = {hcl_string(value)}" for key, value in sorted(values.items())]
    return "tags = {\n" + "\n".join(lines) + "\n  }"


def hcl_bool(value: Any) -> str | None:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str) and value.lower() in {"true", "false"}:
        return value.lower()
    return None


def value(props: dict[str, Any], *keys: str, default: Any = None) -> Any:
    return _pick(props, *keys, default=default)


def terraform_for(resource: dict[str, Any], label: str) -> tuple[str | None, str | None]:
    resource_type = resource["type"].lower()
    props = resource["properties"]
    name = resource["name"]
    tags = resource["tags"]
    lines: list[str] = []

    if resource_type == "aws_vpc":
        cidr = value(props, "cidr_block", "cidrBlock")
        if not cidr:
            return None, "Missing CIDR block"
        lines += [f"  cidr_block = {hcl_string(cidr)}"]
        for source, target in (("enable_dns_support", "enable_dns_support"), ("enable_dns_hostnames", "enable_dns_hostnames")):
            flag = hcl_bool(props.get(source))
            if flag is not None:
                lines.append(f"  {target} = {flag}")

    elif resource_type == "aws_subnet":
        vpc_id = value(props, "vpc_id", "vpcId")
        cidr = value(props, "cidr_block", "cidrBlock")
        if not vpc_id or not cidr:
            return None, "Missing VPC id or CIDR block"
        lines += [f"  vpc_id = {hcl_string(vpc_id)}", f"  cidr_block = {hcl_string(cidr)}"]
        zone = value(props, "availability_zone", "availabilityZone")
        if zone:
            lines.append(f"  availability_zone = {hcl_string(zone)}")
        flag = hcl_bool(value(props, "map_public_ip_on_launch", "mapPublicIpOnLaunch"))
        if flag is not None:
            lines.append(f"  map_public_ip_on_launch = {flag}")

    elif resource_type == "aws_security_group":
        vpc_id = value(props, "vpc_id", "vpcId")
        if not vpc_id:
            return None, "Missing VPC id"
        group_name = value(props, "group_name", "groupName", default=name)
        description = value(props, "description", default=f"Imported security group {name}")
        lines += [f"  name = {hcl_string(group_name)}", f"  description = {hcl_string(description)}", f"  vpc_id = {hcl_string(vpc_id)}"]
        for direction in ("ingress", "egress"):
            rules = value(props, direction, f"{direction}_rules", default=[])
            if not isinstance(rules, list):
                continue
            for rule in rules:
                if not isinstance(rule, dict):
                    continue
                from_port = value(rule, "from_port", "fromPort")
                to_port = value(rule, "to_port", "toPort")
                protocol = _text(value(rule, "protocol", default="-1"), "-1")
                # AWS uses protocol -1 for all traffic; the provider requires 0/0.
                if protocol == "-1":
                    from_port = 0
                    to_port = 0
                elif from_port is None or to_port is None:
                    return None, f"Incomplete {direction} rule port range"
                cidrs = value(rule, "cidr_blocks", "cidrBlocks", default=[])
                ipv6 = value(rule, "ipv6_cidr_blocks", "ipv6Ranges", default=[])
                prefix_lists = value(rule, "prefix_list_ids", "prefixListIds", default=[])
                groups = value(rule, "security_groups", "source_security_group_ids", default=[])
                self_source = value(rule, "self", default=False) is True
                if any(not isinstance(items, list) for items in (cidrs, ipv6, prefix_lists, groups)):
                    return None, f"Invalid {direction} rule source list"
                if not any((cidrs, ipv6, prefix_lists, groups, self_source)):
                    return None, f"Unsupported {direction} rule source"
                lines.append(f"  {direction} {{")
                lines.append(f"    from_port = {int(from_port)}")
                lines.append(f"    to_port = {int(to_port)}")
                lines.append(f"    protocol = {hcl_string(protocol)}")
                if isinstance(cidrs, list) and cidrs:
                    lines.append("    cidr_blocks = [" + ", ".join(hcl_string(cidr) for cidr in cidrs) + "]")
                if isinstance(ipv6, list) and ipv6:
                    lines.append("    ipv6_cidr_blocks = [" + ", ".join(hcl_string(cidr) for cidr in ipv6) + "]")
                if isinstance(prefix_lists, list) and prefix_lists:
                    lines.append("    prefix_list_ids = [" + ", ".join(hcl_string(item) for item in prefix_lists) + "]")
                if isinstance(groups, list) and groups:
                    lines.append("    security_groups = [" + ", ".join(hcl_string(item) for item in groups) + "]")
                if self_source:
                    lines.append("    self = true")
                lines.append("  }")

    elif resource_type == "aws_instance":
        ami = value(props, "ami", "image_id", "imageId")
        instance_type = value(props, "instance_type", "instanceType")
        if not ami or not instance_type:
            return None, "Missing AMI or instance type"
        lines += [f"  ami = {hcl_string(ami)}", f"  instance_type = {hcl_string(instance_type)}"]
        subnet_id = value(props, "subnet_id", "subnetId")
        if subnet_id:
            lines.append(f"  subnet_id = {hcl_string(subnet_id)}")
        groups = value(props, "security_group_ids", "securityGroupIds", default=[])
        if isinstance(groups, list) and groups:
            lines.append("  vpc_security_group_ids = [" + ", ".join(hcl_string(item) for item in groups) + "]")
        for source, target in (("associate_public_ip_address", "associate_public_ip_address"), ("disable_api_termination", "disable_api_termination")):
            flag = hcl_bool(value(props, source, source.replace("_", "")))
            if flag is not None:
                lines.append(f"  {target} = {flag}")

    elif resource_type == "aws_lb":
        lb_name = value(props, "lb_name", "load_balancer_name", "name", default=name)
        lb_type = value(props, "load_balancer_type", "type", default="application")
        subnets = value(props, "subnet_ids", "subnets", "availability_zones", default=[])
        if not lb_name or not isinstance(subnets, list) or not subnets:
            return None, "Missing load balancer name or subnet ids"
        lines += [f"  name = {hcl_string(lb_name)}", f"  load_balancer_type = {hcl_string(lb_type)}", "  subnets = [" + ", ".join(hcl_string(item) for item in subnets) + "]"]
        groups = value(props, "security_group_ids", "security_groups", default=[])
        if isinstance(groups, list) and groups:
            lines.append("  security_groups = [" + ", ".join(hcl_string(item) for item in groups) + "]")
        flag = hcl_bool(value(props, "internal"))
        if flag is not None:
            lines.append(f"  internal = {flag}")

    elif resource_type == "aws_db_instance":
        identifier = value(props, "identifier", default=name)
        engine = value(props, "engine")
        instance_class = value(props, "instance_class", "db_instance_class")
        if not identifier or not engine or not instance_class:
            return None, "Missing DB identifier, engine, or instance class"
        lines += [f"  identifier = {hcl_string(identifier)}", f"  engine = {hcl_string(engine)}", f"  instance_class = {hcl_string(instance_class)}"]
        for source, target in (("allocated_storage", "allocated_storage"), ("storage_encrypted", "storage_encrypted"), ("publicly_accessible", "publicly_accessible"), ("deletion_protection", "deletion_protection")):
            setting = props.get(source)
            if source == "allocated_storage" and setting is not None:
                lines.append(f"  allocated_storage = {int(setting)}")
            elif source != "allocated_storage":
                flag = hcl_bool(setting)
                if flag is not None:
                    lines.append(f"  {target} = {flag}")
        subnet_group = value(props, "db_subnet_group_name", "db_subnet_group")
        if subnet_group:
            lines.append(f"  db_subnet_group_name = {hcl_string(subnet_group)}")
        groups = value(props, "vpc_security_group_ids", "security_group_ids", default=[])
        if isinstance(groups, list) and groups:
            lines.append("  vpc_security_group_ids = [" + ", ".join(hcl_string(item) for item in groups) + "]")
        username = value(props, "username", "master_username")
        if username:
            lines.append(f"  username = {hcl_string(username)}")

    elif resource_type == "aws_db_subnet_group":
        group_name = value(props, "name", "db_subnet_group_name", default=name)
        subnet_ids = value(props, "subnet_ids", "subnetIds", default=[])
        if not group_name or not isinstance(subnet_ids, list) or not subnet_ids:
            return None, "Missing DB subnet group name or subnet ids"
        lines += [f"  name = {hcl_string(group_name)}", "  subnet_ids = [" + ", ".join(hcl_string(item) for item in subnet_ids) + "]"]
        description = value(props, "description")
        if description:
            lines.append(f"  description = {hcl_string(description)}")

    elif resource_type == "aws_s3_bucket":
        bucket = value(props, "bucket", "bucket_name", default=name)
        if not bucket:
            return None, "Missing bucket name"
        lines.append(f"  bucket = {hcl_string(bucket)}")

    else:
        return None, "No Terraform mapping for this resource type"

    lines.append("  " + hcl_tags(tags, name).replace("\n", "\n  "))
    body = f'resource "{resource_type}" "{label}" {{\n' + "\n".join(lines) + "\n\n  lifecycle {\n    prevent_destroy = true\n  }\n}\n"
    return body, None


def terraform_type_for(resource: dict[str, Any]) -> str | None:
    if resource["provider"] == "azure":
        return azure_terraform_type(resource)
    if resource["provider"] == "aws" and resource["type"].lower() in SUPPORTED_AWS_TYPES:
        return resource["type"].lower()
    return None


def terraform_for_provider(resource: dict[str, Any], label: str) -> tuple[str | None, str | None]:
    if resource["provider"] == "azure":
        return terraform_for_azure(resource, label)
    return terraform_for(resource, label)


def build_findings(resources: list[dict[str, Any]]) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    for resource in resources:
        props = resource["properties"]
        resource_type = resource["type"].lower()
        resource_name = resource["name"]
        rid = resource["id"]
        tags = resource.get("tags", {})

        if not tags or not any(str(key).casefold() == "owner" for key in tags):
            findings.append({"id": f"missing-owner-{rid}", "severity": "low", "title": "Ownership metadata is incomplete", "resource": resource_name, "resource_id": rid, "detail": "The inventory has no owner tag. Confirm the accountable service owner before handing this resource into managed operations."})

        if resource_type == "aws_security_group":
            for rule in value(props, "ingress", "ingress_rules", default=[]):
                if not isinstance(rule, dict):
                    continue
                cidrs = value(rule, "cidr_blocks", "cidrBlocks", default=[])
                ipv6 = value(rule, "ipv6_cidr_blocks", "ipv6Ranges", default=[])
                port = value(rule, "from_port", "fromPort")
                if "0.0.0.0/0" in cidrs or "::/0" in ipv6:
                    high_risk_port = port in {22, 3389, -1} or (value(rule, "to_port", "toPort") == 65535 and port == 0)
                    severity = "critical" if high_risk_port else "high"
                    findings.append({"id": f"public-{rid}-{port}", "severity": severity, "title": "Public inbound access", "resource": resource_name, "detail": f"An inbound rule exposes port {port if port is not None else 'all'} to the internet. Confirm the intended access boundary before adopting this rule."})

        if resource_type == "aws_db_instance":
            if hcl_bool(props.get("publicly_accessible")) == "true":
                findings.append({"id": f"public-db-{rid}", "severity": "critical", "title": "Public database endpoint", "resource": resource_name, "detail": "The database is marked publicly accessible. Confirm network controls and business need before adoption."})
            if hcl_bool(props.get("storage_encrypted")) == "false":
                findings.append({"id": f"unencrypted-db-{rid}", "severity": "high", "title": "Database storage encryption is off", "resource": resource_name, "detail": "Storage encryption is disabled in the supplied inventory."})

        if resource_type == "aws_s3_bucket":
            if props.get("public_access_block") is False or props.get("block_public_access") is False:
                findings.append({"id": f"public-bucket-{rid}", "severity": "critical", "title": "Bucket public access is not blocked", "resource": resource_name, "detail": "The inventory reports public access controls as disabled."})
            if props.get("encryption_enabled") is False:
                findings.append({"id": f"unencrypted-bucket-{rid}", "severity": "medium", "title": "No default encryption configuration reported", "resource": resource_name, "detail": "The supplied inventory reports no bucket-level default encryption configuration. Confirm the effective encryption behavior and any account-level controls."})

        if resource_type == "microsoft.network/networksecuritygroups":
            rules = _pick(props, "securityRules", "security_rules", default=[])
            for rule in rules if isinstance(rules, list) else []:
                if not isinstance(rule, dict):
                    continue
                nested = rule.get("properties")
                rule_props = nested if isinstance(nested, dict) else rule
                if _text(_pick(rule_props, "direction"), "").lower() != "inbound" or _text(_pick(rule_props, "access"), "").lower() != "allow":
                    continue
                sources = [_pick(rule_props, "sourceAddressPrefix", "source_address_prefix", default="")]
                sources.extend(_pick(rule_props, "sourceAddressPrefixes", "source_address_prefixes", default=[]) or [])
                public_source = any(str(source).lower() in {"*", "internet", "0.0.0.0/0", "::/0"} for source in sources)
                if not public_source:
                    continue
                ports = [_pick(rule_props, "destinationPortRange", "destination_port_range", default="")]
                ports.extend(_pick(rule_props, "destinationPortRanges", "destination_port_ranges", default=[]) or [])
                high_risk = any(str(port) in {"22", "3389", "*"} for port in ports)
                rule_name = _text(_pick(rule, "name", default=_pick(rule_props, "name", default="inbound rule")))
                findings.append({"id": f"azure-public-{rid}-{rule_name}", "severity": "critical" if high_risk else "high", "title": "Public inbound network rule", "resource": resource_name, "detail": f"The inbound allow rule '{rule_name}' accepts traffic from a public source. Review the exposed destination ports before adopting this rule."})

        if resource_type == "microsoft.storage/storageaccounts":
            if props.get("allowBlobPublicAccess") is True:
                findings.append({"id": f"azure-public-storage-{rid}", "severity": "high", "title": "Storage account allows public blob access", "resource": resource_name, "detail": "The inventory reports blob-level anonymous access as enabled. Confirm the intended access boundary."})
            if props.get("minimumTlsVersion") in {"TLS1_0", "TLS1_1"}:
                findings.append({"id": f"azure-tls-{rid}", "severity": "high", "title": "Storage account uses an older TLS minimum", "resource": resource_name, "detail": "The inventory reports a minimum TLS version below TLS 1.2."})

        if resource_type == "microsoft.keyvault/vaults":
            network_acls = props.get("networkAcls", {}) if isinstance(props.get("networkAcls"), dict) else {}
            if str(network_acls.get("defaultAction", "")).casefold() == "allow":
                findings.append({"id": f"azure-keyvault-network-{rid}", "severity": "high", "title": "Key Vault network default allows access", "resource": resource_name, "resource_id": rid, "detail": "The inventory reports the Key Vault network ACL default action as Allow. Confirm whether private network restrictions are required."})

        if resource_type == "microsoft.sql/servers" and str(props.get("publicNetworkAccess", "")).casefold() == "enabled":
            findings.append({"id": f"azure-sql-public-{rid}", "severity": "high", "title": "SQL server public network access is enabled", "resource": resource_name, "resource_id": rid, "detail": "The inventory reports public network access as enabled. Confirm firewall rules and the approved connectivity path."})

        if resource_type == "microsoft.web/sites":
            site_config = props.get("siteConfig", {}) if isinstance(props.get("siteConfig"), dict) else {}
            if props.get("httpsOnly") is False or str(site_config.get("minTlsVersion", "")).casefold() in {"1.0", "1.1"}:
                findings.append({"id": f"azure-appservice-transport-{rid}", "severity": "high", "title": "App Service transport controls need review", "resource": resource_name, "resource_id": rid, "detail": "The inventory reports HTTPS-only disabled or a TLS version below 1.2."})

    return findings


def terraform_type_for(resource: dict[str, Any]) -> str | None:
    if resource["provider"] == "azure":
        return azure_terraform_type(resource)
    if resource["provider"] == "aws" and resource["type"].lower() in SUPPORTED_AWS_TYPES:
        return resource["type"].lower()
    return None


def terraform_for_provider(resource: dict[str, Any], label: str) -> tuple[str | None, str | None]:
    if resource["provider"] == "azure":
        return terraform_for_azure(resource, label)
    return terraform_for(resource, label)


def _client_access(actor: Actor, client_id: str) -> dict[str, Any]:
    normalized_id = client_id.strip().lower()
    access = actor.clients.get(normalized_id)
    if not access:
        raise HTTPException(status_code=403, detail="This employee is not assigned to the requested client workspace.")
    return access


def _require_cloud_scope(actor: Actor, client_id: str, provider: str, scope_id: str, resource_group: str = "") -> None:
    access = _client_access(actor, client_id)
    if actor.tenant_id == "local":
        return
    normalized_scope = scope_id.strip().casefold() if provider == "azure" else scope_id.strip()
    if not normalized_scope:
        raise HTTPException(status_code=403, detail=f"This {provider.upper()} resource has no account scope. Add its scope ID to the employee's access map.")
    if provider == "azure":
        allowed_subscriptions = set(access.get("azure_subscription_ids", []))
        if normalized_scope in allowed_subscriptions:
            return
        if resource_group:
            normalized_group = resource_group.strip().strip("/").casefold()
            group_scopes = set(access.get("azure_resource_groups", []))
            if f"{normalized_scope}/{normalized_group}" in group_scopes:
                return
        raise HTTPException(status_code=403, detail="Your GENESIS access map does not include this Azure subscription or resource group.")
    allowed_accounts = set(access.get("aws_account_ids", [])) if provider == "aws" else set()
    if normalized_scope not in allowed_accounts:
        raise HTTPException(status_code=403, detail=f"Your GENESIS access map does not include this {provider.upper()} scope.")


def _require_inventory_scopes(inventory: dict[str, Any], actor: Actor, client_id: str) -> None:
    if actor.tenant_id == "local":
        return
    resources = inventory.get("resources", [])
    providers = {str(item.get("provider", "")).lower() for item in resources}
    for provider in providers:
        scope_key = "subscription_id" if provider == "azure" else "account_id" if provider == "aws" else ""
        if not scope_key:
            raise HTTPException(status_code=403, detail="This provider is not enabled for protected inventory runs.")
        scopes = {str(item.get(scope_key) or inventory.get(scope_key) or "").strip() for item in resources if item.get("provider") == provider}
        if not scopes or "" in scopes:
            raise HTTPException(status_code=403, detail=f"Every {provider.upper()} resource must include a cloud scope ID.")
        if provider == "azure":
            scoped_groups = {
                (str(item.get("subscription_id") or inventory.get("subscription_id") or "").strip(), str(item.get("resource_group") or "").strip())
                for item in resources if item.get("provider") == "azure"
            }
            for subscription_id, resource_group in scoped_groups:
                _require_cloud_scope(actor, client_id, provider, subscription_id, resource_group)
        else:
            for scope in scopes:
                _require_cloud_scope(actor, client_id, provider, scope)


def analyze_inventory(raw: Any, owner_id: str = "local-demo-user", actor: Actor | None = None, client_id: str = "demo") -> dict[str, Any]:
    started_at = time.perf_counter()
    inventory = normalize_inventory(raw)
    is_builtin_demo = raw == AZURE_SAMPLE_INVENTORY or raw == AWS_SAMPLE_INVENTORY or raw == SYNTHETIC_AZURE_INVENTORY
    if actor is not None and not is_builtin_demo:
        _require_inventory_scopes(inventory, actor, client_id)
    client_access = _client_access(actor, client_id) if actor is not None else {"name": "Sample workspace"}
    inventory["client_id"] = client_id
    inventory["client_name"] = client_access.get("name", client_id)
    resources = inventory["resources"]
    by_id = {item["id"]: item for item in resources}
    modules: dict[str, list[dict[str, Any]]] = {key: [] for key in MODULES}
    addresses: dict[str, tuple[str, str]] = {}
    module_labels: dict[str, str] = {}
    name_counts: Counter[str] = Counter()
    generated: dict[str, list[str]] = defaultdict(list)
    skipped: list[dict[str, str]] = []

    for resource in resources:
        category = classify(resource)
        resource["module"] = category
        modules[category].append(resource)
        module_labels.setdefault(category, safe_label(category))
        label_base = safe_label(resource["name"])
        name_key = f"{resource['type']}:{label_base}"
        name_counts[name_key] += 1
        label = label_base if name_counts[name_key] == 1 else f"{label_base}_{name_counts[name_key]}"
        resource["terraform_label"] = label

        generated_type = terraform_type_for(resource)
        if not generated_type:
            skipped.append({"id": resource["id"], "name": resource["name"], "type": resource["type"], "reason": "Terraform mapping is not implemented for this resource/provider"})
            continue
        if resource["provider"] == "aws":
            if inventory["region"] == "unknown" or resource["region"] == "unknown":
                skipped.append({"id": resource["id"], "name": resource["name"], "type": resource["type"], "reason": "AWS region is unknown; set a single region before generating provider configuration"})
                continue
            if resource["region"] != inventory["region"]:
                skipped.append({"id": resource["id"], "name": resource["name"], "type": resource["type"], "reason": f"Resource region {resource['region']} differs from package region {inventory['region']}"})
                continue
        if resource["provider"] == "azure":
            if not inventory["subscription_id"] or not resource["subscription_id"]:
                skipped.append({"id": resource["id"], "name": resource["name"], "type": resource["type"], "reason": "Azure subscription ID is unknown; set a subscription before generating provider configuration"})
                continue
            if resource["subscription_id"].casefold() != inventory["subscription_id"].casefold():
                skipped.append({"id": resource["id"], "name": resource["name"], "type": resource["type"], "reason": "Resource subscription differs from the package subscription"})
                continue
        hcl, reason = terraform_for_provider(resource, label)
        if not hcl:
            skipped.append({"id": resource["id"], "name": resource["name"], "type": resource["type"], "reason": reason or "Insufficient configuration"})
            continue
        category_label = module_labels[category]
        addresses[resource["id"]] = (category_label, f"{generated_type}.{label}")
        generated[category_label].append(hcl)

    baseline_terraform_resources = len(addresses)
    coverage_before = round((baseline_terraform_resources / len(resources)) * 100) if resources else 0
    terraform_types_before = len({address.split(".", 1)[0] for _, address in addresses.values()})
    orphan_refs = []
    raw_relationships = raw.get("relationships", raw.get("edges", [])) if isinstance(raw, dict) else []
    for edge in raw_relationships if isinstance(raw_relationships, list) else []:
        if isinstance(edge, dict):
            source = _text(_pick(edge, "source", "source_id", "from"))
            target = _text(_pick(edge, "target", "target_id", "to"))
            if source not in by_id or target not in by_id:
                orphan_refs.append({"source": source, "target": target})

    findings = build_findings(resources)
    if orphan_refs:
        findings.append({"id": "orphan-reference", "severity": "medium", "title": "Unresolved relationship references", "resource": "Inventory", "detail": f"{len(orphan_refs)} supplied relationship(s) point to resources absent from the inventory."})
    resources_by_name: dict[str, dict[str, Any]] = {}
    for resource in resources:
        resources_by_name.setdefault(resource["name"].casefold(), resource)
    for finding in findings:
        if not finding.get("resource_id"):
            matching_resource = resources_by_name.get(str(finding.get("resource", "")).casefold())
            if matching_resource:
                finding["resource_id"] = matching_resource["id"]

    model_budget = ModelBudget()
    investigation = run_investigator(inventory, findings, model_budget, skipped)
    terraform_drafts = write_skipped_resources(skipped, by_id, model_budget)
    for draft in terraform_drafts:
        resource = by_id[draft["resource_id"]]
        resource["terraform_writer"] = {
            "status": draft["status"], "provenance": draft["provenance"],
            "terraform_type": draft["terraform_type"], "validation": draft["validation"],
        }
        skipped_record = next((item for item in skipped if item.get("id") == draft["resource_id"]), None)
        if draft["status"] == "validated":
            if skipped_record:
                skipped.remove(skipped_record)
            category_label = module_labels.get(resource["module"], safe_label(resource["module"]))
            addresses[resource["id"]] = (category_label, f"{draft['terraform_type']}.{draft['label']}")
            provenance_label = "AI-writer" if draft["provenance"] == "azure_openai" else "Local template"
            generated[category_label].append(f"# {provenance_label} · {draft['status']} by GENESIS static checks\n" + draft["hcl"])
        elif skipped_record:
            skipped_record["writer_status"] = "unverified"
            skipped_record["reason"] = f"Terraform writer could not verify this draft: {'; '.join(draft['errors']) or skipped_record['reason']}"

    if skipped:
        findings.append({"id": "partial-coverage", "severity": "medium", "title": "Some resources need manual mapping", "resource": "IaC package", "detail": f"{len(skipped)} of {len(resources)} resources are not emitted as validated Terraform. Review the skipped-resource manifest before treating coverage as complete."})

    files: dict[str, str] = {}
    root_modules: list[str] = []
    imports: list[str] = []
    for category_label, blocks in generated.items():
        module_path = f"modules/{category_label}"
        files[f"{module_path}/main.tf"] = "# Generated from the supplied inventory. Review every field before adoption.\n\n" + "\n".join(blocks)
        root_modules.append(f'module "{category_label}" {{\n  source = "./{module_path}"\n}}')

    for resource in resources:
        address = addresses.get(resource["id"])
        if address:
            module_name, resource_address = address
            imports.append(f"import {{\n  to = module.{module_name}.{resource_address}\n  id = {hcl_string(resource['id'])}\n}}")

    used_providers = sorted({by_id[resource_id]["provider"] for resource_id in addresses})
    provider_requirements: list[str] = []
    provider_config: list[str] = []
    tfvars: list[str] = []
    if "aws" in used_providers:
        provider_requirements.append('    aws = {\n      source  = "hashicorp/aws"\n      version = ">= 5.0, < 7.0"\n    }')
        provider_config.extend([
            'variable "aws_region" {\n  description = "AWS region for the imported environment"\n  type        = string\n}',
            'provider "aws" {\n  region = var.aws_region\n}',
        ])
        tfvars.append(f'aws_region = {hcl_string(inventory["region"] if inventory["region"] != "unknown" else "REPLACE_WITH_AWS_REGION")}')
    if "azure" in used_providers:
        provider_requirements.append('    azurerm = {\n      source  = "hashicorp/azurerm"\n      version = ">= 5.5, < 6.0"\n    }')
        provider_config.extend([
            'variable "azure_subscription_id" {\n  description = "Azure subscription that contains the imported resources"\n  type        = string\n}',
            'provider "azurerm" {\n  features {}\n  subscription_id = var.azure_subscription_id\n}',
        ])
        tfvars.append(f'azure_subscription_id = {hcl_string(inventory["subscription_id"] or "REPLACE_WITH_AZURE_SUBSCRIPTION_ID")}')
    files["versions.tf"] = (
        'terraform {\n  required_version = ">= 1.5.0"\n\n  required_providers {\n'
        + "\n".join(provider_requirements)
        + "\n  }\n}\n\n"
        + "\n\n".join(provider_config)
        + "\n"
    )
    files["main.tf"] = "# Generated by GENESIS. No infrastructure changes are applied by this tool.\n\n" + "\n\n".join(root_modules) + "\n"
    files["imports.tf"] = "# Import blocks associate existing resources with Terraform addresses.\n" + ("\n\n".join(imports) if imports else "# No supported resources were ready to import.\n")
    files["terraform.tfvars.example"] = "\n".join(tfvars) + "\n"

    supported_count = len(addresses)
    coverage = round((supported_count / len(resources)) * 100) if resources else 0
    terraform_types_after = len({address.split(".", 1)[0] for _, address in addresses.values()})
    module_summaries = [
        {"id": key, "label": MODULES[key], "count": len(items), "resource_ids": [item["id"] for item in items]}
        for key, items in modules.items() if items
    ]
    run_id = str(uuid.uuid4())
    agent_review = run_agentic_review(
        provider=inventory["provider"],
        region=inventory["region"],
        resource_count=len(resources),
        relationship_count=len(inventory["relationships"]),
        modules=module_summaries,
        terraform_resources=supported_count,
        coverage=coverage,
        findings=findings,
        skipped=skipped,
        inventory=inventory,
        investigation=investigation,
        terraform_drafts=terraform_drafts,
        budget=model_budget,
    )
    logs = [
        {"agent": "Investigator", "status": "fallback" if investigation.get("mode") == "deterministic_fallback" else "complete", "message": f"Explored {len(investigation['tool_calls'])} read-only tool calls; mapped {len(investigation['workloads'])} workloads and {len(investigation['risks'])} cited risks."},
        {"agent": "Architect", "status": "complete", "message": f"Grouped resources into {len(module_summaries)} modules using resource types, names, and supplied tags."},
        {"agent": "Strategist", "status": "complete", "message": f"Prepared {len(generated)} Terraform module folder(s); {len(skipped)} resource(s) need manual mapping."},
        {"agent": "Terraform writer", "status": "complete" if all(item["status"] == "validated" for item in terraform_drafts) else "review", "message": f"Drafted {len(terraform_drafts)} skipped resource types; {sum(item['status'] == 'validated' for item in terraform_drafts)} passed local syntax and required-argument checks. Never applied."},
        {"agent": "Validator", "status": "review", "message": f"Static inventory checks found {len(findings)} finding(s). Terraform CLI and cloud-state planning were not run."},
        {"agent": "Review agent", "status": agent_review["status"], "message": f"{agent_review['mode'].replace('_', ' ')} selected {len(agent_review['tool_calls'])} evidence tool step(s); a human still approves the package."},
    ]
    analysis_seconds = round(time.perf_counter() - started_at, 3)

    inventory_json = json.dumps(inventory, indent=2, ensure_ascii=False)
    graph_json = json.dumps({"nodes": resources, "edges": inventory["relationships"]}, indent=2, ensure_ascii=False)
    audit_json = json.dumps({
        "run_id": run_id,
        "environment": inventory["name"],
        "provider": inventory["provider"],
        "region": inventory["region"],
        "resource_count": len(resources),
        "relationship_count": len(inventory["relationships"]),
        "terraform_resource_count": supported_count,
        "terraform_types_before_writer": terraform_types_before,
        "terraform_types_after_writer": terraform_types_after,
        "coverage_percent": coverage,
        "coverage_before_writer_percent": coverage_before,
        "findings": findings,
        "skipped_resources": skipped,
        "investigation": investigation,
        "terraform_drafts": [{key: value for key, value in item.items() if key != "hcl"} for item in terraform_drafts],
        "agent_review": agent_review,
        "analysis_seconds": analysis_seconds,
        "checks": {"inventory_schema": "passed", "resource_reference_integrity": "review" if orphan_refs else "passed", "security_inventory_rules": "review" if findings else "passed", "terraform_writer_static_check": "passed_or_unverified", "terraform_validate": "not_run", "cloud_plan": "not_run"},
    }, indent=2, ensure_ascii=False)

    package_readme = f'''# GENESIS generated package

Environment: {inventory['name']}  
Provider: {inventory['provider']}  
Region: {inventory['region']}  
Generated resources: {supported_count} of {len(resources)} ({coverage}% mapping coverage)
Coverage before the Terraform writer: {coverage_before}%

## Before any Terraform operation

This package is a review artifact. GENESIS did not run Terraform, connect to a cloud account during generation, or apply infrastructure changes. It omits unsupported resources and may omit provider-specific details not present in the inventory. Review every resource, relationship, security rule, and finding with a cloud architect.

Terraform writer drafts marked validated passed GENESIS local syntax and required-argument checks only. This is not `terraform validate`, provider-schema validation, a plan review, or adoption approval. Unverified draft HCL stays outside the importable modules.

The import blocks are intended to associate existing resources with Terraform addresses. Terraform's import workflow still requires a plan review. Configuration differences can produce proposed updates after import. `prevent_destroy` is set on emitted resources, but it does not prevent other proposed changes.

1. Copy `terraform.tfvars.example` to a local `terraform.tfvars`; confirm its subscription or region and provider versions against your organization’s standards.
2. Run `terraform init -backend=false` and `terraform validate` in a controlled development environment.
3. Review `audit-report.json` and `skipped-resources.json`.
4. Only after approval, configure a protected state backend and run `terraform plan` with read-only credentials. Review the complete plan before anyone applies it.

Never add credentials, private keys, passwords, or state files to this package or a Git commit.
'''

    files["inventory-manifest.json"] = inventory_json
    files["dependency-graph.json"] = graph_json
    files["investigator-report.json"] = json.dumps(investigation, indent=2, ensure_ascii=False)
    files["terraform-drafts.json"] = json.dumps(terraform_drafts, indent=2, ensure_ascii=False)
    for draft in terraform_drafts:
        if draft["status"] == "unverified" and draft.get("hcl"):
            files[f"terraform-drafts/{draft['label']}.tf"] = "# UNVERIFIED GENESIS Terraform draft. Do not apply. Review and validate with Terraform CLI.\n" + draft["hcl"]
    files["audit-report.json"] = audit_json
    files["agent-review.json"] = json.dumps(agent_review, indent=2, ensure_ascii=False)
    files["skipped-resources.json"] = json.dumps(skipped, indent=2, ensure_ascii=False)
    files["README.md"] = package_readme

    result = {
        "run_id": run_id,
        "environment": inventory,
        "summary": {
            "resources": len(resources),
            "relationships": len(inventory["relationships"]),
            "modules": len(module_summaries),
            "terraform_resources": supported_count,
            "terraform_types_before_writer": terraform_types_before,
            "terraform_types_after_writer": terraform_types_after,
            "coverage_before_writer": coverage_before,
            "coverage": coverage,
            "findings": len(findings),
            "critical_findings": sum(1 for item in findings if item["severity"] == "critical"),
            "skipped": len(skipped),
            "analysis_seconds": analysis_seconds,
        },
        "modules": module_summaries,
        "nodes": resources,
        "edges": inventory["relationships"],
        "findings": findings,
        "skipped": skipped,
        "investigation": investigation,
        "terraform_drafts": terraform_drafts,
        "agent_review": agent_review,
        "logs": logs,
        "files": files,
        "approval": {"approved": False, "approved_at": None},
    }
    RUNS[run_id] = result
    RUN_OWNERS[run_id] = owner_id
    if len(RUNS) > 20:
        evicted = next(iter(RUNS))
        RUNS.pop(evicted)
        RUN_OWNERS.pop(evicted, None)
        RUN_CLIENTS.pop(evicted, None)
    RUN_CLIENTS[run_id] = client_id
    return result


def _owned_run(run_id: str, actor: Actor) -> dict[str, Any]:
    """Return a run only to the employee who created it; conceal foreign IDs."""
    result = RUNS.get(run_id)
    if result is None or RUN_OWNERS.get(run_id) != actor.subject:
        raise HTTPException(status_code=404, detail="Run not found. Re-run discovery before continuing.")
    _client_access(actor, RUN_CLIENTS.get(run_id, ""))
    return result


@app.get("/api/health")
def health() -> dict[str, Any]:
    model_enabled = model_is_configured()
    return {
        "status": "ok",
        "service": "genesis-discovery-api",
        "azure_resource_graph_connector": "configured",
        "review_agent": "azure_openai_configured" if model_enabled else "deterministic_tool_orchestrator",
        "azure_openai_configured": model_enabled,
        "model_mode": "azure_openai" if model_enabled else "local_tools",
        "access_mode": os.getenv("GENESIS_AUTH_MODE", "local").strip().lower(),
        "copilot_mode": "azure_openai_opt_in" if os.getenv("GENESIS_COPILOT_USE_AZURE_OPENAI", "false").strip().lower() in {"1", "true", "yes"} else "local_evidence",
    }


@app.get("/", include_in_schema=False)
def frontend_index() -> FileResponse:
    index_file = FRONTEND_DIST / "index.html"
    if not index_file.is_file():
        raise HTTPException(status_code=404, detail="Frontend assets are not built. Run `npm run build` or use the Vite development server.")
    return FileResponse(index_file)


@app.get("/api/demo")
def demo() -> dict[str, Any]:
    return SYNTHETIC_AZURE_INVENTORY


@app.get("/api/demo/baseline")
def demo_baseline() -> dict[str, Any]:
    """Return the original nine-resource estate for before/after demo measurements."""
    return AZURE_SAMPLE_INVENTORY


@app.post("/api/model/check")
def model_check(actor: Actor = Depends(current_actor)) -> dict[str, Any]:
    del actor  # Authentication is required on protected deployments; the probe itself is read-only.
    return probe_model()


@app.get("/api/demo/aws")
def demo_aws() -> dict[str, Any]:
    return AWS_SAMPLE_INVENTORY


@app.get("/api/clients")
def list_clients(actor: Actor = Depends(current_actor)) -> list[dict[str, str]]:
    return [{"id": client_id, "name": str(access.get("name", client_id))} for client_id, access in sorted(actor.clients.items())]


@app.post("/api/analyze")
def analyze(payload: dict[str, Any], actor: Actor = Depends(current_actor)) -> dict[str, Any]:
    client_id = _text(payload.get("client_id"), "demo").lower()
    _client_access(actor, client_id)
    try:
        return analyze_inventory(payload, owner_id=actor.subject, actor=actor, client_id=client_id)
    except (ValueError, TypeError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.post("/api/providers/aws/discover")
def discover_aws(payload: dict[str, Any], actor: Actor = Depends(current_actor)) -> dict[str, Any]:
    client_id = _text(payload.get("client_id"), "demo").lower()
    client_access = _client_access(actor, client_id)
    region = _text(payload.get("region"), "us-east-1")
    profile = _text(payload.get("profile")) or None
    if actor.tenant_id != "local" and profile:
        raise HTTPException(status_code=403, detail="Named AWS profiles are available only in local demo mode. Protected deployments use the server's assigned role.")
    if not re.fullmatch(r"[a-z]{2}(?:-gov)?-[a-z]+-\d", region):
        raise HTTPException(status_code=422, detail="Enter a valid AWS region, such as us-east-1.")
    try:
        import boto3
        from botocore.exceptions import BotoCoreError, ClientError
    except ImportError as error:
        raise HTTPException(status_code=503, detail="AWS discovery requires the optional boto3 dependency. Install api/requirements.txt.") from error

    try:
        session = boto3.Session(profile_name=profile, region_name=region)
        account_id = session.client("sts").get_caller_identity().get("Account", "")
        _require_cloud_scope(actor, client_id, "aws", account_id)
        ec2 = session.client("ec2")
        resources: list[dict[str, Any]] = []
        relationships: list[dict[str, str]] = []
        def tags_map(tags: list[dict[str, str]] | None) -> dict[str, str]:
            return {item.get("Key", ""): item.get("Value", "") for item in tags or [] if item.get("Key")}

        def listed(client: Any, operation: str, result_key: str) -> Any:
            if client.can_paginate(operation):
                for page in client.get_paginator(operation).paginate():
                    yield from page.get(result_key, [])
            else:
                response = getattr(client, operation)()
                yield from response.get(result_key, [])

        for vpc in listed(ec2, "describe_vpcs", "Vpcs"):
            resources.append({"id": vpc["VpcId"], "type": "aws_vpc", "name": tags_map(vpc.get("Tags")).get("Name", vpc["VpcId"]), "provider": "aws", "region": region, "tags": tags_map(vpc.get("Tags")), "properties": {"cidr_block": vpc.get("CidrBlock"), "enable_dns_support": vpc.get("EnableDnsSupport"), "enable_dns_hostnames": vpc.get("EnableDnsHostnames"), "is_default": vpc.get("IsDefault")}})
        for subnet in listed(ec2, "describe_subnets", "Subnets"):
            resource_id = subnet["SubnetId"]
            resources.append({"id": resource_id, "type": "aws_subnet", "name": tags_map(subnet.get("Tags")).get("Name", resource_id), "provider": "aws", "region": region, "tags": tags_map(subnet.get("Tags")), "properties": {"vpc_id": subnet.get("VpcId"), "cidr_block": subnet.get("CidrBlock"), "availability_zone": subnet.get("AvailabilityZone"), "map_public_ip_on_launch": subnet.get("MapPublicIpOnLaunch")}})
            relationships.append({"source": resource_id, "target": subnet.get("VpcId", ""), "relation": "in_vpc"})
        for reservation in listed(ec2, "describe_instances", "Reservations"):
            for instance in reservation.get("Instances", []):
                resource_id = instance["InstanceId"]
                resources.append({"id": resource_id, "type": "aws_instance", "name": tags_map(instance.get("Tags")).get("Name", resource_id), "provider": "aws", "region": region, "tags": tags_map(instance.get("Tags")), "properties": {"ami": instance.get("ImageId"), "instance_type": instance.get("InstanceType"), "subnet_id": instance.get("SubnetId"), "security_group_ids": [group.get("GroupId") for group in instance.get("SecurityGroups", [])], "private_ip": instance.get("PrivateIpAddress"), "state": instance.get("State", {}).get("Name")}})
                if instance.get("SubnetId"):
                    relationships.append({"source": resource_id, "target": instance["SubnetId"], "relation": "in_subnet"})
                for group in instance.get("SecurityGroups", []):
                    relationships.append({"source": resource_id, "target": group["GroupId"], "relation": "uses_security_group"})
        for group in listed(ec2, "describe_security_groups", "SecurityGroups"):
            resource_id = group["GroupId"]
            def normalize_rules(permissions: list[dict[str, Any]]) -> list[dict[str, Any]]:
                normalized_rules = []
                for permission in permissions:
                    referenced_groups = [item.get("GroupId") for item in permission.get("UserIdGroupPairs", []) if item.get("GroupId")]
                    normalized_rules.append({
                        "from_port": permission.get("FromPort") if permission.get("FromPort") is not None else 0,
                        "to_port": permission.get("ToPort") if permission.get("ToPort") is not None else 0,
                        "protocol": permission.get("IpProtocol", "-1"),
                        "cidr_blocks": [item["CidrIp"] for item in permission.get("IpRanges", []) if "CidrIp" in item],
                        "ipv6_cidr_blocks": [item["CidrIpv6"] for item in permission.get("Ipv6Ranges", []) if "CidrIpv6" in item],
                        "prefix_list_ids": [item["PrefixListId"] for item in permission.get("PrefixListIds", []) if "PrefixListId" in item],
                        "security_groups": [item for item in referenced_groups if item != resource_id],
                        "self": resource_id in referenced_groups,
                    })
                return normalized_rules

            resources.append({"id": resource_id, "type": "aws_security_group", "name": tags_map(group.get("Tags")).get("Name", group.get("GroupName", resource_id)), "provider": "aws", "region": region, "tags": tags_map(group.get("Tags")), "properties": {"vpc_id": group.get("VpcId"), "group_name": group.get("GroupName"), "description": group.get("Description"), "ingress": normalize_rules(group.get("IpPermissions", [])), "egress": normalize_rules(group.get("IpPermissionsEgress", []))}})
            if group.get("VpcId"):
                relationships.append({"source": resource_id, "target": group["VpcId"], "relation": "in_vpc"})
        elbv2 = session.client("elbv2")
        for load_balancer in listed(elbv2, "describe_load_balancers", "LoadBalancers"):
            resource_id = load_balancer["LoadBalancerArn"]
            resources.append({"id": resource_id, "type": "aws_lb", "name": load_balancer.get("LoadBalancerName", resource_id), "provider": "aws", "region": region, "tags": {}, "properties": {"lb_name": load_balancer.get("LoadBalancerName"), "load_balancer_type": load_balancer.get("Type"), "subnet_ids": [item["SubnetId"] for item in load_balancer.get("AvailabilityZones", []) if item.get("SubnetId")], "security_group_ids": load_balancer.get("SecurityGroups", []), "internal": load_balancer.get("Scheme") == "internal"}})
            for subnet_id in [item["SubnetId"] for item in load_balancer.get("AvailabilityZones", []) if item.get("SubnetId")]:
                relationships.append({"source": resource_id, "target": subnet_id, "relation": "uses_subnet"})
            for group_id in load_balancer.get("SecurityGroups", []):
                relationships.append({"source": resource_id, "target": group_id, "relation": "uses_security_group"})
        rds = session.client("rds")
        for db in listed(rds, "describe_db_instances", "DBInstances"):
            resource_id = db["DBInstanceIdentifier"]
            subnet_group = db.get("DBSubnetGroup", {})
            subnet_group_name = subnet_group.get("DBSubnetGroupName")
            subnet_ids = [item.get("SubnetIdentifier") for item in subnet_group.get("Subnets", []) if item.get("SubnetIdentifier")]
            if subnet_group_name and not any(item["id"] == subnet_group_name for item in resources):
                resources.append({"id": subnet_group_name, "type": "aws_db_subnet_group", "name": subnet_group_name, "provider": "aws", "region": region, "tags": {}, "properties": {"subnet_ids": subnet_ids}})
            resources.append({"id": resource_id, "type": "aws_db_instance", "name": resource_id, "provider": "aws", "region": region, "tags": {}, "properties": {"identifier": resource_id, "engine": db.get("Engine"), "instance_class": db.get("DBInstanceClass"), "allocated_storage": db.get("AllocatedStorage"), "storage_encrypted": db.get("StorageEncrypted"), "publicly_accessible": db.get("PubliclyAccessible"), "deletion_protection": db.get("DeletionProtection"), "db_subnet_group_name": subnet_group_name, "db_subnet_group_id": subnet_group_name, "security_group_ids": [item.get("VpcSecurityGroupId") for item in db.get("VpcSecurityGroups", []) if item.get("VpcSecurityGroupId")], "username": db.get("MasterUsername")}})
            for group in db.get("VpcSecurityGroups", []):
                if group.get("VpcSecurityGroupId"):
                    relationships.append({"source": resource_id, "target": group["VpcSecurityGroupId"], "relation": "uses_security_group"})

        s3 = session.client("s3")
        for bucket in listed(s3, "list_buckets", "Buckets"):
            bucket_name = bucket["Name"]
            location = bucket.get("BucketRegion")
            if not location:
                try:
                    location = s3.get_bucket_location(Bucket=bucket_name).get("LocationConstraint") or "us-east-1"
                    if location == "EU":
                        location = "eu-west-1"
                except ClientError:
                    location = "unknown"
            bucket_props: dict[str, Any] = {"bucket": bucket_name}
            try:
                encryption = s3.get_bucket_encryption(Bucket=bucket_name).get("ServerSideEncryptionConfiguration", {}).get("Rules", [])
                bucket_props["encryption_enabled"] = bool(encryption)
            except ClientError as error:
                code = error.response.get("Error", {}).get("Code", "")
                if code in {"ServerSideEncryptionConfigurationNotFoundError", "NoSuchEncryptionConfiguration"}:
                    bucket_props["encryption_enabled"] = False
            try:
                block = s3.get_public_access_block(Bucket=bucket_name).get("PublicAccessBlockConfiguration", {})
                bucket_props["public_access_block"] = all(block.get(key) is True for key in ("BlockPublicAcls", "IgnorePublicAcls", "BlockPublicPolicy", "RestrictPublicBuckets"))
            except ClientError:
                pass
            resources.append({"id": bucket_name, "type": "aws_s3_bucket", "name": bucket_name, "provider": "aws", "region": location, "tags": {}, "properties": bucket_props})

        inventory = {"name": f"AWS {region} inventory", "provider": "aws", "region": region, "account_id": account_id, "resources": resources, "relationships": relationships}
        normalized = normalize_inventory(inventory)
        normalized["client_id"] = client_id
        normalized["client_name"] = client_access.get("name", client_id)
        return normalized
    except (BotoCoreError, ClientError) as error:
        message = getattr(error, "response", {}).get("Error", {}).get("Message") or str(error)
        raise HTTPException(status_code=502, detail=f"Read-only AWS discovery failed: {message}") from error
    except Exception as error:
        raise HTTPException(status_code=502, detail=f"AWS discovery could not complete: {error}") from error


@app.post("/api/providers/azure/discover")
def discover_azure(payload: dict[str, Any], actor: Actor = Depends(current_actor)) -> dict[str, Any]:
    client_id = _text(payload.get("client_id"), "demo").lower()
    client_access = _client_access(actor, client_id)
    from azure.core.exceptions import ClientAuthenticationError, HttpResponseError

    subscription_id = _text(_pick(payload, "subscription_id", "subscriptionId"))
    resource_group = _text(_pick(payload, "resource_group", "resourceGroup")) or None
    if not re.fullmatch(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}", subscription_id):
        raise HTTPException(status_code=422, detail="Enter a valid Azure subscription ID (GUID).")
    _require_cloud_scope(actor, client_id, "azure", subscription_id, resource_group or "")
    if resource_group and (len(resource_group) > 90 or resource_group.endswith(".")):
        raise HTTPException(status_code=422, detail="Enter a valid Azure resource group name (up to 90 characters).")
    try:
        inventory = normalize_inventory(discover_azure_resources(subscription_id, resource_group))
        inventory["client_id"] = client_id
        inventory["client_name"] = client_access.get("name", client_id)
        return inventory
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except ClientAuthenticationError as error:
        raise HTTPException(status_code=401, detail="Azure login was not found. Run `az login` in the same environment as the API, then scan again.") from error
    except HttpResponseError as error:
        if error.status_code == 403:
            raise HTTPException(status_code=403, detail="Azure denied Resource Graph access. Ask an administrator for Reader access on the selected subscription.") from error
        if error.status_code == 429:
            raise HTTPException(status_code=429, detail="Azure Resource Graph is throttling requests. Wait briefly or narrow the scan scope.") from error
        raise HTTPException(status_code=502, detail=f"Azure Resource Graph returned HTTP {error.status_code}.") from error
    except Exception as error:
        raise HTTPException(status_code=502, detail=f"Azure Resource Graph discovery failed: {error}") from error


@app.post("/api/runs/{run_id}/approve")
def approve(run_id: str, payload: dict[str, Any], actor: Actor = Depends(current_actor)) -> dict[str, Any]:
    result = _owned_run(run_id, actor)
    if payload.get("reviewed") is not True:
        raise HTTPException(status_code=400, detail="Review confirmation is required before package export.")
    result["approval"] = {"approved": True, "approved_at": datetime.now(timezone.utc).isoformat()}
    return {"run_id": run_id, "approval": result["approval"]}


@app.post("/api/runs/{run_id}/ask")
def ask_estate(run_id: str, payload: dict[str, Any], actor: Actor = Depends(current_actor)) -> dict[str, Any]:
    result = _owned_run(run_id, actor)
    question = _text(payload.get("question"))
    try:
        return answer_estate_question(question, result)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.get("/api/runs/{run_id}/package")
def download_package(run_id: str, actor: Actor = Depends(current_actor)) -> StreamingResponse:
    result = _owned_run(run_id, actor)
    if not result["approval"]["approved"]:
        raise HTTPException(status_code=403, detail="Architect approval is required before export.")

    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path, content in result["files"].items():
            archive.writestr(path, content)
    buffer.seek(0)
    filename = safe_label(result["environment"]["name"]) + "-genesis-iac.zip"
    return StreamingResponse(buffer, media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="{filename}"'})
