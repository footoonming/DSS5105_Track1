# Seed Dataset Dictionary

The three CSV files provide reproducible seed data for import and regression tests. Online
queries read committed MySQL records. Row counts below describe the seed files, not runtime
constraints. Nullable fields include completion details and workshop batch limits.

Database types, validation rules and column aliases are specified in [schema.yaml](dictionary/schema.yaml)
and [field_mapping.yaml](dictionary/field_mapping.yaml).

The dataset reference date is **2026-04-01**; production history covers the preceding 90 days.
The application uses its configured business clock; this reference date does not freeze runtime dates. The factory
is closed on Sundays. Garments move through four stages:
**KNITTING → ASSEMBLY → WASHING → PACKING**.

| File | Rows | One row is |
|---|---|---|
| `orders.csv` | 120 | One customer order |
| `production_log.csv` | 360 | One stage on one day |
| `workshops.csv` | 8 | One outside workshop's profile card |

## `orders.csv`

| Column | Meaning |
|---|---|
| `order_id` | `ORD-001` … |
| `customer`, `product` | Who ordered it and what it is |
| `category` | `TOPS` (sweaters, hoodies, …) or `ACCESSORIES` (beanies, scarves) |
| `pieces` | How many garments |
| `order_date`, `due_date` | When it was placed and when it is due |
| `status` | `COMPLETE` or `IN_PROGRESS` |
| `current_stage` | `KNITTING` / `ASSEMBLY` / `WASHING` / `PACKING` / `COMPLETE` |
| `last_activity_date` | The last day any work was recorded on this order |
| `completed_date` | When it finished (blank if still in progress) |
| `days_late` | `completed_date − due_date`; negative means early; blank if in progress |

## `production_log.csv`

Factory-wide daily output — the table behind *"how much did assembly get through yesterday,
and is that normal?"*

| Column | Meaning |
|---|---|
| `date` | The day |
| `stage` | One of the four stages |
| `pieces_completed` | Garments finished at that stage that day (0 on Sundays) |

## `workshops.csv`

Workshop profiles support capacity feasibility estimates. Availability, queue duration,
quality constraints and category compatibility must be considered before recommending outsourcing.

| Column | Meaning |
|---|---|
| `workshop_id`, `name` | `W1` … `W8` and a memorable name |
| `capacity_pieces_per_day` | How much it can process per day; work beyond this queues |
| `pickup_lead_days` | Fixed transport overhead per batch |
| `defect_rate` | Chance a batch comes back defective and is partly redone |
| `cost_per_piece` | What it charges |
| `makes` | `TOPS`, `ACCESSORIES`, or `TOPS+ACCESSORIES` — what it is equipped for |
| `status` | `ACTIVE`, or `SUSPENDED` (failed a quality audit — may not take new work) |
| `max_batch_pieces` | Per-batch cap (workshops on trial); blank means no cap |
| `current_queue_days` | Days of work it is already holding "today" |
| `notes` | The one-line reputation a human dispatcher would give it |
