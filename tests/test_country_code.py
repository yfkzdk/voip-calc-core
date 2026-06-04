"""Tests for CountryCode value object."""

import pytest

from voip_calc_core.domain.country_code import CountryCode, InvalidCountryCodeError
from voip_calc_core.domain.money import Money


class TestCountryCodeCreation:
    """CountryCode must validate format and immutability."""

    def test_create_valid_china_code(self):
        cc = CountryCode("+86")
        assert cc.code == "+86"

    def test_create_valid_us_code(self):
        cc = CountryCode("+1")
        assert cc.code == "+1"

    def test_create_valid_multidigit_code(self):
        cc = CountryCode("+351")
        assert cc.code == "+351"

    def test_create_without_plus_raises(self):
        with pytest.raises(InvalidCountryCodeError):
            CountryCode("86")

    def test_create_with_letters_raises(self):
        with pytest.raises(InvalidCountryCodeError):
            CountryCode("+AB")

    def test_create_empty_raises(self):
        with pytest.raises(InvalidCountryCodeError):
            CountryCode("")

    def test_equality_by_value(self):
        assert CountryCode("+86") == CountryCode("+86")

    def test_hash_by_value(self):
        assert hash(CountryCode("+86")) == hash(CountryCode("+86"))


class TestCountryCodeBaseRate:
    """CountryCode maps to base per-minute rate."""

    def test_china_base_rate(self):
        cc = CountryCode("+86")
        rate = cc.base_rate()
        assert rate == Money("0.10", "CNY")

    def test_us_base_rate(self):
        cc = CountryCode("+1")
        rate = cc.base_rate()
        assert rate == Money("0.05", "CNY")

    def test_default_rate_for_unknown_country(self):
        cc = CountryCode("+44")
        rate = cc.base_rate()
        assert rate == Money("0.50", "CNY")

    def test_default_rate_for_japan(self):
        cc = CountryCode("+81")
        rate = cc.base_rate()
        assert rate == Money("0.50", "CNY")
