"""RoutingAppService — application facade for the VoIP rate calculation pipeline.

Orchestrates the four-step pipeline:
  1. Parse ISO-8601 string → aware UTC datetime
  2. Resolve caller tier via external port (with circuit breaker + degradation)
  3. Build domain CallContext
  4. Delegate to RateCalculator, wrap response DTO
"""

from voip_calc_core.domain.call_context import CallContext
from voip_calc_core.domain.country_code import CountryCode
from voip_calc_core.domain.customer_tier import CustomerTier, TierEnum
from voip_calc_core.domain.rate_calculator import RateCalculator

from .circuit_breaker import CircuitBreaker
from .dto import CalculateRateRequest, CalculateRateResponse
from .ports import CustomerProfileFetcher
from .time_parser import parse_iso8601_to_utc


class RoutingAppService:
    """Stateless application service that adapts external requests to the domain.

    Owns protocol translation, external context integration, and degradation
    strategy.  Contains **no** rate-calculation business rules — those live in
    :class:`RateCalculator`.
    """

    def __init__(
        self,
        calculator: RateCalculator,
        profile_fetcher: CustomerProfileFetcher,
        circuit_breaker: CircuitBreaker,
    ) -> None:
        self._calculator = calculator
        self._fetcher = profile_fetcher
        self._breaker = circuit_breaker

    async def execute(self, request: CalculateRateRequest) -> CalculateRateResponse:
        """Run the full rating pipeline for *request*.

        Raises:
            ValueError: if the ISO-8601 string is invalid or naive.
        """
        call_time = parse_iso8601_to_utc(request.call_start_time)
        country = CountryCode.from_phone_number(request.callee)
        tier = await self._fetch_tier_safely(request.caller)
        ctx = CallContext(
            caller=request.caller,
            callee=request.callee,
            call_time=call_time,
        )
        money = self._calculator.calculate(ctx, tier)
        return CalculateRateResponse(
            amount=money.amount,
            currency=money.currency,
            country_code=country.code,
            tier=tier.label(),
            night_valley_applied=self._calculator.night_valley.is_applicable(
                call_time
            ),
            idempotency_key=request.idempotency_key,
        )

    async def _fetch_tier_safely(self, phone: str) -> CustomerTier:
        async def _fetch():
            return await self._fetcher.fetch_tier_by_phone(phone)

        try:
            return await self._breaker.call(
                _fetch, fallback=CustomerTier(TierEnum.NORMAL)
            )
        except Exception:
            return CustomerTier(TierEnum.NORMAL)
