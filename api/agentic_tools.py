"""Typed, read-only tools shared by GENESIS agents and Copilot."""

from __future__ import annotations

import json
import time
from collections import deque
from typing import Any, Callable


TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function", "name": "list_resources",
        "description": "Search the active inventory by name, Azure type, workload/module, and region. Returns real resource IDs.",
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "contains": {"type": "string"}, "resource_type": {"type": "string"},
                "module": {"type": "string", "enum": ["network", "application", "data", "identity", "supporting", ""]},
                "region": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 25},
                "offset": {"type": "integer", "minimum": 0, "maximum": 1500},
            }, "required": ["contains", "resource_type", "module", "region", "limit", "offset"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function", "name": "get_neighbors",
        "description": "Read resources directly connected to a resource in the inferred dependency graph.",
        "strict": True,
        "parameters": {
            "type": "object", "properties": {
                "resource_id": {"type": "string"},
                "direction": {"type": "string", "enum": ["both", "dependencies", "dependents"]},
            }, "required": ["resource_id", "direction"], "additionalProperties": False,
        },
    },
    {
        "type": "function", "name": "impact_of",
        "description": "Walk reverse dependency links to find resources that may be affected if a resource is removed. This is an inventory graph estimate, not an execution plan.",
        "strict": True,
        "parameters": {
            "type": "object", "properties": {
                "resource_id": {"type": "string"}, "max_depth": {"type": "integer", "minimum": 1, "maximum": 4},
            }, "required": ["resource_id", "max_depth"], "additionalProperties": False,
        },
    },
    {
        "type": "function", "name": "get_findings",
        "description": "Read inventory findings and cite their exact resource IDs.",
        "strict": True,
        "parameters": {
            "type": "object", "properties": {
                "resource_id": {"type": "string"},
                "severity": {"type": "string", "enum": ["", "critical", "high", "medium", "low"]},
                "limit": {"type": "integer", "minimum": 1, "maximum": 25},
            }, "required": ["resource_id", "severity", "limit"], "additionalProperties": False,
        },
    },
    {
        "type": "function", "name": "get_estate_summary",
        "description": "Read inventory counts, workload groups, and Terraform coverage for the active discovery run.",
        "strict": True,
        "parameters": {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
    },
    {
        "type": "function", "name": "get_unmapped_resources",
        "description": "List resources the Terraform generator or bounded writer did not emit, with the recorded reason and real resource ID.",
        "strict": True,
        "parameters": {"type": "object", "properties": {
            "resource_type": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 25},
        }, "required": ["resource_type", "limit"], "additionalProperties": False},
    },
]


def _safe_resource(resource: dict[str, Any]) -> dict[str, Any]:
    props = resource.get("properties", {}) if isinstance(resource.get("properties"), dict) else {}
    tags = resource.get("tags", {}) if isinstance(resource.get("tags"), dict) else {}

    def redact(value: Any, depth: int = 0) -> Any:
        if depth > 2:
            return "[truncated]"
        if isinstance(value, dict):
            return {
                str(key): "[REDACTED]" if any(word in str(key).lower() for word in ("secret", "password", "token", "key", "connectionstring", "sas")) else redact(item, depth + 1)
                for key, item in list(value.items())[:16]
            }
        if isinstance(value, list):
            return [redact(item, depth + 1) for item in value[:8]]
        if isinstance(value, str):
            return value[:180]
        if value is None or isinstance(value, (bool, int, float)):
            return value
        return str(value)[:180]

    return {
        "resource_id": str(resource.get("id", "")),
        "name": str(resource.get("name", ""))[:160],
        "type": str(resource.get("type", ""))[:180],
        "provider": str(resource.get("provider", ""))[:30],
        "region": str(resource.get("region", ""))[:80],
        "resource_group": str(resource.get("resource_group", ""))[:100],
        "module": str(resource.get("module", "supporting")),
        "tags": redact(tags),
        "properties": redact(props),
    }


class EstateTools:
    """Per-run tool registry with exact ID validation and bounded output."""

    def __init__(self, run: dict[str, Any], max_tool_calls: int | None = None, max_seconds: float = 90.0):
        self.started_at = time.monotonic()
        self.max_tool_calls = max_tool_calls
        self.max_seconds = max_seconds
        environment = run.get("environment", {})
        self.resources = environment.get("resources", []) if isinstance(environment, dict) else []
        self.edges = environment.get("relationships", []) if isinstance(environment, dict) else []
        self.dependencies: dict[str, list[dict[str, Any]]] = {}
        self.dependents: dict[str, list[dict[str, Any]]] = {}
        for edge in self.edges:
            self.dependencies.setdefault(str(edge.get("source", "")).casefold(), []).append(edge)
            self.dependents.setdefault(str(edge.get("target", "")).casefold(), []).append(edge)
        self.findings = run.get("findings", [])
        self.skipped = run.get("skipped", [])
        self.summary = run.get("summary", {}) if isinstance(run.get("summary"), dict) else {}
        self.modules = run.get("modules", []) if isinstance(run.get("modules"), list) else []
        self.by_id = {str(item.get("id", "")).casefold(): item for item in self.resources if item.get("id")}
        self.findings_by_id = {str(item.get("id", "")): item for item in self.findings if item.get("id")}
        self.name_to_id: dict[str, str] = {}
        for resource in self.resources:
            self.name_to_id.setdefault(str(resource.get("name", "")).casefold(), str(resource.get("id", "")))
        self.trace: list[dict[str, Any]] = []
        self.used_resource_ids: set[str] = set()
        self.functions: dict[str, Callable[..., dict[str, Any]]] = {
            "list_resources": self.list_resources,
            "get_neighbors": self.get_neighbors,
            "impact_of": self.impact_of,
            "get_findings": self.get_findings,
            "get_estate_summary": self.get_estate_summary,
            "get_unmapped_resources": self.get_unmapped_resources,
        }

    def has_resource(self, resource_id: str) -> bool:
        return resource_id.casefold() in self.by_id

    @property
    def tool_calls_remaining(self) -> int:
        return 1_000_000 if self.max_tool_calls is None else max(0, self.max_tool_calls - len(self.trace))

    def _resource(self, resource_id: str) -> dict[str, Any] | None:
        return self.by_id.get(resource_id.casefold())

    def execute(self, name: str, raw_arguments: Any) -> dict[str, Any]:
        if self.tool_calls_remaining <= 0:
            return {"error": "Read-only tool-call limit reached."}
        if time.monotonic() - self.started_at >= self.max_seconds:
            self.trace.append({"tool": name or "unknown", "arguments": raw_arguments if isinstance(raw_arguments, dict) else {}, "result": "Rejected: read-only tool time limit reached."})
            return {"error": "Read-only tool time limit reached."}
        fn = self.functions.get(name)
        if not fn:
            self.trace.append({"tool": name or "unknown", "arguments": raw_arguments if isinstance(raw_arguments, dict) else {}, "result": "Rejected: tool is not allow-listed."})
            return {"error": "Tool is not allow-listed."}
        if not isinstance(raw_arguments, dict):
            self.trace.append({"tool": name, "arguments": {}, "result": "Rejected: arguments were not a JSON object."})
            return {"error": "Tool arguments must be a JSON object."}
        try:
            result = fn(**raw_arguments)
            def collect_ids(value: Any) -> None:
                if isinstance(value, dict):
                    resource_id = value.get("resource_id")
                    if isinstance(resource_id, str) and self.has_resource(resource_id):
                        self.used_resource_ids.add(self._resource(resource_id)["id"])
                    for child in value.values():
                        collect_ids(child)
                elif isinstance(value, list):
                    for child in value:
                        collect_ids(child)
            collect_ids(result)
            count = result.get("count", len(result.get("items", [])) if isinstance(result.get("items"), list) else "summary")
            self.trace.append({"tool": name, "arguments": raw_arguments, "result": f"Returned {count} evidence record(s)."})
            return result
        except (TypeError, ValueError) as error:
            self.trace.append({"tool": name, "arguments": raw_arguments, "result": f"Rejected invalid arguments: {str(error)[:140]}"})
            return {"error": "Arguments did not match the read-only tool contract."}

    def list_resources(
        self, contains: str = "", resource_type: str = "", module: str = "", region: str = "", limit: int = 25, offset: int = 0
    ) -> dict[str, Any]:
        limit = max(1, min(int(limit), 25))
        offset = max(0, min(int(offset), 1500))
        query = contains.casefold().strip()
        exact_type = resource_type.casefold().strip()
        exact_module = module.casefold().strip()
        exact_region = region.casefold().strip()
        matches = []
        for resource in self.resources:
            if query and query not in f"{resource.get('name', '')} {resource.get('id', '')}".casefold():
                continue
            if exact_type and exact_type != str(resource.get("type", "")).casefold():
                continue
            if exact_module and exact_module != str(resource.get("module", "supporting")).casefold():
                continue
            if exact_region and exact_region != str(resource.get("region", "")).casefold():
                continue
            matches.append(resource)
        matches.sort(key=lambda item: (str(item.get("name", "")).casefold(), str(item.get("id", "")).casefold()))
        return {"count": len(matches), "offset": offset, "items": [_safe_resource(item) for item in matches[offset:offset + limit]]}

    def get_neighbors(self, resource_id: str, direction: str = "both") -> dict[str, Any]:
        if direction not in {"both", "dependencies", "dependents"}:
            raise ValueError("Unknown graph direction.")
        resource = self._resource(resource_id)
        if not resource:
            return {"count": 0, "items": [], "error": "Resource ID is not in this inventory."}
        canonical = str(resource["id"])
        neighbors = []
        candidates = []
        if direction in {"both", "dependencies"}:
            candidates.extend(self.dependencies.get(canonical.casefold(), []))
        if direction in {"both", "dependents"}:
            candidates.extend(self.dependents.get(canonical.casefold(), []))
        for edge in candidates:
            source = str(edge.get("source", ""))
            target = str(edge.get("target", ""))
            # The source uses or is contained by the target: target is a dependency.
            if direction in {"both", "dependencies"} and source.casefold() == canonical.casefold():
                other_id, relation, relation_direction = target, edge.get("relation", "related_to"), "dependency"
            elif direction in {"both", "dependents"} and target.casefold() == canonical.casefold():
                other_id, relation, relation_direction = source, edge.get("relation", "related_to"), "dependent"
            else:
                continue
            other = self._resource(other_id)
            if other:
                neighbors.append({"relation": relation, "direction": relation_direction, **_safe_resource(other)})
        deduped = {(item["resource_id"].casefold(), item["relation"], item["direction"]): item for item in neighbors}
        items = sorted(deduped.values(), key=lambda item: (item["direction"], item["name"].casefold()))[:25]
        return {"resource_id": canonical, "count": len(items), "items": items}

    def impact_of(self, resource_id: str, max_depth: int = 3) -> dict[str, Any]:
        if not 1 <= int(max_depth) <= 4:
            raise ValueError("Impact depth must be between 1 and 4.")
        resource = self._resource(resource_id)
        if not resource:
            return {"resource_id": resource_id, "count": 0, "items": [], "error": "Resource ID is not in this inventory."}
        canonical = str(resource["id"])
        distance = {canonical.casefold(): 0}
        queue: deque[str] = deque([canonical])
        impacts = []
        while queue:
            current = queue.popleft()
            depth = distance[current.casefold()]
            if depth >= int(max_depth):
                continue
            for edge in self.dependents.get(current.casefold(), []):
                # If a dependency target is removed, the source that uses it may be impacted.
                dependent = self._resource(str(edge.get("source", "")))
                if not dependent:
                    continue
                key = str(dependent["id"]).casefold()
                if key in distance:
                    continue
                distance[key] = depth + 1
                queue.append(str(dependent["id"]))
                impacts.append({"depth": depth + 1, "relation": edge.get("relation", "depends_on"), **_safe_resource(dependent)})
        impacts.sort(key=lambda item: (item["depth"], item["name"].casefold()))
        return {"resource_id": canonical, "max_depth": int(max_depth), "count": len(impacts), "items": impacts[:50]}

    def get_findings(self, resource_id: str = "", severity: str = "", limit: int = 25) -> dict[str, Any]:
        limit = max(1, min(int(limit), 25))
        if resource_id and not self.has_resource(resource_id):
            return {"count": 0, "items": [], "error": "Resource ID is not in this inventory."}
        items = []
        for finding in self.findings:
            resolved_id = str(finding.get("resource_id", "")) or self.name_to_id.get(str(finding.get("resource", "")).casefold(), "")
            if resource_id and resolved_id.casefold() != resource_id.casefold():
                continue
            if severity and str(finding.get("severity", "")).casefold() != severity.casefold():
                continue
            items.append({
                "finding_id": str(finding.get("id", "")), "resource_id": resolved_id,
                "resource": str(finding.get("resource", "Inventory")), "severity": str(finding.get("severity", "medium")),
                "title": str(finding.get("title", "Finding"))[:180], "detail": str(finding.get("detail", ""))[:420],
            })
        items.sort(key=lambda item: ({"critical": 0, "high": 1, "medium": 2, "low": 3}.get(item["severity"], 4), item["resource"].casefold()))
        return {"count": len(items), "items": items[:limit]}

    def get_estate_summary(self) -> dict[str, Any]:
        counts: dict[str, int] = {}
        for resource in self.resources:
            module = str(resource.get("module", "supporting"))
            counts[module] = counts.get(module, 0) + 1
        return {
            "resource_count": len(self.resources), "relationship_count": len(self.edges),
            "module_counts": counts,
            "terraform_resources": self.summary.get("terraform_resources"),
            "terraform_coverage_percent": self.summary.get("coverage"),
            "finding_count": len(self.findings), "unmapped_count": self.summary.get("skipped"),
            "evidence_resources": [_safe_resource(item) for item in self.resources[:5]],
        }

    def get_unmapped_resources(self, resource_type: str = "", limit: int = 25) -> dict[str, Any]:
        limit = max(1, min(int(limit), 25))
        requested_type = resource_type.casefold().strip()
        items = []
        for skipped in self.skipped:
            if requested_type and requested_type != str(skipped.get("type", "")).casefold():
                continue
            resource_id = str(skipped.get("id", ""))
            if not self.has_resource(resource_id):
                continue
            items.append({
                "resource_id": self._resource(resource_id)["id"], "name": str(skipped.get("name", "")),
                "type": str(skipped.get("type", "")), "reason": str(skipped.get("reason", ""))[:300],
                "writer_status": str(skipped.get("writer_status", "not_attempted")),
            })
        return {"count": len(items), "items": items[:limit]}

    def trace_copy(self) -> list[dict[str, Any]]:
        return json.loads(json.dumps(self.trace, ensure_ascii=False))


def known_resource_ids(run: dict[str, Any]) -> set[str]:
    environment = run.get("environment", {})
    resources = environment.get("resources", []) if isinstance(environment, dict) else []
    return {str(item.get("id", "")) for item in resources if item.get("id")}
