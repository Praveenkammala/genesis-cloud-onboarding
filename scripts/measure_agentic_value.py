"""Measure deterministic GENESIS coverage and evidence on both included Azure estates.

This is a local demo benchmark. It never calls Azure or Azure OpenAI.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))
os.environ["GENESIS_DISABLE_MODEL"] = "true"

from main import analyze_inventory  # noqa: E402


def measure(inventory: dict) -> dict:
    started = time.perf_counter()
    result = analyze_inventory(inventory)
    wall_seconds = round(time.perf_counter() - started, 4)
    investigation = result["investigation"]
    reviewer = result["agent_review"]
    tool_calls = len(investigation.get("tool_calls", [])) + len(reviewer.get("tool_calls", []))
    checks = reviewer.get("citation_checks", {})
    cited = int(checks.get("cited_items", 0))
    valid = int(checks.get("valid_citations", 0))
    citation_share = round(valid / cited, 4) if cited else 1.0
    return {
        "estate": inventory["name"],
        "synthetic": bool(inventory.get("synthetic", False)),
        "resources": result["summary"]["resources"],
        "resource_block_coverage_before_writer_percent": result["summary"]["coverage_before_writer"],
        "resource_block_coverage_after_writer_percent": result["summary"]["coverage"],
        "generated_terraform_types_before_writer": result["summary"]["terraform_types_before_writer"],
        "generated_terraform_types_after_writer": result["summary"]["terraform_types_after_writer"],
        "terraform_writer_drafts": [
            {"type": item["source_type"], "status": item["status"], "provenance": item["provenance"], "attempts": item["attempts"]}
            for item in result["terraform_drafts"]
        ],
        "investigator_tool_calls": len(investigation.get("tool_calls", [])),
        "reviewer_tool_calls": len(reviewer.get("tool_calls", [])),
        "tool_calls_used": tool_calls,
        "reviewer_citations_checked": cited,
        "reviewer_citations_valid": valid,
        "citation_valid_share": citation_share,
        "analysis_seconds": result["summary"]["analysis_seconds"],
        "wall_seconds": wall_seconds,
    }


def main() -> None:
    from azure_sample_inventory import AZURE_SAMPLE_INVENTORY
    report = {
        "benchmark": "GENESIS offline demo; fictional estate data; no Azure or model service calls",
        "estates": [],
    }
    synthetic = json.loads((ROOT / "samples" / "kyndryl-synthetic-estate.json").read_text(encoding="utf-8"))
    report["estates"] = [measure(AZURE_SAMPLE_INVENTORY), measure(synthetic)]
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
