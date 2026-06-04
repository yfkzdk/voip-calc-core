"""Tests for application DTOs and ports."""

import pytest
from decimal import Decimal

from voip_calc_core.application.dto import CalculateRateRequest, CalculateRateResponse
from voip_calc_core.application.ports import CustomerProfileFetcher
from voip_calc_core.domain.customer_tier import CustomerTier, TierEnum


class TestCalculateRateRequest:
    def test_valid_request(self):
        req = CalculateRateRequest(
            caller="+8613800000001",
            callee="+14150000000",
            call_start_time="2026-06-05T14:30:00+08:00",
            idempotency_key="call-001",
        )
        assert req.caller == "+8613800000001"
        assert req.callee == "+14150000000"
        assert req.call_start_time == "2026-06-05T14:30:00+08:00"
        assert req.idempotency_key == "call-001"

    def test_immutable(self):
        req = CalculateRateRequest(
            caller="+8613800000001",
            callee="+14150000000",
            call_start_time="2026-06-05T14:30:00+08:00",
            idempotency_key="call-001",
        )
        with pytest.raises(Exception):
            req.caller = "+8613800000002"  # type: ignore

    def test_empty_caller_raises(self):
        with pytest.raises(ValueError, match="caller"):
            CalculateRateRequest(
                caller="",
                callee="+14150000000",
                call_start_time="2026-06-05T14:30:00+08:00",
                idempotency_key="call-001",
            )

    def test_empty_callee_raises(self):
        with pytest.raises(ValueError, match="callee"):
            CalculateRateRequest(
                caller="+8613800000001",
                callee="",
                call_start_time="2026-06-05T14:30:00+08:00",
                idempotency_key="call-001",
            )

    def test_empty_start_time_raises(self):
        with pytest.raises(ValueError, match="call_start_time"):
            CalculateRateRequest(
                caller="+8613800000001",
                callee="+14150000000",
                call_start_time="",
                idempotency_key="call-001",
            )

    def test_empty_idempotency_key_raises(self):
        with pytest.raises(ValueError, match="idempotency_key"):
            CalculateRateRequest(
                caller="+8613800000001",
                callee="+14150000000",
                call_start_time="2026-06-05T14:30:00+08:00",
                idempotency_key="",
            )

    def test_whitespace_only_fields_raise(self):
        with pytest.raises(ValueError):
            CalculateRateRequest(
                caller="   ",
                callee="+14150000000",
                call_start_time="2026-06-05T14:30:00+08:00",
                idempotency_key="call-001",
            )


class TestCalculateRateResponse:
    def test_valid_response(self):
        resp = CalculateRateResponse(
            amount=Decimal("0.045"),
            currency="CNY",
            country_code="+1",
            tier="VIP",
            night_valley_applied=False,
            idempotency_key="call-001",
        )
        assert resp.amount == Decimal("0.045")
        assert resp.currency == "CNY"
        assert resp.country_code == "+1"
        assert resp.tier == "VIP"
        assert resp.night_valley_applied is False
        assert resp.idempotency_key == "call-001"

    def test_immutable(self):
        resp = CalculateRateResponse(
            amount=Decimal("0.045"),
            currency="CNY",
            country_code="+1",
            tier="VIP",
            night_valley_applied=False,
            idempotency_key="call-001",
        )
        with pytest.raises(Exception):
            resp.amount = Decimal("0.05")  # type: ignore


class TestCustomerProfileFetcher:
    def test_cannot_instantiate_abstract(self):
        with pytest.raises(TypeError):
            CustomerProfileFetcher()  # type: ignore

    def test_concrete_implementation_works(self):
        class FakeFetcher(CustomerProfileFetcher):
            async def fetch_tier_by_phone(self, phone_number: str) -> CustomerTier:
                return CustomerTier(TierEnum.VIP)

        fetcher = FakeFetcher()
        assert fetcher is not None
