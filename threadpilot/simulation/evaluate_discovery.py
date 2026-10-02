"""Score the discovery findings against the planted scenario events.

    python -m simulation.render_demo --days 14      # writes briefings/*.json first
    python -m simulation.evaluate_discovery

For each planted event: was it found, and how many mornings after it started?
For the two finding types that claim a cause (stage below normal, customer
stalled): how many mornings raised one that no planted event explains? Those are
reported as unexplained, not automatically as wrong; the simulator's own queue can
create real slowdowns that nobody planted.
"""
from __future__ import annotations

import argparse
import json
from datetime import date, timedelta
from pathlib import Path

from .simulate import DEFAULT_SCENARIO

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--briefings", type=Path, default=ROOT / "briefings")
    p.add_argument("--scenario", type=Path, default=DEFAULT_SCENARIO)
    a = p.parse_args()
    briefs = {b["business_date"]: b for b in
              (json.loads(f.read_text(encoding="utf-8")) for f in sorted(a.briefings.glob("*.json")))}
    events = json.loads(a.scenario.read_text(encoding="utf-8"))["events"]
    last = max(briefs)

    def found(pred, start: str, end: str) -> str | None:
        day = date.fromisoformat(start) + timedelta(days=1)
        stop = min(date.fromisoformat(end) + timedelta(days=3), date.fromisoformat(last))
        while day <= stop:
            b = briefs.get(day.isoformat())
            if b and any(pred(f) for f in b["all_findings"]):
                return day.isoformat()
            day += timedelta(days=1)
        return None

    rows, explained = [], set()
    for ev in events:
        start, end = ev.get("start", ev.get("date")), ev.get("end", ev.get("date"))
        if start > last:
            continue
        if ev["type"] == "stage_slowdown":
            key = f"stage_below:{ev['stage']}"
            pred = lambda f, k=key: f["key"] == k
        elif ev["type"] == "customer_hold":
            key = f"customer_stalled:{ev['customer']}"
            pred = lambda f, k=key: f["key"] == k
        elif ev["type"] == "order_hold":
            pred = lambda f, o=ev["order_id"]: o in f.get("order_ids", []) and f["type"] in ("quiet_order", "quiet_orders", "customer_stalled")
        else:  # rush_order
            pred = lambda f, c=ev["customer"], n=ev["pieces"]: f["type"] == "new_order_decision" and c in f["title"] and f"{n:,}" in f["title"]
        hit = found(pred, start, end)
        lag = (date.fromisoformat(hit) - date.fromisoformat(start)).days if hit else None
        rows.append((ev["id"], ev["type"], start, hit, lag))
        if ev["type"] in ("stage_slowdown", "customer_hold"):
            d = date.fromisoformat(start)
            while d <= date.fromisoformat(end) + timedelta(days=3):
                explained.add((d.isoformat(), key))
                d += timedelta(days=1)

    print(f"{'event':6} {'type':15} {'start':11} {'first found':12} lag (days)")
    for r in rows:
        print(f"{r[0]:6} {r[1]:15} {r[2]:11} {r[3] or 'missed':12} {'' if r[4] is None else r[4]}")
    recall = sum(r[3] is not None for r in rows) / len(rows)
    unexplained = sorted({(d, f["key"]) for d, b in briefs.items() for f in b["all_findings"]
                          if f["type"] in ("stage_below_normal", "customer_stalled") and (d, f["key"]) not in explained})
    print(f"\nRecall on planted events: {recall:.0%} ({sum(r[3] is not None for r in rows)}/{len(rows)})")
    print(f"Cause-claiming findings with no planted event behind them: {len(unexplained)}")
    for d, k in unexplained:
        print(f"  {d}  {k}")


if __name__ == "__main__":
    main()
