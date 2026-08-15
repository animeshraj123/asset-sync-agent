"""
belief.py
---------
What the agent believes about each asset, distinct from ground truth.
Confidence decays over time since the last update, which is what drives
re-querying rather than sitting on stale-but-uncontested data forever.
"""

from dataclasses import dataclass, field

DECAY_PER_TICK = 0.92


@dataclass
class Belief:
    asset_id: str
    zone: str | None = None
    zone_confidence: float = 0.0
    zone_updated: int = -999
    zone_source: str | None = None

    battery: float | None = None
    battery_updated: int = -999

    status: str | None = None
    status_confidence: float = 0.0
    status_updated: int = -999

    flagged_for_review: bool = False
    review_reason: str = ""
    review_history: list[str] = field(default_factory=list)

    def effective_zone_confidence(self, tick: int) -> float:
        staleness = max(0, tick - self.zone_updated)
        return self.zone_confidence * (DECAY_PER_TICK ** staleness)

    def zone_staleness(self, tick: int) -> int:
        return max(0, tick - self.zone_updated)
