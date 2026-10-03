"""Check the risk, expedite and forecast models against the simulator and the provided data.

    python -m simulation.backtest            # prints markdown tables; takes about a minute

* risk      - orders in progress on several mornings versus when they actually finished in a 300-day simulation.
* expedite  - for orders the briefing says to expedite, re-run the simulation with that order moved to the front and compare
              the real change in lateness (for it, and for everyone else) with what the briefing predicted.
* forecast  - rolling replay on the provided orders, see prediction.forecast_backtest.

Limits: the simulator is not a real factory, and it follows the same earliest-due-first rule as the models, so agreement here
shows the models are internally sound, not that they will hold in production.
"""
from __future__ import annotations

import copy
import csv
import json
import statistics as st
import tempfile
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

from .briefing import build
from .prediction import forecast_backtest, working_days_inclusive
from .simulate import BASE_DIR, DEFAULT_SCENARIO, simulate

BASE = date(2026, 4, 1)
HORIZON = 300


def _morning(i: int) -> tuple[Path, date]:
    d = BASE + timedelta(days=i)
    if i == 0:
        return BASE_DIR, d
    folder = Path(tempfile.mkdtemp())
    simulate(d, out=folder)
    return folder, d


def _final(scenario: dict | None = None) -> dict[str, dict]:
    path = DEFAULT_SCENARIO
    if scenario is not None:
        path = Path(tempfile.mkdtemp()) / "s.json"
        path.write_text(json.dumps(scenario))
    out = Path(tempfile.mkdtemp())
    simulate(BASE + timedelta(days=HORIZON), out=out, scenario_path=path)
    with open(out / "orders.csv", newline="", encoding="utf-8") as f:
        return {r["order_id"]: r for r in csv.DictReader(f)}


def _lateness(d: date, order: dict, final: dict[str, dict]) -> int:
    """Working days after the due date at which the order actually finished (horizon end if it never did)."""
    done = final[order["order_id"]]["completed_date"]
    comp = date.fromisoformat(done) if done else BASE + timedelta(days=HORIZON - 1)
    return max(0, working_days_inclusive(d, comp) - working_days_inclusive(d, date.fromisoformat(order["due_date"])))


def risk_check(mornings=(0, 2, 4, 7, 9, 11, 14)) -> None:
    final = _final()
    rows, errs = defaultdict(lambda: [0, 0, []]), []
    for i in mornings:
        folder, d = _morning(i)
        b = build(folder, d)
        for o in b["orders"]:
            done = final[o["order_id"]]["completed_date"]
            late = (done > o["due_date"]) if done else True
            r = rows[o["risk"]["level"]]
            r[0] += 1
            r[1] += late
            if done and o["risk"]["expected_date"]:
                e, a = date.fromisoformat(o["risk"]["expected_date"]), date.fromisoformat(done)
                errs.append((working_days_inclusive(e, a) - 1) if a > e else -(working_days_inclusive(a, e) - 1))
    print("### Risk: level on the morning vs what happened\n\n| Level | Orders | Finished late |\n|---|---|---|")
    for lvl in ("overdue", "high", "medium", "low"):
        if lvl in rows:
            n, late, _ = rows[lvl]
            print(f"| {lvl} | {n} | {late} ({100 * late / n:.0f}%) |")
    print(f"\nExpected finish date vs actual, {len(errs)} orders that finished: mean error {st.mean(errs):+.1f} working days "
          f"(negative = finished earlier than predicted), mean absolute error {st.mean(abs(e) for e in errs):.1f}.\n")


def expedite_check(mornings=(5, 8, 12), per_morning=3) -> None:
    base_scn = json.loads(DEFAULT_SCENARIO.read_text())
    base_final = _final()
    print("### Expedite: predicted vs simulated\n\n| Morning | Order | Briefing says | Gain predicted | Gain simulated | Cost predicted | Cost simulated |\n|---|---|---|---|---|---|---|")
    gains = []
    for i in mornings:
        folder, d = _morning(i)
        b = build(folder, d)
        cands = sorted((o for o in b["orders"] if o["expedite"] and o["expedite"]["recommendation"] != "investigate"),
                       key=lambda o: -o["expedite"]["gain"])[:per_morning]
        for o in cands:
            scn = copy.deepcopy(base_scn)
            scn["events"].append({"id": "X", "type": "expedite", "order_id": o["order_id"], "date": d.isoformat()})
            exp_final = _final(scn)
            active = b["orders"]
            gain = _lateness(d, o, base_final) - _lateness(d, o, exp_final)
            cost = sum(_lateness(d, y, exp_final) - _lateness(d, y, base_final) for y in active if y["order_id"] != o["order_id"])
            e = o["expedite"]
            gains.append((e["gain"], gain, e["cost"], cost))
            print(f"| {d:%d %b} | {o['order_id']} | {e['recommendation']} | {e['gain']} | {gain} | {e['cost']} | {cost} |")
    if gains:
        print(f"\nMean absolute error: gain {st.mean(abs(p - a) for p, a, _, _ in gains):.1f} working days, "
              f"cost {st.mean(abs(p - a) for _, _, p, a in gains):.1f} working days ({len(gains)} orders).\n")


def forecast_check() -> None:
    with open(BASE_DIR / "orders.csv", newline="", encoding="utf-8") as f:
        orders = list(csv.DictReader(f))
    for o in orders:
        o["pieces"] = int(o["pieces"])
    r = forecast_backtest(orders, BASE)
    print("### Forecast: replay on the provided orders\n")
    print(json.dumps(r, indent=2) + "\n")


if __name__ == "__main__":
    risk_check()
    expedite_check()
    forecast_check()
