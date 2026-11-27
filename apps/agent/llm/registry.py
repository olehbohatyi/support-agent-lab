"""Build the provider for an AgentConfig. Switching provider is one field: ``AgentConfig.provider``."""

from __future__ import annotations

from apps.agent.llm.base import CompletionConfig, LLMProvider
from apps.agent.llm.fake import FakeProvider
from apps.agent.llm.retry import RetryingProvider, RetryPolicy
from apps.tenants.models import AgentConfig

DEFAULT_MODELS: dict[str, str] = {
    AgentConfig.Provider.FAKE: "fake-model",
    AgentConfig.Provider.ANTHROPIC: "claude-opus-5-5",
}


class UnknownProviderError(ValueError):
    pass


def build_provider(config: AgentConfig, *, retry_policy: RetryPolicy | None = None) -> LLMProvider:
    match config.provider:
        case AgentConfig.Provider.FAKE:
            inner: LLMProvider = FakeProvider()
        case AgentConfig.Provider.ANTHROPIC:
            # Imported lazily so tests and the fake path never construct an SDK client.
            from apps.agent.llm.anthropic import AnthropicProvider

            inner = AnthropicProvider.from_settings()
        case other:
            raise UnknownProviderError(f"unknown LLM provider {other!r}")
    return RetryingProvider(inner, policy=retry_policy or RetryPolicy())


def completion_config(config: AgentConfig) -> CompletionConfig:
    return CompletionConfig(
        model=config.model or DEFAULT_MODELS[config.provider],
        system=config.system_prompt,
    )
