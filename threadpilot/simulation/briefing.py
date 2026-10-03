"""Build the morning briefing for one business date, as JSON.

Every number in the output is computed here, never by the LLM. Every finding
carries the CSV rows it was computed from (file + line number), so the interface
can expand any claim into its evidence. The LLM, if used, only rewrites the
`headline` and finding text into prose; it receives this JSON and nothing else.

Definitions (also written into the output under "definitions"):

* Working day: Monday to Saturday. The factory is closed on Sundays.
* Yesterday: the last working day before the business date (a Monday briefing
  covers Saturday).
* Normal output for a stage on a date: mean of the previous 8 same-weekday
  working days before that date. The normal band is mean +/- max(1.5 x SD,
  5% of mean). At least 3 prior samples are required, otherwise "insufficient".
* Idle days: working days since the order's last_activity_date.
* Days per stage: median of (completed_date - order_date) / 4 over completed
  orders, in working days. Used only for a rough projected finish.

Usage
-----
    python -m simulation.briefing --data data/live                    # date from business_date.txt
    python -m simulation.briefing --data data/live --previous briefings/2026-04-06.json
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from statistics import mean, median, pstdev

from .prediction import assess_expedite, assess_risk, dm, forecast, forecast_backtest, project
from .workdays import add_working_days, is_working, prev_working, working_days_between

STAGES = ["KNITTING", "ASSEMBLY", "WASHING", "PACKING"]
BASELINE_WEEKS = 8
MIN_SAMPLES = 3
BAND_SD = 1.5
BAND_MIN_PCT = 0.05
IDLE_ALERT = 5
DUE_SOON = 7
TOP_N = 5
DEFINITIONS = {
    "working_day": "Monday to Saturday; the factory is closed on Sundays",
    "yesterday": "last working day before the business date",
    "normal": f"mean of the previous {BASELINE_WEEKS} same-weekday working days; band = mean +/- max({BAND_SD} x SD, {int(BAND_MIN_PCT*100)}% of mean); needs at least {MIN_SAMPLES} samples",
    "idle_days": "working days since last_activity_date",
    "projected_finish": "expected finish from the queue model: every stage works earliest-due-first at its usual output, new orders keep arriving (an estimate, not a commitment)",
    "risk": "overdue = past due date; high = even the best case is 5+ working days past the due date; medium = best case 1-4 working days late, or on time only if no new order goes ahead of it; low = on time even then. Confidence is how many working days the estimate sits from the due date (5+ high, 2-4 medium, under 2 low). A stalled order is raised to at least medium (high if due within 10 working days)",
    "expedite": "moves one order to the front of every queue it still has to pass; reports working days saved and the other orders pushed later, or past their due date. Recommend now if it saves 2+ days and pushes no order past its date; trade-off if it does; later if it saves under 2 days; find the blocker first if the order is stalled",
    "capacity": "usual output (average of the previous 8 same weekdays in the production log) multiplied by a workshop factor: pieces on orders finished in the last 60 days per working day, divided by the packing output the log shows for the same days. The log shows less than shipped, so the factor raises capacity to what the factory actually delivers",
    "forecast": "orders expected in the next 12 working days from the frequency of the last 60 days of orders (Poisson range); customer and product shares are their share of those orders",
    "order_status": "late = past due date; at risk = risk level high or medium; on track = low (see risk)",
    "on_time_delivery": "share of orders completed in the last 30 days with days_late <= 0",
    "ranking": "score (see score_reason) +10 if new since the previous briefing, -4 per extra morning already reported (max -20) unless it got worse; top 5 shown, rest counted",
}


# ---------------------------------------------------------------- loading
def load(folder: Path) -> tuple[list[dict], list[dict]]:
    def read(name: str) -> list[dict]:
        with (folder / name).open(newline="", encoding="utf-8") as f:
            rows = []
            for i, r in enumerate(csv.DictReader(f), start=2):  # line 1 is the header
                r["_file"], r["_row"] = name, i
                rows.append(r)
            return rows
    orders, log = read("orders.csv"), read("production_log.csv")
    for r in log:
        r["pieces_completed"] = int(r["pieces_completed"])
    for o in orders:
        o["pieces"] = int(o["pieces"])
    return orders, log


def ev(row: dict, fields: list[str]) -> dict:
    """Evidence reference: file, line number and the fields that matter."""
    return {"file": row["_file"], "row": row["_row"], "values": {k: row[k] for k in fields}}


# ---------------------------------------------------------------- calendar
# ---------------------------------------------------------------- judgement tool
def stage_normal(log_by_stage: dict[str, dict[date, dict]], stage: str, day: date) -> dict:
    """Is `stage` output on `day` normal? Same-weekday comparison, Sundays excluded."""
    rows = log_by_stage[stage]
    samples = []
    probe = day - timedelta(days=7)
    while len(samples) < BASELINE_WEEKS and probe >= min(rows, default=day):
        if probe in rows:
            samples.append(rows[probe])
        probe -= timedelta(days=7)
    observed = rows.get(day)
    result = {"stage": stage, "date": day.isoformat(), "samples": len(samples),
              "observed": observed["pieces_completed"] if observed else None,
              "evidence": ([ev(observed, ["date", "stage", "pieces_completed"])] if observed else [])
                          + [ev(r, ["date", "stage", "pieces_completed"]) for r in samples]}
    if len(samples) < MIN_SAMPLES or not is_working(day):
        return {**result, "status": "insufficient", "mean": None, "low": None, "high": None, "pct_vs_mean": None}
    values = [r["pieces_completed"] for r in samples]
    m = mean(values)
    half = max(BAND_SD * pstdev(values), BAND_MIN_PCT * m)
    res = {**result, "mean": round(m, 1), "low": round(m - half, 1), "high": round(m + half, 1)}
    if observed is None:
        return {**res, "status": "no_data", "pct_vs_mean": None}
    obs = observed["pieces_completed"]
    res["pct_vs_mean"] = round(100 * (obs - m) / m, 1) if m else None
    res["status"] = "below" if obs < res["low"] else "above" if obs > res["high"] else "normal"
    return res


# ---------------------------------------------------------------- main builder
def build(folder: Path, business_date: date | None = None, previous: dict | None = None) -> dict:
    if business_date is None:
        business_date = date.fromisoformat((folder / "business_date.txt").read_text().strip())
    orders, log = load(folder)
    log = [r for r in log if date.fromisoformat(r["date"]) < business_date]  # nothing from the future
    log_by_stage: dict[str, dict[date, dict]] = defaultdict(dict)
    for r in log:
        log_by_stage[r["stage"]][date.fromisoformat(r["date"])] = r
    for day, first in sorted(log_by_stage[STAGES[0]].items()):  # factory total = sum of the four stage rows
        rows = [log_by_stage[st].get(day) for st in STAGES]
        log_by_stage["TOTAL"][day] = {"date": day.isoformat(), "stage": "TOTAL", "_file": "production_log.csv",
                                      "_row": first["_row"],
                                      "pieces_completed": sum(r["pieces_completed"] for r in rows if r)}
    yday = prev_working(business_date)

    normals = {s: stage_normal(log_by_stage, s, yday) for s in STAGES}

    # -- derived order facts (all arithmetic here, none in the LLM)
    completed = [o for o in orders if o["status"] == "COMPLETE" and o["completed_date"]]
    per_stage = median(
        working_days_between(date.fromisoformat(o["order_date"]), date.fromisoformat(o["completed_date"])) / 4
        for o in completed)
    active = [o for o in orders if o["status"] == "IN_PROGRESS"]
    for o in active:
        due, last = date.fromisoformat(o["due_date"]), date.fromisoformat(o["last_activity_date"])
        o["days_to_due"] = (due - business_date).days
        o["idle_days"] = max(0, working_days_between(last, business_date) - 1)  # activity yesterday = 0 idle

    # An idle order is only suspicious if the queue does not explain it: an order at
    # the same stage with a LATER due date moved in the last two working days.
    # Otherwise it is simply waiting its turn (earliest-due-first), which is not news.
    recent = prev_working(yday).isoformat()  # "moved recently" = activity in the last two working days
    for o in active:
        o["moved_past_by"] = sorted(p["order_id"] for p in active
                                    if p is not o and p["current_stage"] == o["current_stage"]
                                    and p["due_date"] > o["due_date"] and p["last_activity_date"] >= recent)
        o["unexplained_idle"] = o["idle_days"] >= 3 and bool(o["moved_past_by"])

    findings: list[dict] = []

    # -- discovery 1: a stage whose output left its normal band yesterday
    for i, s in enumerate(STAGES):
        n = normals[s]
        if n["status"] != "below":
            continue
        starved = ""
        if i > 0:
            up = STAGES[i - 1]
            recent = [stage_normal(log_by_stage, up, d)["status"] for d in (yday, prev_working(yday))]
            if "below" in recent:
                starved = f" {up.title()} was also below normal in the last two working days, so this line may be short of work rather than slow."
        findings.append({
            "key": f"stage_below:{s}", "type": "stage_below_normal", "stage": s,
            "title": f"{s.title()} output was {abs(n['pct_vs_mean'])}% below normal yesterday",
            "detail": f"{n['observed']} pieces on {yday:%a %d %b} against a normal of {n['mean']:.0f} "
                      f"(band {n['low']:.0f}-{n['high']:.0f}, {n['samples']} same-weekday samples).{starved}",
            "score": 40 + min(40, round(abs(n["pct_vs_mean"]))),
            "score_reason": "40 + percentage below the same-weekday mean (max 40)",
            "order_ids": [], "evidence": n["evidence"]})

    # -- discovery 2: a customer whose active orders have all stopped moving
    by_customer: dict[str, list[dict]] = defaultdict(list)
    for o in active:
        by_customer[o["customer"]].append(o)
    for cust, os_ in by_customer.items():
        if len(os_) >= 2 and all(o["idle_days"] >= 3 for o in os_) and sum(o["unexplained_idle"] for o in os_) >= max(2, len(os_) - 1):
            findings.append({
                "key": f"customer_stalled:{cust}", "type": "customer_stalled", "customer": cust,
                "title": f"All {len(os_)} active {cust} orders have stopped moving",
                "detail": "Each has been idle at least 3 working days (" +
                          ", ".join(f"{o['order_id']} {o['idle_days']}d" for o in os_) +
                          "). Later-due orders at the same stages are still moving, so the queue does not explain it; "
                          "a shared cause (trims, approvals, payment) is more likely.",
                "score": 70 + 2 * len(os_), "score_reason": "70 + 2 per stalled order",
                "order_ids": [o["order_id"] for o in os_],
                "evidence": [ev(o, ["order_id", "current_stage", "last_activity_date", "due_date"]) for o in os_]})
    stalled_customers = {f["customer"] for f in findings if f["type"] == "customer_stalled"}

    # -- discovery 3: orders that went quiet while later-due orders moved past them
    quiet = []
    for o in active:
        if (o["customer"] in stalled_customers or o["idle_days"] < IDLE_ALERT or o["days_to_due"] > 21
                or not o["unexplained_idle"]):
            continue
        quiet.append(o)
    quiet.sort(key=lambda o: -o["idle_days"])
    if len(quiet) <= 2:
        for o in quiet:
            findings.append({
                "key": f"quiet:{o['order_id']}", "type": "quiet_order", "order_id": o["order_id"],
                "title": f"{o['order_id']} ({o['customer']}) has not moved for {o['idle_days']} working days",
                "detail": f"Still at {o['current_stage'].title()}, due {o['due_date']} ({o['days_to_due']} days). "
                          f"Later-due {', '.join(o['moved_past_by'][:3])} moved past it at the same stage.",
                "score": 45 + min(30, 3 * o["idle_days"]), "score_reason": "45 + 3 per idle working day (max 30)",
                "order_ids": [o["order_id"]],
                "evidence": [ev(o, ["order_id", "current_stage", "last_activity_date", "due_date"])]})
    else:
        findings.append({
            "key": "quiet", "type": "quiet_orders", "title": f"{len(quiet)} orders have gone quiet while later-due orders moved past them",
            "detail": "Longest idle: " + ", ".join(f"{o['order_id']} {o['customer']} ({o['idle_days']}d)" for o in quiet[:3]) + ".",
            "score": min(85, 55 + 5 * len(quiet)), "score_reason": "55 + 5 per quiet order (max 85)",
            "order_ids": [o["order_id"] for o in quiet],
            "evidence": [ev(o, ["order_id", "current_stage", "last_activity_date", "due_date"]) for o in quiet]})

    # -- risk: will each order make its due date? (queue model in prediction.py, validated in docs/prediction_validation.md)
    win = 45
    recent_orders = [o for o in orders if business_date - timedelta(days=win) <= date.fromisoformat(o["order_date"]) < business_date]
    wdays = sum(is_working(business_date - timedelta(days=i)) for i in range(1, win + 1))
    arrivals = {"window_days": win, "orders": len(recent_orders),
                "pieces_per_working_day": round(sum(o["pieces"] for o in recent_orders) / wdays, 1),
                "leads": sorted((date.fromisoformat(o["due_date"]) - date.fromisoformat(o["order_date"])).days for o in recent_orders)}
    usual_log = {st: normals[st]["mean"] for st in STAGES}
    can_project = all(usual_log.values())
    # The log does not reconcile with what ships: capacity is calibrated from completions. factor = pieces on orders
    # finished in the last 60 days per working day, divided by the packing output the log shows for the same days.
    cwin = business_date - timedelta(days=60)
    done60 = [o for o in completed if cwin <= date.fromisoformat(o["completed_date"]) < business_date]
    pack60 = [r["pieces_completed"] for day_, r in log_by_stage["PACKING"].items() if cwin <= day_ < business_date and is_working(day_)]
    cwdays = sum(is_working(cwin + timedelta(days=i)) for i in range(60))
    finished_pd = sum(o["pieces"] for o in done60) / cwdays
    factor = round(min(3.0, max(1.0, finished_pd / mean(pack60))), 3) if len(done60) >= 10 and pack60 else 1.0
    cap = {st: (usual_log[st] * factor if usual_log[st] else None) for st in STAGES}
    capacity = {"workshop_factor": factor, "window_days": 60, "orders_finished": len(done60),
                "finished_pieces_per_day": round(finished_pd), "logged_packing_per_day": round(mean(pack60)) if pack60 else None,
                "note": "Pieces on orders that finished in the last 60 days, per working day, versus packing output in the production log. "
                        "The log shows less than shipped (the rest may be outside workshops), so usual output is scaled by this factor."}
    stalled_ids = {o["order_id"] for o in active
                   if o["customer"] in stalled_customers or (o["unexplained_idle"] and o["idle_days"] >= IDLE_ALERT)}
    best_map = project(active, cap, business_date) if can_project else {}
    exp_map = project(active, cap, business_date, arrivals=arrivals) if can_project else {}
    for o in active:
        if can_project:
            o["risk"] = assess_risk(o, best_map.get(o["order_id"]), exp_map.get(o["order_id"]), business_date, o["order_id"] in stalled_ids)
            o["projected_finish"] = o["risk"]["expected_date"] or o["risk"]["best_date"]
        else:  # too little history for a queue estimate: say so, and fall back to the rough per-stage median
            remaining = len(STAGES) - STAGES.index(o["current_stage"])
            o["projected_finish"] = add_working_days(business_date, round(remaining * per_stage)).isoformat()
            o["risk"] = {"level": "overdue" if o["days_to_due"] < 0 else "unknown", "confidence": "none",
                         "reason": "Not enough production history to estimate", "best_date": None, "expected_date": None,
                         "working_days_left": 0, "margin": 0, "stalled": o["order_id"] in stalled_ids}
        o["projected_late"] = o["risk"]["level"] in ("overdue", "high", "medium")
        parts = []
        if o["days_to_due"] < 0:
            parts.append(("overdue", min(60, 40 + 2 * -o["days_to_due"])))
        elif o["days_to_due"] <= DUE_SOON:
            parts.append(("due within 7 days", 30))
        if o["risk"]["level"] == "high":
            parts.append(("high risk of missing the due date", 20))
        elif o["risk"]["level"] == "medium":
            parts.append(("medium risk of missing the due date", 10))
        if o["idle_days"] >= IDLE_ALERT:
            parts.append((f"idle {o['idle_days']} working days", 15))
        o["priority"] = sum(p for _, p in parts)
        o["priority_parts"] = [{"reason": r, "points": p} for r, p in parts]

    # -- discovery 4: overdue, rolled into one finding so it cannot flood the page
    overdue = sorted([o for o in active if o["days_to_due"] < 0], key=lambda o: o["days_to_due"])
    if overdue:
        findings.append({
            "key": "overdue", "type": "overdue", "title": f"{len(overdue)} active orders are past their due date",
            "detail": "Most overdue: " + ", ".join(f"{o['order_id']} ({-o['days_to_due']}d, {o['current_stage'].title()})"
                                                  for o in overdue[:3]) + ".",
            "score": min(90, 50 + 4 * len(overdue)), "score_reason": "50 + 4 per overdue order (max 90)",
            "order_ids": [o["order_id"] for o in overdue],
            "evidence": [ev(o, ["order_id", "due_date", "current_stage"]) for o in overdue]})

    # -- discovery 5: due this week and the risk model says it may miss
    at_risk = [o for o in active if 0 <= o["days_to_due"] <= DUE_SOON and o["projected_late"]]
    if at_risk:
        findings.append({
            "key": "due_soon_at_risk", "type": "due_soon_at_risk",
            "title": f"{len(at_risk)} orders due within 7 days are at risk of missing their date",
            "detail": "; ".join(f"{o['order_id']} due {dm(date.fromisoformat(o['due_date']))}, {o['risk']['level']} risk" for o in at_risk[:4]) + ".",
            "score": 55 + 3 * len(at_risk), "score_reason": "55 + 3 per order",
            "order_ids": [o["order_id"] for o in at_risk],
            "evidence": [ev(o, ["order_id", "due_date", "current_stage"]) for o in at_risk]})

    # -- discovery 6: work piling up in front of one stage
    for s in STAGES:
        queue = [o for o in active if o["current_stage"] == s]
        pieces = sum(o["pieces"] for o in queue)
        normal_day = cap[s] if can_project else (normals[s]["mean"] or 1)
        if pieces > 6 * normal_day:
            findings.append({
                "key": f"wip:{s}", "type": "wip_pileup", "stage": s,
                "title": f"{len(queue)} orders ({pieces:,} pieces) are waiting at {s.title()}",
                "detail": f"About {pieces / normal_day:.1f} days of work at {s.title()}'s estimated {normal_day:,.0f} pieces a day.",
                "score": 35 + min(25, int(pieces / normal_day)), "score_reason": "35 + days of queued work (max 25)",
                "order_ids": [o["order_id"] for o in queue],
                "evidence": [ev(o, ["order_id", "current_stage", "pieces"]) for o in queue]})

    # -- discovery 7: new orders that need a capacity decision today
    new = [o for o in active if o["order_date"] == yday.isoformat()]
    for o in new:
        lead = (date.fromisoformat(o["due_date"]) - date.fromisoformat(o["order_date"])).days
        if o["pieces"] >= 1000 or lead <= 14:
            findings.append({
                "key": f"new:{o['order_id']}", "type": "new_order_decision", "order_id": o["order_id"],
                "title": f"New order {o['order_id']}: {o['pieces']:,} {o['product'].lower()}s for {o['customer']} in {lead} days",
                "detail": "Large or short-lead order. Run a feasibility check before confirming the date.",
                "score": 50, "score_reason": "fixed 50 for large (>=1,000) or short-lead (<=14 days) orders",
                "order_ids": [o["order_id"]],
                "evidence": [ev(o, ["order_id", "pieces", "order_date", "due_date"])]})

    # -- what changed since the previous briefing. Proactive is a dial: new findings
    # get a boost, findings already reported on earlier mornings fade slowly, so the
    # same item does not lead the page every day unless it keeps getting worse.
    prev_keys = {f["key"]: f for f in (previous or {}).get("all_findings", [])}
    for f in findings:
        before = prev_keys.get(f["key"])
        f["is_new"] = previous is not None and before is None
        f["open_days"] = before.get("open_days", 1) + 1 if before else 1
        worse = bool(before) and f["score"] >= before["score"] + 8  # small drifts do not count
        f["rank_score"] = f["score"] + (10 if f["is_new"] else 0) - (0 if worse else min(20, 4 * (f["open_days"] - 1)))
        f["rank_reason"] = ("new since yesterday (+10)" if f["is_new"] else
                            "getting worse (no fade)" if worse else
                            f"open {f['open_days']} mornings (-{min(20, 4 * (f['open_days'] - 1))})" if before else "first briefing")
    findings.sort(key=lambda f: (-f["rank_score"], f["key"]))
    resolved = [{"key": k, "title": v["title"]} for k, v in prev_keys.items()
                if k not in {f["key"] for f in findings}]

    kpis = {
        "active": len(active),
        "overdue": len(overdue),
        "due_7d": sum(0 <= o["days_to_due"] <= DUE_SOON for o in active),
        "idle_5d": sum(o["idle_days"] >= IDLE_ALERT for o in active),
        "completed_yday": sum(o["completed_date"] == yday.isoformat() for o in orders),
        "new_yday": len(new),
        "output_yday": sum(normals[s]["observed"] or 0 for s in STAGES),
    }
    prev_k = (previous or {}).get("kpis", {})
    kpi_delta = {k: (v - prev_k[k]) if k in prev_k else None for k, v in kpis.items()}

    # -- order status in plain words, derived from the risk level so there is one definition of "at risk"
    for o in active:
        lvl = o["risk"]["level"]
        reasons = []
        if lvl == "overdue":
            status = "late"; reasons.append(o["risk"]["reason"])
        elif lvl in ("high", "medium"):
            status = "at_risk"; reasons.append(o["risk"]["reason"])
        else:
            status = "on_track"
        if o["unexplained_idle"] and o["idle_days"] >= IDLE_ALERT:
            reasons.append(f"idle {o['idle_days']} working days while later-due orders moved")
        o["status_label"], o["status_reasons"] = status, reasons
    status_counts = {k: sum(o["status_label"] == k for o in active) for k in ("on_track", "at_risk", "late")}
    risk_counts = {k: sum(o["risk"]["level"] == k for o in active) for k in ("overdue", "high", "medium", "low", "unknown")}

    # -- expedite assessment for every order that is late or at risk
    for o in active:
        o["expedite"] = (assess_expedite(o, active, cap, business_date, o["order_id"] in stalled_ids, o["idle_days"], best_map, exp_map)
                         if can_project and o["status_label"] in ("late", "at_risk") else None)

    # -- on-time delivery over the last 30 days, and the 30 days before that
    def otd(start: date, end: date, rows: bool = False) -> dict:
        done = [o for o in completed if start <= date.fromisoformat(o["completed_date"]) < end]
        on_time = sum(int(o["days_late"] or 0) <= 0 for o in done)
        out = {"completed": len(done), "on_time": on_time,
               "pct": round(100 * on_time / len(done)) if done else None}
        if rows:  # the orders behind the percentage, so the number can be traced
            out["orders"] = [{"order_id": o["order_id"], "customer": o["customer"],
                              "completed_date": o["completed_date"], "days_late": int(o["days_late"] or 0),
                              "row": o["_row"]} for o in sorted(done, key=lambda o: o["completed_date"])]
        return out
    otd_now = otd(business_date - timedelta(days=30), business_date, rows=True)
    otd_prev = otd(business_date - timedelta(days=60), business_date - timedelta(days=30))

    # -- per customer
    customers = []
    for cust in sorted({o["customer"] for o in orders}):
        mine = [o for o in active if o["customer"] == cust]
        done = [o for o in completed if o["customer"] == cust
                and date.fromisoformat(o["completed_date"]) >= business_date - timedelta(days=60)]
        customers.append({
            "customer": cust, "active": len(mine),
            "late": sum(o["status_label"] == "late" for o in mine),
            "at_risk": sum(o["status_label"] == "at_risk" for o in mine),
            "on_track": sum(o["status_label"] == "on_track" for o in mine),
            "pieces": sum(o["pieces"] for o in mine),
            "next_due": min((o["due_date"] for o in mine if o["days_to_due"] >= 0), default=None),
            "otd_60d": round(100 * sum(int(o["days_late"] or 0) <= 0 for o in done) / len(done)) if done else None,
            "stalled": cust in stalled_customers,
        })
    customers.sort(key=lambda c: (-c["late"] * 3 - c["at_risk"] * 2 - c["stalled"] * 5, -c["pieces"]))

    # -- where the work is sitting
    pipeline = []
    for st in STAGES:
        queue = [o for o in active if o["current_stage"] == st]
        usual = normals[st]["mean"]
        pieces = sum(o["pieces"] for o in queue)
        pipeline.append({"stage": st, "orders": len(queue), "pieces": pieces,
                         "late": sum(o["status_label"] == "late" for o in queue),
                         "usual_per_day": round(usual) if usual else None,
                         "capacity_per_day": round(cap[st]) if cap[st] else None,
                         "days_of_work": round(pieces / cap[st], 1) if cap[st] else None,
                         "yesterday": normals[st]["observed"], "status": normals[st]["status"]})

    # -- deliveries coming up
    buckets = [("late", "Already late", None, -1), ("week", "Due in 0-7 days", 0, 7),
               ("next", "Due in 8-14 days", 8, 14), ("later", "Due later", 15, 10**6)]
    outlook = []
    for key, label, lo, hi in buckets:
        grp = [o for o in active if (o["days_to_due"] < 0 if lo is None else lo <= o["days_to_due"] <= hi)]
        outlook.append({"key": key, "label": label, "orders": len(grp), "pieces": sum(o["pieces"] for o in grp),
                        "at_risk": sum(o["status_label"] == "at_risk" for o in grp),
                        "late": sum(o["status_label"] == "late" for o in grp)})

    # -- a severity word and a suggested next step for each finding
    NEXT_STEP = {
        "overdue": ("Ask the planner for revised ship dates", "chase"),
        "customer_stalled": ("Call the customer's account manager", "chase"),
        "stage_below_normal": ("Check with the stage supervisor", "note"),
        "quiet_order": ("Chase the order", "chase"), "quiet_orders": ("Chase the quiet orders", "chase"),
        "due_soon_at_risk": ("Warn the customers or add capacity", "chase"),
        "wip_pileup": ("Consider overtime or moving work to a workshop", "note"),
        "new_order_decision": ("Run a feasibility check before confirming", "feasibility"),
    }
    for f in findings:
        f["severity"] = "critical" if f["rank_score"] >= 80 else "high" if f["rank_score"] >= 65 else "watch"
        f["next_step"], f["action"] = NEXT_STEP.get(f["type"], ("Review", "note"))

    # -- series for the stage charts: last 18 working days + 6 working days of "expected if normal"
    series = {}
    for s in [*STAGES, "TOTAL"]:
        days, probe = [], yday
        while len(days) < 18:
            if is_working(probe):
                days.append(probe)
            probe -= timedelta(days=1)
        hist = []
        for day in reversed(days):
            n = stage_normal(log_by_stage, s, day)
            hist.append({"date": day.isoformat(), "value": n["observed"], "low": n["low"], "high": n["high"],
                         "mean": n["mean"], "row": n["evidence"][0]["row"] if n["observed"] is not None else None})
        fut, probe = [], business_date
        while len(fut) < 6:
            if is_working(probe):
                n = stage_normal(log_by_stage, s, probe)
                fut.append({"date": probe.isoformat(), "mean": n["mean"], "low": n["low"], "high": n["high"]})
            probe += timedelta(days=1)
        yn = normals[s] if s in normals else stage_normal(log_by_stage, s, yday)
        series[s] = {"history": hist, "expected": fut, "yesterday": {**{k: yn[k] for k in
                     ("observed", "mean", "low", "high", "pct_vs_mean", "status", "samples")},
                                    "evidence": yn["evidence"]}}

    relevant = sorted([o for o in active if o["priority"] > 0], key=lambda o: (-o["priority"], o["due_date"]))[:8]
    relevant_orders = [{k: o[k] for k in ("order_id", "customer", "product", "pieces", "current_stage", "due_date",
                                          "days_to_due", "idle_days", "projected_finish", "projected_late",
                                          "priority", "priority_parts", "_row")} for o in relevant]

    orders_all = sorted(({"order_id": o["order_id"], "customer": o["customer"], "product": o["product"],
                          "pieces": o["pieces"], "stage": o["current_stage"], "due_date": o["due_date"],
                          "days_to_due": o["days_to_due"], "idle_days": o["idle_days"],
                          "projected_finish": o["projected_finish"], "status": o["status_label"],
                          "last_activity": o["last_activity_date"], "order_date": o["order_date"],
                          "reasons": o["status_reasons"], "priority": o["priority"], "row": o["_row"],
                          "risk": o["risk"], "expedite": o["expedite"]}
                         for o in active), key=lambda o: (-o["priority"], o["due_date"]))

    top = findings[:TOP_N]
    newest = [f for f in findings if f["is_new"]]
    below = [s.title() for s in STAGES if normals[s]["status"] == "below"]
    headline = [
        (f"{'Yesterday' if yday == business_date - timedelta(days=1) else 'Last working day'} ({yday:%a %d %b}): "
         f"{kpis['output_yday']:,} pieces across four stages; "
         + (f"{', '.join(below)} below normal." if below else "every stage within its normal band.")),
        (f"New today: {newest[0]['title']}." if newest else
         f"Still open: {top[0]['title']}." if top else "No findings above the alert threshold."),
        (f"Decide today: {len(overdue)} overdue, {kpis['due_7d']} due this week"
         + (f", {kpis['new_yday']} new order{'s' if kpis['new_yday'] != 1 else ''} to confirm." if kpis['new_yday'] else ".")),
    ]

    return {
        "business_date": business_date.isoformat(),
        "covers": yday.isoformat(),
        "headline": headline,
        "kpis": kpis, "kpi_delta": kpi_delta,
        "findings": top, "more_findings": len(findings) - len(top), "all_findings": findings,
        "resolved_since_previous": resolved,
        "stages": series,
        "relevant_orders": relevant_orders,
        "status_counts": status_counts, "risk_counts": risk_counts, "arrivals": arrivals, "capacity": capacity,
        "forecast": {**forecast(orders, business_date), **({"backtest": forecast_backtest(orders, business_date)} if len(orders) >= 20 else {})},
        "on_time_30d": otd_now, "on_time_prev_30d": otd_prev,
        "customers": customers, "pipeline": pipeline, "outlook": outlook, "orders": orders_all,
        "assumptions": {"working_days_per_stage": per_stage},
        "definitions": DEFINITIONS,
    }


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--data", type=Path, required=True)
    p.add_argument("--date", type=date.fromisoformat)
    p.add_argument("--previous", type=Path)
    p.add_argument("--out", type=Path)
    a = p.parse_args()
    prev = json.loads(a.previous.read_text(encoding="utf-8")) if a.previous else None
    b = build(a.data, a.date, prev)
    text = json.dumps(b, indent=2, default=str)
    if a.out:
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_text(text, encoding="utf-8", newline="\n")
        print(f"Wrote {a.out}")
    else:
        print("\n".join(b["headline"]))


if __name__ == "__main__":
    main()
