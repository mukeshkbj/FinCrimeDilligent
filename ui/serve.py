#!/usr/bin/env python3
"""Demo desk for a recorded screening run.

The browser only displays. Decisions are read from an output JSONL file
produced by system/run. This process never decides a hit.

Usage:
    python3 ui/serve.py <data_dir> <output_file> [port]

Prints one line you can open, for example:
    screening desk on http://127.0.0.1:8765/
It does not open a browser. If that port is already taken on localhost, it exits
with an error instead of binding a different interface that would confuse you.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import unicodedata
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import workflow

ROOT = Path(__file__).resolve().parents[1]
STATIC = Path(__file__).resolve().parent / "static"

# Fixed story. Titles are for the analyst. Outcomes come from the output file.
STORY = [
    {
        "id": "S1",
        "hit_id": "H-582410",
        "title": "Elvira Velasco Morillo",
        "wow": False,
        "rule": "Your rules §4",
        "asked": "A joint account holder looks like a listed person. Does the verified date and country agree?",
        "expect_decision": "SAME_ENTITY",
        "expect_code": "NAME_DOB_LOCATION_MATCH",
        "checked_ok": "Checked: name, date and country agree, so this was sent to compliance.",
        "checked_bad": "Something here does not add up. Look before you send it on.",
    },
    {
        "id": "S2",
        "hit_id": "H-02115F",
        "title": "Pescanova",
        "wow": False,
        "rule": "Your rules §5",
        "asked": "A company name and country look like a listed company. Is it the same entity?",
        "expect_decision": "SAME_ENTITY",
        "expect_code": "NAME_LOCATION_MATCH",
        "checked_ok": "Checked: company name and country agree, so this was sent to compliance.",
        "checked_bad": "Something here does not add up. Look before you send it on.",
    },
    {
        "id": "S3",
        "hit_id": "H-13E1CF",
        "title": "Too young at the report",
        "wow": True,
        "rule": "Your rules §3",
        "asked": "Two records merge into one person born in 2007. A 2020 report names someone who would have been 13.",
        "expect_decision": "DIFFERENT_ENTITY",
        "expect_code": "TEMPORAL_IMPOSSIBILITY",
        "checked_ok": "Checked: under 16 at the report, so this hit was cleared.",
        "checked_bad": "Something here does not add up. Look before you clear it.",
    },
    {
        "id": "S4",
        "hit_id": "H-D861DA",
        "title": "Cleared on date of birth",
        "wow": False,
        "rule": "Your rules §4",
        "asked": "The profile age implies a birth year that does not match the customer file.",
        "expect_decision": "DIFFERENT_ENTITY",
        "expect_code": "DOB_MISMATCH",
        "checked_ok": "Checked: the dates contradict, so this hit was cleared.",
        "checked_bad": "Something here does not add up. Look before you clear it.",
    },
    {
        "id": "S5",
        "hit_id": "H-FF3096",
        "title": "Waits for an analyst",
        "wow": False,
        "rule": "Your rules §10",
        "asked": "The name and country agree. There is no date of birth on the list to compare.",
        "expect_decision": "REVIEW",
        "expect_code": "INSUFFICIENT_DATA",
        "checked_ok": "Checked: nothing uncertain was cleared. The memo is ready for an analyst.",
        "checked_bad": "Something here does not add up. An uncertain hit was not left for you.",
    },
]

PLAIN = {
    "DIFFERENT_ENTITY": "Cleared",
    "SAME_ENTITY": "Sent to compliance",
    "REVIEW": "Left for you",
}

PLAIN_CODE = {
    "TEMPORAL_IMPOSSIBILITY": "Too young at the report",
    "DOB_MISMATCH": "Dates do not match",
    "LOCATION_MISMATCH": "Countries do not match",
    "NAME_MISMATCH_VERIFIED": "Verified name does not match",
    "ENTITY_TYPE_MISMATCH": "Person and company clash",
    "DECEASED": "Listed person had died",
    "NAME_DOB_LOCATION_MATCH": "Name, date and country agree",
    "NAME_DOB_MATCH": "Name and date agree",
    "NAME_LOCATION_MATCH": "Name and country agree",
    "INSUFFICIENT_DATA": "Not enough to settle",
    "AMBIGUOUS_CUSTOMER_RECORD": "More than one person fits",
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
        jev_path = Path(str(output_path)[:-6] + ".verify.jsonl") if str(output_path).endswith(".jsonl") else Path(str(output_path) + ".verify.jsonl")
        self.jev = index_jsonl(jev_path, "hit_id") if jev_path.is_file() else {}
        self.labels_out = ROOT / "ui" / "analyst_labels.jsonl"
        digest = hashlib.sha256(output_path.read_bytes()).hexdigest()[:12]
        self.run_id = "recorded-" + digest
        self.repro = self._load_repro()
        self.openrouter_key = bool(os.environ.get("OPENROUTER_API_KEY"))
        workflow.prepare(self)

    def _load_repro(self):
        path = ROOT / "ui" / "static" / "repro.json"
        if not path.is_file():
            return {"status": "missing", "identical": None, "runs": 0, "label": "Run tools/repro_check.py"}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            identical = bool(payload.get("identical"))
            runs = int(payload.get("runs") or 0)
            return {
                "status": "done",
                "identical": identical,
                "runs": runs,
                "label": "5 of 5 runs identical" if identical and runs >= 5 else f"{runs} runs checked",
            }
        except Exception as error:
            return {"status": "failed", "identical": False, "runs": 0, "error": str(error)}

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
        false_positive_clears = 0
        cleared_true = 0
        cleared_said = 0
        same_true = 0
        same_caught = 0
        different_true = 0
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
            if said == "DIFFERENT_ENTITY" and truth != "DIFFERENT_ENTITY":
                false_positive_clears += 1
            if said == "DIFFERENT_ENTITY" and truth == "DIFFERENT_ENTITY":
                cleared_said += 1
            if truth == "DIFFERENT_ENTITY":
                different_true += 1
            if truth == "SAME_ENTITY":
                same_true += 1
                if said == "SAME_ENTITY":
                    same_caught += 1
        review_rate = 0.0
        totals = self.counts()
        if sum(totals.values()):
            review_rate = 100.0 * totals.get("REVIEW", 0) / sum(totals.values())
        score = 100 * max(0.0, 1 - cost / baseline) if baseline else 0
        practice_clears = cleared_said + false_positive_clears
        clearance_precision = (
            100.0 * cleared_said / practice_clears if practice_clears else 100.0
        )
        same_recall = 100.0 * same_caught / same_true if same_true else 0.0
        return {
            "available": True,
            "labels": len(self.labels),
            "right": right,
            "unsafe": unsafe,
            "decision_score": round(score, 1),
            "false_positive_clears": f"{round(100.0 * cleared_said / different_true, 1) if different_true else 0.0}%",
            "clearance_precision": round(clearance_precision, 1),
            "same_entity_recall": round(same_recall, 1),
            "review_rate": round(review_rate, 1),
        }

    def draft_wording(self, hit_id):
        """Optional Grok reword of the memo. Numbers and IDs stay from the engine.

        Uses OPENROUTER_API_KEY when set, else XAI_API_KEY (direct Grok API).
        A draft that adds any record id, date or number not in the memo is rejected.
        """
        import re
        import urllib.request

        if os.environ.get("OPENROUTER_API_KEY"):
            key = os.environ["OPENROUTER_API_KEY"]
            url = "https://openrouter.ai/api/v1/chat/completions"
            model = os.environ.get("GROK_MODEL") or "x-ai/grok-4.3"
        elif os.environ.get("XAI_API_KEY"):
            key = os.environ["XAI_API_KEY"]
            url = "https://api.x.ai/v1/chat/completions"
            model = os.environ.get("XAI_MODEL") or "grok-4.20-0309-non-reasoning"
        else:
            return {"ok": False, "error": "Add OPENROUTER_API_KEY or XAI_API_KEY and restart", "disabled": True}
        memo = workflow.analyst_memo(self, hit_id)
        if not memo:
            return {"ok": False, "error": "Memo is only for REVIEW hits"}
        body = {
            "model": model,
            "temperature": 0,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Rewrite the analyst memo in clear English for a compliance analyst. Keep every record id, "
                        "date and number exactly as given. Do not add facts. 2 to 4 short paragraphs. No markdown."
                    ),
                },
                {"role": "user", "content": memo["text"]},
            ],
        }
        request = urllib.request.Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = json.loads(response.read().decode("utf-8"))
            text = payload["choices"][0]["message"]["content"].strip()
        except Exception as error:
            return {"ok": False, "error": f"Grok did not answer ({type(error).__name__}). The memo above is unchanged."}
        facts = re.compile(r"[A-Za-z]+-[A-Za-z0-9]+|\d+(?:[-/.]\d+)*")
        added = set(facts.findall(text)) - set(facts.findall(memo["text"]))
        if added:
            return {"ok": False, "error": "Draft rejected: it added facts not in the memo (" + ", ".join(sorted(added)[:3]) + ")."}
        return {
            "ok": True,
            "label": f"Draft wording by Grok ({model}) · facts from the engine, checked",
            "text": text,
            "facts": memo,
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
                "plain_code": PLAIN_CODE.get(code, code),
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
                "memo": workflow.analyst_memo(self, spec["hit_id"]),
                "draft_available": self.openrouter_key,
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
                {"name": "Sent to compliance", "count": totals.get("SAME_ENTITY", 0)},
                {"name": "Left for you", "count": totals.get("REVIEW", 0)},
            ],
        }

    def raw_record(self, evidence_id):
        tables = (
            ("CUS-", self.customers, "record_id"),
            ("KYC-", self.kyc, "check_id"),
            ("NOTE-", self.notes, "note_id"),
            ("SR-", self.search, "result_id"),
            ("H-", self.hits, "hit_id"),
            ("A-", self.alerts, "alert_id"),
        )
        for prefix, store, _key in tables:
            if evidence_id.startswith(prefix) and evidence_id in store:
                row = store[evidence_id]
                fields = {key: row.get(key) for key in row.keys()}
                return {
                    "id": evidence_id,
                    "title": "What the auditor sees",
                    "fields": fields,
                    "raw": row,
                }
        # Accounts / applicants may only appear in evidence text.
        accounts_path = self.data_dir / "accounts.jsonl"
        if evidence_id.startswith("ACC-") and accounts_path.is_file():
            for row in read_jsonl(accounts_path):
                if row.get("account_id") == evidence_id:
                    return {"id": evidence_id, "title": "What the auditor sees", "fields": row, "raw": row}
        onboarding_path = self.data_dir / "onboarding.jsonl"
        if evidence_id.startswith("APP-") and onboarding_path.is_file():
            for row in read_jsonl(onboarding_path):
                if row.get("kyc_applicant_id") == evidence_id:
                    return {"id": evidence_id, "title": "What the auditor sees", "fields": row, "raw": row}
        return None

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
            flow = workflow.build(DESK, hit_id, _display_name)
            return self._json({
                "row": {k: v for k, v in row.items()},
                "why": DESK.why(hit_id),
                "brief": DESK.brief(hit_id),
                "trail": DESK.trail(hit_id),
                "jev": DESK.jev.get(hit_id),
                "workflow": flow,
                "memo": flow.get("memo"),
                "draft_available": DESK.openrouter_key,
            })
        if path.startswith("/api/record/"):
            evidence_id = urllib.parse.unquote(path.split("/")[-1])
            record = DESK.raw_record(evidence_id)
            if not record:
                return self._json({"error": "missing"}, 404)
            return self._json(record)
        if path == "/favicon.ico":
            return self._send(204, b"", "image/x-icon")
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
            elif name.endswith(".json"):
                kind = "application/json; charset=utf-8"
            return self._send(200, target.read_bytes(), kind)
        return self._send(404, b"not found", "text/plain")

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/draft":
            length = int(self.headers.get("Content-Length") or 0)
            try:
                payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
            except json.JSONDecodeError:
                return self._json({"ok": False, "error": "not json"}, 400)
            return self._json(DESK.draft_wording(payload.get("hit_id")))
        if parsed.path != "/api/override":
            return self._send(404, b"not found", "text/plain")
        length = int(self.headers.get("Content-Length") or 0)
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
        except json.JSONDecodeError:
            return self._json({"ok": False, "error": "not json"}, 400)
        return self._json(DESK.override(payload))


def _load_env():
    path = ROOT / ".env"
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def main():
    global DESK
    if len(sys.argv) not in (3, 4):
        sys.stderr.write("usage: python3 ui/serve.py <data_dir> <output_file> [port]\n")
        sys.exit(2)
    _load_env()
    data_dir = Path(sys.argv[1]).resolve()
    output_path = Path(sys.argv[2]).resolve()
    port = int(sys.argv[3]) if len(sys.argv) == 4 else 8765
    if not data_dir.is_dir():
        sys.stderr.write(f"error: data folder not found: {data_dir}\n")
        sys.exit(2)
    if not output_path.is_file():
        sys.stderr.write(f"error: output file not found: {output_path}\n")
        sys.exit(2)
    DESK = Desk(data_dir, output_path)
    # Bind the same host we print. Binding 0.0.0.0 while another process owns
    # 127.0.0.1:port makes the printed URL open the wrong app.
    host = "127.0.0.1"
    try:
        server = ThreadingHTTPServer((host, port), Handler)
    except OSError as error:
        sys.stderr.write(
            f"error: could not start the screening desk on http://{host}:{port}\n"
            f"  {error}\n"
            f"  Try another port, for example:\n"
            f"  python3 ui/serve.py {sys.argv[1]} {sys.argv[2]} {port + 1}\n"
        )
        sys.exit(1)
    url = f"http://{host}:{port}/"
    sys.stderr.write(
        f"screening desk on {url}\n"
        f"open that URL in your browser (this process does not open a window)\n"
        f"data={data_dir.name}  output={output_path.name}  hits={len(DESK.output)}\n"
    )
    server.serve_forever()


if __name__ == "__main__":
    main()
