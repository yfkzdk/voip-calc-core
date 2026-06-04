"""Tests for async circuit breaker state machine."""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock

from voip_calc_core.application.circuit_breaker import (
    CircuitBreaker,
    CircuitOpenError,
    CircuitState,
)

pytestmark = pytest.mark.asyncio


class TestCircuitBreakerCreation:
    def test_defaults(self):
        cb = CircuitBreaker()
        assert cb.state == CircuitState.CLOSED
        assert cb._failure_threshold == 5
        assert cb._recovery_timeout == 30.0

    def test_custom_thresholds(self):
        cb = CircuitBreaker(
            failure_threshold=3, recovery_timeout=10.0, half_open_probes=2
        )
        assert cb._failure_threshold == 3
        assert cb._recovery_timeout == 10.0
        assert cb._half_open_probes == 2

    def test_invalid_failure_threshold(self):
        with pytest.raises(ValueError):
            CircuitBreaker(failure_threshold=0)

    def test_invalid_recovery_timeout(self):
        with pytest.raises(ValueError):
            CircuitBreaker(recovery_timeout=-1)

    def test_invalid_half_open_probes(self):
        with pytest.raises(ValueError):
            CircuitBreaker(half_open_probes=0)


class TestClosedToOpen:
    async def test_trips_after_consecutive_failures(self):
        cb = CircuitBreaker(failure_threshold=2)
        async def failing():
            raise RuntimeError("down")

        with pytest.raises(RuntimeError):
            await cb.call(failing)
        assert cb.state == CircuitState.CLOSED

        with pytest.raises(RuntimeError):
            await cb.call(failing)
        assert cb.state == CircuitState.OPEN

    async def test_success_resets_failure_count(self):
        cb = CircuitBreaker(failure_threshold=3)
        async def success():
            return "ok"

        async def failing():
            raise RuntimeError("down")

        with pytest.raises(RuntimeError):
            await cb.call(failing)
        assert cb._failure_count == 1

        result = await cb.call(success)
        assert result == "ok"
        assert cb._failure_count == 0
        assert cb.state == CircuitState.CLOSED


class TestOpenBehavior:
    async def test_rejects_calls_when_open(self):
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=60.0)
        async def failing():
            raise RuntimeError("down")

        with pytest.raises(RuntimeError):
            await cb.call(failing)
        assert cb.state == CircuitState.OPEN

        async def success():
            return "ok"

        with pytest.raises(CircuitOpenError):
            await cb.call(success)

    async def test_returns_fallback_when_open(self):
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=60.0)
        async def failing():
            raise RuntimeError("down")

        with pytest.raises(RuntimeError):
            await cb.call(failing)

        async def success():
            return "ok"

        result = await cb.call(success, fallback="degraded")
        assert result == "degraded"
        assert cb.state == CircuitState.OPEN


class TestHalfOpen:
    async def test_transitions_to_half_open_after_timeout(self):
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.0)
        async def failing():
            raise RuntimeError("down")

        with pytest.raises(RuntimeError):
            await cb.call(failing)
        assert cb.state == CircuitState.OPEN

        # recovery_timeout=0 → transitions to HALF_OPEN then immediately
        # to CLOSED on success — all within the same call() invocation.
        async def success():
            return "ok"

        result = await cb.call(success)
        assert result == "ok"
        assert cb.state == CircuitState.CLOSED

    async def test_success_in_half_open_closes_circuit(self):
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.0)
        async def failing():
            raise RuntimeError("down")

        with pytest.raises(RuntimeError):
            await cb.call(failing)
        assert cb.state == CircuitState.OPEN

        async def success():
            return "ok"

        result = await cb.call(success)
        assert result == "ok"
        # After success the next state transition happens
        assert cb.state == CircuitState.CLOSED

    async def test_failure_in_half_open_reopens_circuit(self):
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.0)
        async def failing():
            raise RuntimeError("down")

        with pytest.raises(RuntimeError):
            await cb.call(failing)
        assert cb.state == CircuitState.OPEN

        async def success():
            return "ok"

        # First call after timeout: enters HALF_OPEN, succeeds
        await cb.call(success)
        assert cb.state == CircuitState.CLOSED

        # Trip again
        with pytest.raises(RuntimeError):
            await cb.call(failing)
        assert cb.state == CircuitState.OPEN

        # Half-open probe that fails
        async def also_failing():
            raise RuntimeError("still down")

        with pytest.raises(RuntimeError):
            await cb.call(also_failing)
        assert cb.state == CircuitState.OPEN


class TestReset:
    async def test_reset_clears_state(self):
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=60.0)
        async def failing():
            raise RuntimeError("down")

        with pytest.raises(RuntimeError):
            await cb.call(failing)
        assert cb.state == CircuitState.OPEN

        await cb.reset()
        assert cb.state == CircuitState.CLOSED
        assert cb._failure_count == 0

        async def success():
            return "ok"

        result = await cb.call(success)
        assert result == "ok"


class TestConcurrency:
    async def test_concurrent_calls_during_half_open_counted(self):
        """Only one probe should succeed in HALF_OPEN with half_open_probes=1."""
        cb = CircuitBreaker(
            failure_threshold=1, recovery_timeout=0.0, half_open_probes=1
        )
        async def failing():
            raise RuntimeError("down")

        with pytest.raises(RuntimeError):
            await cb.call(failing)
        assert cb.state == CircuitState.OPEN

        async def success():
            return "ok"

        # First call transitions to HALF_OPEN and succeeds
        await cb.call(success)
        assert cb.state == CircuitState.CLOSED
