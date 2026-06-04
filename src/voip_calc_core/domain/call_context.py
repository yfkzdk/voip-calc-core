"""CallContext — immutable input DTO for rate calculation."""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class CallContext:
    """Immutable data transfer object carrying call information.

    Attributes:
        caller: Calling party number in international format (+N...)
        callee: Called party number in international format (+N...)
        call_time: UTC datetime when the call was initiated
    """

    caller: str
    callee: str
    call_time: datetime
