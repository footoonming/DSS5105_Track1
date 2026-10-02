# Dashboard chat assistant: tool specification, limits and validation

The "Ask ThreadPilot" drawer in `demo/briefing_demo.html` is a tool-calling assistant. **In its default mode it has
no language model and makes no network calls.** A question is routed (ordered pattern rules in `simulation/chat.js`)
to one of the tools below, the tool reads the embedded briefing JSON, and the reply is assembled from what the tool
returned. Every number in a reply comes from a tool, never from free text. Each reply can expand to the rows behind
it ("Show detail", "Sources") and lists the tools it used.

## Why narrow typed tools and not one `run_sql` tool

Narrow tools are reliable and auditable but blind to anything not anticipated. That is the failure mode accepted
here: an unanticipated question gets "I can't answer that from this dashboard's data" plus the list of things it can
do, rather than a guessed join. In exchange, no query can silently return a wrong number, and each tool's definition
of "normal" or "at risk" is in one inspectable place.

## Tool table

| Tool | Kind | Input | Returns | Exists to answer | Deliberately does not | Failure mode |
|---|---|---|---|---|---|---|
| `get_briefing_summary` | Retrieval | none | headline lines, status counts, top findings | "Did anything go wrong yesterday?" | explain causes | none expected |
| `list_findings` | Discovery | none | top 5 findings with severity, rank reason, next step, evidence rows | "What needs my attention?" | list all findings | empty list if nothing crosses a threshold |
| `list_orders` | Retrieval | status, customer, stage, dueWithin, idleMin, sort | matching in-progress orders, each with its `orders.csv` line | "Which orders are late / at risk / stuck / waiting at X?" | search finished orders | empty list |
| `get_order` | Retrieval | order_id | one order or null | "What is the status of ORD-120?" | know finished orders | null, reply says it is finished or unknown |
| `trace_order` | Tracing | order_id | order, its stage queue, findings it belongs to, source row | "Why is it late / flagged?" | say what blocks an order (no reason codes in the data) | null for unknown order |
| `get_customer` | Retrieval | customer | orders by status, on-time rate over 60 days | "How is TrendCart doing?" | compare customers by revenue (none held) | null |
| `get_stage_output` | Judgement | stage or TOTAL, optional date | observed, usual, band, % vs usual, status, source rows | "Is output normal?" | explain why output moved | error text if the date is outside the 18 working days kept or history is too short |
| `get_pipeline` | Retrieval | none | orders, pieces, usual per day, days of work per stage | "Where is the bottleneck?" | forecast the queue | blank days for a stage with too little history |
| `get_on_time` | Retrieval | none | on-time rate now vs previous 30 days, with the orders behind it | "How is on-time delivery?" | split by customer | blank when nothing finished |
| `check_feasibility` | Judgement | pieces, due date, optional order to exclude | verdict, earliest and latest finish, per-stage table, assumptions | "Can we take 800 hoodies by the 25th?" | promise a date; model overtime or outsourcing | asks for pieces or date; says if the date has passed |
| `draft_chase` | Action | order_id | draft message plus a confirmation card | "Chase it up" | send anything unconfirmed | asks which order |
| `add_note` | Action | order_id, text | confirmation card; log entry on confirm | "Add a note to ORD-120" | change any order data | asks for the text |
| `create_watch` | Action | order, stage or reminder text, date | confirmation card; standing check on confirm | "Tell me if ORD-058 hasn't moved by Thursday" | watch what the briefing data cannot show | asks for order or date |
| `explain_no_data` | Refusal | topic | plain statement of what is not held | revenue, price, profit, worker, demand questions | estimate any of them | none |

**Blast radius of the action tools.** Each action shows a confirmation card with the worst case and logs after
confirming. `draft_chase`: one message to one colleague (in this demo nothing is sent, it is only logged).
`add_note`: a wrong line in the activity log. `create_watch`: one extra alert in a later briefing, removable from the
Watches panel. Nothing here can delete or change order data.

## Definitions the tools use

* **Normal output** (`get_stage_output`): mean of the previous 8 same-weekday working days, band = mean ± max(1.5 × SD, 5% of mean). Sundays are closed.
* **Late** = past due date. **At risk** = due within 7 days and projected to finish after it, or idle 5+ working days while later-due orders at the same stage moved. Otherwise on track.
* **Feasibility** (`check_feasibility`), per stage: days needed = work ahead of the order ÷ usual daily output, plus one working day of handoff for each later stage; the slowest stage sets the finish.
  * *Earlier date*: only in-progress orders due on or before the requested date go first, and nothing new arrives.
  * *Later date*: every in-progress order goes first, plus new orders expected to arrive due before this one. The arrival rate and the usual lead times come from the orders placed in the last 45 days.
  * Verdict: **likely** if the later date uses at most 85% of the working days available; **tight** if it fits; **possible only if prioritised** if only the earlier date fits; otherwise **unlikely**.
  * Queued pieces are counted in full even if partly done. All products are treated alike, because the production log has no product breakdown. No overtime, no workshop outsourcing.

## Validation of the feasibility estimate

The estimate was tested against the simulator by injecting a real extra order and recording when it actually finished
(14 cases: five start dates, 400 to 1,500 pieces, deadlines 16 to 75 days out).

* **First version** (existing orders only): the actual finish was inside its range in 5 of the 7 cases with deadlines up to 40 days out, and in none of the 7 cases with 60 to 75 day deadlines. For 6 of those 7 it said "likely" or "tight" for orders that finished in late July or later, because new orders with earlier due dates kept overtaking them. That is why the arrival model was added.
* **Current version**: the actual finish fell inside the estimated range in 14 of 14 cases, and in 14 of 14 the order finished after its due date, matching the "unlikely" / "possible only if prioritised" verdicts.
* **Limits of that evidence.** The simulator is not a real factory, and it was built by the same team. Every tested case was rated unlikely or only-if-prioritised, because the factory in this data carries about 50 working days of packing work; **no case rated "likely" or "tight" has been validated**. Treat those two verdicts as untested.

## Automated checks

`tests/test_chat.py` drives the real page in a headless browser: 40 checks covering retrieval numbers (compared with
the briefing JSON), tracing to rows, multi-turn memory, ambiguity ("which TrendCart order?"), refusals (revenue,
price, profit, workers, demand, cost), no invented causes, feasibility with missing or varied dates, confirmed
actions and logging, watches that fire from later data, and the drawer itself. They were written by the author of the
assistant, so they show it behaves as designed. They are **not** an independent accuracy measure. For the
evaluation set the brief asks for, add at least 30 questions written by someone who has not seen the code, include at
least 5 ambiguous, unanswerable or hallucination-bait questions and 5 feasibility or action requests, and report
first-pass accuracy.

## Using a real backend (optional, untested against your API)

Open the page with `?api=http://localhost:8000/api/chat`. Each question is then sent as

```json
{"message": "Why is ORD-120 late?", "business_date": "2026-04-09", "history": ["...last 8 user messages..."]}
```

and the page expects `{"reply": "text", "detail": "optional text", "sources": ["orders.csv line 76"], "tools": ["trace_order"]}`.
This is a proposed contract; change `send()` in `chat.js` to match your endpoint. Confirmation cards, watches and
suggested questions stay in the page. If the backend does not answer within 15 seconds, the built-in tools reply and
the chat says so. The page never holds an API key, so keep the key in the backend.

## Known limits

* Intent routing matches phrasings, not meaning. Unusual wording falls back to the help message.
* Watches are checked only when the page shows the morning concerned (replay or the date picker). In production a backend job must evaluate them and push the alert.
* Actions, watches and the activity log live in the page and are lost on reload. Nothing is sent anywhere.
* Only in-progress orders are held per morning: finished orders can be counted (on-time rate) but not looked up.
* "Read aloud" and the microphone depend on the browser's speech support.
