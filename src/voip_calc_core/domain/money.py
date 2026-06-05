"""Money value object. Immutable, same-currency invariant, Decimal precision."""

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Union

CNY = "CNY"


class MoneyCurrencyMismatchError(TypeError):
    """Arithmetic attempted across different currencies."""
    ...


@dataclass(frozen=True)
class Money:
    """Immutable monetary value. All operations return new instances."""

    amount: Decimal
    currency: str

    def __post_init__(self):
        if not isinstance(self.amount, Decimal):
            object.__setattr__(self, "amount", Decimal(str(self.amount)))

    def _require_same_currency(self, other: "Money") -> None:
        if self.currency != other.currency:
            raise MoneyCurrencyMismatchError(
                f"Currency mismatch: {self.currency} vs {other.currency}."
            )

    def __add__(self, other: "Money") -> "Money":
        if not isinstance(other, Money):
            return NotImplemented
        self._require_same_currency(other)
        return Money(self.amount + other.amount, self.currency)

    def __sub__(self, other: "Money") -> "Money":
        if not isinstance(other, Money):
            return NotImplemented
        self._require_same_currency(other)
        return Money(self.amount - other.amount, self.currency)

    def __mul__(self, scalar: Union[Decimal, int, float]) -> "Money":
        if isinstance(scalar, int):
            scalar = Decimal(scalar)
        elif isinstance(scalar, float):
            scalar = Decimal(str(scalar))
        return Money(self.amount * scalar, self.currency)

    def at_least(self, floor: "Money") -> "Money":
        """Return self or floor, whichever is larger."""
        self._require_same_currency(floor)
        return self if self.amount >= floor.amount else floor

    def round_to_cents(self) -> "Money":
        """Round to 2 decimal places using ROUND_HALF_UP (banker-neutral consumer rounding).

        Telecom billing convention: compute at high precision, round only at
        the final charge boundary.  CNY has ISO-4217 exponent 2.
        """
        rounded = self.amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        return Money(rounded, self.currency)

    def __repr__(self) -> str:
        return f"Money({self.amount}, {self.currency})"
