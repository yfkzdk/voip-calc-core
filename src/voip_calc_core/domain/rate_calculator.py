"""RateCalculator — stateless domain service for per-minute rate calculation."""

from datetime import datetime
from decimal import Decimal
from typing import Optional

from .billing_increment import BillingIncrement
from .call_context import CallContext
from .country_code import CountryCode
from .customer_tier import CustomerTier
from .duration import Duration
from .money import Money, CNY
from .night_valley import NightValleyDiscount


class RateCalculator:
    """Stateless domain service: base rate → tier discount → night reduction → floor at ¥0."""

    def __init__(self, night_valley: Optional[NightValleyDiscount] = None):
        self._night_valley = night_valley or NightValleyDiscount()

    @property
    def night_valley(self) -> NightValleyDiscount:
        """The night-valley discount configuration this calculator uses."""
        return self._night_valley

    def is_night_valley(self, call_time: datetime) -> bool:
        """Return True if *call_time* falls within the night valley window."""
        return self._night_valley.is_applicable(call_time)

    def calculateRate(
        self, context: CallContext, customer_tier: Optional[CustomerTier] = None
    ) -> Money:
        country = CountryCode.from_phone_number(context.callee)
        base_rate = country.base_rate()

        tier = customer_tier if customer_tier is not None else context.tier
        if tier is None:
            raise ValueError(
                "customer_tier must be provided either as an argument "
                "or via context.tier"
            )
        discounted = base_rate * tier.discount_rate()

        if self._night_valley.is_applicable(context.call_time):
            result = discounted - self._night_valley.reduction_amount()
        else:
            result = discounted

        return result.at_least(Money(Decimal("0"), CNY))

    def calculate_charge(
        self,
        context: CallContext,
        duration: Duration,
        customer_tier: Optional[CustomerTier] = None,
        billing: Optional[BillingIncrement] = None,
    ) -> Money:
        """Return the **total charge** for a call of *duration* seconds.

        Pipeline::

            per-minute rate (calculate)
              → chargeable seconds (billing increment ceiling)
              → raw charge = rate × (chargeable / 60)
              → round to cents (CNY precision, ROUND_HALF_UP)

        *billing* defaults to 60/60 (whole-minute ceiling) when ``None``.
        """
        if billing is None:
            billing = BillingIncrement.PER_MINUTE

        per_minute_rate = self.calculateRate(context, customer_tier)
        chargeable_seconds = billing.chargeable_duration(duration.seconds)
        chargeable_minutes = Decimal(chargeable_seconds) / Decimal("60")
        raw_charge = per_minute_rate * chargeable_minutes
        return raw_charge.round_to_cents()
