"""Tests for CdrRepository & AbstractUnitOfWork ports with Fake implementations."""

from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import Optional

import pytest

from voip_calc_core.application.ports import CdrRepository, AbstractUnitOfWork
from voip_calc_core.application.rated_call import RatedCall

pytestmark = pytest.mark.asyncio


# ── Fake implementations for testing ──────────────────────────────────────

class DuplicateIdempotencyKeyError(Exception):
    """Raised when an idempotency_key collision is detected."""


class FakeCdrRepository(CdrRepository):
    """In-memory CDR repository — zero I/O, for unit tests.

    Implements the three-layer idempotency defence:
      1. In-memory set (O(1) pre-check)
      2. Dict lookup (idempotent response replay)
      3. Dict insertion guard (final dedup)
    """

    def __init__(self) -> None:
        self._store: dict[str, RatedCall] = {}
        self._seen_keys: set[str] = set()
        self.save_count = 0

    async def save(self, rated_call: RatedCall) -> None:
        key = rated_call.idempotency_key
        # Layer 1: in-memory pre-check
        if key in self._seen_keys:
            return
        # Layer 2: dict lookup (replay)
        if key in self._store:
            self._seen_keys.add(key)
            return
        # Layer 3: insert
        self._store[key] = rated_call
        self._seen_keys.add(key)
        self.save_count += 1

    async def find_by_idempotency_key(self, key: str) -> Optional[RatedCall]:
        return self._store.get(key)

    async def find_by_caller(self, caller: str, limit: int = 50) -> list[RatedCall]:
        return [rc for rc in self._store.values() if rc.caller == caller][:limit]

    def clear(self) -> None:
        """Reset all stored data — used by UoW rollback."""
        self._store.clear()
        self._seen_keys.clear()


class FakeUnitOfWork(AbstractUnitOfWork):
    """In-memory unit of work — commit is a no-op, rollback clears store."""

    def __init__(self, repo: Optional[FakeCdrRepository] = None) -> None:
        self._repo = repo or FakeCdrRepository()
        self.cdr_repo = self._repo
        self.committed = False
        self.rolled_back = False

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        self.rolled_back = True
        self._repo.clear()


# ── Port ABC tests ────────────────────────────────────────────────────────

class TestCdrRepositoryABC:
    def test_cannot_instantiate_abstract(self):
        with pytest.raises(TypeError):
            CdrRepository()  # type: ignore[abstract]

    async def test_fake_is_concrete(self):
        repo = FakeCdrRepository()
        assert isinstance(repo, CdrRepository)


class TestAbstractUnitOfWorkABC:
    def test_cannot_instantiate_abstract(self):
        with pytest.raises(TypeError):
            AbstractUnitOfWork()  # type: ignore[abstract]

    async def test_fake_is_concrete(self):
        uow = FakeUnitOfWork()
        assert isinstance(uow, AbstractUnitOfWork)


# ── FakeCdrRepository tests ───────────────────────────────────────────────

class TestFakeCdrRepositorySave:
    async def test_save_and_retrieve(self):
        repo = FakeCdrRepository()
        rc = _make_rated_call(idempotency_key="k1")
        await repo.save(rc)
        found = await repo.find_by_idempotency_key("k1")
        assert found is not None
        assert found.caller == "+8613800000001"

    async def test_idempotent_save_same_key(self):
        """Saving twice with the same key is a no-op, not an error."""
        repo = FakeCdrRepository()
        rc1 = _make_rated_call(idempotency_key="k1")
        rc2 = _make_rated_call(idempotency_key="k1", amount="0.10")
        await repo.save(rc1)
        await repo.save(rc2)  # should not raise
        assert repo.save_count == 1  # only first write counts
        found = await repo.find_by_idempotency_key("k1")
        assert found.amount == rc1.amount  # first-write-wins

    async def test_find_by_idempotency_key_miss(self):
        repo = FakeCdrRepository()
        assert await repo.find_by_idempotency_key("nonexistent") is None

    async def test_find_by_caller(self):
        repo = FakeCdrRepository()
        await repo.save(_make_rated_call(idempotency_key="k1", caller="+86A"))
        await repo.save(_make_rated_call(idempotency_key="k2", caller="+86A"))
        await repo.save(_make_rated_call(idempotency_key="k3", caller="+86B"))
        results = await repo.find_by_caller("+86A")
        assert len(results) == 2

    async def test_find_by_caller_respects_limit(self):
        repo = FakeCdrRepository()
        for i in range(5):
            await repo.save(_make_rated_call(idempotency_key=f"k{i}", caller="+86A"))
        results = await repo.find_by_caller("+86A", limit=2)
        assert len(results) == 2

    async def test_find_by_caller_empty(self):
        repo = FakeCdrRepository()
        assert await repo.find_by_caller("+86A") == []


# ── FakeUnitOfWork tests ──────────────────────────────────────────────────

class TestFakeUnitOfWork:
    async def test_commit(self):
        uow = FakeUnitOfWork()
        rc = _make_rated_call(idempotency_key="k1")
        await uow.cdr_repo.save(rc)
        await uow.commit()
        assert uow.committed

    async def test_auto_rollback_on_exception(self):
        uow = FakeUnitOfWork()
        try:
            async with uow:
                await uow.cdr_repo.save(_make_rated_call(idempotency_key="k1"))
                raise RuntimeError("boom")
        except RuntimeError:
            pass
        assert uow.rolled_back

    async def test_explicit_context_manager(self):
        uow = FakeUnitOfWork()
        async with uow:
            await uow.cdr_repo.save(_make_rated_call(idempotency_key="k1"))
            await uow.commit()
        assert uow.committed


# ── helpers ────────────────────────────────────────────────────────────────

UTC = timezone.utc
CST = timezone(timedelta(hours=8))


def _make_rated_call(**overrides) -> RatedCall:
    kwargs = {
        "cdr_id": "abc",
        "caller": "+8613800000001",
        "callee": "+14150000000",
        "call_start_time": datetime(2026, 6, 5, 14, 30, 0, tzinfo=CST),
        "country_code": "+1",
        "tier": "VIP",
        "night_valley_applied": False,
        "amount": Decimal("0.045"),
        "currency": "CNY",
        "idempotency_key": "test-key",
        "rated_at": datetime(2026, 6, 5, 14, 30, 1, tzinfo=UTC),
    }
    kwargs.update(overrides)
    if "amount" in overrides:
        kwargs["amount"] = Decimal(overrides["amount"])
    return RatedCall(**kwargs)
