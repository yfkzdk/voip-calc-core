"""Tests for NightValleyDiscount value object."""

import pytest
from datetime import datetime
from decimal import Decimal

from voip_calc_core.domain.night_valley import NightValleyDiscount
from voip_calc_core.domain.money import Money


class TestNightValleyApplicability:
    """NightValleyDiscount checks if call_time falls in 23:00-05:00."""

    @pytest.fixture
    def policy(self):
        """Default night valley: 23:00-05:00, ¥0.02 reduction."""
        return NightValleyDiscount()

    def test_applicable_at_23_00(self, policy):
        call_time = datetime(2026, 6, 5, 23, 0, 0)
        assert policy.is_applicable(call_time) is True

    def test_applicable_at_23_59(self, policy):
        call_time = datetime(2026, 6, 5, 23, 59, 59)
        assert policy.is_applicable(call_time) is True

    def test_applicable_at_midnight(self, policy):
        call_time = datetime(2026, 6, 6, 0, 0, 0)
        assert policy.is_applicable(call_time) is True

    def test_applicable_at_04_59(self, policy):
        call_time = datetime(2026, 6, 6, 4, 59, 59)
        assert policy.is_applicable(call_time) is True

    def test_not_applicable_at_05_00(self, policy):
        call_time = datetime(2026, 6, 6, 5, 0, 0)
        assert policy.is_applicable(call_time) is False

    def test_not_applicable_at_12_00(self, policy):
        call_time = datetime(2026, 6, 5, 12, 0, 0)
        assert policy.is_applicable(call_time) is False

    def test_not_applicable_at_22_59(self, policy):
        call_time = datetime(2026, 6, 5, 22, 59, 59)
        assert policy.is_applicable(call_time) is False


class TestNightValleyReduction:
    """Night valley reduction amount is ¥0.02/minute."""

    def test_reduction_amount(self):
        policy = NightValleyDiscount()
        reduction = policy.reduction_amount()
        assert reduction == Money(Decimal("0.02"), "CNY")

    def test_reduction_is_cny(self):
        policy = NightValleyDiscount()
        assert policy.reduction_amount().currency == "CNY"


class TestNightValleyCustomRange:
    """NightValleyDiscount can be configured with custom range."""

    def test_custom_hours(self):
        policy = NightValleyDiscount(start_hour=22, end_hour=6, reduction=Decimal("0.03"))
        assert policy.is_applicable(datetime(2026, 6, 5, 22, 30)) is True
        assert policy.is_applicable(datetime(2026, 6, 5, 21, 59)) is False
        assert policy.reduction_amount() == Money(Decimal("0.03"), "CNY")
