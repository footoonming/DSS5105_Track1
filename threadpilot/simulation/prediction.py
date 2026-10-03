"""Risk, expedite and forecast models for the morning briefing. Standard library only, pure functions.

Risk and expedite share one engine, `project`: a day-by-day walk through the factory. Every stage works through the orders
waiting at it earliest-due-first, at its usual daily output; Sundays are closed; an order moves on at most one stage a day,
and one order uses at most 60% of a stage's daily output. It is the same kind of logic as the demo simulator but with no
randomness, so it is a projection, not a forecast with error bars.

* risk      - will this in-progress order make its due date? Two projections: BEST (no new orders) and EXPECTED (one
              average-sized order arrives every working day, due after the usual lead time, and goes ahead of any order
              due later). Levels: overdue; high = even the best case is 5+ working days late; medium = late by 1-4 days
              at best, or on time only if nothing new goes ahead; low = on time even then. Plus a confidence label.
* expedite  - what changes if one order is moved to the front of every queue? Gain = how much less late that order is.
              Cost = the extra lateness it adds to other orders. The recommendation looks at the NET change.
* forecast  - how many orders, which customers and products to expect in the next 12 working days, from the frequency of
              the last 60 days of orders. Frequency counting, not machine learning.

Assumptions: in-progress orders start their current stage from zero (partial progress is not recorded, so estimates lean
cautious); all products are treated alike (the production log has no product breakdown); no overtime and no extra
workshop capacity beyond the calibrated factor (briefing.capacity); a stalled order is not modelled, only flagged.
"""
from __future__ import annotations

import math
from collections import Counter
from datetime import date, timedelta
from statistics import mean

from .workdays import is_working, kth_working_day, working_days_inclusive  # noqa: F401  (also re-exported for callers)

STAGES = ["KNITTING", "ASSEMBLY", "WASHING", "PACKING"]
CAP = 200                  # working days to look ahead before giving up
SERVICE_SHARE = 0.6        # one order can use at most this share of a stage's daily output per day
MIN_DAYS_SAVED = 2         # expediting must save at least this many working days to be worth recommending
CONFIDENCE_HIGH = 5        # working days between the estimate and the due date for "high" confidence
CONFIDENCE_MEDIUM = 2
HIGH_LATE_DAYS = 5          # even the best case this many working days past the due date = high risk
STALLED_NEAR_DUE_DAYS = 10 # a stalled order due within this many working days is rated high risk
FORECAST_HORIZON = 12      # working days (two weeks)
FORECAST_WINDOW = 60       # calendar days of order history used
MIN_FORECAST_ORDERS = 10
LEVEL_RANK = {"low": 0, "medium": 1, "high": 2}


# ---------------------------------------------------------------- formatting (calendar helpers live in workdays.py)
def dm(d: date) -> str:
    """'9 Apr'. Written by hand because strftime's no-padding flag is not portable (it fails on Windows)."""
    return f"{d.day} {d.strftime('%b')}"


def dow_dm(d: date) -> str:
    return f"{d.strftime('%a')} {dm(d)}"


# ---------------------------------------------------------------- the projection engine
def project(active: list[dict], cap: dict, business_date: date, expedite_id: str | None = None,
            arrivals: dict | None = None) -> dict[str, int | None]:
    """Working-day index (1 = the business date if it is a working day) at which each active order finishes, or None if
    it does not finish within CAP working days. `cap` is the daily output per stage."""
    work = [{"id": o["order_id"], "pieces": float(o["pieces"]), "stage": STAGES.index(o["current_stage"]),
             "need": float(o["pieces"]), "due": o["due_date"], "real": True} for o in active]
    finish: dict[str, int | None] = {o["order_id"]: None for o in active}
    open_real = len(active)
    lead = None
    if arrivals and arrivals["leads"]:
        leads = sorted(arrivals["leads"])
        lead = leads[len(leads) // 2]
    d, k, syn = business_date - timedelta(days=1), 0, 0
    while open_real and k < CAP:
        d += timedelta(days=1)
        if not is_working(d):
            continue
        k += 1
        if lead is not None:  # one average-sized order a day, due after the usual lead time
            syn += 1
            work.append({"id": f"~{syn}", "pieces": arrivals["pieces_per_working_day"], "stage": 0,
                         "need": arrivals["pieces_per_working_day"], "due": (d + timedelta(days=lead)).isoformat(), "real": False})
        moved: set[str] = set()
        for si in reversed(range(len(STAGES))):
            left = cap[STAGES[si]]
            per_order = SERVICE_SHARE * cap[STAGES[si]]
            queue = [w for w in work if w["stage"] == si and w["id"] not in moved]
            queue.sort(key=lambda w: ("", "") if w["id"] == expedite_id else (w["due"], w["id"]))
            for w in queue:
                if left <= 1e-9:
                    break
                take = min(w["need"], left, max(20.0, per_order))
                w["need"] -= take
                left -= take
                if w["need"] <= 1e-9:
                    if si == len(STAGES) - 1:
                        w["stage"] = len(STAGES)
                        if w["real"]:
                            finish[w["id"]] = k
                            open_real -= 1
                    else:
                        w["stage"] = si + 1
                        w["need"] = w["pieces"]
                        moved.add(w["id"])
        work = [w for w in work if w["stage"] < len(STAGES)]
    return finish


# ---------------------------------------------------------------- risk
def assess_risk(x: dict, best_k: int | None, exp_k: int | None, business_date: date, stalled: bool) -> dict:
    due = date.fromisoformat(x["due_date"])
    unfinished = best_k is None            # does not finish within CAP working days even with no new orders
    best_k = best_k or CAP
    best_date = kth_working_day(business_date, best_k)
    exp_date = kth_working_day(business_date, exp_k) if exp_k else None
    out = {"best_date": best_date.isoformat(), "expected_date": exp_date.isoformat() if exp_date else None,
           "stalled": stalled, **({"unfinished": True} if unfinished else {})}
    if due < business_date:
        late = (business_date - due).days
        return {**out, "level": "overdue", "confidence": "certain", "working_days_left": 0, "margin": 0,
                "late_days_best": best_k, "late_days_expected": exp_k,
                "reason": f"{late} day{'s' if late != 1 else ''} past the {dm(due)} due date"}
    width = working_days_inclusive(business_date, due)
    late_best = max(0, best_k - width)
    if late_best >= HIGH_LATE_DAYS:
        level, margin = "high", late_best
    elif late_best >= 1:
        level, margin = "medium", late_best
    elif exp_k is None or exp_k > width:
        level = "medium"
        margin = min(width - best_k, (exp_k - width) if exp_k is not None else 99)
    else:
        level, margin = "low", width - exp_k
    if late_best >= 1:
        reason = (f"Even in the best case it finishes {dow_dm(best_date)}, {late_best} working day{'s' if late_best != 1 else ''} "
                  f"after the {dm(due)} due date")
    elif level == "medium":
        reason = (f"Finishes {dm(best_date)} at best, {dm(exp_date)} if new orders go ahead of it; due {dm(due)}"
                  if exp_date else f"Finishes {dm(best_date)} at best and may not finish at all if new orders keep going ahead; due {dm(due)}")
    else:
        reason = f"Should finish by {dow_dm(exp_date)}, before the {dm(due)} due date"
    if unfinished:   # no date to show: say so instead of quoting the CAP-th working day as if it were an estimate
        level, margin = "high", CAP
        reason = f"Does not finish within {CAP} working days even in the best case; due {dm(due)}"
    confidence = "high" if margin >= CONFIDENCE_HIGH else "medium" if margin >= CONFIDENCE_MEDIUM else "low"
    if stalled:  # the projection assumes the order moves; a stalled one breaks that assumption
        bumped = "high" if width <= STALLED_NEAR_DUE_DAYS else "medium"
        if LEVEL_RANK[bumped] > LEVEL_RANK[level]:
            level = bumped
        confidence = "medium" if confidence == "high" else confidence
        reason = "Not moving, and the projection assumes it moves. " + reason
    return {**out, "level": level, "confidence": confidence, "working_days_left": width, "margin": margin,
            "late_days_best": late_best, "late_days_expected": (max(0, exp_k - width) if exp_k else None), "reason": reason}


# ---------------------------------------------------------------- expedite
def assess_expedite(x: dict, active: list[dict], cap: dict, business_date: date, stalled: bool, idle_days: int,
                    best_map: dict, exp_map: dict) -> dict:
    """What changes if x goes to the front of every queue it still has to pass?

    Lateness = working days beyond the due date. Gain = how much less late x becomes. Cost = the extra lateness this adds
    to other orders. When many orders are already late, moving one up mostly moves the delay onto others, so the
    recommendation looks at the NET change (gain minus cost), not at x alone.
    """
    xid = x["order_id"]
    wx = working_days_inclusive(business_date, date.fromisoformat(x["due_date"]))
    fast_map = project(active, cap, business_date, expedite_id=xid)
    base_k = exp_map.get(xid) or best_map.get(xid) or CAP     # x's own baseline includes new orders going ahead of it
    fast_k = fast_map.get(xid) or CAP
    saved = max(0, base_k - fast_k)
    gain = max(0, base_k - wx) - max(0, fast_k - wx)
    pushed, cost = [], 0
    for y in active:
        if y is x:
            continue
        before, after = best_map.get(y["order_id"]) or CAP, fast_map.get(y["order_id"]) or CAP
        if after > before:
            wy = working_days_inclusive(business_date, date.fromisoformat(y["due_date"]))
            added = max(0, after - wy) - max(0, before - wy)
            cost += added
            pushed.append({"order_id": y["order_id"], "customer": y["customer"], "extra_days": after - before,
                           "added_lateness": added, "newly_late": before <= wy < after})
    pushed.sort(key=lambda q: (not q["newly_late"], -q["added_lateness"], q["order_id"]))
    newly = [q["order_id"] for q in pushed if q["newly_late"]]
    net = gain - cost
    now_date, fast_date = kth_working_day(business_date, base_k), kth_working_day(business_date, fast_k)
    n_hit = sum(1 for q in pushed if q["added_lateness"] > 0)
    if stalled:
        rec, label = "investigate", "Find the blocker first"
        reason = (f"It has not moved for {idle_days} working days, so moving it up the queue will not help until "
                  "the blocker is found. Ask what is holding it.")
    elif gain < MIN_DAYS_SAVED:
        rec, label = "later", "Expedite later, or not needed"
        reason = ("It is not expected to be late, so there is nothing to gain." if max(0, base_k - wx) == 0 else
                  f"Expediting would cut its lateness by only {gain} working day{'s' if gain != 1 else ''}. "
                  "Keep it in the normal queue and review again tomorrow.")
    elif net < MIN_DAYS_SAVED:
        rec, label = "later", "Expedite later, or not needed"
        reason = (f"Expediting would cut its lateness by {gain} working days but add {cost} days of lateness across "
                  f"{n_hit} other order{'s' if n_hit != 1 else ''}, so overall almost nothing is gained. Keep the normal order.")
    elif newly:
        rec, label = "trade_off", "Trade-off: your call"
        reason = (f"Expediting cuts its lateness by {gain} working days ({dm(now_date)} to {dm(fast_date)}) at a cost of {cost} "
                  f"days of lateness elsewhere, and pushes {len(newly)} order{'s' if len(newly) != 1 else ''} that would "
                  f"have been on time past {'their' if len(newly) != 1 else 'its'} due date: {', '.join(newly[:4])}.")
    else:
        rec, label = "now", "Expedite now"
        reason = (f"Expediting cuts its lateness by {gain} working days ({dm(now_date)} to {dm(fast_date)}); the delay it "
                  f"adds elsewhere is {cost} working day{'s' if cost != 1 else ''} in total and pushes no on-time order late.")
    return {"recommendation": rec, "label": label, "reason": reason, "days_saved": saved, "gain": gain, "cost": cost,
            "net": net, "finish_now": now_date.isoformat(), "finish_expedited": fast_date.isoformat(),
            "newly_late": newly, "pushed": pushed[:8], "pushed_total": len(pushed)}


# ---------------------------------------------------------------- forecast
def poisson_interval(lam: float, lo_p: float = 0.1, hi_p: float = 0.9) -> tuple[int, int]:
    k, cdf, term, lo = 0, 0.0, math.exp(-lam), None
    while k < 2000:
        cdf += term
        if lo is None and cdf >= lo_p:
            lo = k
        if cdf >= hi_p:
            return lo, k
        k += 1
        term *= lam / k
    return lo or 0, k


def forecast(orders: list[dict], business_date: date, horizon: int = FORECAST_HORIZON, window: int = FORECAST_WINDOW) -> dict:
    """Expected orders in the next `horizon` working days from the frequency of the last `window` calendar days."""
    recent = [o for o in orders if business_date - timedelta(days=window) <= date.fromisoformat(o["order_date"]) < business_date]
    if len(recent) < MIN_FORECAST_ORDERS:
        return {"enough_data": False, "orders_in_window": len(recent)}
    wdays = sum(is_working(business_date - timedelta(days=i)) for i in range(1, window + 1))
    lam = len(recent) / wdays * horizon
    lo, hi = poisson_interval(lam)
    avg = mean(o["pieces"] for o in recent)

    def table(field: str) -> list[dict]:
        counts = Counter(o[field] for o in recent)
        rows = []
        for name, c in counts.most_common(5):
            sizes = [o["pieces"] for o in recent if o[field] == name]
            expected = lam * c / len(recent)
            rows.append({field: name, "share": round(c / len(recent), 3), "expected_orders": round(expected, 2),
                         "chance_any": round(1 - math.exp(-expected), 2), "typical_pieces": round(mean(sizes))})
        return rows
    return {"enough_data": True, "window_days": window, "orders_in_window": len(recent),
            "horizon_working_days": horizon, "horizon_end": kth_working_day(business_date, horizon).isoformat(),
            "expected_orders": round(lam, 1), "orders_low": lo, "orders_high": hi,
            "expected_pieces": round(lam * avg), "pieces_low": round(lo * avg), "pieces_high": round(hi * avg),
            "mean_pieces": round(avg), "customers": table("customer"), "products": table("product"),
            "method": f"Order counts over the last {window} days, projected {horizon} working days ahead; the range is the "
                      "10th to 90th percentile of a Poisson count. Customer and product shares are their share of those "
                      "orders. Frequency counting, not a promise."}


def forecast_backtest(orders: list[dict], business_date: date, horizon: int = FORECAST_HORIZON,
                      window: int = FORECAST_WINDOW, step: int = 3) -> dict:
    """Replay the forecast from past starting points that have a full horizon of known outcome, and compare it with what
    arrived. Baseline: 'the same number as in the previous period of the same length'. Starting points overlap, and
    with only a few months of history there are few of them, so treat the result as a sanity check, not an accuracy claim."""
    if not orders:
        return {"enough_data": False, "starting_points": 0}
    dates = sorted(date.fromisoformat(o["order_date"]) for o in orders)
    first = dates[0] + timedelta(days=window)
    t, rows = first, []
    while True:
        end = kth_working_day(t, horizon)
        if end >= business_date:
            break
        actual = [o for o in orders if t <= date.fromisoformat(o["order_date"]) <= end]
        prev_start = t - timedelta(days=(end - t).days + 1)
        naive = sum(1 for o in orders if prev_start <= date.fromisoformat(o["order_date"]) < t)
        f = forecast(orders, t, horizon, window)
        if f["enough_data"]:
            top3 = {c["customer"] for c in f["customers"][:3]}
            rows.append((abs(f["expected_orders"] - len(actual)), abs(naive - len(actual)),
                         sum(o["customer"] in top3 for o in actual), len(actual)))
        t += timedelta(days=step)
    if len(rows) < 3:
        return {"enough_data": False, "starting_points": len(rows)}
    n_actual = sum(r[3] for r in rows)
    n_customers = len({o["customer"] for o in orders})
    return {"enough_data": True, "starting_points": len(rows), "mae_forecast": round(mean(r[0] for r in rows), 1),
            "chance_top3_customer_rate": round(min(3, n_customers) / n_customers, 2),
            "mae_same_as_last_period": round(mean(r[1] for r in rows), 1),
            "top3_customer_hit_rate": round(sum(r[2] for r in rows) / n_actual, 2) if n_actual else None}
