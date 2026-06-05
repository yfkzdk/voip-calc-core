"""BillingIncrement value object — duration → chargeable units conversion.

Models the CGRateS ``RateIncrement`` / ``RateUnit`` concept: a per-minute
rate is applied to *chargeable* duration (rounded up to the configured
increment), not raw wall-clock seconds.
"""

from dataclasses import dataclass, field
from typing import ClassVar


@dataclass(frozen=True)
class BillingIncrement:
    """How to convert wall-clock duration to billable duration.

    Notation: *initial* / *subsequent* (both in seconds).

    Common patterns
    ---------------
    - ``60/60`` — whole-minute ceiling (32 s → 60 s, 61 s → 120 s).
    - ``6/6``   — 6-second pulses (0.1-minute granularity).
    - ``1/1``   — per-second exact billing.
    - ``30/6``  — first 30 s minimum, then 6 s pulses thereafter.
    """

    initial_seconds: int
    subsequent_seconds: int

    PER_MINUTE: ClassVar["BillingIncrement"] = field(default=None, init=False)  # type: ignore[assignment]
    PER_6_SECONDS: ClassVar["BillingIncrement"] = field(default=None, init=False)  # type: ignore[assignment]
    PER_SECOND: ClassVar["BillingIncrement"] = field(default=None, init=False)  # type: ignore[assignment]

    def __post_init__(self):
        if self.initial_seconds < 1:
            raise ValueError(
                f"initial_seconds must be >= 1, got {self.initial_seconds}"
            )
        if self.subsequent_seconds < 1:
            raise ValueError(
                f"subsequent_seconds must be >= 1, got {self.subsequent_seconds}"
            )

    def chargeable_duration(self, actual_seconds: int) -> int:
        """Return the billable duration in seconds for *actual_seconds*.

        Uses ceiling semantics: any fraction of an increment is charged
        as a full increment (telecom industry standard).
        """
        if actual_seconds <= 0:
            return 0

        charged = 0
        remaining = actual_seconds

        # First increment — charged in full if any time was spent
        inc = self.initial_seconds
        if remaining > 0:
            used = min(remaining, inc)
            charged += inc
            remaining -= used

        # Subsequent increments
        inc = self.subsequent_seconds
        while remaining > 0:
            used = min(remaining, inc)
            charged += inc
            remaining -= used

        return charged


# Module-level singletons — frozen dataclass, safe to share.
BillingIncrement.PER_MINUTE = BillingIncrement(60, 60)  # type: ignore[call-arg]
BillingIncrement.PER_6_SECONDS = BillingIncrement(6, 6)  # type: ignore[call-arg]
BillingIncrement.PER_SECOND = BillingIncrement(1, 1)  # type: ignore[call-arg]
