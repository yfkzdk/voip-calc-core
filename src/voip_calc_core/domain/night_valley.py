"""NightValleyDiscount value object. Encapsulates night-time rate reduction."""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from .money import Money


@dataclass(frozen=True)
class NightValleyDiscount:
    """Night valley rate reduction policy.

    When the call time falls within [start_hour, end_hour) crossing midnight,
    a fixed per-minute reduction is applied. The final rate floor (≥ ¥0.00)
    is enforced by RateCalculator, not this value object.

    Default: 23:00–05:00, ¥0.02/minute reduction.
    """

    start_hour: int = 23
    end_hour: int = 5
    reduction: Decimal = field(default_factory=lambda: Decimal("0.02"))

    def __post_init__(self):
        if not (0 <= self.start_hour <= 23 and 0 <= self.end_hour <= 23):
            raise ValueError(
                f"Hours must be 0-23, got start={self.start_hour}, end={self.end_hour}"
            )
        if self.reduction < 0:
            raise ValueError(f"Reduction must be non-negative, got {self.reduction}")

    def is_applicable(self, call_time: datetime) -> bool:
        """Return True if call_time falls within the night valley window.

        Supports cross-midnight ranges (e.g., 23:00 to 05:00).
        """
        hour = call_time.hour
        if self.start_hour > self.end_hour:
            # Cross-midnight: e.g., 23:00–05:00
            return hour >= self.start_hour or hour < self.end_hour
        else:
            # Same-day range: e.g., 22:00–23:00
            return self.start_hour <= hour < self.end_hour

    def reduction_amount(self) -> Money:
        """Return the per-minute reduction as a Money value."""
        return Money(self.reduction, "CNY")
