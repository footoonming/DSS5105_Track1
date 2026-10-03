"""Checks for the simulator and the briefing builder. Run with:  pytest tests/test_simulation.py"""
import csv
import filecmp
import json
from datetime import date

import pytest

from simulation.briefing import build, prev_working
from simulation.render_demo import embed_json
from simulation.simulate import BASE_DIR, ORDER_COLUMNS, simulate


@pytest.fixture(scope="module")
def day10(tmp_path_factory):
    out = tmp_path_factory.mktemp("d10")
    simulate(date(2026, 4, 11), out=out)
    return out


def test_same_inputs_give_identical_files(tmp_path, day10):
    simulate(date(2026, 4, 11), out=tmp_path)
    for name in ("orders.csv", "production_log.csv", "workshops.csv"):
        assert filecmp.cmp(tmp_path / name, day10 / name, shallow=False)


def test_schema_is_unchanged(day10):
    with (day10 / "orders.csv").open() as f:
        assert next(csv.reader(f)) == ORDER_COLUMNS
    with (day10 / "production_log.csv").open() as f:
        assert next(csv.reader(f)) == ["date", "stage", "pieces_completed"]


def test_sundays_are_closed_and_no_future_rows(day10):
    with (day10 / "production_log.csv").open() as f:
        rows = list(csv.DictReader(f))
    assert max(r["date"] for r in rows) == "2026-04-10"
    for r in rows:
        if date.fromisoformat(r["date"]).weekday() == 6:
            assert r["pieces_completed"] == "0"


def test_original_rows_are_kept(day10):
    with (BASE_DIR / "production_log.csv").open() as f:
        base = list(csv.DictReader(f))
    with (day10 / "production_log.csv").open() as f:
        sim = list(csv.DictReader(f))
    assert sim[: len(base)] == base


def test_briefing_changes_from_day_to_day(day10):
    base = build(BASE_DIR, date(2026, 4, 1))
    later = build(day10, previous=base)
    assert base["headline"] != later["headline"]
    assert later["business_date"] == "2026-04-11"


def test_every_finding_has_rows_and_a_score_reason(day10):
    for f in build(day10)["all_findings"]:
        assert f["evidence"], f["key"]
        assert f["score_reason"]
        for e in f["evidence"]:
            assert e["file"] in ("orders.csv", "production_log.csv") and e["row"] >= 2


def test_normal_uses_same_weekday_only():
    b = build(BASE_DIR, date(2026, 4, 1))
    n = b["stages"]["ASSEMBLY"]["yesterday"]
    assert n["samples"] == 8
    assert n["status"] == "below"  # the late-March assembly dip in the original data


def test_monday_briefing_covers_saturday():
    assert prev_working(date(2026, 4, 6)) == date(2026, 4, 4)


def test_planted_customer_hold_is_found(tmp_path):
    simulate(date(2026, 4, 9), out=tmp_path)
    keys = [f["key"] for f in build(tmp_path)["all_findings"]]
    assert "customer_stalled:TrendCart" in keys


def test_planted_washing_breakdown_is_found(tmp_path):
    simulate(date(2026, 4, 8), out=tmp_path)
    keys = [f["key"] for f in build(tmp_path)["all_findings"]]
    assert "stage_below:WASHING" in keys


def test_embedded_data_cannot_close_the_script_tag():
    data = {"customer": "</script><script>alert(1)</script>", "n": 1}
    out = embed_json(data)
    assert "</script>" not in out and json.loads(out) == data
