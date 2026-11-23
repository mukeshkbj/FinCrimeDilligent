#!/usr/bin/env python3
"""Namesake analyst workbench.

A local web app around the scored engine. It runs `system/run` on a data folder,
groups the hits into an alert queue, shows each case with a link graph and the
data discrepancies it found, and records what analysts do: work each issue,
decide each hit, and have a second analyst approve before an alert closes.

The engine still makes every automatic decision. Analyst actions are stored
beside each run (app/runs/<run>/actions.jsonl) and never change the scored file.

Usage:
    python3 app/server.py --data <data folder> [--port 8780]

Python 3 standard library only.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.parse
from collections import defaultdict
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

APP = Path(__file__).resolve().parent
ROOT = APP.parent
STATIC = APP / "static"
RUNS = APP / "runs"
sys.path.insert(0, str(ROOT / "ui"))
sys.path.insert(0, str(ROOT / "system"))

import serve as desk_mod  # noqa: E402  (ui/serve.py: Desk, labels, Grok draft)
import workflow  # noqa: E402  (ui/workflow.py: stages, memo, identity helpers)

PLAIN = {
    "DIFFERENT_ENTITY": "Different person",
    "SAME_ENTITY": "Same person",
    "REVIEW": "Needs a person",
}
PLAIN_CODE = desk_mod.PLAIN_CODE
STATUS_LABEL = {
    "needs_you": "Needs you",
    "awaiting_approval": "Awaiting approval",
    "escalated": "Escalated to compliance",
    "cleared": "Cleared",
}
LOCK = threading.Lock()


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def read_jsonl(path):
    rows = []
    if not Path(path).is_file():
        return rows
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


# ---------------------------------------------------------------------------
# Runs: one folder per screening run, holding the engine output and actions.
# ---------------------------------------------------------------------------

class Runs:
    def __init__(self):
        RUNS.mkdir(parents=True, exist_ok=True)
        self.job = {"state": "idle"}
        self.desks = {}

    def list(self):
        items = []
        for folder in sorted(RUNS.iterdir(), reverse=True):
            meta_path = folder / "meta.json"
            if folder.is_dir() and meta_path.is_file():
                try:
                    items.append(json.loads(meta_path.read_text(encoding="utf-8")))
                except json.JSONDecodeError:
                    continue
        return items

    def meta(self, run_id):
        path = RUNS / run_id / "meta.json"
        if not path.is_file():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def _write_meta(self, run_id, meta):
        (RUNS / run_id / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

    def new_id(self, data_dir):
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        slug = re.sub(r"[^a-z0-9]+", "-", Path(data_dir).name.lower()).strip("-") or "data"
        return f"{stamp}-{slug}"

    def import_output(self, data_dir, output_file, label):
        run_id = self.new_id(data_dir) + "-imported"
        folder = RUNS / run_id
        folder.mkdir(parents=True)
        shutil.copyfile(output_file, folder / "output.jsonl")
        rows = read_jsonl(folder / "output.jsonl")
        meta = {
            "run_id": run_id,
            "label": label,
            "data_dir": str(Path(data_dir).resolve()),
            "started": now_iso(),
            "finished": now_iso(),
            "seconds": 0,
            "state": "done",
            "source": "imported",
            "hits": len(rows),
            "totals": _totals(rows),
        }
        self._write_meta(run_id, meta)
        return meta

    def start(self, data_dir):
        data = Path(data_dir).expanduser().resolve()
        if not (data / "hits.jsonl").is_file() or not (data / "alerts.jsonl").is_file():
            return {"ok": False, "error": f"{data} has no hits.jsonl and alerts.jsonl. Pick the data folder itself."}
        with LOCK:
            if self.job.get("state") == "running":
                return {"ok": False, "error": "A screening run is already in progress."}
            run_id = self.new_id(data)
            folder = RUNS / run_id
            folder.mkdir(parents=True)
            meta = {
                "run_id": run_id,
                "label": f"Screening of {data.name}",
                "data_dir": str(data),
                "started": now_iso(),
                "state": "running",
                "source": "system/run",
            }
            self._write_meta(run_id, meta)
            self.job = {"state": "running", "run_id": run_id, "done": 0, "total": 0, "phase": "Loading the data folder"}
        threading.Thread(target=self._run, args=(run_id, data), daemon=True).start()
        return {"ok": True, "run_id": run_id}

    def _run(self, run_id, data):
        folder = RUNS / run_id
        started = time.time()
        env = dict(os.environ)
        env.pop("RESOLVE_POLISH_REASONS", None)  # the scored wording, as graded
        process = subprocess.Popen(
            [sys.executable, str(ROOT / "system" / "engine.py"), str(data), str(folder / "output.jsonl")],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=env,
            text=True,
            bufsize=1,
        )
        buffer = ""
        while True:
            chunk = process.stdout.read(256)
            if not chunk:
                break
            buffer = (buffer + chunk)[-2000:]
            found = re.findall(r"(\d+)/(\d+) hit", buffer)
            with LOCK:
                if found:
                    done, total = found[-1]
                    self.job.update(done=int(done), total=int(total), phase="Resolving hits")
                elif "writing" in buffer:
                    self.job.update(phase="Writing decisions")
        code = process.wait()
        meta = self.meta(run_id)
        meta["finished"] = now_iso()
        meta["seconds"] = round(time.time() - started, 1)
        if code == 0 and (folder / "output.jsonl").is_file():
            rows = read_jsonl(folder / "output.jsonl")
            meta.update(state="done", hits=len(rows), totals=_totals(rows))
            with LOCK:
                self.job = {"state": "done", "run_id": run_id, "done": len(rows), "total": len(rows), "seconds": meta["seconds"]}
            self._write_meta(run_id, meta)
            if not CURRENT.get("run_id"):
                CURRENT["run_id"] = run_id  # first run: open it straight away
        else:
            meta.update(state="failed", error=buffer[-400:])
            with LOCK:
                self.job = {"state": "failed", "run_id": run_id, "error": "The screening run stopped. See the run log."}
        self._write_meta(run_id, meta)

    def desk(self, run_id):
        meta = self.meta(run_id)
        if not meta or meta.get("state") != "done":
            return None
        if run_id not in self.desks:
            desk = desk_mod.Desk(Path(meta["data_dir"]), RUNS / run_id / "output.jsonl")
            workflow.prepare(desk)
            self.desks[run_id] = Case(desk, run_id, meta)
        return self.desks[run_id]


def _totals(rows):
    totals = {"DIFFERENT_ENTITY": 0, "SAME_ENTITY": 0, "REVIEW": 0}
    for row in rows:
        totals[row.get("decision")] = totals.get(row.get("decision"), 0) + 1
    return totals


# ---------------------------------------------------------------------------
# Case: alerts, issues, link graph and analyst actions for one run.
# ---------------------------------------------------------------------------

class Case:
    def __init__(self, desk, run_id, meta):
        self.desk = desk
        self.run_id = run_id
        self.meta = meta
        self.actions_path = RUNS / run_id / "actions.jsonl"
        self.by_alert = defaultdict(list)
        for hit_id, row in sorted(desk.output.items()):
            self.by_alert[row.get("alert_id")].append(hit_id)
        self.engine = desk._wf_engine
        self.search_by_key = defaultdict(list)
        for result in desk.search.values():
            self.search_by_key[(result.get("query") or "").strip().lower()].append(result)
        self._issue_cache = {}

    # -- actions --------------------------------------------------------------
    def actions(self):
        return read_jsonl(self.actions_path)

    def append(self, record):
        record = dict(record)
        record["at"] = now_iso()
        record["id"] = hashlib.sha1(json.dumps(record, sort_keys=True).encode()).hexdigest()[:10]
        with LOCK:
            with open(self.actions_path, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        return record

    def state(self):
        """Fold the action log into the latest decision and issue status per item."""
        decisions, issues = {}, {}
        for action in self.actions():
            kind = action.get("kind")
            if kind == "decision":
                decisions[action["hit_id"]] = {**action, "approval": "pending"}
            elif kind == "approval" and action.get("hit_id") in decisions:
                current = decisions[action["hit_id"]]
                if action.get("decision_id") == current.get("id"):
                    current["approval"] = "approved" if action.get("approve") else "rejected"
                    current["approver"] = action.get("by")
                    current["approver_note"] = action.get("note")
            elif kind == "issue":
                issues[action["issue_id"]] = action
        return decisions, issues

    # -- per hit ----------------------------------------------------------------
    def final(self, hit_id, decisions):
        row = self.desk.output[hit_id]
        made = decisions.get(hit_id)
        if made and made.get("approval") == "approved":
            return made["decision"], "analyst"
        return row["decision"], "engine"

    def alert_status(self, alert_id, decisions):
        hits = self.by_alert.get(alert_id, [])
        pending_review = False
        awaiting = False
        finals = []
        for hit_id in hits:
            made = decisions.get(hit_id)
            if made and made.get("approval") == "pending":
                awaiting = True
            decision, _who = self.final(hit_id, decisions)
            finals.append(decision)
            if decision == "REVIEW":
                pending_review = True
        if pending_review and not awaiting:
            return "needs_you"
        if awaiting:
            return "awaiting_approval"
        if "SAME_ENTITY" in finals:
            return "escalated"
        return "cleared"

    def alert_rows(self, status=None, query=""):
        decisions, _issues = self.state()
        query = (query or "").strip().lower()
        rows = []
        for alert_id, hit_ids in self.by_alert.items():
            alert = self.desk.alerts.get(alert_id) or {}
            screened = (alert.get("customer") or {})
            current = self.alert_status(alert_id, decisions)
            if status and status != "all" and current != status:
                continue
            names = [self.desk.hits.get(h, {}).get("name") or "" for h in hit_ids]
            haystack = " ".join([alert_id, screened.get("name") or ""] + hit_ids + names).lower()
            if query and query not in haystack:
                continue
            marks = []
            for hit_id in hit_ids:
                decision, who = self.final(hit_id, decisions)
                marks.append({"hit_id": hit_id, "decision": decision, "by": who})
            rows.append({
                "alert_id": alert_id,
                "name": screened.get("name") or "",
                "entity_type": screened.get("entity_type") or "",
                "screened_at": alert.get("screened_at") or "",
                "hits": len(hit_ids),
                "marks": marks,
                "status": current,
                "status_label": STATUS_LABEL[current],
                "review": sum(1 for m in marks if m["decision"] == "REVIEW"),
            })
        order = {"needs_you": 0, "awaiting_approval": 1, "escalated": 2, "cleared": 3}
        rows.sort(key=lambda r: (order[r["status"]], -r["review"], r["alert_id"]))
        return rows

    def overview(self):
        decisions, issues = self.state()
        counts = defaultdict(int)
        for alert_id in self.by_alert:
            counts[self.alert_status(alert_id, decisions)] += 1
        hit_totals = {"DIFFERENT_ENTITY": 0, "SAME_ENTITY": 0, "REVIEW": 0}
        by_analyst = 0
        for hit_id in self.desk.output:
            decision, who = self.final(hit_id, decisions)
            hit_totals[decision] += 1
            by_analyst += who == "analyst"
        engine_totals = _totals(self.desk.output.values())
        activity = sorted(self.actions(), key=lambda a: a.get("at", ""), reverse=True)[:12]
        return {
            "run": self.meta,
            "alerts": len(self.by_alert),
            "alert_status": {k: counts.get(k, 0) for k in STATUS_LABEL},
            "engine_totals": engine_totals,
            "hit_totals": hit_totals,
            "decided_by_analyst": by_analyst,
            "practice": self.desk.practice(),
            "open_issues": sum(1 for v in issues.values() if v.get("status") in ("open", "requested")),
            "activity": [self._describe(a) for a in activity],
        }

    def _describe(self, action):
        kind = action.get("kind")
        who = action.get("by") or "Someone"
        if kind == "decision":
            text = f"{who} decided {action['hit_id']}: {PLAIN.get(action['decision'])}"
        elif kind == "approval":
            text = f"{who} {'approved' if action.get('approve') else 'sent back'} the decision on {action['hit_id']}"
        elif kind == "issue":
            text = f"{who} marked an issue on {action.get('hit_id')} as {action.get('status')}"
        elif kind == "request":
            text = f"{who} drafted an information request for {action.get('alert_id')}"
        else:
            text = f"{who}: {kind}"
        return {"at": action.get("at"), "text": text, "alert_id": action.get("alert_id"), "note": action.get("note") or ""}

    # -- the case page ------------------------------------------------------------
    def alert_detail(self, alert_id):
        if alert_id not in self.by_alert:
            return None
        decisions, issue_state = self.state()
        alert = self.desk.alerts.get(alert_id) or {}
        hits = []
        for hit_id in self.by_alert[alert_id]:
            row = self.desk.output[hit_id]
            hit = self.desk.hits.get(hit_id) or {}
            flow = workflow.build(self.desk, hit_id, desk_mod._display_name)
            decision, who = self.final(hit_id, decisions)
            issues = []
            for issue in self.issues(hit_id):
                saved = issue_state.get(issue["issue_id"])
                issue = dict(issue)
                if saved:
                    issue["status"] = saved.get("status")
                    issue["note"] = saved.get("note")
                    issue["by"] = saved.get("by")
                    issue["at"] = saved.get("at")
                issues.append(issue)
            hits.append({
                "hit_id": hit_id,
                "name": hit.get("name") or "",
                "aliases": hit.get("aliases") or [],
                "categories": hit.get("categories") or [],
                "position": hit.get("position_or_allegation") or "",
                "engine": {
                    "decision": row["decision"],
                    "decision_label": PLAIN[row["decision"]],
                    "reason_code": row["reason_code"],
                    "reason_code_label": PLAIN_CODE.get(row["reason_code"], row["reason_code"]),
                    "customer_record_id": row.get("customer_record_id"),
                    "reason": row.get("reason"),
                    "evidence": row.get("evidence") or [],
                },
                "final": {"decision": decision, "decision_label": PLAIN[decision], "by": who},
                "analyst": decisions.get(hit_id),
                "stages": flow.get("stages"),
                "memo": flow.get("memo"),
                "issues": issues,
                "graph": self.graph(hit_id),
            })
        status = self.alert_status(alert_id, decisions)
        history = [self._describe(a) | {"kind": a.get("kind")} for a in self.actions() if a.get("alert_id") == alert_id]
        history.sort(key=lambda a: a.get("at", ""), reverse=True)
        return {
            "alert_id": alert_id,
            "alert": alert,
            "status": status,
            "status_label": STATUS_LABEL[status],
            "hits": hits,
            "history": history,
            "draft_available": self.desk.draft_key,
        }

    # -- discrepancies ------------------------------------------------------------
    def _group(self, row):
        seed = row.get("customer_record_id")
        if isinstance(seed, str) and seed.startswith("CUS-") and seed in self.desk.customers:
            return seed, workflow._expand(self.desk, seed)
        return seed, tuple()

    def _checks(self, record_id):
        found = []
        for account in self.desk.accounts_by_customer.get(record_id, []):
            for applicant in self.desk.onboarding.get((account.get("account_id"), record_id), []):
                found.extend(self.desk.checks_by_applicant.get(applicant, []))
        return found

    def _iso(self, value):
        if not value or self.engine is None:
            return ""
        try:
            parsed = self.engine.parse_date(str(value))
        except Exception:
            return ""
        if parsed is None or not getattr(parsed, "d", None):
            return ""
        return parsed.iso()

    def issues(self, hit_id):
        if hit_id in self._issue_cache:
            return self._issue_cache[hit_id]
        row = self.desk.output[hit_id]
        hit = self.desk.hits.get(hit_id) or {}
        alert = self.desk.alerts.get(row.get("alert_id")) or {}
        screened = alert.get("customer") or {}
        found = []

        def add(kind, severity, title, detail, evidence, action):
            issue_id = hashlib.sha1(f"{hit_id}|{kind}|{title}".encode()).hexdigest()[:10]
            found.append({
                "issue_id": issue_id, "hit_id": hit_id, "alert_id": row.get("alert_id"),
                "kind": kind, "severity": severity, "title": title, "detail": detail,
                "evidence": [e for e in evidence if e], "suggested": action,
                "status": "noted" if severity == "info" else "open",
            })

        seed, group = self._group(row)
        if seed == "AMBIGUOUS":
            people = [e for e in row.get("evidence") or [] if str(e).startswith("CUS-")]
            add("ambiguous", "blocker", "More than one person fits this alert",
                f"{len(people) or 'Several'} customer records fit the screened details and they are different people.",
                people, "Ask for a full date of birth or a document number that picks one person.")
        elif not seed:
            add("no_customer", "blocker", "No customer record fits the alert",
                "The alert carries no link that leads to a customer, and no record fits the screened details.",
                [], "Ask the business for the customer's account or record number.")

        latest = workflow._identity(self.desk, group) if group else None
        if group and not latest:
            failed = []
            for record_id in group:
                for check in self._checks(record_id):
                    if str(check.get("result") or "").lower() in ("rejected", "expired"):
                        failed.append(check.get("check_id"))
            detail = "No approved identity check or identity note exists for this person."
            if failed:
                detail += f" {len(failed)} check(s) were rejected or expired and are not evidence."
            add("unverified", "warning", "Identity is not verified", detail, list(group[:1]) + failed[:3],
                "Request a fresh identity check before relying on the customer's own details.")

        if group and latest:
            for record_id in group:
                customer = self.desk.customers.get(record_id) or {}
                record_dob = self.desk.customer_dob_iso.get(record_id) or ""
                verified = latest.get("dob") or ""
                if record_dob and len(verified) == 10 and record_dob != verified:
                    add("dob_conflict", "warning", "Date of birth differs between the record and the verified check",
                        f"{record_id} says {record_dob}; {latest.get('id')} verified {verified}. The verified date is used.",
                        [record_id, latest.get("id")], "Correct the customer record, or confirm which date is right.")
                record_name = customer.get("full_name") or ""
                verified_name = latest.get("name") or ""
                if record_name and verified_name and not workflow._names_agree_live(record_name, verified_name):
                    add("name_conflict", "warning", "Name on the record differs from the verified name",
                        f"{record_id} has '{record_name}'; {latest.get('id')} verified '{verified_name}'. The verified name is used.",
                        [record_id, latest.get("id")], "Update the record, or document why the names differ.")
            screened_name = screened.get("name") or ""
            verified_name = latest.get("name") or ""
            if screened_name and verified_name and not workflow._names_agree_live(screened_name, verified_name):
                add("screened_name", "info", "Screened under a different name",
                    f"The alert screened '{screened_name}' but the verified name is '{verified_name}'.",
                    [latest.get("id")], "Check the screening feed uses the verified legal name.")
            for record_id in group:
                for check in self._checks(record_id):
                    if str(check.get("result") or "").lower() in ("rejected", "expired"):
                        add("failed_check", "info", f"{str(check.get('result')).capitalize()} check ignored",
                            f"{check.get('check_id')} ({check.get('checked_at')}) was {check.get('result')}, so it is not evidence.",
                            [check.get("check_id")], "No action unless it is the only check.")
        if len(group) > 1:
            add("merged", "info", f"{len(group)} records belong to one person",
                "They share a phone and a full date of birth, or an approved document number, so all their facts count.",
                list(group), "Consider merging the duplicate records in the system of record.")
        account = alert.get("account_ref")
        holders = self.desk.accounts.get(account, []) if account else []
        if len(set(holders)) > 1:
            add("joint", "info", "Joint account",
                f"{account} has {len(set(holders))} holders; the screened name and date picked the customer.",
                list(dict.fromkeys(holders)), "Confirm the alert is about the right holder.")

        if row["decision"] == "REVIEW":
            if not (hit.get("dobs") or []):
                add("list_dob", "blocker", "The list profile has no date of birth",
                    "Nothing on the list side can be compared with the customer's verified date of birth.",
                    [hit_id], "Look for the listed person's date of birth in the list provider's full record.")
            flow = workflow.build(self.desk, hit_id, desk_mod._display_name)
            compare = next((s for s in flow.get("stages", []) if s.get("key") == "compare"), {})
            marks = {r.get("field"): r.get("mark") for r in compare.get("rows", [])}
            if marks.get("Country") == "clashes" and marks.get("Name") == "matches" and marks.get("DOB") == "matches":
                add("country_vs_identity", "blocker", "Countries clash but name and date of birth agree",
                    "The policy does not clear on country when name and date agree. A person must decide.",
                    row.get("evidence") or [], "Check whether the customer has lived in the listed country.")
            if row["reason_code"] == "INSUFFICIENT_DATA" and not any(i["severity"] == "blocker" for i in found):
                add("insufficient", "blocker", "Nothing settles this hit",
                    "There is no contradiction and not enough agreement to confirm.",
                    row.get("evidence") or [], "Find one more fact: a date of birth, a document number or a place.")
        self._issue_cache[hit_id] = found
        return found

    def request_draft(self, alert_id, issue_ids):
        detail = self.alert_detail(alert_id)
        if not detail:
            return None
        chosen = []
        for hit in detail["hits"]:
            for issue in hit["issues"]:
                if not issue_ids or issue["issue_id"] in issue_ids:
                    if issue["severity"] != "info":
                        chosen.append((hit, issue))
        name = (detail["alert"].get("customer") or {}).get("name") or alert_id
        lines = [
            f"Subject: Information needed to close screening alert {alert_id}",
            "",
            f"We are reviewing a watchlist match for {name} (alert {alert_id}).",
            "To close it we need the following:",
            "",
        ]
        for n, (hit, issue) in enumerate(chosen, 1):
            lines.append(f"{n}. {issue['suggested']} ({issue['title']}; hit {hit['hit_id']}, records {', '.join(issue['evidence'][:3]) or 'n/a'})")
        if not chosen:
            lines.append("1. Nothing outstanding. No request is needed.")
        lines += ["", "Please reply on this case. Do not contact the customer about the watchlist match.", ""]
        return {"text": "\n".join(lines), "label": "Draft — not sent"}

    # -- link graph ------------------------------------------------------------------
    def graph(self, hit_id):
        row = self.desk.output[hit_id]
        hit = self.desk.hits.get(hit_id) or {}
        alert = self.desk.alerts.get(row.get("alert_id")) or {}
        evidence = set(row.get("evidence") or [])
        nodes, edges = {}, []

        def node(node_id, kind, label, sub="", col=0, state=""):
            if node_id and node_id not in nodes:
                nodes[node_id] = {"id": node_id, "kind": kind, "label": label, "sub": sub, "col": col,
                                  "cited": node_id in evidence, "state": state}

        def edge(a, b, label, style=""):
            if a in nodes and b in nodes:
                edges.append({"from": a, "to": b, "label": label, "style": style})

        screened = alert.get("customer") or {}
        alert_id = alert.get("alert_id") or row.get("alert_id")
        node(alert_id, "alert", "Alert", f"{screened.get('name') or ''}", 0)
        link_id = None
        if alert.get("account_ref"):
            link_id = alert["account_ref"]
            node(link_id, "link", "Account", link_id, 1)
        elif alert.get("login_handle"):
            link_id = "login:" + alert["login_handle"]
            node(link_id, "link", "Login", alert["login_handle"], 1)
        elif alert.get("email"):
            link_id = "email:" + alert["email"]
            node(link_id, "link", "Email", alert["email"], 1)
        else:
            link_id = "search:" + alert_id
            node(link_id, "link", "Attribute search", "no link on the alert", 1)
        edge(alert_id, link_id, "carries")

        seed, group = self._group(row)
        candidates = [e for e in evidence if str(e).startswith("CUS-")] if seed == "AMBIGUOUS" else []
        holders = list(dict.fromkeys(self.desk.accounts.get(alert.get("account_ref"), []))) if alert.get("account_ref") else []
        people = list(dict.fromkeys(list(group) + holders + candidates))
        for record_id in people[:8]:
            customer = self.desk.customers.get(record_id) or {}
            state = "chosen" if record_id in group or record_id in candidates else "other"
            node(record_id, "customer", customer.get("full_name") or record_id, record_id, 2, state)
            if record_id in holders:
                edge(link_id, record_id, "holder" if len(holders) > 1 else "holder", "" if state == "chosen" else "muted")
            elif record_id == seed or record_id in candidates:
                edge(link_id, record_id, "fits the screened details" if link_id.startswith("search:") else "leads to")
        for record_id in group:
            if record_id != seed and record_id in nodes and seed in nodes:
                edge(seed, record_id, "same person", "merge")

        latest = workflow._identity(self.desk, group) if group else None
        for record_id in group[:6]:
            for check in self._checks(record_id)[:4]:
                cid = check.get("check_id")
                result = str(check.get("result") or "").lower()
                state = "used" if latest and latest.get("id") == cid else ("ignored" if result != "approved" else "older")
                node(cid, "check", f"ID check · {result}", f"{check.get('verified_name') or ''} · {check.get('checked_at') or ''}", 3, state)
                edge(record_id, cid, "verified by" if result == "approved" else result, "" if result == "approved" else "muted")
            email = str((self.desk.customers.get(record_id) or {}).get("email") or "").lower()
            for note in self.desk.notes_by_email.get(email, [])[:6]:
                nid = note.get("note_id")
                if nid in evidence or (latest and latest.get("id") == nid):
                    node(nid, "note", "Note · " + (note.get("channel") or ""), (note.get("text") or "")[:60], 3,
                         "used" if latest and latest.get("id") == nid else "")
                    edge(record_id, nid, "note")

        decision_id = "decision:" + hit_id
        node(decision_id, "decision", PLAIN[row["decision"]], PLAIN_CODE.get(row["reason_code"], row["reason_code"]), 4, row["decision"])
        for cited in evidence:
            if cited in nodes:
                edge(cited, decision_id, "decided")
        node(hit_id, "hit", hit.get("name") or hit_id, ", ".join(hit.get("categories") or [])[:40], 5)
        edge(hit_id, decision_id, "compared")
        key = ""
        if self.engine is not None:
            try:
                key = self.engine.search_key(hit.get("name") or "")
            except Exception:
                key = ""
        results = self.search_by_key.get((key or "").lower(), [])
        for result in results[:5]:
            rid = result.get("result_id")
            used = rid in evidence
            node(rid, "search", "Search result", (result.get("snippet") or "")[:60], 6, "used" if used else "namesake")
            edge(rid, hit_id, "about this person" if used else "namesake", "" if used else "muted")
        if len(results) > 5:
            node("more:" + hit_id, "search", f"+{len(results) - 5} more results", "namesakes", 6, "namesake")
        return {"nodes": list(nodes.values()), "edges": edges}

    # -- writes ----------------------------------------------------------------------
    def decide(self, payload):
        hit_id = payload.get("hit_id")
        decision = payload.get("decision")
        by = (payload.get("by") or "").strip()
        if hit_id not in self.desk.output:
            return {"ok": False, "error": "Unknown hit."}
        if decision not in ("DIFFERENT_ENTITY", "SAME_ENTITY"):
            return {"ok": False, "error": "Choose Clear or Escalate."}
        if not by:
            return {"ok": False, "error": "Add your name at the top first, so the decision is signed."}
        note = (payload.get("note") or "").strip()
        if len(note) < 10:
            return {"ok": False, "error": "Write a short reason (at least 10 characters). It goes in the audit trail."}
        row = self.desk.output[hit_id]
        if decision == "DIFFERENT_ENTITY" and row["decision"] == "SAME_ENTITY":
            note = note  # allowed, but approval is mandatory below
        record = self.append({
            "kind": "decision", "hit_id": hit_id, "alert_id": row.get("alert_id"),
            "decision": decision, "engine_decision": row["decision"], "note": note[:600], "by": by[:60],
        })
        return {"ok": True, "decision": record}

    def approve(self, payload):
        hit_id = payload.get("hit_id")
        by = (payload.get("by") or "").strip()
        decisions, _ = self.state()
        current = decisions.get(hit_id)
        if not current or current.get("approval") != "pending":
            return {"ok": False, "error": "There is no decision waiting for approval on this hit."}
        if not by:
            return {"ok": False, "error": "Add your name at the top first."}
        if by.lower() == (current.get("by") or "").lower():
            return {"ok": False, "error": "A second analyst must approve. You made this decision."}
        approve = bool(payload.get("approve"))
        note = (payload.get("note") or "").strip()
        if not approve and len(note) < 10:
            return {"ok": False, "error": "Say why you are sending it back (at least 10 characters)."}
        record = self.append({
            "kind": "approval", "hit_id": hit_id, "alert_id": current.get("alert_id"),
            "decision_id": current["id"], "approve": approve, "note": note[:600], "by": by[:60],
        })
        return {"ok": True, "approval": record}

    def issue(self, payload):
        hit_id = payload.get("hit_id")
        if hit_id not in self.desk.output:
            return {"ok": False, "error": "Unknown hit."}
        known = {i["issue_id"]: i for i in self.issues(hit_id)}
        issue_id = payload.get("issue_id")
        status = payload.get("status")
        by = (payload.get("by") or "").strip()
        if issue_id not in known:
            return {"ok": False, "error": "Unknown issue."}
        if status not in ("open", "requested", "resolved", "accepted"):
            return {"ok": False, "error": "Unknown status."}
        if not by:
            return {"ok": False, "error": "Add your name at the top first."}
        note = (payload.get("note") or "").strip()
        if status in ("resolved", "accepted") and len(note) < 10:
            return {"ok": False, "error": "Say how it was resolved, or why the risk is accepted (at least 10 characters)."}
        record = self.append({
            "kind": "issue", "hit_id": hit_id, "alert_id": known[issue_id]["alert_id"], "issue_id": issue_id,
            "status": status, "note": note[:600], "by": by[:60],
        })
        return {"ok": True, "issue": record}

    def log_request(self, payload):
        alert_id = payload.get("alert_id")
        by = (payload.get("by") or "").strip() or "Someone"
        draft = self.request_draft(alert_id, payload.get("issue_ids") or [])
        if not draft:
            return {"ok": False, "error": "Unknown alert."}
        self.append({"kind": "request", "alert_id": alert_id, "by": by[:60], "note": "Information request drafted (not sent)"})
        return {"ok": True, **draft}

    def export(self, fmt):
        decisions, issues = self.state()
        rows = []
        for hit_id, row in sorted(self.desk.output.items()):
            decision, who = self.final(hit_id, decisions)
            made = decisions.get(hit_id) or {}
            rows.append({
                "hit_id": hit_id,
                "alert_id": row.get("alert_id"),
                "engine_decision": row["decision"],
                "engine_reason_code": row["reason_code"],
                "final_decision": decision,
                "decided_by": who if who == "engine" else f"{made.get('by')} (approved by {made.get('approver')})",
                "analyst_note": made.get("note") or "",
                "customer_record_id": row.get("customer_record_id"),
                "reason": row.get("reason"),
                "evidence": ";".join(row.get("evidence") or []),
            })
        if fmt == "csv":
            out = io.StringIO()
            writer = csv.DictWriter(out, fieldnames=list(rows[0].keys()) if rows else ["hit_id"])
            writer.writeheader()
            writer.writerows(rows)
            return out.getvalue().encode("utf-8"), "text/csv; charset=utf-8", "csv"
        body = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)
        return body.encode("utf-8"), "application/x-ndjson; charset=utf-8", "jsonl"


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

RUNS_STATE = None
CURRENT = {"run_id": None}


def current_case():
    run_id = CURRENT.get("run_id")
    return RUNS_STATE.desk(run_id) if run_id else None


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def _send(self, code, body, kind, extra=None):
        self.send_response(code)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, payload, code=200):
        self._send(code, json.dumps(payload, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def _body(self):
        length = int(self.headers.get("Content-Length") or 0)
        try:
            return json.loads(self.rfile.read(length).decode("utf-8") or "{}")
        except json.JSONDecodeError:
            return {}

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path, query = parsed.path, urllib.parse.parse_qs(parsed.query)
        if path in ("/", "/index.html"):
            return self._send(200, (STATIC / "index.html").read_bytes(), "text/html; charset=utf-8")
        if path.startswith("/static/"):
            target = (STATIC / path[len("/static/"):]).resolve()
            if STATIC.resolve() not in target.parents or not target.is_file():
                return self._send(404, b"not found", "text/plain")
            kind = {"css": "text/css", "js": "text/javascript", "svg": "image/svg+xml"}.get(target.suffix[1:], "text/plain")
            return self._send(200, target.read_bytes(), kind + "; charset=utf-8")
        if path == "/favicon.ico":
            return self._send(200, (STATIC / "icon.svg").read_bytes(), "image/svg+xml")
        if path == "/api/state":
            case = current_case()
            return self._json({
                "runs": RUNS_STATE.list(),
                "current": CURRENT.get("run_id"),
                "job": RUNS_STATE.job,
                "ready": case is not None,
                "default_data": str(DEFAULT_DATA) if DEFAULT_DATA else "",
            })
        case = current_case()
        if path.startswith("/api/") and case is None:
            return self._json({"error": "No screening run is open. Start one from Runs."}, 409)
        if path == "/api/overview":
            return self._json(case.overview())
        if path == "/api/alerts":
            return self._json({"alerts": case.alert_rows(query.get("status", ["all"])[0], query.get("q", [""])[0])})
        if path.startswith("/api/alert/"):
            detail = case.alert_detail(path.rsplit("/", 1)[-1])
            return self._json(detail) if detail else self._json({"error": "Unknown alert"}, 404)
        if path.startswith("/api/record/"):
            record = case.desk.raw_record(urllib.parse.unquote(path.rsplit("/", 1)[-1]))
            return self._json(record) if record else self._json({"error": "Not in this data folder"}, 404)
        if path == "/api/export":
            fmt = query.get("format", ["csv"])[0]
            body, kind, ext = case.export(fmt)
            name = f"namesake-{case.run_id}.{ext}"
            return self._send(200, body, kind, {"Content-Disposition": f'attachment; filename="{name}"'})
        return self._send(404, b"not found", "text/plain")

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        payload = self._body()
        if path == "/api/run":
            return self._json(RUNS_STATE.start(payload.get("data_dir") or ""))
        if path == "/api/open":
            run_id = payload.get("run_id")
            meta = RUNS_STATE.meta(run_id) if run_id else None
            if not meta or meta.get("state") != "done":
                return self._json({"ok": False, "error": "That run is not finished."})
            CURRENT["run_id"] = run_id
            RUNS_STATE.desk(run_id)
            return self._json({"ok": True})
        case = current_case()
        if case is None:
            return self._json({"ok": False, "error": "No screening run is open."}, 409)
        if path == "/api/decide":
            return self._json(case.decide(payload))
        if path == "/api/approve":
            return self._json(case.approve(payload))
        if path == "/api/issue":
            return self._json(case.issue(payload))
        if path == "/api/request":
            return self._json(case.log_request(payload))
        if path == "/api/draft":
            return self._json(case.desk.draft_wording(payload.get("hit_id")))
        return self._send(404, b"not found", "text/plain")


DEFAULT_DATA = None


def main():
    global RUNS_STATE, DEFAULT_DATA
    parser = argparse.ArgumentParser(description="Namesake analyst workbench")
    parser.add_argument("--data", help="data folder to screen (the folder with hits.jsonl)")
    parser.add_argument("--import-output", help="open an existing output file instead of running the engine")
    parser.add_argument("--port", type=int, default=8780)
    args = parser.parse_args()
    desk_mod._load_env()
    RUNS_STATE = Runs()
    if args.data:
        DEFAULT_DATA = Path(args.data).expanduser().resolve()
    runs = [r for r in RUNS_STATE.list() if r.get("state") == "done"]
    if args.import_output and DEFAULT_DATA:
        meta = RUNS_STATE.import_output(DEFAULT_DATA, args.import_output, f"Imported {Path(args.import_output).name}")
        runs = [meta] + runs
    if runs:
        CURRENT["run_id"] = runs[0]["run_id"]
        sys.stderr.write(f"Opening run {runs[0]['run_id']} (loading the data folder…)\n")
        RUNS_STATE.desk(runs[0]["run_id"])
    try:
        server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    except OSError as error:
        sys.stderr.write(f"error: port {args.port} is busy ({error}). Try --port {args.port + 1}\n")
        sys.exit(1)
    sys.stderr.write(f"Namesake on http://127.0.0.1:{args.port}/\n")
    server.serve_forever()


if __name__ == "__main__":
    main()
