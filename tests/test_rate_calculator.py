"""Tests for RateCalculator domain service."""

import pytest
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from voip_calc_core.domain.call_context import CallContext
from voip_calc_core.domain.customer_tier import CustomerTier, TierEnum
from voip_calc_core.domain.duration import Duration
from voip_calc_core.domain.money import Money
from voip_calc_core.domain.billing_increment import BillingIncrement
from voip_calc_core.domain.night_valley import NightValleyDiscount
from voip_calc_core.domain.rate_calculator import RateCalculator


CST = timezone(timedelta(hours=8))  # China Standard Time


class TestRateCalculatorDaytime:
    """Rate calculation during daytime (no night valley reduction)."""

    @pytest.fixture
    def daytime(self):
        return datetime(2026, 6, 5, 14, 30, 0, tzinfo=CST)

    @pytest.fixture
    def calc(self):
        return RateCalculator()

    def test_us_normal_daytime(self, calc, daytime):
        """US + NORMAL = 0.05"""
        ctx = CallContext(caller="+8613800000001", callee="+14150000000", call_time=daytime)
        rate = calc.calculateRate(ctx, CustomerTier(TierEnum.NORMAL))
        assert rate == Money(Decimal("0.05"), "CNY")

    def test_china_normal_daytime(self, calc, daytime):
        """China + NORMAL = 0.10"""
        ctx = CallContext(caller="+8613800000001", callee="+8613900000000", call_time=daytime)
        rate = calc.calculateRate(ctx, CustomerTier(TierEnum.NORMAL))
        assert rate == Money(Decimal("0.10"), "CNY")

    def test_us_vip_daytime(self, calc, daytime):
        """US + VIP = 0.05 * 0.9 = 0.045"""
        ctx = CallContext(caller="+8613800000001", callee="+14150000000", call_time=daytime)
        rate = calc.calculateRate(ctx, CustomerTier(TierEnum.VIP))
        assert rate == Money(Decimal("0.045"), "CNY")

    def test_china_vip_daytime(self, calc, daytime):
        """China + VIP = 0.10 * 0.9 = 0.09"""
        ctx = CallContext(caller="+8613800000001", callee="+8613900000000", call_time=daytime)
        rate = calc.calculateRate(ctx, CustomerTier(TierEnum.VIP))
        assert rate == Money(Decimal("0.09"), "CNY")

    def test_default_country_normal_daytime(self, calc, daytime):
        """Unknown country + NORMAL = 0.50"""
        ctx = CallContext(caller="+8613800000001", callee="+4420000000000", call_time=daytime)
        rate = calc.calculateRate(ctx, CustomerTier(TierEnum.NORMAL))
        assert rate == Money(Decimal("0.50"), "CNY")


class TestRateCalculatorNightValley:
    """Rate calculation during night valley (23:00–05:00)."""

    @pytest.fixture
    def night_time(self):
        return datetime(2026, 6, 6, 2, 0, 0, tzinfo=CST)

    @pytest.fixture
    def calc(self):
        return RateCalculator()

    def test_us_normal_night(self, calc, night_time):
        """US + NORMAL - night = 0.05 - 0.02 = 0.03"""
        ctx = CallContext(caller="+8613800000001", callee="+14150000000", call_time=night_time)
        rate = calc.calculateRate(ctx, CustomerTier(TierEnum.NORMAL))
        assert rate == Money(Decimal("0.03"), "CNY")

    def test_us_vip_night(self, calc, night_time):
        """US*VIP - night = 0.05*0.9 - 0.02 = 0.045 - 0.02 = 0.025"""
        ctx = CallContext(caller="+8613800000001", callee="+14150000000", call_time=night_time)
        rate = calc.calculateRate(ctx, CustomerTier(TierEnum.VIP))
        assert rate == Money(Decimal("0.025"), "CNY")

    def test_china_vip_night(self, calc, night_time):
        """China*VIP - night = 0.10*0.9 - 0.02 = 0.09 - 0.02 = 0.07"""
        ctx = CallContext(caller="+8613800000001", callee="+8613900000000", call_time=night_time)
        rate = calc.calculateRate(ctx, CustomerTier(TierEnum.VIP))
        assert rate == Money(Decimal("0.07"), "CNY")


class TestRateCalculatorFloorAtZero:
    """Final rate never goes below ¥0.00."""

    def test_floor_at_zero(self):
        aggressive_night = NightValleyDiscount(
            start_hour=23, end_hour=5, reduction=Decimal("0.05")
        )
        calc = RateCalculator(night_valley=aggressive_night)
        ctx = CallContext(
            caller="+8613800000001",
            callee="+14150000000",
            call_time=datetime(2026, 6, 6, 2, 0, 0, tzinfo=CST),
        )
        rate = calc.calculateRate(ctx, CustomerTier(TierEnum.VIP))
        assert rate == Money(Decimal("0.00"), "CNY")

    def test_exactly_zero(self):
        exact_night = NightValleyDiscount(
            start_hour=23, end_hour=5, reduction=Decimal("0.045")
        )
        calc = RateCalculator(night_valley=exact_night)
        ctx = CallContext(
            caller="+8613800000001",
            callee="+14150000000",
            call_time=datetime(2026, 6, 6, 2, 0, 0, tzinfo=CST),
        )
        rate = calc.calculateRate(ctx, CustomerTier(TierEnum.VIP))
        assert rate == Money(Decimal("0.00"), "CNY")


class TestRateCalculatorImmutability:
    """RateCalculator is stateless — repeated calls yield same result."""

    def test_repeated_calls_same_result(self):
        calc = RateCalculator()
        ctx = CallContext(
            caller="+8613800000001",
            callee="+8613900000000",
            call_time=datetime(2026, 6, 5, 14, 30, 0, tzinfo=CST),
        )
        tier = CustomerTier(TierEnum.VIP)
        first = calc.calculateRate(ctx, tier)
        second = calc.calculateRate(ctx, tier)
        assert first == second
        assert first is not second


class TestRateCalculatorBoundaryHours:
    """Test exact boundary of night valley hours."""

    @pytest.fixture
    def calc(self):
        return RateCalculator()

    def test_at_23_00_applies_night(self, calc):
        ctx = CallContext(
            caller="+8613800000001",
            callee="+14150000000",
            call_time=datetime(2026, 6, 5, 23, 0, 0, tzinfo=CST),
        )
        rate = calc.calculateRate(ctx, CustomerTier(TierEnum.NORMAL))
        assert rate == Money(Decimal("0.03"), "CNY")

    def test_at_05_00_no_night(self, calc):
        ctx = CallContext(
            caller="+8613800000001",
            callee="+14150000000",
            call_time=datetime(2026, 6, 5, 5, 0, 0, tzinfo=CST),
        )
        rate = calc.calculateRate(ctx, CustomerTier(TierEnum.NORMAL))
        assert rate == Money(Decimal("0.05"), "CNY")


class TestCallContextValidation:
    """CallContext enforces timezone-aware datetimes."""

    def test_naive_datetime_raises(self):
        with pytest.raises(ValueError, match="timezone-aware"):
            CallContext(
                caller="+8613800000001",
                callee="+14150000000",
                call_time=datetime(2026, 6, 5, 14, 30, 0),
            )

    def test_aware_datetime_ok(self):
        ctx = CallContext(
            caller="+8613800000001",
            callee="+14150000000",
            call_time=datetime(2026, 6, 5, 14, 30, 0, tzinfo=CST),
        )
        assert ctx.call_time.tzinfo is not None


class TestRateCalculatorCharge:
    """calculate_charge() — per-minute rate × chargeable duration → total."""

    @pytest.fixture
    def calc(self):
        return RateCalculator()

    @pytest.fixture
    def daytime(self):
        return datetime(2026, 6, 5, 14, 30, 0, tzinfo=CST)

    @pytest.fixture
    def us_normal_ctx(self, daytime):
        return CallContext(
            caller="+8613800000001", callee="+14150000000", call_time=daytime
        )

    @pytest.fixture
    def normal_tier(self):
        return CustomerTier(TierEnum.NORMAL)

    # ── 60/60 (per-minute ceiling) ──────────────────────────────

    def test_exact_one_minute(self, calc, us_normal_ctx, normal_tier):
        """US NORMAL = ¥0.05/min × 60s (exact 1 min) = ¥0.05"""
        charge = calc.calculate_charge(us_normal_ctx, Duration(60), normal_tier)
        assert charge == Money(Decimal("0.05"), "CNY")

    def test_exact_three_minutes(self, calc, us_normal_ctx, normal_tier):
        """US NORMAL = ¥0.05/min × 180s = ¥0.15"""
        charge = calc.calculate_charge(us_normal_ctx, Duration(180), normal_tier)
        assert charge == Money(Decimal("0.15"), "CNY")

    def test_partial_minute_ceil(self, calc, us_normal_ctx, normal_tier):
        """32s → 60s chargeable → ¥0.05"""
        charge = calc.calculate_charge(us_normal_ctx, Duration(32), normal_tier)
        assert charge == Money(Decimal("0.05"), "CNY")

    def test_over_one_minute_ceil(self, calc, us_normal_ctx, normal_tier):
        """61s → 120s chargeable → ¥0.10"""
        charge = calc.calculate_charge(us_normal_ctx, Duration(61), normal_tier)
        assert charge == Money(Decimal("0.10"), "CNY")

    def test_zero_duration(self, calc, us_normal_ctx, normal_tier):
        charge = calc.calculate_charge(us_normal_ctx, Duration(0), normal_tier)
        assert charge == Money(Decimal("0.00"), "CNY")

    # ── rounding to cents ───────────────────────────────────────

    def test_rounding_half_up(self, calc, us_normal_ctx):
        """US VIP = ¥0.045/min × 90s (2 min chargeable) = ¥0.09"""
        vip = CustomerTier(TierEnum.VIP)
        charge = calc.calculate_charge(us_normal_ctx, Duration(90), vip)
        # 90s → ceil to 2 min → ¥0.045 × 2 = ¥0.09
        assert charge == Money(Decimal("0.09"), "CNY")

    def test_rounding_sub_cent(self, calc, us_normal_ctx):
        """US VIP = ¥0.045/min × 32s (1 min ceil) = ¥0.045 → rounds to ¥0.05"""
        vip = CustomerTier(TierEnum.VIP)
        charge = calc.calculate_charge(us_normal_ctx, Duration(32), vip)
        assert charge == Money(Decimal("0.05"), "CNY")

    # ── night valley + duration ─────────────────────────────────

    def test_night_valley_with_duration(self, calc):
        """Night US NORMAL = ¥0.03/min × 60s = ¥0.03"""
        night = datetime(2026, 6, 6, 2, 0, 0, tzinfo=CST)
        ctx = CallContext(
            caller="+8613800000001", callee="+14150000000", call_time=night
        )
        charge = calc.calculate_charge(
            ctx, Duration(60), CustomerTier(TierEnum.NORMAL)
        )
        assert charge == Money(Decimal("0.03"), "CNY")

    def test_night_valley_large_duration(self, calc):
        """Night US NORMAL = ¥0.03/min × 600s = ¥0.30"""
        night = datetime(2026, 6, 6, 2, 0, 0, tzinfo=CST)
        ctx = CallContext(
            caller="+8613800000001", callee="+14150000000", call_time=night
        )
        charge = calc.calculate_charge(
            ctx, Duration(600), CustomerTier(TierEnum.NORMAL)
        )
        assert charge == Money(Decimal("0.30"), "CNY")

    # ── 6/6 pulse billing ───────────────────────────────────────

    def test_6s_pulse_billing(self, calc, us_normal_ctx, normal_tier):
        """US NORMAL ¥0.05/min, 6/6 pulse, 10s → 12s chargeable → ¥0.01"""
        charge = calc.calculate_charge(
            us_normal_ctx,
            Duration(10),
            normal_tier,
            billing=BillingIncrement.PER_6_SECONDS,
        )
        # 12s / 60s × ¥0.05 = ¥0.01
        assert charge == Money(Decimal("0.01"), "CNY")

    def test_6s_30_seconds(self, calc, us_normal_ctx, normal_tier):
        """30s → 30s chargeable (exact 5 pulses) → ¥0.025 → rounds to ¥0.03"""
        charge = calc.calculate_charge(
            us_normal_ctx,
            Duration(30),
            normal_tier,
            billing=BillingIncrement.PER_6_SECONDS,
        )
        # 30s / 60s × ¥0.05 = ¥0.025 → ROUND_HALF_UP → ¥0.03
        assert charge == Money(Decimal("0.03"), "CNY")

    # ── 1/1 per-second billing ──────────────────────────────────

    def test_per_second_billing(self, calc, us_normal_ctx, normal_tier):
        """US NORMAL ¥0.05/min, 1/1 pulse, 30s → 30s chargeable → ¥0.025 → ¥0.03"""
        charge = calc.calculate_charge(
            us_normal_ctx,
            Duration(30),
            normal_tier,
            billing=BillingIncrement.PER_SECOND,
        )
        # 30s / 60s × ¥0.05 = ¥0.025 → ROUND_HALF_UP → ¥0.03
        assert charge == Money(Decimal("0.03"), "CNY")

    # ── 30/6 first-large-then-small ────────────────────────────

    def test_30_6_billing(self, calc, us_normal_ctx, normal_tier):
        """30/6 pulse, 35s → 30+6s = 36s chargeable → ¥0.03"""
        charge = calc.calculate_charge(
            us_normal_ctx,
            Duration(35),
            normal_tier,
            billing=BillingIncrement(initial_seconds=30, subsequent_seconds=6),
        )
        # 36s / 60s × ¥0.05 = ¥0.03
        assert charge == Money(Decimal("0.03"), "CNY")

    # ── backward compatibility ──────────────────────────────────

    def test_calculate_unchanged(self, calc, us_normal_ctx, normal_tier):
        """calculateRate() still returns per-minute rate, unmodified."""
        rate = calc.calculateRate(us_normal_ctx, normal_tier)
        assert rate == Money(Decimal("0.05"), "CNY")

    def test_default_billing_is_per_minute(self, calc, us_normal_ctx, normal_tier):
        """Omitting billing defaults to 60/60."""
        charge_default = calc.calculate_charge(us_normal_ctx, Duration(61), normal_tier)
        charge_explicit = calc.calculate_charge(
            us_normal_ctx, Duration(61), normal_tier,
            billing=BillingIncrement.PER_MINUTE,
        )
        assert charge_default == charge_explicit
