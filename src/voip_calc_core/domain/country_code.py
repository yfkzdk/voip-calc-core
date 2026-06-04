"""CountryCode value object. Encapsulates country calling code and base rate."""

import re
from dataclasses import dataclass
from decimal import Decimal

from .money import Money


class InvalidCountryCodeError(ValueError):
    """Raised when country code format is invalid."""

    pass


@dataclass(frozen=True)
class CountryCode:
    """Country calling code value object.

    Format: + followed by digits (e.g., +86, +1, +351).

    Encapsulates the base-rate-per-minute mapping:
        +86 (China) → ¥0.10
        +1  (USA)   → ¥0.05
        other       → ¥0.50 (default)
    """

    code: str

    _PATTERN = re.compile(r"^\+\d+$")

    _BASE_RATES = {
        "+86": Decimal("0.10"),
        "+1": Decimal("0.05"),
    }
    _DEFAULT_RATE = Decimal("0.50")

    def __post_init__(self):
        if not self._PATTERN.match(self.code):
            raise InvalidCountryCodeError(
                f"Invalid country code: '{self.code}'. "
                f"Expected format: + followed by digits (e.g., +86)."
            )

    def base_rate(self) -> "Money":
        """Return the base per-minute rate for this country."""
        amount = self._BASE_RATES.get(self.code, self._DEFAULT_RATE)
        return Money(amount, "CNY")
