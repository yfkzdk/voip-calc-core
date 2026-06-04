"""Integration tests for RoutingAppService pipeline."""

import pytest
from decimal import Decimal
from typing import Optional

from voip_calc_core.domain.customer_tier import CustomerTier, TierEnum
from voip_calc_core.domain.rate_calculator import RateCalculator
from voip_calc_core.application.circuit_breaker import CircuitBreaker
from voip_calc_core.application.dto import CalculateRateRequest, CalculateRateResponse
from voip_calc_core.application.ports import CustomerProfileFetcher
from voip_calc_core.application.routing_service import RoutingAppService

pytestmark = pytest.mark.asyncio


class FakeFetcher(CustomerProfileFetcher):
    """Stub fetcher that looks up a hard-coded phone → tier mapping."""

    def __init__(self, mapping: Optional[dict] = None):
        self._mapping = mapping or {}
        self.call_count = 0

    async def fetch_tier_by_phone(self, phone_number: str) -> CustomerTier:
        self.call_count += 1
        if phone_number in self._mapping:
            return self._mapping[phone_number]
        return CustomerTier(TierEnum.NORMAL)


class FailingFetcher(CustomerProfileFetcher):
    """Fetcher that always raises — simulates a downed external service."""

    async def fetch_tier_by_phone(self, phone_number: str) -> CustomerTier:
        raise RuntimeError("external service unreachable")


def build_request(**overrides) -> CalculateRateRequest:
    defaults = {
        "caller": "+8613800000001",
        "callee": "+14150000000",
        "call_start_time": "2026-06-05T14:30:00+08:00",
        "idempotency_key": "test-001",
    }
    defaults.update(overrides)
    return CalculateRateRequest(**defaults)


class TestRoutingAppServiceHappyPath:
    async def test_us_vip_daytime(self):
        fetcher = FakeFetcher({"+8613800000001": CustomerTier(TierEnum.VIP)})
        service = RoutingAppService(
            calculator=RateCalculator(),
            profile_fetcher=fetcher,
            circuit_breaker=CircuitBreaker(),
        )
        response = await service.execute(build_request())
        assert response.amount == Decimal("0.045")
        assert response.currency == "CNY"
        assert response.tier == "VIP"
        assert response.country_code == "+1"
        assert response.night_valley_applied is False
        assert response.idempotency_key == "test-001"

    async def test_us_normal_night(self):
        fetcher = FakeFetcher()
        service = RoutingAppService(
            calculator=RateCalculator(),
            profile_fetcher=fetcher,
            circuit_breaker=CircuitBreaker(),
        )
        response = await service.execute(
            build_request(
                call_start_time="2026-06-06T02:00:00+00:00",  # 02:00 UTC is night
            )
        )
        assert response.amount == Decimal("0.03")
        assert response.night_valley_applied is True

    async def test_china_normal_daytime(self):
        fetcher = FakeFetcher()
        service = RoutingAppService(
            calculator=RateCalculator(),
            profile_fetcher=fetcher,
            circuit_breaker=CircuitBreaker(),
        )
        response = await service.execute(
            build_request(callee="+8613900000000")
        )
        assert response.amount == Decimal("0.10")
        assert response.country_code == "+86"

    async def test_unknown_country_default_rate(self):
        fetcher = FakeFetcher()
        service = RoutingAppService(
            calculator=RateCalculator(),
            profile_fetcher=fetcher,
            circuit_breaker=CircuitBreaker(),
        )
        response = await service.execute(
            build_request(callee="+442000000000")
        )
        assert response.amount == Decimal("0.50")
        assert response.country_code == "+44"


class TestRoutingAppServiceDegradation:
    async def test_degraded_to_normal_on_fetch_failure(self):
        """When the profile fetcher throws, the service degrades to NORMAL."""
        service = RoutingAppService(
            calculator=RateCalculator(),
            profile_fetcher=FailingFetcher(),
            circuit_breaker=CircuitBreaker(),
        )
        response = await service.execute(build_request())
        assert response.tier == "NORMAL"
        assert response.amount == Decimal("0.05")  # US + NORMAL

    async def test_degraded_on_circuit_open(self):
        """Once the breaker opens, subsequent calls return NORMAL via fallback."""
        breaker = CircuitBreaker(failure_threshold=1, recovery_timeout=60.0)
        service = RoutingAppService(
            calculator=RateCalculator(),
            profile_fetcher=FailingFetcher(),
            circuit_breaker=breaker,
        )
        # First call: fetcher fails → degradation to NORMAL
        response = await service.execute(build_request(idempotency_key="call-1"))
        assert response.tier == "NORMAL"

        # Circuit is now OPEN → fallback kicks in before calling fetcher
        response = await service.execute(build_request(idempotency_key="call-2"))
        assert response.tier == "NORMAL"
        assert response.amount == Decimal("0.05")

    async def test_fetcher_not_called_when_circuit_open(self):
        """When circuit is OPEN, the fetcher should never be invoked."""
        fetcher = FailingFetcher()
        breaker = CircuitBreaker(failure_threshold=1, recovery_timeout=60.0)
        service = RoutingAppService(
            calculator=RateCalculator(),
            profile_fetcher=fetcher,
            circuit_breaker=breaker,
        )
        await service.execute(build_request(idempotency_key="call-1"))

        # Replace with a fetcher that would succeed — circuit blocks it anyway
        good_fetcher = FakeFetcher(
            {"+8613800000001": CustomerTier(TierEnum.VIP)}
        )
        service._fetcher = good_fetcher
        response = await service.execute(build_request(idempotency_key="call-2"))
        # Circuit OPEN → fallback returns NORMAL, VIP fetcher never called
        assert response.tier == "NORMAL"
        assert good_fetcher.call_count == 0


class TestRoutingAppServiceTimeRejection:
    async def test_naive_time_rejected(self):
        service = RoutingAppService(
            calculator=RateCalculator(),
            profile_fetcher=FakeFetcher(),
            circuit_breaker=CircuitBreaker(),
        )
        with pytest.raises(ValueError, match="timezone"):
            await service.execute(build_request(call_start_time="2026-06-05T14:30:00"))

    async def test_garbage_time_rejected(self):
        service = RoutingAppService(
            calculator=RateCalculator(),
            profile_fetcher=FakeFetcher(),
            circuit_breaker=CircuitBreaker(),
        )
        with pytest.raises(ValueError, match="Invalid ISO-8601"):
            await service.execute(build_request(call_start_time="yesterday"))
