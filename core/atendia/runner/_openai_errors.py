"""Shared OpenAI exception taxonomy for NLU and Composer.

Use as:
    try:
        ...
    except _RETRIABLE as e:
        # retry with backoff
    except _NON_RETRIABLE as e:
        # fail fast, fall back

Note on order: catch _RETRIABLE FIRST, _NON_RETRIABLE second.
RateLimitError/InternalServerError are subclasses of APIStatusError;
listing _NON_RETRIABLE first would route 429/5xx to the fail-fast path.
"""
from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    InternalServerError,
    RateLimitError,
)
from pydantic import ValidationError


_RETRIABLE = (
    APITimeoutError,
    APIConnectionError,
    RateLimitError,
    InternalServerError,
)

_NON_RETRIABLE = (
    AuthenticationError,
    BadRequestError,
    ValidationError,
    APIStatusError,
)
