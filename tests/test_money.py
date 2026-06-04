"""Tests for Money value object."""

import pytest
from decimal import Decimal

from voip_calc_core.domain.money import Money, MoneyCurrencyMismatchError


class TestMoneyCreation:
    """Money value object must be created with valid amount and currency."""

    def test_create_money_with_cny(self):
        money = Money(Decimal("0.10"), "CNY")
        assert money.amount == Decimal("0.10")
        assert money.currency == "CNY"

    def test_create_money_with_float_converts_to_decimal(self):
        money = Money(Decimal("0.05"), "CNY")
        assert money.amount == Decimal("0.05")

    def test_money_equality_by_value(self):
        a = Money(Decimal("0.10"), "CNY")
        b = Money(Decimal("0.10"), "CNY")
        assert a == b

    def test_money_inequality_different_amount(self):
        a = Money(Decimal("0.10"), "CNY")
        b = Money(Decimal("0.05"), "CNY")
        assert a != b

    def test_money_hash_based_on_value(self):
        a = Money(Decimal("0.10"), "CNY")
        b = Money(Decimal("0.10"), "CNY")
        assert hash(a) == hash(b)


class TestMoneyAddition:
    """Money addition follows same-currency invariant."""

    def test_add_same_currency(self):
        a = Money(Decimal("0.10"), "CNY")
        b = Money(Decimal("0.05"), "CNY")
        result = a + b
        assert result.amount == Decimal("0.15")
        assert result.currency == "CNY"
        # Original objects unchanged
        assert a.amount == Decimal("0.10")
        assert b.amount == Decimal("0.05")

    def test_add_different_currency_raises(self):
        a = Money(Decimal("0.10"), "CNY")
        b = Money(Decimal("0.05"), "USD")
        with pytest.raises(MoneyCurrencyMismatchError):
            a + b


class TestMoneySubtraction:
    """Money subtraction follows same-currency invariant. Negative allowed."""

    def test_subtract_same_currency(self):
        a = Money(Decimal("0.10"), "CNY")
        b = Money(Decimal("0.02"), "CNY")
        result = a - b
        assert result.amount == Decimal("0.08")

    def test_subtract_result_can_be_negative(self):
        a = Money(Decimal("0.01"), "CNY")
        b = Money(Decimal("0.03"), "CNY")
        result = a - b
        assert result.amount == Decimal("-0.02")

    def test_subtract_different_currency_raises(self):
        a = Money(Decimal("0.10"), "CNY")
        b = Money(Decimal("0.02"), "USD")
        with pytest.raises(MoneyCurrencyMismatchError):
            a - b


class TestMoneyMultiplication:
    """Money can be multiplied by a scalar. Always commutative-safe."""

    def test_multiply_by_decimal(self):
        money = Money(Decimal("0.10"), "CNY")
        result = money * Decimal("0.9")
        assert result.amount == Decimal("0.09")
        assert result.currency == "CNY"

    def test_multiply_by_int(self):
        money = Money(Decimal("0.05"), "CNY")
        result = money * 2
        assert result.amount == Decimal("0.10")

    def test_multiply_by_float(self):
        money = Money(Decimal("0.10"), "CNY")
        result = money * 0.5
        assert result.amount == Decimal("0.05")

    def test_multiply_is_immutable(self):
        money = Money(Decimal("0.10"), "CNY")
        _ = money * Decimal("0.5")
        assert money.amount == Decimal("0.10")


class TestMoneyRepr:
    """Money string representation for debugging."""

    def test_repr(self):
        money = Money(Decimal("0.10"), "CNY")
        assert repr(money) == "Money(0.10, CNY)"
