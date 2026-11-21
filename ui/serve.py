#!/usr/bin/env python3
"""Demo desk for a recorded screening run.

The browser only displays. Decisions are read from an output JSONL file
produced by system/run. This process never decides a hit.

Usage:
    python3 ui/serve.py <data_dir> <output_file> [port]
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import threading
import unicodedata
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import workflow

ROOT = Path(__file__).resolve().parents[1]
STATIC = Path(__file__).resolve().parent / "static"
ENGINE = ROOT / "system" / "engine.py"

# Fixed story. Titles are for the analyst. Outcomes come from the output file.
STORY = [
    {
        "id": "S1",
        "hit_id": "H-2808BE",
        "title": "The passport is someone else",
        "wow": False,
        "rule": "Your rules §4",
        "asked": "A typed name matches a person on a list. You need the name on the passport.",
        "expect_decision": "DIFFERENT_ENTITY",
        "expect_code": "NAME_MISMATCH_VERIFIED",
        "checked_ok": "Checked: the passport name, not the name that was typed, decided this.",
        "checked_bad": "Something here does not add up. Look before you clear it.",
    },
    {
        "id": "S2",
        "hit_id": "H-80B4B5",
        "title": "The old date of birth was wrong",
        "wow": True,
        "rule": "Your rules §4",
        "asked": "The customer file has one date of birth. A later identity note has another. A real match must not be cleared on the old date.",
        "expect_decision": "SAME_ENTITY",
        "expect_code": "NAME_DOB_LOCATION_MATCH",
        "checked_ok": "Checked: the verified date was used, so a real match was not cleared.",
        "checked_bad": "Something here does not add up. The verified date did not decide this.",
    },
    {
        "id": "S3",
        "hit_id": "H-8E4EC8",
        "title": "They are not in the same country",
        "wow": False,
        "rule": "Your rules §6",
        "asked": "The names are close. The countries are not, and there is no shared date of birth to hold the hit.",
        "expect_decision": "DIFFERENT_ENTITY",
        "expect_code": "LOCATION_MISMATCH",
        "checked_ok": "Checked: no country is shared, and name plus date of birth do not already agree.",
        "checked_bad": "Something here does not add up. Look before you clear it.",
    },
    {
        "id": "S4",
        "hit_id": "H-FF3096",
        "title": "Not enough to clear or keep",
        "wow": False,
        "rule": "Your rules §10",
        "asked": "The name and the country agree. There is no date of birth to compare.",
        "expect_decision": "REVIEW",
        "expect_code": "INSUFFICIENT_DATA",
        "checked_ok": "Checked: nothing uncertain was cleared.",
        "checked_bad": "Something here does not add up. An uncertain hit was not left for you.",
    },
    {
        "id": "S5",
        "hit_id": "H-6C7985",
        "title": "Two people fit this alert",
        "wow": False,
        "rule": "Your rules §10",
        "asked": "More than one person in the files fits the screened name, year and country.",
        "expect_decision": "REVIEW",
        "expect_code": "INSUFFICIENT_DATA",
        "expect_customer": "AMBIGUOUS",
        "checked_ok": "Checked: both people were left for you, and the customer is marked ambiguous.",
        "checked_bad": "Something here does not add up. Look before you pick a person.",
    },
]

PLAIN = {
    "DIFFERENT_ENTITY": "Cleared",
    "SAME_ENTITY": "Kept open",
    "REVIEW": "Left for you",
}

COST = {
    "DIFFERENT_ENTITY": {"DIFFERENT_ENTITY": 0, "SAME_ENTITY": 3, "REVIEW": 3},
    "SAME_ENTITY": {"DIFFERENT_ENTITY": 60, "SAME_ENTITY": 0, "REVIEW": 2},
    "REVIEW": {"DIFFERENT_ENTITY": 60, "SAME_ENTITY": 2, "REVIEW": 0},
}

BANNED = (
    "webhook",
    "endpoint",
    "dataset",
    "json",
    " api",
    "api ",
    "eval",
    "station",
    "recall",
)


def _display_name(hit):
    """Latin list name, with the original script beside it when the file has one."""
    name = hit.get("name") or ""
    native = ""
    for alias in [name] + [str(item) for item in (hit.get("aliases") or [])]:
        letters = [ch for ch in alias if ch.isalpha() and "LATIN" not in unicodedata.name(ch, "LATIN")]
        if letters:
            native = "".join(letters)[:24]
            break
    if native and native not in name:
        return f"{name} ({native})"
    return name


def read_jsonl(path):
    rows = []
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def index_jsonl(path, key):
    found = {}
    if not path.is_file():
        return found
    for row in read_jsonl(path):
        if row.get(key):
            found[row[key]] = row
    return found


class Desk:
    def __init__(self, data_dir: Path, output_path: Path):
        self.data_dir = data_dir
        self.output_path = output_path
        self.output = index_jsonl(output_path, "hit_id")
        self.alerts = index_jsonl(data_dir / "alerts.jsonl", "alert_id")
        self.hits = index_jsonl(data_dir / "hits.jsonl", "hit_id")
        self.customers = index_jsonl(data_dir / "customers.jsonl", "record_id")
        self.kyc = index_jsonl(data_dir / "kyc_checks.jsonl", "check_id")
        self.notes = index_jsonl(data_dir / "notes.jsonl", "note_id")
        self.search = index_jsonl(data_dir / "search_results.jsonl", "result_id")
        self.labels = {}
        labels_path = data_dir / "practice_labels.jsonl"
        if labels_path.is_file():
            self.labels = index_jsonl(labels_path, "hit_id")
        self.accounts = {}
        accounts_path = data_dir / "accounts.jsonl"
        if accounts_path.is_file():
            for row in read_jsonl(accounts_path):
                self.accounts.setdefault(row["account_id"], []).append(row["customer_id"])
        jev_path = Path(str(output_path)[:-6] + ".jev.jsonl") if str(output_path).endswith(".jsonl") else Path(str(output_path) + ".jev.jsonl")
        self.jev = index_jsonl(jev_path, "hit_id") if jev_path.is_file() else {}
        self.labels_out = ROOT / "ui" / "analyst_labels.jsonl"
        digest = hashlib.sha256(output_path.read_bytes()).hexdigest()[:12]
        self.run_id = "recorded-" + digest
        self.repro = {"status": "running", "identical": None, "runs": 0}
        workflow.prepare(self)
        threading.Thread(target=self._repro, daemon=True).start()

    def _decision_key(self, path):
        parts = []
        for row in read_jsonl(path):
            parts.append(row["hit_id"] + "|" + row["decision"] + "|" + row["reason_code"])
        return hashlib.sha256("\n".join(parts).encode()).hexdigest()

    def _repro(self):
        hashes = []
        try:
            for _ in range(5):
                handle = tempfile.NamedTemporaryFile(prefix="screen-", suffix=".jsonl", delete=False)
                handle.close()
                subprocess.check_call(
                    [sys.executable, str(ENGINE), str(self.data_dir), handle.name],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                hashes.append(self._decision_key(Path(handle.name)))
                os.unlink(handle.name)
            self.repro = {
                "status": "done",
                "identical": len(set(hashes)) == 1,
                "runs": 5,
                "scope": "decision and reason code",
            }
        except Exception as error:
            self.repro = {"status": "failed", "identical": False, "runs": len(hashes), "error": str(error)}

    def counts(self):
        totals = {"DIFFERENT_ENTITY": 0, "SAME_ENTITY": 0, "REVIEW": 0}
        for row in self.output.values():
            totals[row["decision"]] = totals.get(row["decision"], 0) + 1
        return totals

    def practice(self):
        if not self.labels:
            return {"available": False}
        cost = 0
        baseline = 0
        right = 0
        unsafe = 0
        for label in self.labels.values():
            answer = self.output.get(label["hit_id"], {})
            said = answer.get("decision", "REVIEW")
            truth = label["decision"]
            cost += COST[truth][said]
            baseline += COST[truth]["REVIEW"]
            if said == truth:
                right += 1
            if truth != "DIFFERENT_ENTITY" and said == "DIFFERENT_ENTITY":
                unsafe += 1
        score = 100 * max(0.0, 1 - cost / baseline) if baseline else 0
        return {
            "available": True,
            "labels": len(self.labels),
            "right": right,
            "unsafe": unsafe,
            "decision_score": round(score, 1),
        }

    def evidence_fields(self, evidence_id):
        if evidence_id.startswith("KYC-") and evidence_id in self.kyc:
            row = self.kyc[evidence_id]
            return {
                "id": evidence_id,
                "kind": "Identity check",
                "fields": {
                    "verified_name": row.get("verified_name"),
                    "verified_dob": row.get("verified_dob"),
                    "document_country": row.get("document_country"),
                    "result": row.get("result"),
                },
            }
        if evidence_id.startswith("NOTE-") and evidence_id in self.notes:
            row = self.notes[evidence_id]
            text = (row.get("text") or "").replace("\n", " ")
            return {
                "id": evidence_id,
                "kind": "Note",
                "fields": {
                    "channel": row.get("channel"),
                    "created_at": row.get("created_at"),
                    "text": text[:280],
                },
            }
        if evidence_id.startswith("CUS-") and evidence_id in self.customers:
            row = self.customers[evidence_id]
            return {
                "id": evidence_id,
                "kind": "Customer file",
                "fields": {
                    "full_name": row.get("full_name"),
                    "dob": row.get("dob"),
                    "nationality": row.get("nationality"),
                    "residence_country": row.get("residence_country"),
                },
            }
        if evidence_id.startswith("SR-") and evidence_id in self.search:
            row = self.search[evidence_id]
            return {
                "id": evidence_id,
                "kind": "Search result",
                "fields": {
                    "query": row.get("query"),
                    "snippet": (row.get("snippet") or "")[:280],
                },
            }
        return {"id": evidence_id, "kind": "Record", "fields": {}}

    def step_payload(self, spec):
        row = self.output.get(spec["hit_id"])
        hit = self.hits.get(spec["hit_id"], {})
        alert = self.alerts.get(hit.get("alert_id"), {}) if hit else {}
        screened = alert.get("customer") or {}
        if not row:
            return {
                "id": spec["id"],
                "hit_id": spec["hit_id"],
                "title": spec["title"],
                "wow": spec["wow"],
                "status": "missing",
                "simple": {
                    "rule": spec["rule"],
                    "asked": spec["asked"],
                    "happened": "This hit is not in the output file.",
                    "outcome": "Missing",
                    "checked": spec["checked_bad"],
                    "passed": False,
                },
                "detailed": {"mode": "REAL", "error": "Hit missing from output file"},
            }
        decision = row["decision"]
        code = row["reason_code"]
        customer = row.get("customer_record_id")
        passed = decision == spec["expect_decision"] and code == spec["expect_code"]
        if spec.get("expect_customer"):
            passed = passed and customer == spec["expect_customer"]
        evidence = [self.evidence_fields(item) for item in row.get("evidence") or []]
        declared = None
        if isinstance(customer, str) and customer.startswith("CUS-") and customer in self.customers:
            declared = {
                "id": customer,
                "full_name": self.customers[customer].get("full_name"),
                "dob": self.customers[customer].get("dob"),
                "used_in_decision": customer in (row.get("evidence") or []),
            }
        return {
            "id": spec["id"],
            "hit_id": spec["hit_id"],
            "title": spec["title"],
            "wow": spec["wow"],
            "status": "recorded",
            "simple": {
                "rule": spec["rule"],
                "asked": spec["asked"],
                "screened_name": screened.get("name"),
                "screened_on": alert.get("screened_at"),
                "hit_name": _display_name(hit),
                "happened": row.get("reason"),
                "outcome": PLAIN.get(decision, decision),
                "checked": spec["checked_ok"] if passed else spec["checked_bad"],
                "passed": passed,
            },
            "detailed": {
                "mode": "REAL",
                "model_used": False,
                "model_note": "This output file has no model field. The page did not call one.",
                "confidence": None,
                "confidence_note": "The rules file does not record a confidence number.",
                "decision": decision,
                "reason_code": code,
                "customer_record_id": customer,
                "alert_id": row.get("alert_id"),
                "hit_id": row.get("hit_id"),
                "reason": row.get("reason"),
                "evidence": evidence,
                "declared_customer": declared,
                "hit": {
                    "name": hit.get("name"),
                    "entity_type": hit.get("entity_type"),
                    "dobs": hit.get("dobs") or [],
                    "countries": hit.get("countries") or [],
                    "primary_category": hit.get("primary_category"),
                },
                "screened": {
                    "name": screened.get("name"),
                    "entity_type": screened.get("entity_type"),
                    "dob": screened.get("dob"),
                    "country": screened.get("country"),
                    "screened_at": alert.get("screened_at"),
                },
                "rule_check": "pass" if passed else "fail",
                "rule": spec["rule"],
                "why": self.why(spec["hit_id"]),
                "brief": self.brief(spec["hit_id"]),
                "trail": self.trail(spec["hit_id"]),
                "jev": self.jev.get(spec["hit_id"]),
                "workflow": workflow.build(self, spec["hit_id"], _display_name),
            },
        }

    def journey(self):
        steps = [self.step_payload(spec) for spec in STORY]
        passed = sum(1 for step in steps if step["simple"]["passed"])
        return {
            "run_id": self.run_id,
            "steps": steps,
            "summary": f"Checked: {passed} of {len(steps)} story checks passed, {len(steps) - passed} need a look · practice file",
        }

    def summary(self):
        totals = self.counts()
        return {
            "run_id": self.run_id,
            "hits": len(self.output),
            "totals": totals,
            "practice": self.practice(),
            "repro": self.repro,
            "funnel": workflow.funnel(self),
            "bar": [
                {"name": "Cleared", "count": totals.get("DIFFERENT_ENTITY", 0)},
                {"name": "Kept open", "count": totals.get("SAME_ENTITY", 0)},
                {"name": "Left for you", "count": totals.get("REVIEW", 0)},
            ],
        }

    def trail(self, hit_id):
        row = self.output.get(hit_id, {})
        hit = self.hits.get(hit_id, {})
        alert = self.alerts.get(hit.get("alert_id") or row.get("alert_id"), {})
        hops = []
        if alert.get("account_ref"):
            holders = self.accounts.get(alert["account_ref"], [])
            hops.append({"hop": "Account", "detail": alert["account_ref"] + " holders " + ", ".join(holders)})
        if alert.get("login_handle"):
            hops.append({"hop": "Login", "detail": alert["login_handle"]})
        if alert.get("email"):
            hops.append({"hop": "Email", "detail": alert["email"]})
        customer = row.get("customer_record_id")
        if customer:
            hops.append({"hop": "Customer", "detail": customer})
        for item in self.evidence_fields_list(row.get("evidence") or []):
            hops.append({"hop": item["kind"], "detail": item["id"] + " " + " ".join(f"{k}={v}" for k, v in item["fields"].items() if v)})
        return hops

    def evidence_fields_list(self, evidence):
        return [self.evidence_fields(item) for item in evidence]

    def brief(self, hit_id):
        row = self.output.get(hit_id)
        if not row or row.get("decision") != "REVIEW":
            return None
        hit = self.hits.get(hit_id, {})
        missing = []
        if not (hit.get("dobs") or []):
            missing.append("The list profile has no date of birth in its date field.")
        if row.get("customer_record_id") == "AMBIGUOUS":
            missing.append("More than one person fits the screened details.")
            settle = "A full date of birth or a document number that picks one of those people."
        elif not (hit.get("dobs") or []):
            settle = "A date of birth on the list profile, or an identity note that states one."
        else:
            settle = "One more fact that either contradicts the list profile or agrees on name and date."
        log = self.jev.get(hit_id) or {}
        return {"missing": missing, "would_settle": settle, "name_agree": log.get("name_agree"), "dob_agree": log.get("dob_agree")}

    def why(self, hit_id):
        row = self.output.get(hit_id)
        if not row:
            return None
        return {
            "question": "Why this result?",
            "answer": row.get("reason"),
            "from": "from your records",
            "evidence": self.evidence_fields_list(row.get("evidence") or []),
            "decision": row.get("decision"),
            "reason_code": row.get("reason_code"),
        }

    def queue(self, kind):
        rows = []
        for hit_id, row in self.output.items():
            log = self.jev.get(hit_id) or {}
            if kind == "review" and row["decision"] != "REVIEW":
                continue
            if kind == "cleared" and row["decision"] != "DIFFERENT_ENTITY":
                continue
            if kind == "kept" and row["decision"] != "SAME_ENTITY":
                continue
            if kind == "review_name_dob":
                if row["decision"] != "REVIEW" or not (log.get("name_agree") and log.get("dob_agree")):
                    continue
            hit = self.hits.get(hit_id, {})
            rows.append({
                "hit_id": hit_id,
                "alert_id": row.get("alert_id"),
                "name": hit.get("name"),
                "decision": row["decision"],
                "reason_code": row["reason_code"],
                "customer_record_id": row.get("customer_record_id"),
                "jev": "downgraded" if log.get("downgraded") else ("pass" if log else "not logged"),
            })
        rows.sort(key=lambda item: item["hit_id"])
        return {"filter": kind, "count": len(rows), "hits": rows[:80]}

    def override(self, payload):
        hit_id = payload.get("hit_id")
        decision = payload.get("decision")
        if hit_id not in self.output or decision not in PLAIN:
            return {"ok": False, "error": "Unknown hit or decision"}
        record = {
            "hit_id": hit_id,
            "decision": decision,
            "note": (payload.get("note") or "")[:240],
            "source": "demo override — not the scored file",
        }
        self.labels_out.parent.mkdir(parents=True, exist_ok=True)
        with open(self.labels_out, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        return {"ok": True, "saved": str(self.labels_out.name), "label": "Demo: your note only. The scored file is unchanged."}

    def config(self):
        return {
            "app_name": "Screening desk",
            "outcome": "Clears false sanctions hits safely, and sends every doubtful one to a person, with a precise reason.",
            "how": "It reads the customer file, the passport check and the list profile, then applies your rules.",
            "promises": [
                "A bad decision is worse than no decision, so anything uncertain goes to review.",
                "Every decision cites the record fields it used.",
                "Same input, same answer, every run.",
            ],
            "how_to_read": "Workflow is the hit, left to right. Simple is the analyst view. Detailed shows the ids and the fields behind the same steps.",
            "run_id": self.run_id,
            "modes": {
                "decisions": "REAL",
                "records": "REAL",
                "model": "not used",
            },
            "practice_banner": "Practice file. These people are invented. Nothing is sent to a customer.",
        }


DESK = None


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        sys.stderr.write("ui %s\n" % (fmt % args))

    def _send(self, code, body, content_type):
        data = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _json(self, payload, code=200):
        self._send(code, json.dumps(payload, ensure_ascii=False), "application/json; charset=utf-8")

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        if path == "/api/config":
            return self._json(DESK.config())
        if path == "/api/summary":
            return self._json(DESK.summary())
        if path == "/api/journey":
            return self._json(DESK.journey())
        if path == "/api/queue":
            kind = urllib.parse.parse_qs(parsed.query).get("filter", ["all"])[0]
            return self._json(DESK.queue(kind))
        if path.startswith("/api/hit/"):
            hit_id = path.split("/")[-1]
            row = DESK.output.get(hit_id)
            if not row:
                return self._json({"error": "missing"}, 404)
            return self._json({
                "row": {k: v for k, v in row.items()},
                "why": DESK.why(hit_id),
                "brief": DESK.brief(hit_id),
                "trail": DESK.trail(hit_id),
                "jev": DESK.jev.get(hit_id),
                "workflow": workflow.build(DESK, hit_id, _display_name),
            })
        if path in ("/", "/index.html"):
            return self._send(200, (STATIC / "index.html").read_bytes(), "text/html; charset=utf-8")
        if path.startswith("/static/"):
            name = path[len("/static/") :]
            target = (STATIC / name).resolve()
            if STATIC.resolve() not in target.parents and target != STATIC.resolve():
                return self._send(404, b"not found", "text/plain")
            if not target.is_file():
                return self._send(404, b"not found", "text/plain")
            kind = "text/plain; charset=utf-8"
            if name.endswith(".css"):
                kind = "text/css; charset=utf-8"
            elif name.endswith(".js"):
                kind = "text/javascript; charset=utf-8"
            return self._send(200, target.read_bytes(), kind)
        return self._send(404, b"not found", "text/plain")

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/api/override":
            return self._send(404, b"not found", "text/plain")
        length = int(self.headers.get("Content-Length") or 0)
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
        except json.JSONDecodeError:
            return self._json({"ok": False, "error": "not json"}, 400)
        return self._json(DESK.override(payload))


def main():
    global DESK
    if len(sys.argv) not in (3, 4):
        sys.stderr.write("usage: python3 ui/serve.py <data_dir> <output_file> [port]\n")
        sys.exit(2)
    data_dir = Path(sys.argv[1]).resolve()
    output_path = Path(sys.argv[2]).resolve()
    port = int(sys.argv[3]) if len(sys.argv) == 4 else 8765
    DESK = Desk(data_dir, output_path)
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    sys.stderr.write(f"screening desk on http://127.0.0.1:{port}\n")
    server.serve_forever()


if __name__ == "__main__":
    main()
