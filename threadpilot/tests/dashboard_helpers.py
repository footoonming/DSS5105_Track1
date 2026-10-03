"""Helpers shared by the browser tests (test_chat.py, test_panels.py). The fixtures (site, B, page) are in conftest.py."""
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = date(2026, 4, 1)


def d(i): return BASE + timedelta(days=i)
def short(dt): return f"{dt:%a}, {dt.day} {dt:%b}"
def workdays(a, b): return sum((a + timedelta(days=k)).weekday() != 6 for k in range((b - a).days + 1))
def plural(k, w): return f"{k} {w}{'' if k == 1 else 's'}"
def text(r): return " ".join(r["lines"])
def order(B, i, oid): return next(o for o in B[i]["orders"] if o["order_id"] == oid)


def ask(page, i, *qs):
    """Go to morning i, start a fresh conversation, ask the questions in order, return the responses."""
    return page.evaluate("""([i, qs]) => { go(i); ThreadPilotChat.reset();
        return qs.map(q => JSON.parse(JSON.stringify(ThreadPilotChat.respond(q)))); }""", [i, list(qs)])


def reset_browser_state(page):
    """Forget settings and memos saved in the browser and reload the page."""
    page.evaluate("localStorage.clear()")
    page.reload()
    page.wait_for_selector("#riskCard .rk-col")
