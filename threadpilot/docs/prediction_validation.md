# Risk, expedite and forecast: method, validation and limits

What was added to the morning briefing (`simulation/prediction.py`, shown in the dashboard):

* **Risk level and confidence** for every in-progress order, and the at-risk section split into *already overdue* and *approaching due date*.
* **Expedite assessment**: should an overdue or at-risk order be moved to the front of the queue, now or later?
* **Order forecast** for the next two weeks: how many orders, from which customers, for which products.

Everything is computed in Python and stored in the briefing JSON; the page and the chat only display it. Reproduce every number below with
`python -m simulation.backtest`.

## 1. A finding about the provided data

The production log and the order sizes do not reconcile. In the 60 days before 1 April, orders totalling **56,950 pieces** finished,
but the log shows packing handled **33,634 pieces** in the same days: the log accounts for about 59% of what shipped. A plausible
explanation is that the outside workshops do the rest (your brief mentions workshop capacity), but the data does not say so.

A model that trusts the log alone says every order is hopeless, which contradicts the history. So **capacity is calibrated from
completions**: usual output (average of the previous 8 same weekdays) times a *workshop factor* = pieces finished per working day divided by
the packing output the log shows (1.69 on 1 April). The factor is recorded in every briefing (`capacity`) and explained in the page's
"How these numbers are calculated". The simulator reproduces the same gap (real capacity = logged capacity x 1.69; only the logged share is
written to the log), so the demo behaves like the real data. **Ask whoever supplied the data what the log counts.**

A second finding follows from it: even with that capacity, the 34 orders in progress hold about 29 working days of work while customers
usually allow 12 to 30. **The data describes a factory that is badly behind**, so nearly every order is late or at risk, and the risk labels
cannot spread out much (section 3).

## 2. Definitions

* **Projection engine** (`project`): a day-by-day walk through the factory. Each stage works through the orders waiting at it earliest-due-first
  at its estimated daily output; Sundays closed; an order moves on at most one stage a day; one order uses at most 60% of a stage's day.
  Orders in progress start their current stage from zero (partial progress is not recorded), so estimates lean cautious.
* **Best case** = no new orders. **Expected case** = one average-sized order arrives every working day, due after the usual lead time, and goes
  ahead of any order due later.
* **Risk**: *overdue* = past the due date. *High* = even the best case finishes 5 or more working days late. *Medium* = best case 1 to 4 days
  late, or on time only if nothing new goes ahead. *Low* = on time even then. **Confidence** = how many working days the estimate sits from the due
  date (5 or more high, 2 to 4 medium, under 2 low). A **stalled** order (not moving while later-due orders move, or part of a stalled customer)
  is raised to at least medium, and to high if due within 10 working days, because the projection assumes it moves.
* **Expedite**: re-run the projection with one order first in every queue. *Gain* = working days less late for that order. *Cost* = extra
  lateness added to all other orders. *Net* = gain minus cost. **Expedite now** if net is at least 2 and no on-time order is pushed late;
  **trade-off** if net is at least 2 but some on-time order would be pushed late; **later or not needed** if the gain is under 2 or the net is
  under 2 (it just moves the delay onto others); **find the blocker first** if the order is stalled.
* **Forecast**: orders per working day over the last 60 days times 12 working days; the range is the 10th to 90th percentile of a Poisson
  count. Customer and product shares are their share of those orders. Frequency counting, not machine learning.

## 3. Validation

The simulator is not a real factory, and it follows the same earliest-due-first rule as the projection engine. Agreement below shows the
models are implemented correctly and internally consistent. **It does not show they will hold on real data.**

| Level | Orders | Finished late |
|---|---|---|
| overdue | 51 | 51 (100%) |
| high | 151 | 141 (93%) |
| medium | 35 | 32 (91%) |
| low | 2 | 0 (0%) |

Expected finish date vs actual, 239 orders that finished: mean error -1.1 working days (negative = finished earlier than predicted), mean absolute error 2.2.

Read the table as follows. The finish dates are good (average error 2.2 working days, leaning slightly cautious). The *levels* barely separate
orders, because in this simulated factory almost every order really does finish late: only 2 low-risk orders appeared in 7 mornings. That is the
data's story, not a modelling bug. The useful ranking inside "high" is how late (the "working days late at best" figure).

### Expedite: predicted vs simulated

| Morning | Order | Briefing says | Gain predicted | Gain simulated | Cost predicted | Cost simulated |
|---|---|---|---|---|---|---|
| 06 Apr | ORD-109 | now | 10 | 0 | 1 | 2 |
| 06 Apr | ORD-008 | later | 10 | 8 | 9 | 16 |
| 06 Apr | ORD-017 | later | 10 | 4 | 11 | 4 |
| 09 Apr | ORD-008 | now | 7 | 7 | 3 | 4 |
| 09 Apr | ORD-122 | later | 7 | 8 | 6 | 8 |
| 09 Apr | ORD-040 | later | 6 | 7 | 16 | 18 |
| 13 Apr | ORD-095 | later | 11 | 9 | 17 | 14 |
| 13 Apr | ORD-122 | later | 10 | 8 | 10 | 6 |
| 13 Apr | ORD-024 | later | 9 | 8 | 10 | 3 |

Mean absolute error: gain 2.8 working days, cost 3.8 working days (9 orders).

Read the table as follows. Gain is within 2 working days for 5 of 9 orders and badly wrong for one (ORD-109 on 6 April: predicted 10, simulated 0,
not diagnosed). Cost is the harder number (average error 3.8). The simulation confirms the main message: moving one order up mostly moves the
delay onto others (for ORD-008 on 6 April the simulated cost, 16 days, is twice its gain), which is why most recommendations are "later".

**Forecast** (replay on the provided orders, six overlapping starting points):

| Measure | Result |
|---|---|
| Forecast error (orders per 12 working days) | 2.8 |
| Error of "same number as the last period" | 2.0 |
| Top-3 customers hit rate | 31% of orders |
| Chance level for 3 of 8 customers | 38% |

**The forecast is not better than repeating the last period, and the customer ranking is no better than picking at random.** I tried history
windows of 14 to 60 days: none beat the baseline. The dashboard shows these test numbers beside the forecast and describes the customer and product
lists as "who orders often", not as predictions. With about 90 days of orders, nothing more can be claimed.

**Feasibility** (the chat's "Can we take N pieces by date?"), 14 test orders injected into the simulator with five start dates, 400 to 1,500
pieces and deadlines 16 to 75 days out: the real finish fell inside the estimated range in 14 of 14 cases. Verdicts: "unlikely" 5 times (all 5
finished late), "possible only if prioritised" 9 times (2 finished late, 7 on time). No case produced "likely" or "tight", so those two
verdicts are untested.

## 4. Not done, or only partly

* **Hourly refresh** is a saved setting only. The production log has one row per day, so only orders, notes and actions could change within a day,
  and this demo has one briefing per morning. For real use the backend needs an APScheduler job that rebuilds the briefing on the chosen schedule and
  an endpoint such as `GET /api/briefing?date=latest` that the page polls.
* **Memos** are notes kept in the browser. The risk model still uses the original due dates, so an amended date does not change risk. Production needs
  a table, and the tools must read it:

```sql
CREATE TABLE order_amendments (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  order_id VARCHAR(16) NOT NULL,
  kind ENUM('delivery_date', 'specification') NOT NULL,
  original_due DATE NULL, new_due DATE NULL, specification TEXT NULL,
  reason VARCHAR(200), created_by VARCHAR(64), created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

* **Teams**: the panel copies a ready message. Posting to Teams or looking up people needs a Microsoft integration and addresses, and the data holds none.
* **Settings** (text size, typeface, targets, refresh) are saved per browser, not per user account. Text size uses the CSS `zoom` property
  (Chrome, Edge, Safari, Firefox 126 or later).
* **Risk, expedite and feasibility use two different methods** (day-by-day projection in Python; a closed-form estimate in the chat). Both were checked
  against the simulator, but moving feasibility onto the same projection in the backend would remove the duplication.
