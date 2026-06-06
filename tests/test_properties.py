"""Property-based tests — invariant verification via Hypothesis.

These declare universal truths about the domain model.  Unlike
example-based tests that check one specific input, property tests
generate thousands of random inputs and verify invariants hold for
every single one.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from hypothesis import assume, given, strategies as st

from voip_calc_core.domain.billing_increment import BillingIncrement
from voip_calc_core.domain.call_context import CallContext
from voip_calc_core.domain.country_code import CountryCode
from voip_calc_core.domain.customer_tier import CustomerTier, TierEnum
from voip_calc_core.domain.duration import Duration
from voip_calc_core.domain.money import Money, CNY
from voip_calc_core.domain.night_valley import NightValleyDiscount
from voip_calc_core.domain.rate_calculator import RateCalculator

CST = timezone(timedelta(hours=8))

# ── strategies ──────────────────────────────────────────────────────

valid_country_codes = st.sampled_from(["+86", "+1", "+44", "+81", "+49", "+33"])
phone_numbers = st.builds(
    lambda code, suffix: f"{code}{suffix}",
    code=valid_country_codes,
    suffix=st.text(alphabet="0123456789", min_size=7, max_size=11),
)
tiers = st.sampled_from([CustomerTier(TierEnum.VIP), CustomerTier(TierEnum.NORMAL)])
hours = st.integers(0, 23)
durations_seconds = st.integers(0, 86_400)  # 0–24h
billing_increments = st.sampled_from([
    BillingIncrement.PER_MINUTE,
    BillingIncrement.PER_6_SECONDS,
    BillingIncrement.PER_SECOND,
    BillingIncrement(30, 6),
])
reductions = st.decimals(min_value=0, max_value=0.10, places=3)


# ── helpers ─────────────────────────────────────────────────────────

def _make_context(callee_phone, hour):
    call_time = datetime(2026, 6, 5, hour, 0, 0, tzinfo=CST)
    return CallContext(
        caller="+8613800000001",
        callee=callee_phone,
        call_time=call_time,
    )


# ── Money properties ────────────────────────────────────────────────

class TestMoneyProperties:
    @given(
        amount=st.decimals(min_value=0, max_value=1_000_000, places=2),
        scalar=st.integers(1, 1000),
    )
    def test_multiplication_is_distributive(self, amount, scalar):
        """a * n + a * m == a * (n + m)"""
        a = Money(Decimal(str(amount)), CNY)
        n = scalar
        m = scalar + 1
        left = a * n + a * m
        right = a * (n + m)
        assert left == right

    @given(amount=st.decimals(min_value=0, max_value=1000, places=2))
    def test_round_trip_via_cents(self, amount):
        """round_to_cents is idempotent."""
        m = Money(Decimal(str(amount)), CNY)
        once = m.round_to_cents()
        twice = once.round_to_cents()
        assert once == twice

    @given(amount=st.decimals(min_value=-100, max_value=100, places=2))
    def test_floor_protection(self, amount):
        """at_least(Y=0) never returns negative."""
        m = Money(Decimal(str(amount)), CNY)
        result = m.at_least(Money(Decimal("0"), CNY))
        assert result.amount >= 0


# ── RateCalculator properties ───────────────────────────────────────

class TestRateCalculatorProperties:
    @given(phone=phone_numbers, tier=tiers, hour=hours)
    def test_rate_never_negative(self, phone, tier, hour):
        ctx = _make_context(phone, hour)
        calc = RateCalculator()
        rate = calc.calculate(ctx, tier)
        assert rate.amount >= 0

    @given(phone=phone_numbers, hour=hours)
    def test_vip_never_exceeds_normal(self, phone, hour):
        ctx = _make_context(phone, hour)
        calc = RateCalculator()
        vip_rate = calc.calculate(ctx, CustomerTier(TierEnum.VIP))
        normal_rate = calc.calculate(ctx, CustomerTier(TierEnum.NORMAL))
        assert vip_rate.amount <= normal_rate.amount

    @given(phone=phone_numbers, tier=tiers)
    def test_night_rate_never_exceeds_day_rate(self, phone, tier):
        calc = RateCalculator()
        night_ctx = _make_context(phone, 2)  # 02:00 CST
        day_ctx = _make_context(phone, 14)   # 14:00 CST
        night_rate = calc.calculate(night_ctx, tier)
        day_rate = calc.calculate(day_ctx, tier)
        assert night_rate.amount <= day_rate.amount

    @given(phone=phone_numbers, tier=tiers, hour=hours, seconds=durations_seconds)
    def test_charge_grows_with_duration(self, phone, tier, hour, seconds):
        ctx = _make_context(phone, hour)
        calc = RateCalculator()
        charge_1 = calc.calculate_charge(ctx, tier, Duration(seconds))
        charge_2 = calc.calculate_charge(ctx, tier, Duration(seconds * 2))
        # 2× duration should produce >= charge (not strictly > because of floor at 0)
        assert charge_2.amount >= charge_1.amount


# ── BillingIncrement properties ─────────────────────────────────────

class TestBillingIncrementProperties:
    @given(seconds=st.integers(0, 86_400), billing=billing_increments)
    def test_chargeable_never_less_than_actual(self, seconds, billing):
        """Ceiling semantics: billable >= actual."""
        result = billing.chargeable_duration(seconds)
        assert result >= seconds

    @given(billing=billing_increments)
    def test_zero_always_zero(self, billing):
        assert billing.chargeable_duration(0) == 0

    @given(seconds=st.integers(1, 86_400), billing=billing_increments)
    def test_chargeable_is_multiple_of_subsequent(self, seconds, billing):
        """After initial chunk, chargeable duration must be
        initial + k * subsequent for some integer k >= 0."""
        result = billing.chargeable_duration(seconds)
        if result <= billing.initial_seconds:
            return  # entire call fits in initial increment
        remainder = result - billing.initial_seconds
        assert remainder % billing.subsequent_seconds == 0


# ── NightValleyDiscount properties ──────────────────────────────────

class TestNightValleyProperties:
    @given(hour=hours)
    def test_applicable_only_in_window(self, hour):
        nv = NightValleyDiscount()
        call_time = datetime(2026, 6, 5, hour, 0, 0, tzinfo=CST)
        in_window = (hour >= 23 or hour < 5)
        assert nv.is_applicable(call_time) == in_window

    @given(start=st.integers(0, 23), end=st.integers(0, 23))
    def test_cross_midnight_or_same_day_consistent(self, start, end):
        """Any valid hour range produces consistent results at boundaries."""
        assume(start != end)  # empty interval when start == end
        nv = NightValleyDiscount(start_hour=start, end_hour=end)
        # Hour exactly at start should be applicable
        at_start = datetime(2026, 6, 5, start, 0, 0, tzinfo=CST)
        assert nv.is_applicable(at_start) is True
        # Hour exactly at end should NOT be applicable (half-open interval)
        at_end = datetime(2026, 6, 5, end, 0, 0, tzinfo=CST)
        assert nv.is_applicable(at_end) is False


# ── Duration properties ─────────────────────────────────────────────

class TestDurationProperties:
    @given(seconds=st.integers(0, 86_400))
    def test_valid_duration_accepted(self, seconds):
        d = Duration(seconds)
        assert d.seconds == seconds

    @given(seconds=st.integers(-86_400, -1))
    def test_negative_duration_rejected(self, seconds):
        try:
            Duration(seconds)
            assert False, f"Expected ValueError for {seconds}"
        except ValueError:
            pass
