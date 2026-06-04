"""Tests for time_parser — strict ISO-8601 → aware UTC datetime."""

import pytest
from datetime import datetime, timezone, timedelta

from voip_calc_core.application.time_parser import parse_iso8601_to_utc


UTC = timezone.utc
CST = timezone(timedelta(hours=8))


class TestParseValid:
    def test_with_colon_offset(self):
        result = parse_iso8601_to_utc("2026-06-05T14:30:00+08:00")
        assert result.tzinfo is not None
        assert result.hour == 6  # 14:30 CST → 06:30 UTC
        assert result.minute == 30

    def test_without_colon_offset(self):
        result = parse_iso8601_to_utc("2026-06-05T14:30:00+0800")
        assert result.hour == 6
        assert result.minute == 30

    def test_zulu_suffix(self):
        result = parse_iso8601_to_utc("2026-06-05T14:30:00Z")
        assert result.hour == 14  # Z = UTC, no conversion
        assert result.minute == 30

    def test_positive_offset(self):
        result = parse_iso8601_to_utc("2026-06-06T02:00:00+05:30")
        assert result.hour == 20  # 02:00 +05:30 → 20:30 UTC (previous day)
        assert result.minute == 30

    def test_negative_offset(self):
        result = parse_iso8601_to_utc("2026-06-06T02:00:00-05:00")
        assert result.hour == 7  # 02:00 -05:00 → 07:00 UTC

    def test_with_microseconds(self):
        result = parse_iso8601_to_utc("2026-06-05T14:30:00.123456+00:00")
        assert result.microsecond == 123456

    def test_date_preserved_across_offset(self):
        result = parse_iso8601_to_utc("2026-06-06T01:00:00+08:00")
        assert result.day == 5  # 01:00 Jun 6 CST → 17:00 Jun 5 UTC

    def test_midnight_rollover(self):
        result = parse_iso8601_to_utc("2026-06-06T00:00:00+01:00")
        assert result.day == 5  # 00:00 Jun 6 +01:00 → 23:00 Jun 5 UTC


class TestRejectNaive:
    def test_no_offset_rejected(self):
        with pytest.raises(ValueError, match="timezone offset"):
            parse_iso8601_to_utc("2026-06-05T14:30:00")

    def test_naive_with_space_rejected(self):
        with pytest.raises(ValueError, match="timezone offset"):
            parse_iso8601_to_utc("2026-06-05T14:30:00.123")

    def test_date_only_rejected(self):
        with pytest.raises(ValueError, match="timezone offset"):
            parse_iso8601_to_utc("2026-06-05")


class TestRejectInvalid:
    def test_empty_string(self):
        with pytest.raises(ValueError, match="empty"):
            parse_iso8601_to_utc("")

    def test_whitespace_only(self):
        with pytest.raises(ValueError, match="empty"):
            parse_iso8601_to_utc("   ")

    def test_garbage_string(self):
        with pytest.raises(ValueError, match="Invalid ISO-8601"):
            parse_iso8601_to_utc("not-a-date")

    def test_wrong_format(self):
        with pytest.raises(ValueError, match="Invalid ISO-8601"):
            parse_iso8601_to_utc("06/05/2026 14:30:00")

    def test_trailing_garbage(self):
        with pytest.raises(ValueError, match="Invalid ISO-8601"):
            parse_iso8601_to_utc("2026-06-05T14:30:00Z extra")


class TestImmutability:
    def test_same_input_same_output(self):
        a = parse_iso8601_to_utc("2026-06-05T14:30:00+08:00")
        b = parse_iso8601_to_utc("2026-06-05T14:30:00+08:00")
        assert a == b
        assert a is not b

    def test_different_inputs_different_outputs(self):
        a = parse_iso8601_to_utc("2026-06-05T14:30:00+08:00")
        b = parse_iso8601_to_utc("2026-06-05T14:30:00+00:00")
        assert a != b
