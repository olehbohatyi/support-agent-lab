"""B-03: LLM gateway. Everything runs on FakeProvider or a stub SDK client — no network."""

from __future__ import annotations

import random
import socket
from decimal import Decimal
from typing import Any

import anthropic
import httpx2
import pytest
from anthropic.types.beta import BetaMessage

from apps.agent.llm.anthropic import (
    FALLBACK_BETA,
    AnthropicProvider,
    replayable_blocks,
    to_anthropic_messages,
    to_llm_error,
)
from apps.agent.llm.base import (
    CompletionConfig,
    LLMMessage,
    ProviderState,
    Role,
    StopReason,
    ToolCall,
    ToolSpec,
)
from apps.agent.llm.errors import (
    LLMPermanentError,
    LLMRateLimitError,
    LLMTimeoutError,
    LLMTransientError,
)
from apps.agent.llm.fake import FakeProvider, FakeScriptExhaustedError, fake_text, fake_tool_call
from apps.agent.llm.pricing import estimate_cost_usd
from apps.agent.llm.registry import build_provider, completion_config
from apps.agent.llm.retry import RetryingProvider, RetryPolicy
from apps.tenants.models import AgentConfig

CONFIG = CompletionConfig(model="claude-opus-5-5", system="You help customers.")
INVOICE_TOOL = ToolSpec(
    name="get_invoice_status",
    description="Look up an invoice of the current customer.",
    input_schema={
        "type": "object",
        "properties": {"invoice_number": {"type": "string"}},
        "required": ["invoice_number"],
        "additionalProperties": False,
    },
    strict=True,
)


# --- FakeProvider -----------------------------------------------------------------------------


def test_fake_provider_replays_text_tool_call_error_and_timeout_in_order() -> None:
    provider = FakeProvider.scripted(
        [
            fake_tool_call("get_invoice_status", {"invoice_number": "SM-R-9001"}, call_id="c1"),
            fake_text("Your invoice is open."),
            LLMTransientError("overloaded"),
            LLMTimeoutError("slow"),
        ]
    )
    messages = [LLMMessage.user("Wie ist der Status meiner Rechnung?")]

    first = provider.complete(messages, [INVOICE_TOOL], CONFIG)
    second = provider.complete(messages, [INVOICE_TOOL], CONFIG)

    assert first.stop_reason is StopReason.TOOL_USE
    assert first.tool_calls == [
        ToolCall(id="c1", name="get_invoice_status", arguments={"invoice_number": "SM-R-9001"})
    ]
    assert second.text == "Your invoice is open."
    with pytest.raises(LLMTransientError):
        provider.complete(messages, [], CONFIG)
    with pytest.raises(LLMTimeoutError):
        provider.complete(messages, [], CONFIG)
    assert len(provider.calls) == 4
    assert provider.calls[0].tools == [INVOICE_TOOL]


def test_fake_provider_fails_loudly_when_script_is_exhausted() -> None:
    provider = FakeProvider.scripted([fake_text("only one")])
    provider.complete([LLMMessage.user("hi")], [], CONFIG)

    with pytest.raises(FakeScriptExhaustedError):
        provider.complete([LLMMessage.user("again")], [], CONFIG)


def test_fake_provider_without_script_echoes_last_user_message() -> None:
    response = FakeProvider().complete([LLMMessage.user("Hallo")], [], CONFIG)

    assert response.text == "(fake) You said: Hallo"
    assert response.stop_reason is StopReason.END_TURN


def test_tests_cannot_reach_external_hosts() -> None:
    with socket.socket() as sock, pytest.raises(RuntimeError, match="external network"):
        sock.connect(("api.anthropic.com", 443))


# --- Retries ----------------------------------------------------------------------------------


def _retrying(steps: list[Any], **policy: Any) -> tuple[RetryingProvider, list[float]]:
    sleeps: list[float] = []
    provider = RetryingProvider(
        FakeProvider.scripted(steps),
        policy=RetryPolicy(jitter=False, **policy),
        sleep=sleeps.append,
        rng=random.Random(0),
    )
    return provider, sleeps


def test_transient_errors_are_retried_with_exponential_backoff() -> None:
    provider, sleeps = _retrying([LLMTransientError("503"), LLMTimeoutError("slow"), fake_text("ok")])

    response = provider.complete([LLMMessage.user("hi")], [], CONFIG)

    assert response.text == "ok"
    assert sleeps == [0.5, 1.0]


def test_permanent_errors_are_not_retried() -> None:
    provider, sleeps = _retrying([LLMPermanentError("bad request"), fake_text("never")])

    with pytest.raises(LLMPermanentError):
        provider.complete([LLMMessage.user("hi")], [], CONFIG)
    assert sleeps == []


def test_retries_stop_after_max_attempts() -> None:
    provider, sleeps = _retrying([LLMTransientError("a"), LLMTransientError("b"), LLMTransientError("c")])

    with pytest.raises(LLMTransientError, match="c"):
        provider.complete([LLMMessage.user("hi")], [], CONFIG)
    assert len(sleeps) == 2


def test_rate_limit_waits_for_retry_after_but_not_longer_than_max_delay() -> None:
    provider, sleeps = _retrying(
        [
            LLMRateLimitError("429", retry_after_s=3),
            LLMRateLimitError("429", retry_after_s=60),
            fake_text("ok"),
        ],
        max_delay_s=8.0,
    )

    provider.complete([LLMMessage.user("hi")], [], CONFIG)

    assert sleeps == [3, 8.0]


def test_full_jitter_stays_within_the_backoff_ceiling() -> None:
    policy = RetryPolicy(base_delay_s=1.0, max_delay_s=4.0, jitter=True)
    rng = random.Random(42)

    delays = [policy.delay_for(attempt, LLMTransientError("x"), rng) for attempt in range(1, 6)]

    assert all(0 <= d <= min(2 ** (i), 4.0) for i, d in enumerate(delays))


# --- Registry: switching provider is one field ------------------------------------------------


@pytest.mark.django_db
def test_provider_is_selected_by_agent_config_field(settings: Any) -> None:
    settings.ANTHROPIC_API_KEY = "test-key-not-real"
    config = AgentConfig(provider=AgentConfig.Provider.FAKE, system_prompt="p")

    fake = build_provider(config)
    config.provider = AgentConfig.Provider.ANTHROPIC
    real = build_provider(config)

    assert isinstance(fake, RetryingProvider) and isinstance(fake.inner, FakeProvider)
    assert isinstance(real, RetryingProvider) and isinstance(real.inner, AnthropicProvider)
    assert completion_config(config).model == "claude-opus-5-5"
    config.model = "claude-sonnet-5-5"
    assert completion_config(config).model == "claude-sonnet-5-5"


# --- AnthropicProvider: request and response normalization ------------------------------------


class _StubMessages:
    def __init__(self, response: BetaMessage | Exception) -> None:
        self.response = response
        self.requests: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> BetaMessage:
        self.requests.append(kwargs)
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


class _StubClient:
    def __init__(self, response: BetaMessage | Exception) -> None:
        self.messages = _StubMessages(response)
        self.beta = self


def _message(content: list[dict[str, Any]], stop_reason: str, **extra: Any) -> BetaMessage:
    return BetaMessage.model_validate(
        {
            "id": "msg_1",
            "type": "message",
            "role": "assistant",
            "model": "claude-opus-5-5",
            "stop_reason": stop_reason,
            "stop_sequence": None,
            "content": content,
            "usage": {"input_tokens": 120, "output_tokens": 40, "cache_read_input_tokens": 0},
            **extra,
        }
    )


TOOL_USE_CONTENT = [
    {"type": "thinking", "thinking": "", "signature": "sig-abc"},
    {"type": "text", "text": "Ich schaue nach."},
    {
        "type": "tool_use",
        "id": "toolu_1",
        "name": "get_invoice_status",
        "input": {"invoice_number": "SM-R-9001"},
    },
]


def test_anthropic_request_uses_current_api_conventions() -> None:
    client = _StubClient(_message([{"type": "text", "text": "Hallo!"}], "end_turn"))

    AnthropicProvider(client).complete([LLMMessage.user("Hallo")], [INVOICE_TOOL], CONFIG)

    request = client.messages.requests[0]
    assert request["model"] == "claude-opus-5-5"
    assert request["system"] == "You help customers."
    assert "thinking" not in request  # always on for Opus 5.5; effort controls depth
    assert "tool_choice" not in request  # forced tool choice is a 400 on current models
    assert request["output_config"] == {"effort": "medium"}
    assert request["betas"] == [FALLBACK_BETA] and request["fallbacks"] == "default"
    assert request["timeout"] == CONFIG.timeout_s
    assert request["tools"][0]["strict"] is True
    assert request["messages"] == [{"role": "user", "content": "Hallo"}]


def test_anthropic_response_is_normalized_and_keeps_thinking_for_replay() -> None:
    client = _StubClient(_message(TOOL_USE_CONTENT, "tool_use"))

    response = AnthropicProvider(client).complete([LLMMessage.user("Rechnung?")], [INVOICE_TOOL], CONFIG)

    assert response.stop_reason is StopReason.TOOL_USE
    assert response.text == "Ich schaue nach."
    assert response.tool_calls[0].name == "get_invoice_status"
    assert response.tool_calls[0].arguments == {"invoice_number": "SM-R-9001"}
    assert (response.usage.input_tokens, response.usage.output_tokens) == (120, 40)
    assert response.model == "claude-opus-5-5"
    assert response.provider_state is not None
    assert response.provider_state.blocks[0] == {"type": "thinking", "thinking": "", "signature": "sig-abc"}


def test_tool_round_trip_replays_assistant_blocks_unchanged_and_merges_tool_results() -> None:
    client = _StubClient(_message(TOOL_USE_CONTENT, "tool_use"))
    first = AnthropicProvider(client).complete([LLMMessage.user("Rechnung?")], [INVOICE_TOOL], CONFIG)

    history = [
        LLMMessage.user("Rechnung?"),
        first.as_message(),
        LLMMessage.tool_result("toolu_1", '{"status": "open"}'),
        LLMMessage.tool_result("toolu_2", "invoice not found", is_error=True),
    ]
    wire = to_anthropic_messages(history, model="claude-opus-5-5")

    assert wire[1] == {"role": "assistant", "content": first.provider_state.blocks}  # type: ignore[union-attr]
    assert wire[2]["role"] == "user"
    assert [b["tool_use_id"] for b in wire[2]["content"]] == ["toolu_1", "toolu_2"]  # one message
    assert wire[2]["content"][1]["is_error"] is True
    assert len(wire) == 3


def test_assistant_message_without_provider_state_is_rebuilt_from_fields() -> None:
    message = LLMMessage(
        role=Role.ASSISTANT,
        content="Moment.",
        tool_calls=[ToolCall(id="c1", name="handoff_to_human", arguments={"reason": "legal"})],
        provider_state=ProviderState(provider="fake", model="fake-model", blocks=[{"type": "x"}]),
    )

    wire = to_anthropic_messages([LLMMessage.user("?"), message], model="claude-opus-5-5")

    assert wire[1]["content"] == [
        {"type": "text", "text": "Moment."},
        {"type": "tool_use", "id": "c1", "name": "handoff_to_human", "input": {"reason": "legal"}},
    ]


def test_refusal_is_a_stop_reason_not_an_exception() -> None:
    message = _message(
        [],
        "refusal",
        stop_details={"type": "refusal", "category": "cyber", "explanation": "declined"},
    )

    response = AnthropicProvider(_StubClient(message)).complete([LLMMessage.user("?")], [], CONFIG)

    assert response.stop_reason is StopReason.REFUSAL
    assert response.refusal_category == "cyber"


def test_blocks_before_a_mid_output_fallback_are_not_replayed() -> None:
    blocks = [
        {"type": "thinking", "thinking": "", "signature": "a"},
        {"type": "text", "text": "partial "},
        {"type": "tool_use", "id": "t0", "name": "x", "input": {}},
        {"type": "fallback", "from": {"model": "m1"}, "to": {"model": "m2"}},
        {"type": "thinking", "thinking": "", "signature": "b"},
        {"type": "tool_use", "id": "t1", "name": "y", "input": {}},
    ]

    kept = replayable_blocks(blocks)

    assert [b["type"] for b in kept] == ["text", "fallback", "thinking", "tool_use"]
    assert kept[-1]["id"] == "t1"


# --- Error normalization ----------------------------------------------------------------------

_REQUEST = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")


def _status_error(
    cls: type[anthropic.APIStatusError], status: int, **headers: str
) -> anthropic.APIStatusError:
    return cls("error", response=httpx2.Response(status, request=_REQUEST, headers=headers), body=None)


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (anthropic.APITimeoutError(request=_REQUEST), LLMTimeoutError),
        (anthropic.APIConnectionError(request=_REQUEST), LLMTransientError),
        (_status_error(anthropic.InternalServerError, 500), LLMTransientError),
        (_status_error(anthropic.OverloadedError, 529), LLMTransientError),
        (_status_error(anthropic.ConflictError, 409), LLMTransientError),
        (_status_error(anthropic.BadRequestError, 400), LLMPermanentError),
        (_status_error(anthropic.AuthenticationError, 401), LLMPermanentError),
        (_status_error(anthropic.NotFoundError, 404), LLMPermanentError),
    ],
)
def test_sdk_errors_map_to_gateway_errors(error: anthropic.APIError, expected: type[Exception]) -> None:
    mapped = to_llm_error(error)

    assert type(mapped) is expected
    assert mapped.provider == "anthropic"


def test_rate_limit_error_carries_retry_after() -> None:
    mapped = to_llm_error(_status_error(anthropic.RateLimitError, 429, **{"retry-after": "7"}))

    assert isinstance(mapped, LLMRateLimitError)
    assert mapped.retry_after_s == 7.0


def test_provider_raises_gateway_errors_and_retry_layer_handles_them() -> None:
    client = _StubClient(_status_error(anthropic.OverloadedError, 529))
    sleeps: list[float] = []
    provider = RetryingProvider(
        AnthropicProvider(client), policy=RetryPolicy(max_attempts=2, jitter=False), sleep=sleeps.append
    )

    with pytest.raises(LLMTransientError):
        provider.complete([LLMMessage.user("?")], [], CONFIG)
    assert len(client.messages.requests) == 2
    assert sleeps == [0.5]


# --- Pricing ----------------------------------------------------------------------------------


def test_cost_estimate_for_known_and_unknown_models() -> None:
    usage = fake_text("x").usage.model_copy(update={"input_tokens": 1_000_000, "output_tokens": 100_000})

    assert estimate_cost_usd("claude-opus-5-5", usage) == Decimal("6.000000")  # 4.00 + 0.1 * 20.00
    assert estimate_cost_usd("some-unknown-model", usage) is None
