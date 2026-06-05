"""CallContext — immutable input DTO for rate calculation."""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class CallContext:
    """Immutable transfer object: caller, callee, and timezone-aware call_time."""

    caller: str
    callee: str
    call_time: datetime

    def __post_init__(self):
        if self.call_time.tzinfo is None:
            raise ValueError(
                "call_time must be timezone-aware (tzinfo must not be None). "
                "Use datetime.now(timezone.utc) or attach a known timezone."
            )