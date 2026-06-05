"""Application-layer data transfer objects.

These DTOs are the contract between the external world (HTTP, RPC, CLI)
and the domain model.  They carry no business rules — only raw data and
structural validation.
"""

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class CalculateRateRequest:
    """Raw request from the API gateway or external caller.

    All datetime values arrive as strings to avoid implicit coercion
    by framework JSON deserializers.  The application service is
    responsible for parsing and validating them.

    .. important::
       ``call_start_time`` **must** carry an explicit timezone offset
       (e.g. ``+08:00``, ``-05:00``, ``Z``).  If a naive string is
       supplied (no offset), the parser will reject it — unless the
       application service is configured with a *default_timezone*,
       in which case the naive datetime is interpreted as local time
       in that timezone, **not** as UTC.
    """

    caller: str
    callee: str
    call_start_time: str
    idempotency_key: str

    def __post_init__(self) -> None:
        if not self.caller or not self.caller.strip():
            raise ValueError("caller must not be empty")
        if not self.callee or not self.callee.strip():
            raise ValueError("callee must not be empty")
        if not self.call_start_time or not self.call_start_time.strip():
            raise ValueError("call_start_time must not be empty")
        if not self.idempotency_key or not self.idempotency_key.strip():
            raise ValueError("idempotency_key must not be empty")


@dataclass(frozen=True)
class CalculateRateResponse:
    """Result returned to the caller after rate calculation.

    Includes audit fields (country_code, tier, night_valley_applied)
    so the caller can understand *why* a particular rate was returned.
    """

    amount: Decimal
    currency: str
    country_code: str
    tier: str
    night_valley_applied: bool
    idempotency_key: str
