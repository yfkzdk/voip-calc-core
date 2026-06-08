"""RoutingAppService — application facade for the VoIP rate calculation pipeline.

Orchestrates a five-step pipeline:
  1. Parse ISO-8601 string → aware UTC datetime
  2. Resolve caller tier via external port (with circuit breaker + degradation)
  3. Build domain CallContext
  4. Delegate to RateCalculator
  5. Persist RatedCall via UnitOfWork (optional — skipped when no factory provided)
"""

from typing import Callable, Optional, Sequence, Type

from voip_calc_core.domain.call_context import CallContext
from voip_calc_core.domain.country_code import CountryCode
from voip_calc_core.domain.customer_tier import CustomerTier, TierEnum
from voip_calc_core.domain.rate_calculator import RateCalculator

from .circuit_breaker import CircuitBreaker, ExcludeSpec
from .dto import CalculateRateRequest, CalculateRateResponse
from .ports import AbstractUnitOfWork, CustomerProfileFetcher
from .rated_call import RatedCall
from .time_parser import parse_iso8601_to_utc

# Business-logic exceptions that should NOT count as circuit failures.
# These indicate bad input, not a broken downstream service.
_DEFAULT_EXCLUDE: Sequence[ExcludeSpec] = (ValueError, TypeError)


class RoutingAppService:
    """Stateless application service that adapts external requests to the domain.

    Owns protocol translation, external context integration, and degradation
    strategy.  Contains **no** rate-calculation business rules — those live in
    :class:`RateCalculator`.

    By default the circuit breaker excludes ``ValueError`` and ``TypeError``
    from failure counting — those represent bad input, not a dying downstream.
    Pass *breaker_exclude* to override, or inject your own :class:`CircuitBreaker`.
    """

    def __init__(
        self,
        calculator: RateCalculator,
        profile_fetcher: CustomerProfileFetcher,
        circuit_breaker: Optional[CircuitBreaker] = None,
        breaker_exclude: Optional[Sequence[ExcludeSpec]] = None,
        unit_of_work_factory: Optional[Callable[[], AbstractUnitOfWork]] = None,
    ) -> None:
        self._calculator = calculator
        self._fetcher = profile_fetcher
        self._uow_factory = unit_of_work_factory
        if circuit_breaker is not None:
            self._breaker = circuit_breaker
        else:
            self._breaker = CircuitBreaker(
                exclude=breaker_exclude
                if breaker_exclude is not None
                else _DEFAULT_EXCLUDE,
            )

    async def execute(self, request: CalculateRateRequest) -> CalculateRateResponse:
        """Run the full rating pipeline for *request*.

        Raises:
            ValueError: if the ISO-8601 string is invalid or naive.
        """
        call_time = parse_iso8601_to_utc(request.call_start_time, field_name="call_start_time")
        country = CountryCode.from_phone_number(request.callee)
        tier = await self._fetch_tier_safely(request.caller)
        ctx = CallContext(
            caller=request.caller,
            callee=request.callee,
            call_time=call_time,
        )
        money = self._calculator.calculateRate(ctx, tier)
        night_valley = self._calculator.is_night_valley(call_time)

        # Step 5: persist CDR (skipped when no UoW factory provided)
        if self._uow_factory is not None:
            rated_call = RatedCall.create(
                caller=request.caller,
                callee=request.callee,
                call_start_time=call_time,
                country_code=country.code,
                tier=tier.label(),
                night_valley_applied=night_valley,
                amount=money.amount,
                currency=money.currency,
                idempotency_key=request.idempotency_key,
            )
            async with self._uow_factory() as uow:
                await uow.cdr_repo.save(rated_call)
                await uow.commit()

        return CalculateRateResponse(
            amount=money.amount,
            currency=money.currency,
            country_code=country.code,
            tier=tier.label(),
            night_valley_applied=night_valley,
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
