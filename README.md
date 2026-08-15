# asset-sync-agent
Cost-aware multi-sensor asset synchronisation agent

Live Demo [https://asset-sync-agent-vzzpode63nsxmvuqjofhro.streamlit.app/]



# Asset Synchronisation Agent

A multi-step agent that maintains a live inventory of physical assets — 8 warehouse
robots — by querying 4 sensors with different cost, latency, and reliability
profiles. It decides which sensors to trust, when to reconcile conflicting
reports, when to escalate to an expensive sensor, and when to stop. It then
reports the exact operational cost of staying synchronised and justifies it,
decision by decision.

```
python demo.py          # CLI run: full decision log + final report
streamlit run app.py    # interactive dashboard: step through it live
```

No external services required. Everything is deterministic given the seed in
`demo.py` / the sidebar, so the same run can be reproduced and audited.

---

## The problem this solves

Sensors disagree, go stale, or drop out — and querying every sensor for every
asset on every cycle to stay safe is wasteful. This agent has to decide, live,
which sensor to trust and when the cost of asking again is no longer worth the
certainty gained. That decision-making — not the sensor plumbing — is the hard
part, and every decision it makes is logged with the numbers behind it.

---

## Project structure

| File | Responsibility |
|---|---|
| `world.py` | Ground-truth simulator. The agent never reads this directly. |
| `sensors.py` | 4 sensor stubs, each modeling a real sensor failure mode. |
| `belief.py` | Per-asset belief state, with confidence that decays over time. |
| `cost.py` | Ledger — every sensor query and reconciliation is counted here. |
| `agent.py` | The decision core: priority, sensor selection, reconciliation, escalation. |
| `demo.py` | Runs 8 assets × 4 sensors × 20 ticks, prints the full decision log and final report. |
| `app.py` | Streamlit dashboard — step through the same simulation live, with technical / plain-English / full-detail log views. |

---

## The four sensors, and why each one exists

| Sensor | Cost | Reliability | Failure mode modeled |
|---|---|---|---|
| `telemetry` (self-report) | 1 | 95% | 20% packet loss — richest data (zone+battery+status), but silently absent 1 in 5 checks |
| `rfid_gate` | 1 | 92% | Event-driven — only updates on a gate crossing, so it goes **stale**, not noisy |
| `uwb_tracker` | 2 | 85% | Occasional **systematic drift** (interference) — confidently wrong for several ticks in a row, not random noise |
| `vision_checkpoint` | 5 | 97% | Only ~40% coverage per tick (fixed checkpoints) — expensive, reliable, and scarce |

These cover the three distinct ways a real sensor misleads you: *silence*
(packet loss), *staleness* (event-driven), and *confident drift*
(interference bias). A strategy that only handled noise would fail against
the drifting UWB sensor; the reconciliation logic below is built specifically
to handle all three at once.

---

## How the agent decides — one tick, one asset, in order

1. **Priority** — `(1 − decayed_confidence) × (0.4 + 0.6 × criticality)`.
   Below a threshold (0.065), the asset is **skipped** entirely — not worth
   even the cheapest sensor. Confidence decays over time since the last
   check (`belief.py`), so a stale-but-once-confident belief becomes
   worth re-checking on its own.
2. **Cheapest sensors first** — `telemetry` and `rfid_gate` (cost 1 each)
   are always queried before anything else.
3. **Cross-check only on disagreement** — `uwb_tracker` (cost 2) is queried
   only if the cheap sensors disagreed or returned nothing. No blind polling.
4. **Escalation is a cost/value comparison, not a rule** —
   `expected_value = conflict_magnitude × (0.3 + 0.7 × criticality) × 10`
   is compared against the vision sensor's cost of 5. The same asset with a
   small conflict is *not* escalated; the same asset with a large one *is* —
   every escalation and every non-escalation is logged with the exact numbers
   that drove it.
5. **Reconciliation** — a recency- and reliability-weighted vote across
   whatever readings came back (not "trust the newest" or "trust the most
   reliable sensor," either of which fails against a drifting-but-fresh
   reading). If the winning zone can't clear 60% confidence and the vote is
   genuinely contested, the agent does **not** guess — it flags the asset for
   human review with the full vote breakdown.
6. **Per-tick budget** (20 cost units by default) is a second, independent
   stopping mechanism modeling a real API rate limit. When it runs out,
   remaining assets carry their uncertainty into the next tick rather than
   being force-queried.

---

## Sample result (seed 42, 20 ticks, 8 assets, budget 20/tick)

```
Total operations performed: 363
  Sensor queries by type : {telemetry: 115, rfid_gate: 113, uwb_tracker: 15, vision_checkpoint: 5}
  Cost by sensor type    : {telemetry: 115, rfid_gate: 113, uwb_tracker: 30, vision_checkpoint: 25}
  Reconciliation cycles  : 115 (cost 57.5)
  Total cost incurred    : 340.5 units
  Escalations to vision  : 5
  Human review flags     : 4
  Assets skipped (cheap) : 45

Final belief accuracy vs ground truth: 100%

Naive baseline (query everything, every tick): 1440 cost units over 20 ticks
Actual cost incurred by agent                : 340.5 cost units
Savings from cost-aware scheduling            : 76.4%
```

The full per-tick decision log (every skip, escalation, reconciliation, and
review flag, with its reasoning) prints during `demo.py` and is also written
to `run_report.json`.

### Ground-truth validation

`world.py` injects one genuine anomaly at tick 12 — asset R4 (high
criticality) is put into an `error` state and relocated unexpectedly, like a
robot being towed or misrouted. This is what drives R4's repeated escalations
and review flags mid-run: the agent isn't reacting to noise, it's reacting to
a high-criticality asset whose cheap sensors genuinely disagree about where
it is — exactly the case the expensive sensor exists for.

---

## The dashboard (`app.py`)

```
pip install -r requirements.txt
streamlit run app.py
```

- **Step +1 / Run full / Reset** — control the simulation live.
- **Belief vs. ground truth table** — per asset: believed zone, true zone,
  match, confidence, which sensor(s) it trusted (`Source`), and whether it's
  flagged for human review.
- **Cost breakdown & cumulative cost charts** — where the spend actually goes.
- **Decision log**, with two independent toggles:
  - **🧒 Simple explanation mode** — the same events in plain English
    (e.g. *"Robot R6: sensors disagreed a lot and it's an important robot —
    paid for the expensive camera to be sure"*) instead of technical terms
    like `expected_value` and `conflict_magnitude`.
  - **🔍 Show routine checks too** — reveals every successful, uneventful
    confirmation as well, not just the notable decisions, so nothing is
    hidden — it's filtered by default purely for readability.

---

## Honest limitations

- **Sensors are stubbed, not live APIs.** Each is written as a swappable
  `.query()` client with a realistic cost/reliability/failure profile, so
  wiring in a real GPS/IoT/vision API means replacing the body of one class —
  the agent's decision logic doesn't need to change.
- **Escalation doesn't yet account for sensor coverage odds.** In the sample
  run, 3 of 5 vision-sensor escalations paid the cost but the camera wasn't
  covering that asset that tick, returning nothing. The decision was still
  reasonable given what the agent knew (`expected_value` vs. cost), but a
  more complete model would multiply in `vision_checkpoint.availability`
  before deciding to escalate — a one-line change, left as a known next step
  rather than something silently worked around.
- **Confidence is reactive, not fully Bayesian.** Each reconciliation
  computes a fresh weighted vote from that tick's readings and then decays
  until the next check — it doesn't compound belief across many past
  observations. This is a deliberate simplicity trade-off (avoids
  overconfidence from repeatedly re-confirming the same source) but is worth
  stating precisely rather than implying full Bayesian tracking.
- **Reconciliation conflict-resolution is zone-only.** `battery` and
  `status` are taken opportunistically from the most reliable sensor that
  reported them, without their own weighted-vote logic the way `zone` has.
- **Tuning constants are hand-set, not learned** — the priority threshold,
  escalation multiplier, and confidence-resolved threshold are documented
  in `agent.py` with the reasoning behind each number, calibrated against
  this specific scenario. A production system would want to calibrate these
  against real cost/error data instead.

---

## Requirements

```
streamlit>=1.35
pandas>=2.0
```

`demo.py` alone has no external dependencies — only `app.py` needs the above.
