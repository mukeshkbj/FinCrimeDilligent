"use strict";

const SPEEDS = { 0.5: 3200, 1: 1600, 2: 800 };
const state = {
  steps: [],
  index: 0,
  view: "workflow",
  timer: null,
  playing: false,
  speed: 1,
  mode: "step",
  labels: { decisions: {}, reason_codes: {}, customer: {} },
};

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;",
  }[ch]));
}

function withChips(value) {
  const text = String(value ?? "");
  const re = /\b((?:CUS|KYC|NOTE|SR|ACC|APP)-[0-9A-Za-z]+)\b/g;
  let html = "";
  let last = 0;
  let match;
  while ((match = re.exec(text))) {
    html += esc(text.slice(last, match.index));
    html += `<button type="button" class="chip" data-record="${esc(match[1])}">${esc(match[1])}</button>`;
    last = match.index + match[0].length;
  }
  html += esc(text.slice(last));
  return html;
}

function chipId(id) {
  return `<button type="button" class="chip" data-record="${esc(id)}">${esc(id)}</button>`;
}

function $(id) { return document.getElementById(id); }

function outcomeClass(text) {
  const value = String(text || "");
  if (value === "DIFFERENT_ENTITY" || value.startsWith("DIFFERENT_ENTITY") || /cleared/i.test(value)) return "cleared";
  if (value === "SAME_ENTITY" || value.startsWith("SAME_ENTITY") || /compliance|kept open/i.test(value)) return "kept";
  return "review";
}

function plainFrom(map, code) {
  const table = (state.labels && state.labels[map]) || {};
  return table[code] || "";
}

function codeWithPlain(code, map) {
  if (!code) return "";
  const plain = plainFrom(map, code);
  if (!plain || plain === code) return code;
  return `${code} · ${plain}`;
}

function codeTone(code, map) {
  if (map === "decisions") {
    if (code === "DIFFERENT_ENTITY") return "cleared";
    if (code === "SAME_ENTITY") return "kept";
    if (code === "REVIEW") return "review";
  }
  if (map === "reason_codes") return "reason";
  if (map === "customer") return "customer";
  return "neutral";
}

/** HTML: monospace code badge + English. Safe for innerHTML. */
function codeBadgeHtml(code, map, fallback) {
  if (!code) return esc(fallback || "not available");
  const plain = plainFrom(map, code);
  const tone = codeTone(code, map);
  const badge = `<span class="code-badge code-badge-${tone}" title="${esc(codeWithPlain(code, map) || code)}">${esc(code)}</span>`;
  if (!plain || plain === code) return badge;
  return `${badge} <span class="code-plain">${esc(plain)}</span>`;
}

function plainDecision(decision) {
  return plainFrom("decisions", decision) || decision || "";
}

function decisionLabel(decision) {
  return codeWithPlain(decision, "decisions");
}

function reasonCodeLabel(code) {
  return codeWithPlain(code, "reason_codes");
}

function decisionBadge(decision) {
  return codeBadgeHtml(decision, "decisions");
}

function reasonBadge(code) {
  return codeBadgeHtml(code, "reason_codes");
}

function customerBadge(customerId) {
  if (!customerId) return esc("not available");
  if (customerId === "AMBIGUOUS") return codeBadgeHtml(customerId, "customer");
  return `<span class="code-badge code-badge-id">${esc(customerId)}</span>`;
}

function customerLabel(customerId) {
  if (!customerId) return "not available";
  if (customerId === "AMBIGUOUS") return codeWithPlain(customerId, "customer");
  return customerId;
}

function renderGlossary(labels) {
  const host = $("glossary-list");
  if (!host || !labels) return;
  const blocks = [
    ["Decisions", labels.decisions || {}],
    ["Reason codes", labels.reason_codes || {}],
    ["Customer record", labels.customer || {}],
  ];
  const extras = [
    ["Sanctions", "Government lists of people and companies banks must not deal with."],
    ["PEP", "Politically exposed person — a public official or family member, higher corruption risk."],
    ["Screening hit", "A watchlist profile whose name looks like one of our customers."],
    ["Alert", "One customer's hits grouped together."],
    ["J/E/V", "Judge / Evaluate / Verify — three checks on every hit. Pass means they agreed; downgraded means a clearance or confirm was pulled back to REVIEW."],
    ["Judge", "The rules decision (SAME_ENTITY, DIFFERENT_ENTITY, or REVIEW)."],
    ["Evaluate", "An independent re-check of name agreement and date comparison."],
    ["Verify", "Checks that the reason code fits the decision and every cited id exists in the files."],
    ["SAR", "Suspicious Activity Report filed with the UK National Crime Agency; a confirmed match may lead to one."],
  ];
  const mapFor = { Decisions: "decisions", "Reason codes": "reason_codes", "Customer record": "customer" };
  const codeItems = blocks.map(([title, table]) => {
    const map = mapFor[title] || "reason_codes";
    const rows = Object.entries(table).map(([code]) =>
      `<li class="glossary-code">${codeBadgeHtml(code, map)}</li>`
    ).join("");
    return `<li class="glossary-group"><strong>${esc(title)}</strong><ul>${rows}</ul></li>`;
  }).join("");
  const extraItems = extras.map(([term, plain]) =>
    `<li><strong>${esc(term)}.</strong> ${esc(plain)}</li>`
  ).join("");
  host.innerHTML = `${codeItems}${extraItems}`;
}

function renderFilters() {
  const host = $("filters");
  if (!host) return;
  const buttons = [
    ["review", "REVIEW", true],
    ["review_name_dob", null, false],
    ["cleared", "DIFFERENT_ENTITY", false],
    ["kept", "SAME_ENTITY", false],
  ];
  host.innerHTML = buttons.map(([filter, decision, primary]) => {
    const cls = primary ? ' class="primary"' : "";
    const label = decision
      ? decisionBadge(decision)
      : esc("Name and date agree");
    return `<button type="button" data-filter="${esc(filter)}"${cls}>${label}</button>`;
  }).join("");
  host.querySelectorAll("button").forEach((button) => {
    button.onclick = () => loadQueue(button.dataset.filter);
  });
}

async function openRecord(recordId) {
  const panel = $("record-panel");
  if (!panel || !recordId) return;
  try {
    const body = await getJSON("/api/record/" + encodeURIComponent(recordId));
    $("record-title").textContent = body.title || "What the auditor sees";
    const rows = Object.entries(body.fields || {})
      .filter(([, value]) => value !== null && value !== undefined && value !== "")
      .map(([key, value]) => `<tr><th>${esc(key)}</th><td>${esc(typeof value === "object" ? JSON.stringify(value) : value)}</td></tr>`)
      .join("");
    $("record-fields").innerHTML = `<p class="meta">${esc(body.id)}</p><table>${rows || "<tr><td>No fields</td></tr>"}</table>`;
    $("record-raw").textContent = JSON.stringify(body.raw || body.fields || {}, null, 2);
    panel.hidden = false;
  } catch (error) {
    $("ticker").textContent = "That record could not be opened.";
  }
}

function bindChips(root) {
  if (!root) return;
  root.querySelectorAll("[data-record]").forEach((button) => {
    button.onclick = (event) => {
      event.preventDefault();
      openRecord(button.dataset.record);
    };
  });
}

async function getJSON(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error("The recorded file could not be read.");
  return response.json();
}

function applyTheme(choice) {
  const root = document.documentElement;
  const buttons = document.querySelectorAll(".theme button");
  buttons.forEach((button) => button.setAttribute("aria-pressed", button.dataset.theme === choice ? "true" : "false"));
  if (choice === "system") {
    const dark = window.matchMedia("(prefers-color-scheme: dark)").matches;
    root.dataset.theme = dark ? "dark" : "light";
  } else {
    root.dataset.theme = choice;
  }
  try { localStorage.setItem("desk-theme", choice); } catch (error) { /* storage blocked */ }
}

function renderFunnel(summary) {
  const funnel = summary.funnel || {};
  const steps = [
    [funnel.hits, "Hits"],
    [funnel.customer_found, "Customer found"],
  ];
  const outcomes = [
    ["cleared", funnel.cleared, "DIFFERENT_ENTITY"],
    ["kept", funnel.kept_open, "SAME_ENTITY"],
    ["review", funnel.review, "REVIEW"],
  ];
  const main = steps.map(([count, label]) =>
    `<div class="funnel-step"><strong>${esc(count)}</strong><span>${esc(label)}</span></div>`
  ).join('<span class="funnel-arrow" aria-hidden="true">→</span>');
  const split = outcomes.map(([kind, count, code]) =>
    `<div class="outcome-tile ${kind}"><strong>${esc(count)}</strong>${decisionBadge(code)}</div>`
  ).join("");
  $("funnel-row").innerHTML = `${main}<span class="funnel-arrow" aria-hidden="true">→</span><div class="funnel-outcomes">${split}</div>`;
}

function renderMatchers(payload) {
  const host = $("matchers-table");
  const note = $("matchers-note");
  if (!host || !payload || !payload.matchers) {
    if (host) host.innerHTML = "";
    if (note) note.textContent = "";
    return;
  }
  const order = ["full", "plain", "novar"];
  const rows = order.map((key) => {
    const row = payload.matchers[key] || {};
    return `<tr>
      <td>${esc(row.title || key)}</td>
      <td class="num">${esc(row.right)}/${esc(row.labels)}</td>
      <td class="num">${esc(row.unsafe)}</td>
      <td class="num">${esc(row.decision_score)}</td>
    </tr>`;
  }).join("");
  host.innerHTML = `
    <table>
      <thead><tr><th>Matcher</th><th>Right</th><th>Unsafe clears</th><th>Score</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>
    <div class="matchers-examples" id="matchers-examples"></div>`;
  note.textContent = payload.note || "";
  const examples = (payload.matchers.plain && payload.matchers.plain.demo_examples) || [];
  const box = $("matchers-examples");
  if (!box) return;
  box.innerHTML = examples.map((item) => {
    const list = item.list_name || item.hit_id;
    return `<button type="button" data-hit="${esc(item.hit_id)}">
      ${esc(item.hit_id)} · ${esc(list)} became cleared under the plain fuzzy matcher
    </button>`;
  }).join("");
  box.querySelectorAll("button").forEach((button) => {
    button.onclick = () => openHit(button.dataset.hit);
  });
}

function renderSummary(summary) {
  renderFunnel(summary);
  const practice = summary.practice || {};
  const repro = summary.repro || {};
  const reproLabel = repro.label || (repro.identical ? "5 of 5 runs identical" : "runs checked");
  const tiles = [
    ["Decision score (practice)", practice.available ? practice.decision_score : "n/a"],
    ["Unsafe clears", practice.available ? practice.unsafe : "n/a"],
    ["False positives cleared", practice.available ? practice.false_positive_clears : "n/a"],
    ["Clearance precision", practice.available ? `${practice.clearance_precision}%` : "n/a"],
    ["Same-entity recall", practice.available ? `${practice.same_entity_recall}%` : "n/a"],
    ["Review rate", practice.available ? `${practice.review_rate}%` : "n/a"],
    [reproLabel, repro.status === "done" && repro.identical ? "yes" : (repro.status || "n/a")],
  ];
  $("kpis").innerHTML = tiles.map(([label, value]) => `<div class="kpi"><span>${label}</span><strong>${value}</strong></div>`).join("");
  const total = (summary.bar || []).reduce((sum, part) => sum + part.count, 0) || 1;
  const classes = ["seg-cleared", "seg-kept", "seg-review"];
  const decisions = ["DIFFERENT_ENTITY", "SAME_ENTITY", "REVIEW"];
  $("bar").innerHTML = (summary.bar || []).map((part, index) => {
    const width = Math.max(2, Math.round(100 * part.count / total));
    const title = `${part.name} · ${part.count}`;
    return `<i class="${classes[index] || ""}" style="width:${width}%" title="${esc(title)}" aria-label="${esc(title)}"></i>`;
  }).join("");
  const legend = $("bar-legend");
  if (legend) {
    legend.innerHTML = (summary.bar || []).map((part, index) => {
      const code = decisions[index] || part.name;
      return `<li class="bar-legend-item ${classes[index] || ""}"><span class="bar-swatch" aria-hidden="true"></span><span class="bar-legend-label">${decisionBadge(code)}</span><strong class="bar-legend-count">${esc(part.count)}</strong></li>`;
    }).join("");
  }
}

function stopAutoplay() {
  if (state.timer) {
    clearInterval(state.timer);
    state.timer = null;
  }
  state.playing = false;
  syncPlaybackUi();
}

function intervalMs() {
  return SPEEDS[state.speed] || SPEEDS[1];
}

function advanceTick() {
  if (state.index >= state.steps.length - 1) {
    stopAutoplay();
    state.mode = "step";
    syncPlaybackUi();
    return;
  }
  state.index += 1;
  renderStep();
}

function startAutoplay({ fromStart = false } = {}) {
  stopAutoplay();
  state.mode = "auto";
  state.playing = true;
  if (fromStart || state.index >= state.steps.length - 1) state.index = 0;
  renderStep();
  state.timer = setInterval(advanceTick, intervalMs());
  syncPlaybackUi();
}

function setSpeed(speed) {
  state.speed = Number(speed) || 1;
  if (state.playing) {
    if (state.timer) clearInterval(state.timer);
    state.timer = setInterval(advanceTick, intervalMs());
  }
  syncPlaybackUi();
}

function goTo(index, { manual = false } = {}) {
  const next = Math.max(0, Math.min(state.steps.length - 1, index));
  if (manual && state.playing) stopAutoplay();
  if (manual) state.mode = "step";
  state.index = next;
  renderStep();
  syncPlaybackUi();
}

function syncPlaybackUi() {
  const play = $("play");
  if (play) {
    play.setAttribute("aria-pressed", state.playing ? "true" : "false");
    play.textContent = state.playing ? "Playing…" : "Autoplay full story";
  }
  document.querySelectorAll(".speed button").forEach((button) => {
    button.setAttribute("aria-pressed", String(Number(button.dataset.speed) === state.speed));
  });
  document.querySelectorAll(".mode-group button[data-mode]").forEach((button) => {
    button.setAttribute("aria-pressed", button.dataset.mode === state.mode ? "true" : "false");
  });
  const count = $("step-count");
  if (!count) return;
  const step = state.steps[state.index];
  const raw = step ? ((step.detailed && step.detailed.reason_code) || step.title) : "";
  const title = reasonCodeLabel(raw) || raw;
  const modeLabel = state.playing ? "Auto" : "Step";
  count.textContent = `${modeLabel} · Step ${state.index + 1} of ${state.steps.length}${title ? ` · ${title}` : ""}`;
}

function renderTimeline() {
  const host = $("timeline");
  if (!host) return;
  host.innerHTML = state.steps.map((step, index) => {
    const star = step.wow ? " ★" : "";
    const current = index === state.index ? ' aria-current="true"' : "";
    const kind = outcomeClass((step.detailed && step.detailed.decision) || (step.simple && step.simple.outcome) || "");
    const raw = (step.detailed && step.detailed.reason_code) || step.title;
    const title = reasonCodeLabel(raw) || (step.simple && step.simple.plain_code) || raw;
    const short = String(step.id || "").replace(/^H-/, "");
    return `<button type="button" class="timeline-chip ${kind}" data-step="${index}"${current} title="${esc(step.id)} · ${esc(title)}">${esc(short)}${star}</button>`;
  }).join("");
  host.querySelectorAll("button").forEach((button) => {
    button.onclick = () => goTo(Number(button.dataset.step), { manual: true });
  });
  syncPlaybackUi();
}

function renderRail() {
  renderTimeline();
}

function fieldsTable(items) {
  if (!items || !items.length) return "<p>No cited records.</p>";
  return items.map((item) => {
    const rows = Object.entries(item.fields || {}).filter(([, value]) => value !== null && value !== undefined && value !== "")
      .map(([key, value]) => `<tr><th>${key}</th><td>${String(value)}</td></tr>`).join("");
    return `<p><span class="tag real">REAL</span> ${item.kind} ${item.id}</p><table>${rows}</table>`;
  }).join("");
}

function linesHtml(lines) {
  return (lines || []).map((line) => `<dt>${esc(line.label)}</dt><dd>${withChips(line.value)}</dd>`).join("");
}

function renderWorkflow(flow) {
  const panel = $("panel-workflow");
  if (!panel) return;
  if (!flow || !flow.stages) {
    panel.innerHTML = "<p>not available</p>";
    return;
  }
  const decision = flow.decision || "";
  const stages = flow.stages.map((stage, index) => {
    let body = "";
    if (stage.rows) {
      body = stage.rows.map((row) => `
        <div class="compare-row">
          <strong>${esc(row.field)}</strong>
          <span class="mark mark-${esc(row.mark)}">${esc(row.mark)}</span>
          <div><span class="side-note">Customer</span> ${withChips(row.customer)}</div>
          <div><span class="side-note">List</span> ${withChips(row.list)}</div>
          ${row.note ? `<div class="side-note">${withChips(row.note)}</div>` : ""}
        </div>`).join("");
    } else if (stage.key === "decision") {
      const ids = (stage.evidence || []).length ? stage.evidence.map(chipId).join(" ") : "not available";
      const code = stage.reason_code || flow.reason_code || "";
      const decided = stage.decision || decision;
      body = `
        <p class="dec-word">${decisionBadge(decided)}</p>
        <dl>
          <dt>Decision</dt><dd>${decisionBadge(decided)}</dd>
          <dt>Reason code</dt><dd>${reasonBadge(code)}</dd>
          <dt>Why</dt><dd class="reason">${withChips(stage.reason)}</dd>
          <dt>Evidence</dt><dd>${ids}</dd>
        </dl>`;
    } else {
      body = `<dl>${linesHtml(stage.lines)}</dl>`;
    }
    const arrow = index === 0 ? "" : `<div class="stage-arrow" aria-hidden="true" title="Next stage">
      <svg viewBox="0 0 24 24" width="26" height="26" focusable="false" aria-hidden="true">
        <path d="M9 5l7 7-7 7" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>
      </svg>
    </div>`;
    const tint = stage.key ? ` stage-${esc(stage.key)}` : "";
    return `${arrow}<article class="stage${tint}"><h3><span class="n">${stage.n}</span> ${esc(stage.title)}</h3>${body}</article>`;
  }).join("");
  panel.innerHTML = `
    <div class="wf-head">
      <p class="card-kicker">${decisionBadge(decision)}</p>
      <h2>${esc(flow.list_name || "")}</h2>
    </div>
    <div class="pipeline">${stages}</div>`;
  bindChips(panel);
}

function renderStep() {
  const step = state.steps[state.index];
  if (!step) return;
  renderRail();
  const simple = step.simple || {};
  const detailed = step.detailed || {};
  renderWorkflow(detailed.workflow);
  const initials = (simple.screened_name || "?").split(" ").map((part) => part[0]).join("").slice(0, 2);
  const memo = (detailed && detailed.memo) || (detailed && detailed.workflow && detailed.workflow.memo);
  const draftAvailable = detailed && detailed.draft_available;
  const memoHtml = memo ? `
      <section class="memo">
        <h3>Analyst memo</h3>
        <pre class="memo-text">${esc(memo.text)}</pre>
        <div class="memo-actions">
          <button type="button" id="copy-memo">Copy memo</button>
          <button type="button" id="draft-memo" ${draftAvailable ? "" : "disabled"} title="${draftAvailable ? "Reword with Grok" : "Add OPENROUTER_API_KEY or XAI_API_KEY and restart"}">Draft wording</button>
        </div>
        <p class="meta" id="draft-label" hidden></p>
        <pre class="memo-text" id="draft-text" hidden></pre>
      </section>` : "";
  $("panel-simple").innerHTML = `
    <article class="card now">
      <p class="card-kicker">${initials} · ${simple.screened_on || ""} · ${simple.rule}${step.wow ? " · starred" : ""}</p>
      <h2>${step.id} · ${reasonBadge(detailed.reason_code || step.title)}</h2>
      <p class="outcome ${outcomeClass((detailed && detailed.decision) || simple.outcome)}">${decisionBadge((detailed && detailed.decision) || "")}</p>
      <p><strong>What was asked.</strong> ${esc(simple.asked)}</p>
      <p><strong>What happened.</strong> ${withChips(simple.happened)}</p>
      <p class="meta">${esc(simple.screened_name || "")} was screened against ${esc(simple.hit_name || "the list name")}.</p>
      <p class="checked ${simple.passed ? "" : "fail"}">${esc(simple.checked)}</p>
      ${memoHtml}
    </article>`;
  bindChips($("panel-simple"));
  if (memo) {
    const copy = $("copy-memo");
    if (copy) {
      copy.onclick = async () => {
        try {
          await navigator.clipboard.writeText(memo.text);
          copy.textContent = "Copied";
        } catch (error) {
          copy.textContent = "Copy failed";
        }
      };
    }
    const draft = $("draft-memo");
    if (draft && draftAvailable) {
      draft.onclick = async () => {
        draft.disabled = true;
        draft.textContent = "Drafting…";
        try {
          const response = await fetch("/api/draft", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ hit_id: step.hit_id }),
          });
          const body = await response.json();
          if (!body.ok) throw new Error(body.error || "draft failed");
          $("draft-label").hidden = false;
          $("draft-label").textContent = body.label;
          $("draft-text").hidden = false;
          $("draft-text").textContent = body.text;
        } catch (error) {
          $("draft-label").hidden = false;
          $("draft-label").textContent = error.message || "Draft failed";
        } finally {
          draft.disabled = false;
          draft.textContent = "Draft wording";
        }
      };
    }
  }
  const jev = detailed.jev || {};
  const jevHtml = jev.judge
    ? `<section class="panel"><h3>Judge, evaluate, verify</h3><p>Judge ${decisionBadge(jev.judge.decision)} / ${reasonBadge(jev.judge.reason_code)}. Evaluate ${jev.evaluate.agrees ? "agrees" : "disagrees"}. Verify ${jev.verify.ok ? "ok" : "failed"}. ${jev.downgraded ? `Downgraded to ${decisionBadge("REVIEW")}.` : "Not downgraded."}</p><p class="meta">${detailed.model_note || ""} ${detailed.confidence_note || ""}</p></section>`
    : "";
  const trail = (detailed.trail || []).map((hop) => `<div class="hop"><strong>${hop.hop}.</strong> ${hop.detail}</div>`).join("");
  const brief = detailed.brief;
  const briefHtml = brief
    ? `<p>${(brief.missing || []).join(" ")}</p><p>The one document that would settle it: ${brief.would_settle}</p>`
    : "<p>This hit is not waiting for a person.</p>";
  const evidenceIds = detailed.evidence
    || ((detailed.why && detailed.why.evidence) ? detailed.why.evidence.map((item) => item.id) : []);
  const evidenceHtml = evidenceIds.length ? evidenceIds.map(chipId).join(" ") : "not available";
  $("panel-detailed").innerHTML = `
    <article class="card now">
      <p class="card-kicker">${step.id} · ${reasonBadge(detailed.reason_code || step.title)}</p>
      <h2 class="code-heading">${decisionBadge(detailed.decision)} ${reasonBadge(detailed.reason_code)}</h2>
      <p><span class="tag real">REAL</span><span class="tag real">rules</span><span class="tag gap">no confidence number in the file</span></p>
      <section class="panel"><h3>Inputs</h3><p>Hit ${esc(detailed.hit_id || "")} · alert ${esc(detailed.alert_id || "")} · customer ${customerBadge(detailed.customer_record_id)}</p>
        <p>Screened ${detailed.screened && detailed.screened.name} · list name ${detailed.hit && detailed.hit.name}</p></section>
      <section class="panel"><h3>Why this result</h3>
        <dl>
          <dt>Decision</dt><dd>${decisionBadge(detailed.decision)}</dd>
          <dt>Reason code</dt><dd>${reasonBadge(detailed.reason_code)}</dd>
          <dt>Why</dt><dd class="reason">${withChips(detailed.why ? detailed.why.answer : detailed.reason)}</dd>
          <dt>Evidence</dt><dd>${evidenceHtml}</dd>
        </dl>
        <p class="meta">${detailed.why ? detailed.why.from : ""}</p>${fieldsTable(detailed.why && detailed.why.evidence)}</section>
      <section class="panel"><h3>Review brief</h3>${briefHtml}</section>
      <section class="panel"><h3>Evidence trail</h3>${trail || "<p>No hops recorded.</p>"}</section>
      ${jevHtml}
      <section class="panel"><h3>Demo note</h3>
        <p>Demo: this writes a local label only. The scored file is not changed.</p>
        <button type="button" id="override" class="demo">Demo: leave this for a person</button>
        <p id="override-note"></p>
      </section>
    </article>`;
  const override = $("override");
  if (override) {
    override.onclick = async () => {
      const response = await fetch("/api/override", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ hit_id: step.hit_id, decision: "REVIEW", note: "demo" }),
      });
      const body = await response.json();
      $("override-note").textContent = body.label || body.error || "";
    };
  }
  $("check-list").innerHTML = state.steps.map((item) => `<li>${item.id} ${item.title}: ${item.simple.checked}</li>`).join("");
  $("ticker").textContent = `Viewing ${step.id} of ${state.steps.length}. ${step.title}.`;
}

function showView(name) {
  state.view = name;
  $("panel-workflow").hidden = name !== "workflow";
  $("panel-simple").hidden = name !== "simple";
  $("panel-detailed").hidden = name !== "detailed";
  $("tab-workflow").setAttribute("aria-selected", name === "workflow" ? "true" : "false");
  $("tab-simple").setAttribute("aria-selected", name === "simple" ? "true" : "false");
  $("tab-detailed").setAttribute("aria-selected", name === "detailed" ? "true" : "false");
}

async function loadQueue(filter) {
  const body = await getJSON("/api/queue?filter=" + encodeURIComponent(filter));
  $("queue").innerHTML = body.hits.map((hit) => {
    const jevBit = hit.jev
      ? ` <span class="code-badge code-badge-jev" title="Judge / Evaluate / Verify">${esc("J/E/V")} <span class="code-plain">${esc(hit.jev)}</span></span>`
      : "";
    return `<button type="button" data-hit="${esc(hit.hit_id)}"><span class="code-badge code-badge-id">${esc(hit.hit_id)}</span> ${esc(hit.name || "")} ${decisionBadge(hit.decision)} ${reasonBadge(hit.reason_code)}${jevBit}</button>`;
  }).join("") || "<p>None in this filter.</p>";
  $("queue").setAttribute("aria-label", `${body.count} hits in this filter`);
}

async function openHit(hitId) {
  const body = await getJSON("/api/hit/" + encodeURIComponent(hitId));
  showView("workflow");
  const step = {
    id: hitId,
    title: body.row.reason_code,
    wow: false,
    hit_id: hitId,
    simple: {
      rule: "Your rules",
      asked: "Opened from the queue.",
      happened: body.row.reason,
      outcome: plainDecision(body.row.decision) || "Needs a person",
      plain_code: reasonCodeLabel(body.row.reason_code) || body.row.reason_code,
      screened_name: "",
      screened_on: "",
      hit_name: "",
      checked: "Checked: this line is the recorded decision.",
      passed: true,
    },
    detailed: {
      decision: body.row.decision,
      reason_code: body.row.reason_code,
      reason: body.row.reason,
      evidence: body.row.evidence || [],
      customer_record_id: body.row.customer_record_id,
      alert_id: body.row.alert_id,
      hit_id: hitId,
      why: body.why,
      brief: body.brief,
      trail: body.trail,
      jev: body.jev,
      memo: body.memo,
      draft_available: body.draft_available,
      model_note: "Model was not used to build this file.",
      confidence_note: "No confidence number is stored.",
      workflow: body.workflow,
      hit: { name: (body.workflow && body.workflow.list_name) || "" },
      screened: { name: "" },
    },
  };
  state.steps = state.steps.map((item) => item.hit_id === hitId ? step : item);
  const existing = state.steps.findIndex((item) => item.hit_id === hitId);
  if (existing >= 0) state.index = existing;
  else {
    state.steps.push(step);
    state.index = state.steps.length - 1;
  }
  renderStep();
}

async function start() {
  let saved = "light";
  try { saved = localStorage.getItem("desk-theme") || "light"; } catch (error) { saved = "light"; }
  applyTheme(saved);
  document.querySelectorAll(".theme button").forEach((button) => {
    button.onclick = () => applyTheme(button.dataset.theme);
  });
  const config = await getJSON("/api/config");
  state.labels = config.labels || state.labels;
  renderGlossary(state.labels);
  $("app-name").textContent = config.app_name;
  document.title = config.app_name;
  $("outcome").textContent = config.outcome;
  $("how").textContent = config.how;
  $("how-to-read").textContent = config.how_to_read;
  $("banner").textContent = config.practice_banner;
  $("promises").innerHTML = (config.promises || []).map((line) => `<li>${line}</li>`).join("");
  $("real-line").textContent = "Decisions: real recorded file. Records: real. Model: not used.";
  renderFilters();
  const summary = await getJSON("/api/summary");
  if (summary.labels) state.labels = summary.labels;
  renderSummary(summary);
  try {
    const matchers = await getJSON("/static/matchers.json");
    renderMatchers(matchers);
  } catch (error) {
    renderMatchers(null);
  }
  const journey = await getJSON("/api/journey");
  state.steps = journey.steps;
  state.index = 1;
  $("summary-line").textContent = journey.summary;
  renderStep();
  $("tab-workflow").onclick = () => showView("workflow");
  $("tab-simple").onclick = () => showView("simple");
  $("tab-detailed").onclick = () => showView("detailed");
  const params = new URLSearchParams(window.location.search);
  const shot = params.get("shot");
  if (shot) document.body.dataset.shot = shot;
  const requested = params.get("hit");
  if (requested) {
    const existing = state.steps.findIndex((item) => item.hit_id === requested);
    if (existing >= 0) {
      state.index = existing;
      state.view = "workflow";
      renderStep();
    } else {
      await openHit(requested);
    }
  }
  showView(state.view);
  syncPlaybackUi();
  $("back").onclick = () => goTo(state.index - 1, { manual: true });
  $("next").onclick = () => goTo(state.index + 1, { manual: true });
  $("play").onclick = () => {
    if (state.playing) {
      stopAutoplay();
      state.mode = "step";
      syncPlaybackUi();
      return;
    }
    startAutoplay({ fromStart: true });
  };
  $("replay").onclick = () => startAutoplay({ fromStart: true });
  $("reset").onclick = () => {
    stopAutoplay();
    state.mode = "step";
    goTo(0, { manual: true });
  };
  $("mode-auto").onclick = () => startAutoplay();
  $("mode-step").onclick = () => {
    stopAutoplay();
    state.mode = "step";
    syncPlaybackUi();
  };
  document.querySelectorAll(".speed button").forEach((button) => {
    button.onclick = () => setSpeed(button.dataset.speed);
  });
  $("queue").addEventListener("click", (event) => {
    const button = event.target.closest("button");
    if (button && button.dataset.hit) openHit(button.dataset.hit);
  });
  const close = $("record-close");
  if (close) close.onclick = () => { $("record-panel").hidden = true; };
  $("ticker").textContent = "Showing the recorded decisions. Nothing on this page changes the scored file.";
  loadQueue("review");
}

start().catch((error) => { $("ticker").textContent = error.message; });
