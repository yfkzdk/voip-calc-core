"""NightValleyDiscount value object. Encapsulates night-time rate reduction."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from .money import Money, CNY

# Business charging timezone. Locked to prevent server timezone drift from
# corrupting night-valley boundary determination across data centre migrations.
_CHARGING_TIMEZONE = timezone(timedelta(hours=8))  # Asia/Shanghai (UTC+8, no DST)


@dataclass(frozen=True)
class NightValleyDiscount:
    """Night valley rate reduction policy.

    When the call time falls within [start_hour, end_hour) crossing midnight,
    a fixed per-minute reduction is applied. The final rate floor (>= Y=0.00)
    is enforced by RateCalculator, not this value object.

    The *charging_timezone* locks hour determination to a fixed business
    timezone.  This prevents server migration or system clock drift from
    silently corrupting night-valley eligibility.

    Default: 23:00-05:00 Asia/Shanghai, Y=0.02/minute reduction.
    """

    start_hour: int = 23
    end_hour: int = 5
    reduction: Decimal = field(default_factory=lambda: Decimal("0.02"))
    charging_timezone: timezone = field(default=_CHARGING_TIMEZONE)

    def __post_init__(self):
        if not (0 <= self.start_hour <= 23 and 0 <= self.end_hour <= 23):
            raise ValueError(
                f"Hours must be 0-23, got start={self.start_hour}, end={self.end_hour}"
            )
        if self.reduction < 0:
            raise ValueError(f"Reduction must be non-negative, got {self.reduction}")

    def is_applicable(self, call_time: datetime) -> bool:
        """Return True if call_time falls within the night valley window.

        Normalises *call_time* to the configured charging timezone before
        checking the hour, so the result is deterministic regardless of
        the timezone the caller passed in.
        """
        local = call_time.astimezone(self.charging_timezone)
        hour = local.hour
        if self.start_hour > self.end_hour:
            return hour >= self.start_hour or hour < self.end_hour
        else:
            return self.start_hour <= hour < self.end_hour

    def reduction_amount(self) -> Money:
        """Return the per-minute reduction as a Money value."""
        return Money(self.reduction, CNY)
