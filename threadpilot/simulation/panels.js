/* ThreadPilot panels: settings (text size, typeface, stage targets, refresh), the at-risk split, the order forecast, memos
 * for amended delivery dates and specifications, and the right-hand follow-up action panel.
 *
 * Everything the model computed (risk, expedite assessment, forecast) comes from the briefing JSON. This file only displays it,
 * plus two small browser-side things: settings and memos, kept in localStorage (try/catch: it can be unavailable).
 * Memos are annotations. In production they need a database table and the tools must apply them (see docs/prediction_validation.md).
 */
(() => {
"use strict";
const ST = ["KNITTING", "ASSEMBLY", "WASHING", "PACKING"];
const FONTS = {
  system: {label: "System", css: 'system-ui,-apple-system,"Segoe UI",Roboto,Arial,sans-serif'},
  inter: {label: "Inter", css: '"Inter",system-ui,sans-serif'},
  serif: {label: "Serif", css: 'Georgia,"Times New Roman",serif'},
  mono: {label: "Monospace", css: 'ui-monospace,"SF Mono",Menlo,Consolas,monospace'},
};
const SIZES = {S: 0.9, M: 1, L: 1.15, XL: 1.3};
const LEVEL = {overdue: ["late", "Overdue"], high: ["critical", "High risk"], medium: ["high", "Medium risk"], low: ["on_track", "Low risk"], unknown: ["watch", "Unknown"]};
const REC = {now: "Expedite now", trade_off: "Trade-off: your call", later: "Expedite later, or not needed", investigate: "Find the blocker first"};
const mem = {};
const store = {
  get(k, d) { try { const v = localStorage.getItem(k); return v ? JSON.parse(v) : d; } catch (e) { return k in mem ? mem[k] : d; } },
  set(k, v) { mem[k] = v; try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) { /* in-memory only */ } },
};
let settings = {size: "M", font: "system", targets: {}, refresh: "daily", ...store.get("tp.settings", {})};
let memos = store.get("tp.memos", []);
const expanded = {od: false, ap: false};
const dd = s => new Date(s + "T12:00:00Z");
const diffDays = (a, b) => Math.round((dd(a) - dd(b)) / 864e5);
const dm = s => fmt(s, {day: "numeric", month: "short"});
const nowHM = () => new Date().toLocaleTimeString("en-GB", {hour: "2-digit", minute: "2-digit"});
const logIt = (what, detail) => { log.unshift({time: nowHM(), what, detail}); renderLog(); };
const order = id => B[idx].orders.find(o => o.order_id === id);
const saveSettings = () => store.set("tp.settings", settings);
const saveMemos = () => store.set("tp.memos", memos);
const localDate = () => { const t = new Date(); return `${t.getFullYear()}-${String(t.getMonth() + 1).padStart(2, "0")}-${String(t.getDate()).padStart(2, "0")}`; };
const newId = () => `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
let lastFocus = null;   // dialogs take keyboard focus when they open and give it back when they close
function showLayer(el) { lastFocus = document.activeElement; el.hidden = false; const f = el.querySelector("input, select, textarea, button"); if (f) f.focus(); }
function hideLayer(el) { el.hidden = true; const t = lastFocus; lastFocus = null; if (t && document.contains(t) && t.focus) t.focus(); }

/* ---------- settings ---------- */
function applySettings() {
  document.documentElement.style.setProperty("--z", SIZES[settings.size] || 1);
  document.documentElement.style.setProperty("--font", (FONTS[settings.font] || FONTS.system).css);
  const lab = document.querySelector("#refreshNote");
  if (lab) lab.textContent = settings.refresh === "hourly" ? "Refresh: hourly (needs the live backend)" : "Refresh: daily at 07:00";
}
function renderSettings() {
  const seg = (items, cur, attr) => `<div class="seg" role="group">${items.map(([k, label, style]) => `<button ${attr}="${k}" aria-pressed="${k === cur}" ${style ? `style="font-family:${style}"` : ""}>${label}</button>`).join("")}</div>`;
  document.querySelector("#stBody").innerHTML = `
    <div class="set-row"><div class="set-l">Text size</div>${seg(Object.keys(SIZES).map(k => [k, k]), settings.size, "data-tp-size")}</div>
    <div class="set-row"><div class="set-l">Typeface</div>${seg(Object.entries(FONTS).map(([k, f]) => [k, f.label, f.css]), settings.font, "data-tp-font")}</div>
    <div class="set-row"><div class="set-l">Stage targets <small>pieces per day</small></div>
      <div class="tgt">${ST.map(s => `<label>${cap(s)}<input type="number" min="0" step="10" inputmode="numeric" data-tp-target="${s}" value="${settings.targets[s] || ""}" placeholder="no target"></label>`).join("")}</div>
      <div class="row-btns"><button class="btn sm" data-tp-fill>Use usual output</button><button class="btn sm ghost" data-tp-clear>Clear</button></div>
      <p class="setnote">A stage is highlighted when its output is below target on 3 working days in a row.</p></div>
    <div class="set-row"><div class="set-l">Refresh</div>${seg([["daily", "Daily, 07:00"], ["hourly", "Hourly"]], settings.refresh, "data-tp-refresh")}
      <p class="setnote">${settings.refresh === "hourly" ? "Saved, but this demo has nothing to refresh hourly: it builds one briefing per morning and the production log is daily. Hourly needs the live backend." : "The briefing is built once each morning."}</p></div>`;
}
function openSettings() { renderSettings(); showLayer(document.querySelector("#settingsModal")); }

/* ---------- stage targets ---------- */
function targetStatus() {
  const b = B[idx];
  return ST.map(s => {
    const t = Number(settings.targets[s]);
    if (!t) return {stage: s, target: null};
    const vals = b.stages[s].history.filter(h => h.value != null);
    let streak = 0;
    for (let i = vals.length - 1; i >= 0 && vals[i].value < t; i--) streak++;
    const y = vals[vals.length - 1];
    return {stage: s, target: t, yesterday: y ? y.value : null, met: y ? y.value >= t : null, streak, missed3: streak >= 3};
  });
}
function targetStrip() {
  const anchor = document.querySelector("#chartsum"); if (!anchor) return;
  let strip = document.querySelector("#targetStrip");
  if (!strip) { strip = document.createElement("div"); strip.id = "targetStrip"; strip.className = "strip"; anchor.insertAdjacentElement("afterend", strip); }
  const ts = targetStatus();
  strip.innerHTML = ts.every(t => !t.target) ? `<span class="muted" style="font-size:12.5px">No stage targets set. <button class="linkb" data-tp-open="settings" style="background:none;border:0;color:var(--chart);cursor:pointer;text-decoration:underline">Set targets</button></span>`
    : ts.filter(t => t.target).map(t => {
      const cls = t.missed3 ? "late" : t.met ? "on_track" : "high";
      const msg = t.missed3 ? `missed ${t.streak} days in a row` : t.met ? "met yesterday" : "missed yesterday";
      return `<span class="pill ${cls}">${cap(t.stage)} ${n(t.target)}/day · ${n(t.yesterday)} · ${msg}</span>`;
    }).join("");
  const ch = document.querySelector("#changes");
  if (ch) {   // called on every keystroke in Settings, so replace earlier pills instead of adding more
    ch.querySelectorAll("[data-tp-pill]").forEach(e => e.remove());
    ch.insertAdjacentHTML("beforeend", ts.filter(t => t.missed3).map(t => `<span class="pill late" data-tp-pill>${cap(t.stage)} below its ${n(t.target)} target ${t.streak} days running</span>`).join(""));
  }
}

/* ---------- at risk, split in two ---------- */
const riskPill = r => `<span class="pill ${LEVEL[r.level][0]}">${LEVEL[r.level][1]}</span>`;
function riskItem(o, overdue) {
  const r = o.risk, exp = r.expected_date || r.best_date;
  const sub = overdue ? `${-o.days_to_due} day${o.days_to_due === -1 ? "" : "s"} late · now expected to finish about ${dm(exp)}`
    : `due in ${o.days_to_due} day${o.days_to_due === 1 ? "" : "s"} (${dm(o.due_date)}) · ${r.late_days_best ? `${r.late_days_best} working days late even at best` : "on time only if nothing overtakes it"}`;
  return `<li class="rk-item"><div class="rk-main"><b>${esc(o.order_id)}</b> <span class="muted">${esc(o.customer)} · ${n(o.pieces)} ${esc(o.product.toLowerCase())}</span><div class="rk-sub">${esc(sub)}</div></div>
    <div class="rk-side">${riskPill(r)}${overdue ? "" : `<span class="riskline">confidence ${esc(r.confidence)}</span>`}<button class="btn sm" data-tp-actions="${esc(o.order_id)}">Actions</button></div></li>`;
}
function riskCard() {
  const el = document.querySelector("#riskCard"); if (!el) return;
  const os = B[idx].orders;
  const od = os.filter(o => o.status === "late").sort((a, b) => a.days_to_due - b.days_to_due);
  const ap = os.filter(o => o.status === "at_risk").sort((a, b) => a.days_to_due - b.days_to_due || b.risk.late_days_best - a.risk.late_days_best);
  const col = (key, title, list, overdue) => `<div class="rk-col"><h3>${title} <span class="count">${list.length}</span></h3>
    <ul>${(expanded[key] ? list : list.slice(0, 5)).map(o => riskItem(o, overdue)).join("") || `<li class="muted" style="padding:8px 0">None this morning.</li>`}</ul>
    ${list.length > 5 ? `<button class="btn sm rk-more" data-tp-more="${key}">${expanded[key] ? "Show fewer" : `Show all ${list.length}`}</button>` : ""}</div>`;
  el.innerHTML = `<div class="card-h"><h2>At risk</h2><span class="muted">overdue orders, and orders approaching their due date</span></div>
    <div class="card-b rk-grid">${col("od", "Already overdue", od, true)}${col("ap", "Approaching due date", ap, false)}</div>`;
}

/* ---------- forecast ---------- */
function forecastCard() {
  const el = document.querySelector("#forecastCard"); if (!el) return;
  const f = B[idx].forecast;
  if (!f || !f.enough_data) { el.innerHTML = `<div class="card-h"><h2>Expected orders</h2></div><div class="card-b muted">Not enough order history for a forecast.</div>`; return; }
  const bt = f.backtest, rel = !bt ? "" : !bt.enough_data ? "Too little history to test this forecast."
    : `Tested on ${bt.starting_points} past starting points of your data: off by ${bt.mae_forecast} orders on average, against ${bt.mae_same_as_last_period} for simply repeating the last period. The top 3 customers were right for ${Math.round(100 * bt.top3_customer_hit_rate)}% of orders; picking 3 customers at random would be right ${Math.round(100 * bt.chance_top3_customer_rate)}%.`;
  const li = (rows, key) => rows.slice(0, 4).map(r => `<li><span>${esc(r[key])}</span><span class="muted">${r.expected_orders} orders · ${Math.round(100 * r.chance_any)}% chance of 1+ · usually ${n(r.typical_pieces)} pcs</span></li>`).join("");
  el.innerHTML = `<div class="card-h"><h2>Expected orders, next 2 weeks</h2><span class="muted">to ${dm(f.horizon_end)}</span></div>
    <div class="card-b"><div class="fc-big">about ${Math.round(f.expected_orders)} orders <span class="muted" style="font-size:15px;font-weight:400">(${f.orders_low} to ${f.orders_high})</span></div>
      <div class="muted">about ${n(f.expected_pieces)} pieces (${n(f.pieces_low)} to ${n(f.pieces_high)}), ${n(f.mean_pieces)} per order on average</div>
      <div class="fc-grid"><div><b style="font-size:13px">Customers most likely to order</b><ul class="fc-list">${li(f.customers, "customer")}</ul></div>
      <div><b style="font-size:13px">Products most likely</b><ul class="fc-list">${li(f.products, "product")}</ul></div></div>
      <p class="fc-note">${esc(f.method)} ${esc(rel)} Treat the customer and product lists as who orders often, not as predictions.</p></div>`;
}

/* ---------- memos ---------- */
function latestDateMemo(id) { return memos.filter(m => m.order_id === id && m.type === "date").sort((a, b) => b.created.localeCompare(a.created))[0]; }
function dueBadge(id) { const m = latestDateMemo(id); return m ? `<span class="amend" title="Amended delivery date (memo): ${esc(m.reason || "")}">amended: ${esc(dm(m.new_due))}</span>` : ""; }
function riskBadge(o) {
  if (!o.risk || o.status === "late") return "";
  const m = latestDateMemo(o.order_id), info = m ? ` · vs amended date: ${amendedVerdict(o, m)}` : "";
  return `<span class="riskline">${LEVEL[o.risk.level][1].toLowerCase()}, confidence ${esc(o.risk.confidence)}${esc(info)}</span>`;
}
function amendedVerdict(o, m) {
  const exp = o.risk.expected_date || o.risk.best_date;
  if (m.new_due < today()) return "still overdue";
  return exp > m.new_due ? `still ${diffDays(exp, m.new_due)} days late` : "projected to meet it";
}
function today() { return B[idx].business_date; }
function memoCard() {
  const el = document.querySelector("#memoCard"); if (!el) return;
  const rows = type => memos.filter(m => m.type === type).sort((a, b) => b.created.localeCompare(a.created));
  const cust = id => { const o = order(id); return o ? esc(o.customer) : `<span class="muted">no longer in progress</span>`; };
  const dates = rows("date"), specs = rows("spec");
  el.innerHTML = `<div class="card-h"><h2>Memos: amended dates and specifications</h2><button class="btn sm primary" data-tp-open="memo">Add memo</button></div>
    <div class="card-b"><b style="font-size:13px">Amended delivery dates</b>
    <div class="tbl"><table class="mini"><thead><tr><th>Order</th><th>Customer</th><th>Original due</th><th>Amended due</th><th>Change</th><th>Against the new date</th><th>Reason</th><th></th></tr></thead><tbody>
    ${dates.map(m => { const o = order(m.order_id); return `<tr><td><b>${esc(m.order_id)}</b></td><td>${cust(m.order_id)}</td><td>${esc(dm(m.original_due))}</td><td>${esc(dm(m.new_due))}</td><td>${diffDays(m.new_due, m.original_due) >= 0 ? "+" : ""}${diffDays(m.new_due, m.original_due)} days</td><td>${o ? esc(amendedVerdict(o, m)) : "–"}</td><td style="white-space:normal">${esc(m.reason || "")}</td><td><button class="xbtn" data-tp-rm="${m.id}" aria-label="Remove memo">&times;</button></td></tr>`; }).join("") || `<tr><td colspan="8" class="muted">No amended delivery dates recorded.</td></tr>`}
    </tbody></table></div>
    <b style="font-size:13px;display:block;margin-top:14px">Orders with amended specifications</b>
    <div class="tbl"><table class="mini"><thead><tr><th>Order</th><th>Customer</th><th>Amended specification</th><th>Reason</th><th>Recorded</th><th></th></tr></thead><tbody>
    ${specs.map(m => `<tr><td><b>${esc(m.order_id)}</b></td><td>${cust(m.order_id)}</td><td style="white-space:normal">${esc(m.spec)}</td><td style="white-space:normal">${esc(m.reason || "")}</td><td>${esc(m.created_local || m.created.slice(0, 10))}</td><td><button class="xbtn" data-tp-rm="${m.id}" aria-label="Remove memo">&times;</button></td></tr>`).join("") || `<tr><td colspan="6" class="muted">No amended specifications recorded.</td></tr>`}
    </tbody></table></div>
    <p class="fc-note">Memos are notes kept in this browser. They do not change the factory's order data, and the risk model still uses the original due dates.</p></div>`;
}
function openMemo(id, type) {
  const os = B[idx].orders;
  document.querySelector("#mmBody").innerHTML = `
    <div class="sec" style="border:0;padding:0"><label>Order<select id="mmOrder">${os.map(o => `<option value="${esc(o.order_id)}" ${o.order_id === id ? "selected" : ""}>${esc(o.order_id)} · ${esc(o.customer)} · due ${esc(dm(o.due_date))}</option>`).join("")}</select></label>
    <label>What changed<select id="mmType"><option value="date" ${type !== "spec" ? "selected" : ""}>Delivery date</option><option value="spec" ${type === "spec" ? "selected" : ""}>Specification</option></select></label>
    <label id="mmDateRow">New delivery date<input type="date" id="mmDate" min="${today()}"></label>
    <label id="mmSpecRow" hidden>New specification<textarea id="mmSpec" placeholder="For example: switch to navy trim, add size XXL"></textarea></label>
    <label>Reason or customer request<input type="text" id="mmReason" maxlength="200" placeholder="Who asked, and why"></label></div>`;
  const sync = () => { const spec = document.querySelector("#mmType").value === "spec"; document.querySelector("#mmDateRow").hidden = spec; document.querySelector("#mmSpecRow").hidden = !spec; };
  document.querySelector("#mmType").onchange = sync; sync();
  showLayer(document.querySelector("#memoModal"));
}
function saveMemo() {
  const id = document.querySelector("#mmOrder").value, type = document.querySelector("#mmType").value, o = order(id);
  const reason = document.querySelector("#mmReason").value.trim();
  if (type === "date") {
    const nd = document.querySelector("#mmDate").value;
    if (!nd) return toast("Choose the new delivery date first");
    memos.unshift({id: newId(), order_id: id, type, original_due: o.due_date, new_due: nd, reason, created: new Date().toISOString(), created_local: localDate()});
    logIt(`Memo: delivery date amended for ${id}`, `${dm(o.due_date)} to ${dm(nd)}${reason ? ": " + reason : ""}`);
  } else {
    const spec = document.querySelector("#mmSpec").value.trim();
    if (!spec) return toast("Describe the new specification first");
    memos.unshift({id: newId(), order_id: id, type, spec, reason, created: new Date().toISOString(), created_local: localDate()});
    logIt(`Memo: specification amended for ${id}`, spec);
  }
  saveMemos(); hideLayer(document.querySelector("#memoModal")); memoCard(); orders(); renderSide(); toast("Memo saved");
}

/* ---------- right-hand follow-up panel ---------- */
let sideId = null;
function drafts(o) {
  const ex = o.expedite, rec = ex ? ex.recommendation : "later";
  const about = `${o.order_id} (${o.customer}, ${n(o.pieces)} ${o.product.toLowerCase()})`;
  const due = o.days_to_due < 0 ? `${-o.days_to_due} days overdue (due ${dm(o.due_date)})` : `due ${dm(o.due_date)}`;
  let ask;
  if (rec === "investigate") ask = `It has not moved for ${o.idle_days} working days. Could you tell me what is holding it and when it can restart?`;
  else if (rec === "now" || rec === "trade_off") ask = `Please prioritise it at ${cap(o.stage)} and confirm a firm finish date by 12:00 today.` + (rec === "trade_off" && ex.newly_late.length ? ` Note: prioritising it will push ${ex.newly_late.slice(0, 3).join(", ")} past their due dates.` : "");
  else ask = "Could you give me an update and a firm finish date by 12:00 today?";
  const kind = rec === "now" || rec === "trade_off" ? "Expedite request" : "Status request";
  const subject = `${kind}: ${o.order_id} (${o.customer}), ${due}`;
  const body = `Hi,\n\n${about} is at ${cap(o.stage)} and ${due}.${o.status === "late" ? "" : " " + o.risk.reason + "."}\n\n${ask}\n\nThanks`;
  const teams = `${about} is at ${cap(o.stage)}, ${due}. ${ask}`;
  return {subject, body, teams};
}
function renderSide() {
  if (!sideId) return;
  const o = order(sideId), body = document.querySelector("#apBody");
  if (!o) { body.innerHTML = `<div class="sec"><p>${esc(sideId)} is no longer in progress on ${esc(dm(today()))}.</p></div>`; return; }
  document.querySelector("#apTitle").textContent = `Follow-up: ${o.order_id}`;
  document.querySelector("#apSub").textContent = `${o.customer} · ${n(o.pieces)} ${o.product.toLowerCase()} · at ${cap(o.stage)} · due ${dm(o.due_date)}`;
  const ex = o.expedite, d = drafts(o), m = latestDateMemo(o.order_id);
  const pushed = ex && ex.pushed.length ? `<div class="tbl" style="margin-top:8px"><table class="mini"><thead><tr><th>Order slowed</th><th>Customer</th><th>Extra days</th><th>Added lateness</th><th>Pushed late?</th></tr></thead><tbody>${ex.pushed.map(p => `<tr><td>${esc(p.order_id)}</td><td>${esc(p.customer)}</td><td>${p.extra_days}</td><td>${p.added_lateness}</td><td>${p.newly_late ? "yes" : "–"}</td></tr>`).join("")}</tbody></table></div><p class="fc-note">Top ${ex.pushed.length} of ${ex.pushed_total} orders that would be slowed.</p>` : "";
  body.innerHTML = `
    <div class="sec"><h3>Risk</h3><span class="pill ${LEVEL[o.risk.level][0]}">${LEVEL[o.risk.level][1]}</span> <span class="muted">confidence ${esc(o.risk.confidence)}</span><p>${esc(o.risk.reason)}.</p>
      <p>Expected to finish about ${esc(dm(o.risk.expected_date || o.risk.best_date))}${o.risk.expected_date ? ` (best case ${esc(dm(o.risk.best_date))})` : ""}.${m ? ` Amended date on memo: ${esc(dm(m.new_due))}, ${esc(amendedVerdict(o, m))}.` : ""}</p></div>
    <div class="sec reco ${ex ? ex.recommendation : "later"}"><h3>Expedite now or later?</h3>
      ${ex ? `<b>${esc(ex.label)}</b><p>${esc(ex.reason)}</p>${ex.recommendation === "investigate" ? "" : `<div class="nums"><div><b>${ex.gain}</b>working days less late</div><div><b>${ex.cost}</b>days of lateness added elsewhere</div><div><b>${ex.net}</b>net</div></div>${pushed}`}
        <p class="fc-note">Projection, not a promise: queued orders count in full, no overtime, no extra workshop capacity beyond the estimated factor. Checked against the simulator in docs/prediction_validation.md.</p>`
        : `<p>No assessment: this order is not overdue or at risk.</p>`}</div>
    <div class="sec"><h3>Email</h3>
      <label>To<input type="text" id="apTo" placeholder="production planner's email (optional)"></label>
      <label>Subject<input type="text" id="apSubject" value="${esc(d.subject)}"></label>
      <label>Message<textarea id="apBodyText" rows="8">${esc(d.body)}</textarea></label>
      <div class="row-btns"><button class="btn primary sm" data-tp-mail>Open in email app</button><button class="btn sm" data-tp-copy="email">Copy email</button></div></div>
    <div class="sec"><h3>Teams message</h3><label>Message<textarea id="apTeams" rows="4">${esc(d.teams)}</textarea></label>
      <div class="row-btns"><button class="btn sm" data-tp-copy="teams">Copy Teams message</button></div></div>
    <div class="sec"><h3>Record a change</h3><p>The customer agreed a new date or changed the specification?</p>
      <div class="row-btns"><button class="btn sm" data-tp-memo="date">Amended delivery date</button><button class="btn sm" data-tp-memo="spec">Amended specification</button></div></div>`;
}
function mailtoUrl(to, subject, body) {
  const addr = to.split(",").map(x => encodeURIComponent(x.trim()).replace("%40", "@")).filter(x => x).join(",");
  return `mailto:${addr}?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`;
}
function openActions(id) {
  if (window.ThreadPilotChat && window.ThreadPilotChat.close) window.ThreadPilotChat.close();
  sideId = id; renderSide();
  showLayer(document.querySelector("#actionPanel")); document.body.classList.add("side-open");
  document.querySelector("#apBody").scrollTop = 0;
}
function closeSide() { hideLayer(document.querySelector("#actionPanel")); document.body.classList.remove("side-open"); sideId = null; }
async function copy(text) {
  try { await navigator.clipboard.writeText(text); return true; } catch (e) {
    const t = document.createElement("textarea"); t.value = text; document.body.append(t); t.select();
    let ok = false; try { ok = document.execCommand("copy"); } catch (e2) { ok = false; } t.remove(); return ok;
  }
}

/* ---------- events ---------- */
document.addEventListener("click", async e => {
  const t = e.target.closest("[data-tp-actions],[data-tp-more],[data-tp-open],[data-tp-size],[data-tp-font],[data-tp-refresh],[data-tp-fill],[data-tp-clear],[data-tp-rm],[data-tp-mail],[data-tp-copy],[data-tp-memo]");
  if (!t) return;
  const ds = t.dataset;
  if (ds.tpActions) openActions(ds.tpActions);
  else if (ds.tpMore) { expanded[ds.tpMore] = !expanded[ds.tpMore]; riskCard(); }
  else if (ds.tpOpen === "settings") openSettings();
  else if (ds.tpOpen === "memo") openMemo(null, "date");
  else if (ds.tpSize) { settings.size = ds.tpSize; saveSettings(); applySettings(); renderSettings(); }
  else if (ds.tpFont) { settings.font = ds.tpFont; saveSettings(); applySettings(); renderSettings(); }
  else if (ds.tpRefresh) { settings.refresh = ds.tpRefresh; saveSettings(); applySettings(); renderSettings(); }
  else if ("tpFill" in ds) { ST.forEach(s => { const m = B[idx].stages[s].yesterday.mean; if (m) settings.targets[s] = Math.round(m / 10) * 10; }); saveSettings(); renderSettings(); targetStrip(); }
  else if ("tpClear" in ds) { settings.targets = {}; saveSettings(); renderSettings(); targetStrip(); }
  else if (ds.tpRm) { memos = memos.filter(m => String(m.id) !== ds.tpRm); saveMemos(); memoCard(); orders(); renderSide(); }
  else if (ds.tpMemo) openMemo(sideId, ds.tpMemo);
  else if ("tpMail" in ds) {
    const to = document.querySelector("#apTo").value.trim(), sub = document.querySelector("#apSubject").value, body = document.querySelector("#apBodyText").value;
    logIt(`Email draft opened for ${sideId}`, sub);
    window.location.href = mailtoUrl(to, sub, body);
  } else if (ds.tpCopy) {
    const text = ds.tpCopy === "email" ? `Subject: ${document.querySelector("#apSubject").value}\n\n${document.querySelector("#apBodyText").value}` : document.querySelector("#apTeams").value;
    const ok = await copy(text);
    if (ok) logIt(`${ds.tpCopy === "email" ? "Email" : "Teams message"} draft copied for ${sideId}`, text.split("\n")[0].slice(0, 100));
    toast(ok ? "Copied" : "Copy failed: select the text and copy it by hand");
  }
});
document.addEventListener("input", e => {
  const t = e.target.closest("[data-tp-target]"); if (!t) return;
  const v = Number(t.value); if (v > 0) settings.targets[t.dataset.tpTarget] = v; else delete settings.targets[t.dataset.tpTarget];
  saveSettings(); targetStrip();
});
document.addEventListener("keydown", e => {
  if (e.key !== "Escape") return;
  for (const id of ["#settingsModal", "#memoModal"]) { const m = document.querySelector(id); if (!m.hidden) { hideLayer(m); return; } }
  if (!document.querySelector("#actionPanel").hidden) closeSide();
});
document.querySelector("#apClose").onclick = closeSide;
document.querySelector("#stDone").onclick = () => hideLayer(document.querySelector("#settingsModal"));
document.querySelector("#mmCancel").onclick = () => hideLayer(document.querySelector("#memoModal"));
document.querySelector("#mmSave").onclick = saveMemo;
for (const id of ["#settingsModal", "#memoModal"]) document.querySelector(id).addEventListener("click", e => { if (e.target.id === id.slice(1)) hideLayer(e.target); });
const sb = document.querySelector("#settingsBtn"); if (sb) sb.onclick = openSettings;

window.panelsHook = () => { applySettings(); riskCard(); forecastCard(); memoCard(); targetStrip(); renderSide(); };
window.TPPanels = {targetStatus, openActions, riskBadge, dueBadge, settings: () => settings, memos: () => memos, drafts, closeSide, mailtoUrl};
applySettings(); window.panelsHook(); orders();
})();
