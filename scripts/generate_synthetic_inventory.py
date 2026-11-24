"""Regenerate the fictional Azure managed-services demo estate JSON."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SUBSCRIPTION = "11111111-1111-4111-8111-111111111111"
TENANT = "22222222-2222-4222-8222-222222222222"
WORKLOADS = [
    ("payhub", "payments-hub", "rg-northstar-payments-prd-01", "eastus"),
    ("claimslake", "claims-data-lake", "rg-contoso-claims-prod", "eastus2"),
    ("euroapi", "europe-api", "rg-fabrikam-eu-api-02", "centralus"),
    ("opsmon", "operations-monitoring", "rg-ops--legacy", "eastus"),
]


def make() -> dict:
    resources = []
    relationships = []

    def add(resource_id: str, resource_type: str, name: str, rg: str, region: str, tags: dict, properties: dict, kind=None, sku=None):
        record = {
            "id": resource_id, "type": resource_type, "name": name,
            "provider": "azure", "subscription_id": SUBSCRIPTION,
            "resource_group": rg, "region": region, "tags": tags,
            "properties": properties,
        }
        if kind is not None:
            record["kind"] = kind
        if sku is not None:
            record["sku"] = sku
        resources.append(record)
        return resource_id

    for index, (short, workload, rg, region) in enumerate(WORKLOADS):
        common = {"environment": "prod", "application": workload, "owner": "platform-ops"}
        base = f"/subscriptions/{SUBSCRIPTION}/resourceGroups/{rg}"
        rg_id = add(f"{base}", "Microsoft.Resources/subscriptions/resourceGroups", rg, rg, region, common.copy(), {})
        vnet_name = f"vnet-{short}-prod"
        vnet_id = f"{base}/providers/Microsoft.Network/virtualNetworks/{vnet_name}"
        subnet_web = f"{vnet_id}/subnets/snet-{short}-web"
        subnet_data = f"{vnet_id}/subnets/snet-{short}-data"
        add(vnet_id, "Microsoft.Network/virtualNetworks", vnet_name, rg, region, common.copy(), {
            "addressSpace": {"addressPrefixes": [f"10.{60 + index}.0.0/16"]},
            "subnets": [{"id": subnet_web}, {"id": subnet_data}],
        })
        add(subnet_web, "Microsoft.Network/virtualNetworks/subnets", f"snet-{short}-web", rg, region, {}, {
            "addressPrefix": f"10.{60 + index}.1.0/24", "virtualNetwork": {"id": vnet_id},
        })
        add(subnet_data, "Microsoft.Network/virtualNetworks/subnets", f"snet-{short}-data", rg, region, {}, {
            "addressPrefixes": [f"10.{60 + index}.10.0/24"], "virtualNetwork": {"id": vnet_id},
        })
        nsg_name = f"nsg-{short}-web"
        nsg_id = f"{base}/providers/Microsoft.Network/networkSecurityGroups/{nsg_name}"
        rules = [{"name": "allow-https", "properties": {
            "priority": 300, "direction": "Inbound", "access": "Allow", "protocol": "Tcp",
            "sourcePortRange": "*", "destinationPortRange": "443",
            "sourceAddressPrefix": "Internet", "destinationAddressPrefix": "*",
        }}]
        if index == 0:
            rules.append({"name": "temp-ssh-open", "properties": {
                "priority": 310, "direction": "Inbound", "access": "Allow", "protocol": "Tcp",
                "sourcePortRange": "*", "destinationPortRange": "22",
                "sourceAddressPrefix": "0.0.0.0/0", "destinationAddressPrefix": "*",
            }})
        add(nsg_id, "Microsoft.Network/networkSecurityGroups", nsg_name, rg, region, common.copy(), {"securityRules": rules})
        pip_name = f"pip-{short}-web"
        pip_id = f"{base}/providers/Microsoft.Network/publicIPAddresses/{pip_name}"
        add(pip_id, "Microsoft.Network/publicIPAddresses", pip_name, rg, region, common.copy(), {
            "publicIPAllocationMethod": "Static", "publicIPAddressVersion": "IPv4", "idleTimeoutInMinutes": 10,
        }, sku={"name": "Standard", "tier": "Regional"})
        nic_name = f"nic-{short}-web"
        nic_id = f"{base}/providers/Microsoft.Network/networkInterfaces/{nic_name}"
        add(nic_id, "Microsoft.Network/networkInterfaces", nic_name, rg, region, common.copy(), {
            "ipConfigurations": [{"name": "ipconfig-primary", "properties": {
                "primary": True, "privateIPAllocationMethod": "Dynamic",
                "subnet": {"id": subnet_web}, "publicIPAddress": {"id": pip_id},
            }}], "networkSecurityGroup": {"id": nsg_id},
        })
        vm_name = f"vm-{short}-web-01" if index != 3 else "vm-ops--legacy__01"
        vm_id = f"{base}/providers/Microsoft.Compute/virtualMachines/{vm_name}"
        add(vm_id, "Microsoft.Compute/virtualMachines", vm_name, rg, region, common.copy(), {
            "hardwareProfile": {"vmSize": "Standard_B2s"},
            "networkProfile": {"networkInterfaces": [{"id": nic_id}]},
            "osProfile": {"adminUsername": "azureuser"},
        })
        sql_name = f"sql-{short}-primary"
        sql_id = f"{base}/providers/Microsoft.Sql/servers/{sql_name}"
        add(sql_id, "Microsoft.Sql/servers", sql_name, rg, region, common.copy(), {
            "version": "12.0", "publicNetworkAccess": "Enabled", "minimalTlsVersion": "1.2",
        })
        db_name = f"sqldb-{short}-core"
        add(f"{sql_id}/databases/{db_name}", "Microsoft.Sql/servers/databases", db_name, rg, region, common.copy(), {
            "serverId": sql_id, "status": "Online", "sku": {"name": "GP_Gen5_2"}, "maxSizeBytes": 268435456000,
        })
        vault_name = f"kv{short}prod{index + 1:02d}"[:24]
        add(f"{base}/providers/Microsoft.KeyVault/vaults/{vault_name}", "Microsoft.KeyVault/vaults", vault_name, rg, region, common.copy() if index % 2 == 0 else {}, {
            "tenantId": TENANT, "sku": {"name": "standard"}, "enableSoftDelete": True,
            "softDeleteRetentionInDays": 90, "purgeProtectionEnabled": index != 2,
            "networkAcls": {"defaultAction": "Allow" if index == 0 else "Deny"},
        })
        storage_name = f"st{short}{index + 1:02d}prod"
        add(f"{base}/providers/Microsoft.Storage/storageAccounts/{storage_name}", "Microsoft.Storage/storageAccounts", storage_name, rg, region, common.copy(), {
            "accessTier": "Hot", "allowBlobPublicAccess": False, "supportsHttpsTrafficOnly": True,
            "minimumTlsVersion": "TLS1_2", "publicNetworkAccess": "Enabled",
        }, kind="StorageV2", sku={"name": "Standard_LRS"})
        plan_name = f"asp-{short}-prod"
        plan_id = f"{base}/providers/Microsoft.Web/serverfarms/{plan_name}"
        add(plan_id, "Microsoft.Web/serverfarms", plan_name, rg, region, common.copy(), {
            "sku": {"name": "P1v3", "tier": "PremiumV3"}, "reserved": True,
        }, kind="linux")
        site_name = f"app-{short}-prod"
        add(f"{base}/providers/Microsoft.Web/sites/{site_name}", "Microsoft.Web/sites", site_name, rg, region, common.copy(), {
            "serverFarmId": plan_id, "httpsOnly": True, "kind": "app,linux", "state": "Running",
            "siteConfig": {"alwaysOn": True, "minTlsVersion": "1.2"},
        }, kind="app,linux")
        add(f"{base}/providers/Microsoft.OperationalInsights/workspaces/law-{short}-prod", "Microsoft.OperationalInsights/workspaces", f"law-{short}-prod", rg, region, common.copy(), {
            "retentionInDays": 30, "sku": {"name": "PerGB2018"},
        })
        add(f"{base}/providers/Microsoft.Insights/components/ai-{short}-prod", "Microsoft.Insights/components", f"ai-{short}-prod", rg, region, common.copy(), {
            "Application_Type": "web", "WorkspaceResourceId": f"{base}/providers/Microsoft.OperationalInsights/workspaces/law-{short}-prod",
        })
        identity_name = f"id-{short}-app"
        add(f"{base}/providers/Microsoft.ManagedIdentity/userAssignedIdentities/{identity_name}", "Microsoft.ManagedIdentity/userAssignedIdentities", identity_name, rg, region, common.copy(), {
            "clientId": f"00000000-0000-4000-8000-{index + 1:012d}",
        })
        endpoint_name = f"pe-{short}-sql"
        add(f"{base}/providers/Microsoft.Network/privateEndpoints/{endpoint_name}", "Microsoft.Network/privateEndpoints", endpoint_name, rg, region, common.copy(), {
            "subnet": {"id": subnet_data},
            "privateLinkServiceConnections": [{"name": f"plsc-{short}-sql", "properties": {
                "privateLinkServiceId": sql_id, "groupIds": ["sqlServer"],
            }}],
        })
        # Explicit records supplement the property-derived links so the walk is clear in the demo graph.
        relationships.extend([
            {"source": nic_id, "target": nsg_id, "relation": "uses_network_security_group"},
            {"source": vm_id, "target": nic_id, "relation": "uses_network_interface"},
            {"source": f"{sql_id}/databases/{db_name}", "target": sql_id, "relation": "hosted_on"},
            {"source": f"{base}/providers/Microsoft.Web/sites/{site_name}", "target": plan_id, "relation": "uses_service_plan"},
            {"source": f"{base}/providers/Microsoft.Insights/components/ai-{short}-prod", "target": f"{base}/providers/Microsoft.OperationalInsights/workspaces/law-{short}-prod", "relation": "writes_to"},
        ])

    return {
        "name": "Kyndryl Managed Services · Fictional Azure multi-workload estate",
        "provider": "azure", "region": "eastus", "subscription_id": SUBSCRIPTION,
        "resources": resources, "relationships": relationships,
        "synthetic": True,
        "notice": "All tenant, subscription, customer, workload, resource, and configuration data is fictional and generated for a product demonstration.",
    }


if __name__ == "__main__":
    output = ROOT / "samples" / "kyndryl-synthetic-estate.json"
    output.write_text(json.dumps(make(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {len(make()['resources'])} synthetic resources to {output}")
