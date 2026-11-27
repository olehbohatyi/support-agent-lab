"""One real model call by hand (B-03 acceptance). Costs a fraction of a cent on a real provider."""

from django.core.management.base import BaseCommand, CommandError, CommandParser

from apps.agent.llm.base import CompletionConfig, LLMMessage
from apps.agent.llm.errors import LLMError
from apps.agent.llm.pricing import estimate_cost_usd
from apps.agent.llm.registry import DEFAULT_MODELS
from apps.agent.llm.retry import RetryingProvider
from apps.tenants.models import AgentConfig

SYSTEM = (
    "You are the customer support assistant of a German utility provider. "
    "Answer briefly, in the customer's language."
)
QUESTION = "Hallo, wie kann ich meinen Zählerstand übermitteln?"


class Command(BaseCommand):
    help = "Send one question to an LLM provider through the gateway and print the normalized response."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--provider", choices=[p.value for p in AgentConfig.Provider], default="anthropic"
        )
        parser.add_argument("--model", default="")
        parser.add_argument("--question", default=QUESTION)

    def handle(self, *args: object, **options: str) -> None:
        provider_name = options["provider"]
        if provider_name == AgentConfig.Provider.ANTHROPIC:
            from apps.agent.llm.anthropic import AnthropicProvider

            provider = RetryingProvider(AnthropicProvider.from_settings())
        else:
            from apps.agent.llm.fake import FakeProvider

            provider = RetryingProvider(FakeProvider())

        config = CompletionConfig(
            model=options["model"] or DEFAULT_MODELS[provider_name], system=SYSTEM, max_tokens=1024
        )
        try:
            response = provider.complete([LLMMessage.user(options["question"])], [], config)
        except LLMError as error:
            raise CommandError(f"{type(error).__name__}: {error}") from error

        cost = estimate_cost_usd(response.model, response.usage)
        self.stdout.write(response.text or "(no text)")
        self.stdout.write(
            f"\nprovider={response.provider} model={response.model} stop={response.stop_reason} "
            f"tokens in/out={response.usage.input_tokens}/{response.usage.output_tokens} "
            f"latency={response.latency_ms}ms cost=${cost if cost is not None else 'n/a'}"
        )
