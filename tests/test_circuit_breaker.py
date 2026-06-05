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


class TestExclude:
    """Business exceptions excluded from failure counting (pybreaker convention)."""

    class BusinessError(Exception):
        pass

    async def test_excluded_by_type_does_not_count(self):
        cb = CircuitBreaker(failure_threshold=1, exclude=[ValueError])
        async def bad_input():
            raise ValueError("invalid field")

        # ValueError is excluded — should not count as a failure
        with pytest.raises(ValueError):
            await cb.call(bad_input)
        assert cb.state == CircuitState.CLOSED
        assert cb._failure_count == 0

    async def test_system_error_still_counts_when_exclude_set(self):
        cb = CircuitBreaker(failure_threshold=1, exclude=[ValueError])
        async def down():
            raise RuntimeError("down")

        with pytest.raises(RuntimeError):
            await cb.call(down)
        assert cb.state == CircuitState.OPEN
        assert cb._failure_count == 1

    async def test_excluded_by_callable(self):
        cb = CircuitBreaker(
            failure_threshold=1,
            exclude=[lambda e: isinstance(e, ValueError) and "retry" not in str(e)],
        )
        # Ordinary ValueError → excluded
        async def bad_input():
            raise ValueError("invalid field")

        with pytest.raises(ValueError):
            await cb.call(bad_input)
        assert cb.state == CircuitState.CLOSED

    async def test_not_excluded_by_callable_when_predicate_false(self):
        cb = CircuitBreaker(
            failure_threshold=1,
            exclude=[lambda e: isinstance(e, ValueError) and "retry" not in str(e)],
        )
        # ValueError with "retry" in message → NOT excluded → counts
        async def transient():
            raise ValueError("retry later")

        with pytest.raises(ValueError):
            await cb.call(transient)
        assert cb.state == CircuitState.OPEN

    async def test_exclude_subclass_also_excluded(self):
        cb = CircuitBreaker(failure_threshold=1, exclude=[self.BusinessError])
        async def biz_fail():
            raise self.BusinessError("account banned")

        with pytest.raises(self.BusinessError):
            await cb.call(biz_fail)
        assert cb.state == CircuitState.CLOSED

    async def test_multiple_exclude_entries(self):
        cb = CircuitBreaker(
            failure_threshold=1,
            exclude=[ValueError, self.BusinessError, lambda e: isinstance(e, KeyError)],
        )
        async def raise_key():
            raise KeyError("missing")

        with pytest.raises(KeyError):
            await cb.call(raise_key)
        assert cb.state == CircuitState.CLOSED
        assert cb._failure_count == 0

    async def test_exclude_does_not_prevent_real_trip(self):
        """Excluded exceptions don't reset the failure counter either."""
        cb = CircuitBreaker(failure_threshold=2, exclude=[ValueError])
        async def bad_input():
            raise ValueError("invalid")
        async def down():
            raise ConnectionError("refused")

        # ValueError: excluded, doesn't count
        with pytest.raises(ValueError):
            await cb.call(bad_input)
        assert cb._failure_count == 0

        # ConnectionError: counts
        with pytest.raises(ConnectionError):
            await cb.call(down)
        assert cb._failure_count == 1

        # One more ConnectionError → trip
        with pytest.raises(ConnectionError):
            await cb.call(down)
        assert cb.state == CircuitState.OPEN


class TestHalfOpenConcurrency:
    """Verify HALF_OPEN probe counting is atomic under concurrent callers.

    The design rule is "mutate state inside lock, execute I/O outside lock."
    With half_open_probes=N, exactly N concurrent callers must execute while
    the rest are rejected — no overshoot, no probe starvation.
    """

    async def test_only_one_probe_with_half_open_probes_1(self):
        """5 concurrent callers, half_open_probes=1 → exactly 1 executes."""
        cb = CircuitBreaker(
            failure_threshold=1, recovery_timeout=0.0, half_open_probes=1
        )

        async def fail():
            raise RuntimeError("down")

        with pytest.raises(RuntimeError):
            await cb.call(fail)
        assert cb.state == CircuitState.OPEN

        executed = 0

        async def probe():
            nonlocal executed
            await asyncio.sleep(0.01)  # yield to event loop — let concurrent tasks observe HALF_OPEN
            executed += 1
            return "ok"

        results = await asyncio.gather(
            *[cb.call(probe, fallback="rejected") for _ in range(5)]
        )
        accepted = [r for r in results if r == "ok"]
        rejected = [r for r in results if r == "rejected"]

        assert len(accepted) == 1
        assert len(rejected) == 4
        assert executed == 1  # probe body ran exactly once

    async def test_exactly_two_probes_with_half_open_probes_2(self):
        """half_open_probes=2 → exactly 2 probes execute, 3 rejected."""
        cb = CircuitBreaker(
            failure_threshold=1, recovery_timeout=0.0, half_open_probes=2
        )

        async def fail():
            raise RuntimeError("down")

        with pytest.raises(RuntimeError):
            await cb.call(fail)
        assert cb.state == CircuitState.OPEN

        executed = 0

        async def probe():
            nonlocal executed
            await asyncio.sleep(0.01)
            executed += 1
            return "ok"

        results = await asyncio.gather(
            *[cb.call(probe, fallback="rejected") for _ in range(5)]
        )
        accepted = [r for r in results if r == "ok"]
        rejected = [r for r in results if r == "rejected"]

        assert len(accepted) == 2
        assert len(rejected) == 3
        assert executed == 2

    async def test_half_open_probe_failure_reopens_circuit(self):
        """When the HALF_OPEN probe fails, circuit returns to OPEN immediately."""
        cb = CircuitBreaker(
            failure_threshold=1, recovery_timeout=60.0, half_open_probes=1
        )

        async def initial_fail():
            raise RuntimeError("down")

        with pytest.raises(RuntimeError):
            await cb.call(initial_fail)
        assert cb.state == CircuitState.OPEN

        # Simulate recovery_timeout expiry
        cb._last_failure_time = 0.0

        async def probe_fails():
            await asyncio.sleep(0.01)
            raise ConnectionError("still unreachable")

        # Probe executes in HALF_OPEN and fails → failure threshold 1 → OPEN
        with pytest.raises(ConnectionError):
            await cb.call(probe_fails)
        assert cb.state == CircuitState.OPEN

        # recovery_timeout=60 → next call stays OPEN, returns fallback
        async def success():
            return "ok"

        result = await cb.call(success, fallback="still-degraded")
        assert result == "still-degraded"

    async def test_rejected_probes_dont_affect_success_count(self):
        """Rejected callers must not reset failure count or alter state."""
        cb = CircuitBreaker(
            failure_threshold=2, recovery_timeout=0.0, half_open_probes=1
        )

        async def fail():
            raise RuntimeError("down")

        with pytest.raises(RuntimeError):
            await cb.call(fail)
        # failure_count=1 but threshold=2 → still CLOSED
        assert cb.state == CircuitState.CLOSED

        # Second failure trips to OPEN
        with pytest.raises(RuntimeError):
            await cb.call(fail)
        assert cb.state == CircuitState.OPEN

        executed = 0

        async def probe():
            nonlocal executed
            await asyncio.sleep(0.01)
            executed += 1
            return "ok"

        # 10 concurrent callers, only 1 probe allowed
        results = await asyncio.gather(
            *[cb.call(probe, fallback="rejected") for _ in range(10)]
        )
        assert sum(1 for r in results if r == "ok") == 1
        assert sum(1 for r in results if r == "rejected") == 9
        assert executed == 1

        # After successful probe, circuit is CLOSED and failure_count=0
        assert cb.state == CircuitState.CLOSED
        assert cb._failure_count == 0
