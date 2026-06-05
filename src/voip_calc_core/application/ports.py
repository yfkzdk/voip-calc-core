"""Application-layer ports (interfaces) for external system integration.

These abstract ports follow the hexagonal/ports-and-adapters pattern:
the domain layer never knows about Redis, gRPC, or HTTP.  Application
services depend on these abstractions, and infrastructure adapters
implement them.
"""

from abc import ABC, abstractmethod
from typing import Optional

from voip_calc_core.domain.customer_tier import CustomerTier


class CustomerProfileFetcher(ABC):
    """Abstract port for resolving a caller's identity tier.

    Implementations may query a Redis cache, call an account microservice
    via gRPC, or return a hard-coded default.  The application service
    owns degradation — adapters should raise on failure, not swallow.
    """

    @abstractmethod
    async def fetch_tier_by_phone(self, phone_number: str) -> CustomerTier:
        """Return the customer tier for *phone_number*.

        Raises:
            Any exception on failure.  The caller is responsible for
            catching and degrading (e.g. falling back to NORMAL).
        """
        ...


class CdrRepository(ABC):
    """Abstract port for CDR (Call Detail Record) persistence.

    The application service uses this port to store rated call records
    without knowing the underlying storage engine.  Implementations may
    use SQLite, PostgreSQL, or an in-memory store for testing.
    """

    @abstractmethod
    async def save(self, rated_call: "RatedCall") -> None:
        """Persist *rated_call*.  Must be idempotent (idempotency_key)."""
        ...

    @abstractmethod
    async def find_by_idempotency_key(self, key: str) -> Optional["RatedCall"]:
        """Return the previously-saved record for *key*, or ``None``."""
        ...

    @abstractmethod
    async def find_by_caller(
        self, caller: str, limit: int = 50
    ) -> list["RatedCall"]:
        """Return recent rated calls for *caller* (audit trail)."""
        ...


class AbstractUnitOfWork(ABC):
    """Atomic transaction boundary for CDR writes.

    Usage::

        async with uow:
            await uow.cdr_repo.save(rated_call)
            await uow.commit()

    .. warning::

       Implementations of ``__aexit__`` must preserve the **original**
       exception when ``commit()`` fails.  If ``rollback()`` also raises,
       the rollback exception must not mask the commit failure — otherwise
       upstream circuit breakers will see the wrong error.
    """

    cdr_repo: CdrRepository

    async def __aenter__(self) -> "AbstractUnitOfWork":
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        if exc_type is not None:
            await self.rollback()
            return
        try:
            await self.commit()
        except BaseException:
            try:
                await self.rollback()
            except BaseException:
                pass
            raise

    @abstractmethod
    async def commit(self) -> None:
        ...

    @abstractmethod
    async def rollback(self) -> None:
        ...
