"""AnthropicProvider: Claude via the official SDK, normalized to the gateway types.

Decisions (see docs/DECISIONS.md, ADR-005):
- the SDK client is created with ``max_retries=0``; RetryingProvider is the only retry layer;
- no ``thinking`` parameter: thinking is always on for Claude Opus 5.5, depth is set by effort;
- ``tool_choice`` stays "auto" (forced tool choice returns a 400 on current models);
- server-side refusal fallbacks are on by default (``fallbacks="default"``); a refusal that
  still comes back is reported as StopReason.REFUSAL, not raised;
- the assistant's raw content blocks are kept in ProviderState and sent back unchanged,
  because thinking blocks must be replayed as they were returned.
"""

from __future__ import annotations

import time
from typing import Any

import anthropic
from django.conf import settings

from apps.agent.llm.base import (
    CompletionConfig,
    LLMMessage,
    LLMResponse,
    ProviderState,
    Role,
    StopReason,
    ToolCall,
    ToolSpec,
    Usage,
)
from apps.agent.llm.errors import (
    LLMError,
    LLMPermanentError,
    LLMRateLimitError,
    LLMTimeoutError,
    LLMTransientError,
)

PROVIDER_NAME = "anthropic"
FALLBACK_BETA = "server-side-fallback-2026-07-01"

# Block types that must not be echoed when they precede the last `fallback` block
# (they belong to the model that declined mid-output).
_PRE_FALLBACK_DROP = {"thinking", "redacted_thinking", "tool_use"}

_STOP_REASONS = {
    "end_turn": StopReason.END_TURN,
    "stop_sequence": StopReason.END_TURN,
    "tool_use": StopReason.TOOL_USE,
    "max_tokens": StopReason.MAX_TOKENS,
    "refusal": StopReason.REFUSAL,
}


class AnthropicProvider:
    name = PROVIDER_NAME

    def __init__(self, client: Any, *, use_fallbacks: bool = True) -> None:
        self._client = client
        self._use_fallbacks = use_fallbacks

    @classmethod
    def from_settings(cls) -> AnthropicProvider:
        # An empty key lets the SDK resolve credentials itself (env var or `ant auth login` profile).
        api_key = getattr(settings, "ANTHROPIC_API_KEY", "") or None
        return cls(anthropic.Anthropic(api_key=api_key, max_retries=0))

    def complete(
        self, messages: list[LLMMessage], tools: list[ToolSpec], config: CompletionConfig
    ) -> LLMResponse:
        request = self._build_request(messages, tools, config)
        started = time.perf_counter()
        try:
            message = self._client.beta.messages.create(**request)
        except anthropic.APIError as error:
            raise to_llm_error(error) from error
        latency_ms = int((time.perf_counter() - started) * 1000)
        return self._to_response(message, latency_ms)

    # --- request ---------------------------------------------------------------------------

    def _build_request(
        self, messages: list[LLMMessage], tools: list[ToolSpec], config: CompletionConfig
    ) -> dict[str, Any]:
        request: dict[str, Any] = {
            "model": config.model,
            "max_tokens": config.max_tokens,
            "messages": to_anthropic_messages(messages, model=config.model),
            "timeout": config.timeout_s,
        }
        if config.system:
            request["system"] = config.system
        if tools:
            request["tools"] = [_tool_param(t) for t in tools]
        if config.effort:
            request["output_config"] = {"effort": config.effort}
        if self._use_fallbacks:
            request["betas"] = [FALLBACK_BETA]
            request["fallbacks"] = "default"
        return request

    # --- response --------------------------------------------------------------------------

    def _to_response(self, message: Any, latency_ms: int) -> LLMResponse:
        blocks = [b.model_dump(mode="json", by_alias=True, exclude_none=True) for b in message.content]
        replay = replayable_blocks(blocks)
        text = "".join(b.get("text", "") for b in replay if b.get("type") == "text")
        tool_calls = [
            ToolCall(id=b["id"], name=b["name"], arguments=dict(b.get("input") or {}))
            for b in replay
            if b.get("type") == "tool_use"
        ]
        usage = message.usage
        stop_details = getattr(message, "stop_details", None)
        return LLMResponse(
            text=text,
            tool_calls=tool_calls,
            stop_reason=_STOP_REASONS.get(message.stop_reason or "", StopReason.OTHER),
            usage=Usage(
                input_tokens=usage.input_tokens or 0,
                output_tokens=usage.output_tokens or 0,
                cache_read_input_tokens=getattr(usage, "cache_read_input_tokens", None) or 0,
                cache_creation_input_tokens=getattr(usage, "cache_creation_input_tokens", None) or 0,
            ),
            latency_ms=latency_ms,
            provider=PROVIDER_NAME,
            # The model that actually answered (differs from the request after a fallback).
            model=message.model,
            refusal_category=getattr(stop_details, "category", None) if stop_details else None,
            provider_state=ProviderState(provider=PROVIDER_NAME, model=message.model, blocks=replay),
        )


# --- conversions (module-level so tests can call them directly) ---------------------------------


def _tool_param(tool: ToolSpec) -> dict[str, Any]:
    param: dict[str, Any] = {
        "name": tool.name,
        "description": tool.description,
        "input_schema": tool.input_schema,
    }
    if tool.strict:
        param["strict"] = True
    return param


def replayable_blocks(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Content to keep for the next request, per the refusal-fallback echo rules."""
    last_fallback = max((i for i, b in enumerate(blocks) if b.get("type") == "fallback"), default=-1)
    return [b for i, b in enumerate(blocks) if i >= last_fallback or b.get("type") not in _PRE_FALLBACK_DROP]


def to_anthropic_messages(messages: list[LLMMessage], *, model: str) -> list[dict[str, Any]]:
    """Gateway messages -> Messages API ``messages``.

    Consecutive tool results are merged into ONE user message: splitting parallel tool
    results across messages teaches the model to stop making parallel calls.
    """
    out: list[dict[str, Any]] = []
    for message in messages:
        match message.role:
            case Role.USER:
                out.append({"role": "user", "content": message.content})
            case Role.ASSISTANT:
                out.append({"role": "assistant", "content": _assistant_content(message)})
            case Role.TOOL:
                result = {
                    "type": "tool_result",
                    "tool_use_id": message.tool_call_id,
                    "content": message.content,
                }
                if message.is_error:
                    result["is_error"] = True
                previous = out[-1] if out else None
                if previous and previous["role"] == "user" and _is_tool_results(previous["content"]):
                    previous["content"].append(result)
                else:
                    out.append({"role": "user", "content": [result]})
    return out


def _is_tool_results(content: Any) -> bool:
    return isinstance(content, list) and all(b.get("type") == "tool_result" for b in content)


def _assistant_content(message: LLMMessage) -> list[dict[str, Any]]:
    state = message.provider_state
    if state is not None and state.provider == PROVIDER_NAME:
        # Send back exactly what the API returned (thinking blocks included). Blocks a
        # different model can't read are dropped by the API itself, unbilled.
        return [dict(b) for b in state.blocks]
    blocks: list[dict[str, Any]] = []
    if message.content:
        blocks.append({"type": "text", "text": message.content})
    blocks.extend(
        {"type": "tool_use", "id": c.id, "name": c.name, "input": c.arguments} for c in message.tool_calls
    )
    return blocks


def to_llm_error(error: anthropic.APIError) -> LLMError:
    """The single place where SDK exceptions become gateway errors."""
    # Order matters: most specific first (APITimeoutError is an APIConnectionError).
    if isinstance(error, anthropic.APITimeoutError):
        return LLMTimeoutError("anthropic request timed out", provider=PROVIDER_NAME)
    if isinstance(error, anthropic.APIConnectionError):
        return LLMTransientError("could not reach the anthropic API", provider=PROVIDER_NAME)
    if isinstance(error, anthropic.RateLimitError):
        return LLMRateLimitError(
            "anthropic rate limit",
            provider=PROVIDER_NAME,
            retry_after_s=_retry_after(error),
        )
    if isinstance(error, anthropic.APIStatusError):
        status = error.status_code
        # 409 is retried by the SDK's own policy too; 5xx covers 500/503/504/529 (overloaded).
        if status == 409 or status >= 500:
            return LLMTransientError(
                f"anthropic server error {status}", provider=PROVIDER_NAME, status_code=status
            )
        return LLMPermanentError(
            f"anthropic rejected the request ({status}): {error.message}",
            provider=PROVIDER_NAME,
            status_code=status,
        )
    return LLMPermanentError(f"anthropic error: {error}", provider=PROVIDER_NAME)


def _retry_after(error: anthropic.APIStatusError) -> float | None:
    raw = error.response.headers.get("retry-after")
    try:
        return float(raw) if raw is not None else None
    except ValueError:
        return None
