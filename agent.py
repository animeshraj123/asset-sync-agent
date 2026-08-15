"""
agent.py
--------
The decision-making core. Every tick, for every asset, the agent asks:

  1. Is this asset worth spending a query on right now?
  2. Which sensor(s) first? -> cheapest first (telemetry, rfid_gate).
  3. Do the cheap readings agree? If not, cross-check with uwb_tracker.
  4. Is the remaining disagreement worth the expensive vision sensor?
  5. Reconcile: recency- and reliability-weighted vote, not "trust the newest."
"""

from __future__ import annotations
import random
from world import World, ZONES
from sensors import Sensor
from belief import Belief

RECENCY_DECAY = 0.75
PRIORITY_ACTION_THRESHOLD = 0.065
CONFIDENCE_RESOLVED_THRESHOLD = 0.60

ROOM_NAME = {f"Z{i}": f"Room {i}" for i in range(1, 7)}
SENSOR_NAME = {
    "telemetry": "Radio check-in",
    "rfid_gate": "Doorway scanner",
    "uwb_tracker": "Position tracker",
    "vision_checkpoint": "Camera",
}


def room(z):
    return ROOM_NAME.get(z, z)


def conflict_magnitude(zones_with_weights: dict[str, float]) -> float:
    if len(zones_with_weights) <= 1:
        return 0.0
    items = sorted(zones_with_weights.items(), key=lambda x: -x[1])
    total = sum(zones_with_weights.values())
    top_share = items[0][1] / total
    spread = max(abs(ZONES.index(z1) - ZONES.index(z2))
                 for z1 in zones_with_weights for z2 in zones_with_weights) / (len(ZONES) - 1)
    contestedness = 1 - top_share
    return round(min(1.0, 0.6 * spread + 0.6 * contestedness), 3)


class Agent:
    def __init__(self, world: World, sensors: dict[str, Sensor], cost_tracker,
                 budget_per_tick: float = 20.0, rng: random.Random | None = None):
        self.world = world
        self.sensors = sensors
        self.cost = cost_tracker
        self.budget_per_tick = budget_per_tick
        self.rng = rng or random.Random(7)
        self.beliefs: dict[str, Belief] = {aid: Belief(asset_id=aid) for aid in world.assets}

    def _priority(self, aid: str, tick: int) -> float:
        belief = self.beliefs[aid]
        true = self.world.assets[aid]
        eff_conf = belief.effective_zone_confidence(tick)
        uncertainty = 1.0 - eff_conf
        if belief.zone is None:
            uncertainty = 1.0
        return round(uncertainty * (0.4 + 0.6 * true.criticality), 4)

    def _reconcile(self, aid: str, readings: list[tuple[Sensor, dict]], tick: int):
        belief = self.beliefs[aid]
        self.cost.log_reconciliation()

        zone_votes: dict[str, float] = {}
        for sensor, data in readings:
            if not data or "zone" not in data:
                continue
            age = max(0, tick - data["tick_observed"])
            weight = sensor.reliability * data.get("confidence_hint", sensor.reliability) * (RECENCY_DECAY ** age)
            zone_votes[data["zone"]] = zone_votes.get(data["zone"], 0.0) + weight

        if not zone_votes:
            self.cost.decisions_log.append(
                f"tick {tick}: reconciliation for {aid} had no usable zone readings "
                f"(sensors returned None) — belief left unchanged, will retry next tick"
            )
            self.cost.friendly_log.append(
                f"😶 Robot {aid}: nobody answered this turn — belief unchanged, will try again next turn.")
            return

        mag = conflict_magnitude(zone_votes)
        best_zone, best_weight = max(zone_votes.items(), key=lambda x: x[1])
        total_weight = sum(zone_votes.values())
        conf = best_weight / total_weight

        if mag > 0.15 and conf < CONFIDENCE_RESOLVED_THRESHOLD:
            belief.flagged_for_review = True
            reason = (f"tick {tick}: conflicting zone reports for {aid} "
                      f"{ {z: round(w,2) for z,w in zone_votes.items()} } "
                      f"— best candidate '{best_zone}' only reached confidence "
                      f"{conf:.2f} (< {CONFIDENCE_RESOLVED_THRESHOLD}); flagged for human review "
                      f"rather than silently picking a winner")
            belief.review_reason = reason
            belief.review_history.append(reason)
            self.cost.human_flags.append(reason)
            self.cost.friendly_log.append(
                f"🚩 Robot {aid}: sensors still can't agree confidently — flagging for a human to check.")
        else:
            belief.zone = best_zone
            belief.zone_confidence = min(0.99, conf)
            belief.zone_updated = tick
            belief.zone_source = "+".join(sorted({s.name for s, d in readings if d and "zone" in d}))
            belief.flagged_for_review = False

            sources_used = ", ".join(SENSOR_NAME.get(s.name, s.name) for s, d in readings if d and "zone" in d)
            self.cost.routine_log.append(
                f"tick {tick}: ✅ Robot {aid} confirmed in {room(best_zone)} "
                f"(confidence {conf:.2f}) using {sources_used}."
            )

        for sensor, data in readings:
            if data and "battery" in data:
                belief.battery = data["battery"]
                belief.battery_updated = tick
            if data and "status" in data:
                if sensor.reliability >= 0.9:
                    belief.status = data["status"]
                    belief.status_confidence = sensor.reliability
                    belief.status_updated = tick

    def _expected_value_of_escalation(self, aid: str, mag: float) -> float:
        true = self.world.assets[aid]
        return round(mag * (0.3 + 0.7 * true.criticality) * 10, 2)

    def run_tick(self):
        tick = self.world.tick
        budget = self.budget_per_tick

        ranked = sorted(self.world.assets.keys(), key=lambda a: -self._priority(a, tick))

        for aid in ranked:
            priority = self._priority(aid, tick)

            if priority < PRIORITY_ACTION_THRESHOLD:
                msg = (f"tick {tick}: skipped {aid} — priority {priority:.3f} below action "
                       f"threshold {PRIORITY_ACTION_THRESHOLD} (belief still fresh/confident enough)")
                self.cost.skipped.append(msg)
                self.cost.friendly_log.append(
                    f"🟢 Robot {aid}: still confident where it is — skipped checking to save cost.")
                continue

            if budget <= 0:
                msg = (f"tick {tick}: stopped scheduling — budget exhausted before reaching "
                       f"{aid} (priority {priority:.3f}); remaining uncertainty carried to next tick")
                self.cost.decisions_log.append(msg)
                self.cost.friendly_log.append(
                    f"⏳ Ran out of budget this turn before checking Robot {aid} — will check it next turn.")
                break

            true_state = self.world.assets[aid]
            readings: list[tuple[Sensor, dict]] = []

            for key in ("telemetry", "rfid_gate"):
                s = self.sensors[key]
                if budget < s.cost:
                    continue
                data = s.query(aid, true_state, tick)
                budget -= s.cost
                self.cost.log_query(s)
                if data:
                    readings.append((s, data))

            zones_seen: dict[str, float] = {}
            for s, d in readings:
                if "zone" in d:
                    zones_seen[d["zone"]] = zones_seen.get(d["zone"], 0.0) + 1.0
            mag = conflict_magnitude(zones_seen)
            need_crosscheck = mag > 0 or not readings

            if need_crosscheck and budget >= self.sensors["uwb_tracker"].cost:
                s = self.sensors["uwb_tracker"]
                data = s.query(aid, true_state, tick)
                budget -= s.cost
                self.cost.log_query(s)
                if data:
                    readings.append((s, data))
                zones_seen = {}
                for sr, d in readings:
                    if "zone" in d:
                        zones_seen[d["zone"]] = zones_seen.get(d["zone"], 0.0) + 1.0
                mag = conflict_magnitude(zones_seen)

            if mag > 0 and budget >= self.sensors["vision_checkpoint"].cost:
                ev = self._expected_value_of_escalation(aid, mag)
                if ev > self.sensors["vision_checkpoint"].cost:
                    s = self.sensors["vision_checkpoint"]
                    data = s.query(aid, true_state, tick)
                    budget -= s.cost
                    self.cost.log_query(s)
                    note = (f"tick {tick}: ESCALATED to vision_checkpoint for {aid} — "
                            f"conflict_magnitude={mag:.2f}, criticality={true_state.criticality:.2f}, "
                            f"expected_value={ev:.2f} > sensor cost {s.cost} -> justified")
                    self.cost.escalations.append(note)
                    self.cost.friendly_log.append(
                        f"📸 Robot {aid}: sensors disagreed a lot and it's an important robot — "
                        f"paid for the expensive camera to be sure.")
                    if data:
                        readings.append((s, data))
                    else:
                        self.cost.decisions_log.append(
                            f"tick {tick}: vision_checkpoint queried for {aid} but camera did not "
                            f"cover it this tick (availability={s.availability}) — cost spent, no data returned"
                        )
                        self.cost.friendly_log.append(
                            f"📸 Robot {aid}: paid for the camera, but it wasn't pointed at the right "
                            f"room this turn — spent the cost, learned nothing new.")
                else:
                    self.cost.decisions_log.append(
                        f"tick {tick}: conflict for {aid} (mag={mag:.2f}) NOT escalated — "
                        f"expected_value={ev:.2f} <= vision sensor cost {self.sensors['vision_checkpoint'].cost} "
                        f"(criticality {true_state.criticality:.2f} too low to justify the spend)"
                    )
                    self.cost.friendly_log.append(
                        f"🤔 Robot {aid}: cheap sensors disagreed a bit, but it's not important enough "
                        f"to pay for the camera — went with the best guess instead.")

            if readings:
                self._reconcile(aid, readings, tick)

        return budget
