"""Application-layer ports (interfaces) for external system integration.

These abstract ports follow the hexagonal/ports-and-adapters pattern:
the domain layer never knows about Redis, gRPC, or HTTP.  Application
services depend on these abstractions, and infrastructure adapters
implement them.
"""

from abc import ABC, abstractmethod

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
