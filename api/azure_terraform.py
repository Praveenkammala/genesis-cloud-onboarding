"""Small, explicit AzureRM mappings for reviewed Terraform generation."""

from __future__ import annotations

import json
import re
from typing import Any


AZURE_TERRAFORM_TYPES = {
    "microsoft.resources/subscriptions/resourcegroups": "azurerm_resource_group",
    "microsoft.resources/resourcegroups": "azurerm_resource_group",
    "azurerm_resource_group": "azurerm_resource_group",
    "microsoft.network/virtualnetworks": "azurerm_virtual_network",
    "azurerm_virtual_network": "azurerm_virtual_network",
    "microsoft.network/virtualnetworks/subnets": "azurerm_subnet",
    "azurerm_subnet": "azurerm_subnet",
    "microsoft.network/networksecuritygroups": "azurerm_network_security_group",
    "azurerm_network_security_group": "azurerm_network_security_group",
    "microsoft.network/publicipaddresses": "azurerm_public_ip",
    "azurerm_public_ip": "azurerm_public_ip",
    "microsoft.network/networkinterfaces": "azurerm_network_interface",
    "azurerm_network_interface": "azurerm_network_interface",
    "microsoft.storage/storageaccounts": "azurerm_storage_account",
    "azurerm_storage_account": "azurerm_storage_account",
}


def terraform_type(resource: dict[str, Any]) -> str | None:
    if resource.get("provider") != "azure":
        return None
    return AZURE_TERRAFORM_TYPES.get(str(resource.get("type", "")).lower())


def _pick(source: dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if key in source and source[key] is not None:
            return source[key]
    return default


def _hcl_string(value: Any) -> str:
    return json.dumps(str(value), ensure_ascii=False)


def _hcl_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return _hcl_string(value)


def _hcl_list(values: list[Any]) -> str:
    return "[" + ", ".join(_hcl_value(item) for item in values) + "]"


def _tags_block(tags: dict[str, Any]) -> list[str]:
    safe_tags = {
        str(key): str(value)
        for key, value in tags.items()
        if value is not None and not any(token in str(key).lower() for token in ("secret", "password", "token", "key"))
    }
    if not safe_tags:
        return []
    lines = ["  tags = {"]
    lines.extend(f"    {_hcl_string(key)} = {_hcl_string(value)}" for key, value in sorted(safe_tags.items()))
    lines.append("  }")
    return lines


def _child_name(resource_id: str, parent: str) -> str | None:
    match = re.search(rf"/{re.escape(parent)}/([^/]+)", resource_id, re.IGNORECASE)
    return match.group(1) if match else None


def _rule_props(rule: dict[str, Any]) -> dict[str, Any]:
    nested = rule.get("properties")
    return nested if isinstance(nested, dict) else rule


def _append_string_or_list(lines: list[str], target: str, scalar: Any, plural: Any) -> bool:
    if isinstance(plural, list) and plural:
        lines.append(f"    {target}s = {_hcl_list(plural)}")
        return True
    if scalar is not None:
        lines.append(f"    {target} = {_hcl_value(scalar)}")
        return True
    return False


def terraform_for_azure(resource: dict[str, Any], label: str) -> tuple[str | None, str | None]:
    resource_type = terraform_type(resource)
    if not resource_type:
        return None, "No Azure Terraform mapping for this resource type"

    props = resource.get("properties") if isinstance(resource.get("properties"), dict) else {}
    tags = resource.get("tags") if isinstance(resource.get("tags"), dict) else {}
    name = str(resource.get("name") or resource.get("id") or "resource")
    region = str(resource.get("region") or "")
    resource_group = str(resource.get("resource_group") or "")
    lines: list[str] = []

    if resource_type == "azurerm_resource_group":
        if not region or region.lower() == "unknown":
            return None, "Missing resource group location"
        lines += [f"  name = {_hcl_string(name)}", f"  location = {_hcl_string(region)}"]

    elif resource_type == "azurerm_virtual_network":
        address_space = _pick(props, "address_space", "addressSpace", default={})
        if isinstance(address_space, dict):
            address_space = _pick(address_space, "addressPrefixes", "address_prefixes", default=[])
        if not isinstance(address_space, list) or not address_space:
            address_space = _pick(props, "addressPrefixes", default=[])
        if not resource_group or not region or not isinstance(address_space, list) or not address_space:
            return None, "Missing resource group, location, or virtual network address space"
        lines += [
            f"  name = {_hcl_string(name)}",
            f"  location = {_hcl_string(region)}",
            f"  resource_group_name = {_hcl_string(resource_group)}",
            f"  address_space = {_hcl_list(address_space)}",
        ]
        dns = _pick(props, "dns_servers", default={})
        if isinstance(dns, dict):
            dns = _pick(dns, "dnsServers", "dns_servers", default=[])
        if isinstance(dns, list) and dns:
            lines.append(f"  dns_servers = {_hcl_list(dns)}")

    elif resource_type == "azurerm_subnet":
        parent_vnet = _child_name(str(resource.get("id", "")), "virtualNetworks")
        address_prefixes = _pick(props, "address_prefixes", "addressPrefixes", default=[])
        if isinstance(address_prefixes, str):
            address_prefixes = [address_prefixes]
        if not address_prefixes:
            single_prefix = _pick(props, "address_prefix", "addressPrefix")
            address_prefixes = [single_prefix] if single_prefix else []
        if not resource_group or not parent_vnet or not isinstance(address_prefixes, list) or not address_prefixes:
            return None, "Missing resource group, parent virtual network, or subnet address prefixes"
        if any(props.get(key) for key in ("networkSecurityGroup", "routeTable", "delegations", "serviceEndpoints")):
            return None, "Subnet association, delegation, or endpoint details need a separate Terraform mapping"
        lines += [
            f"  name = {_hcl_string(name)}",
            f"  resource_group_name = {_hcl_string(resource_group)}",
            f"  virtual_network_name = {_hcl_string(parent_vnet)}",
            f"  address_prefixes = {_hcl_list(address_prefixes)}",
        ]

    elif resource_type == "azurerm_network_security_group":
        if not resource_group or not region:
            return None, "Missing resource group or location"
        lines += [
            f"  name = {_hcl_string(name)}",
            f"  location = {_hcl_string(region)}",
            f"  resource_group_name = {_hcl_string(resource_group)}",
        ]
        rules = _pick(props, "securityRules", "security_rules", default=[])
        if not isinstance(rules, list):
            return None, "Invalid network security rule list"
        for rule in rules:
            if not isinstance(rule, dict):
                return None, "Invalid network security rule record"
            rule_props = _rule_props(rule)
            rule_name = _pick(rule, "name", default=_pick(rule_props, "name"))
            priority = _pick(rule_props, "priority")
            direction = _pick(rule_props, "direction")
            access = _pick(rule_props, "access")
            protocol = _pick(rule_props, "protocol")
            if not all(item is not None for item in (rule_name, priority, direction, access, protocol)):
                return None, "A network security rule is missing a required field"
            block = [
                "  security_rule {",
                f"    name = {_hcl_string(rule_name)}",
                f"    priority = {_hcl_value(priority)}",
                f"    direction = {_hcl_string(direction)}",
                f"    access = {_hcl_string(access)}",
                f"    protocol = {_hcl_string(protocol)}",
            ]
            source_ports = _pick(rule_props, "sourcePortRange", "source_port_range")
            source_ports_many = _pick(rule_props, "sourcePortRanges", "source_port_ranges")
            destination_ports = _pick(rule_props, "destinationPortRange", "destination_port_range")
            destination_ports_many = _pick(rule_props, "destinationPortRanges", "destination_port_ranges")
            source_prefix = _pick(rule_props, "sourceAddressPrefix", "source_address_prefix")
            source_prefixes = _pick(rule_props, "sourceAddressPrefixes", "source_address_prefixes")
            destination_prefix = _pick(rule_props, "destinationAddressPrefix", "destination_address_prefix")
            destination_prefixes = _pick(rule_props, "destinationAddressPrefixes", "destination_address_prefixes")
            if not _append_string_or_list(block, "source_port_range", source_ports, source_ports_many):
                return None, "A network security rule has no source port range"
            if not _append_string_or_list(block, "destination_port_range", destination_ports, destination_ports_many):
                return None, "A network security rule has no destination port range"
            if not _append_string_or_list(block, "source_address_prefix", source_prefix, source_prefixes):
                return None, "A network security rule has no source address"
            if not _append_string_or_list(block, "destination_address_prefix", destination_prefix, destination_prefixes):
                return None, "A network security rule has no destination address"
            description = _pick(rule_props, "description")
            if description:
                block.append(f"    description = {_hcl_string(description)}")
            block.append("  }")
            lines.extend(block)

    elif resource_type == "azurerm_public_ip":
        allocation = _pick(props, "publicIPAllocationMethod", "public_ip_allocation_method")
        sku = resource.get("sku") if isinstance(resource.get("sku"), dict) else props.get("sku", {})
        sku_name = _pick(sku, "name", default="Standard") if isinstance(sku, dict) else "Standard"
        if not resource_group or not region or allocation != "Static" or sku_name not in {"Standard", "StandardV2"}:
            return None, "Only Static public IPs with current Standard or StandardV2 SKUs are mapped"
        if any(props.get(key) for key in ("publicIPPrefix", "ipTags", "ddosSettings")):
            return None, "Public IP prefix, IP tags, or DDoS settings need an additional Terraform mapping"
        lines += [
            f"  name = {_hcl_string(name)}",
            f"  location = {_hcl_string(region)}",
            f"  resource_group_name = {_hcl_string(resource_group)}",
            f"  allocation_method = {_hcl_string(allocation)}",
            f"  sku = {_hcl_string(sku_name)}",
        ]
        sku_tier = _pick(sku, "tier") if isinstance(sku, dict) else None
        if sku_tier in {"Regional", "Global"}:
            lines.append(f"  sku_tier = {_hcl_string(sku_tier)}")
        version = _pick(props, "publicIPAddressVersion", "public_ip_address_version")
        if version in {"IPv4", "IPv6"}:
            lines.append(f"  ip_version = {_hcl_string(version)}")
        timeout = _pick(props, "idleTimeoutInMinutes", "idle_timeout_in_minutes")
        if timeout is not None:
            if not isinstance(timeout, int) or timeout < 4 or timeout > 30:
                return None, "Public IP idle timeout must be an integer between 4 and 30 minutes"
            lines.append(f"  idle_timeout_in_minutes = {_hcl_value(timeout)}")

    elif resource_type == "azurerm_network_interface":
        if not resource_group or not region:
            return None, "Missing resource group or location"
        if props.get("networkSecurityGroup"):
            return None, "Network interface security group association needs a separate Terraform resource"
        configurations = _pick(props, "ipConfigurations", "ip_configurations", default=[])
        if not isinstance(configurations, list) or not configurations:
            return None, "Missing network interface IP configuration"
        lines += [
            f"  name = {_hcl_string(name)}",
            f"  location = {_hcl_string(region)}",
            f"  resource_group_name = {_hcl_string(resource_group)}",
        ]
        for config in configurations:
            if not isinstance(config, dict):
                return None, "Invalid network interface IP configuration"
            config_props = _rule_props(config)
            allocation = _pick(config_props, "privateIPAllocationMethod", "private_ip_address_allocation")
            config_name = _pick(config, "name", default=_pick(config_props, "name"))
            if not config_name or allocation not in {"Dynamic", "Static"}:
                return None, "Network interface IP configuration is missing a name or allocation method"
            lines += ["  ip_configuration {", f"    name = {_hcl_string(config_name)}"]
            subnet = _pick(config_props, "subnet", default={})
            subnet_id = subnet.get("id") if isinstance(subnet, dict) else None
            if subnet_id:
                lines.append(f"    subnet_id = {_hcl_string(subnet_id)}")
            lines.append(f"    private_ip_address_allocation = {_hcl_string(allocation)}")
            private_ip = _pick(config_props, "privateIPAddress", "private_ip_address")
            if allocation == "Static" and private_ip:
                lines.append(f"    private_ip_address = {_hcl_string(private_ip)}")
            public_ip = _pick(config_props, "publicIPAddress", default={})
            public_ip_id = public_ip.get("id") if isinstance(public_ip, dict) else None
            if public_ip_id:
                lines.append(f"    public_ip_address_id = {_hcl_string(public_ip_id)}")
            if _pick(config_props, "primary") is not None:
                lines.append(f"    primary = {_hcl_value(config_props['primary'])}")
            lines.append("  }")

    elif resource_type == "azurerm_storage_account":
        sku = resource.get("sku") if isinstance(resource.get("sku"), dict) else props.get("sku", {})
        sku_name = _pick(sku, "name") if isinstance(sku, dict) else None
        sku_parts = str(sku_name or "").split("_", 1)
        tier = _pick(props, "account_tier", "accountTier", default=sku_parts[0] if len(sku_parts) == 2 else None)
        replication = _pick(props, "account_replication_type", "accountReplicationType", default=sku_parts[1] if len(sku_parts) == 2 else None)
        kind = _pick(props, "kind", default=resource.get("kind"))
        if not resource_group or not region or not tier or not replication:
            return None, "Missing resource group, location, storage tier, or replication type"
        lines += [
            f"  name = {_hcl_string(name)}",
            f"  resource_group_name = {_hcl_string(resource_group)}",
            f"  location = {_hcl_string(region)}",
            f"  account_tier = {_hcl_string(tier)}",
            f"  account_replication_type = {_hcl_string(replication)}",
        ]
        if kind:
            lines.append(f"  account_kind = {_hcl_string(kind)}")
        access_tier = _pick(props, "accessTier", "access_tier")
        if access_tier in {"Hot", "Cool", "Cold", "Smart", "Premium"}:
            lines.append(f"  access_tier = {_hcl_string(access_tier)}")
        for source, target in (
            ("allowBlobPublicAccess", "allow_nested_items_to_be_public"),
            ("supportsHttpsTrafficOnly", "https_traffic_only_enabled"),
        ):
            setting = _pick(props, source)
            if isinstance(setting, bool):
                lines.append(f"  {target} = {_hcl_value(setting)}")
        min_tls = _pick(props, "minimumTlsVersion", "min_tls_version")
        if min_tls and min_tls != "TLS1_2":
            return None, "AzureRM supports TLS1_2 for this setting; older reported values are not emitted as a safe import configuration"
        if min_tls == "TLS1_2":
            lines.append("  min_tls_version = \"TLS1_2\"")
        public_network = _pick(props, "publicNetworkAccess", "public_network_access_enabled")
        if public_network in {"Enabled", "Disabled", "SecuredByPerimeter"}:
            lines.append(f"  public_network_access = {_hcl_string(public_network)}")

    else:
        return None, "No Azure Terraform mapping for this resource type"

    lines.extend(_tags_block(tags))
    body = f'resource "{resource_type}" "{label}" {{\n' + "\n".join(lines) + "\n\n  lifecycle {\n    prevent_destroy = true\n  }\n}\n"
    return body, None
