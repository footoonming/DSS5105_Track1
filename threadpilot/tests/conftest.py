"""Shared test setup.

* Makes the threadpilot/ folder importable (the simulation package) when pytest runs from here.
* Browser fixtures for the dashboard tests: `site` builds the demo page and briefings into a temporary folder, `B` is the
  list of briefings, `page` is the page open in headless Chromium. Each test module gets its own copy (module scope).
  Browser tests skip themselves if Playwright or its browser is not installed.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    out = tmp_path_factory.mktemp("site")
    subprocess.run([sys.executable, "-m", "simulation.render_demo", "--days", "14", "--briefings", str(out / "b"),
                    "--html", str(out / "demo.html")], cwd=ROOT, check=True, capture_output=True)
    briefs = [json.loads(p.read_text()) for p in sorted((out / "b").glob("*.json"))]
    return out / "demo.html", briefs


@pytest.fixture(scope="module")
def B(site):
    return site[1]


@pytest.fixture(scope="module")
def page(site):
    sync_api = pytest.importorskip("playwright.sync_api")
    with sync_api.sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as e:  # browser not installed
            pytest.skip(f"headless browser not available: {e}")
        pg = browser.new_page()
        pg.goto(site[0].as_uri())
        yield pg
        browser.close()
