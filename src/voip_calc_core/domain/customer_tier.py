"""CustomerTier value object. Encapsulates customer identity and discount rate."""

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum


class TierEnum(Enum):
    VIP = "VIP"
    NORMAL = "NORMAL"


@dataclass(frozen=True)
class CustomerTier:
    """Customer identity tier with associated discount rate.

    VIP    → 0.9 (10% discount, for overseas students / Chinese diaspora)
    NORMAL → 1.0 (no discount)
    """

    tier: TierEnum

    _DISCOUNT_RATES = {
        TierEnum.VIP: Decimal("0.9"),
        TierEnum.NORMAL: Decimal("1.0"),
    }

    def discount_rate(self) -> Decimal:
        """Return the discount multiplier for this tier."""
        return self._DISCOUNT_RATES[self.tier]

    def label(self) -> str:
        """Return human-readable tier label."""
        return self.tier.value

    @classmethod
    def from_label(cls, label: str) -> "CustomerTier":
        """Construct CustomerTier from a case-insensitive label."""
        try:
            return cls(TierEnum(label.upper()))
        except (ValueError, KeyError):
            valid = ", ".join(e.value for e in TierEnum)
            raise ValueError(
                f"Unknown customer tier: '{label}'. Valid tiers: {valid}"
            )
