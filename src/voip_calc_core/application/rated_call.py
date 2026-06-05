"""RatedCall — persistence data object for CDR storage.

This is a PO (Persistence Object), NOT a domain entity.  It carries the
fields needed to store a rated call record, with structural validation
(timezone awareness, non-negative amount) but no business rules.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4


@dataclass(frozen=True)
class RatedCall:
    """Immutable record of a rated VoIP call, ready for persistence.

    Constructed by the application service from a
    :class:`~voip_calc_core.application.dto.CalculateRateResponse`
    plus the original request context (caller, callee, call time).
    """

    cdr_id: str
    caller: str
    callee: str
    call_start_time: datetime
    country_code: str
    tier: str
    night_valley_applied: bool
    amount: Decimal
    currency: str
    idempotency_key: str
    rated_at: datetime

    def __post_init__(self) -> None:
        if not self.cdr_id or not self.cdr_id.strip():
            raise ValueError("cdr_id must not be empty")
        if not self.caller or not self.caller.strip():
            raise ValueError("caller must not be empty")
        if not self.callee or not self.callee.strip():
            raise ValueError("callee must not be empty")
        if self.call_start_time.tzinfo is None:
            raise ValueError("call_start_time must be timezone-aware")
        if self.rated_at.tzinfo is None:
            raise ValueError("rated_at must be timezone-aware")
        if self.amount < 0:
            raise ValueError("amount must be >= 0")
        if not self.currency or not self.currency.strip():
            raise ValueError("currency must not be empty")
        if not self.idempotency_key or not self.idempotency_key.strip():
            raise ValueError("idempotency_key must not be empty")

    @classmethod
    def create(
        cls,
        *,
        caller: str,
        callee: str,
        call_start_time: datetime,
        country_code: str,
        tier: str,
        night_valley_applied: bool,
        amount: Decimal,
        currency: str,
        idempotency_key: str,
    ) -> "RatedCall":
        """Factory that auto-generates *cdr_id* and *rated_at*."""
        return cls(
            cdr_id=uuid4().hex,
            caller=caller,
            callee=callee,
            call_start_time=call_start_time,
            country_code=country_code,
            tier=tier,
            night_valley_applied=night_valley_applied,
            amount=amount,
            currency=currency,
            idempotency_key=idempotency_key,
            rated_at=datetime.now(timezone.utc),
        )
