"""Tests for RatedCall persistence object."""

from datetime import datetime, timezone, timedelta
from decimal import Decimal

import pytest

from voip_calc_core.application.rated_call import RatedCall


UTC = timezone.utc
CST = timezone(timedelta(hours=8))


def _rated_call(**overrides):
    defaults = {
        "cdr_id": "abc123",
        "caller": "+8613800000001",
        "callee": "+14150000000",
        "call_start_time": datetime(2026, 6, 5, 14, 30, 0, tzinfo=CST),
        "country_code": "+1",
        "tier": "VIP",
        "night_valley_applied": False,
        "amount": Decimal("0.045"),
        "currency": "CNY",
        "idempotency_key": "test-key-001",
        "rated_at": datetime(2026, 6, 5, 14, 30, 1, tzinfo=UTC),
    }
    defaults.update(overrides)
    return RatedCall(**defaults)


class TestRatedCallCreation:
    def test_valid_record(self):
        rc = _rated_call()
        assert rc.cdr_id == "abc123"
        assert rc.amount == Decimal("0.045")
        assert rc.currency == "CNY"

    def test_immutable(self):
        rc = _rated_call()
        with pytest.raises(Exception):
            rc.amount = Decimal("0.99")  # type: ignore[misc]

    def test_equality_by_value(self):
        a = _rated_call()
        b = _rated_call()
        assert a == b

    def test_inequality(self):
        a = _rated_call()
        b = _rated_call(cdr_id="different")
        assert a != b


class TestRatedCallValidation:
    def test_empty_cdr_id_raises(self):
        with pytest.raises(ValueError, match="cdr_id"):
            _rated_call(cdr_id="")

    def test_empty_caller_raises(self):
        with pytest.raises(ValueError, match="caller"):
            _rated_call(caller="")

    def test_empty_callee_raises(self):
        with pytest.raises(ValueError, match="callee"):
            _rated_call(callee="")

    def test_naive_call_start_time_raises(self):
        with pytest.raises(ValueError, match="timezone-aware"):
            _rated_call(call_start_time=datetime(2026, 6, 5, 14, 30, 0))

    def test_naive_rated_at_raises(self):
        with pytest.raises(ValueError, match="timezone-aware"):
            _rated_call(rated_at=datetime(2026, 6, 5, 14, 30, 0))

    def test_negative_amount_raises(self):
        with pytest.raises(ValueError, match=">= 0"):
            _rated_call(amount=Decimal("-0.01"))

    def test_zero_amount_ok(self):
        rc = _rated_call(amount=Decimal("0.00"))
        assert rc.amount == Decimal("0.00")

    def test_empty_currency_raises(self):
        with pytest.raises(ValueError, match="currency"):
            _rated_call(currency="")

    def test_empty_idempotency_key_raises(self):
        with pytest.raises(ValueError, match="idempotency_key"):
            _rated_call(idempotency_key="")


class TestRatedCallCreate:
    def test_auto_generates_cdr_id_and_rated_at(self):
        rc = RatedCall.create(
            caller="+8613800000001",
            callee="+14150000000",
            call_start_time=datetime(2026, 6, 5, 14, 30, 0, tzinfo=CST),
            country_code="+1",
            tier="VIP",
            night_valley_applied=False,
            amount=Decimal("0.045"),
            currency="CNY",
            idempotency_key="test-key-001",
        )
        assert len(rc.cdr_id) == 32  # uuid4 hex
        assert rc.rated_at.tzinfo is not None
        assert rc.amount == Decimal("0.045")

    def test_create_always_unique_cdr_id(self):
        a = RatedCall.create(
            caller="+8613800000001",
            callee="+14150000000",
            call_start_time=datetime(2026, 6, 5, 14, 30, 0, tzinfo=CST),
            country_code="+1",
            tier="VIP",
            night_valley_applied=False,
            amount=Decimal("0.045"),
            currency="CNY",
            idempotency_key="test-key-001",
        )
        b = RatedCall.create(
            caller="+8613800000001",
            callee="+14150000000",
            call_start_time=datetime(2026, 6, 5, 14, 30, 0, tzinfo=CST),
            country_code="+1",
            tier="VIP",
            night_valley_applied=False,
            amount=Decimal("0.045"),
            currency="CNY",
            idempotency_key="test-key-002",
        )
        assert a.cdr_id != b.cdr_id
