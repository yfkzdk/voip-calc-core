"""CustomerTier value object. Encapsulates customer identity and discount rate."""

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum


class TierEnum(Enum):
    VIP = "VIP"
    NORMAL = "NORMAL"


@dataclass(frozen=True)
class CustomerTier:
    """Customer identity tier with associated discount rate."""

    tier: TierEnum

    _DISCOUNT_RATES = {
        TierEnum.VIP: Decimal("0.9"),
        TierEnum.NORMAL: Decimal("1.0"),
    }

    def discount_rate(self) -> Decimal:
        return self._DISCOUNT_RATES[self.tier]

    def label(self) -> str:
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
