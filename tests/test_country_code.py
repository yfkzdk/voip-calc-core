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


class TestCountryCodeFromPhoneNumber:
    """CountryCode can be extracted from international phone numbers."""

    def test_china_phone(self):
        cc = CountryCode.from_phone_number("+8613800138000")
        assert cc.code == "+86"

    def test_us_phone(self):
        cc = CountryCode.from_phone_number("+14155551234")
        assert cc.code == "+1"

    def test_uk_phone(self):
        cc = CountryCode.from_phone_number("+442012345678")
        assert cc.code == "+44"

    def test_portugal_phone(self):
        cc = CountryCode.from_phone_number("+351912345678")
        assert cc.code == "+351"

    def test_phone_without_plus_raises(self):
        with pytest.raises(InvalidCountryCodeError):
            CountryCode.from_phone_number("8613800138000")

    def test_empty_phone_raises(self):
        with pytest.raises(InvalidCountryCodeError):
            CountryCode.from_phone_number("")


class TestCountryCodeFromPhoneNumberBoundary:
    """Boundary and fuzzing-inspired tests for longest-prefix extraction.

    Covers E.164 edge cases, null-byte injection, bidi characters, over-length
    numbers, and fallback-to-regex paths — informed by known CVEs in phone
    number parsers (CVE-2024-39697, CVE-2025-10954, CVE-2026-28446).
    """

    # ── empty / structural boundaries ──────────────────────────

    def test_plus_only_raises(self):
        with pytest.raises(InvalidCountryCodeError):
            CountryCode.from_phone_number("+")

    def test_plus_with_space_raises(self):
        with pytest.raises(InvalidCountryCodeError):
            CountryCode.from_phone_number("+ 86")

    def test_whitespace_only_raises(self):
        with pytest.raises(InvalidCountryCodeError):
            CountryCode.from_phone_number("   ")

    def test_digits_without_plus_raises(self):
        with pytest.raises(InvalidCountryCodeError):
            CountryCode.from_phone_number("8613800138000")

    def test_parentheses_format_raises(self):
        with pytest.raises(InvalidCountryCodeError):
            CountryCode.from_phone_number("(+86)13800000001")

    # ── country-code-only (no subscriber number) ───────────────

    def test_country_code_only_no_subscriber(self):
        cc = CountryCode.from_phone_number("+86")
        assert cc.code == "+86"

    def test_single_digit_country_code_only(self):
        cc = CountryCode.from_phone_number("+1")
        assert cc.code == "+1"

    # ── non-digit injection ────────────────────────────────────

    def test_non_digit_after_plus_raises(self):
        with pytest.raises(InvalidCountryCodeError):
            CountryCode.from_phone_number("+abc")

    def test_null_byte_after_country_code(self):
        """Null byte stops trie walk cleanly; country code is extracted."""
        cc = CountryCode.from_phone_number("+86\x00123456")
        assert cc.code == "+86"

    def test_special_chars_in_subscriber(self):
        """Hyphens / spaces in subscriber part stop the trie at the code."""
        cc = CountryCode.from_phone_number("+86-138-0000-0001")
        assert cc.code == "+86"

    def test_unicode_bidi_character(self):
        """Right-to-left mark (U+200F) stops trie walk; code still extracted."""
        cc = CountryCode.from_phone_number("+86‏13800000001")
        assert cc.code == "+86"

    # ── length boundaries ──────────────────────────────────────

    def test_e164_max_15_digit_boundary(self):
        """E.164 max is 15 digits after +.  Prefix extraction mustn't choke."""
        cc = CountryCode.from_phone_number("+861234567890123")
        assert cc.code == "+86"

    def test_over_20_digits(self):
        """Over-length numbers must not crash trie or regex."""
        cc = CountryCode.from_phone_number("+86123456789012345678901234567890")
        assert cc.code == "+86"

    def test_three_digit_code_15_digit_subscriber(self):
        cc = CountryCode.from_phone_number("+351912345678901")
        assert cc.code == "+351"

    # ── fallback regex path (code NOT in trie) ─────────────────

    def test_code_not_in_trie_falls_back_to_regex(self):
        """+999 is not a real country code; falls back to 1-3 digit regex."""
        cc = CountryCode.from_phone_number("+9991234567")
        assert cc.code == "+999"

    def test_two_digit_code_not_in_trie(self):
        """+99 is not in the trie. Regex greedily matches 1-3 digits → +991."""
        cc = CountryCode.from_phone_number("+99123456")
        assert cc.code == "+991"
