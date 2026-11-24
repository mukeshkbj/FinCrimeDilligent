"use strict";
/* Namesake analyst workbench. The page only displays and sends analyst actions;
   every automatic decision comes from the engine via the server. */

const $ = (s, el = document) => el.querySelector(s);
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const ID_RE = /\b(?:CUS-\d{6}|KYC-[0-9A-F]{6}|NOTE-[0-9A-F]{6}|SR-[0-9A-F]{6}|H-[0-9A-F]{6}|A-[0-9A-F]{6}|ACC-[0-9A-F]{6}|APP-[0-9A-F]{6})\b/g;
const PLAIN = { DIFFERENT_ENTITY: "Different person", SAME_ENTITY: "Same person", REVIEW: "Needs a person" };
const STATUS = { needs_you: "Needs you", awaiting_approval: "Awaiting approval", escalated: "Escalated to compliance", cleared: "Cleared" };
const ISSUE_STATUS = { open: "Open", requested: "Info requested", resolved: "Resolved", accepted: "Risk accepted", noted: "Noted" };
const store = {
  get(k, d) { try { return localStorage.getItem(k) ?? d; } catch (e) { return d; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* storage blocked */ } },
};
const ui = { state: null, alert: null, hit: null, tab: "issues", choice: null, queue: [] };

async function api(path, body) {
  const opts = body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : {};
  const res = await fetch(path, opts);
  const data = await res.json().catch(() => ({}));
  if (!res.ok && !body) throw Object.assign(new Error(data.error || res.statusText), { status: res.status });
  return data;
}
function toast(msg, bad) {
  const t = $("#toast"); t.textContent = msg; t.className = "toast show" + (bad ? " bad" : "");
  clearTimeout(toast.t); toast.t = setTimeout(() => (t.className = "toast"), 3200);
}
const me = () => ($("#analyst").value || "").trim();
const ids = (text) => esc(text).replace(ID_RE, (m) => `<button class="idchip" data-rec="${m}">${m}</button>`);
const when = (iso) => (iso ? new Date(iso).toLocaleString(undefined, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) : "");
const pill = (status) => `<span class="pill st-${status}">${STATUS[status]}</span>`;
const dchip = (d, extra = "") => `<span class="pill d-${d}">${PLAIN[d]}${extra}</span>`;

/* ---------- shell ---------- */
function applyTheme(mode) {
  store.set("ns-theme", mode);
  const dark = mode === "dark" || (mode === "system" && matchMedia("(prefers-color-scheme: dark)").matches);
  document.documentElement.dataset.theme = dark ? "dark" : "light";
  document.querySelectorAll(".theme button").forEach((b) => b.classList.toggle("on", b.dataset.theme === mode));
}
async function refreshState() {
  ui.state = await api("/api/state");
  const run = ui.state.runs.find((r) => r.run_id === ui.state.current);
  $("#run-pill").innerHTML = run ? `Run <b>${esc(run.label)}</b><br>${run.hits} hits · ${when(run.finished)}` : "No run open";
  if (ui.state.ready) {
    const o = await api("/api/overview");
    $("#nav-needs").textContent = o.alert_status.needs_you || "";
    $("#nav-approvals").textContent = o.alert_status.awaiting_approval || "";
  }
}
function setNav(key) { document.querySelectorAll(".side nav a").forEach((a) => a.classList.toggle("on", a.dataset.nav === key)); }

/* ---------- router ---------- */
async function route() {
  const [path, qs] = location.hash.slice(1).split("?");
  const params = new URLSearchParams(qs || "");
  const parts = (path || "/overview").split("/").filter(Boolean);
  await refreshState().catch(() => {});
  const main = $("#main");
  try {
    if (!ui.state.ready && parts[0] !== "runs") { setNav("runs"); return renderRuns(main, "No screening run is open yet. Run one below (about 10 seconds), then every page works."); }
    if (parts[0] === "queue") { setNav(params.get("status") === "awaiting_approval" ? "approvals" : "queue"); return renderQueue(main, params); }
    if (parts[0] === "alert") { setNav("queue"); return renderAlert(main, parts[1], params.get("hit")); }
    if (parts[0] === "runs") { setNav("runs"); return renderRuns(main); }
    if (parts[0] === "graph") { setNav("graph"); return renderKG(main, params.get("focus")); }
    setNav("overview"); return renderOverview(main);
  } catch (e) {
    main.innerHTML = `<div class="card card-pad"><h2>Something went wrong</h2><p>${esc(e.message)}</p><a href="#/runs">Go to Runs</a></div>`;
  }
}

/* ---------- overview ---------- */
async function renderOverview(main) {
  const o = await api("/api/overview");
  const s = o.alert_status, t = o.hit_totals, total = Object.values(t).reduce((a, b) => a + b, 0) || 1;
  const p = o.practice || {};
  main.innerHTML = `
  <div class="page-head"><div><h1>Overview</h1><p>${esc(o.run.label)} · ${o.alerts} alerts · ${total} hits · data folder <span class="code">${esc(o.run.data_dir)}</span></p></div>
    <div><a class="btn primary" href="#/queue?status=needs_you">Open the queue</a></div></div>
  <div class="grid-4">
    <a class="card kpi needs" href="#/queue?status=needs_you"><div class="label">Needs you</div><div class="value">${s.needs_you}</div><div class="hint">alerts with a hit no rule could settle</div></a>
    <a class="card kpi wait" href="#/queue?status=awaiting_approval"><div class="label">Awaiting approval</div><div class="value">${s.awaiting_approval}</div><div class="hint">decided, waiting for a second analyst</div></a>
    <a class="card kpi same" href="#/queue?status=escalated"><div class="label">Escalated to compliance</div><div class="value">${s.escalated}</div><div class="hint">a hit is the customer</div></a>
    <a class="card kpi clear" href="#/queue?status=cleared"><div class="label">Cleared</div><div class="value">${s.cleared}</div><div class="hint">every hit is a different person</div></a>
  </div>
  <div class="grid-2">
    <div class="card card-pad"><h2>Where the hits went</h2>
      <div class="bar">${["DIFFERENT_ENTITY", "SAME_ENTITY", "REVIEW"].map((d) => `<span class="d-${d}" style="width:${(100 * t[d]) / total}%;background:currentColor"></span>`).join("")}</div>
      <div class="legend"><span><i style="background:var(--clear)"></i>Different person ${t.DIFFERENT_ENTITY}</span><span><i style="background:var(--same)"></i>Same person ${t.SAME_ENTITY}</span><span><i style="background:var(--review)"></i>Needs a person ${t.REVIEW}</span></div>
      <p class="by" style="margin-top:12px">${o.decided_by_analyst} hit(s) decided by analysts and approved. ${o.open_issues} data issue(s) open or waiting for information.</p>
      ${p.available ? `<h2 style="margin-top:18px">Engine quality on ${p.labels} answered practice hits</h2>
      <div class="metrics">
        <div><small>Right decisions</small><b>${p.right}/${p.labels}</b></div><div><small>Unsafe clearances</small><b>${p.unsafe}</b></div><div><small>Decision score</small><b>${p.decision_score}</b></div>
        <div><small>False positives cleared</small><b>${esc(p.false_positive_clears)}</b></div><div><small>Clearance precision</small><b>${p.clearance_precision}%</b></div><div><small>Review rate</small><b>${p.review_rate}%</b></div>
      </div>` : ""}
    </div>
    <div class="card card-pad"><h2>Recent activity</h2>
      ${o.activity.length ? `<ul class="activity">${o.activity.map((a) => `<li><time>${when(a.at)}</time><a href="#/alert/${esc(a.alert_id)}">${esc(a.text)}</a>${a.note ? `<div class="by">“${esc(a.note)}”</div>` : ""}</li>`).join("")}</ul>` : `<p class="empty">No analyst actions yet. Start with the queue.</p>`}
    </div>
  </div>`;
}

/* ---------- queue ---------- */
async function renderQueue(main, params) {
  const status = params.get("status") || "needs_you";
  const q = params.get("q") || "";
  const [data, o] = await Promise.all([api(`/api/alerts?status=${status}&q=${encodeURIComponent(q)}`), api("/api/overview")]);
  ui.queue = data.alerts.map((a) => a.alert_id);
  store.set("ns-queue", JSON.stringify({ status, q, ids: ui.queue }));
  const tabs = ["needs_you", "awaiting_approval", "escalated", "cleared", "all"];
  main.innerHTML = `
  <div class="page-head"><div><h1>Queue</h1><p>Alerts close only when every hit is a different person. Hits the rules could not settle wait for you.</p></div>
    <div style="display:flex;gap:8px"><input class="field search" id="q" placeholder="Search name, alert or hit id" value="${esc(q)}">
    <a class="btn" href="/api/export?format=csv">Export CSV</a></div></div>
  <div class="tabs">${tabs.map((k) => `<a class="${k === status ? "on" : ""}" href="#/queue?status=${k}">${k === "all" ? "All" : STATUS[k]}<span class="n">${k === "all" ? o.alerts : o.alert_status[k]}</span></a>`).join("")}</div>
  <div class="card">${data.alerts.length ? `<table class="list"><thead><tr><th>Status</th><th>Customer as screened</th><th>Alert</th><th>Hits</th><th>Decisions per hit</th><th>Screened</th></tr></thead><tbody>
    ${data.alerts.slice(0, 300).map((a) => `<tr class="row" data-alert="${a.alert_id}"><td>${pill(a.status)}</td><td class="name"><b>${esc(a.name)}</b><small>${esc(a.entity_type)}</small></td><td class="code">${a.alert_id}</td>
      <td>${a.hits}${a.review ? ` <span class="issue-count">· ${a.review} to decide</span>` : ""}</td>
      <td><div class="dots">${a.marks.map((m) => `<i class="${m.decision} ${m.by}" title="${m.hit_id}: ${PLAIN[m.decision]}${m.by === "analyst" ? " (analyst)" : ""}"></i>`).join("")}</div></td><td>${esc(a.screened_at)}</td></tr>`).join("")}
  </tbody></table>${data.alerts.length > 300 ? `<p class="by card-pad">Showing 300 of ${data.alerts.length}. Search to narrow.</p>` : ""}` : `<p class="empty card-pad">Nothing here.</p>`}</div>`;
  main.querySelectorAll("tr.row").forEach((tr) => (tr.onclick = () => (location.hash = `#/alert/${tr.dataset.alert}`)));
  $("#q").onkeydown = (e) => { if (e.key === "Enter") location.hash = `#/queue?status=${status}&q=${encodeURIComponent(e.target.value)}`; };
}

/* ---------- case ---------- */
async function renderAlert(main, alertId, hitId) {
  const d = await api(`/api/alert/${alertId}`);
  if (!ui.alert || ui.alert.alert_id !== alertId) ui.tab = "issues";
  ui.alert = d;
  const hit = d.hits.find((h) => h.hit_id === hitId) || d.hits.find((h) => h.final.decision === "REVIEW") || d.hits[0];
  ui.hit = hit.hit_id;
  let queue = JSON.parse(store.get("ns-queue", "{}") || "{}");
  if ((queue.ids || []).indexOf(alertId) < 0) {
    const all = await api(`/api/alerts?status=${d.status}`);
    queue = { status: d.status, q: "", ids: all.alerts.map((a) => a.alert_id) };
    store.set("ns-queue", JSON.stringify(queue));
  }
  const pos = (queue.ids || []).indexOf(alertId);
  const prev = pos > 0 ? queue.ids[pos - 1] : null, next = pos >= 0 && pos < queue.ids.length - 1 ? queue.ids[pos + 1] : null;
  const scr = d.alert.customer || {};
  main.innerHTML = `
  <a class="crumb" href="#/queue?status=${esc(queue.status || "needs_you")}">← Queue${pos >= 0 ? ` · ${pos + 1} of ${queue.ids.length}` : ""}</a>
  <div class="case-head"><div><h1>${esc(scr.name || alertId)}</h1>
    <div class="case-meta">${pill(d.status)}<span class="code">${alertId}</span><span>${esc(scr.entity_type || "")}</span><span>Screened ${esc(d.alert.screened_at || "")}</span><span>${d.hits.length} hit(s)</span></div></div>
    <div style="display:flex;gap:8px;flex-wrap:wrap"><button class="btn" id="req">Draft information request</button>
      <a class="btn ${prev ? "" : "disabled"}" ${prev ? `href="#/alert/${prev}"` : ""} title="Previous alert in ${esc(STATUS[queue.status] || "the queue")}">‹ Previous</a><a class="btn ${next ? "" : "disabled"}" ${next ? `href="#/alert/${next}"` : ""} title="Next alert in ${esc(STATUS[queue.status] || "the queue")}">Next ›</a></div></div>
  <div class="case-grid">
    <div class="card hitlist">${d.hits.map((h) => {
      const open = h.issues.filter((i) => i.severity !== "info" && ["open", "requested"].includes(i.status)).length;
      return `<button data-hit="${h.hit_id}" class="${h.hit_id === hit.hit_id ? "on" : ""}"><b>${esc(h.name)}</b><span class="code">${h.hit_id} · ${esc((h.categories || []).join(", "))}</span>
        <div class="row2">${dchip(h.final.decision, h.final.by === "analyst" ? " · analyst" : "")}${open ? `<span class="issue-count">${open} issue${open > 1 ? "s" : ""}</span>` : ""}</div></button>`;
    }).join("")}</div>
    <div id="hitpane"></div>
  </div>
  <div id="hittabs"></div>
  <div class="card card-pad section"><h2>Audit trail</h2>${d.history.length ? `<ul class="activity">${d.history.map((a) => `<li><time>${when(a.at)}</time>${esc(a.text)}${a.note ? `<div class="by">“${esc(a.note)}”</div>` : ""}</li>`).join("")}</ul>` : `<p class="empty">No analyst actions on this alert yet. Engine decisions are in each hit.</p>`}</div>`;
  main.querySelectorAll(".hitlist button").forEach((b) => (b.onclick = () => { history.replaceState(null, "", `#/alert/${alertId}?hit=${b.dataset.hit}`); renderAlert(main, alertId, b.dataset.hit); }));
  $("#req").onclick = draftRequest;
  renderHit($("#hitpane"), hit);
}

function renderHit(pane, h) {
  const e = h.engine, a = h.analyst;
  const issuesOpen = h.issues.filter((i) => i.severity !== "info" && ["open", "requested"].includes(i.status)).length;
  const blockers = h.issues.filter((i) => i.severity === "blocker" && ["open", "requested"].includes(i.status)).length;
  const tabs = [["issues", `Issues`, h.issues.length], ["graph", "Link graph", ""], ["trail", "Evidence trail", ""]];
  if (h.memo) tabs.push(["memo", "Analyst memo", ""]);
  if (!tabs.find((t) => t[0] === ui.tab)) ui.tab = "issues";
  pane.innerHTML = `
  <div class="card card-pad">
    <div class="decision-banner"><div>
      <div class="by">Engine decision · rules from POLICY.md</div>
      <h2>${dchip(e.decision)} <span style="font-size:15px;font-weight:500;color:var(--ink-2)">${esc(e.reason_code_label)}</span></h2>
      <div class="code">${esc(e.reason_code)} · customer ${esc(e.customer_record_id || "none")}</div></div>
      <div style="text-align:right"><div class="by">Final</div>${dchip(h.final.decision)}<div class="by">${h.final.by === "analyst" ? `by ${esc(a.by)}, approved by ${esc(a.approver)}` : "engine decision stands"}</div></div></div>
    <p class="reason">${ids(e.reason)}</p>
    <div class="by">Evidence: ${e.evidence.map((x) => `<button class="idchip" data-rec="${x}">${x}</button>`).join(" ") || "none"}</div>
    ${h.position ? `<p class="by" style="margin-top:8px">Listed for: ${esc(h.position)}</p>` : ""}
  </div>
  <div class="section">${decidePanel(h, issuesOpen, blockers)}</div>`;
  $("#hittabs").innerHTML = `<div class="card card-pad section">
    <div class="tabs">${tabs.map(([k, label, n]) => `<button data-tab="${k}" class="${ui.tab === k ? "on" : ""}">${label}${n !== "" ? `<span class="n">${n}</span>` : ""}</button>`).join("")}
      <span class="by" style="margin-left:auto;align-self:center">${esc(h.name)} · ${h.hit_id}</span></div>
    <div id="tabbody"></div>
  </div>`;
  document.querySelectorAll("#hittabs [data-tab]").forEach((b) => (b.onclick = () => { ui.tab = b.dataset.tab; renderHit(pane, h); }));
  const body = $("#tabbody");
  if (ui.tab === "issues") renderIssues(body, h);
  if (ui.tab === "graph") renderGraph(body, h.graph);
  if (ui.tab === "trail") renderTrail(body, h.stages);
  if (ui.tab === "memo") renderMemo(body, h);
  wireDecide(pane, h);
}

function decidePanel(h, issuesOpen, blockers) {
  const a = h.analyst;
  if (a && a.approval === "pending") {
    const mine = me() && me().toLowerCase() === (a.by || "").toLowerCase();
    return `<div class="approval"><h3 style="margin:0">Waiting for a second analyst</h3>
      <p style="margin:6px 0">${esc(a.by)} proposes <b>${PLAIN[a.decision]}</b> (engine said ${PLAIN[a.engine_decision]}). “${esc(a.note)}”</p>
      ${mine ? `<p class="by">You made this decision. Another analyst must approve it.</p>` : `
      <textarea class="field" id="ap-note" placeholder="Note for the audit trail (required to send back)"></textarea>
      <div style="display:flex;gap:8px;margin-top:8px"><button class="btn primary" id="ap-yes">Approve</button><button class="btn" id="ap-no">Send back</button></div>`}</div>`;
  }
  const engineReview = h.engine.decision === "REVIEW";
  const title = engineReview ? "Your decision" : "Challenge the engine";
  const sub = engineReview ? "No rule could settle this hit. Decide it, then a second analyst approves." : "The engine decided this hit. Override it only with a reason; a second analyst approves.";
  const back = a && a.approval === "rejected" ? `<div class="warn-line">Sent back by ${esc(a.approver)}: “${esc(a.approver_note)}”</div>` : "";
  const approved = a && a.approval === "approved" ? `<div class="by" style="margin-bottom:8px">Last decision approved: ${PLAIN[a.decision]} by ${esc(a.by)}, approved by ${esc(a.approver)}.</div>` : "";
  return `<div class="decide"><h3>${title}</h3><div class="by">${sub}</div>${back}${approved}
    <div class="choices">
      <button class="choice c ${ui.choice === "DIFFERENT_ENTITY" ? "on" : ""}" data-choice="DIFFERENT_ENTITY"><b>Clear · different person</b><small>A fact contradicts the match</small></button>
      <button class="choice s ${ui.choice === "SAME_ENTITY" ? "on" : ""}" data-choice="SAME_ENTITY"><b>Escalate · same person</b><small>Send to compliance</small></button>
    </div>
    <textarea class="field" id="dec-note" placeholder="Reason, citing the records you relied on (for example: KYC-358C76 shows born 2007)"></textarea>
    ${ui.choice === "DIFFERENT_ENTITY" && blockers ? `<div class="warn-line">${blockers} blocking issue(s) are still open on this hit. Resolve them, or explain in your reason why clearing is safe.</div>` : ""}
    ${issuesOpen && ui.choice !== "DIFFERENT_ENTITY" ? `<div class="by" style="margin-top:6px">${issuesOpen} issue(s) still open on this hit.</div>` : ""}
    <div style="margin-top:10px"><button class="btn primary" id="dec-go" ${ui.choice ? "" : "disabled"}>Submit for approval</button></div></div>`;
}

function wireDecide(pane, h) {
  pane.querySelectorAll("[data-choice]").forEach((b) => (b.onclick = () => { ui.choice = b.dataset.choice; renderHit(pane, h); }));
  const go = $("#dec-go");
  if (go) go.onclick = async () => {
    const r = await api("/api/decide", { hit_id: h.hit_id, decision: ui.choice, note: $("#dec-note").value, by: me() });
    if (!r.ok) return toast(r.error, true);
    ui.choice = null; toast("Decision submitted. A second analyst must approve it."); reloadCase();
  };
  const yes = $("#ap-yes"), no = $("#ap-no");
  const send = async (approve) => {
    const r = await api("/api/approve", { hit_id: h.hit_id, approve, note: ($("#ap-note") || {}).value || "", by: me() });
    if (!r.ok) return toast(r.error, true);
    toast(approve ? "Approved. The decision is final." : "Sent back to the analyst."); reloadCase();
  };
  if (yes) yes.onclick = () => send(true);
  if (no) no.onclick = () => send(false);
}
function reloadCase() { renderAlert($("#main"), ui.alert.alert_id, ui.hit).then(refreshState); }

/* ---------- issues ---------- */
function renderIssues(body, h) {
  if (!h.issues.length) { body.innerHTML = `<p class="empty">No discrepancies found in the records for this hit.</p>`; return; }
  const order = { blocker: 0, warning: 1, info: 2 };
  const list = [...h.issues].sort((x, y) => order[x.severity] - order[y.severity]);
  body.innerHTML = `<p class="by" style="margin-top:0">Discrepancies found by comparing the customer's records, identity checks and the list profile. Blockers stop a safe clearance.</p>` +
    list.map((i) => {
      const done = ["resolved", "accepted", "noted"].includes(i.status);
      return `<div class="issue ${i.severity} ${done ? "done" : ""}" data-issue="${i.issue_id}">
        <header><div><span class="sev ${i.severity}">${i.severity}</span><h4>${esc(i.title)}</h4></div><span class="ist ${i.status}">${ISSUE_STATUS[i.status] || i.status}</span></header>
        <p>${ids(i.detail)}</p>
        ${i.evidence.length ? `<div class="by">Records: ${i.evidence.map((x) => `<button class="idchip" data-rec="${x}">${x}</button>`).join(" ")}</div>` : ""}
        <div class="suggest"><b>Suggested:</b> ${esc(i.suggested)}</div>
        ${i.note ? `<div class="by">${esc(ISSUE_STATUS[i.status])} by ${esc(i.by)} · ${when(i.at)}: “${esc(i.note)}”</div>` : ""}
        ${i.severity === "info" ? "" : `<div class="issue-actions"><input class="field" placeholder="Note (required to resolve or accept)">
          ${i.status !== "requested" ? `<button class="btn small" data-set="requested">Info requested</button>` : ""}
          ${done ? `<button class="btn small" data-set="open">Reopen</button>` : `<button class="btn small clear" data-set="resolved">Resolved</button><button class="btn small" data-set="accepted">Accept risk</button>`}</div>`}
      </div>`;
    }).join("");
  body.querySelectorAll("[data-set]").forEach((b) => (b.onclick = async () => {
    const card = b.closest(".issue");
    const r = await api("/api/issue", { hit_id: h.hit_id, issue_id: card.dataset.issue, status: b.dataset.set, note: $("input", card).value, by: me() });
    if (!r.ok) return toast(r.error, true);
    ui.tab = "issues"; toast("Issue updated."); reloadCase();
  }));
}

async function draftRequest() {
  const r = await api("/api/request", { alert_id: ui.alert.alert_id, by: me() });
  if (!r.ok) return toast(r.error, true);
  openDrawer("Information request", `<p class="badge-draft">${esc(r.label)}</p><pre class="draft" id="draft-text">${esc(r.text)}</pre>
    <button class="btn primary" id="copy">Copy text</button><p class="by">Namesake never contacts anyone. Copy it into your case system or email yourself.</p>`, "Draft for your case system");
  $("#copy").onclick = () => { navigator.clipboard?.writeText(r.text); toast("Copied."); };
}

/* ---------- trail and memo ---------- */
function renderTrail(body, stages) {
  body.innerHTML = `<div class="stages">${(stages || []).map((s) => {
    if (s.rows) return `<div class="stage"><h4>${s.n} · ${esc(s.title)}</h4><table class="cmp">${s.rows.map((r) => `<tr><td><b>${esc(r.field)}</b> <span class="mark ${r.mark}">${esc(r.mark)}</span><br>Customer: ${ids(r.customer)}<br>List: ${ids(r.list)}</td></tr>`).join("")}</table></div>`;
    if (s.key === "decision") return `<div class="stage"><h4>${s.n} · ${esc(s.title)}</h4>${dchip(s.decision)}<p>${ids(s.reason)}</p></div>`;
    return `<div class="stage"><h4>${s.n} · ${esc(s.title)}</h4><dl>${(s.lines || []).map((l) => `<dt>${esc(l.label)}</dt><dd>${ids(l.value)}</dd>`).join("")}</dl></div>`;
  }).join("")}</div>`;
}
function renderMemo(body, h) {
  const m = h.memo;
  const list = (xs) => `<ul>${(xs || []).map((x) => `<li>${ids(x)}</li>`).join("")}</ul>`;
  body.innerHTML = `<div class="memo"><h4>What agrees</h4>${list(m.agrees)}<h4>What contradicts</h4>${list(m.contradicts)}<h4>What is missing</h4>${list(m.missing)}
    <h4>What would settle it</h4><p>${esc(m.would_settle)}</p><h4>Sources checked</h4>${list(m.sources)}
    ${(m.rejected || []).length ? `<h4>Search results rejected as namesakes</h4><ul>${m.rejected.map((r) => `<li>${ids(r.id)}: ${esc(r.reason)}</li>`).join("")}</ul>` : ""}
    ${ui.alert.draft_available ? `<div style="margin-top:12px"><button class="btn" id="grok">Draft wording with Grok</button></div><div id="grok-out"></div>` : ""}</div>`;
  const g = $("#grok");
  if (g) g.onclick = async () => {
    g.disabled = true; g.textContent = "Drafting…";
    const r = await api("/api/draft", { hit_id: h.hit_id });
    g.disabled = false; g.textContent = "Draft wording with Grok";
    $("#grok-out").innerHTML = r.ok ? `<p class="badge-draft">${esc(r.label)}</p><pre class="draft">${esc(r.text)}</pre>` : `<p class="warn-line">${esc(r.error)}</p>`;
  };
}

/* ---------- link graph ---------- */
const COLS = ["Alert", "Link", "Customer records", "Identity", "Decision", "List hit", "Search results"];
function renderGraph(body, g) {
  const W = 142, H = 48, GX = 40, GY = 14, TOP = 36, LEFT = 12;
  const cols = {}; g.nodes.forEach((n) => (cols[n.col] = cols[n.col] || []).push(n));
  const rows = Math.max(...Object.values(cols).map((c) => c.length), 1);
  const height = TOP + rows * (H + GY) + 10;
  const pos = {};
  Object.entries(cols).forEach(([c, list]) => {
    const off = ((rows - list.length) * (H + GY)) / 2;
    list.forEach((n, i) => (pos[n.id] = { x: LEFT + c * (W + GX), y: TOP + off + i * (H + GY) }));
  });
  const width = LEFT * 2 + 7 * W + 6 * GX;
  const edges = g.edges.map((e) => {
    const a = pos[e.from], b = pos[e.to]; if (!a || !b) return "";
    const fwd = a.x <= b.x;
    const x1 = fwd ? a.x + W : a.x, y1 = a.y + H / 2, x2 = fwd ? b.x : b.x + W, y2 = b.y + H / 2;
    const same = Math.abs(a.x - b.x) < 1;
    const d = same ? `M${a.x + W},${y1} C${a.x + W + 40},${y1} ${b.x + W + 40},${y2} ${b.x + W},${y2}`
      : `M${x1},${y1} C${(x1 + x2) / 2},${y1} ${(x1 + x2) / 2},${y2} ${x2},${y2}`;
    const cls = e.label === "decided" ? "decided" : e.style;
    const lx = same ? a.x + W + 34 : (x1 + x2) / 2, ly = (y1 + y2) / 2 - 4;
    const show = e.style === "merge" || ["rejected", "expired"].includes(e.label);
    return `<path class="g-edge ${cls}" d="${d}"><title>${esc(e.label)}</title></path>${show ? `<text class="g-label" x="${lx}" y="${ly}" text-anchor="middle">${esc(e.label)}</text>` : ""}`;
  }).join("");
  const nodes = g.nodes.map((n) => {
    const p = pos[n.id], cls = ["g-node", n.kind, n.state, n.cited ? "cited" : ""].join(" ");
    const clip = (s, k) => (s && s.length > k ? s.slice(0, k - 1) + "…" : s || "");
    return `<g class="${cls}" data-rec="${esc(n.id)}" tabindex="0" role="button" aria-label="${esc(n.label)} ${esc(n.id)}">
      <rect x="${p.x}" y="${p.y}" width="${W}" height="${H}" rx="8"/>
      <text class="t" x="${p.x + 9}" y="${p.y + 19}">${esc(clip(n.label, 19))}</text>
      <text class="s" x="${p.x + 9}" y="${p.y + 36}">${esc(clip(n.sub || n.id, n.cited ? 15 : 24))}</text>
      ${n.cited ? `<text class="g-tag" x="${p.x + W - 7}" y="${p.y + 36}" text-anchor="end">DECIDED</text>` : ""}</g>`;
  }).join("");
  const heads = COLS.map((c, i) => `<text class="g-col" x="${LEFT + i * (W + GX)}" y="22">${c}</text>`).join("");
  body.innerHTML = `<p class="by" style="margin-top:0">How this alert reaches the customer and the listed person. Click any box to open its record.</p>
    <div class="graph-wrap"><svg class="graph" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" style="max-width:100%;height:auto;min-width:900px">${heads}${edges}${nodes}</svg></div>
    <div class="graph-key"><a class="btn small" href="#/graph?focus=${esc((g.nodes.find((n) => n.kind === "hit") || {}).id || "")}">Explore in knowledge graph</a><span><i></i>cited in the decision</span><span><i class="m"></i>same person (phone + date of birth, or document)</span><span><i class="x"></i>not used: other holder, rejected check, namesake</span></div>`;
  body.querySelectorAll(".g-node").forEach((el) => el.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") el.dispatchEvent(new Event("click", { bubbles: true })); }));
}


/* ---------- knowledge graph (whole data room) ---------- */
const KG_COLORS = { alert: "#2f6fdf", hit: "#7a4cc2", customer: "#137a4b", account: "#5c6b80", check: "#a35d00", note: "#8a6d3b", search: "#94a0b4" };
const KG_EXAMPLES = [["A-0487B9", "Two records, one person"], ["CUS-377745", "Joint account, shared phone"], ["A-D81CF0", "15 hits on one alert"], ["H-FF3096", "Hit left for review"]];
const kg = { nodes: new Map(), edges: new Map(), expanded: new Set(), selected: null, scale: 1, tx: 0, ty: 0 };

async function renderKG(main, focus) {
  focus = (focus || "A-0487B9").toUpperCase();
  main.innerHTML = `
  <div class="page-head"><div><h1>Knowledge graph</h1><p>Every customer, account, identity check, note, alert, list hit and search result, and how they connect. Click a node to see it; double-click (or Expand) to bring in its connections.</p></div>
    <div style="display:flex;gap:8px"><input class="field search" id="kg-q" placeholder="Any id: CUS-, ACC-, KYC-, NOTE-, A-, H-, SR-" value="${esc(focus)}"><button class="btn primary" id="kg-go">Show</button></div></div>
  <div class="kg-examples">Try: ${KG_EXAMPLES.map(([id, t]) => `<a href="#/graph?focus=${id}">${t} <span class="code">${id}</span></a>`).join("")}</div>
  <div class="kg-grid">
    <div class="card kg-canvas"><svg id="kg-svg" class="graph"></svg>
      <div class="kg-tools"><button class="btn small" id="kg-fit">Fit</button><button class="btn small" id="kg-reset">Start again</button><span class="by" id="kg-count"></span></div></div>
    <div class="card card-pad kg-side" id="kg-side"></div>
  </div>
  <div class="graph-key">${Object.entries(KG_COLORS).map(([k, c]) => `<span><b style="display:inline-block;width:10px;height:10px;border-radius:50%;background:${c};margin-right:5px"></b>${k}</span>`).join("")}
    <span><i class="m"></i>same person</span><span><i class="x"></i>not the same / not used</span></div>`;
  $("#kg-go").onclick = () => (location.hash = `#/graph?focus=${encodeURIComponent($("#kg-q").value.trim())}`);
  $("#kg-q").onkeydown = (e) => { if (e.key === "Enter") $("#kg-go").click(); };
  $("#kg-fit").onclick = () => { kgFit(); kgDraw(); };
  $("#kg-reset").onclick = () => { kgClear(); kgExpand(focus, true); };
  if (!kg.nodes.has(focus)) kgClear();
  await kgExpand(focus, true);
}
function kgClear() { kg.nodes.clear(); kg.edges.clear(); kg.expanded.clear(); kg.selected = null; }
async function kgExpand(id, select) {
  let d;
  try { d = await api(`/api/kg/${encodeURIComponent(id)}`); }
  catch (e) { toast(e.message, true); return; }
  const base = kg.nodes.get(d.node.id);
  if (!base) kg.nodes.set(d.node.id, { ...d.node, x: 0, y: 0, vx: 0, vy: 0 });
  const c = kg.nodes.get(d.node.id);
  d.neighbours.forEach((nb, i) => {
    if (!kg.nodes.has(nb.node.id)) {
      const a = (2 * Math.PI * i) / Math.max(d.neighbours.length, 1);
      kg.nodes.set(nb.node.id, { ...nb.node, x: c.x + 140 * Math.cos(a), y: c.y + 140 * Math.sin(a), vx: 0, vy: 0 });
    }
    const key = [d.node.id, nb.node.id].sort().join("|");
    if (!kg.edges.has(key)) kg.edges.set(key, { a: d.node.id, b: nb.node.id, rel: nb.rel, style: nb.style });
  });
  kg.expanded.add(d.node.id);
  if (select) kg.selected = d.node.id;
  kgLayout(); kgFit(); kgDraw(); kgSide();
}
function kgLayout() {
  const ns = [...kg.nodes.values()], es = [...kg.edges.values()];
  for (let it = 0; it < 260; it++) {
    const t = 1 - it / 260;
    for (let i = 0; i < ns.length; i++) for (let j = i + 1; j < ns.length; j++) {
      const a = ns[i], b = ns[j]; let dx = a.x - b.x, dy = a.y - b.y; let d2 = dx * dx + dy * dy || 0.01;
      const f = 9000 / d2, d = Math.sqrt(d2); dx /= d; dy /= d;
      a.vx += dx * f; a.vy += dy * f; b.vx -= dx * f; b.vy -= dy * f;
    }
    es.forEach((e) => {
      const a = kg.nodes.get(e.a), b = kg.nodes.get(e.b); if (!a || !b) return;
      const dx = b.x - a.x, dy = b.y - a.y, d = Math.sqrt(dx * dx + dy * dy) || 1, f = (d - 150) * 0.04;
      a.vx += (dx / d) * f; a.vy += (dy / d) * f; b.vx -= (dx / d) * f; b.vy -= (dy / d) * f;
    });
    ns.forEach((n) => { n.vx -= n.x * 0.002; n.vy -= n.y * 0.002; n.x += Math.max(-30, Math.min(30, n.vx)) * t; n.y += Math.max(-30, Math.min(30, n.vy)) * t; n.vx *= 0.5; n.vy *= 0.5; });
  }
}
function kgFit() {
  const ns = [...kg.nodes.values()]; if (!ns.length) return;
  const svg = $("#kg-svg"), W = svg.clientWidth || 900, H = svg.clientHeight || 620;
  const xs = ns.map((n) => n.x), ys = ns.map((n) => n.y);
  const minX = Math.min(...xs) - 90, maxX = Math.max(...xs) + 90, minY = Math.min(...ys) - 50, maxY = Math.max(...ys) + 50;
  kg.scale = Math.min(1.4, W / (maxX - minX), H / (maxY - minY));
  kg.tx = W / 2 - ((minX + maxX) / 2) * kg.scale; kg.ty = H / 2 - ((minY + maxY) / 2) * kg.scale;
}
function kgDraw() {
  const svg = $("#kg-svg"); if (!svg) return;
  const clip = (s, k) => (s && s.length > k ? s.slice(0, k - 1) + "…" : s || "");
  const P = (n) => [n.x * kg.scale + kg.tx, n.y * kg.scale + kg.ty];
  const sel = kg.selected;
  const edges = [...kg.edges.values()].map((e) => {
    const a = kg.nodes.get(e.a), b = kg.nodes.get(e.b); if (!a || !b) return "";
    const [x1, y1] = P(a), [x2, y2] = P(b), on = sel && (e.a === sel || e.b === sel);
    return `<line class="g-edge ${e.style || ""} ${on ? "decided" : ""}" x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}"><title>${esc(e.rel)}</title></line>
      ${on ? `<text class="g-label" x="${(x1 + x2) / 2}" y="${(y1 + y2) / 2 - 4}" text-anchor="middle">${esc(clip(e.rel, 34))}</text>` : ""}`;
  }).join("");
  const nodes = [...kg.nodes.values()].map((n) => {
    const [x, y] = P(n), r = n.id === sel ? 13 : 10, col = KG_COLORS[n.kind] || "#888";
    const dim = n.kind === "check" && n.state && n.state !== "approved";
    return `<g class="kg-node ${n.id === sel ? "sel" : ""}" data-kg="${esc(n.id)}" tabindex="0" role="button" aria-label="${esc(n.label)} ${esc(n.id)}">
      <circle cx="${x}" cy="${y}" r="${r}" fill="${col}" ${dim ? 'fill-opacity=".35"' : ""} stroke="${kg.expanded.has(n.id) ? "var(--ink)" : "var(--surface)"}" stroke-width="2.5"/>
      <text class="kg-t" x="${x}" y="${y + r + 13}" text-anchor="middle">${esc(clip(n.label, 22))}</text>
      <text class="kg-s" x="${x}" y="${y + r + 25}" text-anchor="middle">${esc(n.id)}</text></g>`;
  }).join("");
  svg.innerHTML = edges + nodes;
  $("#kg-count").textContent = `${kg.nodes.size} nodes · ${kg.edges.size} links`;
  svg.querySelectorAll(".kg-node").forEach((g) => {
    g.onclick = () => { kg.selected = g.dataset.kg; kgDraw(); kgSide(); };
    g.ondblclick = () => kgExpand(g.dataset.kg, true);
    g.onkeydown = (e) => { if (e.key === "Enter") kgExpand(g.dataset.kg, true); else if (e.key === " ") { e.preventDefault(); g.onclick(); } };
  });
}
async function kgSide() {
  const side = $("#kg-side"), n = kg.nodes.get(kg.selected); if (!side || !n) return;
  const links = [...kg.edges.values()].filter((e) => e.a === n.id || e.b === n.id)
    .map((e) => { const o = kg.nodes.get(e.a === n.id ? e.b : e.a); return `<li><a href="#" data-pick="${esc(o.id)}">${esc(o.label)}</a> <span class="code">${esc(o.id)}</span><div class="by">${esc(e.rel)}</div></li>`; }).join("");
  const open = n.id.startsWith("A-") ? `#/alert/${n.id}` : n.id.startsWith("H-") ? `#/alert/${(ui.alertOfHit || {})[n.id] || ""}` : "";
  side.innerHTML = `<div class="by">${esc(n.kind)}</div><h2 style="margin:2px 0 4px">${esc(n.label)}</h2><div class="code">${esc(n.id)}</div><p class="by">${esc(n.sub)}</p>
    <div style="display:flex;gap:6px;flex-wrap:wrap;margin:10px 0">${kg.expanded.has(n.id) ? `<span class="pill d-DIFFERENT_ENTITY">Expanded</span>` : `<button class="btn small primary" id="kg-exp">Expand connections</button>`}
      <button class="btn small" data-rec="${esc(n.id)}">Open record</button>${n.id.startsWith("A-") ? `<a class="btn small" href="${open}">Open case</a>` : ""}</div>
    <h4 style="margin:14px 0 6px;font-size:13px;color:var(--ink-3)">Connections shown (${links ? links.split("<li>").length - 1 : 0})</h4><ul class="activity">${links}</ul>`;
  const ex = $("#kg-exp"); if (ex) ex.onclick = () => kgExpand(n.id, true);
  side.querySelectorAll("[data-pick]").forEach((a) => (a.onclick = (e) => { e.preventDefault(); kg.selected = a.dataset.pick; kgDraw(); kgSide(); }));
}
window.addEventListener("resize", () => { if ($("#kg-svg")) { kgFit(); kgDraw(); } });

/* ---------- runs ---------- */
async function renderRuns(main, notice) {
  setNav("runs");
  const s = ui.state || (await api("/api/state"));
  main.innerHTML = `${notice ? `<div class="notice">${esc(notice)}</div>` : ""}
  <div class="page-head"><div><h1>Runs</h1><p>Each run screens a data folder with the scored engine (<span class="code">system/run</span>) and keeps its own analyst actions.</p></div></div>
  <div class="card card-pad"><h2>New screening run</h2>
    <div style="display:flex;gap:8px;flex-wrap:wrap"><input class="field" id="data" style="flex:1;min-width:300px" placeholder="/path/to/data folder (the one with hits.jsonl)" value="${esc(s.default_data || "")}">
    <button class="btn primary" id="go">Run screening</button></div>
    <div id="job"></div></div>
  <div class="card section"><table class="list"><thead><tr><th>Run</th><th>Data folder</th><th>Hits</th><th>Outcome</th><th>Took</th><th></th></tr></thead><tbody>
    ${s.runs.map((r) => `<tr><td><b>${esc(r.label)}</b><div class="code">${esc(r.run_id)}</div></td><td class="code">${esc(r.data_dir)}</td><td>${r.hits ?? "–"}</td>
      <td>${r.totals ? `${dchip("DIFFERENT_ENTITY", " " + r.totals.DIFFERENT_ENTITY)} ${dchip("SAME_ENTITY", " " + r.totals.SAME_ENTITY)} ${dchip("REVIEW", " " + r.totals.REVIEW)}` : esc(r.state)}</td>
      <td>${r.seconds != null ? r.seconds + " s" : ""}</td><td>${r.state === "done" ? (r.run_id === s.current ? `<span class="by">Open</span>` : `<button class="btn small" data-open="${r.run_id}">Open</button>`) : esc(r.state)}</td></tr>`).join("") || `<tr><td colspan="6" class="empty">No runs yet.</td></tr>`}
  </tbody></table></div>`;
  $("#go").onclick = async () => {
    const r = await api("/api/run", { data_dir: $("#data").value });
    if (!r.ok) return toast(r.error, true);
    pollJob();
  };
  main.querySelectorAll("[data-open]").forEach((b) => (b.onclick = async () => {
    b.textContent = "Loading…"; const r = await api("/api/open", { run_id: b.dataset.open });
    if (!r.ok) return toast(r.error, true); location.hash = "#/overview";
  }));
  if (s.job && s.job.state === "running") pollJob();
}
async function pollJob() {
  const s = await api("/api/state"), j = s.job, box = $("#job");
  if (!box) { if (j.state === "running") setTimeout(pollJob, 1000); else if (j.state === "done") refreshState(); return; }
  if (j.state === "running") {
    const pct = j.total ? Math.round((100 * j.done) / j.total) : 3;
    box.innerHTML = `<div class="progress"><span style="width:${pct}%"></span></div><div class="by">${esc(j.phase || "Starting")}${j.total ? ` · ${j.done} of ${j.total} hits` : ""}</div>`;
    setTimeout(pollJob, 700);
  } else if (j.state === "done") {
    box.innerHTML = `<p class="by">Finished ${j.done} hits in ${j.seconds} s. Opening…</p>`;
    await api("/api/open", { run_id: j.run_id }); location.hash = "#/overview"; route();
  } else if (j.state === "failed") {
    box.innerHTML = `<p class="warn-line">${esc(j.error)}</p>`;
  }
}

/* ---------- records drawer ---------- */
function openDrawer(title, html, sub = "What the auditor sees") {
  $("#drawer-sub").textContent = sub; $("#drawer-title").textContent = title; $("#drawer-body").innerHTML = html;
  $("#drawer").classList.add("open"); $("#drawer").setAttribute("aria-hidden", "false");
}
function closeDrawer() { $("#drawer").classList.remove("open"); $("#drawer").setAttribute("aria-hidden", "true"); }
async function openRecord(id) {
  if (!/^(CUS|KYC|NOTE|SR|H|A|ACC|APP)-/.test(id)) return;
  try {
    const r = await api(`/api/record/${encodeURIComponent(id)}`);
    const rows = Object.entries(r.fields || {}).map(([k, v]) => `<tr><th>${esc(k)}</th><td>${esc(typeof v === "object" && v !== null ? JSON.stringify(v, null, 1) : v ?? "")}</td></tr>`).join("");
    openDrawer(id, `<table class="fields">${rows}</table>`);
  } catch (e) { toast(`${id} is not in this data folder.`, true); }
}

/* ---------- boot ---------- */
document.addEventListener("click", (e) => {
  const link = e.target.closest('a[href^="#"]');
  if (link && link.getAttribute("href") === location.hash) { e.preventDefault(); ui.choice = null; route(); return; }
  const rec = e.target.closest("[data-rec]");
  if (rec) { e.preventDefault(); openRecord(rec.dataset.rec); }
});
$("#drawer").addEventListener("click", (e) => { if (e.target.id === "drawer") closeDrawer(); });
$("#drawer-close").onclick = closeDrawer;
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeDrawer(); });
document.querySelectorAll(".theme button").forEach((b) => (b.onclick = () => applyTheme(b.dataset.theme)));
matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => applyTheme(store.get("ns-theme", "light")));
$("#analyst").value = store.get("ns-analyst", "");
$("#analyst").oninput = (e) => store.set("ns-analyst", e.target.value.trim());
applyTheme(store.get("ns-theme", "light"));
window.addEventListener("hashchange", () => { ui.choice = null; route(); });
if (!location.hash) location.hash = "#/overview"; else route();
