"use strict";

const state = { steps: [], index: 0, view: "workflow", timer: null };

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;",
  }[ch]));
}

function withChips(value) {
  const text = String(value ?? "");
  const re = /\(((?:H|A|CUS|KYC|NOTE|SR|ACC|APP)-[0-9A-Za-z]+)([^)]*)\)/g;
  let html = "";
  let last = 0;
  let match;
  while ((match = re.exec(text))) {
    html += esc(text.slice(last, match.index));
    const rest = match[2].replace(/^,\s*/, "").trim();
    html += `<span class="chip">${esc(match[1])}${rest ? `<span class="chip-meta">${esc(rest)}</span>` : ""}</span>`;
    last = match.index + match[0].length;
  }
  html += esc(text.slice(last));
  return html;
}

function chipId(id) {
  return `<span class="chip">${esc(id)}</span>`;
}

function $(id) { return document.getElementById(id); }

function outcomeClass(text) {
  if (text === "Cleared") return "cleared";
  if (text === "Kept open") return "kept";
  return "review";
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
    ["cleared", funnel.cleared, "Cleared"],
    ["kept", funnel.kept_open, "Kept open"],
    ["review", funnel.review, "Sent to review"],
  ];
  const main = steps.map(([count, label]) =>
    `<div class="funnel-step"><strong>${esc(count)}</strong><span>${esc(label)}</span></div>`
  ).join('<span class="funnel-arrow" aria-hidden="true">→</span>');
  const split = outcomes.map(([kind, count, label]) =>
    `<div class="outcome-tile ${kind}"><strong>${esc(count)}</strong><span>${esc(label)}</span></div>`
  ).join("");
  $("funnel-row").innerHTML = `${main}<span class="funnel-arrow" aria-hidden="true">→</span><div class="funnel-outcomes">${split}</div>`;
}

function renderSummary(summary) {
  renderFunnel(summary);
  const totals = summary.totals || {};
  const practice = summary.practice || {};
  const repro = summary.repro || {};
  const tiles = [
    ["Hits", summary.hits],
    ["Cleared", totals.DIFFERENT_ENTITY],
    ["Kept open", totals.SAME_ENTITY],
    ["Left for you", totals.REVIEW],
    ["Practice score", practice.available ? practice.decision_score : "n/a"],
    ["Unsafe clears", practice.available ? practice.unsafe : "n/a"],
    ["Five runs", repro.status === "done" ? (repro.identical ? "identical" : "differ") : repro.status || "waiting"],
  ];
  $("kpis").innerHTML = tiles.map(([label, value]) => `<div class="kpi"><span>${label}</span><strong>${value}</strong></div>`).join("");
  const total = (summary.bar || []).reduce((sum, part) => sum + part.count, 0) || 1;
  const classes = ["seg-cleared", "seg-kept", "seg-review"];
  $("bar").innerHTML = (summary.bar || []).map((part, index) => {
    const width = Math.max(2, Math.round(100 * part.count / total));
    const label = width > 12 ? `${part.name} ${part.count}` : "";
    return `<i class="${classes[index] || ""}" style="width:${width}%">${label}</i>`;
  }).join("");
  if (repro.status === "running") {
    setTimeout(() => getJSON("/api/summary").then(renderSummary).catch(() => {}), 4000);
  }
}

function renderRail() {
  $("rail").innerHTML = state.steps.map((step, index) => {
    const star = step.wow ? '<span class="star"> ★</span>' : "";
    const current = index === state.index ? ' aria-current="true"' : "";
    return `<button type="button" data-step="${index}"${current}>${step.id} ${step.title}${star}</button>`;
  }).join("");
  $("rail").querySelectorAll("button").forEach((button) => {
    button.onclick = () => { state.index = Number(button.dataset.step); renderStep(); };
  });
  $("step-count").textContent = `Step ${state.index + 1} of ${state.steps.length}`;
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
  const plain = decision === "DIFFERENT_ENTITY" ? "Cleared" : decision === "SAME_ENTITY" ? "Kept open" : decision === "REVIEW" ? "Sent to review" : decision;
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
      body = `
        <p class="dec-word dec-${esc(stage.decision)}">${esc(stage.decision)}</p>
        <dl>
          <dt>Reason code</dt><dd>${esc(stage.reason_code)}</dd>
          <dt>Reason</dt><dd class="reason">${withChips(stage.reason)}</dd>
          <dt>Evidence</dt><dd>${ids}</dd>
        </dl>`;
    } else {
      body = `<dl>${linesHtml(stage.lines)}</dl>`;
    }
    const arrow = index === 0 ? "" : '<div class="stage-arrow" aria-hidden="true">→</div>';
    return `${arrow}<article class="stage"><h3><span class="n">${stage.n}</span> ${esc(stage.title)}</h3>${body}</article>`;
  }).join("");
  panel.innerHTML = `
    <div class="wf-head">
      <p class="card-kicker">${esc(flow.hit_id)} · ${esc(plain)}</p>
      <h2>${esc(flow.list_name || "")}</h2>
    </div>
    <div class="pipeline">${stages}</div>`;
}

function renderStep() {
  const step = state.steps[state.index];
  if (!step) return;
  renderRail();
  const simple = step.simple;
  const detailed = step.detailed;
  renderWorkflow(detailed && detailed.workflow);
  const initials = (simple.screened_name || "?").split(" ").map((part) => part[0]).join("").slice(0, 2);
  $("panel-simple").innerHTML = `
    <article class="card now">
      <p class="card-kicker">${initials} · ${simple.screened_on || ""} · ${simple.rule}${step.wow ? " · starred" : ""}</p>
      <h2>${step.id} · ${step.title}</h2>
      <p class="outcome ${outcomeClass(simple.outcome)}">${simple.outcome}</p>
      <p><strong>What was asked.</strong> ${simple.asked}</p>
      <p><strong>What happened.</strong> ${simple.happened}</p>
      <p class="meta">${simple.screened_name || ""} was screened against ${simple.hit_name || "the list name"}.</p>
      <p class="checked ${simple.passed ? "" : "fail"}">${simple.checked}</p>
    </article>`;
  const trail = (detailed.trail || []).map((hop) => `<div class="hop"><strong>${hop.hop}.</strong> ${hop.detail}</div>`).join("");
  const brief = detailed.brief;
  const briefHtml = brief
    ? `<p>${(brief.missing || []).join(" ")}</p><p>The one document that would settle it: ${brief.would_settle}</p>`
    : "<p>This hit is not waiting for a person.</p>";
  $("panel-detailed").innerHTML = `
    <article class="card now">
      <p class="card-kicker">${step.id} · ${step.title}</p>
      <h2>${detailed.decision || ""} · ${detailed.reason_code || ""}</h2>
      <p><span class="tag real">REAL</span><span class="tag real">rules</span></p>
      <section class="panel"><h3>Inputs</h3><p>Hit ${detailed.hit_id} · alert ${detailed.alert_id} · customer ${detailed.customer_record_id}</p>
        <p>Screened ${detailed.screened && detailed.screened.name} · list name ${detailed.hit && detailed.hit.name}</p></section>
      <section class="panel"><h3>Why this result</h3><p>${detailed.why ? detailed.why.answer : ""}</p><p class="meta">${detailed.why ? detailed.why.from : ""}</p>${fieldsTable(detailed.why && detailed.why.evidence)}</section>
      <section class="panel"><h3>Review brief</h3>${briefHtml}</section>
      <section class="panel"><h3>Evidence trail</h3>${trail || "<p>No hops recorded.</p>"}</section>
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
  $("queue").innerHTML = body.hits.map((hit) =>
    `<button type="button" data-hit="${hit.hit_id}">${hit.hit_id} · ${hit.name || ""} · ${hit.decision} · ${hit.reason_code}</button>`
  ).join("") || "<p>None in this filter.</p>";
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
      outcome: body.row.decision === "DIFFERENT_ENTITY" ? "Cleared" : body.row.decision === "SAME_ENTITY" ? "Kept open" : "Left for you",
      screened_name: "",
      screened_on: "",
      hit_name: "",
      checked: "Checked: this line is the recorded decision.",
      passed: true,
    },
    detailed: {
      decision: body.row.decision,
      reason_code: body.row.reason_code,
      customer_record_id: body.row.customer_record_id,
      alert_id: body.row.alert_id,
      hit_id: hitId,
      why: body.why,
      brief: body.brief,
      trail: body.trail,
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
  $("app-name").textContent = config.app_name;
  document.title = config.app_name;
  $("outcome").textContent = config.outcome;
  $("how").textContent = config.how;
  $("how-to-read").textContent = config.how_to_read;
  $("banner").textContent = config.practice_banner;
  $("promises").innerHTML = (config.promises || []).map((line) => `<li>${line}</li>`).join("");
  $("real-line").textContent = "Decisions: real recorded file. Records: real.";
  const summary = await getJSON("/api/summary");
  renderSummary(summary);
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
  $("back").onclick = () => { state.index = Math.max(0, state.index - 1); renderStep(); };
  $("next").onclick = () => { state.index = Math.min(state.steps.length - 1, state.index + 1); renderStep(); };
  $("play").onclick = () => {
    if (state.timer) clearInterval(state.timer);
    state.index = 0;
    renderStep();
    state.timer = setInterval(() => {
      if (state.index >= state.steps.length - 1) { clearInterval(state.timer); return; }
      state.index += 1;
      renderStep();
    }, 1600);
  };
  document.querySelectorAll("#filters button").forEach((button) => {
    button.onclick = () => loadQueue(button.dataset.filter);
  });
  $("queue").addEventListener("click", (event) => {
    const button = event.target.closest("button");
    if (button && button.dataset.hit) openHit(button.dataset.hit);
  });
  loadQueue("review");
}

start().catch((error) => { $("ticker").textContent = error.message; });
