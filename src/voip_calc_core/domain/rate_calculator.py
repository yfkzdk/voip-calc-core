"""RateCalculator — stateless domain service for per-minute rate calculation."""

from decimal import Decimal
from typing import Optional

from .call_context import CallContext
from .country_code import CountryCode
from .customer_tier import CustomerTier
from .money import Money
from .night_valley import NightValleyDiscount


class RateCalculator:
    """Stateless domain service that calculates the final per-minute rate.

    Pipeline:
        1. Base rate from callee's country code
        2. Customer tier discount
        3. Night valley reduction (if applicable)
        4. Floor at ¥0.00

    Usage:
        calc = RateCalculator()
        rate = calc.calculate(context, customer_tier)
    """

    def __init__(self, night_valley: Optional[NightValleyDiscount] = None):
        self._night_valley = night_valley or NightValleyDiscount()

    def calculate(
        self, context: CallContext, customer_tier: CustomerTier
    ) -> Money:
        """Calculate the final per-minute rate for a call.

        Args:
            context: Immutable call details (caller, callee, call_time).
            customer_tier: Pre-resolved customer identity tier.

        Returns:
            Money representing the final per-minute rate in CNY.
        """
        country = CountryCode.from_phone_number(context.callee)
        base_rate = country.base_rate()

        discounted = base_rate * customer_tier.discount_rate()

        if self._night_valley.is_applicable(context.call_time):
            result = discounted - self._night_valley.reduction_amount()
            if result.amount < 0:
                return Money(Decimal("0"), result.currency)
            return result

        return discounted
