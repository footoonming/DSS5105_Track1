"""Simulate N mornings, build a briefing for each, and write a self-contained demo page.

    python -m simulation.render_demo --days 14

Writes:
    briefings/<date>.json          one archived briefing per morning (the audit trail)
    demo/briefing_demo.html        open in any browser, no server needed

Morning 0 (2026-04-01) is the original, unmodified dataset. Every later morning is
the simulator's output for that date. Each briefing is compared with the one
before it, which is where "new since yesterday" and "resolved" come from.
"""
from __future__ import annotations

import argparse
import json
import tempfile
from datetime import date, timedelta
from pathlib import Path

from .briefing import build
from .simulate import BASE_DIR, DEFAULT_SCENARIO, simulate

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = Path(__file__).resolve().parent / "demo_template.html"
BASE_DATE = date(2026, 4, 1)


def slim(b: dict) -> dict:
    """Drop what the page does not need, to keep the HTML small."""
    b = dict(b)
    b.pop("all_findings", None)
    return b


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--days", type=int, default=14, help="mornings after 2026-04-01 to include")
    p.add_argument("--scenario", type=Path, default=DEFAULT_SCENARIO)
    p.add_argument("--briefings", type=Path, default=ROOT / "briefings")
    p.add_argument("--html", type=Path, default=ROOT / "demo" / "briefing_demo.html")
    a = p.parse_args()

    a.briefings.mkdir(parents=True, exist_ok=True)
    previous, pages = None, []
    with tempfile.TemporaryDirectory() as tmp:
        for n in range(a.days + 1):
            day = BASE_DATE + timedelta(days=n)
            if n == 0:
                folder = BASE_DIR
            else:
                folder = Path(tmp) / day.isoformat()
                simulate(day, BASE_DIR, folder, a.scenario)
            b = build(folder, day, previous)
            (a.briefings / f"{day}.json").write_text(json.dumps(b, indent=2), encoding="utf-8", newline="\n")
            pages.append(slim(b))
            previous = b
            print(f"{day}  " + b["headline"][1])

    scenario = json.loads(a.scenario.read_text(encoding="utf-8"))
    payload = {"briefings": pages, "scenario": scenario["events"]}
    html = TEMPLATE.read_text(encoding="utf-8")
    here = Path(__file__).resolve().parent
    for marker, name in (("/*__CHAT_CSS__*/", "chat.css"), ("<!--__CHAT_HTML__-->", "chat.html"), ("/*__CHAT_JS__*/", "chat.js")):
        html = html.replace(marker, (here / name).read_text(encoding="utf-8"))
    html = html.replace("/*__DATA__*/null", json.dumps(payload))
    a.html.parent.mkdir(parents=True, exist_ok=True)
    a.html.write_text(html, encoding="utf-8", newline="\n")
    print(f"Wrote {len(pages)} briefings to {a.briefings} and the demo page to {a.html}")


if __name__ == "__main__":
    main()
