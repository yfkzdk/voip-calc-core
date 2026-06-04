"""CallContext — immutable input DTO for rate calculation."""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class CallContext:
    """Immutable data transfer object carrying call information.

    Attributes:
        caller: Calling party number in international format (+N...)
        callee: Called party number in international format (+N...)
        call_time: Timezone-aware UTC datetime when the call was initiated
    """

    caller: str
    callee: str
    call_time: datetime

    def __post_init__(self):
        if self.call_time.tzinfo is None:
            raise ValueError(
                "call_time must be timezone-aware (tzinfo must not be None). "
                "Use datetime.now(timezone.utc) or attach a known timezone."
            )
