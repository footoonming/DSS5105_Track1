"""Deterministic day-by-day simulator for the SweaterCo dataset.

The provided dataset is a single snapshot taken on 2026-04-01. A briefing built on
a frozen snapshot says the same thing every morning. This module rolls the factory
forward one working day at a time so that every morning has new production rows,
orders that move (or stall), orders that finish, and new orders that arrive.

Design choices
--------------
* Reproducible: every day uses its own seeded RNG (seed + date), so simulating to
  2026-04-10 always produces byte-identical files, on any machine.
* Same schema: the output CSVs keep exactly the original columns, so the existing
  importer / database / tools work on simulated data without changes.
* Grounded in history: daily stage capacity is the same-weekday mean of the
  original production_log, with small noise. Sundays stay closed (zero rows).
* Scenario events (slowdowns, holds, rush orders) come from a JSON file. The
  briefing never reads that file, so the events double as ground truth for
  measuring whether discovery finds them.

Usage
-----
    python -m simulation.simulate --until 2026-04-10          # data as of that morning
    python -m simulation.simulate --days 5                     # 5 days after the base date
    python -m simulation.simulate --days 5 --out data/live     # choose output folder

The output folder contains orders.csv, production_log.csv, workshops.csv and
business_date.txt (the morning the files describe).
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import random
import shutil
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parents[1]
BASE_DIR = ROOT / "data"
DEFAULT_OUT = ROOT / "data" / "live"
DEFAULT_SCENARIO = Path(__file__).resolve().parent / "scenarios" / "default.json"

STAGES = ["KNITTING", "ASSEMBLY", "WASHING", "PACKING"]
ORDER_COLUMNS = [
    "order_id", "customer", "product", "category", "pieces", "order_date", "due_date",
    "status", "current_stage", "last_activity_date", "completed_date", "days_late",
]
ARRIVALS_PER_WORKING_DAY = 1.0     # historical rate is ~1.3; slightly lower keeps WIP roughly stable
PER_ORDER_SHARE = 0.6              # one order can take at most 60% of a stage's day
CAPACITY_NOISE_SD = 0.07           # day-to-day variation around the weekday mean
MIN_ACTIVITY_PIECES = 20           # less than this does not count as "the order moved"


# ---------------------------------------------------------------- I/O helpers
def read_csv(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as f:
        return [dict(r) for r in csv.DictReader(f)]


def write_csv(path: Path, rows: list[dict], columns: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        for r in rows:
            writer.writerow({c: r.get(c, "") for c in columns})


def d(s: str) -> date:
    return date.fromisoformat(s)


def rng_for(seed: int, day: date, salt: str = "") -> random.Random:
    return random.Random(f"{seed}|{day.isoformat()}|{salt}")


def poisson(rng: random.Random, lam: float) -> int:
    limit, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= limit:
            return k
        k += 1


# ---------------------------------------------------------------- the model
class Factory:
    def __init__(self, base_dir: Path, scenario: dict):
        self.orders = read_csv(base_dir / "orders.csv")
        self.log = read_csv(base_dir / "production_log.csv")
        self.workshops_path = base_dir / "workshops.csv"
        self.scenario = scenario
        self.seed = int(scenario.get("seed", 0))
        self.base_date = max(d(r["date"]) for r in self.log) + timedelta(days=1)
        self.weekday_capacity = self._weekday_capacity()
        self.history_orders = list(self.orders)  # sampling pool for new orders
        # Unknown in the source data: how far each active order is through its
        # current stage. Seed it deterministically per order.
        self.stage_done: dict[str, int] = {}
        for o in self.orders:
            if o["status"] == "IN_PROGRESS":
                r = random.Random(f"{self.seed}|init|{o['order_id']}")
                lo, hi = (0.3, 0.9) if o["current_stage"] == "PACKING" else (0.0, 0.6)
                self.stage_done[o["order_id"]] = int(int(o["pieces"]) * r.uniform(lo, hi))
        self.next_id = max(int(o["order_id"].split("-")[1]) for o in self.orders) + 1
        self.factor = self._workshop_factor()

    def _weekday_capacity(self) -> dict[tuple[str, int], float]:
        buckets: dict[tuple[str, int], list[int]] = defaultdict(list)
        for r in self.log:
            day = d(r["date"])
            if day.weekday() != 6:
                buckets[(r["stage"], day.weekday())].append(int(r["pieces_completed"]))
        return {k: mean(v) for k, v in buckets.items()}

    def _workshop_factor(self) -> float:
        """The source data does not reconcile: orders that finished in the last 60 days total far more pieces than the
        production log shows packing handled. The simulator reproduces that: real capacity = logged capacity x factor
        (the rest being work the log does not show, e.g. outside workshops) and only the logged share is written to the
        log. Same definition the briefing uses to estimate the factor from completions."""
        start = self.base_date - timedelta(days=60)
        done = [o for o in self.orders if o["status"] == "COMPLETE" and o["completed_date"] and start <= d(o["completed_date"]) < self.base_date]
        packing = [int(r["pieces_completed"]) for r in self.log
                   if r["stage"] == "PACKING" and start <= d(r["date"]) < self.base_date and d(r["date"]).weekday() != 6]
        if len(done) < 10 or not packing:
            return 1.0
        wdays = sum((start + timedelta(days=i)).weekday() != 6 for i in range(60))
        return round(min(3.0, max(1.0, sum(int(o["pieces"]) for o in done) / wdays / mean(packing))), 3)

    # -- scenario helpers
    def _active_events(self, day: date, kind: str) -> list[dict]:
        out = []
        for ev in self.scenario.get("events", []):
            if ev["type"] != kind:
                continue
            if ("date" in ev and d(ev["date"]) == day) or ("start" in ev and d(ev["start"]) <= day <= d(ev["end"])):
                out.append(ev)
        return out

    def _on_hold(self, order: dict, day: date) -> bool:
        return (any(ev["customer"] == order["customer"] for ev in self._active_events(day, "customer_hold"))
                or any(ev["order_id"] == order["order_id"] for ev in self._active_events(day, "order_hold")))

    # -- one simulated day
    def step(self, day: date) -> None:
        if day.weekday() == 6:  # Sunday: factory closed, zero rows like the source data
            for stage in STAGES:
                self.log.append({"date": day.isoformat(), "stage": stage, "pieces_completed": 0})
            return
        self._arrivals(day)
        moved_today: set[str] = set()
        expedited = {ev["order_id"] for ev in self.scenario.get("events", []) if ev["type"] == "expedite" and d(ev["date"]) <= day}
        # Downstream first, so an order can advance at most one stage per day.
        for stage in reversed(STAGES):
            rng = rng_for(self.seed, day, stage)
            capacity = self.weekday_capacity[(stage, day.weekday())]
            capacity *= max(0.5, rng.gauss(1.0, CAPACITY_NOISE_SD))
            for ev in self._active_events(day, "stage_slowdown"):
                if ev["stage"] == stage:
                    capacity *= float(ev["factor"])
            capacity = int(round(capacity * self.factor))
            queue = [o for o in self.orders
                     if o["status"] == "IN_PROGRESS" and o["current_stage"] == stage
                     and o["order_id"] not in moved_today and not self._on_hold(o, day)]
            queue.sort(key=lambda o: ("", "") if o["order_id"] in expedited else (o["due_date"], o["order_id"]))  # earliest due first
            left, produced = capacity, 0
            for o in queue:
                if left <= 0:
                    break
                oid, pieces = o["order_id"], int(o["pieces"])
                need = pieces - self.stage_done.get(oid, 0)
                take = int(min(need, left, max(MIN_ACTIVITY_PIECES, capacity * PER_ORDER_SHARE)))
                if take <= 0:
                    continue
                self.stage_done[oid] = self.stage_done.get(oid, 0) + take
                left -= take
                produced += take
                if take >= MIN_ACTIVITY_PIECES or self.stage_done[oid] >= pieces:
                    o["last_activity_date"] = day.isoformat()
                if self.stage_done[oid] >= pieces:
                    self._advance(o, day)
                    moved_today.add(oid)
            self.log.append({"date": day.isoformat(), "stage": stage, "pieces_completed": int(round(produced / self.factor))})
        # keep the file in date + stage order like the source
        self.log.sort(key=lambda r: (r["date"], STAGES.index(r["stage"])))

    def _advance(self, o: dict, day: date) -> None:
        i = STAGES.index(o["current_stage"])
        self.stage_done[o["order_id"]] = 0
        if i == len(STAGES) - 1:
            o.update(status="COMPLETE", current_stage="COMPLETE", completed_date=day.isoformat(),
                     days_late=str((day - d(o["due_date"])).days))
        else:
            o["current_stage"] = STAGES[i + 1]

    def _arrivals(self, day: date) -> None:
        rng = rng_for(self.seed, day, "arrivals")
        new = []
        for _ in range(poisson(rng, ARRIVALS_PER_WORKING_DAY)):
            t = rng.choice(self.history_orders)
            lead = rng.randint(14, 35)
            new.append({"customer": t["customer"], "product": t["product"],
                        "category": t["category"], "pieces": t["pieces"], "lead": lead})
        for ev in self._active_events(day, "rush_order"):
            new.append({"customer": ev["customer"], "product": ev["product"],
                        "category": ev["category"], "pieces": str(ev["pieces"]),
                        "lead": int(ev["lead_days"])})
        for n in new:
            oid = f"ORD-{self.next_id:03d}"
            self.next_id += 1
            self.orders.append({
                "order_id": oid, "customer": n["customer"], "product": n["product"],
                "category": n["category"], "pieces": str(n["pieces"]),
                "order_date": day.isoformat(),
                "due_date": (day + timedelta(days=n["lead"])).isoformat(),
                "status": "IN_PROGRESS", "current_stage": "KNITTING",
                "last_activity_date": day.isoformat(), "completed_date": "", "days_late": "",
            })
            self.stage_done[oid] = 0

    # -- output
    def write(self, out: Path, business_date: date) -> None:
        out.mkdir(parents=True, exist_ok=True)
        write_csv(out / "orders.csv", self.orders, ORDER_COLUMNS)
        write_csv(out / "production_log.csv", self.log, ["date", "stage", "pieces_completed"])
        shutil.copyfile(self.workshops_path, out / "workshops.csv")
        (out / "business_date.txt").write_text(business_date.isoformat() + "\n", encoding="utf-8", newline="\n")


def simulate(until: date, base_dir: Path = BASE_DIR, out: Path | None = DEFAULT_OUT,
             scenario_path: Path = DEFAULT_SCENARIO) -> Factory:
    """Simulate every day from the base date up to (not including) `until`.

    The result describes the factory on the *morning* of `until`: production rows
    exist up to the day before, exactly like the original snapshot (rows to
    2026-03-31, business date 2026-04-01).
    """
    scenario = json.loads(scenario_path.read_text(encoding="utf-8"))
    factory = Factory(base_dir, scenario)
    if until < factory.base_date:
        raise ValueError(f"until must be on or after {factory.base_date}")
    day = factory.base_date  # source rows end the day before; base_date is the first new day
    while day < until:
        factory.step(day)
        day += timedelta(days=1)
    if out is not None:
        factory.write(out, until)
    return factory


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--until", type=date.fromisoformat, help="business date (morning) to simulate to")
    g.add_argument("--days", type=int, help="number of days after the base date 2026-04-01")
    p.add_argument("--out", type=Path, default=DEFAULT_OUT)
    p.add_argument("--base", type=Path, default=BASE_DIR, help="folder with the original CSVs")
    p.add_argument("--scenario", type=Path, default=DEFAULT_SCENARIO)
    a = p.parse_args()
    until = a.until or date(2026, 4, 1) + timedelta(days=a.days)
    f = simulate(until, a.base, a.out, a.scenario)
    active = sum(o["status"] == "IN_PROGRESS" for o in f.orders)
    print(f"Wrote {a.out} for business date {until}: {len(f.orders)} orders "
          f"({active} in progress), {len(f.log)} production rows")


if __name__ == "__main__":
    main()
