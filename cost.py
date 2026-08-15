"""
cost.py
-------
Every unit of work the agent does gets counted here.
"""

from dataclasses import dataclass, field

RECONCILIATION_COST = 0.5


@dataclass
class CostTracker:
    query_counts: dict[str, int] = field(default_factory=dict)
    query_cost: dict[str, float] = field(default_factory=dict)
    reconciliations: int = 0
    escalations: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    human_flags: list[str] = field(default_factory=list)
    decisions_log: list[str] = field(default_factory=list)

    def log_query(self, sensor):
        self.query_counts[sensor.name] = self.query_counts.get(sensor.name, 0) + 1
        self.query_cost[sensor.name] = self.query_cost.get(sensor.name, 0) + sensor.cost

    def log_reconciliation(self):
        self.reconciliations += 1

    @property
    def total_query_cost(self) -> float:
        return sum(self.query_cost.values())

    @property
    def total_cost(self) -> float:
        return self.total_query_cost + self.reconciliations * RECONCILIATION_COST

    @property
    def total_operations(self) -> int:
        return sum(self.query_counts.values()) + self.reconciliations

    def breakdown(self) -> dict:
        return {
            "queries_by_sensor": dict(self.query_counts),
            "cost_by_sensor": {k: round(v, 2) for k, v in self.query_cost.items()},
            "reconciliation_cycles": self.reconciliations,
            "reconciliation_cost": round(self.reconciliations * RECONCILIATION_COST, 2),
            "total_operations": self.total_operations,
            "total_cost_units": round(self.total_cost, 2),
            "escalations_to_expensive_sensor": len(self.escalations),
            "human_review_flags": len(self.human_flags),
            "assets_skipped_as_not_worth_querying": len(self.skipped),
        }
