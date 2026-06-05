"""Tests for BillingIncrement value object."""

import pytest

from voip_calc_core.domain.billing_increment import BillingIncrement


class TestBillingIncrementCreation:
    def test_per_minute_singleton(self):
        assert BillingIncrement.PER_MINUTE.initial_seconds == 60
        assert BillingIncrement.PER_MINUTE.subsequent_seconds == 60

    def test_per_6_seconds_singleton(self):
        assert BillingIncrement.PER_6_SECONDS.initial_seconds == 6
        assert BillingIncrement.PER_6_SECONDS.subsequent_seconds == 6

    def test_per_second_singleton(self):
        assert BillingIncrement.PER_SECOND.initial_seconds == 1
        assert BillingIncrement.PER_SECOND.subsequent_seconds == 1

    def test_custom_30_6(self):
        bi = BillingIncrement(initial_seconds=30, subsequent_seconds=6)
        assert bi.initial_seconds == 30
        assert bi.subsequent_seconds == 6

    def test_invalid_initial(self):
        with pytest.raises(ValueError, match="initial_seconds"):
            BillingIncrement(initial_seconds=0, subsequent_seconds=60)

    def test_invalid_subsequent(self):
        with pytest.raises(ValueError, match="subsequent_seconds"):
            BillingIncrement(initial_seconds=60, subsequent_seconds=0)


class TestChargeableDuration60x60:
    """Per-minute ceiling: 60/60."""

    def test_zero_seconds(self):
        assert BillingIncrement.PER_MINUTE.chargeable_duration(0) == 0

    def test_negative_seconds(self):
        assert BillingIncrement.PER_MINUTE.chargeable_duration(-5) == 0

    def test_exact_minute(self):
        assert BillingIncrement.PER_MINUTE.chargeable_duration(60) == 60

    def test_partial_minute_ceil(self):
        """32 s → billed as 60 s (whole-minute ceiling)."""
        assert BillingIncrement.PER_MINUTE.chargeable_duration(32) == 60

    def test_over_one_minute(self):
        """61 s → billed as 120 s."""
        assert BillingIncrement.PER_MINUTE.chargeable_duration(61) == 120

    def test_exact_three_minutes(self):
        assert BillingIncrement.PER_MINUTE.chargeable_duration(180) == 180

    def test_large_duration(self):
        """3600 s (1 hour) → exactly 3600 s."""
        assert BillingIncrement.PER_MINUTE.chargeable_duration(3600) == 3600


class TestChargeableDuration6x6:
    """6-second pulse billing."""

    def test_three_seconds(self):
        assert BillingIncrement.PER_6_SECONDS.chargeable_duration(3) == 6

    def test_six_seconds(self):
        assert BillingIncrement.PER_6_SECONDS.chargeable_duration(6) == 6

    def test_seven_seconds(self):
        assert BillingIncrement.PER_6_SECONDS.chargeable_duration(7) == 12

    def test_ten_seconds(self):
        assert BillingIncrement.PER_6_SECONDS.chargeable_duration(10) == 12


class TestChargeableDuration1x1:
    """Per-second exact billing."""

    def test_one_second(self):
        assert BillingIncrement.PER_SECOND.chargeable_duration(1) == 1

    def test_59_seconds(self):
        assert BillingIncrement.PER_SECOND.chargeable_duration(59) == 59


class TestChargeableDuration30x6:
    """30 s minimum first increment, then 6 s pulses."""

    def test_10_seconds(self):
        bi = BillingIncrement(initial_seconds=30, subsequent_seconds=6)
        assert bi.chargeable_duration(10) == 30

    def test_30_seconds(self):
        bi = BillingIncrement(initial_seconds=30, subsequent_seconds=6)
        assert bi.chargeable_duration(30) == 30

    def test_35_seconds(self):
        bi = BillingIncrement(initial_seconds=30, subsequent_seconds=6)
        assert bi.chargeable_duration(35) == 36

    def test_60_seconds(self):
        bi = BillingIncrement(initial_seconds=30, subsequent_seconds=6)
        assert bi.chargeable_duration(60) == 60
