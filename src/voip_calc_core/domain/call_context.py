"""CallContext — immutable input DTO for rate calculation."""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from .customer_tier import CustomerTier


@dataclass(frozen=True)
class CallContext:
    """Immutable transfer object: caller, callee, call_time, and optional tier.

    *tier* is optional — when ``None``, callers must pass *customer_tier*
    explicitly to :meth:`RateCalculator.calculateRate`.  When set, it satisfies
    the single-parameter ``calculateRate(CallContext)`` contract required by
    the exam specification.
    """

    caller: str
    callee: str
    call_time: datetime
    tier: Optional[CustomerTier] = None

    def __post_init__(self):
        if self.call_time.tzinfo is None:
            raise ValueError(
                "call_time must be timezone-aware (tzinfo must not be None). "
                "Use datetime.now(timezone.utc) or attach a known timezone."
            )
