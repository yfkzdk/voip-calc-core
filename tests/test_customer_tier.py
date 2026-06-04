"""Tests for CustomerTier value object."""

import pytest
from decimal import Decimal

from voip_calc_core.domain.customer_tier import CustomerTier, TierEnum


class TestCustomerTierCreation:
    """CustomerTier must be valid enum and immutable."""

    def test_create_vip(self):
        tier = CustomerTier(TierEnum.VIP)
        assert tier.tier == TierEnum.VIP

    def test_create_normal(self):
        tier = CustomerTier(TierEnum.NORMAL)
        assert tier.tier == TierEnum.NORMAL

    def test_equality_by_value(self):
        assert CustomerTier(TierEnum.VIP) == CustomerTier(TierEnum.VIP)

    def test_inequality(self):
        assert CustomerTier(TierEnum.VIP) != CustomerTier(TierEnum.NORMAL)

    def test_hash_by_value(self):
        assert hash(CustomerTier(TierEnum.NORMAL)) == hash(CustomerTier(TierEnum.NORMAL))


class TestCustomerTierDiscount:
    """CustomerTier maps to discount rate."""

    def test_vip_discount_rate(self):
        tier = CustomerTier(TierEnum.VIP)
        assert tier.discount_rate() == Decimal("0.9")

    def test_normal_discount_rate(self):
        tier = CustomerTier(TierEnum.NORMAL)
        assert tier.discount_rate() == Decimal("1.0")

    def test_vip_label(self):
        tier = CustomerTier(TierEnum.VIP)
        assert tier.label() == "VIP"

    def test_normal_label(self):
        tier = CustomerTier(TierEnum.NORMAL)
        assert tier.label() == "NORMAL"


class TestCustomerTierFromString:
    """Factory method to construct from human-readable label."""

    def test_from_label_vip(self):
        tier = CustomerTier.from_label("VIP")
        assert tier.tier == TierEnum.VIP

    def test_from_label_normal(self):
        tier = CustomerTier.from_label("NORMAL")
        assert tier.tier == TierEnum.NORMAL

    def test_from_label_case_insensitive(self):
        tier = CustomerTier.from_label("vip")
        assert tier.tier == TierEnum.VIP

    def test_from_label_invalid_raises(self):
        with pytest.raises(ValueError):
            CustomerTier.from_label("PREMIUM")
