"""Strict ISO-8601 datetime parser.  Rejects naive datetimes, normalises to UTC.

Python 3.9 compatibility: :func:`datetime.fromisoformat` does not accept
``±HHMM`` offsets (missing colon).  We pre-process those before handing off.
"""

import re
from datetime import datetime, timezone, tzinfo
from typing import Optional

# Matches a ±HHMM offset that is missing the colon separator, e.g. "+0800".
# Use search (no $ anchor) so the regex engine can find the offset anywhere;
# in a well-formed ISO-8601 string the offset is always at the end.
_OFFSET_NO_COLON = re.compile(r"([+-]\d{2})(\d{2})")


def parse_iso8601_to_utc(
    raw: str,
    *,
    field_name: str = "datetime string",
    default_timezone: Optional[tzinfo] = None,
) -> datetime:
    """Parse an ISO-8601 string and return a timezone-aware UTC datetime.

    The input **must** carry an explicit timezone offset.  Naive strings
    (missing offset or ``Z``) are rejected — the parser will not guess.

    Args:
        raw: ISO-8601 datetime string.
        field_name: Human-readable name of the field being parsed, used in
            error messages (e.g. ``"call_start_time"``).
        default_timezone: If provided, naive datetimes are assigned this
            timezone instead of being rejected (pyiso8601 convention).

    Raises:
        ValueError: if the string is not valid ISO-8601 **or** is naive
            and *default_timezone* is ``None``.
    """
    if not raw or not raw.strip():
        raise ValueError(f"{field_name} must not be empty")

    raw = raw.strip()

    # Python 3.9 fromisoformat does not support 'Z' — normalise to +00:00.
    if raw.endswith("Z") or raw.endswith("z"):
        raw = raw[:-1] + "+00:00"

    # Python 3.9 fromisoformat requires a colon in the offset: +08:00, not +0800.
    m = _OFFSET_NO_COLON.search(raw)
    if m:
        raw = raw[: m.start()] + f"{m[1]}:{m[2]}"

    try:
        dt = datetime.fromisoformat(raw)
    except (ValueError, TypeError) as exc:
        raise ValueError(
            f"Invalid ISO-8601 datetime: {raw!r}. "
            f"Expected format like '2026-06-05T14:30:00+08:00' or '2026-06-05T14:30:00Z'."
        ) from exc

    if dt.tzinfo is None:
        if default_timezone is not None:
            dt = dt.replace(tzinfo=default_timezone)
        else:
            raise ValueError(
                f"{field_name} must include a timezone offset (e.g. +08:00, -05:00, Z). "
                f"Got a naive datetime: {raw!r}"
            )

    return dt.astimezone(timezone.utc)
