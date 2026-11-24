# Inventory JSON format

The API accepts a provider-neutral JSON inventory. Azure is the default demo. The Azure connector produces this same shape from Azure Resource Graph; AWS remains supported as a secondary provider. The included sample IDs and subscription are fictional.

## Azure example

```json
{
  "client_id": "client-acme-prod",
  "name": "Northstar production",
  "provider": "azure",
  "subscription_id": "11111111-1111-4111-8111-111111111111",
  "region": "eastus",
  "resources": [
    {
      "id": "/subscriptions/11111111-1111-4111-8111-111111111111/resourceGroups/rg-example/providers/Microsoft.Network/virtualNetworks/vnet-example",
      "type": "Microsoft.Network/virtualNetworks",
      "name": "vnet-example",
      "provider": "azure",
      "subscription_id": "11111111-1111-4111-8111-111111111111",
      "resource_group": "rg-example",
      "region": "eastus",
      "tags": { "environment": "demo" },
      "properties": { "addressSpace": { "addressPrefixes": ["10.40.0.0/16"] } }
    }
  ],
  "relationships": []
}
```

Required fields: `resources` must be a non-empty array and every resource must have `id` and `type`. Names default to IDs. The API infers Azure provider from ARM resource types beginning with `Microsoft.` if the record has no explicit provider. Subscription ID can be supplied at inventory level or on each resource; if absent, the API attempts to parse it from the ARM ID. Resource group name can be supplied per resource or parsed from its ARM ID.

## AWS example

```json
{
  "client_id": "client-acme-prod",
  "name": "Northstar production",
  "provider": "aws",
  "region": "us-east-1",
  "account_id": "123456789012",
  "resources": [
    {
      "id": "vpc-0a91c7e31d44",
      "type": "aws_vpc",
      "name": "production-vpc",
      "tags": { "Environment": "production" },
      "properties": { "cidr_block": "10.40.0.0/16" }
    },
    {
      "id": "subnet-0e11a21001",
      "type": "aws_subnet",
      "name": "private-a",
      "tags": {},
      "properties": {
        "vpc_id": "vpc-0a91c7e31d44",
        "cidr_block": "10.40.11.0/24"
      }
    }
  ],
  "relationships": [
    { "source": "subnet-0e11a21001", "target": "vpc-0a91c7e31d44", "relation": "in_vpc" }
  ]
}
```

## Relationships and limits

Relationships are optional. The API uses supplied `relationships` (or `edges`) and infers common references. AWS fields include `vpc_id`, `subnet_id`, `security_group_ids`, `subnet_ids`, and `depends_on`. Azure ARM `id` references in properties and hierarchical ARM IDs are resolved against resource IDs in the same inventory. Unresolved user-supplied relationships are omitted and reported as a finding.

Region and tags are optional; `properties` must be an object when supplied. Resource IDs are unique without regard to letter case. The API accepts up to 1,500 records per run. AWS Terraform output requires a known, consistent single region. Azure output requires a known subscription, while resources may use multiple Azure regions.

The UI attaches the selected `client_id` to analysis and discovery requests. In protected App Service mode, the API checks that the signed-in employee is assigned to that client and that every Azure subscription or AWS account ID is in that client's scope map. Protected AWS imports must include `account_id` at inventory or resource level; ARNs with an account component are parsed automatically. Do not merge inventories from clients that have different workspace assignments.

Keep passwords, private keys, tokens, connection strings, SAS values, and credentials out of files. The API redacts common secret-shaped property keys before presenting scan results, but this is not a general-purpose secret scanner. Do not use it as a justification for uploading unreviewed secrets or sensitive operational data.

Terraform mappings are intentionally limited. See [`architecture.md`](architecture.md) for the supported Azure resource types and what the mapping percentage means.
