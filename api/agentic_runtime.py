"""Bounded Azure OpenAI Responses API helpers used by GENESIS roles."""

from __future__ import annotations

import json
import os
import time
from typing import Any


MAX_RUN_SECONDS = 90.0
MAX_RUN_OUTPUT_TOKENS = 6000
MAX_MODEL_REQUESTS = 28


class ModelBudget:
    def __init__(self, seconds: float = MAX_RUN_SECONDS, output_tokens: int = MAX_RUN_OUTPUT_TOKENS):
        self.deadline = time.monotonic() + seconds
        self.tokens_left = output_tokens
        self.requests_left = MAX_MODEL_REQUESTS

    @property
    def seconds_left(self) -> float:
        return max(0.0, self.deadline - time.monotonic())

    def reserve(self, requested: int) -> int:
        if self.seconds_left <= 0:
            raise TimeoutError("The GENESIS model time budget was reached.")
        if self.requests_left <= 0:
            raise RuntimeError("The GENESIS model request budget was reached.")
        if self.tokens_left <= 0:
            raise RuntimeError("The GENESIS model output-token budget was reached.")
        limit = min(requested, self.tokens_left)
        self.tokens_left -= limit
        self.requests_left -= 1
        return limit

    def settle(self, reserved: int, response: Any) -> None:
        usage = getattr(response, "usage", None)
        actual = getattr(usage, "output_tokens", None) if usage is not None else None
        if isinstance(actual, int) and actual >= 0:
            self.tokens_left += max(0, reserved - actual)


def model_config() -> tuple[str, str]:
    if os.getenv("GENESIS_DISABLE_MODEL", "").strip().lower() in {"1", "true", "yes"}:
        return "", ""
    return os.getenv("AZURE_OPENAI_ENDPOINT", "").strip(), os.getenv("AZURE_OPENAI_CHAT_DEPLOYMENT", "").strip()


def model_is_configured() -> bool:
    endpoint, deployment = model_config()
    return bool(endpoint and deployment)


def make_client(endpoint: str, budget: ModelBudget, timeout: float = 16.0) -> Any:
    from azure.identity import DefaultAzureCredential, get_bearer_token_provider
    from openai import OpenAI

    token_provider = get_bearer_token_provider(
        DefaultAzureCredential(exclude_interactive_browser_credential=True),
        "https://ai.azure.com/.default",
    )
    return OpenAI(
        api_key=token_provider,
        base_url=f"{endpoint.rstrip('/')}/openai/v1/",
        timeout=max(1.0, min(timeout, budget.seconds_left)),
        max_retries=0,
    )


def create_response(client: Any, budget: ModelBudget, *, max_output_tokens: int = 700, **kwargs: Any) -> Any:
    reserved = budget.reserve(max_output_tokens)
    timeout_client = client.with_options(timeout=max(0.1, min(16.0, budget.seconds_left)))
    response = timeout_client.responses.create(max_output_tokens=reserved, store=False, **kwargs)
    budget.settle(reserved, response)
    return response


def response_tool_agent(
    *,
    system_prompt: str,
    user_prompt: str,
    registry: Any,
    tools: list[dict[str, Any]],
    output_schema: dict[str, Any],
    budget: ModelBudget,
    max_tool_calls: int,
    max_output_tokens: int = 800,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Run one serialized, allow-listed tool loop and return the schema-constrained final object."""
    endpoint, deployment = model_config()
    if not endpoint or not deployment:
        raise RuntimeError("Azure OpenAI endpoint and deployment are not configured.")
    client = make_client(endpoint, budget)
    conversation: list[Any] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    response = create_response(
        client, budget, max_output_tokens=max_output_tokens,
        model=deployment, input=conversation, tools=tools,
        tool_choice="auto", parallel_tool_calls=False, text=output_schema,
    )
    calls_used = 0
    while True:
        calls = [item for item in response.output if getattr(item, "type", "") == "function_call"]
        if not calls:
            break
        call_outputs = []
        for call in calls:
            if calls_used >= max_tool_calls:
                break
            calls_used += 1
            import json
            try:
                arguments = json.loads(str(getattr(call, "arguments", "{}")) or "{}")
            except json.JSONDecodeError:
                arguments = None
            result = registry.execute(str(getattr(call, "name", "")), arguments)
            call_outputs.append({
                "type": "function_call_output",
                "call_id": str(getattr(call, "call_id", "")),
                "output": json.dumps(result, ensure_ascii=False, separators=(",", ":")),
            })
        conversation.extend(item.model_dump(exclude_none=True) for item in response.output)
        conversation.extend(call_outputs)
        tools_enabled = calls_used < max_tool_calls
        response = create_response(
            client, budget, max_output_tokens=max_output_tokens,
            model=deployment, input=conversation,
            tools=tools if tools_enabled else [],
            tool_choice="auto" if tools_enabled else "none",
            parallel_tool_calls=False, text=output_schema,
        )
    import json
    payload = json.loads(str(getattr(response, "output_text", "") or "{}"))
    if not isinstance(payload, dict):
        raise ValueError("The model did not return a JSON object.")
    return payload, registry.trace_copy()


def probe_model() -> dict[str, Any]:
    """Exercise Entra auth, function calling, and structured output with a local no-op tool."""
    endpoint, deployment = model_config()
    if not endpoint or not deployment:
        return {"configured": False, "status": "not_configured", "deployment": None, "message": "Set AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_CHAT_DEPLOYMENT to enable the Azure OpenAI mode."}
    budget = ModelBudget(seconds=15, output_tokens=64)
    try:
        client = make_client(endpoint, budget, timeout=10)
        tool = {"type": "function", "name": "probe_read_only_status", "description": "Return local readiness.", "strict": True,
                "parameters": {"type": "object", "properties": {}, "required": [], "additionalProperties": False}}
        schema = {"format": {"type": "json_schema", "name": "genesis_model_probe", "strict": True, "schema": {
            "type": "object", "properties": {"status": {"type": "string", "enum": ["ready"]}},
            "required": ["status"], "additionalProperties": False,
        }}}
        conversation: list[Any] = [
            {"role": "system", "content": "Call probe_read_only_status once, then report status ready."},
            {"role": "user", "content": "Verify the GENESIS tool calling and structured output path."},
        ]
        first = create_response(
            client, budget, max_output_tokens=32, model=deployment, input=conversation,
            tools=[tool], tool_choice="required", parallel_tool_calls=False, text=schema,
        )
        calls = [item for item in first.output if getattr(item, "type", "") == "function_call"]
        if len(calls) != 1 or getattr(calls[0], "name", "") != "probe_read_only_status":
            raise ValueError("The deployment did not return the required function call.")
        call = calls[0]
        conversation.extend(item.model_dump(exclude_none=True) for item in first.output)
        conversation.append({"type": "function_call_output", "call_id": str(call.call_id), "output": json.dumps({"status": "ready"})})
        final = create_response(
            client, budget, max_output_tokens=32, model=deployment, input=conversation,
            tools=[tool], tool_choice="none", parallel_tool_calls=False, text=schema,
        )
        output = json.loads(str(getattr(final, "output_text", "") or "{}"))
        if output.get("status") != "ready":
            raise ValueError("The deployment did not honor the structured output schema.")
        return {"configured": True, "status": "ready", "deployment": deployment, "message": "Azure OpenAI is reachable with the current identity; Responses API function calling and structured output passed."}
    except Exception as error:
        status = _classify_model_error(error)
        return {"configured": True, "status": status, "deployment": deployment, "message": _safe_model_error(status)}


def _classify_model_error(error: Exception) -> str:
    text = f"{type(error).__name__} {error}".casefold()
    code = str(getattr(error, "status_code", ""))
    if code in {"401", "403"} or "credential" in text or "unauthorized" in text or "forbidden" in text or "authentication" in text:
        return "authentication_or_role_error"
    if code == "404" or "deploymentnotfound" in text or "not found" in text:
        return "deployment_or_region_error"
    if code == "429" or "quota" in text or "rate limit" in text or "capacity" in text or "too many requests" in text:
        return "quota_or_capacity_error"
    if any(word in text for word in ("function call", "tool call", "json schema", "structured output", "unsupported")):
        return "unsupported_model_features"
    if isinstance(error, TimeoutError) or "timeout" in text or "timed out" in text:
        return "timeout"
    return "connection_or_configuration_error"


def _safe_model_error(status: str) -> str:
    return {
        "authentication_or_role_error": "Azure OpenAI rejected the identity. Check managed identity or CLI sign-in and the Cognitive Services OpenAI User role on the model resource.",
        "deployment_or_region_error": "The endpoint or deployment was not found. Check the resource endpoint, deployment name, and model availability in that Azure region.",
        "quota_or_capacity_error": "The deployment is reachable but has no available quota or capacity. Check deployment quota, TPM/RPM, and regional capacity.",
        "unsupported_model_features": "The deployment did not accept the function-calling or strict structured-output features required by GENESIS. Check the selected model/version and Azure Responses API support.",
        "timeout": "The Azure OpenAI request exceeded the 10 second connection check.",
        "connection_or_configuration_error": "Azure OpenAI could not complete the request. Check endpoint format, network access, and v1 Responses API support.",
    }.get(status, "Azure OpenAI is unavailable.")
