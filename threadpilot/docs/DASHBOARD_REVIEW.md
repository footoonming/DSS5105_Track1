# Dashboard review: through the eyes of a fashion-retail CEO

The reviewer persona: the CEO of a large fashion-retail franchise who buys from this
factory and also sits over its general manager. They have two minutes between
meetings, they read on a phone as often as a laptop, and they think in customers,
delivery dates and exceptions, not in production stages or scoring rules.

## What did not work in the first version

| # | Problem | Why it matters to a CEO |
|---|---|---|
| 1 | No single answer to "are we OK?" | The page opened with prose, not a status. The first question is always "how many orders are late or about to be?" |
| 2 | Internal vocabulary | "Normal band", "priority 78", "rank score", "stage below normal". A CEO should never have to decode a metric. |
| 3 | No customer view | Retail runs on accounts. "Which customers are hurt this morning?" had no answer without reading every finding. |
| 4 | Findings were paragraphs | Each item was three lines of text before you knew what to do about it. |
| 5 | No next step, no button | The brief asks the co-pilot to get things done. The page described problems but gave no way to act on them. |
| 6 | Four small charts, no total | Hard to read at a glance; the total factory picture was missing. |
| 7 | Bottleneck invisible | The real story (work piling up at Assembly) was buried in one finding. |
| 8 | No trend on the headline numbers | "9 late" means nothing without "and it was 11 yesterday". |
| 9 | Colours were bespoke | Indigo and madder red on grey looked distinctive but did not follow the red/amber/green convention every executive already reads without thinking. |

## What changed

**Layout, top to bottom, in the order a CEO asks questions**

1. **Morning summary**: three lines labelled Yesterday / Top issue / Decide, then chips for what is new or cleared since yesterday.
2. **Order health**: one stacked bar, on track / at risk / late, plus on-time delivery over 30 days with the change against the previous 30. Each count is clickable and filters the order table.
3. **Five KPI tiles**: late orders, at risk, due in 7 days, output yesterday, on-time delivery. Each has a two-week sparkline and a change chip. Red always means worse, green always means better, whichever direction the number moved.
4. **Needs your attention**: at most five items, each with a severity pill (Critical / High / Watch), a one-line title, a plain next step, a Details button that expands the source rows, and one action button.
5. **Customers**: every account with its active orders as a status bar, and on-time delivery over 60 days. Clicking a customer shows only their orders.
6. **Daily output**: one larger chart with an All stages / per-stage switch, a usual range band, below-usual points in red, and the expected next six working days.
7. **Work in progress**: days of work queued at each stage, with the bottleneck named in a callout.
8. **Orders in progress**: delivery buckets (already late, 0-7 days, 8-14 days, later) that act as filters, plus search, status and customer filters, a plain-English "why" for each order, and a Chase button on every row.
9. **Activity log**: every confirmed action with its time.

**New functions**

- Status for every order (late / at risk / on track), with the reason in words. Computed in Python, not in the browser.
- Customer summary, pipeline and delivery outlook, also computed in Python and archived in each briefing JSON.
- On-time delivery rate, current and previous 30 days.
- Chase, Add note and Check feasibility actions. Each opens a confirmation dialog that shows the drafted message and states the worst case ("one unwanted message to one colleague"), then writes to the activity log. This is the brief's confirm-before, log-after rule made visible.
- Clickable KPIs, health counts, customers and delivery buckets, so every number leads to the orders behind it.
- Light and dark themes, following the device setting by default.
- Date picker, replay and read aloud kept from the first version.

**Colour system**

A neutral base with semantic status colours, the convention used by most current SaaS and BI dashboards (Linear, Stripe, Shopify Polaris, Untitled UI):

| Role | Light | Dark |
|---|---|---|
| Page / card | `#F5F6F8` / `#FFFFFF` | `#0E1117` / `#161B22` |
| Text | `#101828` | `#F2F4F7` |
| Primary buttons | near-black `#101828` | near-white `#F2F4F7` |
| Charts | blue `#2563EB` on `#DBEAFE` band | `#60A5FA` on `#1E3A5F` |
| On track | green `#12B76A` | `#32D583` |
| At risk | amber `#F79009` | `#FDB022` |
| Late / critical | red `#F04438` | `#F97066` |

Colour is only ever used to carry status. Everything else is black, white and grey,
which also suits a fashion-retail audience used to a monochrome brand look. Status is
never shown by colour alone: every pill and bar also has a word or a count.

The dashboard carries no retailer's name or logo; it is the factory's ThreadPilot tool.

## Still worth doing in the real app

- Port this layout into `frontend/` and have it read `GET /api/briefing?date=` instead of the embedded demo data.
- Wire the action buttons to the backend's confirmed-action endpoint and store the log server-side.
- Add a "My customers" saved filter for an executive who only follows three accounts.
- Email or push the three summary lines at 07:00, with a link to this page.
