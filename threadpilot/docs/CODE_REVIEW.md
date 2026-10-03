# Code review and integration notes

## Updates, 2 October 2026 (read first)

* **Live password in documentation (fixed in this package).** README section 7.4 (Windows example) contained
  the MySQL root password that was also in `.env`, plus two generated passwords. They are replaced with
  placeholders in `README.zh.md`. Change that root password, and any other place it is used.
* **`data/raw/` advice withdrawn.** See item 2 below. Keep `data/raw/` ignored.
* **LangChain is already used**, by the SQL agent in `backend/app/services/ai_sql_service.py`. Advice given in
  chat ("don't add LangChain") assumed it was not. Keep it where it is; there is no need to extend it just to
  standardise output formats. Note: `langchain-community`, which the SQL agent imports for `SQLDatabaseToolkit`,
  now emits a deprecation warning saying it is being sunset and no longer actively maintained. It works today;
  plan a migration to the standalone integration packages after the capstone.
* **`backend/start.sh` had Windows line endings**, which break it on macOS and Linux. Converted, and
  `.gitattributes` now keeps shell scripts LF.
* **The public repository is older than the local code** (no `docker-compose.yml`, no SQL agent). See
  `docs/GITHUB_GUIDE.md`.
* **`BUSINESS_NOW` example** now uses the dataset's morning, so a fresh setup does not report every order as
  months late.


Reviewed: `threadpilot.zip`, `DSS5105.zip`, `index.html`, `index__5_.html`, against the
Track 1 brief.

---

## 1. Fix before publishing

| # | Issue | Where | Fix |
|---|---|---|---|
| 1 | Live OpenAI key and real database passwords shipped in the zip | `backend/.env`, `.env` | Rotate the key and passwords. Share `.env.example` only. |
| 2 | ~~A fresh clone cannot import data~~ **Withdrawn.** The seed command loads the committed `data/*.csv`; `data/raw/` only feeds optional imports and sync | n/a | Keep `data/raw/` ignored |
| 3 | 78 MB of build output in the archive | `backend/.venv` (246 MB), `backend/runtime/` (MySQL data, TLS private keys, test SQLite) | Delete before committing; extend `.gitignore` |
| 4 | Test databases and `__pycache__` committed | throughout | Same |

## 2. Why the briefing repeats itself

Three independent causes, all fixed by the new `simulation/` package:

1. **Hard-coded strings** in `frontend/data-views.js`: `"Wednesday, April 1"`,
   `"on Mar 31"`, `"of 120 total orders"`, and `const SNAPSHOT='Apr 01, 2026 …'` in
   `app.js`. Even with new data the page reads the same. Derive all of these from
   `TRACK1_DATA.today`.
2. **The dataset never moves.** One snapshot, business date 2026-04-01.
3. **The clock does not match the data.** `BUSINESS_NOW=live` makes "today"
   September 2026, so every order looks ~175 days idle and every briefing screams.

Also: nothing generates the briefing on a schedule. The "preferred time" field in
settings only writes to `localStorage`. APScheduler is already a dependency; a job
that advances the day at 06:55 and writes the briefing at 07:00 closes this gap and
gives you the archive that makes "what changed since yesterday" possible.

## 3. Design issues against the brief

* **Two definitions of "normal".** `data-views.js` compares against the prior 20
  working-day mean; `backend/app/workflow_tools.py::normality` uses the previous 8
  same weekdays. The brief asks for one explicit, inspectable definition. Keep the
  same-weekday one, in the backend, and let the frontend read it.
* **Three implementations of risk.** Frontend JavaScript, `DSS5105/tools/risk_tools.py`
  and the backend workflow tools each compute their own score. One source of truth.
* **Arithmetic in the browser.** The frontend recomputes scores, baselines and counts
  from the snapshot. It happens not to be the LLM doing it, but it still means the
  interface and the tools can disagree. Have the backend return computed values.
* **Two competing frontends.** `index__5_.html` ("SweaterCo Co-Pilot", `API_MODE='mock'`,
  `const TODAY='2026-04-01'`) and `threadpilot/frontend`. Pick one; a grader who opens
  the wrong one sees a mock.
* **A broken loader copy.** The standalone `index.html` loads `data.js` *and*
  `app.js`, `data-views.js`, `ai-api.js`, `ai-stream.js` statically, while `data.js`
  injects those same scripts after fetching the snapshot. The static `app.js` runs
  before `TRACK1_DATA` exists and the second load hits duplicate `const`
  declarations. The repo's `frontend/index.html` is correct; delete the other copy.
* **Evaluation reporting.** `live-verification-summary.json` shows 36/45 workflow
  turns passing on the first full run, then a rerun of the failures, reported as
  "combined distinct turns passed: 45". Report the first-pass number, 80%, and
  describe the rerun separately. The brief grades measured accuracy, and an honest
  lower number scores better than an inflated one.
* **Language.** README, `docs/` and most docstrings are in Chinese. Lecturers and
  external readers need an English README at minimum.
* **Deliverables to confirm:** the one-table tool specification (name, input, output,
  purpose, non-goals, failure mode) and the ≥30-question evaluation set with ≥5
  ambiguous/unanswerable/hallucination-bait and ≥5 feasibility or action requests.
  `data/dialogs.xlsx` has 1,012 scenario rows but is not that table; produce both as
  short documents a grader can read in five minutes.

## 4. The ML package (DSS5105)

The structure is good: one feature function shared by training and serving, a report
with coefficients, and a refusal path when there are too few samples. The problems
are statistical.

| Issue | Evidence | Suggested fix |
|---|---|---|
| Workshop features carry no information | `workshop_avg_capacity`, `_queue_days`, `_defect_rate` are computed from `category` alone, so all three get the identical coefficient −0.0647 | Drop them, or make them order-specific |
| Train/serve skew | `build_training_table` uses `reference_date=due_date`; `predict_order_delay` uses today | Use a consistent as-of date, e.g. a fixed number of days before due |
| Censoring | Only `COMPLETE` orders are trained on, so orders that are already late and still running are excluded | Label in-progress orders past due as delayed, or model time-to-finish |
| Noisy metrics | 86 samples, one 22-row test split, AUC 0.923 | Repeated stratified 5-fold CV, report a spread, compare against a pieces-only baseline and against the rule-based score |
| Saturated predictions | Every 2,000-piece order gets 0.99 | Check calibration; `pieces` dominates after scaling |
| Not connected | No reference to `predict_order_delay` anywhere in `threadpilot/` | Expose it as a tool with a stated failure mode, or say in the report that it is a prototype |
| Unsupported output | `suggested_workshop` in `in_progress_orders_forecast.csv` — the data never links orders to workshops | Label it as an assumption-driven recommendation |
| Version mismatch | `__pycache__` shows Python 3.14; backend requires `>=3.12,<3.14` | Pin one version |
| Duplicated code | `models/feasibility_tools.py` and `tools/feasibility_tools.py` differ | Keep one |

One data note: `workshops.csv` has `cost_per_piece`. That is a cost, not a price or
revenue, so the co-pilot should still refuse revenue questions.

---

## 5. What is in this package

```
simulation/simulate.py             day-by-day factory simulator (seeded, same schema)
simulation/briefing.py             judgement, discovery, tracing; all arithmetic
simulation/render_demo.py          simulate N days, archive briefings, build the demo page
simulation/evaluate_discovery.py   score findings against the planted events
simulation/scenarios/default.json  planted events: ground truth, never read by the briefing
simulation/demo_template.html      the page template
demo/briefing_demo.html            ready to open, 15 mornings embedded
briefings/2026-04-*.json           one archived briefing per morning
tests/test_simulation.py           10 tests
```

Run it:

```bash
python -m simulation.render_demo --days 14     # rebuild everything
python -m simulation.evaluate_discovery        # recall against planted events
pytest tests/test_simulation.py
```

No dependencies beyond the standard library. Drop `simulation/` and `tests/` into the
repository root; `demo/` and `briefings/` are generated output you may either commit
as evidence or ignore.

### Current measured result

```
EV-1  assembly dip        found 1 day after it started
EV-2  dryer breakdown     found 1 day after
EV-3  TrendCart hold      found 4 days after
EV-4  quiet order         found 5 days after
EV-5  rush order          found 1 day after
Recall 5/5. 7 cause-claiming findings with no planted event behind them
(5 are genuine knock-on starvation in the simulated queue, 2 are false positives).
```

Put that table in the report. It is exactly the "measured accuracy" the brief asks
for, and the false positives are more convincing than a perfect score.

## 6. Wiring it into the backend

Scheduled generation, using APScheduler which you already depend on:

```python
# backend/app/main.py, at startup
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from simulation.briefing import build
from simulation.simulate import simulate

scheduler = AsyncIOScheduler(timezone="Asia/Singapore")

@scheduler.scheduled_job("cron", hour=6, minute=55)
def advance_day() -> None:
    simulate(next_business_date(), out=LIVE_DIR)   # or import real data here instead
    import_into_database(LIVE_DIR)

@scheduler.scheduled_job("cron", hour=7, minute=0)
def write_briefing() -> None:
    previous = load_latest_briefing()
    briefing = build(LIVE_DIR, previous=previous)
    save_briefing(briefing)                         # briefings/<date>.json
```

Then serve it: `GET /api/briefing` for today, `GET /api/briefing?date=YYYY-MM-DD`
for an archived morning. The frontend reads that instead of recomputing anything,
which also removes the duplicate "normal" definition.

For the chat side, each briefing finding is already a tool result with evidence, so
"why is that order at risk?" should re-run the tool rather than paraphrase the
briefing text.

## 7. Interface suggestions

* Remove every hard-coded date and count; derive from the data.
* Show the business date and, while you are using simulated data, say "simulated
  day 8" next to it. Never let it look like a live feed.
* First three lines: what happened, what is at risk, what to decide. Everything else
  one click away.
* On every number, a way to open the rows behind it.
* Show what changed since the previous briefing, including items that cleared.
  Resolution is information too.
* Charts with a normal band beat charts with a single line, because the question is
  never "how many pieces" but "is that normal".
* Keep the briefing archive reachable, so the manager can say "what did you tell me
  on Monday?".
* Voice out is cheap: `speechSynthesis` reads the three lines, no API needed.

## 8. Video plan for the briefing section (about 70 seconds)

1. Open on 1 April, the original dataset. Read the three lines. (10s)
2. Click 8 April. Point at "New today": the TrendCart hold and washing 61% below
   normal. (20s)
3. Expand "Show the 9 source rows" on the washing finding, so the grader sees line
   numbers, not prose. (15s)
4. Click 10 April: packing is low, and the briefing says it may be short of work
   because washing was down two days earlier. (15s)
5. Open the planted-events panel: nobody told the system about these; it found them
   from the data. (10s)

That answers "is this dynamic?" without anyone having to take your word for it.


## Code review of the dashboard and prediction code, October 2026

Tools used: `ruff` (pyflakes, bugbear and simplify rules), `node --check`, a byte-for-byte comparison of all 15 briefings before and after
the refactor, and new regression tests that were confirmed to fail on the previous code.

**Fixed**

| Problem | Effect | Fix |
|---|---|---|
| Stage-target alert pills were added again on every keystroke | Duplicate red pills piled up in the summary while typing a target | Earlier pills are replaced, not appended |
| Data was embedded in a `<script>` tag as raw JSON | A value containing `</script>` (e.g. a customer name from an uploaded spreadsheet) would break the page | `embed_json` writes `</` as `<\/` |
| Order IDs were inserted into the orders table without escaping | A crafted order ID could inject HTML | Escaped like every other value |
| "worth" and "shift" were refusal words | "Is it worth prioritising ORD-120?" and "What caused the shift in output?" were refused | Removed; "prioritise" now means expedite |
| The chat took the first number as the piece count | "2 orders of 400 hoodies" was read as 2 pieces | Numbers followed by orders, days, weeks and similar are skipped |
| An order that never finishes was given the 200th working day as its date | A made-up date in the risk reason | Says it does not finish within 200 working days |
| Memo dates were stored in UTC | Before 08:00 in Singapore a memo showed yesterday's date | Local date stored |
| Dialogs did not take keyboard focus | Keyboard users had to tab through the page to reach a dialog | Focus moves in on open and back on close |
| Empty-data-attribute buttons ("Use usual output", "Clear", "Open in email app") did nothing | Found while testing; fixed earlier | `"key" in dataset` instead of a truthiness check |
| One test used `A and B or C` | It passed almost regardless of the page | Asserts the exact expected text |
| Calendar helpers were defined in two Python modules | Two copies to keep in step | One module, `simulation/workdays.py` |
| Test tools were not pinned | CI could pick a newer browser with different behaviour, as happened with the date commas | `requirements-dev.txt`, used by CI |
| Files opened without closing, unused imports, a lambda capturing a loop variable | Lint warnings | Cleaned; `ruff` passes |

**Recommended, not done (larger changes)**

* `briefing.build()` is about 400 lines. Splitting it into steps (load, derive, discover, assess, summarise) would make each step testable on its own.
* Feasibility in the chat uses a closed-form estimate in JavaScript; risk and expedite use the Python projection. Both were validated, but feasibility
  should move to the backend and use `project`, so there is one method.
* `chat.js` and `panels.js` rely on globals defined by the page (`B`, `idx`, `fmt`, `esc`). Fine for a single-file demo; in the real front end
  use modules with explicit imports.
* Intent routing in the demo chat is ordered regular expressions. The test suite guards it, but the backend's intent classifier should do this in production.
* Settings and memos live in the browser. In production they belong to the user's account and to an `order_amendments` table (see
  `docs/prediction_validation.md`).
* The demo page embeds 15 briefings (1.6 MB). A production page should fetch one briefing at a time from the backend.
