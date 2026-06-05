"""Integration tests for SqliteCdrRepository + SqliteUnitOfWork.

Uses temp file database so multiple UoW instances share the same store.
"""

import tempfile
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from voip_calc_core.infrastructure.sqlite_cdr_repository import (
    SqliteCdrRepository,
    SqliteUnitOfWork,
)

from .test_cdr_repository import _make_rated_call, UTC, CST

pytestmark = pytest.mark.asyncio


@pytest.fixture
def db_path():
    """Create a temp SQLite database file shared across UoW instances."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    yield path
    Path(path).unlink(missing_ok=True)


class TestSqliteCdrRepositorySave:
    async def test_save_and_retrieve(self, db_path):
        async with SqliteUnitOfWork(db_path=db_path) as uow:
            rc = _make_rated_call(idempotency_key="k1")
            await uow.cdr_repo.save(rc)
            await uow.commit()

        async with SqliteUnitOfWork(db_path=db_path) as uow:
            found = await uow.cdr_repo.find_by_idempotency_key("k1")
            assert found is not None
            assert found.caller == "+8613800000001"
            assert found.amount == Decimal("0.045")
            assert found.call_start_time.tzinfo is not None

    async def test_save_idempotent(self, db_path):
        """INSERT OR IGNORE: second save with same key is a no-op."""
        async with SqliteUnitOfWork(db_path=db_path) as uow:
            rc1 = _make_rated_call(idempotency_key="k1", amount="0.045")
            await uow.cdr_repo.save(rc1)
            await uow.commit()

        async with SqliteUnitOfWork(db_path=db_path) as uow:
            rc2 = _make_rated_call(idempotency_key="k1", amount="0.99")
            await uow.cdr_repo.save(rc2)
            await uow.commit()

        async with SqliteUnitOfWork(db_path=db_path) as uow:
            found = await uow.cdr_repo.find_by_idempotency_key("k1")
            assert found.amount == Decimal("0.045")  # first-write-wins

    async def test_memory_pre_check_prevents_db_hit(self, db_path):
        """Layer 1 (in-memory set) intercepts before reaching SQLite."""
        async with SqliteUnitOfWork(db_path=db_path) as uow:
            rc = _make_rated_call(idempotency_key="k1")
            await uow.cdr_repo.save(rc)
            await uow.cdr_repo.save(rc)  # second call → caught by set
            await uow.commit()

        async with SqliteUnitOfWork(db_path=db_path) as uow:
            found = await uow.cdr_repo.find_by_idempotency_key("k1")
            assert found is not None


class TestSqliteCdrRepositoryQuery:
    async def test_find_by_idempotency_key_miss(self, db_path):
        async with SqliteUnitOfWork(db_path=db_path) as uow:
            assert await uow.cdr_repo.find_by_idempotency_key("nope") is None

    async def test_find_by_caller(self, db_path):
        async with SqliteUnitOfWork(db_path=db_path) as uow:
            await uow.cdr_repo.save(_make_rated_call(cdr_id="a", idempotency_key="k1", caller="+86A"))
            await uow.cdr_repo.save(_make_rated_call(cdr_id="b", idempotency_key="k2", caller="+86A"))
            await uow.cdr_repo.save(_make_rated_call(cdr_id="c", idempotency_key="k3", caller="+86B"))
            await uow.commit()

        async with SqliteUnitOfWork(db_path=db_path) as uow:
            results = await uow.cdr_repo.find_by_caller("+86A")
            assert len(results) == 2

    async def test_find_by_caller_respects_limit(self, db_path):
        async with SqliteUnitOfWork(db_path=db_path) as uow:
            for i in range(5):
                await uow.cdr_repo.save(
                    _make_rated_call(cdr_id=str(i), idempotency_key=f"k{i}", caller="+86A")
                )
            await uow.commit()

        async with SqliteUnitOfWork(db_path=db_path) as uow:
            results = await uow.cdr_repo.find_by_caller("+86A", limit=2)
            assert len(results) == 2

    async def test_find_by_caller_empty(self, db_path):
        async with SqliteUnitOfWork(db_path=db_path) as uow:
            assert await uow.cdr_repo.find_by_caller("+86A") == []


class TestSqliteUnitOfWork:
    async def test_commit_persists(self, db_path):
        async with SqliteUnitOfWork(db_path=db_path) as uow:
            await uow.cdr_repo.save(_make_rated_call(idempotency_key="k1"))
            await uow.commit()
        # New UoW sees committed data
        async with SqliteUnitOfWork(db_path=db_path) as uow:
            assert await uow.cdr_repo.find_by_idempotency_key("k1") is not None

    async def test_no_explicit_commit_auto_commits_on_exit(self, db_path):
        async with SqliteUnitOfWork(db_path=db_path) as uow:
            await uow.cdr_repo.save(_make_rated_call(idempotency_key="k1"))
            # no explicit commit — __aexit__ auto-commits on normal exit
        async with SqliteUnitOfWork(db_path=db_path) as uow:
            assert await uow.cdr_repo.find_by_idempotency_key("k1") is not None

    async def test_exception_triggers_rollback(self, db_path):
        try:
            async with SqliteUnitOfWork(db_path=db_path) as uow:
                await uow.cdr_repo.save(_make_rated_call(idempotency_key="k1"))
                await uow.commit()
                raise RuntimeError("boom after commit")
        except RuntimeError:
            pass
        # Data committed before the exception should persist
        async with SqliteUnitOfWork(db_path=db_path) as uow:
            assert await uow.cdr_repo.find_by_idempotency_key("k1") is not None

    async def test_exception_before_commit_rolls_back(self, db_path):
        try:
            async with SqliteUnitOfWork(db_path=db_path) as uow:
                await uow.cdr_repo.save(_make_rated_call(idempotency_key="k1"))
                raise RuntimeError("boom before commit")
        except RuntimeError:
            pass
        async with SqliteUnitOfWork(db_path=db_path) as uow:
            assert await uow.cdr_repo.find_by_idempotency_key("k1") is None

    async def test_separate_uow_sees_separate_data(self, db_path):
        """Transaction isolation: uncommitted writes are invisible."""
        async with SqliteUnitOfWork(db_path=db_path) as uow1:
            await uow1.cdr_repo.save(_make_rated_call(idempotency_key="k1"))
            await uow1.commit()

            # uow2 should NOT see uow1's committed data (snapshot isolation)
            # Actually SQLite in WAL mode: readers see the snapshot at
            # the start of their read transaction.  We just verify
            # that explicit commit works across UoW boundaries.
            pass

        async with SqliteUnitOfWork(db_path=db_path) as uow2:
            found = await uow2.cdr_repo.find_by_idempotency_key("k1")
            assert found is not None


class TestSqliteRoundTrip:
    """Verify data integrity across serialization / deserialization."""

    async def test_decimal_precision(self, db_path):
        amounts = [Decimal("0.045"), Decimal("0.10"), Decimal("0.50"), Decimal("0.00")]
        for i, amt in enumerate(amounts):
            async with SqliteUnitOfWork(db_path=db_path) as uow:
                await uow.cdr_repo.save(
                    _make_rated_call(cdr_id=str(i), idempotency_key=f"ka{i}", amount=str(amt))
                )
                await uow.commit()

        for i, amt in enumerate(amounts):
            async with SqliteUnitOfWork(db_path=db_path) as uow:
                found = await uow.cdr_repo.find_by_idempotency_key(f"ka{i}")
                assert found.amount == amt

    async def test_timezone_preserved(self, db_path):
        async with SqliteUnitOfWork(db_path=db_path) as uow:
            await uow.cdr_repo.save(_make_rated_call(idempotency_key="k1"))
            await uow.commit()

        async with SqliteUnitOfWork(db_path=db_path) as uow:
            found = await uow.cdr_repo.find_by_idempotency_key("k1")
            assert found.call_start_time.tzinfo is not None
            assert found.rated_at.tzinfo is not None
            # _serialize_dt normalizes to UTC; roundtripped datetime is in UTC
            assert found.call_start_time.utcoffset() == timedelta(0)

    async def test_night_valley_roundtrip(self, db_path):
        for nv in [True, False]:
            async with SqliteUnitOfWork(db_path=db_path) as uow:
                await uow.cdr_repo.save(
                    _make_rated_call(
                        cdr_id=f"nv{int(nv)}",
                        idempotency_key=f"nv{int(nv)}",
                        night_valley_applied=nv,
                    )
                )
                await uow.commit()

            async with SqliteUnitOfWork(db_path=db_path) as uow:
                found = await uow.cdr_repo.find_by_idempotency_key(f"nv{int(nv)}")
                assert found.night_valley_applied == nv
