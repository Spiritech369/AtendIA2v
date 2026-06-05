from __future__ import annotations

import asyncio
import random
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal, TypeVar

T = TypeVar("T")

ProviderErrorKind = Literal[
    "429",
    "timeout",
    "5xx",
    "malformed_json",
    "empty_response",
    "schema_parse_failure",
    "retry_exhausted",
    "circuit_open",
    "contract",
    "logical_validation",
    "other",
]


class ProviderReliabilityError(Exception):
    kind: ProviderErrorKind = "other"
    retryable = False


class ProviderMalformedJSONError(ProviderReliabilityError):
    kind: ProviderErrorKind = "malformed_json"
    retryable = True


class ProviderEmptyResponseError(ProviderReliabilityError):
    kind: ProviderErrorKind = "empty_response"
    retryable = True


class ProviderSchemaParseError(ProviderReliabilityError):
    kind: ProviderErrorKind = "schema_parse_failure"
    retryable = True


class ProviderContractError(ProviderReliabilityError):
    kind: ProviderErrorKind = "contract"
    retryable = False


class ProviderLogicalValidationError(ProviderReliabilityError):
    kind: ProviderErrorKind = "logical_validation"
    retryable = False


class ProviderRetryExhaustedError(ProviderReliabilityError):
    kind: ProviderErrorKind = "retry_exhausted"
    retryable = False

    def __init__(self, last_error: BaseException | None = None) -> None:
        self.last_error = last_error
        detail = type(last_error).__name__ if last_error else "Unknown"
        super().__init__(f"provider retry exhausted; last_error={detail}")


class ProviderCircuitOpenError(ProviderReliabilityError):
    kind: ProviderErrorKind = "circuit_open"
    retryable = False


@dataclass(frozen=True)
class ProviderReliabilityConfig:
    max_retries: int = 2
    timeout_s: float = 8.0
    base_delay_ms: int = 500
    max_delay_ms: int = 4000
    jitter_ms: int = 250
    circuit_failure_threshold: int = 5
    circuit_cooldown_s: float = 30.0
    retry_output_parse_failures: bool = True


@dataclass
class ProviderReliabilitySnapshot:
    provider_error_rate: float = 0.0
    provider_429_count: int = 0
    provider_timeout_count: int = 0
    provider_5xx_count: int = 0
    provider_retry_count: int = 0
    provider_retry_exhausted_count: int = 0
    provider_circuit_breaker_open_count: int = 0
    provider_fallback_response_count: int = 0
    provider_latency_p50: int = 0
    provider_latency_p95: int = 0
    provider_latency_p99: int = 0
    provider_call_count: int = 0
    provider_error_count: int = 0
    circuit_state: str = "closed"
    last_error_kind: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider_error_rate": self.provider_error_rate,
            "provider_429_count": self.provider_429_count,
            "provider_timeout_count": self.provider_timeout_count,
            "provider_5xx_count": self.provider_5xx_count,
            "provider_retry_count": self.provider_retry_count,
            "provider_retry_exhausted_count": self.provider_retry_exhausted_count,
            "provider_circuit_breaker_open_count": self.provider_circuit_breaker_open_count,
            "provider_fallback_response_count": self.provider_fallback_response_count,
            "provider_latency_p50": self.provider_latency_p50,
            "provider_latency_p95": self.provider_latency_p95,
            "provider_latency_p99": self.provider_latency_p99,
            "provider_call_count": self.provider_call_count,
            "provider_error_count": self.provider_error_count,
            "circuit_state": self.circuit_state,
            "last_error_kind": self.last_error_kind,
        }


@dataclass
class _ProviderReliabilityCounters:
    call_count: int = 0
    error_count: int = 0
    count_429: int = 0
    timeout_count: int = 0
    count_5xx: int = 0
    retry_count: int = 0
    retry_exhausted_count: int = 0
    circuit_breaker_open_count: int = 0
    fallback_response_count: int = 0
    latencies_ms: list[int] = field(default_factory=list)
    last_error_kind: str | None = None

    def record_error_kind(self, kind: ProviderErrorKind) -> None:
        self.error_count += 1
        self.last_error_kind = kind
        if kind == "429":
            self.count_429 += 1
        elif kind == "timeout":
            self.timeout_count += 1
        elif kind == "5xx":
            self.count_5xx += 1


@dataclass
class _CircuitState:
    state: Literal["closed", "open", "half_open"] = "closed"
    failure_count: int = 0
    opened_at: float | None = None


_CIRCUITS: dict[tuple[str, str, str], _CircuitState] = {}


class ProviderReliabilityLayer:
    """Retries remote provider calls before any tool or state side effect boundary."""

    def __init__(
        self,
        *,
        provider: str,
        model: str,
        tenant_id: str,
        config: ProviderReliabilityConfig | None = None,
        rng: random.Random | None = None,
    ) -> None:
        self.provider = provider
        self.model = model
        self.tenant_id = tenant_id
        self.config = config or ProviderReliabilityConfig()
        self._rng = rng or random.Random()
        self._counters = _ProviderReliabilityCounters()
        self._circuit_key = (provider, model, tenant_id)
        _CIRCUITS.setdefault(self._circuit_key, _CircuitState())

    @property
    def idempotency_key_prefix(self) -> str:
        return f"{self.tenant_id}:{self.provider}:{self.model}"

    async def execute(
        self,
        operation: Callable[[], Awaitable[T]],
        *,
        operation_name: str,
        idempotency_key: str | None = None,
    ) -> T:
        del operation_name, idempotency_key
        self._check_circuit()
        attempts = self.config.max_retries + 1
        last_error: BaseException | None = None
        start = time.perf_counter()

        for attempt in range(1, attempts + 1):
            if attempt > 1:
                self._counters.retry_count += 1
                await asyncio.sleep(self._backoff_delay_s(attempt - 1))
            self._counters.call_count += 1
            try:
                result = await asyncio.wait_for(operation(), timeout=self.config.timeout_s)
            except Exception as exc:
                last_error = exc
                kind = classify_provider_error(exc)
                self._counters.record_error_kind(kind)
                if _breaker_error(kind):
                    self._record_circuit_failure()
                if attempt >= attempts or not is_retryable_provider_error(
                    exc,
                    retry_output_parse_failures=self.config.retry_output_parse_failures,
                ):
                    if attempt >= attempts and is_retryable_provider_error(
                        exc,
                        retry_output_parse_failures=self.config.retry_output_parse_failures,
                    ):
                        self._counters.retry_exhausted_count += 1
                        raise ProviderRetryExhaustedError(exc) from exc
                    raise
                continue
            latency_ms = int((time.perf_counter() - start) * 1000)
            self._counters.latencies_ms.append(latency_ms)
            self._record_circuit_success()
            return result

        self._counters.retry_exhausted_count += 1
        raise ProviderRetryExhaustedError(last_error)

    def record_fallback_response(self) -> None:
        self._counters.fallback_response_count += 1

    def snapshot(self) -> ProviderReliabilitySnapshot:
        circuit = _CIRCUITS[self._circuit_key]
        calls = max(self._counters.call_count, 1)
        latencies = sorted(self._counters.latencies_ms)
        return ProviderReliabilitySnapshot(
            provider_error_rate=round(self._counters.error_count / calls, 4),
            provider_429_count=self._counters.count_429,
            provider_timeout_count=self._counters.timeout_count,
            provider_5xx_count=self._counters.count_5xx,
            provider_retry_count=self._counters.retry_count,
            provider_retry_exhausted_count=self._counters.retry_exhausted_count,
            provider_circuit_breaker_open_count=self._counters.circuit_breaker_open_count,
            provider_fallback_response_count=self._counters.fallback_response_count,
            provider_latency_p50=_percentile(latencies, 50),
            provider_latency_p95=_percentile(latencies, 95),
            provider_latency_p99=_percentile(latencies, 99),
            provider_call_count=self._counters.call_count,
            provider_error_count=self._counters.error_count,
            circuit_state=circuit.state,
            last_error_kind=self._counters.last_error_kind,
        )

    def _backoff_delay_s(self, retry_number: int) -> float:
        base = min(
            self.config.max_delay_ms,
            self.config.base_delay_ms * (2 ** max(retry_number - 1, 0)),
        )
        jitter = self._rng.randint(0, max(self.config.jitter_ms, 0))
        return (base + jitter) / 1000

    def _check_circuit(self) -> None:
        circuit = _CIRCUITS[self._circuit_key]
        if circuit.state != "open":
            return
        elapsed = time.monotonic() - (circuit.opened_at or 0.0)
        if elapsed >= self.config.circuit_cooldown_s:
            circuit.state = "half_open"
            return
        self._counters.circuit_breaker_open_count += 1
        self._counters.record_error_kind("circuit_open")
        raise ProviderCircuitOpenError(
            f"provider circuit open for {self.provider}/{self.model}/{self.tenant_id}"
        )

    def _record_circuit_failure(self) -> None:
        circuit = _CIRCUITS[self._circuit_key]
        circuit.failure_count += 1
        if circuit.failure_count >= self.config.circuit_failure_threshold:
            if circuit.state != "open":
                self._counters.circuit_breaker_open_count += 1
            circuit.state = "open"
            circuit.opened_at = time.monotonic()

    def _record_circuit_success(self) -> None:
        circuit = _CIRCUITS[self._circuit_key]
        circuit.state = "closed"
        circuit.failure_count = 0
        circuit.opened_at = None


def classify_provider_error(exc: BaseException) -> ProviderErrorKind:
    if isinstance(exc, ProviderReliabilityError):
        return exc.kind
    name = type(exc).__name__.casefold()
    message = str(exc).casefold()
    status_code = getattr(exc, "status_code", None) or getattr(exc, "status", None)
    if isinstance(exc, TimeoutError | asyncio.TimeoutError) or "timeout" in name:
        return "timeout"
    if status_code == 429 or "ratelimit" in name or "rate_limit" in name or "too many requests" in message:
        return "429"
    if isinstance(status_code, int) and 500 <= status_code <= 599:
        return "5xx"
    if "internalservererror" in name:
        return "5xx"
    if "jsondecodeerror" in name:
        return "malformed_json"
    return "other"


def is_retryable_provider_error(
    exc: BaseException,
    *,
    retry_output_parse_failures: bool = True,
) -> bool:
    if isinstance(exc, ProviderContractError | ProviderLogicalValidationError):
        return False
    if isinstance(exc, ProviderReliabilityError):
        if exc.kind in {"malformed_json", "schema_parse_failure", "empty_response"}:
            return retry_output_parse_failures and exc.retryable
        return exc.retryable
    return classify_provider_error(exc) in {"429", "timeout", "5xx"}


def reset_provider_reliability_circuits() -> None:
    _CIRCUITS.clear()


def _breaker_error(kind: ProviderErrorKind) -> bool:
    return kind in {"429", "timeout", "5xx"}


def _percentile(values: list[int], percentile: int) -> int:
    if not values:
        return 0
    if len(values) == 1:
        return values[0]
    index = round((percentile / 100) * (len(values) - 1))
    return values[min(max(index, 0), len(values) - 1)]


__all__ = [
    "ProviderCircuitOpenError",
    "ProviderContractError",
    "ProviderEmptyResponseError",
    "ProviderLogicalValidationError",
    "ProviderMalformedJSONError",
    "ProviderReliabilityConfig",
    "ProviderReliabilityLayer",
    "ProviderReliabilitySnapshot",
    "ProviderRetryExhaustedError",
    "ProviderSchemaParseError",
    "classify_provider_error",
    "is_retryable_provider_error",
    "reset_provider_reliability_circuits",
]
