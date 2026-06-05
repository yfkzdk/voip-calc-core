"""Circuit breaker state machine for async external calls.

Implements the standard three-state pattern (CLOSED → OPEN → HALF_OPEN).
Uses :class:`asyncio.Lock` for async-safe state transitions.

Exception filtering via *exclude* follows the pybreaker convention: excluded
exceptions are re-raised but do **not** count as failures that could trip
the circuit.  This prevents business-logic exceptions (e.g. ``ValueError``
from bad input) from causing a system-level circuit trip.
"""

import asyncio
import time
from enum import Enum, auto
from typing import Any, Callable, Awaitable, Optional, Sequence, Type, TypeVar, Union

T = TypeVar("T")

# An exclude entry is either an exception *type* or a callable that receives
# the exception instance and returns ``True`` if it should be excluded.
ExcludeSpec = Union[Type[Exception], Callable[[Exception], bool]]


class CircuitState(Enum):
    CLOSED = auto()
    OPEN = auto()
    HALF_OPEN = auto()


class CircuitOpenError(Exception):
    """Raised when a call is rejected because the circuit is OPEN."""


class CircuitBreaker:
    """Async circuit breaker with configurable thresholds.

    Args:
        failure_threshold: Consecutive failures before tripping to OPEN.
        recovery_timeout: Seconds to wait before transitioning OPEN → HALF_OPEN.
        half_open_probes: Max calls allowed in HALF_OPEN before deciding.
        exclude: Exception types or predicates that should NOT count as
            failures.  Business-logic exceptions (``ValueError``, validation
            errors, etc.) belong here so they don't trip the circuit.
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        half_open_probes: int = 1,
        exclude: Optional[Sequence[ExcludeSpec]] = None,
    ) -> None:
        if failure_threshold < 1:
            raise ValueError("failure_threshold must be >= 1")
        if recovery_timeout < 0:
            raise ValueError("recovery_timeout must be >= 0")
        if half_open_probes < 1:
            raise ValueError("half_open_probes must be >= 1")

        self._failure_threshold = failure_threshold
        self._recovery_timeout = recovery_timeout
        self._half_open_probes = half_open_probes
        self._exclude: Sequence[ExcludeSpec] = exclude or []

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_time: float = 0.0
        self._half_open_attempts = 0
        self._lock = asyncio.Lock()

    @property
    def state(self) -> CircuitState:
        """Current circuit state (may trigger OPEN → HALF_OPEN transition)."""
        return self._state

    async def call(
        self,
        coro_factory: Callable[..., Awaitable[T]],
        *args: Any,
        fallback: Optional[T] = None,
        **kwargs: Any,
    ) -> T:
        """Execute *coro_factory* under circuit-breaker protection.

        Args:
            coro_factory: Async callable that returns *T*.
            fallback: Value returned when the circuit is OPEN.  If ``None``
                      (default), :class:`CircuitOpenError` is raised instead.

        Returns:
            The result of *coro_factory* on success, or *fallback* if the
            circuit is OPEN and a fallback was provided.

        Raises:
            CircuitOpenError: If the circuit is OPEN and no *fallback* is given.
        """
        async with self._lock:
            now = time.monotonic()
            if self._state == CircuitState.OPEN:
                if now - self._last_failure_time >= self._recovery_timeout:
                    self._state = CircuitState.HALF_OPEN
                    self._half_open_attempts = 0
                else:
                    if fallback is not None:
                        return fallback
                    raise CircuitOpenError(
                        f"Circuit is OPEN — call rejected. "
                        f"Retry in {self._recovery_timeout - (now - self._last_failure_time):.1f}s."
                    )

            # HALF_OPEN: only *half_open_probes* calls are allowed through
            # as probes.  Additional concurrent arrivals are rejected so the
            # downstream service isn't flooded before the probe result is known.
            if (
                self._state == CircuitState.HALF_OPEN
                and self._half_open_attempts >= self._half_open_probes
            ):
                if fallback is not None:
                    return fallback
                raise CircuitOpenError(
                    "Circuit is HALF_OPEN and probe limit reached — call rejected."
                )

            if self._state == CircuitState.HALF_OPEN:
                self._half_open_attempts += 1

        # Execute outside the lock so concurrent calls aren't serialised.
        try:
            result = await coro_factory(*args, **kwargs)
        except Exception as exc:
            if not self._is_excluded(exc):
                await self._on_failure()
            raise

        await self._on_success()
        return result

    async def _on_success(self) -> None:
        async with self._lock:
            self._failure_count = 0
            self._state = CircuitState.CLOSED

    async def _on_failure(self) -> None:
        async with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.monotonic()
            if self._failure_count >= self._failure_threshold:
                self._state = CircuitState.OPEN

    def _is_excluded(self, exc: Exception) -> bool:
        """Return ``True`` if *exc* should NOT count as a circuit failure."""
        for entry in self._exclude:
            if isinstance(entry, type) and isinstance(exc, entry):
                return True
            if callable(entry) and not isinstance(entry, type) and entry(exc):
                return True
        return False

    async def reset(self) -> None:
        """Force the circuit back to CLOSED (e.g. for testing)."""
        async with self._lock:
            self._state = CircuitState.CLOSED
            self._failure_count = 0
            self._half_open_attempts = 0
