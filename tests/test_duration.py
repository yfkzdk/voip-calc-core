"""Tests for Duration value object."""

import pytest

from voip_calc_core.domain.duration import Duration


class TestDurationCreation:
    def test_zero_duration(self):
        d = Duration(0)
        assert d.seconds == 0

    def test_positive_duration(self):
        d = Duration(180)
        assert d.seconds == 180

    def test_large_duration(self):
        d = Duration(3600)
        assert d.seconds == 3600

    def test_negative_raises(self):
        with pytest.raises(ValueError, match="non-negative"):
            Duration(-1)


class TestDurationImmutability:
    def test_frozen(self):
        d = Duration(60)
        with pytest.raises(Exception):
            d.seconds = 120  # type: ignore

    def test_equality_by_value(self):
        assert Duration(60) == Duration(60)

    def test_hash_by_value(self):
        assert hash(Duration(60)) == hash(Duration(60))
