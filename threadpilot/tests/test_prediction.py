"""Checks for the risk, expedite and forecast models (no browser needed). Run with:  pytest tests/test_prediction.py"""
import csv
import json
from datetime import date, timedelta

import pytest

from simulation.briefing import build
from simulation.prediction import (STAGES, assess_expedite, assess_risk, forecast, forecast_backtest, kth_working_day, poisson_interval,
                                   project)
from simulation.simulate import BASE_DIR, DEFAULT_SCENARIO, simulate

MONDAY = date(2026, 4, 6)
CAP = {s: 1000.0 for s in STAGES}


def read_orders(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def order(oid, pieces, stage, due, customer="C"):
    return {"order_id": oid, "pieces": pieces, "current_stage": stage, "due_date": due, "customer": customer}


@pytest.fixture(scope="module")
def morning(tmp_path_factory):
    out = tmp_path_factory.mktemp("m8")
    simulate(date(2026, 4, 9), out=out)
    return build(out)


# ---------- the projection engine, against hand calculations ----------
def test_a_lone_order_needs_one_day_per_remaining_stage():
    # 600 pieces is exactly 60% of a 1,000-piece day, so it clears one stage a day: 4 stages = 4 working days
    assert project([order("A", 600, "KNITTING", "2026-05-01")], CAP, MONDAY) == {"A": 4}
    assert project([order("A", 600, "WASHING", "2026-05-01")], CAP, MONDAY) == {"A": 2}


def test_big_orders_need_more_than_one_day_per_stage():
    # 1,200 pieces at 600 a day = 2 days per stage at 4 stages, and the next stage starts the day after the previous ends
    assert project([order("A", 1200, "KNITTING", "2026-05-01")], CAP, MONDAY)["A"] == 8


def test_sundays_are_skipped():
    saturday = date(2026, 4, 4)
    k = project([order("A", 100, "KNITTING", "2026-05-01")], CAP, saturday)["A"]
    assert k == 4 and kth_working_day(saturday, k) == date(2026, 4, 8)      # Sat, Mon, Tue, Wed


def test_earliest_due_goes_first_and_expediting_reverses_it():
    a, b = order("A", 1500, "PACKING", "2026-04-10"), order("B", 1500, "PACKING", "2026-04-20")
    base, fast = project([a, b], CAP, MONDAY), project([a, b], CAP, MONDAY, expedite_id="B")
    assert base["A"] < base["B"] and fast["B"] < fast["A"]


def test_expediting_never_makes_the_order_later_nor_others_earlier():
    active = [order(f"O{i}", 700 + 100 * i, STAGES[i % 4], f"2026-04-{10 + i}") for i in range(8)]
    base = project(active, CAP, MONDAY)
    for x in active:
        fast = project(active, CAP, MONDAY, expedite_id=x["order_id"])
        assert fast[x["order_id"]] <= base[x["order_id"]]
        assert all(fast[y["order_id"]] >= base[y["order_id"]] for y in active if y is not x)


def test_expedite_assessment_adds_up():
    active = [order("A", 900, "ASSEMBLY", "2026-04-08"), order("B", 900, "ASSEMBLY", "2026-04-12"), order("C", 900, "KNITTING", "2026-04-30")]
    best = project(active, CAP, MONDAY)
    e = assess_expedite(active[1], active, CAP, MONDAY, False, 0, best, best)
    assert e["net"] == e["gain"] - e["cost"] and e["recommendation"] in {"now", "trade_off", "later", "investigate"}
    assert assess_expedite(active[1], active, CAP, MONDAY, True, 6, best, best)["recommendation"] == "investigate"


# ---------- the briefing ----------
def test_status_follows_risk_level(morning):
    for o in morning["orders"]:
        lvl = o["risk"]["level"]
        assert (o["status"] == "late") == (lvl == "overdue") == (o["days_to_due"] < 0)
        assert (o["status"] == "at_risk") == (lvl in ("high", "medium"))
        assert (o["status"] == "on_track") == (lvl == "low")


def test_every_late_or_at_risk_order_has_an_expedite_assessment(morning):
    for o in morning["orders"]:
        assert (o["expedite"] is not None) == (o["status"] in ("late", "at_risk"))
        if o["expedite"]:
            e = o["expedite"]
            assert e["net"] == e["gain"] - e["cost"] and e["recommendation"] in {"now", "trade_off", "later", "investigate"}


def test_a_stalled_order_is_never_low_risk_and_is_told_to_find_the_blocker(morning):
    stalled = [o for o in morning["orders"] if o["risk"]["stalled"]]
    assert stalled, "the planted TrendCart hold should have produced stalled orders by 9 April"
    for o in stalled:
        assert o["risk"]["level"] != "low"
        if o["expedite"]:
            assert o["expedite"]["recommendation"] == "investigate"


def test_risk_confidence_and_dates_are_present(morning):
    for o in morning["orders"]:
        r = o["risk"]
        assert r["confidence"] in {"certain", "high", "medium", "low"} and r["reason"]
        assert r["best_date"] <= (r["expected_date"] or "9999")


def test_capacity_factor_is_recorded_and_consistent(morning):
    c = morning["capacity"]
    assert 1.0 <= c["workshop_factor"] <= 3.0
    assert abs(c["workshop_factor"] - c["finished_pieces_per_day"] / c["logged_packing_per_day"]) < 0.05


def test_the_provided_data_does_not_reconcile_and_the_briefing_says_so():
    c = build(BASE_DIR, date(2026, 4, 1))["capacity"]
    assert c["workshop_factor"] > 1.5          # about 57,000 pieces finished vs 34,000 in the production log


def test_new_briefing_fields_survive_a_json_round_trip(morning):
    assert json.loads(json.dumps(morning))["orders"][0]["risk"]["level"] == morning["orders"][0]["risk"]["level"]


# ---------- the simulator accepts an expedite event ----------
def test_simulator_expedite_event_does_not_slow_the_order(tmp_path):
    scn = json.loads(DEFAULT_SCENARIO.read_text())
    simulate(date(2026, 6, 1), out=tmp_path / "base")
    base = {r["order_id"]: r for r in read_orders(tmp_path / "base" / "orders.csv")}
    pick = next(o for o in base.values() if o["status"] == "COMPLETE" and o["completed_date"] > "2026-04-20" and o["order_date"] < "2026-04-01")
    scn["events"].append({"id": "X", "type": "expedite", "order_id": pick["order_id"], "date": "2026-04-01"})
    path = tmp_path / "s.json"
    path.write_text(json.dumps(scn))
    simulate(date(2026, 6, 1), out=tmp_path / "exp", scenario_path=path)
    exp = {r["order_id"]: r for r in read_orders(tmp_path / "exp" / "orders.csv")}
    assert exp[pick["order_id"]]["completed_date"] <= pick["completed_date"]


# ---------- forecast ----------
def make_orders(n, days=60, end=date(2026, 4, 1)):
    return [{"order_id": f"O{i}", "customer": "A" if i % 3 else "B", "product": "Hoodie" if i % 2 else "Vest", "pieces": 1000,
             "order_date": (end - timedelta(days=1 + i * days // n)).isoformat(), "due_date": end.isoformat()} for i in range(n)]


def test_forecast_is_the_arithmetic_it_claims_to_be():
    f = forecast(make_orders(60), date(2026, 4, 1))
    assert f["enough_data"] and f["orders_in_window"] == 60
    assert f["orders_low"] <= f["expected_orders"] <= f["orders_high"]
    assert abs(f["expected_pieces"] - f["expected_orders"] * f["mean_pieces"]) <= 0.05 * f["mean_pieces"]   # orders are shown to 1 decimal
    assert abs(sum(c["share"] for c in f["customers"]) - 1) < 0.01


def test_forecast_declines_when_there_is_too_little_history():
    assert forecast(make_orders(5), date(2026, 4, 1))["enough_data"] is False


def test_poisson_interval_brackets_the_mean():
    lo, hi = poisson_interval(15.0)
    assert lo < 15 < hi and (lo, hi) == (10, 20)       # P(X<=9)=0.070, P(X<=10)=0.118; P(X<=19)=0.875, P(X<=20)=0.917


def test_forecast_backtest_states_the_chance_level_for_customers():
    orders = read_orders(BASE_DIR / "orders.csv")
    for o in orders:
        o["pieces"] = int(o["pieces"])
    r = forecast_backtest(orders, date(2026, 4, 1))
    assert r["enough_data"] and r["chance_top3_customer_rate"] == pytest.approx(3 / len({o["customer"] for o in orders}), abs=0.01)


def test_an_order_that_never_finishes_gets_no_made_up_date():
    x = order("A", 1000, "KNITTING", "2026-04-30")
    k = project([x], {s: 1.0 for s in STAGES}, MONDAY)["A"]           # one piece a day: hopeless
    r = assess_risk(x, k, None, MONDAY, False)
    assert k is None and r["level"] == "high" and r.get("unfinished") and "200 working days" in r["reason"]


def test_forecast_backtest_copes_with_no_orders():
    assert forecast_backtest([], date(2026, 4, 1)) == {"enough_data": False, "starting_points": 0}
