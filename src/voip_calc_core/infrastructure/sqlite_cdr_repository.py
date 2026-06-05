"""SQLite adapter for CDR persistence — development/testing only.

.. warning::
   SQLite uses database-level write locks.  Even in WAL mode,
   concurrent writes are serialised.  This adapter is suitable for
   development, local testing, and low-throughput scenarios.  For
   production, use a PostgreSQL adapter or an async queue-based
   writer.  See :ref:`PERSISTENCE_DESIGN.md §7` for details.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Optional

from voip_calc_core.application.ports import CdrRepository, AbstractUnitOfWork
from voip_calc_core.application.rated_call import RatedCall


class SqliteCdrRepository(CdrRepository):
    """SQLite-backed CDR repository — development/testing adapter.

    Implements two-layer idempotency:
      1. In-memory :class:`set` of seen keys (O(1), zero I/O)
      2. ``INSERT OR IGNORE`` (database-level dedup via UNIQUE constraint)
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._seen_keys: set[str] = set()
        self._ensure_schema()

    # ── CdrRepository interface ────────────────────────────────────────

    async def save(self, rated_call: RatedCall) -> None:
        key = rated_call.idempotency_key

        # Layer 1: in-memory pre-check (no I/O)
        if key in self._seen_keys:
            return
        self._seen_keys.add(key)

        # Layer 2: INSERT OR IGNORE (database-level dedup)
        self._conn.execute(
            """INSERT OR IGNORE INTO rated_calls
               (cdr_id, caller, callee, call_start_time, country_code,
                tier, night_valley_applied, amount, currency,
                idempotency_key, rated_at, extra_fields)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                rated_call.cdr_id,
                rated_call.caller,
                rated_call.callee,
                _serialize_dt(rated_call.call_start_time),
                rated_call.country_code,
                rated_call.tier,
                1 if rated_call.night_valley_applied else 0,
                str(rated_call.amount),
                rated_call.currency,
                rated_call.idempotency_key,
                _serialize_dt(rated_call.rated_at),
                "{}",
            ),
        )

    async def find_by_idempotency_key(self, key: str) -> Optional[RatedCall]:
        row = self._conn.execute(
            f"SELECT {_COLUMNS} FROM rated_calls WHERE idempotency_key = ?",
            (key,),
        ).fetchone()
        if row is None:
            return None
        return _row_to_rated_call(row)

    async def find_by_caller(
        self, caller: str, limit: int = 50
    ) -> list[RatedCall]:
        rows = self._conn.execute(
            f"SELECT {_COLUMNS} FROM rated_calls WHERE caller = ? "
            "ORDER BY rated_at DESC LIMIT ?",
            (caller, limit),
        ).fetchall()
        return [_row_to_rated_call(r) for r in rows]

    # ── schema ─────────────────────────────────────────────────────────

    def _ensure_schema(self) -> None:
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA_SQL)


class SqliteUnitOfWork(AbstractUnitOfWork):
    """SQLite-backed unit of work — manages transaction lifecycle.

    Creates a dedicated connection for each unit of work.  The
    connection is opened in ``__aenter__`` and closed in ``__aexit__``.
    """

    def __init__(self, db_path: str = ":memory:") -> None:
        self._db_path = db_path
        self._conn: Optional[sqlite3.Connection] = None
        self.cdr_repo: CdrRepository  # set in __aenter__

    async def __aenter__(self) -> "SqliteUnitOfWork":
        self._conn = sqlite3.connect(self._db_path)
        self.cdr_repo = SqliteCdrRepository(self._conn)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        try:
            await super().__aexit__(exc_type, exc_val, exc_tb)
        finally:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    async def commit(self) -> None:
        if self._conn is not None:
            self._conn.commit()

    async def rollback(self) -> None:
        if self._conn is not None:
            self._conn.rollback()


# ── helpers ────────────────────────────────────────────────────────────

_COLUMNS = (
    "cdr_id, caller, callee, call_start_time, country_code, "
    "tier, night_valley_applied, amount, currency, idempotency_key, rated_at"
)

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS rated_calls (
    cdr_id            TEXT PRIMARY KEY NOT NULL,
    caller            TEXT NOT NULL,
    callee            TEXT NOT NULL,
    call_start_time   TEXT NOT NULL,
    country_code      TEXT NOT NULL,
    tier              TEXT NOT NULL,
    night_valley_applied INTEGER NOT NULL,
    amount            TEXT NOT NULL,
    currency          TEXT NOT NULL,
    idempotency_key   TEXT NOT NULL UNIQUE,
    rated_at          TEXT NOT NULL,
    extra_fields      TEXT DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_rated_calls_caller ON rated_calls(caller);
CREATE INDEX IF NOT EXISTS idx_rated_calls_rated_at ON rated_calls(rated_at);
"""


def _serialize_dt(dt: datetime) -> str:
    """Serialize an aware UTC datetime to ISO-8601 string."""
    return dt.astimezone(timezone.utc).isoformat()


def _row_to_rated_call(row: tuple) -> RatedCall:
    """Deserialize a database row back into a :class:`RatedCall`."""
    (
        cdr_id, caller, callee, call_start_time_str, country_code,
        tier, night_valley_int, amount_str, currency,
        idempotency_key, rated_at_str,
    ) = row
    return RatedCall(
        cdr_id=cdr_id,
        caller=caller,
        callee=callee,
        call_start_time=datetime.fromisoformat(call_start_time_str),
        country_code=country_code,
        tier=tier,
        night_valley_applied=bool(night_valley_int),
        amount=Decimal(amount_str),
        currency=currency,
        idempotency_key=idempotency_key,
        rated_at=datetime.fromisoformat(rated_at_str),
    )
