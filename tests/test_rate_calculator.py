"""Tests for RateCalculator domain service."""

import pytest
from datetime import datetime
from decimal import Decimal

from voip_calc_core.domain.call_context import CallContext
from voip_calc_core.domain.customer_tier import CustomerTier, TierEnum
from voip_calc_core.domain.money import Money
from voip_calc_core.domain.night_valley import NightValleyDiscount
from voip_calc_core.domain.rate_calculator import RateCalculator


class TestRateCalculatorDaytime:
    """Rate calculation during daytime (no night valley reduction)."""

    @pytest.fixture
    def daytime(self):
        return datetime(2026, 6, 5, 14, 30, 0)

    @pytest.fixture
    def calc(self):
        return RateCalculator()

    def test_us_normal_daytime(self, calc, daytime):
        """US + NORMAL = 0.05"""
        ctx = CallContext(caller="+8613800000001", callee="+14150000000", call_time=daytime)
        rate = calc.calculate(ctx, CustomerTier(TierEnum.NORMAL))
        assert rate == Money(Decimal("0.05"), "CNY")

    def test_china_normal_daytime(self, calc, daytime):
        """China + NORMAL = 0.10"""
        ctx = CallContext(caller="+8613800000001", callee="+8613900000000", call_time=daytime)
        rate = calc.calculate(ctx, CustomerTier(TierEnum.NORMAL))
        assert rate == Money(Decimal("0.10"), "CNY")

    def test_us_vip_daytime(self, calc, daytime):
        """US + VIP = 0.05 * 0.9 = 0.045"""
        ctx = CallContext(caller="+8613800000001", callee="+14150000000", call_time=daytime)
        rate = calc.calculate(ctx, CustomerTier(TierEnum.VIP))
        assert rate == Money(Decimal("0.045"), "CNY")

    def test_china_vip_daytime(self, calc, daytime):
        """China + VIP = 0.10 * 0.9 = 0.09"""
        ctx = CallContext(caller="+8613800000001", callee="+8613900000000", call_time=daytime)
        rate = calc.calculate(ctx, CustomerTier(TierEnum.VIP))
        assert rate == Money(Decimal("0.09"), "CNY")

    def test_default_country_normal_daytime(self, calc, daytime):
        """Unknown country + NORMAL = 0.50"""
        ctx = CallContext(caller="+8613800000001", callee="+4420000000000", call_time=daytime)
        rate = calc.calculate(ctx, CustomerTier(TierEnum.NORMAL))
        assert rate == Money(Decimal("0.50"), "CNY")


class TestRateCalculatorNightValley:
    """Rate calculation during night valley (23:00–05:00)."""

    @pytest.fixture
    def night_time(self):
        return datetime(2026, 6, 6, 2, 0, 0)

    @pytest.fixture
    def calc(self):
        return RateCalculator()

    def test_us_normal_night(self, calc, night_time):
        """US + NORMAL - night = 0.05 - 0.02 = 0.03"""
        ctx = CallContext(caller="+8613800000001", callee="+14150000000", call_time=night_time)
        rate = calc.calculate(ctx, CustomerTier(TierEnum.NORMAL))
        assert rate == Money(Decimal("0.03"), "CNY")

    def test_us_vip_night(self, calc, night_time):
        """US*VIP - night = 0.05*0.9 - 0.02 = 0.045 - 0.02 = 0.025"""
        ctx = CallContext(caller="+8613800000001", callee="+14150000000", call_time=night_time)
        rate = calc.calculate(ctx, CustomerTier(TierEnum.VIP))
        assert rate == Money(Decimal("0.025"), "CNY")

    def test_china_vip_night(self, calc, night_time):
        """China*VIP - night = 0.10*0.9 - 0.02 = 0.09 - 0.02 = 0.07"""
        ctx = CallContext(caller="+8613800000001", callee="+8613900000000", call_time=night_time)
        rate = calc.calculate(ctx, CustomerTier(TierEnum.VIP))
        assert rate == Money(Decimal("0.07"), "CNY")


class TestRateCalculatorFloorAtZero:
    """Final rate never goes below ¥0.00."""

    def test_floor_at_zero(self):
        """With a custom night valley discount large enough to push below zero."""
        # Use default rates: US + VIP = 0.045, then subtract 0.05 → -0.005 → floor at 0
        aggressive_night = NightValleyDiscount(
            start_hour=23, end_hour=5, reduction=Decimal("0.05")
        )
        calc = RateCalculator(night_valley=aggressive_night)
        ctx = CallContext(
            caller="+8613800000001",
            callee="+14150000000",
            call_time=datetime(2026, 6, 6, 2, 0, 0),
        )
        rate = calc.calculate(ctx, CustomerTier(TierEnum.VIP))
        assert rate == Money(Decimal("0.00"), "CNY")

    def test_exactly_zero(self):
        """Rate that lands exactly at zero stays at zero."""
        exact_night = NightValleyDiscount(
            start_hour=23, end_hour=5, reduction=Decimal("0.045")
        )
        calc = RateCalculator(night_valley=exact_night)
        ctx = CallContext(
            caller="+8613800000001",
            callee="+14150000000",
            call_time=datetime(2026, 6, 6, 2, 0, 0),
        )
        rate = calc.calculate(ctx, CustomerTier(TierEnum.VIP))
        assert rate == Money(Decimal("0.00"), "CNY")


class TestRateCalculatorImmutability:
    """RateCalculator is stateless — repeated calls yield same result."""

    def test_repeated_calls_same_result(self):
        calc = RateCalculator()
        ctx = CallContext(
            caller="+8613800000001",
            callee="+8613900000000",
            call_time=datetime(2026, 6, 5, 14, 30, 0),
        )
        tier = CustomerTier(TierEnum.VIP)
        first = calc.calculate(ctx, tier)
        second = calc.calculate(ctx, tier)
        assert first == second
        assert first is not second  # Different objects, same value


class TestRateCalculatorBoundaryHours:
    """Test exact boundary of night valley hours."""

    @pytest.fixture
    def calc(self):
        return RateCalculator()

    def test_at_23_00_applies_night(self, calc):
        ctx = CallContext(
            caller="+8613800000001",
            callee="+14150000000",
            call_time=datetime(2026, 6, 5, 23, 0, 0),
        )
        rate = calc.calculate(ctx, CustomerTier(TierEnum.NORMAL))
        assert rate == Money(Decimal("0.03"), "CNY")

    def test_at_05_00_no_night(self, calc):
        ctx = CallContext(
            caller="+8613800000001",
            callee="+14150000000",
            call_time=datetime(2026, 6, 5, 5, 0, 0),
        )
        rate = calc.calculate(ctx, CustomerTier(TierEnum.NORMAL))
        assert rate == Money(Decimal("0.05"), "CNY")
