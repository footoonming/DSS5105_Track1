/* ThreadPilot chat: a tool-calling assistant over the briefings embedded in this page.
 *
 * Default mode has no language model and no network. Questions are routed to small named
 * tools (see TOOLS below) that read the briefing JSON, and every number in an answer comes
 * from a tool. To use a real backend instead, open the page with ?api=http://localhost:8000/api/chat
 * (contract in docs/chat_tools.md); if the backend is unreachable the built-in tools answer.
 *
 * The planted scenario events are never read here: the assistant knows only what the
 * briefing data shows, so it cannot "explain" a cause the data does not contain.
 */
(() => {
"use strict";
const $c = s => document.querySelector(s);
const ST = ["KNITTING", "ASSEMBLY", "WASHING", "PACKING"];
const MON = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"];
const DOW = ["sunday", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday"];
const SW = {late: "late", at_risk: "at risk", on_track: "on track"};
const FEAS_SLACK = 0.85;           // "likely" needs the cautious estimate to use at most 85% of the days available

/* ---------- calendar helpers (Sundays closed) ---------- */
const iso = d => d.toISOString().slice(0, 10);
const D = s => new Date(s + "T12:00:00Z");
const plus = (s, k) => { const d = D(s); d.setUTCDate(d.getUTCDate() + k); return iso(d); };
const working = s => D(s).getUTCDay() !== 0;
const nextWork = s => { let d = plus(s, 1); while (!working(d)) d = plus(d, 1); return d; };
const workDaysIncl = (a, b) => { let c = 0; for (let d = a; d <= b; d = plus(d, 1)) if (working(d)) c++; return c; };
const kthWork = (a, k) => { let d = a, c = working(a) ? 1 : 0; while (c < k) { d = plus(d, 1); if (working(d)) c++; } return d; };
const sum = (xs, f) => xs.reduce((t, x) => t + f(x), 0);
const cur = () => B[idx];
const today = () => cur().business_date;
const day = s => fmt(s, {weekday: "short", day: "numeric", month: "short"});
const dlong = s => fmt(s, {weekday: "long", day: "numeric", month: "long"});
const pl = (k, w) => `${k} ${w}${k === 1 ? "" : "s"}`;
const trunc = (t, k = 110) => t.length > k ? t.slice(0, k - 1) + "…" : t;
const nowHM = () => new Date().toLocaleTimeString("en-GB", {hour: "2-digit", minute: "2-digit"});

/* ---------- parsing ---------- */
const MONRE = "(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*";
function mk(y, m, d) { const t = new Date(Date.UTC(y, m, d, 12)); return t.getUTCMonth() === m && t.getUTCDate() === d ? iso(t) : null; }
function parseDate(ql, ref, dir) {          // dir: "future" for deadlines, "past" for "what happened on Monday"
  let m;
  if ((m = ql.match(/\b20\d\d-\d\d-\d\d\b/))) return m[0];
  if (/\btoday\b/.test(ql)) return ref;
  if (/\btomorrow\b/.test(ql)) return plus(ref, 1);
  if (/\byesterday\b/.test(ql)) return plus(ref, -1);
  if ((m = ql.match(/\bin (\d+) (day|days|week|weeks)\b/))) return plus(ref, +m[1] * (m[2][0] === "w" ? 7 : 1));
  if (/\bnext week\b/.test(ql)) return plus(ref, 7);
  const r = D(ref), y = r.getUTCFullYear();
  const fix = (mo, dd) => { let c = mk(y, mo, dd); if (!c) return null;
    if (dir === "future" && c < ref) c = mk(y + 1, mo, dd); if (dir === "past" && c > ref) c = mk(y - 1, mo, dd); return c; };
  if ((m = ql.match(new RegExp("\\b(\\d{1,2})(?:st|nd|rd|th)?\\s+(?:of\\s+)?" + MONRE + "\\b")))) return fix(MON.indexOf(m[2]), +m[1]);
  if ((m = ql.match(new RegExp("\\b" + MONRE + "\\s+(\\d{1,2})(?:st|nd|rd|th)?\\b")))) return fix(MON.indexOf(m[1]), +m[2]);
  if ((m = ql.match(/\b(\d{1,2})(?:st|nd|rd|th)\b/)) || (m = ql.match(/\b(?:by|on|before)\s+(?:the\s+)?(\d{1,2})\b/))) {
    const dd = +m[1]; let mo = r.getUTCMonth(), yy = y, c = mk(yy, mo, dd);
    if (c && dir === "future" && c < ref) { mo++; if (mo > 11) { mo = 0; yy++; } c = mk(yy, mo, dd); }
    if (c && dir === "past" && c > ref) { mo--; if (mo < 0) { mo = 11; yy--; } c = mk(yy, mo, dd); }
    return c;
  }
  for (let i = 0; i < 7; i++) if (new RegExp("\\b" + DOW[i] + "\\b").test(ql)) {
    const rd = r.getUTCDay();
    return dir === "past" ? plus(ref, -(((rd - i + 7) % 7) || 7)) : plus(ref, ((i - rd + 7) % 7) || 7);
  }
  return null;
}
function parsePieces(ql) {
  let s = ql.replace(/\bord[-\s]?\d+\b/g, " ").replace(/\b20\d\d-\d\d-\d\d\b/g, " ").replace(/\b\d{1,2}(?:st|nd|rd|th)\b/g, " ")
    .replace(/\b(?:by|on|before)\s+(?:the\s+)?\d{1,2}\b/g, " ").replace(/\bin \d+ (?:days?|weeks?)\b/g, " ")
    .replace(new RegExp("\\b\\d{1,2}\\s+(?:of\\s+)?" + MONRE + "\\b", "g"), " ").replace(new RegExp("\\b" + MONRE + "\\s+\\d{1,2}\\b", "g"), " ");
  const m = s.match(/\b(\d{1,3}(?:,\d{3})+|\d+)(\s*k\b)?/);
  if (!m) return null;
  const v = parseInt(m[1].replace(/,/g, ""), 10) * (m[2] ? 1000 : 1);
  return v > 0 ? v : null;
}
const orderIds = ql => [...ql.matchAll(/\bord[-\s]?(\d{1,3})\b/g)].map(m => "ORD-" + m[1].padStart(3, "0"));
const stageOf = ql => /knit/.test(ql) ? "KNITTING" : /assembl/.test(ql) ? "ASSEMBLY" : /wash/.test(ql) ? "WASHING" : /pack/.test(ql) ? "PACKING" : null;
function customerOf(ql) {
  const flat = ql.replace(/[^a-z0-9]/g, ""), words = new Set(ql.split(/[^a-z0-9]+/));
  for (const c of cur().customers) {
    const nm = c.customer.toLowerCase(), key = nm.replace(/[^a-z0-9]/g, ""), first = nm.split(/[^a-z0-9]+/)[0];
    if (flat.includes(key) || (first.length > 3 && words.has(first))) return c;
  }
  return null;
}
function productOf(ql) {
  const prods = [...new Set(cur().orders.map(o => o.product.toLowerCase()))];
  return prods.find(p => ql.includes(p)) || null;
}

/* ---------- html helpers (callers escape cell content) ---------- */
const tbl = (head, rows) => `<div class="ctbl"><table><thead><tr>${head.map(h => `<th>${esc(h)}</th>`).join("")}</tr></thead><tbody>${rows.map(r => `<tr>${r.map(c => `<td>${c}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
const orderRows = xs => tbl(["Order", "Customer", "Stage", "Due", "Status", "Source"], xs.map(o => [
  `<b>${esc(o.order_id)}</b>`, esc(o.customer), esc(cap(o.stage)),
  o.days_to_due < 0 ? `${-o.days_to_due}d late` : esc(day(o.due_date)), esc(SW[o.status]), `orders.csv line ${o.row}`]));
const kv = pairs => tbl(["Field", "Value"], pairs.map(([k, v]) => [esc(k), v]));

/* ---------- state ---------- */
const ctx = {lastOrder: null, lastCustomer: null, lastStage: null, lastFeas: null, pending: null, last: null, excludeOrder: null};
const watches = [];
const ui = {open: false, unread: 0, speak: false, backend: new URLSearchParams(location.search).get("api"), seq: 0, resp: {}, lastIdx: null};

/* ---------- TOOLS: each has a stated purpose, limits and failure mode (also shown in the panel) ---------- */
const spec = (kind, answers, doesnt, fails) => ({kind, answers, doesnt, fails});
const T = {
  get_briefing_summary: {...spec("Retrieval", "What happened yesterday, what is at risk, what needs a decision.", "Explain causes; it reports what the data shows.", "None expected; reads the stored briefing."),
    run: () => { const b = cur(); return {headline: b.headline, counts: b.status_counts, findings: b.findings, more: b.more_findings, covers: b.covers}; }},
  list_findings: {...spec("Discovery", "The few things worth the manager's attention, ranked, each with its rank reason and next step.", "Show all findings; only the top five make the page.", "Returns an empty list when nothing crosses a threshold."),
    run: () => cur().findings},
  list_orders: {...spec("Retrieval", "Which in-progress orders match a status, customer, stage, due window or idle time.", "Search completed orders or orders on other dates.", "Empty list when nothing matches."),
    run: a => { let xs = cur().orders.slice();
      if (a.status) xs = xs.filter(o => o.status === a.status);
      if (a.customer) xs = xs.filter(o => o.customer === a.customer);
      if (a.stage) xs = xs.filter(o => o.stage === a.stage);
      if (a.dueWithin != null) xs = xs.filter(o => o.days_to_due >= 0 && o.days_to_due <= a.dueWithin);
      if (a.idleMin != null) xs = xs.filter(o => o.idle_days >= a.idleMin);
      if (a.sort === "due") xs.sort((p, q) => p.days_to_due - q.days_to_due);
      if (a.sort === "idle") xs.sort((p, q) => q.idle_days - p.idle_days);
      return xs; }},
  get_order: {...spec("Retrieval", "Status, due date, stage and projected finish of one order.", "Know about finished orders; this view holds in-progress orders only.", "Returns null for an unknown or finished order, and the assistant says so."),
    run: a => cur().orders.find(o => o.order_id === a.order_id) || null},
  trace_order: {...spec("Tracing", "Why an order is flagged: its reasons, the queue it sits in, the findings it belongs to, and its source row.", "Say what is blocking an order; the data has activity dates, not reason codes.", "Returns null for an unknown order."),
    run: a => { const o = cur().orders.find(x => x.order_id === a.order_id); if (!o) return null;
      return {order: o, queue: cur().pipeline.find(p => p.stage === o.stage), findings: cur().findings.filter(f => (f.order_ids || []).includes(o.order_id))}; }},
  get_customer: {...spec("Retrieval", "A customer's orders by status and on-time delivery over 60 days.", "Compare customers by revenue; no prices are held.", "Returns null for an unknown customer."),
    run: a => cur().customers.find(c => c.customer === a.customer) || null},
  get_stage_output: {...spec("Judgement", "Is a stage's (or the whole factory's) output normal on a given day? Normal is the average of the previous 8 same weekdays, with a band.", "Explain why output changed; the production log records pieces, not causes.", "Says so when there is not enough history, or the date is outside the 18 working days kept."),
    run: a => { const b = cur(), st = b.stages[a.stage];
      if (!a.date || a.date === b.covers) return {...st.yesterday, date: b.covers, stage: a.stage, evidence: st.yesterday.evidence};
      const h = st.history.find(x => x.date === a.date);
      if (!h) return {error: `I keep 18 working days of history in this view and ${day(a.date)} is not one of them (or the factory was closed).`};
      if (h.value == null || h.low == null) return {error: `There is not enough history to judge ${day(a.date)}.`};
      const pct = Math.round(1000 * (h.value - h.mean) / h.mean) / 10;
      return {date: a.date, stage: a.stage, observed: h.value, mean: h.mean, low: h.low, high: h.high, pct_vs_mean: pct, samples: 8,
              status: h.value < h.low ? "below" : h.value > h.high ? "above" : "normal",
              evidence: [{file: "production_log.csv", row: h.row, values: {date: a.date, stage: a.stage, pieces_completed: h.value}}]}; }},
  get_pipeline: {...spec("Retrieval", "Where the work is sitting: orders, pieces and days of work queued at each stage.", "Predict how the queue will change.", "Days of work is blank for a stage with too little history."),
    run: () => cur().pipeline},
  get_on_time: {...spec("Retrieval", "Share of orders finished in the last 30 days that were on time, versus the 30 days before.", "Break down by customer here (the customer table does that for 60 days).", "Percentage is blank when no orders finished in the window."),
    run: () => ({now: cur().on_time_30d, prev: cur().on_time_prev_30d})},
  check_feasibility: {...spec("Judgement", "Can a new order of N pieces be done by a date? Returns a range and the assumptions behind it.", "Promise a date; it is an estimate, never a yes. It also ignores overtime and workshop outsourcing.", "Asks for pieces or a date when missing; says the date has passed if it has."),
    run: a => { const b = cur(), start = b.business_date, W = workDaysIncl(start, a.due), arr = b.arrivals, CAP = 200;
      const act = b.orders.filter(o => o.order_id !== a.exclude), usual = Object.fromEntries(b.pipeline.map(p => [p.stage, p.usual_per_day]));
      if (ST.some(s => !usual[s])) return {error: "There is not enough production history to estimate capacity."};
      // share of newly arriving orders that would be due before this one (and so go ahead of it), from the usual lead times
      const share = x => x <= 0 ? 0 : arr.leads.filter(l => l < x).length / Math.max(1, arr.leads.length);
      const rate = arr.pieces_per_working_day;
      const rows = ST.map((s, i) => { const needs = act.filter(o => ST.indexOf(o.stage) <= i), handoff = ST.length - 1 - i, u = usual[s];
        const aheadBest = sum(needs.filter(o => o.due_date <= a.due), o => o.pieces), aheadCautious = sum(needs, o => o.pieces);
        // cautious: every queued order goes first, plus new orders that arrive with an earlier due date
        let work = aheadCautious + a.pieces, k = 0, d = plus(start, -1), daysCautious = Infinity, inflow = 0;
        while (k < CAP) { d = plus(d, 1); if (!working(d)) continue; k++;
          const add = rate * share((D(a.due) - D(d)) / 864e5); work += add; inflow += add; if (u * k >= work) { daysCautious = k + handoff; break; } }
        return {stage: s, usual: u, aheadBest, aheadCautious, inflow: Math.round(inflow), daysBest: (aheadBest + a.pieces) / u + handoff, daysCautious}; });
      const top = k => rows.reduce((m, r) => r[k] > m[k] ? r : m), tb = top("daysBest"), tc = top("daysCautious");
      const best = Math.ceil(tb.daysBest), cautious = Number.isFinite(tc.daysCautious) ? Math.ceil(tc.daysCautious) : null;
      const verdict = cautious != null && cautious <= W * FEAS_SLACK ? "likely" : cautious != null && cautious <= W ? "tight" : best <= W ? "only_if_prioritised" : "unlikely";
      return {pieces: a.pieces, due: a.due, start, W, rows, best, cautious, bestDate: kthWork(start, best), cautiousDate: cautious == null ? null : kthWork(start, cautious), cap: CAP,
              bottleneck: (cautious == null ? tc : tc).stage, bottleneckAhead: tc.aheadCautious, bottleneckUsual: tc.usual, rate, verdict}; }},
  draft_chase: {...spec("Action", "Drafts a chase-up message for one order. Nothing is sent without a confirmation.", "Send anything on its own. Worst case after confirmation: one message to one colleague.", "Asks which order when the target is unclear."),
    run: a => ({order: cur().orders.find(o => o.order_id === a.order_id)})},
  add_note: {...spec("Action", "Adds a note to the activity log for one order, after confirmation.", "Change any order data.", "Asks for the note text when it is missing."),
    run: a => a},
  create_watch: {...spec("Action", "Creates a standing check ('tell me if ORD-x has not moved by Thursday', 'remind me tomorrow if packing is still behind') that fires in a later briefing.", "Watch anything it cannot evaluate from the briefing data; checks run once per morning, not continuously.", "Asks for the order or date when missing."),
    run: a => a},
  explain_no_data: {...spec("Refusal", "Says plainly that this system holds no prices, revenue, profit or worker data.", "Estimate those figures; it never invents one.", "None."),
    run: a => a},
};

/* ---------- response builder ---------- */
const R = (intent, lines, o = {}) => ({intent, lines, detail: o.detail || null, sources: o.sources || [], chips: o.chips || [],
  confirm: o.confirm || null, refused: !!o.refused, asks: !!o.asks, tools: [], assumptions: o.assumptions || null});
const chip = (label, q) => ({label, q: q || label});
const notFound = id => R("not_found", [`${id} is not in progress on ${day(today())}.`, "It has either finished or does not exist; this view holds in-progress orders only."]);
const worstOrder = () => cur().orders.find(o => o.status === "late") || cur().orders.find(o => o.status === "at_risk") || cur().orders[0];

function logAction(what, detail) { log.unshift({time: nowHM(), what, detail}); renderLog(); }

/* ---------- answer builders ---------- */
function summaryAnswer(call) {
  const s = call("get_briefing_summary", {}), b = cur();
  const strip = (l, re) => l.replace(re, "");
  const lines = [strip(s.headline[0], /^(Yesterday|Last working day) \([^)]*\): /), s.headline[1], strip(s.headline[2], /^Decide today: /)];
  lines[0] = `${day(s.covers)}: ${lines[0]}`;
  return R("summary", lines, {
    detail: tbl(["Rank", "Severity", "Finding", "Next step"], s.findings.map((f, i) => [i + 1, esc(cap(f.severity)), esc(f.title), esc(f.next_step)])) +
      kv([["Late", String(s.counts.late)], ["At risk", String(s.counts.at_risk)], ["On track", String(s.counts.on_track)]]),
    sources: ["Morning briefing for " + day(today()) + ": orders.csv and production_log.csv up to " + day(s.covers)],
    chips: s.findings.slice(0, 2).map((f, i) => chip(`Finding ${i + 1}: ${trunc(f.title, 38)}`, `Tell me more about finding ${i + 1}`))});
}
function findingAnswer(k, call) {
  const f = call("list_findings", {})[k - 1];
  if (!f) return R("finding", [`There is no finding ${k} this morning; there are ${cur().findings.length}.`]);
  if (f.order_ids && f.order_ids.length === 1) ctx.lastOrder = f.order_ids[0];
  const cols = [...new Set(f.evidence.flatMap(e => Object.keys(e.values)))];
  return R("finding", [f.title + ".", `Next step: ${f.next_step}. Rank score ${f.rank_score} (${f.rank_reason}).`], {
    detail: `<p class="cnote">${esc(f.detail)}</p>` + tbl(["Source", ...cols.map(c => c.replace(/_/g, " "))], f.evidence.map(e => [`${esc(e.file)} line ${e.row}`, ...cols.map(c => esc(e.values[c] ?? ""))])),
    sources: [...new Set(f.evidence.map(e => `${e.file} line ${e.row}`))].slice(0, 12),
    chips: f.order_ids && f.order_ids.length === 1 ? [chip(`Chase ${f.order_ids[0]}`)] : []});
}
function attentionAnswer(call) {
  const fs = call("list_findings", {});
  if (!fs.length) return R("attention", ["Nothing crosses an alert threshold this morning."]);
  return R("attention", [`${pl(fs.length, "thing")} need${fs.length === 1 ? "s" : ""} your attention${cur().more_findings ? `, plus ${cur().more_findings} lower-priority` : ""}.`,
      ...fs.slice(0, 2).map((f, i) => `${i + 1}. ${f.title}. Next: ${f.next_step.toLowerCase()}.`)], {
    detail: tbl(["Rank", "Severity", "Finding", "Why it ranks here"], fs.map((f, i) => [i + 1, esc(cap(f.severity)), esc(f.title), esc(f.rank_reason)])),
    chips: fs.slice(0, 3).map((f, i) => chip(`Finding ${i + 1}`, `Tell me more about finding ${i + 1}`))});
}
function orderAnswer(id, call) {
  const o = call("get_order", {order_id: id}); if (!o) return notFound(id);
  Object.assign(ctx, {lastOrder: id, lastCustomer: o.customer, lastStage: o.stage});
  const head = `${o.order_id} (${o.customer}, ${n(o.pieces)} ${o.product.toLowerCase()})`;
  const l1 = o.status === "late" ? `${head} is late: ${-o.days_to_due} days past its ${day(o.due_date)} due date, still at ${cap(o.stage)}.`
    : o.status === "at_risk" ? `${head} is at risk: ${o.reasons[0] || "it may miss its due date"}.`
    : `${head} is on track: due ${day(o.due_date)} (${o.days_to_due} days), at ${cap(o.stage)}.`;
  const l2 = `${o.idle_days ? `Last activity ${pl(o.idle_days, "working day")} ago` : "It moved yesterday"}; projected finish ${day(o.projected_finish)}.`;
  return R("order_status", [l1, l2], {detail: orderRows([o]), sources: [`orders.csv line ${o.row} (${o.order_id})`],
    chips: [chip("Why?", `Why is ${o.order_id} ${o.status === "late" ? "late" : "flagged"}?`), chip(`Chase ${o.order_id}`), chip("Watch it for 2 days", `Tell me if ${o.order_id} hasn't moved by ${kthWork(today(), 3)}`)]});
}
function traceAnswer(id, call) {
  const t = call("trace_order", {order_id: id}); if (!t) return notFound(id);
  const o = t.order, q = t.queue; Object.assign(ctx, {lastOrder: id, lastCustomer: o.customer, lastStage: o.stage});
  const l1 = `${o.order_id} is ${SW[o.status]}${o.reasons.length ? ": " + o.reasons.join("; ") : ": nothing in the data flags it"}.`;
  const l2 = `It is at ${cap(o.stage)} (stage ${ST.indexOf(o.stage) + 1} of 4), where ${pl(q.orders, "order")} and ${n(q.pieces)} pieces are queued${q.days_of_work ? `, about ${q.days_of_work} days of work` : ""}.`;
  const l3 = o.idle_days >= 5 ? "The data records activity dates, not reasons, so I cannot say what is blocking it."
    : t.findings.length ? `It is part of: ${t.findings[0].title}.` : null;
  return R("trace_order", [l1, l2, l3].filter(Boolean), {
    detail: kv([["Source row", `orders.csv line ${o.row}`], ["Customer", esc(o.customer)], ["Quantity", `${n(o.pieces)} ${esc(o.product.toLowerCase())}`], ["Ordered", esc(day(o.order_date))],
      ["Due", `${esc(day(o.due_date))} (${o.days_to_due < 0 ? -o.days_to_due + " days late" : o.days_to_due + " days"})`], ["Current stage", esc(cap(o.stage))],
      ["Last activity", `${esc(day(o.last_activity))} (${o.idle_days} working days idle)`], ["Projected finish", esc(day(o.projected_finish))], ["Priority score", String(o.priority)]]),
    sources: [`orders.csv line ${o.row} (${o.order_id})`, `Queue at ${cap(o.stage)}: in-progress orders at that stage in orders.csv`],
    chips: [chip(`Chase ${o.order_id}`), chip(`Show the ${cap(o.stage)} queue`, `Which orders are waiting at ${o.stage.toLowerCase()}?`)]});
}
function askWhichOrder(c, then, call, extra) {
  const xs = call("list_orders", {customer: c.customer, sort: "due"});
  ctx.pending = {type: "order", then, customer: c, extra};
  return R("clarify_order", [`${c.customer} has ${pl(xs.length, "order")} in progress. Which one do you mean?`], {asks: true,
    chips: [...xs.slice(0, 6).map(o => chip(`${o.order_id} · ${n(o.pieces)} ${o.product.toLowerCase()} · ${o.status === "late" ? -o.days_to_due + "d late" : SW[o.status]}`, o.order_id)),
            chip(`All ${c.customer} orders`, `How are all ${c.customer} orders doing?`)]});
}
function customerAnswer(c, call) {
  ctx.lastCustomer = c.customer;
  const xs = call("list_orders", {customer: c.customer, sort: "due"}), cc = call("get_customer", {customer: c.customer});
  if (!xs.length) return R("customer", [`${c.customer} has no orders in progress on ${day(today())}.`]);
  const parts = [cc.late && `${cc.late} late`, cc.at_risk && `${cc.at_risk} at risk`, cc.on_track && `${cc.on_track} on track`].filter(Boolean).join(", ");
  const lines = [`${c.customer} has ${pl(cc.active, "order")} in progress: ${parts}.`];
  if (cc.stalled) lines.push("All of them have stopped moving.");
  lines.push(cc.otd_60d != null ? `On-time delivery over the last 60 days: ${cc.otd_60d}%.` : "No orders finished in the last 60 days.");
  const worst = xs[0];
  return R("customer", lines, {detail: orderRows(xs), sources: [...new Set(xs.map(o => `orders.csv line ${o.row} (${o.order_id})`))],
    chips: [chip(`Why is ${worst.order_id} ${worst.status === "late" ? "late" : "flagged"}?`), chip(`Chase ${worst.order_id}`)]});
}
function customersAnswer() {
  const cs = cur().customers.filter(c => c.late || c.at_risk || c.stalled).slice(0, 3);
  if (!cs.length) return R("customers", ["No customer has late or at-risk orders this morning."]);
  return R("customers", [`${pl(cs.length, "customer")} most affected this morning:`, ...cs.map(c => `${c.customer}: ${c.late} late, ${c.at_risk} at risk${c.stalled ? ", all orders stalled" : ""}.`)], {
    detail: tbl(["Customer", "Active", "Late", "At risk", "On time, 60 days"], cur().customers.map(c => [esc(c.customer), c.active, c.late, c.at_risk, c.otd_60d == null ? "–" : c.otd_60d + "%"])),
    sources: ["orders.csv, in-progress rows grouped by customer"], chips: cs.slice(0, 2).map(c => chip(`How is ${c.customer} doing?`))});
}
function listAnswer(intent, label, xs, sourcesNote) {
  if (!xs.length) return R(intent, [`No orders are ${label} this morning.`]);
  const top = xs.slice(0, 3).map(o => `${o.order_id} (${o.customer}${o.days_to_due < 0 ? `, ${-o.days_to_due}d late` : `, due ${day(o.due_date)}`})`).join(", ");
  return R(intent, [`${pl(xs.length, "order")} ${xs.length === 1 ? "is" : "are"} ${label}.`, `Most urgent: ${top}.`], {
    detail: orderRows(xs), sources: [...new Set(xs.map(o => `orders.csv line ${o.row} (${o.order_id})`))].slice(0, 15),
    chips: [chip(`Why is ${xs[0].order_id} ${xs[0].status === "late" ? "late" : "flagged"}?`), chip(`Chase ${xs[0].order_id}`)]});
}
function stageAnswer(stage, ql, call, why) {
  const date = parseDate(ql, today(), "past"), r = call("get_stage_output", {stage, date: date && date !== cur().covers ? date : null});
  if (r.error) return R("stage_output", [r.error]);
  const name = stage === "TOTAL" ? "The factory" : cap(stage); ctx.lastStage = stage === "TOTAL" ? null : stage;
  const l1 = r.status === "normal" ? `${name} made ${n(r.observed)} pieces on ${day(r.date)}, within its usual range of ${n(Math.round(r.low))} to ${n(Math.round(r.high))}.`
    : `${name} made ${n(r.observed)} pieces on ${day(r.date)}: ${Math.abs(r.pct_vs_mean)}% ${r.status} its usual ${n(Math.round(r.mean))}.`;
  const lines = [l1];
  lines.push(why ? "The production log records output, not causes, so I cannot say why." : `Usual is the average of the previous ${r.samples} same weekdays; Sundays are closed.`);
  if (r.status === "below" && stage !== "TOTAL" && ST.indexOf(stage) > 0 && r.date === cur().covers) {
    const up = ST[ST.indexOf(stage) - 1];
    if (cur().stages[up].yesterday.status === "below") lines.push(`${cap(up)}, upstream, was also below usual, so this stage may be short of work.`);
  }
  let detail;
  if (stage === "TOTAL") {
    detail = tbl(["Stage", "Pieces", "Usual", "Source"], ST.map(s => { const y = cur().stages[s].yesterday, e = y.evidence[0];
      return [esc(cap(s)), n(y.observed), n(Math.round(y.mean)), `production_log.csv line ${e.row}`]; }));
  } else {
    detail = tbl(["Source", "Date", "Pieces", "Role"], r.evidence.map((e, i) => [`${esc(e.file)} line ${e.row}`, esc(day(e.values.date)), n(e.values.pieces_completed), i === 0 ? "the day asked about" : "usual baseline"]));
  }
  const srcs = stage === "TOTAL" ? ST.map(s => `production_log.csv line ${cur().stages[s].yesterday.evidence[0].row} (${cap(s)})`) : r.evidence.map(e => `${e.file} line ${e.row}`);
  return R("stage_output", lines, {detail, sources: srcs, chips: stage === "TOTAL" ? [chip("Where is the bottleneck?")] : [chip(`Which orders are waiting at ${cap(stage)}?`)]});
}
function stagesBelowAnswer(ql, call) {   // "how was output yesterday" with no stage named
  const a = stageAnswer("TOTAL", ql, call, false);
  const below = ST.filter(s => cur().stages[s].yesterday.status === "below").map(cap);
  if (a.lines.length && below.length && !/error|keep 18/.test(a.lines[0])) a.lines.splice(1, 0, `Below usual: ${below.join(", ")}.`);
  return a;
}
function pipelineAnswer(call) {
  const p = call("get_pipeline", {}), hot = p.reduce((m, s) => (s.days_of_work || 0) > (m.days_of_work || 0) ? s : m);
  if (!hot.days_of_work) return R("pipeline", ["There is not enough history to size the queues."]);
  return R("pipeline", [`${cap(hot.stage)} is the bottleneck: ${n(hot.pieces)} pieces queued, about ${hot.days_of_work} days of work at its usual ${n(hot.usual_per_day)} a day.`,
      `${pl(hot.orders, "order")} are waiting there${hot.late ? `, ${hot.late} already late` : ""}.`], {
    detail: tbl(["Stage", "Orders", "Pieces", "Usual per day", "Days of work"], p.map(s => [esc(cap(s.stage)), s.orders, n(s.pieces), n(s.usual_per_day), s.days_of_work ?? "–"])),
    sources: ["orders.csv: pieces of in-progress orders at each stage; production_log.csv: usual output"], chips: [chip(`Which orders are waiting at ${cap(hot.stage)}?`, `Which orders are waiting at ${hot.stage.toLowerCase()}?`)]});
}
function onTimeAnswer(call) {
  const {now, prev} = call("get_on_time", {});
  if (now.pct == null) return R("on_time", ["No orders finished in the last 30 days, so there is no rate to report."]);
  const d = prev.pct != null ? now.pct - prev.pct : null;
  return R("on_time", [`On-time delivery was ${now.pct}% over the last 30 days (${now.on_time} of ${now.completed} orders).`,
      d == null ? "There is no earlier window to compare with." : `${d === 0 ? "No change" : Math.abs(d) + " points " + (d < 0 ? "down" : "up")} on the 30 days before (${prev.pct}%).`], {
    detail: tbl(["Order", "Customer", "Finished", "Days late", "Source"], now.orders.map(o => [esc(o.order_id), esc(o.customer), esc(day(o.completed_date)), o.days_late <= 0 ? "on time" : o.days_late, `orders.csv line ${o.row}`])),
    sources: [`${now.completed} completed rows in orders.csv (completed_date in the last 30 days)`]});
}

/* ---------- feasibility ---------- */
const VERDICT = {likely: "Likely feasible", tight: "Feasible but tight", only_if_prioritised: "Possible only if it is prioritised", unlikely: "Unlikely"};
function feasAnswer(pieces, due, call, excl, productWord) {
  if (due < today()) return R("feasibility", [`${day(due)} has already passed; the briefing is for ${day(today())}.`]);
  const f = call("check_feasibility", {pieces, due, exclude: excl}); if (f.error) return R("feasibility", [f.error]);
  ctx.lastFeas = {pieces, due, product: productWord};
  const l1 = f.cautiousDate ? `${VERDICT[f.verdict]} by ${day(due)}: I estimate it finishes between ${day(f.bestDate)} and ${day(f.cautiousDate)}, with ${pl(f.W, "working day")} available.`
    : `${VERDICT[f.verdict]} by ${day(due)}: at best it finishes around ${day(f.bestDate)}, and if new orders keep arriving ahead of it, it may not finish within ${f.cap} working days. ${pl(f.W, "Working day")} are available.`;
  const l2 = `Bottleneck: ${cap(f.bottleneck)}, with ${n(f.bottleneckAhead)} pieces already queued at a usual ${n(f.bottleneckUsual)} a day.`;
  const assumptions = [
    "Capacity is each stage's usual daily output (average of the previous 8 same weekdays); no overtime.",
    "Sundays are closed. Each later stage adds one working day of handoff.",
    "Earlier date = only in-progress orders due on or before your date go first, and nothing new arrives. Later date = every in-progress order goes first.",
    "Pieces already queued are counted in full, even if partly done, so the estimate leans cautious.",
    `Later date also assumes new work keeps arriving at about ${n(Math.round(f.rate))} pieces a working day (average of the last ${cur().arrivals.window_days} days), with the usual lead times; new orders due earlier than this one go ahead of it.`,
    "All products are treated alike: the production log has no product breakdown, so the product does not change the answer.",
    "Workshop outsourcing is not included. 'Likely' means the cautious estimate uses at most 85% of the days available.",
    ...(excl ? [`${excl} is excluded from the queue because it is the order being checked.`] : [])];
  const dd = plus(due, 7);
  return R("feasibility", [l1, l2, "This is an estimate with assumptions, not a commitment."], {assumptions,
    detail: tbl(["Stage", "Usual per day", "Queued ahead (earlier / later)", "Days needed (earlier / later)"], f.rows.map(r => [esc(cap(r.stage)), n(r.usual), `${n(r.aheadBest)} / ${n(r.aheadCautious)}${r.inflow ? ` + ${n(r.inflow)} new` : ""}`, `${r.daysBest.toFixed(1)} / ${Number.isFinite(r.daysCautious) ? r.daysCautious.toFixed(1) : "over " + f.cap}`])) +
      `<ul class="cassume">${assumptions.map(a => `<li>${esc(a)}</li>`).join("")}</ul>`,
    sources: ["orders.csv: in-progress pieces by stage and due date", "production_log.csv: usual output per stage (previous 8 same weekdays)"],
    chips: [chip(`What if it is due ${day(dd)}?`, `What if the due date is ${dd}`), chip(`What about ${n(Math.round(pieces / 2))} pieces?`, `What about ${Math.round(pieces / 2)} pieces`), chip(`Where is the bottleneck?`)]});
}
function feasRoute(text, ql, call) {
  const exclude = ctx.excludeOrder; ctx.excludeOrder = null;
  const rerun = /\b(what if|what about|and (?:by|for)|how about)\b/.test(ql) && ctx.lastFeas;
  let pieces = parsePieces(ql), due = parseDate(ql, today(), "future"), prod = productOf(ql);
  if (rerun) { pieces = pieces || ctx.lastFeas.pieces; due = due || ctx.lastFeas.due; prod = prod || ctx.lastFeas.product; }
  if (!pieces) { ctx.pending = {type: "feas", pieces: null, due, exclude}; return R("clarify_feasibility", ["How many pieces is the order?"], {asks: true}); }
  if (!due) { ctx.pending = {type: "feas", pieces, due: null, exclude}; return R("clarify_feasibility", [`${n(pieces)} pieces: by what date does the customer need them?`], {asks: true}); }
  return feasAnswer(pieces, due, call, exclude, prod);
}

/* ---------- actions and watches ---------- */
function chaseProposal(id, call) {
  const o = call("draft_chase", {order_id: id}).order; if (!o) return notFound(id);
  Object.assign(ctx, {lastOrder: id, lastCustomer: o.customer, lastStage: o.stage});
  const about = `${o.order_id} (${o.customer}, ${n(o.pieces)} ${o.product.toLowerCase()}), currently at ${cap(o.stage)}, due ${day(o.due_date)}`;
  const msg = `Hi, can you give me an update on ${about}? ${o.reasons.length ? "Flagged this morning: " + o.reasons.join("; ") + ". " : ""}Please reply with a firm finish date by 12:00 today. Thanks.`;
  return R("chase_draft", [`Here is a chase-up for ${o.order_id}. Nothing is sent until you confirm.`], {confirm: {
    kind: "chase", title: `Chase ${o.order_id}`, select: {key: "to", label: "To", value: "Production planner", options: ["Production planner", `${cap(o.stage)} supervisor`, "Account manager"]},
    editable: {key: "message", label: "Message", value: msg}, blast: "Worst case: one unwanted message to one colleague, which this confirmation step prevents. In this demo nothing is sent; it is only logged.",
    apply: v => { logAction(`Chase-up sent about ${o.order_id}`, `To ${v.to}: ${trunc(v.message)}`); return `Logged at ${nowHM()}. In this demo nothing was actually sent.`; }}});
}
function noteProposal(id, text, call) {
  const o = call("add_note", {order_id: id}) && cur().orders.find(x => x.order_id === id); if (!o) return notFound(id);
  ctx.lastOrder = id;
  return R("note_draft", [`Here is the note for ${id}. It is saved only when you confirm.`], {confirm: {
    kind: "note", title: `Add a note to ${id}`, editable: {key: "message", label: "Note", value: text}, blast: "Worst case: a wrong note in the activity log. It changes no order data.",
    apply: v => { logAction(`Note added to ${id}`, v.message); return `Saved to the activity log at ${nowHM()}.`; }}});
}
function watchProposal(w, call) {
  call("create_watch", {kind: w.kind});
  const when = `${dlong(w.trigger)}'s 07:00 briefing (data to ${day(plus(w.trigger, -1))})`;
  const cond = w.kind === "no_move" ? `${w.order_id} has had no activity since ${day(w.last_activity)}` : w.kind === "stage_behind" ? `${cap(w.stage)} output is still below its usual range` : w.text;
  return R("watch_draft", [w.kind === "plain" ? `I can remind you in ${when}.` : `I can check this in ${when}.`], {confirm: {
    kind: "watch", title: w.kind === "plain" ? "Set a reminder" : "Create a standing check", fields: [{label: "Condition", value: cond}, {label: "Checked in", value: when}],
    blast: "Worst case: one extra alert in a later briefing. You can remove it from Watches at any time. It is checked once each morning, not continuously.",
    apply: () => { watches.push({...w, id: ++ui.seq, created_idx: idx, state: "active", result: null}); logAction(w.kind === "plain" ? "Reminder set" : "Watch created", `${cond}; checked ${day(w.trigger)}`);
      return `Done. I will raise it in the briefing for ${day(w.trigger)}.`; }}});
}
function watchRoute(text, ql, call, isRemind) {
  const ids = orderIds(ql), pron = /\b(it|that one|that order|this one)\b/.test(ql);
  const stage = stageOf(ql), id = ids[0] || (pron ? ctx.lastOrder : null);
  let trig = parseDate(ql, today(), "future");
  if (/\btomorrow\b/.test(ql)) trig = nextWork(today());
  if (trig && !working(trig)) trig = nextWork(trig);
  if (isRemind && stage && /\b(behind|below|slow|low|still|not caught up|short)\b/.test(ql)) {
    if (!trig) trig = nextWork(today());
    return watchProposal({kind: "stage_behind", stage, trigger: trig, text: `${cap(stage)} still behind`}, call);
  }
  if (isRemind && !id) {
    if (!trig) { ctx.pending = {type: "watch", w: {kind: "plain", text: text.replace(/^\s*remind me\s*/i, "")}}; return R("clarify_watch", ["When should I remind you?"], {asks: true}); }
    return watchProposal({kind: "plain", trigger: trig, text: `Reminder: ${text.replace(/^\s*remind me\s*(?:to\s*)?/i, "")}`}, call);
  }
  if (!id) return R("clarify_watch", ["Which order should I watch?"], {asks: true, chips: cur().orders.filter(o => o.status !== "on_track").slice(0, 4).map(o => chip(`Watch ${o.order_id}`, `Tell me if ${o.order_id} hasn't moved by ${kthWork(today(), 3)}`))});
  const o = cur().orders.find(x => x.order_id === id); if (!o) return notFound(id);
  if (!trig) { ctx.pending = {type: "watch", w: {kind: "no_move", order_id: id, last_activity: o.last_activity, stage_at_create: o.stage}}; return R("clarify_watch", [`Watch ${id} until when? For example "by Friday".`], {asks: true}); }
  if (trig <= today()) return R("watch_draft", [`${day(trig)} is not in the future; the briefing is for ${day(today())}.`]);
  ctx.lastOrder = id;
  return watchProposal({kind: "no_move", order_id: id, last_activity: o.last_activity, stage_at_create: o.stage, trigger: trig, text: `Watch ${id}`}, call);
}
function evaluateWatches() {
  const tIdx = w => B.findIndex(x => x.business_date >= w.trigger);
  for (const w of watches) {
    if (idx <= w.created_idx) { w.state = "active"; w.result = null; continue; }      // time rewound: the check has not happened yet
    const ti = tIdx(w); if (w.state !== "active" || ti < 0 || idx < ti) continue;
    const tb = B[ti]; let fire = false, msg = "";
    if (w.kind === "no_move") {
      const o = tb.orders.find(x => x.order_id === w.order_id);
      if (!o) msg = `${w.order_id} has finished, so the watch is cleared.`;
      else if (o.last_activity <= w.last_activity) { fire = true; msg = `${w.order_id} has not moved since ${day(o.last_activity)}: ${pl(o.idle_days, "working day")} idle, still at ${cap(o.stage)}.`; }
      else msg = `${w.order_id} moved on ${day(o.last_activity)}, so no alert is needed.`;
    } else if (w.kind === "stage_behind") {
      const y = tb.stages[w.stage].yesterday;
      if (y.status === "below") { fire = true; msg = `${cap(w.stage)} is still below usual: ${n(y.observed)} pieces, ${Math.abs(y.pct_vs_mean)}% under its usual ${n(Math.round(y.mean))}.`; }
      else msg = `${cap(w.stage)} is back within its usual range (${n(y.observed)} pieces), so no reminder is needed.`;
    } else { fire = true; msg = w.text; }
    w.state = fire ? "fired" : "cleared"; w.result = msg;
    const r = R("watch_result", [`${fire ? "Alert" : "Watch cleared"}: ${msg}`], {chips: fire && w.order_id ? [chip(`Why is ${w.order_id} stuck?`, `Why is ${w.order_id} flagged?`), chip(`Chase ${w.order_id}`)] : []});
    r.tools = [{name: "create_watch", args: {id: w.id, evaluated: tb.business_date}}]; r.proactive = true;
    addBot(r); if (fire) toast("Watch fired: " + trunc(msg, 60)); logAction(fire ? "Watch fired" : "Watch cleared", msg);
  }
}

/* ---------- refusals ---------- */
const NO_PRICE = /\b(price|prices|pricing|revenue|profit|margin|sales|income|turnover|earn|earnings|money|invoice|paid|payment|budget|worth)\b|how much (?:does|do|did|is|are).*\b(cost|sell|make)\b/;
const NO_PEOPLE = /\b(worker|workers|employee|employees|operator|operators|staff|headcount|salary|wages?|who (?:is|was|are|were) (?:working|on shift)|who works|shift|overtime hours)\b/;
const NO_FORECAST = /\b(forecast|predict|projection|next month|next quarter|next year|demand|trend of orders)\b/;
function refusalRoute(ql, call) {
  let why = null, alt = [chip("Did anything go wrong yesterday?"), chip("Where is the bottleneck?")];
  if (NO_PRICE.test(ql)) why = "This system holds no prices, revenue or profit. Orders have pieces, dates and stages only, so any figure would be invented.";
  else if (/\bcost\b/.test(ql)) why = "This system holds no prices or revenue. The source data has a cost per piece for each workshop, but it is not loaded into this view.";
  else if (NO_PEOPLE.test(ql)) why = "No worker names or staffing data are held. Output is recorded per stage per day, not per person.";
  else if (NO_FORECAST.test(ql)) { why = "There is no demand forecast in this view, so I will not guess at future volumes."; alt = [chip("Can we take 800 hoodies by the 25th?", `Can we take 800 hoodies by ${plus(today(), 16)}?`), chip("How was output yesterday?")]; }
  if (!why) return null;
  call("explain_no_data", {topic: why.slice(0, 20)});
  return R("no_data", [why, "I would rather say so than give you a made-up number."], {refused: true, chips: alt});
}

/* ---------- pending clarifications ---------- */
function finishOrderIntent(then, id, call, extra) {
  return then === "why" ? traceAnswer(id, call) : then === "chase" ? chaseProposal(id, call) : then === "watch" ? watchRoute(`tell me if ${id} hasn't moved by ${extra || ""}`.trim(), `tell me if ${id.toLowerCase()} hasn't moved by ${extra || ""}`.trim(), call, false)
    : then === "note" ? noteProposal(id, extra || "", call) : orderAnswer(id, call);
}
function resolvePending(text, ql, call) {
  const p = ctx.pending;
  if (/^(cancel|never ?mind|forget it|stop|no)\.?$/.test(ql)) { ctx.pending = null; return R("cancelled", ["Okay, cancelled."]); }
  if (p.type === "order") {
    const id = orderIds(ql)[0] || (/^\d{1,3}$/.test(ql) ? "ORD-" + ql.padStart(3, "0") : null);
    const spare = ql.replace(/\bord[-\s]?\d+\b/g, " ").split(/\s+/).filter(Boolean).length;   // "ORD-020 please" answers; "chase ORD-120 now" is a new request
    if (/\ball\b/.test(ql) && p.customer && spare <= 4) { ctx.pending = null; return customerAnswer(p.customer, call); }
    const command = /\b(chase|follow|nudge|escalate|why|how|what|which|watch|remind|note|tell|show|add|can we)\b/.test(ql);
    if (id && spare <= 2 && !command) { ctx.pending = null; return finishOrderIntent(p.then, id, call, p.extra); }
  } else if (p.type === "feas") {
    const pieces = p.pieces || parsePieces(ql), due = p.due || parseDate(ql, today(), "future");
    if (pieces && due) { ctx.pending = null; return feasAnswer(pieces, due, call, p.exclude, productOf(ql)); }
    if (pieces !== p.pieces || due !== p.due) { ctx.pending = {...p, pieces, due};
      return R("clarify_feasibility", [pieces ? `${n(pieces)} pieces: by what date?` : "How many pieces?"], {asks: true}); }
  } else if (p.type === "watch") {
    const trig0 = parseDate(ql, today(), "future"); let trig = /\btomorrow\b/.test(ql) ? nextWork(today()) : trig0;
    if (trig) { if (!working(trig)) trig = nextWork(trig); ctx.pending = null; return watchProposal({...p.w, trigger: trig, text: p.w.text || `Watch ${p.w.order_id}`}, call); }
  } else if (p.type === "note") {
    ctx.pending = null;
    if (!/\?\s*$|^(why|how|what|which|who|when|can|chase|tell|show|remind|watch)\b/.test(ql)) return noteProposal(p.id, text, call);
  }
  ctx.pending = null; return null;            // not an answer to the question: treat it as a fresh one
}

/* ---------- routing ---------- */
function helpAnswer(first) {
  const w = worstOrder();
  return R(first ? "greeting" : "fallback", first ? ["Good morning. Ask me about orders, customers, output, or whether we can take a new order.", "I show the rows behind every number, and I confirm before I do anything."]
    : ["I can't answer that from this dashboard's data.", "I can answer questions about orders, customers, stage output, the morning briefing, feasibility of a new order, and I can draft chase-ups, notes and watches."], {
    chips: [chip("Did anything go wrong yesterday?"), chip(`Why is ${w.order_id} ${w.status === "late" ? "late" : "flagged"}?`), chip("Where is the bottleneck?")]});
}
function route(text, ql, call) {
  if (!ql) return helpAnswer(false);
  if (/^(hi|hello|hey|good morning|morning|help|what can you do)\b[\s!?.]*$/.test(ql)) return helpAnswer(true);
  if (/^(more|more detail|details?|show (?:me )?(?:the )?(?:detail|details|rows|source|sources|more)|expand|show rows)[\s!?.]*$/.test(ql)) {
    const l = ctx.last;
    return l && l.detail ? Object.assign(R("detail", ["Here is the detail."], {detail: l.detail, sources: l.sources}), {openDetail: true}) : R("detail", ["There is no detail to expand yet. Ask me something first."]);
  }
  const ids = orderIds(ql), pron = /\b(it|that one|that order|this order|this one|that|those)\b/.test(ql), tid = ids[0] || (pron ? ctx.lastOrder : null);
  const cust = customerOf(ql), stage = stageOf(ql);

  /* actions first: they always ask for confirmation */
  if (/\bremind(er)?\b/.test(ql)) return watchRoute(text, ql, call, true);
  if (/(?:tell|alert|notify|warn|ping)\s+me\s+if|let me know if|\bwatch\b|keep an eye on|\bmonitor\b/.test(ql)) return watchRoute(text, ql, call, false);
  if (/\b(add|write|save|log|leave)\b.*\bnote\b|\bnote\b.*\bord[-\s]?\d/.test(ql)) {
    if (!tid) return R("clarify_note", ["Which order is the note for?"], {asks: true});
    const m = text.match(/note(?:\s+(?:to|on|for))?\s*(?:ord[-\s]?\d+)?\s*[:\-,]?\s*(.*)$/i), body = (m && m[1] || "").replace(/^(?:that|saying)\s+/i, "").trim();
    if (!body) { ctx.pending = {type: "note", id: tid}; return R("clarify_note", [`What should the note on ${tid} say?`], {asks: true}); }
    return noteProposal(tid, body, call);
  }
  if (/\b(chase|follow[ -]?up|nudge|escalate)\b|\b(draft|write|send)\b.*\b(message|email|chase)\b/.test(ql)) {
    if (tid) return chaseProposal(tid, call);
    if (cust) { const xs = call("list_orders", {customer: cust.customer, sort: "due"}); return xs.length > 1 ? askWhichOrder(cust, "chase", call) : xs.length ? chaseProposal(xs[0].order_id, call) : customerAnswer(cust, call); }
    ctx.pending = {type: "order", then: "chase"};
    return R("clarify_order", ["Which order should I chase?"], {asks: true, chips: cur().orders.filter(o => o.status !== "on_track").slice(0, 4).map(o => chip(`${o.order_id} · ${o.customer}`, o.order_id))});
  }
  const refusal = refusalRoute(ql, call); if (refusal) return refusal;

  if ((/\bcan we\b.*\b(take|do|make|deliver|fit|handle|accept|squeeze|hit|meet)\b/.test(ql) && (!ids.length || /\btake\b/.test(ql))) || /feasib|\bcapacity (?:for|to)\b|take on\b|\bwill we (?:make|hit|meet)\b/.test(ql)
      || (/\bwhat if\b|\b(?:what|how) about \d/.test(ql) && (ctx.lastFeas || parsePieces(ql))))
    return feasRoute(text, ql, call);

  const fm = ql.match(/\b(?:finding|issue|item)\s*#?(\d)\b/); if (fm) return findingAnswer(+fm[1], call);
  if (/\b(why|how come|explain|what caused|reason|root cause|trace|show (?:me )?(?:the )?(?:rows|evidence))\b/.test(ql)) {
    if (tid) return traceAnswer(tid, call);
    if (stage) return stageAnswer(stage, ql, call, true);
    if (cust) { const f = cur().findings.find(x => x.key === `customer_stalled:${cust.customer}`); return f ? findingAnswer(cur().findings.indexOf(f) + 1, call) : customerAnswer(cust, call); }
    if (/\boutput|production|factory\b/.test(ql)) return stageAnswer("TOTAL", ql, call, true);
    ctx.pending = {type: "order", then: "why"};
    return R("clarify_order", ["Why what? Name an order (for example ORD-120) or a stage."], {asks: true, chips: cur().findings.slice(0, 3).map((f, i) => chip(`Finding ${i + 1}: ${trunc(f.title, 36)}`, `Tell me more about finding ${i + 1}`))});
  }
  if (ids.length > 1) { const rs = ids.slice(0, 3).map(id => orderAnswer(id, call)); const r = rs[0]; r.lines = rs.map(x => x.lines[0]); r.detail = orderRows(ids.map(id => cur().orders.find(o => o.order_id === id)).filter(Boolean)); r.sources = rs.flatMap(x => x.sources); return r; }
  if (ids.length === 1) return orderAnswer(ids[0], call);
  if (cust) {
    const act = call("list_orders", {customer: cust.customer, sort: "due"});
    if (/\b(the|an?|that)\s+(?:\w+\s+)?order\b/.test(ql) && !/\borders\b/.test(ql) && act.length > 1) return askWhichOrder(cust, "status", call);
    if (act.length === 1 && /\border\b/.test(ql)) return orderAnswer(act[0].order_id, call);
    return customerAnswer(cust, call);
  }
  if (/\bcustomers\b/.test(ql) && /\b(late|worst|risk|stalled|problem|behind|trouble|affected)\b/.test(ql)) return customersAnswer();
  if (stage && /\b(waiting|queue|queued|backlog|orders|stuck|in)\b/.test(ql) && !/\boutput|made|produced\b/.test(ql)) {
    const xs = call("list_orders", {stage, sort: "due"}); return listAnswer("stage_orders", `waiting at ${cap(stage)}`, xs);
  }
  if (/\bbottleneck|constraint|slowest|most (?:backed|queued)|biggest queue|where is the work\b|work in progress|\bwip\b/.test(ql)) return pipelineAnswer(call);
  if (stage || /\boutput|throughput|production|pieces (?:made|produced)|how much (?:did we|was)\b/.test(ql)) return stage ? stageAnswer(stage, ql, call, false) : stagesBelowAnswer(ql, call);
  if (/\bon[- ]?time|otd|delivery rate|delivered on time\b/.test(ql)) return onTimeAnswer(call);
  if (/\b(overdue|late|past due|behind schedule)\b/.test(ql) && !/\bat risk\b/.test(ql)) return listAnswer("late_orders", "late", call("list_orders", {status: "late", sort: "due"}));
  if (/\bat[- ]risk|risky|might miss|may miss|going to be late|will be late\b/.test(ql)) return listAnswer("at_risk_orders", "at risk", call("list_orders", {status: "at_risk"}));
  if (/\bdue (?:this|next) week|due soon|deadlines?|due in (?:the next )?7|coming due|due this\b/.test(ql)) return listAnswer("due_soon", "due in the next 7 days", call("list_orders", {dueWithin: 7, sort: "due"}));
  if (/\b(stuck|stalled|quiet|not moved|hasn'?t moved|idle|not moving|gone quiet)\b/.test(ql)) {
    const xs = call("list_orders", {idleMin: 5, sort: "idle"}), r = listAnswer("idle_orders", "idle for 5+ working days", xs);
    if (xs.length) r.lines[1] = "Idle is not always a problem: orders waiting their turn behind earlier-due work are not flagged in the briefing."; return r;
  }
  if (/\bneeds? (?:my )?attention|top (?:issues|problems|risks)|worr(?:y|ied)|biggest (?:risk|problem|issue)|priorit|what should i (?:do|look)/.test(ql)) return attentionAnswer(call);
  if (/\byesterday|what happened|go wrong|gone wrong|summary|briefing|overview|how are we|how'?s the factory|any(?:thing)? (?:problems|issues|news)|anything|status|this morning|today\b/.test(ql)) return summaryAnswer(call);
  return helpAnswer(false);
}

function respond(q) {
  const text = String(q || "").trim(), ql = text.toLowerCase().replace(/[“”]/g, '"').replace(/[’]/g, "'"), calls = [];
  const call = (name, args) => { calls.push({name, args}); return T[name].run(args || {}); };
  let r = ctx.pending ? resolvePending(text, ql, call) : null;
  if (!r) r = route(text, ql, call);
  r.tools = calls; r.question = text; if (r.intent !== "detail") ctx.last = r;
  return r;
}
function applyConfirm(r, values) {
  const c = r.confirm; if (!c) return null;
  const v = {...values}; if (c.select && v[c.select.key] == null) v[c.select.key] = c.select.value; if (c.editable && v[c.editable.key] == null) v[c.editable.key] = c.editable.value;
  return c.apply(v);
}

/* ---------- UI ---------- */
const els = {};
function say(text) { if (!ui.speak || !("speechSynthesis" in window)) return; speechSynthesis.cancel(); const u = new SpeechSynthesisUtterance(text); u.lang = "en-GB"; speechSynthesis.speak(u); }
function scrollDown() { els.log.scrollTop = els.log.scrollHeight; }
function addUser(text) { const d = document.createElement("div"); d.className = "msg user"; d.innerHTML = `<div class="bubble">${esc(text)}</div>`; els.log.append(d); scrollDown(); }
function addSystem(text) { const d = document.createElement("div"); d.className = "msg sys"; d.textContent = text; els.log.append(d); scrollDown(); }
function confirmHtml(id, c) {
  const fields = (c.fields || []).map(f => `<div class="cc-row"><span>${esc(f.label)}</span><b>${esc(f.value)}</b></div>`).join("");
  const sel = c.select ? `<label class="cc-lab">${esc(c.select.label)}<select data-key="${c.select.key}">${c.select.options.map(o => `<option>${esc(o)}</option>`).join("")}</select></label>` : "";
  const ed = c.editable ? `<label class="cc-lab">${esc(c.editable.label)}<textarea data-key="${c.editable.key}" rows="4">${esc(c.editable.value)}</textarea></label>` : "";
  return `<div class="cc" id="cc-${id}"><h4>${esc(c.title)}</h4>${fields}${sel}${ed}<p class="blast">${esc(c.blast)}</p>
    <div class="cc-btns"><button class="btn sm" data-cancel="${id}">Cancel</button><button class="btn sm primary" data-confirm="${id}">Confirm and log</button></div></div>`;
}
function addBot(r) {
  const id = ++ui.seq; ui.resp[id] = r;
  const d = document.createElement("div"); d.className = "msg bot"; d.dataset.id = id;
  const lines = r.lines.map((l, i) => `<p${i === 0 ? ' class="lead"' : ""}>${esc(l)}</p>`).join("");
  const chips = r.chips.length ? `<div class="chips">${r.chips.map(c => `<button class="chip" data-q="${esc(c.q)}">${esc(c.label)}</button>`).join("")}</div>` : "";
  const acts = [r.detail ? `<button class="linkb" data-cdet="${id}" aria-expanded="false">Show detail</button>` : "", r.sources.length ? `<button class="linkb" data-src="${id}" aria-expanded="false">Sources (${r.sources.length})</button>` : ""].filter(Boolean).join("");
  const trace = r.tools.length ? `<div class="trace">Tools used: ${[...new Set(r.tools.map(t => t.name))].map(esc).join(", ")}</div>` : "";
  d.innerHTML = `<div class="bubble${r.refused ? " refused" : ""}${r.asks ? " asks" : ""}">${lines}${r.confirm ? confirmHtml(id, r.confirm) : ""}</div>${chips}
    ${acts ? `<div class="acts">${acts}</div>` : ""}<div class="panel" id="det-c${id}" hidden>${r.detail || ""}</div>
    <div class="panel" id="src-c${id}" hidden><ul>${r.sources.map(s => `<li>${esc(s)}</li>`).join("")}</ul></div>${trace}`;
  els.log.append(d);
  if (r.openDetail) { $c(`#det-c${id}`).hidden = false; d.querySelector("[data-cdet]").setAttribute("aria-expanded", "true"); d.querySelector("[data-cdet]").textContent = "Hide detail"; }
  if (!ui.open) { ui.unread++; badge(); } scrollDown(); say(r.lines.slice(0, 2).join(" "));
}
function badge() { els.badge.hidden = !ui.unread; els.badge.textContent = ui.unread; }
function typing(on) { let t = $c("#chatTyping"); if (on && !t) { t = document.createElement("div"); t.id = "chatTyping"; t.className = "msg bot"; t.innerHTML = `<div class="bubble dots" aria-label="Working"><i></i><i></i><i></i></div>`; els.log.append(t); scrollDown(); } if (!on && t) t.remove(); }
function send(text) {
  text = String(text || "").trim(); if (!text) return;
  addUser(text); els.input.value = ""; typing(true);
  const local = () => { typing(false); addBot(respond(text)); };
  if (!ui.backend) return void setTimeout(local, 260);
  const ac = new AbortController(), to = setTimeout(() => ac.abort(), 15000);
  fetch(ui.backend, {method: "POST", headers: {"Content-Type": "application/json"}, signal: ac.signal,
    body: JSON.stringify({message: text, business_date: today(), history: [...els.log.querySelectorAll(".msg.user .bubble")].slice(-8).map(x => x.textContent)})})
    .then(r => { if (!r.ok) throw new Error(r.status); return r.json(); })
    .then(j => { typing(false); const r = R("backend", [String(j.reply || "").trim() || "(empty reply)"], {detail: j.detail ? `<p class="cnote">${esc(j.detail)}</p>` : null, sources: j.sources || []}); r.tools = (j.tools || []).map(t => ({name: String(t.name || t)})); addBot(r); })
    .catch(() => { typing(false); addSystem("Backend unreachable, answered with the built-in tools."); addBot(respond(text)); })
    .finally(() => clearTimeout(to));
}
function suggestions() {
  const b = cur(), w = worstOrder(), top = b.customers[0], pieces = 800;
  const set = [chip("Did anything go wrong yesterday?"), chip(`How is the ${top ? top.customer : "TrendCart"} order doing?`),
    chip(`Can we take ${pieces} hoodies by the ${fmt(plus(today(), 16), {day: "numeric", month: "long"})}?`), chip(`Chase ${w.order_id}`),
    chip("Remind me tomorrow if packing is still behind"), chip("What's our revenue this month?")];
  els.suggest.innerHTML = set.map(c => `<button class="chip" data-q="${esc(c.q)}">${esc(c.label)}</button>`).join("");
}
function renderWatches() {
  els.watches.innerHTML = watches.length ? `<ul class="wl">${watches.map(w => `<li><span class="pill ${w.state === "fired" ? "late" : w.state === "cleared" ? "on_track" : "neutral"}">${w.state === "active" ? "Waiting" : w.state === "fired" ? "Fired" : "Cleared"}</span>
    <span>${esc(w.kind === "no_move" ? `${w.order_id} not moved by ${day(w.trigger)}` : w.kind === "stage_behind" ? `${cap(w.stage)} still behind on ${day(w.trigger)}` : trunc(w.text, 60) + ` (${day(w.trigger)})`)}${w.result ? `<br><small>${esc(w.result)}</small>` : ""}</span>
    <button class="linkb" data-rmwatch="${w.id}">Remove</button></li>`).join("")}</ul>` : `<p class="cnote">No standing checks yet. Try "Tell me if ORD-120 hasn't moved by Friday".</p>`;
  els.watchBtn.textContent = `Watches (${watches.length})`;
}
function renderTools() {
  els.tools.innerHTML = `<p class="cnote">Every number in an answer comes from one of these tools. None of them guesses.</p>` + Object.entries(T).map(([k, t]) =>
    `<details><summary><b>${esc(k)}</b> <span class="muted">${esc(t.kind)}</span></summary><p>${esc(t.answers)}</p><p class="muted">Does not: ${esc(t.doesnt)}</p><p class="muted">If it fails: ${esc(t.fails)}</p></details>`).join("");
}
function open(on) {
  ui.open = on; els.panel.hidden = !on; els.fab.hidden = on; els.fab.setAttribute("aria-expanded", on); document.body.classList.toggle("chat-open", on);
  if (on) { ui.unread = 0; badge(); if (!els.log.children.length) addBot(helpAnswer(true)); setTimeout(() => els.input.focus(), 30); scrollDown(); }
}
function toggle(el, btn) { el.hidden = !el.hidden; btn.setAttribute("aria-expanded", !el.hidden); }
function initUI() {
  Object.assign(els, {fab: $c("#chatFab"), badge: $c("#chatBadge"), panel: $c("#chatPanel"), log: $c("#chatLog"), input: $c("#chatInput"), suggest: $c("#chatSuggest"),
    watches: $c("#chatWatches"), watchBtn: $c("#chatWatchBtn"), tools: $c("#chatTools"), mode: $c("#chatMode"), mic: $c("#chatMic")});
  els.mode.textContent = ui.backend ? "Connected to backend" : "Built-in tools · no language model";
  els.mode.title = ui.backend ? ui.backend : "Answers come from tools that read this dashboard's data. Add ?api=URL to use a backend instead.";
  els.fab.onclick = () => open(true); $c("#chatClose").onclick = () => open(false);
  $c("#chatForm").onsubmit = e => { e.preventDefault(); send(els.input.value); };
  els.watchBtn.onclick = () => { renderWatches(); toggle(els.watches, els.watchBtn); };
  $c("#chatToolsBtn").onclick = e => toggle(els.tools, e.currentTarget);
  $c("#chatSpeak").onclick = e => { ui.speak = !ui.speak; e.currentTarget.setAttribute("aria-pressed", ui.speak); if (!ui.speak && "speechSynthesis" in window) speechSynthesis.cancel(); };
  $c("#chatClear").onclick = () => { els.log.innerHTML = ""; Object.assign(ctx, {lastOrder: null, lastCustomer: null, lastStage: null, lastFeas: null, pending: null, last: null}); addBot(helpAnswer(true)); };
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (SR) { els.mic.hidden = false; els.mic.onclick = () => { const r = new SR(); r.lang = "en-GB"; r.onresult = e => send(e.results[0][0].transcript); r.start(); els.mic.setAttribute("aria-pressed", "true"); r.onend = () => els.mic.setAttribute("aria-pressed", "false"); }; }
  els.log.addEventListener("click", e => {
    const t = e.target.closest("[data-q],[data-cdet],[data-src],[data-confirm],[data-cancel],[data-rmwatch]"); if (!t) return;
    if (t.dataset.q) send(t.dataset.q);
    else if (t.dataset.cdet) { toggle($c(`#det-c${t.dataset.cdet}`), t); t.textContent = t.getAttribute("aria-expanded") === "true" ? "Hide detail" : "Show detail"; }
    else if (t.dataset.src) toggle($c(`#src-c${t.dataset.src}`), t);
    else if (t.dataset.cancel) { const c = $c(`#cc-${t.dataset.cancel}`); c.classList.add("closed"); c.innerHTML = `<p class="cnote">Cancelled. Nothing was done.</p>`; }
    else if (t.dataset.confirm) { const id = t.dataset.confirm, c = $c(`#cc-${id}`), vals = {}; c.querySelectorAll("[data-key]").forEach(x => vals[x.dataset.key] = x.value.trim());
      const done = applyConfirm(ui.resp[id], vals); c.classList.add("closed"); c.innerHTML = `<p class="cnote"><b>Done.</b> ${esc(done || "")}</p>`; toast("Logged"); renderWatches(); }
  });
  els.suggest.addEventListener("click", e => { const t = e.target.closest("[data-q]"); if (t) send(t.dataset.q); });
  els.watches.addEventListener("click", e => { const t = e.target.closest("[data-rmwatch]"); if (!t) return; const i = watches.findIndex(w => w.id === +t.dataset.rmwatch); if (i >= 0) watches.splice(i, 1); renderWatches(); });
  document.addEventListener("keydown", e => {
    if (e.key === "Escape" && ui.open && $c("#modal").hidden) open(false);
    if (e.key === "/" && !e.target.matches("input,textarea,select") && $c("#modal").hidden) { e.preventDefault(); open(true); }
  });
  renderTools(); renderWatches();
}

/* called by the dashboard after every render (date change, replay) */
window.chatHook = () => {
  if (!els.log) return;
  if (ui.lastIdx !== null && ui.lastIdx !== idx) { ctx.pending = null; if (els.log.children.length) addSystem(`Now showing ${dlong(today())}`); }
  ui.lastIdx = idx; evaluateWatches(); suggestions(); renderWatches();
};
window.ThreadPilotChat = {
  respond, apply: applyConfirm, ask: q => { open(true); send(q); }, tools: T, ctx, watches,
  askFeasibility: id => { const o = cur().orders.find(x => x.order_id === id); if (!o) return; ctx.excludeOrder = id; open(true); send(`Can we take ${o.pieces} ${o.product.toLowerCase()} by ${o.due_date}?`); },
  reset: () => { Object.assign(ctx, {lastOrder: null, lastCustomer: null, lastStage: null, lastFeas: null, pending: null, last: null, excludeOrder: null}); watches.length = 0; },
};
initUI(); window.chatHook();
})();
