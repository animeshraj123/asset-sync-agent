"""
app.py
------
Streamlit dashboard for the asset synchronisation agent. Reuses the exact
same World / sensors / Agent / CostTracker classes as demo.py — this is a
visualisation layer, not a second implementation, so anything defensible
about the CLI run is equally true here.

Run: streamlit run app.py
"""

import random
import pandas as pd
import streamlit as st

from world import World, AssetTrueState, ZONES
from sensors import build_sensors
from agent import Agent
from cost import CostTracker

st.set_page_config(page_title="Asset Sync Agent", layout="wide")

CRITICALITY = {
    "R1": 0.9, "R2": 0.35, "R3": 0.5, "R4": 0.9,
    "R5": 0.3, "R6": 0.45, "R7": 0.85, "R8": 0.4,
}


def build_fleet(seed: int) -> dict[str, AssetTrueState]:
    rng = random.Random(seed)
    return {
        aid: AssetTrueState(
            asset_id=aid, zone=rng.choice(ZONES),
            battery=rng.uniform(40, 95), status="idle", criticality=crit,
        )
        for aid, crit in CRITICALITY.items()
    }


def init_sim(seed: int, budget: float):
    fleet = build_fleet(seed)
    world = World(fleet, seed=seed)
    sensors = build_sensors(random.Random(seed + 1))
    cost = CostTracker()
    agent = Agent(world, sensors, cost, budget_per_tick=budget, rng=random.Random(seed + 2))
    st.session_state.world = world
    st.session_state.sensors = sensors
    st.session_state.cost = cost
    st.session_state.agent = agent
    st.session_state.history = []  # cumulative cost per tick, for the chart
    st.session_state.tick_logs = {}  # tick -> list[str] of this tick's log lines


def run_one_tick():
    world = st.session_state.world
    agent = st.session_state.agent
    cost = st.session_state.cost

    before = {"ops": cost.total_operations, "cost": cost.total_cost}
    world.step()
    unspent = agent.run_tick()
    tick = world.tick

    lines = []
    for entry in cost.escalations:
        if entry.startswith(f"tick {tick}:"):
            lines.append(f"🔺 ESCALATION — {entry}")
    for entry in cost.human_flags:
        if entry.startswith(f"tick {tick}:"):
            lines.append(f"🚩 REVIEW FLAG — {entry}")
    for entry in cost.decisions_log:
        if entry.startswith(f"tick {tick}:"):
            lines.append(f"⚙️ decision — {entry}")
    for entry in cost.skipped:
        if entry.startswith(f"tick {tick}:"):
            lines.append(f"⏭️ skip — {entry}")
    st.session_state.tick_logs[tick] = lines

    st.session_state.history.append({
        "tick": tick,
        "cumulative_cost": round(cost.total_cost, 2),
        "cumulative_ops": cost.total_operations,
        "budget_spent_this_tick": round(agent.budget_per_tick - unspent, 2),
    })


# ---------------- sidebar ----------------
st.sidebar.title("Simulation controls")
seed = st.sidebar.number_input("Random seed", value=42, step=1)
budget = st.sidebar.slider("Per-tick budget (cost units)", 5.0, 40.0, 20.0, step=1.0)
n_ticks_full = st.sidebar.slider("Ticks for 'run full simulation'", 5, 40, 20)

if "world" not in st.session_state:
    init_sim(seed, budget)

col_a, col_b, col_c = st.sidebar.columns(3)
if col_a.button("Reset"):
    init_sim(seed, budget)
    st.rerun()
if col_b.button("Step +1"):
    run_one_tick()
if col_c.button("Run full"):
    for _ in range(n_ticks_full - st.session_state.world.tick):
        if st.session_state.world.tick >= n_ticks_full:
            break
        run_one_tick()

st.sidebar.caption(
    "Sensors: telemetry (cost 1, 95% reliable, 20% packet loss) · "
    "rfid_gate (cost 1, 92% reliable, event-driven/stale) · "
    "uwb_tracker (cost 2, 85% reliable, systematic drift) · "
    "vision_checkpoint (cost 5, 97% reliable, 40% coverage)."
)

# ---------------- header ----------------
st.title("📦 Asset Synchronisation Agent")
st.caption(
    "Live inventory across 4 unreliable sensors. Every query, reconciliation, "
    "escalation, and skip is a logged, cost-justified decision — not a fixed poll loop."
)

world = st.session_state.world
agent = st.session_state.agent
cost = st.session_state.cost
breakdown = cost.breakdown()

m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("Tick", world.tick)
m2.metric("Total operations", breakdown["total_operations"])
m3.metric("Total cost (units)", breakdown["total_cost_units"])
m4.metric("Escalations", breakdown["escalations_to_expensive_sensor"])
m5.metric("Human review flags", breakdown["human_review_flags"])

# naive baseline comparison, live
if world.tick > 0:
    naive_per_tick = sum(s.cost for s in st.session_state.sensors.values()) * len(world.assets)
    naive_total = naive_per_tick * world.tick
    savings = 1 - breakdown["total_cost_units"] / naive_total if naive_total else 0
    st.info(
        f"Naive baseline (query all 4 sensors for all {len(world.assets)} assets, every tick) "
        f"would cost **{naive_total} units** by now. Agent has spent **{breakdown['total_cost_units']} units** "
        f"— a **{savings*100:.1f}%** reduction."
    )

# ---------------- belief vs ground truth ----------------
st.subheader("Belief vs. ground truth (per asset)")
rows = []
for aid, belief in agent.beliefs.items():
    true = world.assets[aid]
    rows.append({
        "Asset": aid,
        "Criticality": true.criticality,
        "Believed zone": belief.zone,
        "True zone": true.zone,
        "Match": "✅" if belief.zone == true.zone else "❌",
        "Confidence": round(belief.zone_confidence, 2),
        "Source": belief.zone_source if belief.zone_source else "—",
        "Last updated (tick)": belief.zone_updated if belief.zone_updated > -900 else "—",
        "Flagged for review": "🚩" if belief.flagged_for_review else "",
    })
df = pd.DataFrame(rows).sort_values("Criticality", ascending=False)
st.dataframe(df, use_container_width=True, hide_index=True)

# ---------------- cost breakdown ----------------
st.subheader("Cost breakdown by sensor")
cost_df = pd.DataFrame([
    {"sensor": k, "queries": breakdown["queries_by_sensor"].get(k, 0), "cost_units": v}
    for k, v in breakdown["cost_by_sensor"].items()
])
if not cost_df.empty:
    c1, c2 = st.columns(2)
    c1.bar_chart(cost_df.set_index("sensor")["cost_units"])
    c2.bar_chart(cost_df.set_index("sensor")["queries"])

# ---------------- cost over time ----------------
if st.session_state.history:
    st.subheader("Cumulative cost over time")
    hist_df = pd.DataFrame(st.session_state.history).set_index("tick")
    st.line_chart(hist_df[["cumulative_cost", "cumulative_ops"]])

# ---------------- decision log ----------------
st.subheader("Decision log")
if not st.session_state.tick_logs:
    st.write("Run a tick to see the agent's reasoning.")
else:
    for tick in sorted(st.session_state.tick_logs.keys(), reverse=True):
        lines = st.session_state.tick_logs[tick]
        label = f"Tick {tick}" + (f" — {len(lines)} notable decisions" if lines else " — routine, nothing flagged")
        with st.expander(label, expanded=(tick == world.tick)):
            if lines:
                for line in lines:
                    st.write(line)
            else:
                st.write("All assets within confident/fresh range — no escalation, no conflict, no skip needed.")
