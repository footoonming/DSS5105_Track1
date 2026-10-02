"""Checks for the dashboard chat assistant. They run the real page in a headless browser and compare answers
with numbers computed here, in Python, straight from the briefing JSON.

    pip install pytest playwright && playwright install chromium
    pytest tests/test_chat.py

These cases were written by the author of the assistant, so they show it behaves as designed. They are not an
independent accuracy measure: for that, add questions written by someone who has not seen the code.
"""
import json
import re
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

sync_api = pytest.importorskip("playwright.sync_api")
ROOT = Path(__file__).resolve().parents[1]
BASE = date(2026, 4, 1)


def d(i): return BASE + timedelta(days=i)
def short(dt): return f"{dt:%a}, {dt.day} {dt:%b}"
def workdays(a, b): return sum((a + timedelta(days=k)).weekday() != 6 for k in range((b - a).days + 1))
def plural(k, w): return f"{k} {w}{'' if k == 1 else 's'}"


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    out = tmp_path_factory.mktemp("site")
    subprocess.run([sys.executable, "-m", "simulation.render_demo", "--days", "14", "--briefings", str(out / "b"),
                    "--html", str(out / "demo.html")], cwd=ROOT, check=True, capture_output=True)
    briefs = [json.loads(p.read_text()) for p in sorted((out / "b").glob("*.json"))]
    return out / "demo.html", briefs


@pytest.fixture(scope="module")
def B(site): return site[1]


@pytest.fixture(scope="module")
def page(site):
    with sync_api.sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as e:  # no browser installed
            pytest.skip(f"headless browser not available: {e}")
        pg = browser.new_page()
        pg.goto(site[0].as_uri())
        yield pg
        browser.close()


def ask(page, i, *qs):
    """Go to morning i, start a fresh conversation, ask the questions in order, return the responses."""
    return page.evaluate("""([i, qs]) => { go(i); ThreadPilotChat.reset();
        return qs.map(q => JSON.parse(JSON.stringify(ThreadPilotChat.respond(q)))); }""", [i, list(qs)])


def text(r): return " ".join(r["lines"])
def order(B, i, oid): return next(o for o in B[i]["orders"] if o["order_id"] == oid)


# ---------- retrieval and judgement ----------
def test_morning_summary_uses_briefing_numbers(page, B):
    r, = ask(page, 8, "Did anything go wrong yesterday?")
    assert r["intent"] == "summary"
    assert f"{B[8]['kpis']['output_yday']:,}" in text(r)
    assert B[8]["headline"][1] in text(r)
    assert r["tools"][0]["name"] == "get_briefing_summary"


@pytest.mark.parametrize("q,status", [("How many orders are late?", "late"), ("Which orders are at risk?", "at_risk")])
def test_status_counts_match(page, B, q, status):
    r, = ask(page, 8, q)
    k = B[8]["status_counts"][status]
    assert plural(k, "order") in text(r)
    assert r["detail"] and "orders.csv line" in r["detail"]


def test_due_this_week_and_idle_counts(page, B):
    due, idle = ask(page, 8, "What is due this week?")[0], ask(page, 8, "Which orders are stuck?")[0]
    assert plural(B[8]["kpis"]["due_7d"], "order") in text(due)
    assert plural(B[8]["kpis"]["idle_5d"], "order") in text(idle)


def test_order_status_cites_its_row(page, B):
    r, = ask(page, 8, "What is the status of ORD-120?")
    o = order(B, 8, "ORD-120")
    assert r["intent"] == "order_status" and f"{-o['days_to_due']} days past" in text(r)
    assert f"orders.csv line {o['row']}" in r["sources"][0]


def test_stage_output_matches_production_log(page, B):
    r, = ask(page, 8, "How did packing do yesterday?")
    y = B[8]["stages"]["PACKING"]["yesterday"]
    assert f"{y['observed']:,}" in text(r)
    assert any(f"line {e['row']}" in s for e in y["evidence"][:1] for s in r["sources"])


def test_stage_on_a_past_weekday(page, B):
    r, = ask(page, 8, "How was washing on Monday?")           # Thu 9 Apr -> Mon 6 Apr
    h = next(x for x in B[8]["stages"]["WASHING"]["history"] if x["date"] == "2026-04-06")
    assert f"{h['value']:,}" in text(r) and "Mon, 6 Apr" in text(r)


def test_bottleneck_names_the_biggest_queue(page, B):
    r, = ask(page, 8, "Where is the bottleneck?")
    hot = max(B[8]["pipeline"], key=lambda s: s["days_of_work"] or 0)
    assert hot["stage"].title() in text(r) and str(hot["days_of_work"]) in text(r)


def test_on_time_delivery(page, B):
    r, = ask(page, 8, "What is our on-time delivery?")
    assert f"{B[8]['on_time_30d']['pct']}%" in text(r)
    assert r["detail"].count("orders.csv line") == B[8]["on_time_30d"]["completed"]


# ---------- tracing and multi-turn ----------
def test_why_expands_to_rows(page, B):
    r, = ask(page, 8, "Why is ORD-120 late?")
    o = order(B, 8, "ORD-120")
    assert r["intent"] == "trace_order" and any(t["name"] == "trace_order" for t in r["tools"])
    assert f"orders.csv line {o['row']}" in r["detail"]


def test_follow_up_remembers_the_order(page, B):
    a, b, c = ask(page, 8, "Why is ORD-120 late?", "and ORD-020?", "why is that one late?")
    assert "ORD-020" in text(b) and "ORD-020" in text(c) and c["intent"] == "trace_order"


def test_vague_question_asks_which_order(page, B):
    r, = ask(page, 8, "How is the TrendCart order doing?")
    active = [o["order_id"] for o in B[8]["orders"] if o["customer"] == "TrendCart"]
    assert r["asks"] and r["intent"] == "clarify_order"
    assert {c["q"] for c in r["chips"]} >= set(active[:6])
    assert not re.search(r"\d+ days", text(r))                 # it must not guess an answer


def test_clarification_can_be_answered_with_an_order_id(page, B):
    q, a = ask(page, 8, "How is the TrendCart order doing?", "ORD-020")
    assert a["intent"] == "order_status" and "ORD-020" in text(a)


def test_customer_summary(page, B):
    r, = ask(page, 8, "How is TrendCart doing?")
    c = next(x for x in B[8]["customers"] if x["customer"] == "TrendCart")
    assert plural(c["active"], "order") in text(r) and f"{c['late']} late" in text(r)


# ---------- things the data cannot answer ----------
@pytest.mark.parametrize("q", ["What's our revenue this month?", "How much profit did we make on ORD-120?",
                               "What price do we charge per hoodie?", "Who is the best machine operator?",
                               "Who is working on ORD-120?", "What will demand be next month?",
                               "What does a workshop cost per piece?"])
def test_refuses_instead_of_inventing(page, q):
    r, = ask(page, 8, q)
    assert r["intent"] == "no_data" and r["refused"]
    assert not re.search(r"\d", text(r))


def test_does_not_invent_a_cause(page, B):
    r, = ask(page, 8, "Why did washing drop yesterday?")
    t = text(r).lower()
    assert "cannot say why" in t and "dryer" not in t and "breakdown" not in t
    assert f"{B[8]['stages']['WASHING']['yesterday']['observed']:,}" in text(r)


def test_unknown_order_and_gibberish(page):
    a, b = ask(page, 8, "Where is ORD-999?", "asdf qwerty")
    assert a["intent"] == "not_found" and b["intent"] == "fallback"


def test_chat_code_never_reads_the_planted_events():
    src = (ROOT / "simulation" / "chat.js").read_text()
    assert "DATA.scenario" not in src and "scenario.json" not in src


# ---------- feasibility ----------
ALLOWED = ("Likely feasible", "Feasible but tight", "Possible only if it is prioritised", "Unlikely")


def test_feasibility_is_an_estimate_with_assumptions(page, B):
    r, = ask(page, 8, "Can we take 800 hoodies by the 25th?")
    assert r["intent"] == "feasibility" and text(r).startswith(ALLOWED)
    assert not text(r).lower().startswith("yes")
    assert f"{workdays(d(8), date(2026, 4, 25))} working days" in text(r)
    assert len(r["assumptions"]) >= 6 and "estimate" in text(r) and r["detail"]


def test_feasibility_asks_for_what_is_missing(page):
    a, b = ask(page, 8, "Can we take 800 hoodies?", "by the 25th")
    assert a["intent"] == "clarify_feasibility" and "date" in text(a)
    assert b["intent"] == "feasibility"
    c, d2 = ask(page, 8, "Can we take some hoodies by the 25th?", "600")
    assert c["intent"] == "clarify_feasibility" and "How many pieces" in text(c) and d2["intent"] == "feasibility"


@pytest.mark.parametrize("q,due", [("Can we take 800 hoodies by Friday?", date(2026, 4, 10)),
                                   ("Can we take 800 hoodies in 2 weeks?", date(2026, 4, 23)),
                                   ("Can we take 800 hoodies by 30 April?", date(2026, 4, 30)),
                                   ("Can we take 1,200 hoodies by 2026-05-02?", date(2026, 5, 2))])
def test_feasibility_understands_dates(page, q, due):
    r, = ask(page, 8, q)
    assert f"by {short(due)}" in text(r)


def test_feasibility_what_if_reuses_the_last_order(page):
    a, b, c = ask(page, 8, "Can we take 800 hoodies by the 25th?", "What if the due date is 2026-05-02", "What about 400 pieces")
    ab, ac = b["tools"][0]["args"], c["tools"][0]["args"]
    assert (ab["pieces"], ab["due"]) == (800, "2026-05-02")            # new date, pieces remembered
    assert (ac["pieces"], ac["due"]) == (400, "2026-05-02")            # new pieces, latest date remembered
    assert b["tools"][0]["name"] == c["tools"][0]["name"] == "check_feasibility"


def test_feasibility_rejects_a_past_date(page):
    r, = ask(page, 8, "Can we take 800 hoodies by 2026-04-01?")
    assert "already passed" in text(r)


# ---------- actions: confirm first, log after ----------
def test_chase_needs_confirmation_then_logs(page):
    out = page.evaluate("""() => { go(8); ThreadPilotChat.reset(); const n0 = log.length;
        const r = ThreadPilotChat.respond("Chase ORD-120"); const n1 = log.length;
        ThreadPilotChat.apply(r, {}); return {intent: r.intent, hasConfirm: !!r.confirm, blast: r.confirm.blast, n0, n1, n2: log.length, top: log[0].what}; }""")
    assert out["intent"] == "chase_draft" and out["hasConfirm"] and "Worst case" in out["blast"]
    assert out["n1"] == out["n0"] and out["n2"] == out["n0"] + 1 and "ORD-120" in out["top"]


def test_chase_it_uses_the_order_just_discussed(page):
    a, b = ask(page, 8, "ORD-020", "That order has not moved. Chase it up.")
    assert b["intent"] == "chase_draft" and "ORD-020" in b["confirm"]["title"]


def test_a_new_command_is_not_swallowed_by_an_open_question(page):
    q, a = ask(page, 8, "How is the TrendCart order doing?", "Chase ORD-120")
    assert q["asks"] and a["intent"] == "chase_draft"
    q, b = ask(page, 8, "How is the TrendCart order doing?", "ORD-120 please")
    assert b["intent"] == "order_status"


def test_chase_a_customer_asks_which_order(page):
    r, = ask(page, 8, "Chase TrendCart")
    assert r["asks"] and r["intent"] == "clarify_order"


def test_note_asks_for_text_then_saves_it(page):
    a, b = ask(page, 8, "Add a note to ORD-120: waiting on trim approval", "Add a note to ORD-020")
    assert a["intent"] == "note_draft" and a["confirm"]["editable"]["value"] == "waiting on trim approval"
    assert b["intent"] == "clarify_note" and b["asks"]


def _watch_flow(page, i, q, advance_to):
    return page.evaluate("""([i, q, j]) => { go(i); ThreadPilotChat.reset();
        const r = ThreadPilotChat.respond(q); const before = ThreadPilotChat.watches.length; ThreadPilotChat.apply(r, {});
        const w0 = {...ThreadPilotChat.watches[0]}; go(j); const w1 = {...ThreadPilotChat.watches[0]}; go(i); const w2 = {...ThreadPilotChat.watches[0]};
        return {intent: r.intent, before, after: ThreadPilotChat.watches.length, state1: w1.state, msg1: w1.result, state2: w2.state, trigger: w0.trigger}; }""", [i, q, advance_to])


def test_watch_fires_from_data_not_from_memory(page, B):
    out = _watch_flow(page, 8, "Tell me if ORD-120 hasn't moved by Friday", 9)
    assert out["intent"] == "watch_draft" and out["before"] == 0 and out["after"] == 1 and out["trigger"] == "2026-04-10"
    then, later = order(B, 8, "ORD-120"), next((o for o in B[9]["orders"] if o["order_id"] == "ORD-120"), None)
    expect = "fired" if later and later["last_activity"] <= then["last_activity"] else "cleared"
    assert out["state1"] == expect and out["state2"] == "active"      # rewinding the date re-arms the watch


def test_conditional_reminder_for_a_stage(page, B):
    out = _watch_flow(page, 8, "Remind me tomorrow if packing is still behind", 9)
    assert out["intent"] == "watch_draft" and out["trigger"] == "2026-04-10"
    expect = "fired" if B[9]["stages"]["PACKING"]["yesterday"]["status"] == "below" else "cleared"
    assert out["state1"] == expect


# ---------- the interface itself ----------
def test_drawer_roundtrip(page):
    page.evaluate("go(8); ThreadPilotChat.reset()")
    page.click("#chatFab")
    assert page.is_visible("#chatPanel")
    page.fill("#chatInput", "Chase ORD-120")
    page.press("#chatInput", "Enter")
    page.wait_for_selector(".cc [data-confirm]")
    n0 = page.locator("#log li").count()
    page.click(".cc [data-confirm]")
    page.wait_for_selector(".cc.closed")
    assert "Chase-up sent about ORD-120" in page.inner_text("#log")
    assert page.locator("#log li").count() >= n0
    page.keyboard.press("Escape")
    assert not page.is_visible("#chatPanel")


def test_dates_do_not_depend_on_the_browser(page):
    """Browsers disagree on punctuation (newer date data drops the comma in 'Fri, 10 Apr'); the page must not."""
    out = page.evaluate("""() => { go(8); ThreadPilotChat.reset();
        const orig = Date.prototype.toLocaleDateString;
        Date.prototype.toLocaleDateString = function (l, o) { const r = orig.call(this, l, o); return /^[A-Za-z]{3},/.test(r) ? r.replace(',', '') : r + '!'; };
        try { return [fmt('2026-04-10', {weekday: 'short', day: 'numeric', month: 'short'}), fmt('2026-04-09', {weekday: 'long', day: 'numeric', month: 'long'}),
                      fmt('2026-04-09', {weekday: 'short', day: 'numeric', month: 'short', year: 'numeric'}), fmt('2026-04-09', {day: 'numeric', month: 'short'}),
                      ThreadPilotChat.respond('Can we take 800 hoodies by Friday?').lines[0]]; }
        finally { Date.prototype.toLocaleDateString = orig; } }""")
    assert out[:4] == ["Fri, 10 Apr", "Thursday 9 April", "Thu, 9 Apr 2026", "9 Apr"]
    assert "by Fri, 10 Apr" in out[4]
