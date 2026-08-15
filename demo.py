"""
demo.py
-------
End-to-end demonstration: 8 assets, 4 sensors, 20 ticks. Prints a running
log of decisions, then a final report: total operations, cost breakdown,
accuracy against ground truth, and a naive-baseline comparison.

Run: python demo.py
"""

import json
import random
from world import World, AssetTrueState, ZONES
from sensors import build_sensors
from agent import Agent
from cost import CostTracker

N_TICKS = 20
SEED = 42


def build_fleet() -> dict[str, AssetTrueState]:
    rng = random.Random(SEED)
    criticality = {
        "R1": 0.9, "R2": 0.35, "R3": 0.5, "R4": 0.9,
        "R5": 0.3, "R6": 0.45, "R7": 0.85, "R8": 0.4,
    }
    fleet = {}
    for aid, crit in criticality.items():
        fleet[aid] = AssetTrueState(
            asset_id=aid, zone=rng.choice(ZONES),
            battery=rng.uniform(40, 95), status="idle", criticality=crit,
        )
    return fleet


def accuracy_report(agent: Agent, world: World) -> dict:
    correct, total = 0, 0
    per_asset = {}
    for aid, belief in agent.beliefs.items():
        true = world.assets[aid]
        hit = belief.zone == true.zone
        per_asset[aid] = {
            "believed_zone": belief.zone, "true_zone": true.zone, "match": hit,
            "belief_confidence": round(belief.zone_confidence, 2),
            "flagged_for_review": belief.flagged_for_review,
        }
        total += 1
        correct += int(hit)
    return {"per_asset": per_asset, "final_accuracy": round(correct / total, 2)}


def naive_baseline_cost(sensors, n_assets: int, n_ticks: int) -> dict:
    per_tick = sum(s.cost for s in sensors.values()) * n_assets
    return {
        "description": "cost if every sensor were queried for every asset on every tick",
        "cost_per_tick": per_tick,
        "total_cost_over_run": per_tick * n_ticks,
    }


def main():
    fleet = build_fleet()
    world = World(fleet, seed=SEED)
    rng = random.Random(SEED + 1)
    sensors = build_sensors(rng)
    cost = CostTracker()
    agent = Agent(world, sensors, cost, budget_per_tick=20.0, rng=random.Random(SEED + 2))

    print("=" * 78)
    print("ASSET SYNCHRONISATION AGENT — DEMO RUN")
    print(f"{len(fleet)} assets, {len(sensors)} sensors, {N_TICKS} ticks")
    print("=" * 78)

    for _ in range(N_TICKS):
        world.step()
        unspent = agent.run_tick()
        tick = world.tick
        print(f"\n--- tick {tick} (budget spent: {agent.budget_per_tick - unspent:.1f}/{agent.budget_per_tick}) ---")
        for log_list, label in [(cost.escalations, "ESCALATION"), (cost.human_flags, "REVIEW FLAG")]:
            for entry in log_list:
                if entry.startswith(f"tick {tick}:"):
                    print(f"  [{label}] {entry}")
        for entry in cost.decisions_log:
            if entry.startswith(f"tick {tick}:"):
                print(f"  [decision] {entry}")
        for entry in cost.skipped:
            if entry.startswith(f"tick {tick}:"):
                print(f"  [skip]     {entry}")

    print("\n" + "=" * 78)
    print("FINAL REPORT")
    print("=" * 78)

    breakdown = cost.breakdown()
    acc = accuracy_report(agent, world)
    baseline = naive_baseline_cost(sensors, len(fleet), N_TICKS)

    print(f"\nTotal operations performed: {breakdown['total_operations']}")
    print(f"  Sensor queries by type : {breakdown['queries_by_sensor']}")
    print(f"  Cost by sensor type    : {breakdown['cost_by_sensor']}")
    print(f"  Reconciliation cycles  : {breakdown['reconciliation_cycles']} (cost {breakdown['reconciliation_cost']})")
    print(f"  Total cost incurred    : {breakdown['total_cost_units']} units")
    print(f"  Escalations to vision  : {breakdown['escalations_to_expensive_sensor']}")
    print(f"  Human review flags     : {breakdown['human_review_flags']}")
    print(f"  Assets skipped (cheap) : {breakdown['assets_skipped_as_not_worth_querying']}")

    print(f"\nFinal belief accuracy vs ground truth: {acc['final_accuracy']*100:.0f}%")
    for aid, info in acc["per_asset"].items():
        flag = " <== FLAGGED FOR HUMAN REVIEW" if info["flagged_for_review"] else ""
        mark = "OK " if info["match"] else "OFF"
        print(f"  {aid}: believed={info['believed_zone']} true={info['true_zone']} "
              f"[{mark}] conf={info['belief_confidence']}{flag}")

    print(f"\nNaive baseline (query everything, every tick): "
          f"{baseline['total_cost_over_run']} cost units over {N_TICKS} ticks")
    print(f"Actual cost incurred by agent                : {breakdown['total_cost_units']} cost units")
    savings = 1 - breakdown["total_cost_units"] / baseline["total_cost_over_run"]
    print(f"Savings from cost-aware scheduling            : {savings*100:.1f}%")

    report = {
        "config": {"n_assets": len(fleet), "n_ticks": N_TICKS, "seed": SEED,
                    "budget_per_tick": agent.budget_per_tick},
        "cost_breakdown": breakdown,
        "accuracy": acc,
        "naive_baseline": baseline,
        "savings_pct": round(savings * 100, 1),
        "escalation_log": cost.escalations,
        "human_review_flags": cost.human_flags,
        "sample_decisions": cost.decisions_log[:40],
    }
    with open("run_report.json", "w") as f:
        json.dump(report, f, indent=2)
    print("\nFull machine-readable report written to run_report.json")


if __name__ == "__main__":
    main()
