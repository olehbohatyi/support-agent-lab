"""Retry with exponential backoff, only for transient errors.

This is the single retry layer: provider SDKs are created with their own retries off,
so a failing call is never retried twice over (SDK x ours).
"""

from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from apps.agent.llm.base import CompletionConfig, LLMMessage, LLMProvider, LLMResponse, ToolSpec
from apps.agent.llm.errors import LLMRateLimitError, LLMTransientError

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 3
    base_delay_s: float = 0.5
    max_delay_s: float = 8.0
    jitter: bool = True

    def delay_for(self, attempt: int, error: LLMTransientError, rng: random.Random) -> float:
        """Delay before attempt ``attempt + 1`` (attempt is 1-based)."""
        if isinstance(error, LLMRateLimitError) and error.retry_after_s is not None:
            return min(error.retry_after_s, self.max_delay_s)
        delay = min(self.base_delay_s * 2 ** (attempt - 1), self.max_delay_s)
        if self.jitter:
            # "Full jitter": spreads retries of many clients so they don't hit the API in sync.
            delay = rng.uniform(0, delay)
        return delay


@dataclass
class RetryingProvider:
    """Wraps any provider; same interface, plus retries on transient errors."""

    inner: LLMProvider
    policy: RetryPolicy = field(default_factory=RetryPolicy)
    sleep: Callable[[float], None] = time.sleep
    rng: random.Random = field(default_factory=random.Random)

    @property
    def name(self) -> str:
        return self.inner.name

    def complete(
        self, messages: list[LLMMessage], tools: list[ToolSpec], config: CompletionConfig
    ) -> LLMResponse:
        attempt = 1
        while True:
            try:
                return self.inner.complete(messages, tools, config)
            except LLMTransientError as error:
                if attempt >= self.policy.max_attempts:
                    raise
                delay = self.policy.delay_for(attempt, error, self.rng)
                logger.warning(
                    "llm transient error, retrying",
                    extra={
                        "provider": self.name,
                        "attempt": attempt,
                        "delay_s": round(delay, 3),
                        "error": type(error).__name__,
                    },
                )
                self.sleep(delay)
                attempt += 1
