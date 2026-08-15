"""
world.py
--------
Ground-truth simulation. This represents reality: where the assets actually
are, what state they're actually in. The agent NEVER reads this directly —
it only ever sees it through sensors.py, which corrupt/delay/drop it in
different ways. This file exists so we can score the agent's beliefs
against reality at the end of the demo and prove the decisions were sound,
not just plausible-sounding.
"""

import random
from dataclasses import dataclass

ZONES = ["Z1", "Z2", "Z3", "Z4", "Z5", "Z6"]
STATUSES = ["idle", "moving", "charging", "error"]


@dataclass
class AssetTrueState:
    asset_id: str
    zone: str
    battery: float
    status: str
    criticality: float  # 0..1 — e.g. a robot currently carrying cargo is worth more certainty


class World:
    """Advances ground truth by one tick at a time. A tick ~= one polling
    interval in a real deployment (e.g. 30s-1min)."""

    def __init__(self, assets: dict[str, AssetTrueState], seed: int = 42):
        self.assets = assets
        self.tick = 0
        self.rng = random.Random(seed)
        self._error_injected = False

    def step(self):
        self.tick += 1
        rng = self.rng
        for a in self.assets.values():
            if a.status != "charging" and rng.random() < 0.30:
                idx = ZONES.index(a.zone)
                idx = max(0, min(len(ZONES) - 1, idx + rng.choice([-1, 1])))
                a.zone = ZONES[idx]

            if a.status == "charging":
                a.battery = min(100, a.battery + rng.uniform(4, 8))
                if a.battery > 85 and rng.random() < 0.4:
                    a.status = "idle"
            else:
                a.battery = max(0, a.battery - rng.uniform(0.5, 2.5))

            if a.battery < 15 and a.status != "charging":
                a.status = "charging"
            elif a.status != "charging" and rng.random() < 0.06:
                a.status = rng.choice(["idle", "moving"])

        if self.tick == 12 and not self._error_injected:
            victim = self.assets.get("R4")
            if victim:
                victim.status = "error"
                victim.zone = "Z6"
                self._error_injected = True
