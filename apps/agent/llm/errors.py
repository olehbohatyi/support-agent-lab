"""One error vocabulary for every provider.

The loop and the retry policy only need one question answered: is it worth trying again?
Providers map their SDK exceptions onto these classes in exactly one place.
"""

from __future__ import annotations


class LLMError(Exception):
    """Base class. ``retryable`` tells the retry policy what to do."""

    retryable = False

    def __init__(self, message: str, *, provider: str = "", status_code: int | None = None) -> None:
        super().__init__(message)
        self.provider = provider
        self.status_code = status_code


class LLMTransientError(LLMError):
    """Overload, 5xx, network blip: the same request may succeed later."""

    retryable = True


class LLMTimeoutError(LLMTransientError):
    """The provider did not answer within the configured timeout."""


class LLMRateLimitError(LLMTransientError):
    def __init__(
        self,
        message: str,
        *,
        provider: str = "",
        status_code: int | None = 429,
        retry_after_s: float | None = None,
    ) -> None:
        super().__init__(message, provider=provider, status_code=status_code)
        self.retry_after_s = retry_after_s


class LLMPermanentError(LLMError):
    """Bad request, auth, unknown model: retrying the same request cannot help."""
