"""Duration value object — call length in seconds."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Duration:
    """Call duration in whole seconds. Non-negative."""

    seconds: int

    def __post_init__(self):
        if self.seconds < 0:
            raise ValueError(
                f"Duration must be non-negative, got {self.seconds}"
            )
