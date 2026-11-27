"""Provider-neutral LLM types. The agent loop only ever sees these, never an SDK object.

A provider turns ``(messages, tools, config)`` into an ``LLMResponse``. Anything a provider
needs to replay later (e.g. Anthropic thinking blocks, which must be sent back unchanged)
travels in ``ProviderState`` — opaque to the agent, owned by the provider that wrote it.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field


class Role(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"  # the result of a tool call, sent back to the model


class ToolSpec(BaseModel):
    """A tool the model may call. ``input_schema`` is JSON Schema (generated from pydantic in B-04)."""

    model_config = ConfigDict(frozen=True)

    name: str
    description: str
    input_schema: dict[str, Any]
    # Anthropic strict tool use: the API guarantees inputs match the schema exactly.
    # Requires additionalProperties=false and a complete `required` list in the schema.
    strict: bool = False


class ToolCall(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class ProviderState(BaseModel):
    """Raw provider content kept for replay. Only the provider that wrote it reads it."""

    model_config = ConfigDict(frozen=True)

    provider: str
    model: str
    blocks: list[dict[str, Any]]


class LLMMessage(BaseModel):
    role: Role
    content: str = ""
    # Assistant turn: the calls the model asked for.
    tool_calls: list[ToolCall] = Field(default_factory=list)
    # Tool turn: which call this is the result of, and whether the tool failed.
    tool_call_id: str | None = None
    is_error: bool = False
    provider_state: ProviderState | None = None

    @classmethod
    def user(cls, text: str) -> LLMMessage:
        return cls(role=Role.USER, content=text)

    @classmethod
    def tool_result(cls, call_id: str, content: str, *, is_error: bool = False) -> LLMMessage:
        return cls(role=Role.TOOL, tool_call_id=call_id, content=content, is_error=is_error)


class StopReason(StrEnum):
    END_TURN = "end_turn"  # final answer
    TOOL_USE = "tool_use"  # run the tools and call again
    MAX_TOKENS = "max_tokens"  # output was cut off
    REFUSAL = "refusal"  # the model (or its safety layer) declined; the loop should hand off
    OTHER = "other"


class Usage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return (
            self.input_tokens
            + self.output_tokens
            + self.cache_read_input_tokens
            + self.cache_creation_input_tokens
        )


class LLMResponse(BaseModel):
    text: str = ""
    tool_calls: list[ToolCall] = Field(default_factory=list)
    stop_reason: StopReason
    usage: Usage = Field(default_factory=Usage)
    latency_ms: int = 0
    provider: str
    model: str
    refusal_category: str | None = None
    provider_state: ProviderState | None = None

    def as_message(self) -> LLMMessage:
        """The assistant turn to append to the history before the next call."""
        return LLMMessage(
            role=Role.ASSISTANT,
            content=self.text,
            tool_calls=list(self.tool_calls),
            provider_state=self.provider_state,
        )


Effort = Literal["low", "medium", "high", "xhigh", "max"]


class CompletionConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    model: str
    system: str = ""
    max_tokens: int = 16_000
    timeout_s: float = 60.0
    # Set explicitly: on Claude Opus 5.5 the API default is "medium".
    effort: Effort | None = "medium"


class LLMProvider(Protocol):
    name: str

    def complete(
        self, messages: list[LLMMessage], tools: list[ToolSpec], config: CompletionConfig
    ) -> LLMResponse: ...
