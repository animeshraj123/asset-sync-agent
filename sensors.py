"""
sensors.py
----------
Four distinct data sources modeling real industrial sensor classes.
Each exposes .query(asset_id, true_state, tick) -> dict | None with an
honest cost and reliability profile.

1. RFIDGateSensor  - cheap, event-driven, goes STALE between gate crossings.
2. UWBTrackerSensor - continuous but subject to systematic drift ("confidently wrong").
3. TelemetrySelfReportSensor - most complete data, highest reliability, but packet loss.
4. VisionCheckpointSensor - expensive, most reliable when it fires, limited coverage.
"""

from __future__ import annotations
import random
from world import ZONES, STATUSES, AssetTrueState


class Sensor:
    name = "base"
    cost = 1
    reliability = 1.0

    def query(self, asset_id: str, true_state: AssetTrueState, tick: int) -> dict | None:
        raise NotImplementedError


class RFIDGateSensor(Sensor):
    name = "rfid_gate"
    cost = 1
    reliability = 0.92

    def __init__(self, rng: random.Random):
        self.rng = rng
        self._last_seen: dict[str, tuple[str, int]] = {}

    def query(self, asset_id, true_state, tick):
        if self.rng.random() < 0.55:
            zone = true_state.zone if self.rng.random() < self.reliability else self.rng.choice(ZONES)
            self._last_seen[asset_id] = (zone, tick)
        if asset_id in self._last_seen:
            zone, seen_tick = self._last_seen[asset_id]
            return {"zone": zone, "tick_observed": seen_tick, "confidence_hint": self.reliability}
        return None


class UWBTrackerSensor(Sensor):
    name = "uwb_tracker"
    cost = 2
    reliability = 0.85

    def __init__(self, rng: random.Random):
        self.rng = rng
        self._drift_until: dict[str, int] = {}

    def query(self, asset_id, true_state, tick):
        if asset_id not in self._drift_until and self.rng.random() < 0.035:
            self._drift_until[asset_id] = tick + self.rng.randint(3, 6)

        drifting = asset_id in self._drift_until and tick <= self._drift_until[asset_id]
        if drifting:
            idx = ZONES.index(true_state.zone)
            idx = max(0, min(len(ZONES) - 1, idx + self.rng.choice([-2, -1, 1, 2])))
            zone = ZONES[idx]
            conf_hint = 0.4
        else:
            correct = self.rng.random() < self.reliability
            zone = true_state.zone if correct else self.rng.choice(ZONES)
            conf_hint = self.reliability

        return {"zone": zone, "tick_observed": tick, "confidence_hint": conf_hint}


class TelemetrySelfReportSensor(Sensor):
    name = "telemetry"
    cost = 1
    reliability = 0.95
    packet_loss = 0.20

    def __init__(self, rng: random.Random):
        self.rng = rng

    def query(self, asset_id, true_state, tick):
        if self.rng.random() < self.packet_loss:
            return None
        zone = true_state.zone if self.rng.random() < self.reliability else self.rng.choice(ZONES)
        battery = max(0, min(100, true_state.battery + self.rng.uniform(-2, 2)))
        status = true_state.status if self.rng.random() < self.reliability else self.rng.choice(STATUSES)
        return {
            "zone": zone, "battery": battery, "status": status,
            "tick_observed": tick, "confidence_hint": self.reliability,
        }


class VisionCheckpointSensor(Sensor):
    name = "vision_checkpoint"
    cost = 5
    reliability = 0.97
    availability = 0.40

    def __init__(self, rng: random.Random):
        self.rng = rng

    def query(self, asset_id, true_state, tick):
        if self.rng.random() > self.availability:
            return None
        zone = true_state.zone if self.rng.random() < self.reliability else self.rng.choice(ZONES)
        status = true_state.status if self.rng.random() < self.reliability else self.rng.choice(STATUSES)
        return {"zone": zone, "status": status, "tick_observed": tick, "confidence_hint": self.reliability}


def build_sensors(rng: random.Random) -> dict[str, Sensor]:
    return {
        "rfid_gate": RFIDGateSensor(rng),
        "uwb_tracker": UWBTrackerSensor(rng),
        "telemetry": TelemetrySelfReportSensor(rng),
        "vision_checkpoint": VisionCheckpointSensor(rng),
    }
