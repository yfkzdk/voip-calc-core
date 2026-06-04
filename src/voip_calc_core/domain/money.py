"""Money value object. Immutable, same-currency invariant, Decimal precision."""

from dataclasses import dataclass
from decimal import Decimal
from typing import Union


class MoneyCurrencyMismatchError(TypeError):
    """Raised when arithmetic is attempted across different currencies."""

    pass


@dataclass(frozen=True)
class Money:
    """Immutable monetary value with currency.

    Invariants:
        - amount is always a Decimal (precision-safe)
        - same-currency operations only
        - all operations return new Money instances
    """

    amount: Decimal
    currency: str

    def __post_init__(self):
        if not isinstance(self.amount, Decimal):
            object.__setattr__(self, "amount", Decimal(str(self.amount)))

    def __add__(self, other: "Money") -> "Money":
        if not isinstance(other, Money):
            return NotImplemented
        if self.currency != other.currency:
            raise MoneyCurrencyMismatchError(
                f"Cannot add {self.currency} and {other.currency}: "
                f"currency must match."
            )
        return Money(self.amount + other.amount, self.currency)

    def __sub__(self, other: "Money") -> "Money":
        if not isinstance(other, Money):
            return NotImplemented
        if self.currency != other.currency:
            raise MoneyCurrencyMismatchError(
                f"Cannot subtract {other.currency} from {self.currency}: "
                f"currency must match."
            )
        return Money(self.amount - other.amount, self.currency)

    def __mul__(self, scalar: Union[Decimal, int, float]) -> "Money":
        if isinstance(scalar, (int, float)):
            scalar = Decimal(str(scalar))
        return Money(self.amount * scalar, self.currency)

    def __repr__(self) -> str:
        return f"Money({self.amount}, {self.currency})"
