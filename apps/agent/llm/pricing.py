"""Per-model prices for cost tracking (USD per 1M tokens, Anthropic first-party API).

Source: the Claude API model table, cached 2026-11-03. Prices change; check before quoting
cost numbers in a report. Unknown models return ``None`` instead of a guessed cost.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from apps.agent.llm.base import Usage

PRICES_AS_OF = "2026-11-03"
_MTOK = Decimal(1_000_000)


@dataclass(frozen=True)
class ModelPrice:
    input: Decimal
    output: Decimal
    cache_read: Decimal | None = None  # None: fall back to the input price

    def cache_write(self) -> Decimal:
        # 5-minute cache writes bill at 1.25x the input price.
        return self.input * Decimal("1.25")


PRICES: dict[str, ModelPrice] = {
    "claude-opus-5-5": ModelPrice(Decimal("4.00"), Decimal("20.00"), Decimal("0.20")),
    "claude-sonnet-5-5": ModelPrice(Decimal("2.00"), Decimal("10.00"), Decimal("0.10")),
    # Up to 100K-token prompts; longer prompts are billed higher.
    "claude-haiku-5-5": ModelPrice(Decimal("0.10"), Decimal("0.50")),
}


def estimate_cost_usd(model: str, usage: Usage) -> Decimal | None:
    price = PRICES.get(model)
    if price is None:
        return None
    cache_read = price.cache_read if price.cache_read is not None else price.input
    total = (
        usage.input_tokens * price.input
        + usage.output_tokens * price.output
        + usage.cache_read_input_tokens * cache_read
        + usage.cache_creation_input_tokens * price.cache_write()
    ) / _MTOK
    return total.quantize(Decimal("0.000001"))
