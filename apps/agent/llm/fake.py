"""FakeProvider: deterministic, no network. Used by every agent test and the eval runner in CI.

Two modes:
- scripted: replays a list of steps in order (a response, or an exception to raise);
- echo (no script): answers with the last user message, so the app runs without an API key.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from apps.agent.llm.base import (
    CompletionConfig,
    LLMMessage,
    LLMResponse,
    Role,
    StopReason,
    ToolCall,
    ToolSpec,
    Usage,
)

FAKE_PROVIDER_NAME = "fake"

Step = LLMResponse | Exception


@dataclass(frozen=True)
class FakeCall:
    """What the provider was asked: tests assert on this."""

    messages: list[LLMMessage]
    tools: list[ToolSpec]
    config: CompletionConfig


class FakeScriptExhaustedError(AssertionError):
    """The code under test made more model calls than the scenario planned for."""


@dataclass
class FakeProvider:
    script: list[Step] | None = None
    calls: list[FakeCall] = field(default_factory=list)
    name: str = FAKE_PROVIDER_NAME

    @classmethod
    def scripted(cls, steps: Iterable[Step]) -> FakeProvider:
        return cls(script=list(steps))

    def complete(
        self, messages: list[LLMMessage], tools: list[ToolSpec], config: CompletionConfig
    ) -> LLMResponse:
        self.calls.append(FakeCall(list(messages), list(tools), config))
        if self.script is None:
            return self._echo(messages, config)
        if not self.script:
            raise FakeScriptExhaustedError(f"FakeProvider script exhausted after {len(self.calls) - 1} calls")
        step = self.script.pop(0)
        if isinstance(step, Exception):
            raise step
        return step.model_copy(update={"model": config.model or step.model})

    def _echo(self, messages: list[LLMMessage], config: CompletionConfig) -> LLMResponse:
        last_user = next((m.content for m in reversed(messages) if m.role is Role.USER), "")
        return fake_text(f"(fake) You said: {last_user}", model=config.model)


def _usage(text: str) -> Usage:
    # Rough and deterministic: enough for budget tests, no tokenizer needed.
    return Usage(input_tokens=10, output_tokens=max(1, len(text) // 4))


def fake_text(text: str, *, model: str = "fake-model") -> LLMResponse:
    return LLMResponse(
        text=text,
        stop_reason=StopReason.END_TURN,
        usage=_usage(text),
        provider=FAKE_PROVIDER_NAME,
        model=model,
    )


def fake_tool_call(
    name: str,
    arguments: dict[str, Any] | None = None,
    *,
    call_id: str | None = None,
    text: str = "",
    model: str = "fake-model",
) -> LLMResponse:
    return LLMResponse(
        text=text,
        tool_calls=[
            ToolCall(id=call_id or f"call_{uuid.uuid4().hex[:8]}", name=name, arguments=arguments or {})
        ],
        stop_reason=StopReason.TOOL_USE,
        usage=_usage(text or name),
        provider=FAKE_PROVIDER_NAME,
        model=model,
    )


def fake_refusal(*, category: str | None = None, model: str = "fake-model") -> LLMResponse:
    return LLMResponse(
        stop_reason=StopReason.REFUSAL,
        refusal_category=category,
        provider=FAKE_PROVIDER_NAME,
        model=model,
    )
