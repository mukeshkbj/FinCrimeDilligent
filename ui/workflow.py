"""Read-only workflow for one recorded hit.

Stage text comes from the output line and the data files. A missing fact is
"not available". This module does not decide a hit and does not write a file.
"""

from __future__ import annotations

import re
import sys
from collections import defaultdict
from pathlib import Path

NA = "not available"

_DOC_SKIP = {"NONE", "UNKNOWN", "NULL", "TEST", "N/A", "NA"}
_ID_RE = re.compile(r"\b(?:CUS-\d{6}|KYC-[0-9A-F]+|NOTE-[0-9A-F]+|SR-[0-9A-F]+)\b")


def _engine():
    root = Path(__file__).resolve().parents[1] / "system"
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    import engine

    return engine


def _text(value):
    if value is None:
        return ""
    return str(value).strip()


def _or_na(value):
    text = _text(value)
    return text if text else NA


def _full_iso(engine, value):
    if engine is None:
        text = _text(value)
        return text if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text) else None
    parsed = engine.parse_date(value)
    if parsed and parsed.full():
        return parsed.iso()
    return None


def _iso(engine, value):
    if engine is None:
        return _text(value) or None
    parsed = engine.parse_date(value)
    if parsed and parsed.y:
        return parsed.iso()
    return None


def prepare(desk):
    """Index joins used only to display a hit. Safe to call more than once."""
    if getattr(desk, "_workflow_ready", False):
        return
    try:
        engine = _engine()
    except Exception:
        engine = None
    desk._wf_engine = engine
    desk.accounts_by_customer = defaultdict(list)
    desk.by_login = defaultdict(list)
    accounts_path = desk.data_dir / "accounts.jsonl"
    if accounts_path.is_file():
        for row in _read(accounts_path):
            customer_id = row.get("customer_id")
            if not customer_id:
                continue
            desk.accounts_by_customer[customer_id].append(row)
            login = _text(row.get("login_handle")).lower()
            if login:
                desk.by_login[login].append(customer_id)
    desk.by_email = defaultdict(list)
    desk.customer_dob_iso = {}
    for record_id, customer in desk.customers.items():
        email = _text(customer.get("email")).lower()
        if email:
            desk.by_email[email].append(record_id)
        desk.customer_dob_iso[record_id] = _full_iso(engine, customer.get("dob"))
    desk.onboarding = defaultdict(list)
    onboarding_path = desk.data_dir / "onboarding.jsonl"
    if onboarding_path.is_file():
        for row in _read(onboarding_path):
            applicant = row.get("kyc_applicant_id")
            if applicant:
                desk.onboarding[(row.get("account_id"), row.get("customer_id"))].append(applicant)
    desk.checks_by_applicant = defaultdict(list)
    for check in desk.kyc.values():
        applicant = check.get("applicant_id")
        if applicant:
            desk.checks_by_applicant[applicant].append(check)
    desk.notes_by_email = defaultdict(list)
    for note in desk.notes.values():
        email = _text(note.get("requester_email")).lower()
        if email:
            desk.notes_by_email[email].append(note)
    desk.phone_dob = defaultdict(list)
    for record_id, customer in desk.customers.items():
        phone = re.sub(r"\D", "", customer.get("phone") or "")
        dob = desk.customer_dob_iso.get(record_id)
        if len(phone) >= 8 and dob:
            desk.phone_dob[(phone, dob)].append(record_id)
    desk.docs_of = defaultdict(set)
    desk.docs = defaultdict(list)
    approved = defaultdict(list)
    for record_id in desk.customers:
        for check in _approved(desk, record_id):
            number = re.sub(r"\s+", "", _text(check.get("document_number"))).upper()
            if len(number) < 5 or number in _DOC_SKIP:
                continue
            desk.docs_of[record_id].add(number)
            approved[number].append(record_id)
    for number, ids in approved.items():
        unique = list(dict.fromkeys(ids))
        if 1 < len(unique) <= 8:
            desk.docs[number] = unique
    desk._workflow_ready = True


def _read(path):
    import json

    rows = []
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _approved(desk, record_id):
    found = []
    for account in desk.accounts_by_customer.get(record_id, []):
        for applicant in desk.onboarding.get((account.get("account_id"), record_id), []):
            for check in desk.checks_by_applicant.get(applicant, []):
                if _text(check.get("result")).lower() == "approved":
                    found.append(check)
    return found


def _expand(desk, seed):
    seen = set()
    stack = [seed]
    while stack:
        current = stack.pop()
        if current in seen or current not in desk.customers:
            continue
        seen.add(current)
        customer = desk.customers[current]
        phone = re.sub(r"\D", "", customer.get("phone") or "")
        dob = desk.customer_dob_iso.get(current)
        if len(phone) >= 8 and dob:
            for other in desk.phone_dob.get((phone, dob), []):
                if other not in seen:
                    stack.append(other)
        for number in desk.docs_of.get(current, ()):
            for other in desk.docs.get(number, []):
                if other not in seen:
                    stack.append(other)
    return tuple(sorted(seen))


def funnel(desk):
    cleared = kept = review = found = 0
    for row in desk.output.values():
        decision = row.get("decision")
        if decision == "DIFFERENT_ENTITY":
            cleared += 1
        elif decision == "SAME_ENTITY":
            kept += 1
        elif decision == "REVIEW":
            review += 1
        if row.get("customer_record_id"):
            found += 1
    return {
        "hits": len(desk.output),
        "customer_found": found,
        "cleared": cleared,
        "kept_open": kept,
        "review": review,
    }


def _line(label, value):
    return {"label": label, "value": _or_na(value)}


def _screened(alert):
    customer = (alert or {}).get("customer") or {}
    if not isinstance(customer, dict):
        customer = {}
    return customer


def _how(desk, alert):
    if not alert:
        return NA, NA, []
    account = _text(alert.get("account_ref"))
    if account:
        return "Account", account, list(desk.accounts.get(account, []))
    login = _text(alert.get("login_handle"))
    if login:
        return "Login", login, list(dict.fromkeys(desk.by_login.get(login.lower(), [])))
    email = _text(alert.get("email"))
    if email:
        return "Email", email, list(dict.fromkeys(desk.by_email.get(email.lower(), [])))
    return "Attributes", "", []


def _identity(desk, group):
    engine = desk._wf_engine
    candidates = []
    for record_id in group:
        customer = desk.customers.get(record_id) or {}
        for check in _approved(desk, record_id):
            candidates.append(
                {
                    "id": check.get("check_id"),
                    "when": _text(check.get("checked_at")),
                    "kind": "Approved check",
                    "name": _text(check.get("verified_name")),
                    "dob": _iso(engine, check.get("verified_dob")) or _text(check.get("verified_dob")),
                    "country": _canon(desk, check.get("document_country")) or _text(check.get("document_country")),
                    "result": _text(check.get("result")),
                }
            )
        email = _text(customer.get("email")).lower()
        for note in desk.notes_by_email.get(email, []):
            parsed = None
            if engine is not None:
                try:
                    parsed = engine.parse_identity_note(note.get("text") or "")
                except Exception:
                    parsed = None
            if not parsed:
                continue
            checked = parsed.get("checked")
            when = checked.iso() if checked is not None and hasattr(checked, "iso") else _text(note.get("created_at"))
            dob = parsed.get("dob")
            candidates.append(
                {
                    "id": note.get("note_id"),
                    "when": when,
                    "kind": "Identity note",
                    "name": _text(parsed.get("name")),
                    "dob": dob.iso() if dob is not None and hasattr(dob, "iso") else "",
                    "country": _text(parsed.get("country")),
                    "result": "approved",
                }
            )
    candidates.sort(key=lambda item: (item["when"], item["id"] or ""), reverse=True)
    return candidates[0] if candidates else None


def _canon(desk, value):
    engine = desk._wf_engine
    if engine is None or not _text(value):
        return ""
    try:
        return engine.canon_field(value) or ""
    except Exception:
        return ""


def _country_set(desk, values):
    found = []
    engine = desk._wf_engine
    for value in values:
        if not _text(value):
            continue
        canon = _canon(desk, value)
        if canon and canon not in found:
            found.append(canon)
            continue
        if engine is None:
            continue
        try:
            for _index, name in engine.find_countries(str(value)):
                if name not in found:
                    found.append(name)
        except Exception:
            continue
    return found


def _hit_countries(desk, hit):
    values = []
    for field in ("countries", "nationality", "citizenship", "addresses"):
        raw = hit.get(field) or []
        if isinstance(raw, str):
            raw = [raw]
        values.extend(raw)
    if hit.get("place_of_birth"):
        values.append(hit.get("place_of_birth"))
    return _country_set(desk, values)


def _customer_countries(desk, group, latest, evidence_notes):
    values = []
    if latest and latest.get("country"):
        values.append(latest["country"])
    for record_id in group:
        customer = desk.customers.get(record_id) or {}
        values.append(customer.get("nationality"))
        values.append(customer.get("residence_country"))
    for note in evidence_notes:
        values.append(note.get("text") or "")
    # Places named on the person's other notes are part of the file, not a guess.
    for record_id in group:
        customer = desk.customers.get(record_id) or {}
        email = _text(customer.get("email")).lower()
        for note in desk.notes_by_email.get(email, []):
            if latest and note.get("note_id") == latest.get("id"):
                continue
            values.append(note.get("text") or "")
    return _country_set(desk, values)


def _cited_date(reason):
    match = re.search(
        r"(\d{4}(?:-\d{2}){0,2}) \(((?:KYC|NOTE|CUS)-[0-9A-Z]+)",
        reason or "",
    )
    if not match:
        return "", ""
    return match.group(1), match.group(2)


def _list_dob(reason, hit):
    dobs = [str(item) for item in (hit.get("dobs") or []) if _text(item)]
    if dobs:
        return ", ".join(dobs)
    text = reason or ""
    low = text.lower()
    if "cannot be compared" in low or "not on the list entry" in low or "no date of birth" in low or "cannot be settled" in low:
        return ""
    for pattern in (
        r"agrees with hit DOB ([^(.;]+)",
        r"Hit DOB ([^(.;]+)",
        r"hit DOB ([^(.;]+)",
        r"agrees with the hit's ([^.]+)",
        r"birth year at ([^.]+)",
        r"listed date of birth is ([^.]+)",
        r"activity on ([^.]+)",
    ):
        match = re.search(pattern, text, re.I)
        if match and re.search(r"\d{4}", match.group(1)):
            return match.group(1).strip()
    return ""


def _name_mark(reason, code, name_agree=None):
    """Prefer the engine's name_agree flag; fall back to the reason text."""
    if name_agree is True:
        return "matches"
    if name_agree is False and code == "NAME_MISMATCH_VERIFIED":
        return "clashes"
    low = (reason or "").lower()
    if "not cleared on name" in low or "may transliterate" in low or "could be transliterations" in low:
        return "missing"
    if "does not match" in low or "agrees with none" in low or code == "NAME_MISMATCH_VERIFIED":
        return "clashes"
    if "name agrees" in low or ("transliterates to" in low and "matching" in low) or ("cjk name" in low and "matches" in low):
        return "matches"
    if code in ("NAME_DOB_MATCH", "NAME_DOB_LOCATION_MATCH", "NAME_LOCATION_MATCH"):
        return "matches"
    if name_agree is False:
        return "clashes"
    return None


def _dob_mark(reason, code, customer_value, list_value, dob_agree=None):
    low = (reason or "").lower()
    list_missing = not list_value or list_value == NA or "not available" in str(list_value).lower()
    if list_missing or "cannot be compared" in low or "not on the list entry" in low or "cannot be settled" in low or "no date of birth" in low:
        return "missing"
    if dob_agree is True or "agrees with hit dob" in low or re.search(r"date of birth[^.]*agrees with the hit", low) or code in ("NAME_DOB_MATCH", "NAME_DOB_LOCATION_MATCH"):
        return "matches"
    # Age-at-report is shown on its own Time row; DOB itself is not a clash.
    if code == "TEMPORAL_IMPOSSIBILITY":
        return "missing" if list_missing else "matches" if dob_agree else "missing"
    if code == "DOB_MISMATCH" or "contradict" in low:
        return "clashes"
    if not customer_value or not list_value:
        return "missing"
    return "missing"


def _time_row(reason, code):
    if code != "TEMPORAL_IMPOSSIBILITY":
        return None
    match = re.search(
        r"at most (\d+) on (\d{4}-\d{2}-\d{2}).*under 16",
        reason or "",
        re.I,
    )
    if match:
        age, when = match.group(1), match.group(2)
        return {
            "field": "Time",
            "customer": f"{age} at the {when} report",
            "list": "under 16",
            "mark": "clashes",
        }
    return {
        "field": "Time",
        "customer": "too young at the report",
        "list": "under 16",
        "mark": "clashes",
    }


def _compare(desk, reason, code, hit, list_name, group, latest, customer, fallback_name="", flags=None):
    flags = flags or {}
    verified = re.search(r"[Vv]erified name ([^(]+?) \(", reason or "")
    on_file = re.search(r"customer name on file is ([^.]+)", reason or "", re.I)
    if verified:
        customer_name = verified.group(1).strip()
    elif latest and latest.get("name"):
        customer_name = latest["name"]
    elif on_file:
        customer_name = on_file.group(1).strip()
    elif customer:
        customer_name = _text(customer.get("full_name"))
    elif fallback_name:
        customer_name = fallback_name
    else:
        customer_name = ""
    cited_dob, cited_id = _cited_date(reason)
    if cited_dob:
        customer_dob = f"{cited_dob} ({cited_id})" if cited_id else cited_dob
    elif latest and latest.get("dob"):
        customer_dob = latest["dob"]
    elif customer:
        customer_dob = _text(customer.get("dob"))
    else:
        customer_dob = ""
    list_dob = _list_dob(reason, hit)
    name_mark = _name_mark(reason, code, flags.get("name_agree"))
    if name_mark is None:
        name_mark = "missing"
    dob_mark = _dob_mark(reason, code, customer_dob, list_dob, flags.get("dob_agree"))
    both = re.search(r"Shared country ([A-Z][^.(;]{0,48}?)(?: in | \()", reason or "") or re.search(
        r"Both the customer and the hit are linked to ([^.]+)", reason or ""
    )
    only = re.search(
        r"The customer is linked only to ([^.]+?) but the hit is linked only to ([^.]+)",
        reason or "",
    ) or re.search(r"do not overlap|countries do not", reason or "", re.I)
    notes = [desk.notes[item] for item in (re.findall(r"NOTE-[0-9A-F]+", reason or "")) if item in desk.notes]
    customer_set = _customer_countries(desk, group, latest, notes)
    hit_set = _hit_countries(desk, hit)
    if both:
        place = both.group(1).strip()
        customer_country = place
        list_country = place
        country_mark = "matches"
    elif only and only.lastindex and only.lastindex >= 2:
        customer_country = only.group(1).strip()
        list_country = only.group(2).strip()
        country_mark = "clashes"
    else:
        customer_country = ", ".join(customer_set)
        list_country = ", ".join(hit_set)
        if only:
            country_mark = "clashes"
        elif not customer_set or not hit_set:
            country_mark = "missing"
        elif set(customer_set) & set(hit_set):
            country_mark = "matches"
        else:
            country_mark = "clashes"
    customer_type = _text((customer or {}).get("entity_type")) or _text(_screened(desk.alerts.get(hit.get("alert_id"))).get("entity_type"))
    list_type = _text(hit.get("entity_type"))
    low = (reason or "").lower()
    if code == "ENTITY_TYPE_MISMATCH" or "hit is an individual" in low or "hit is a company" in low:
        type_mark = "clashes"
    elif not customer_type or not list_type:
        type_mark = "missing"
    elif customer_type.casefold() == list_type.casefold():
        type_mark = "matches"
    else:
        type_mark = "clashes"
    rows = [
        {"field": "Name", "customer": _or_na(customer_name), "list": _or_na(list_name), "mark": name_mark},
        {"field": "DOB", "customer": _or_na(customer_dob), "list": _or_na(list_dob), "mark": dob_mark},
        {"field": "Country", "customer": _or_na(customer_country), "list": _or_na(list_country), "mark": country_mark},
        {"field": "Type", "customer": _or_na(customer_type), "list": _or_na(list_type), "mark": type_mark},
    ]
    time_row = _time_row(reason, code)
    if time_row:
        rows.append(time_row)
    low_reason = (reason or "").lower()
    if "not cleared on name" in low_reason or "may transliterate" in low_reason or "could be transliterations" in low_reason:
        clause = re.search(r".{0,220}not cleared on name", reason or "", re.I)
        if clause:
            note = clause.group(0).strip()
            rows[0]["note"] = note if note.endswith(".") else note + "."
    return rows


def analyst_memo(desk, hit_id):
    """One-page REVIEW memo from engine facts. No model."""
    prepare(desk)
    row = desk.output.get(hit_id) or {}
    if row.get("decision") != "REVIEW":
        return None
    hit = desk.hits.get(hit_id) or {}
    reason = row.get("reason") or ""
    code = row.get("reason_code") or ""
    evidence = list(row.get("evidence") or [])
    log = (getattr(desk, "jev", {}) or {}).get(hit_id) or {}
    flags = {
        "name_agree": log.get("name_agree"),
        "dob_agree": log.get("dob_agree"),
    }
    customer_id = row.get("customer_record_id")
    customer = desk.customers.get(customer_id) if isinstance(customer_id, str) and customer_id.startswith("CUS-") else None
    group = _expand(desk, customer_id) if customer else tuple()
    latest = _identity(desk, group) if group else None
    list_name = hit.get("name") or ""
    compare = _compare(desk, reason, code, hit, list_name, group, latest, customer, flags=flags)
    agrees = [f"{item['field']}: {item['customer']} · {item['list']}" for item in compare if item.get("mark") == "matches"]
    clashes = [f"{item['field']}: {item['customer']} · {item['list']}" for item in compare if item.get("mark") == "clashes"]
    missing = [f"{item['field']}: {item['customer']} · {item['list']}" for item in compare if item.get("mark") == "missing"]
    if not (hit.get("dobs") or []):
        missing.append("The list profile has no date of birth in its date field.")
    if customer_id == "AMBIGUOUS":
        missing.append("More than one person fits the screened details.")
        settle = "A full date of birth or a document number that picks one of those people."
    elif not (hit.get("dobs") or []):
        settle = "A listed date of birth for the hit would settle it."
    else:
        settle = "One more fact that either contradicts the list profile or agrees on name and date."
    rejected = []
    hit_countries = set(_hit_countries(desk, hit))
    for result_id, result in sorted((getattr(desk, "search", {}) or {}).items()):
        if result.get("hit_id") and result.get("hit_id") != hit_id:
            continue
        snippet = _text(result.get("snippet"))[:120]
        query = _text(result.get("query"))
        if not snippet and not query:
            continue
        if result_id in evidence:
            continue
        # Namesakes seen in search but not used as evidence.
        if query and list_name and list_name.split(",")[0].split()[0].lower() in query.lower():
            rejected.append({
                "id": result_id,
                "reason": "Namesake search result; not used because it did not supply a usable date for this listing.",
            })
        if len(rejected) >= 5:
            break
    sources = list(evidence)
    lines = [
        "Analyst memo",
        "",
        "What agrees",
        *(agrees or ["Nothing firmly agrees yet."]),
        "",
        "What contradicts",
        *(clashes or ["Nothing contradicts"]),
        "",
        "What's missing",
        *(missing or ["Nothing obvious is missing from the compare stage."]),
        "",
        "The one document that would settle it",
        settle,
        "",
        "Sources checked",
        *(sources or ["No cited records."]),
    ]
    if rejected:
        lines.append("")
        lines.append("Search results seen and rejected as namesakes")
        for item in rejected:
            lines.append(f"{item['id']}: {item['reason']}")
    text = "\n".join(lines)
    return {
        "title": "Analyst memo",
        "agrees": agrees or ["Nothing firmly agrees yet."],
        "contradicts": clashes or ["Nothing contradicts"],
        "missing": missing or ["Nothing obvious is missing from the compare stage."],
        "would_settle": settle,
        "sources": sources,
        "rejected": rejected,
        "text": text,
        "flags": flags,
    }


def build(desk, hit_id, display_name):
    prepare(desk)
    row = desk.output.get(hit_id) or {}
    hit = desk.hits.get(hit_id) or {}
    alert = desk.alerts.get(hit.get("alert_id") or row.get("alert_id")) or {}
    screened = _screened(alert)
    reason = row.get("reason") or ""
    code = row.get("reason_code") or ""
    decision = row.get("decision") or ""
    evidence = list(row.get("evidence") or [])
    list_name = display_name(hit) if hit else ""
    how, how_value, holders = _how(desk, alert)
    customer_id = row.get("customer_record_id")
    ambiguous = customer_id == "AMBIGUOUS"
    customer = desk.customers.get(customer_id) if isinstance(customer_id, str) and customer_id.startswith("CUS-") else None
    group = _expand(desk, customer_id) if customer else tuple()
    latest = _identity(desk, group) if group else None

    alert_lines = [
        _line("Alert", alert.get("alert_id") or row.get("alert_id")),
        _line("Screened", alert.get("screened_at")),
        _line("Name", screened.get("name")),
        _line("Type", screened.get("entity_type")),
        _line("Date of birth", screened.get("dob")),
        _line("Country", screened.get("country")),
        _line("City", screened.get("city")),
    ]
    if how == "Account":
        alert_lines.append(_line("Account", how_value))
    elif how == "Login":
        alert_lines.append(_line("Login", how_value))
    elif how == "Email":
        alert_lines.append(_line("Email", how_value))
    else:
        alert_lines.append(_line("Link", "No account, login, or email" if alert else NA))

    found_lines = [_line("How", how)]
    if how == "Attributes":
        found_lines.append(_line("Screened name", screened.get("name")))
        found_lines.append(_line("Screened date", screened.get("dob")))
        found_lines.append(_line("Screened country", screened.get("country")))
        found_lines.append(_line("Screened city", screened.get("city")))
    else:
        found_lines.append(_line(how, how_value))
    if holders and len(holders) > 1:
        found_lines.append(_line("Holders", ", ".join(holders)))
    found_lines.append(_line("Customer", customer_id))
    if ambiguous:
        cited = [item for item in evidence if str(item).startswith("CUS-")]
        named = []
        for record_id in cited:
            person = desk.customers.get(record_id) or {}
            name = _text(person.get("full_name"))
            named.append(f"{record_id} {name}".strip())
        found_lines.append(_line("People", "; ".join(named) if named else NA))
    elif customer:
        found_lines.append(_line("File name", customer.get("full_name")))

    identity_lines = []
    if ambiguous:
        identity_lines.append(_line("Records", "More than one person fits, so there is no single identity."))
        identity_lines.append(_line("Latest approved check", NA))
    elif not customer_id:
        identity_lines.append(_line("Records", NA))
        identity_lines.append(_line("Latest approved check", NA))
    elif not group:
        identity_lines.append(_line("Records", f"{customer_id} is not in the customer file"))
        identity_lines.append(_line("Latest approved check", NA))
    else:
        if len(group) == 1:
            identity_lines.append(_line("Records", group[0]))
            identity_lines.append(_line("Merged", "One record. No other record shares a phone and a full date of birth, or an approved document number."))
        else:
            identity_lines.append(_line("Records", ", ".join(group)))
            identity_lines.append(_line("Merged", "These records share a phone and a full date of birth, or an approved document number."))
        if latest:
            identity_lines.append(_line("Latest", f"{latest['kind']} {latest['id']}"))
            identity_lines.append(_line("Check name", latest.get("name")))
            identity_lines.append(_line("Check date", latest.get("dob")))
            identity_lines.append(_line("Check country", latest.get("country")))
            identity_lines.append(_line("Checked", latest.get("when")))
            file_dates = [desk.customer_dob_iso.get(record_id) or _text((desk.customers.get(record_id) or {}).get("dob")) for record_id in group]
            file_dates = [item for item in file_dates if item]
            check_dob = _text(latest.get("dob"))
            if file_dates and check_dob and check_dob not in file_dates:
                identity_lines.append(_line("File date", file_dates[0]))
        else:
            identity_lines.append(_line("Latest approved check", NA))

    fallback_name = ""
    if not customer:
        names = []
        for item in evidence:
            if str(item).startswith("CUS-"):
                name = _text((desk.customers.get(item) or {}).get("full_name"))
                if name and name not in names:
                    names.append(name)
        fallback_name = "; ".join(names)
    log = (getattr(desk, "jev", {}) or {}).get(hit_id) or {}
    flags = {
        "name_agree": log.get("name_agree"),
        "dob_agree": log.get("dob_agree"),
    }
    compare_rows = _compare(
        desk, reason, code, hit, list_name, group, latest, customer, fallback_name, flags=flags
    )
    stages = [
        {"key": "alert", "n": 1, "title": "Alert", "lines": alert_lines},
        {"key": "customer", "n": 2, "title": "Customer found", "lines": found_lines},
        {"key": "identity", "n": 3, "title": "Identity built", "lines": identity_lines},
        {"key": "compare", "n": 4, "title": "Compare", "rows": compare_rows},
        {
            "key": "decision",
            "n": 5,
            "title": "Decision",
            "decision": decision or NA,
            "reason_code": code or NA,
            "reason": reason or NA,
            "evidence": evidence or [],
        },
    ]
    memo = analyst_memo(desk, hit_id) if decision == "REVIEW" else None
    return {
        "hit_id": hit_id,
        "list_name": list_name or NA,
        "decision": decision or NA,
        "reason_code": code or NA,
        "stages": stages,
        "flags": flags,
        "memo": memo,
    }
