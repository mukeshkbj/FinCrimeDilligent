#!/usr/bin/env python3
"""Build a synthetic "unseen-style" holdout for Track 2 (Same person or not?).

Usage:  python3 make_unseen.py <dev_dir> <out_dir> [--seed N] [--reps N]

It copies the dev data room into <out_dir> (so the engine still faces 72k
customers of noise), then appends new customers, accounts, onboarding rows,
KYC checks, notes, search results, alerts and hits. The answer to every new
hit is fixed by construction from POLICY.md, never from any engine.

<out_dir>/practice_labels.jsonl holds ONLY the new hits, so
    validate.py --data <out_dir> --output <file> --score <out_dir>/practice_labels.jsonl
scores the holdout. <out_dir>/holdout_cases.jsonl adds the scenario name of each hit.

Do not commit <out_dir>: it contains the dev data room.
"""
import json, os, random, shutil, sys

FILES = ["alerts", "hits", "customers", "accounts", "onboarding", "kyc_checks", "notes", "search_results"]
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August",
          "September", "October", "November", "December"]
NUM_WORDS = {20: "twenty", 30: "thirty", 40: "forty", 50: "fifty", 60: "sixty"}
ONES = ["", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"]

FIRST_M = ["Robert", "Thomas", "Daniel", "Marco", "Stefan", "Andrei", "Kwame", "Tariq", "Lucas", "Henrik",
           "Mateo", "Pavel", "Oskar", "Rafael", "Emeka", "Joaquim", "Viktor", "Anselm", "Idris", "Bastian"]
FIRST_F = ["Helena", "Marta", "Ingrid", "Sofia", "Amara", "Leila", "Clara", "Irina", "Nadia", "Beatriz",
           "Freya", "Yasmin", "Odile", "Teresa", "Zofia", "Ines", "Mirela", "Abena", "Liesel", "Carmen"]
SYL_A = ["Var", "Kel", "Dor", "Mar", "Tes", "Bril", "Hal", "Quen", "Ost", "Vel", "Brand", "Cor", "Fen", "Lund", "Rav"]
SYL_B = ["ovic", "assen", "ingtor", "eaux", "ström", "ellini", "acourt", "isto", "ankova", "erby", "ow", "uzzi", "enholt", "ária", "ewski"]
MID = ["", "", "ar", "en", "il", "or", "ad", "um", "et", "is"]
NICK = {"Robert": "Bob", "Thomas": "Tom", "Daniel": "Danny", "Stefan": "Steve", "Mateo": "Matt",
        "Rafael": "Rafa", "Teresa": "Tess", "Helena": "Lena"}
COUNTRIES = ["United Kingdom", "Germany", "Spain", "Brazil", "Nigeria", "Poland", "Canada", "Italy",
             "Portugal", "Sweden", "Mexico", "Kenya", "Romania", "Netherlands", "Ghana", "Chile"]
DEMONYM = {"Nigeria": "Nigerian", "Germany": "German", "Spain": "Spanish", "Brazil": "Brazilian",
           "Poland": "Polish", "Kenya": "Kenyan", "Mexico": "Mexican", "Ghana": "Ghanaian"}
ISO = {"United Kingdom": "GB", "Germany": "DE", "Spain": "ES", "Nigeria": "NG", "Brazil": "BR", "Poland": "PL",
       "Canada": "CA", "Italy": "IT", "Portugal": "PT", "Sweden": "SE", "Kenya": "KE", "Mexico": "MX"}
CITY = {"United Kingdom": "Leeds", "Germany": "Leipzig", "Spain": "Valencia", "Brazil": "Recife",
        "Nigeria": "Ibadan", "Poland": "Gdansk", "Canada": "Halifax", "Italy": "Bologna", "Portugal": "Porto",
        "Sweden": "Malmo", "Mexico": "Puebla", "Kenya": "Mombasa", "Romania": "Cluj", "Netherlands": "Utrecht",
        "Ghana": "Kumasi", "Chile": "Valparaiso", "Hong Kong": "Kowloon", "China": "Shenzhen"}
LISTING = {"PEP": "a politically exposed person", "Sanctions": "a sanctioned individual",
           "Enforcement": "the subject of enforcement action", "Adverse Media": "named in adverse media"}


def words(n):
    tens, ones = divmod(n, 10)
    t = NUM_WORDS.get(tens * 10)
    return f"{t}-{ONES[ones]}" if t and ones else (t or str(n))


class Room:
    def __init__(self, dev, rng):
        self.rng = rng
        self.rows = {f: [] for f in FILES}
        self.used = set()
        self.names = set()
        for f in FILES:
            key = {"alerts": "alert_id", "hits": "hit_id", "customers": "record_id", "accounts": "account_id",
                   "onboarding": "kyc_applicant_id", "kyc_checks": "check_id", "notes": "note_id",
                   "search_results": "result_id"}[f]
            with open(os.path.join(dev, f + ".jsonl"), encoding="utf-8") as h:
                for line in h:
                    if line.strip():
                        r = json.loads(line)
                        self.used.add(r[key])
                        if f == "customers":
                            self.names.update(r["full_name"].lower().split())
        self.labels = []

    def nid(self, prefix, digits=False):
        while True:
            body = f"{self.rng.randrange(10**6):06d}" if digits else f"{self.rng.randrange(16**6):06X}"
            i = f"{prefix}-{body}"
            if i not in self.used:
                self.used.add(i)
                return i

    def surname(self):
        while True:
            s = self.rng.choice(SYL_A) + self.rng.choice(MID) + self.rng.choice(SYL_B)
            if s.lower() not in self.names:
                self.names.add(s.lower())
                return s

    def person(self, female=None):
        female = self.rng.random() < 0.5 if female is None else female
        return self.rng.choice(FIRST_F if female else FIRST_M), self.surname(), female

    # ---- bank side -------------------------------------------------------
    def customer(self, name, dob, country, etype="Individual", nationality=None, residence=None,
                 phone=None, email=None, city=None):
        rid = self.nid("CUS", digits=True)
        email = email or f"{name.split()[0].lower()}.{name.split()[-1].lower()}{self.rng.randrange(1000, 9999)}@mail.example"
        self.rows["customers"].append({
            "record_id": rid, "entity_type": etype, "full_name": name, "preferred_name": None, "login_name": None,
            "dob": dob, "nationality": nationality if nationality is not None else country,
            "residence_country": residence if residence is not None else country,
            "city": city or CITY.get(country, "Capital"), "address": f"{self.rng.randrange(1, 300)} High Street",
            "email": email, "phone": phone or f"+44 7{self.rng.randrange(10**8, 10**9)}",
            "occupation": "Retail" if etype == "Company" else "Engineer", "employer": None,
            "registration_number": None, "onboarded_at": "2023-03-14", "status": "active",
            "last_kyc_refresh": "2024-03-01"})
        return rid, email

    def account(self, holders, login=None):
        acc = self.nid("ACC")
        for cid in holders:
            self.rows["accounts"].append({"account_id": acc, "customer_id": cid, "login_handle": login,
                                          "phone": None, "opened_at": "2023-03-14", "status": "active"})
        return acc

    def kyc(self, acc, cid, vname, vdob, country, result="approved", checked="2024-06-10", company=False,
            app=None, docno=None):
        if app is None:
            app = self.nid("APP")
            self.rows["onboarding"].append({"account_id": acc, "customer_id": cid, "kyc_applicant_id": app,
                                            "onboarded_at": "2023-03-14"})
        kid = self.nid("KYC")
        self.rows["kyc_checks"].append({
            "check_id": kid, "applicant_id": app,
            "provider": "Companies registry lookup" if company else self.rng.choice(["Onfido", "Persona", "Sumsub"]),
            "verified_name": vname, "verified_dob": vdob,
            "document_type": "registry extract" if company else "passport",
            "document_number": None if company else (docno or f"P{self.rng.randrange(10**7, 10**8)}"),
            "document_country": country, "result": result, "checked_at": checked})
        return kid, app

    def note(self, email, text, channel="phone", created="2025-02-11"):
        nid = self.nid("NOTE")
        self.rows["notes"].append({"note_id": nid, "requester_email": email, "created_at": created,
                                   "channel": channel, "text": text})
        return nid

    def sr(self, hit_name, snippet):
        sid = self.nid("SR")
        q = " ".join(sorted(p.strip(",").lower() for p in hit_name.replace(",", " ").split()))
        self.rows["search_results"].append({"result_id": sid, "query": q, "title": f"{hit_name} - news",
                                            "snippet": snippet, "source": "newswire.example"})
        return sid

    # ---- list side -------------------------------------------------------
    def hit(self, alert_id, name, etype="Individual", dobs=None, countries=None, category="PEP", notes=None,
            deceased=None, aliases=None, nationality=None):
        hid = self.nid("H")
        self.rows["hits"].append({
            "hit_id": hid, "alert_id": alert_id, "match_score": self.rng.choice([92, 95, 97, 100]),
            "entity_type": etype, "name": name, "first_name": None, "middle_name": None, "last_name": None,
            "best_matching_name": None, "aliases": aliases or [], "gender": None, "dobs": dobs or [],
            "place_of_birth": None, "life_status": "Deceased" if deceased else None, "deceased_date": deceased,
            "nationality": nationality or [], "citizenship": [], "countries": countries or [], "addresses": [],
            "identifiers": [], "categories": [category], "primary_category": category, "subcategories": [],
            "position_or_allegation": None, "details": {}, "relationships": [], "profile_notes": notes,
            "sources": [], "source_urls": []})
        return hid

    def alert(self, screened_name, etype="Individual", dob=None, country=None, city=None, account_ref=None,
              login=None, email=None, screened="2026-11-12"):
        aid = self.nid("A")
        self.rows["alerts"].append({"alert_id": aid, "screened_at": screened,
                                    "customer": {"name": screened_name, "entity_type": etype, "dob": dob,
                                                 "country": country, "city": city},
                                    "account_ref": account_ref, "login_handle": login, "email": email,
                                    "hit_ids": []})
        return aid

    def attach(self, aid, hid):
        for a in self.rows["alerts"]:
            if a["alert_id"] == aid:
                a["hit_ids"].append(hid)

    def label(self, scenario, aid, hid, decision, codes, records, evidence):
        self.labels.append({"hit_id": hid, "alert_id": aid, "decision": decision, "reason_codes": codes,
                            "customer_record_ids": records, "evidence": sorted(evidence), "scenario": scenario})


# --------------------------------------------------------------------------
# Scenario builders. Each builds one alert and labels its hit(s) from POLICY.md.
# --------------------------------------------------------------------------

def base(r, country=None, female=None, dob_year=None, fmt="iso", company=False):
    """A linked individual (or company) with an approved check. Returns a dict of handles."""
    first, last, fem = r.person(female)
    country = country or r.rng.choice(COUNTRIES)
    y = dob_year or r.rng.randrange(1955, 1995)
    m, d = r.rng.randrange(1, 13), r.rng.randrange(1, 29)
    iso = f"{y:04d}-{m:02d}-{d:02d}"
    shown = {"iso": iso, "dmy": f"{d:02d}/{m:02d}/{y}", "long": f"{MONTHS[m-1]} {d}, {y}",
             "dm": f"{d} {MONTHS[m-1][:3]} {y}"}[fmt]
    name = f"{last} {r.rng.choice(['Holdings', 'Trading', 'Partners'])} {r.rng.choice(['Ltd', 'GmbH', 'SA', 'BV'])}" if company else f"{first} {last}"
    cid, email = r.customer(name, shown, country, etype="Company" if company else "Individual")
    acc = r.account([cid])
    kid, app = r.kyc(acc, cid, name if company else name.upper(), iso, country, company=company)
    return dict(first=first, last=last, fem=fem, name=name, country=country, y=y, m=m, d=d, iso=iso,
                cid=cid, email=email, acc=acc, kid=kid, app=app)


def s_dob_field_mismatch(r):
    b = base(r)
    aid = r.alert(b["name"], account_ref=b["acc"])
    hid = r.hit(aid, f"{b['last']}, {b['first']}", dobs=[str(b["y"] - r.rng.randrange(4, 15))], countries=[b["country"]])
    r.attach(aid, hid)
    r.label("dob_field_mismatch", aid, hid, "DIFFERENT_ENTITY", ["DOB_MISMATCH"], [b["cid"]], [b["kid"]])


def s_dob_same_year_other_month(r):
    b = base(r)
    m2 = b["m"] % 12 + 1
    aid = r.alert(b["name"], account_ref=b["acc"])
    hid = r.hit(aid, f"{b['first']} {b['last']}", dobs=[f"{b['y']}-{m2:02d}-{b['d']:02d}"], countries=[b["country"]])
    r.attach(aid, hid)
    r.label("dob_same_year_other_month", aid, hid, "DIFFERENT_ENTITY", ["DOB_MISMATCH"], [b["cid"]], [b["kid"]])


def s_dob_one_year_off(r):
    # +/- 1 year: not a contradiction, and not agreement either -> REVIEW
    b = base(r)
    aid = r.alert(b["name"], account_ref=b["acc"])
    hid = r.hit(aid, f"{b['last']}, {b['first']}", dobs=[str(b["y"] + r.rng.choice([-1, 1]))], countries=[b["country"]])
    r.attach(aid, hid)
    r.label("dob_one_year_off", aid, hid, "REVIEW", ["INSUFFICIENT_DATA"], [b["cid"]], [b["cid"], b["kid"]])


def s_one_agreeing_date_blocks(r):
    b = base(r)
    aid = r.alert(b["name"], account_ref=b["acc"])
    hid = r.hit(aid, f"{b['last']}, {b['first']}", dobs=[str(b["y"] - 20), str(b["y"])], countries=[b["country"]])
    r.attach(aid, hid)
    r.label("one_agreeing_date_blocks_clear", aid, hid, "SAME_ENTITY",
            ["NAME_DOB_LOCATION_MATCH", "NAME_DOB_MATCH"], [b["cid"]], [b["cid"], b["kid"]])


AGE_TEMPLATES = [
    "When the {what} took place in {mon} {yr}, {name} was {age}.",
    "{name}, aged {agew}, was named in {mon} {yr} in connection with a {what}.",
    "In {mon} {yr} a {age}-year-old {name} appeared before the court.",
    "{name} ({age}) was questioned by investigators in {mon} {yr}.",
    "By {mon} {yr}, {name} had reached the age of {age}.",
    "Reports from {mon} {yr} describe {name} as {age} years old at the time.",
]


def _age_note(r, name, birth_year, tmpl):
    yr = r.rng.randrange(birth_year + 25, min(birth_year + 55, 2026))
    mon_i = r.rng.randrange(0, 12)
    age = yr - birth_year - r.rng.choice([0, 1])  # birthday before/after -> 2 candidate years incl. true one
    text = tmpl.format(what=r.rng.choice(["inquiry", "trial", "hearing"]), mon=MONTHS[mon_i], yr=yr,
                       name=name, age=age, agew=words(age))
    return text + "\n\nCareer:\nRegional official (2010 - 2018)."


def s_age_note_mismatch(r, k):
    b = base(r)
    hit_name = f"{b['first']} {b['last']}"
    true_birth = b["y"] - r.rng.randrange(5, 14)
    aid = r.alert(b["name"], account_ref=b["acc"])
    hid = r.hit(aid, hit_name, countries=[b["country"]], notes=_age_note(r, hit_name, true_birth, AGE_TEMPLATES[k]))
    r.attach(aid, hid)
    r.label(f"age_note_mismatch_t{k}", aid, hid, "DIFFERENT_ENTITY", ["DOB_MISMATCH"], [b["cid"]], [b["kid"]])


def s_age_note_match(r, k):
    b = base(r)
    hit_name = f"{b['first']} {b['last']}"
    aid = r.alert(b["name"], account_ref=b["acc"])
    hid = r.hit(aid, hit_name, countries=[b["country"]], notes=_age_note(r, hit_name, b["y"], AGE_TEMPLATES[k]))
    r.attach(aid, hid)
    r.label(f"age_note_match_t{k}", aid, hid, "SAME_ENTITY", ["NAME_DOB_LOCATION_MATCH", "NAME_DOB_MATCH"],
            [b["cid"]], [b["cid"], b["kid"]])


def s_temporal_person(r):
    b = base(r, dob_year=r.rng.randrange(2003, 2009))
    rep = b["y"] + r.rng.randrange(6, 13)
    notes = (f"According to {r.rng.choice(['Reuters', 'the Daily Courier', 'bbc.co.uk'])}; "
             f"{MONTHS[r.rng.randrange(12)]} {r.rng.randrange(1, 28)}, {rep}: {b['first']} {b['last']} was arrested "
             f"on suspicion of fraud.")
    aid = r.alert(b["name"], account_ref=b["acc"])
    hid = r.hit(aid, f"{b['first']} {b['last']}", countries=[b["country"]], category="Adverse Media", notes=notes)
    r.attach(aid, hid)
    r.label("temporal_person", aid, hid, "DIFFERENT_ENTITY", ["TEMPORAL_IMPOSSIBILITY"], [b["cid"]], [b["kid"]])


def s_temporal_spanish_line_ignored(r):
    # Only English "According to ...; Month D, YYYY:" lines count. A Spanish line is not a dated report.
    b = base(r, dob_year=r.rng.randrange(2003, 2008))
    rep = b["y"] + 8
    notes = f"Según El País; 3 de marzo de {rep}: {b['first']} {b['last']} fue detenido por fraude."
    aid = r.alert(b["name"], account_ref=b["acc"])
    hid = r.hit(aid, f"{b['first']} {b['last']}", countries=[b["country"]], category="Adverse Media", notes=notes)
    r.attach(aid, hid)
    r.label("spanish_report_line_ignored", aid, hid, "REVIEW", ["INSUFFICIENT_DATA"], [b["cid"]], [b["cid"], b["kid"]])


def s_temporal_company(r):
    b = base(r, company=True, dob_year=r.rng.randrange(2016, 2022))
    rep = b["y"] - r.rng.randrange(3, 9)
    core = b["name"].rsplit(" ", 1)[0]
    notes = f"According to Financial Times; {MONTHS[r.rng.randrange(12)]} 12, {rep}: {core} was fined for market abuse."
    aid = r.alert(b["name"], etype="Company", account_ref=b["acc"])
    hid = r.hit(aid, core + " Limited", etype="Company", countries=[b["country"]], category="Enforcement", notes=notes)
    r.attach(aid, hid)
    r.label("temporal_company", aid, hid, "DIFFERENT_ENTITY", ["TEMPORAL_IMPOSSIBILITY"], [b["cid"]], [b["kid"]])


def s_company_incorporation_mismatch(r):
    b = base(r, company=True, dob_year=r.rng.randrange(1995, 2015))
    core = b["name"].rsplit(" ", 1)[0]
    aid = r.alert(b["name"], etype="Company", account_ref=b["acc"])
    hid = r.hit(aid, core, etype="Company", dobs=[str(b["y"] - r.rng.randrange(5, 20))], countries=[b["country"]],
                category="Enforcement")
    r.attach(aid, hid)
    r.label("company_incorporation_mismatch", aid, hid, "DIFFERENT_ENTITY", ["DOB_MISMATCH"], [b["cid"]], [b["kid"]])


def s_company_match(r):
    b = base(r, company=True)
    core = b["name"].rsplit(" ", 1)[0]
    aid = r.alert(b["name"], etype="Company", account_ref=b["acc"])
    hid = r.hit(aid, core + r.rng.choice([", S.A.", " Limited", " AG", ""]), etype="Company",
                countries=[b["country"]], category="Adverse Media")
    r.attach(aid, hid)
    r.label("company_name_country_match", aid, hid, "SAME_ENTITY", ["NAME_LOCATION_MATCH"], [b["cid"]],
            [b["cid"], b["kid"]])


def s_company_age_note_not_a_date(r):
    # For companies, only dobs is an incorporation date. An "age" sentence is not evidence.
    b = base(r, company=True)
    core = b["name"].rsplit(" ", 1)[0]
    aid = r.alert(b["name"], etype="Company", account_ref=b["acc"])
    hid = r.hit(aid, core, etype="Company", countries=[b["country"]], category="Enforcement",
                notes=f"{core}, founded some 80 years ago, was investigated in March 2015.")
    r.attach(aid, hid)
    r.label("company_profile_age_ignored", aid, hid, "SAME_ENTITY", ["NAME_LOCATION_MATCH"], [b["cid"]],
            [b["cid"], b["kid"]])


def s_deceased(r):
    b = base(r)
    aid = r.alert(b["name"], account_ref=b["acc"])
    hid = r.hit(aid, f"{b['last']}, {b['first']}", countries=[b["country"]], deceased=f"{r.rng.randrange(2012, 2025)}-0{r.rng.randrange(1, 9)}")
    r.attach(aid, hid)
    r.label("deceased", aid, hid, "DIFFERENT_ENTITY", ["DECEASED"], [b["cid"]], [b["cid"]])


def s_death_after_screening(r):
    b = base(r)
    aid = r.alert(b["name"], account_ref=b["acc"], screened="2026-11-03")
    hid = r.hit(aid, f"{b['last']}, {b['first']}", countries=[b["country"]], deceased="2026-11-20")
    r.attach(aid, hid)
    r.label("death_after_screening_not_cleared", aid, hid, "REVIEW", ["INSUFFICIENT_DATA"], [b["cid"]], [b["cid"], b["kid"]])


def s_entity_type(r):
    b = base(r)
    aid = r.alert(b["name"], account_ref=b["acc"])
    hid = r.hit(aid, f"{b['first']} {b['last']} Trading Ltd", etype="Company", countries=[b["country"]],
                category="Enforcement")
    r.attach(aid, hid)
    r.label("entity_type_mismatch", aid, hid, "DIFFERENT_ENTITY", ["ENTITY_TYPE_MISMATCH"], [b["cid"]], [b["cid"]])


def s_location_mismatch(r):
    b = base(r)
    other = r.rng.choice([c for c in COUNTRIES if c != b["country"]])
    aid = r.alert(b["name"], account_ref=b["acc"])
    hid = r.hit(aid, f"{b['last']}, {b['first']}", countries=[other], category="Adverse Media")
    r.attach(aid, hid)
    r.label("location_mismatch", aid, hid, "DIFFERENT_ENTITY", ["LOCATION_MISMATCH"], [b["cid"]], [b["cid"], b["kid"]])


def s_location_blocked_by_note(r, wording):
    b = base(r)
    other = r.rng.choice([c for c in COUNTRIES if c != b["country"]])
    texts = [f"The client mentioned they lived and worked in {other} from 2009 to 2013.",
             f"Customer said she previously resided in {other} before relocating.",
             f"Caller confirmed a former home address in {other} (2015-2017)."]
    nid = r.note(b["email"], texts[wording])
    aid = r.alert(b["name"], account_ref=b["acc"])
    hid = r.hit(aid, f"{b['last']}, {b['first']}", countries=[other], category="Adverse Media")
    r.attach(aid, hid)
    r.label(f"location_blocked_by_note_w{wording}", aid, hid, "REVIEW", ["INSUFFICIENT_DATA"], [b["cid"]], [nid])


def s_location_name_dob_agree(r):
    b = base(r)
    other = r.rng.choice([c for c in COUNTRIES if c != b["country"]])
    aid = r.alert(b["name"], account_ref=b["acc"])
    hid = r.hit(aid, f"{b['last']}, {b['first']}", dobs=[b["iso"]], countries=[other])
    r.attach(aid, hid)
    r.label("location_clash_but_name_dob_agree", aid, hid, "REVIEW", ["INSUFFICIENT_DATA"], [b["cid"]], [b["cid"], b["kid"]])


def s_demonym_iso(r):
    country = r.rng.choice(list(DEMONYM))
    first, last, _ = r.person()
    y = r.rng.randrange(1960, 1990)
    iso = f"{y}-0{r.rng.randrange(1, 9)}-1{r.rng.randrange(0, 9)}"
    cid, email = r.customer(f"{first} {last}", iso, country, nationality=DEMONYM[country], residence=ISO.get(country, country))
    acc = r.account([cid])
    kid, _ = r.kyc(acc, cid, f"{first} {last}".upper(), iso, country)
    aid = r.alert(f"{first} {last}", account_ref=acc)
    hid = r.hit(aid, f"{last}, {first}", dobs=[str(y)], nationality=[DEMONYM[country]], countries=[country])
    r.attach(aid, hid)
    r.label("demonym_and_iso_codes_agree", aid, hid, "SAME_ENTITY", ["NAME_DOB_LOCATION_MATCH", "NAME_DOB_MATCH"],
            [cid], [cid, kid])


def s_territory(r):
    first, last, _ = r.person()
    y = r.rng.randrange(1960, 1990)
    iso = f"{y}-05-14"
    cid, _ = r.customer(f"{first} {last}", iso, "Hong Kong")
    acc = r.account([cid])
    kid, _ = r.kyc(acc, cid, f"{first} {last}".upper(), iso, "Hong Kong")
    aid = r.alert(f"{first} {last}", account_ref=acc)
    hid = r.hit(aid, f"{last}, {first}", countries=["China"], category="Adverse Media")
    r.attach(aid, hid)
    r.label("territory_is_own_country", aid, hid, "DIFFERENT_ENTITY", ["LOCATION_MISMATCH"], [cid], [cid, kid])


def s_verified_name_mismatch(r):
    b = base(r)
    other_first, other_last, _ = r.person(b["fem"])
    # The customer record and screening carry a nickname/alias; the passport says someone else.
    r.rows["kyc_checks"][-1]["verified_name"] = f"{other_first} {other_last}".upper()
    aid = r.alert(b["name"], account_ref=b["acc"])
    hid = r.hit(aid, f"{b['last']}, {b['first']}", category="Adverse Media")
    r.attach(aid, hid)
    r.label("verified_name_mismatch", aid, hid, "DIFFERENT_ENTITY", ["NAME_MISMATCH_VERIFIED"], [b["cid"]], [b["kid"]])


def s_nickname_match(r):
    first = r.rng.choice(list(NICK))
    last = r.surname()
    y = r.rng.randrange(1960, 1990)
    iso = f"{y}-03-0{r.rng.randrange(1, 9)}"
    country = r.rng.choice(COUNTRIES)
    cid, _ = r.customer(f"{NICK[first]} {last}", iso, country)
    acc = r.account([cid])
    kid, _ = r.kyc(acc, cid, f"{first} {last}".upper(), iso, country)
    aid = r.alert(f"{NICK[first]} {last}", account_ref=acc)
    hid = r.hit(aid, f"{last}, {first}", dobs=[iso], countries=[country])
    r.attach(aid, hid)
    r.label("nickname_variant_match", aid, hid, "SAME_ENTITY", ["NAME_DOB_LOCATION_MATCH", "NAME_DOB_MATCH"],
            [cid], [cid, kid])


def s_rejected_check_ignored(r):
    b = base(r)
    # A newer REJECTED check with a different DOB must be ignored; the approved one agrees with the hit.
    r.kyc(b["acc"], b["cid"], b["name"].upper(), f"{b['y'] + 17}-01-01", b["country"], result="rejected",
          checked="2025-09-01", app=b["app"])
    aid = r.alert(b["name"], account_ref=b["acc"])
    hid = r.hit(aid, f"{b['last']}, {b['first']}", dobs=[str(b["y"])], countries=[b["country"]], category="Sanctions")
    r.attach(aid, hid)
    r.label("newer_rejected_check_ignored", aid, hid, "SAME_ENTITY", ["NAME_DOB_LOCATION_MATCH", "NAME_DOB_MATCH"],
            [b["cid"]], [b["cid"], b["kid"]])


def s_expired_check_ignored(r):
    first, last, _ = r.person()
    country = r.rng.choice(COUNTRIES)
    y = r.rng.randrange(1960, 1990)
    cid, _ = r.customer(f"{first} {last}", None, country)
    acc = r.account([cid])
    # Only an expired check carries a DOB that would contradict the hit: it is not evidence -> REVIEW, not clear.
    kid, _ = r.kyc(acc, cid, f"{first} {last}".upper(), f"{y}-02-02", country, result="expired")
    aid = r.alert(f"{first} {last}", account_ref=acc)
    hid = r.hit(aid, f"{last}, {first}", dobs=[str(y - 12)], countries=[country])
    r.attach(aid, hid)
    r.label("expired_check_not_evidence", aid, hid, "REVIEW", ["INSUFFICIENT_DATA"], [cid], [cid])


def s_merge_phone_dob(r):
    # Two records of one person (same phone + full DOB). Only the second ties them to the hit's country.
    first, last, _ = r.person()
    c1, c2 = r.rng.sample(COUNTRIES, 2)
    y = r.rng.randrange(1960, 1990)
    iso = f"{y}-07-1{r.rng.randrange(0, 9)}"
    phone = f"+44 7{r.rng.randrange(10**8, 10**9)}"
    a, _ = r.customer(f"{first} {last}", iso, c1, phone=phone)
    b2, _ = r.customer(f"{first} {last}", iso, c2, phone=phone)
    acc = r.account([a])
    kid, _ = r.kyc(acc, a, f"{first} {last}".upper(), iso, c1)
    aid = r.alert(f"{first} {last}", account_ref=acc)
    hid = r.hit(aid, f"{last}, {first}", countries=[c2], category="Adverse Media")
    r.attach(aid, hid)
    r.label("merged_record_blocks_location_clear", aid, hid, "REVIEW", ["INSUFFICIENT_DATA"], [a, b2], [b2])


def s_shared_phone_not_merged(r):
    # Same phone, different DOB (a relative). The relative's country must NOT count.
    first, last, _ = r.person()
    c1, c2 = r.rng.sample(COUNTRIES, 2)
    y = r.rng.randrange(1960, 1990)
    phone = f"+44 7{r.rng.randrange(10**8, 10**9)}"
    a, _ = r.customer(f"{first} {last}", f"{y}-04-04", c1, phone=phone)
    r.customer(f"{r.person()[0]} {last}", f"{y + 25}-09-09", c2, phone=phone)
    acc = r.account([a])
    kid, _ = r.kyc(acc, a, f"{first} {last}".upper(), f"{y}-04-04", c1)
    aid = r.alert(f"{first} {last}", account_ref=acc)
    hid = r.hit(aid, f"{last}, {first}", countries=[c2], category="Adverse Media")
    r.attach(aid, hid)
    r.label("shared_phone_alone_no_merge", aid, hid, "DIFFERENT_ENTITY", ["LOCATION_MISMATCH"], [a], [a, kid])


def s_joint_account(r):
    # Joint holders; the screened name + DOB pick the second one, whose DOB contradicts the hit.
    f1, l1, _ = r.person()
    f2, l2, _ = r.person()
    country = r.rng.choice(COUNTRIES)
    y1, y2 = r.rng.randrange(1950, 1965), r.rng.randrange(1980, 1995)
    a, _ = r.customer(f"{f1} {l1}", f"{y1}-01-15", country)
    b2, _ = r.customer(f"{f2} {l2}", f"{y2}-06-20", country)
    acc = r.account([a, b2])
    app = r.nid("APP")
    r.rows["onboarding"].append({"account_id": acc, "customer_id": b2, "kyc_applicant_id": app, "onboarded_at": "2023-03-14"})
    kid, _ = r.kyc(acc, b2, f"{f2} {l2}".upper(), f"{y2}-06-20", country, app=app)
    aid = r.alert(f"{f2} {l2}", dob=f"{y2}-06-20", account_ref=acc)
    hid = r.hit(aid, f"{l2}, {f2}", dobs=[str(y1)], countries=[country])
    r.attach(aid, hid)
    r.label("joint_account_pick_holder", aid, hid, "DIFFERENT_ENTITY", ["DOB_MISMATCH"], [b2], [kid])


def s_unlinked_ambiguous(r):
    # No link. Two different people fit the screened name; one clears on location, the other matches.
    first, last, _ = r.person()
    c1, c2 = r.rng.sample(COUNTRIES, 2)
    y = r.rng.randrange(1960, 1990)
    a, _ = r.customer(f"{first} {last}", f"{y}-02-10", c1)
    b2, _ = r.customer(f"{first} {last}", f"{y + 9}-11-21", c2)
    aid = r.alert(f"{first} {last}")
    hid = r.hit(aid, f"{last}, {first}", dobs=[str(y + 9)], countries=[c2])
    r.attach(aid, hid)
    r.label("unlinked_two_people_fit", aid, hid, "REVIEW", ["AMBIGUOUS_CUSTOMER_RECORD"], ["AMBIGUOUS"], [a, b2])


def s_unlinked_attribute_search(r):
    first, last, _ = r.person()
    country = r.rng.choice(COUNTRIES)
    y = r.rng.randrange(1960, 1990)
    iso = f"{y}-08-2{r.rng.randrange(0, 8)}"
    cid, _ = r.customer(f"{first} {last}", iso, country)
    # Screened with a typo in the surname; DOB and country pin the record.
    typo = last[:-1] + ("a" if last[-1] != "a" else "e")
    aid = r.alert(f"{first} {typo}", dob=iso, country=country)
    hid = r.hit(aid, f"{last}, {first}", dobs=[str(y - 11)], countries=[country])
    r.attach(aid, hid)
    r.label("unlinked_attribute_search_typo", aid, hid, "DIFFERENT_ENTITY", ["DOB_MISMATCH"], [cid], [cid])


def s_email_link_note_identity(r):
    # Linked by email only; the verified identity lives in a kyc-channel note, which contradicts the hit DOB.
    first, last, _ = r.person()
    country = r.rng.choice(COUNTRIES)
    y = r.rng.randrange(1960, 1990)
    cid, email = r.customer(f"{first} {last}", None, country)
    nid = r.note(email, f"Identity confirmed by Veriff for {first.upper()} {last.upper()}, date of birth "
                        f"{r.rng.randrange(1, 28)} {MONTHS[r.rng.randrange(12)]} {y}, passport issued in {country}.",
                 channel="kyc", created="2024-05-05")
    aid = r.alert(f"{first} {last}", email=email)
    hid = r.hit(aid, f"{last}, {first}", dobs=[str(y + 13)], countries=[country])
    r.attach(aid, hid)
    r.label("email_link_note_identity", aid, hid, "DIFFERENT_ENTITY", ["DOB_MISMATCH"], [cid], [nid])


def s_search_result_dob(r, decoy):
    b = base(r)
    hit_name = f"{b['last']}, {b['first']}"
    cat = r.rng.choice(list(LISTING))
    rep = r.rng.randrange(2012, 2024)
    true_age = rep - (b["y"] - r.rng.randrange(8, 15))
    sid = r.sr(hit_name, f"{b['first']} {b['last']}, {true_age}, {LISTING[cat]} from {b['country']}, "
                         f"was mentioned in a regulator's notice in {MONTHS[r.rng.randrange(12)]} {rep}.")
    if decoy:  # a namesake: agreeing age, but wrong listing type and another country -> must be ignored
        other = r.rng.choice([c for c in COUNTRIES if c != b["country"]])
        r.sr(hit_name, f"{b['first']} {b['last']}, {rep - b['y']}, a youth football coach in {other}, "
                       f"was profiled in {MONTHS[2]} {rep}.")
    aid = r.alert(b["name"], account_ref=b["acc"])
    hid = r.hit(aid, hit_name, countries=[b["country"]], category=cat)
    r.attach(aid, hid)
    r.label("search_result_dob" + ("_with_decoy" if decoy else ""), aid, hid, "DIFFERENT_ENTITY", ["DOB_MISMATCH"],
            [b["cid"]], [b["kid"], sid])


def s_no_customer_dob(r):
    first, last, _ = r.person()
    country = r.rng.choice(COUNTRIES)
    cid, _ = r.customer(f"{first} {last}", None, country)
    acc = r.account([cid])
    aid = r.alert(f"{first} {last}", account_ref=acc)
    hid = r.hit(aid, f"{last}, {first}", dobs=["1971"], countries=[country])
    r.attach(aid, hid)
    r.label("unknown_stays_unknown", aid, hid, "REVIEW", ["INSUFFICIENT_DATA"], [cid], [cid])


def s_placeholder_name(r):
    country = r.rng.choice(COUNTRIES)
    last = r.surname()
    cid, _ = r.customer(f"{last} NA", "1980-01-01", country)
    acc = r.account([cid])
    kid, _ = r.kyc(acc, cid, f"{last.upper()} N/A", "1980-01-01", country)
    aid = r.alert(f"{last} NA", account_ref=acc)
    hid = r.hit(aid, f"{last}, Viktor", dobs=["1980"], countries=[country])
    r.attach(aid, hid)
    r.label("placeholder_single_part_name", aid, hid, "REVIEW", ["INSUFFICIENT_DATA"], [cid], [cid, kid])


def s_multi_hit_alert(r):
    b = base(r)
    aid = r.alert(b["name"], account_ref=b["acc"])
    other = r.rng.choice([c for c in COUNTRIES if c != b["country"]])
    h1 = r.hit(aid, f"{b['last']}, {b['first']}", countries=[other], category="Adverse Media")
    h2 = r.hit(aid, f"{b['first']} {b['last']}", dobs=[b["iso"]], countries=[b["country"]], category="Sanctions")
    r.attach(aid, h1); r.attach(aid, h2)
    r.label("multi_hit_clear", aid, h1, "DIFFERENT_ENTITY", ["LOCATION_MISMATCH"], [b["cid"]], [b["cid"], b["kid"]])
    r.label("multi_hit_match", aid, h2, "SAME_ENTITY", ["NAME_DOB_LOCATION_MATCH", "NAME_DOB_MATCH"], [b["cid"]],
            [b["cid"], b["kid"]])


def s_dob_formats(r, fmt):
    b = base(r, fmt=fmt)
    hit_dob = {"iso": f"{b['d']:02d} {MONTHS[b['m']-1]} {b['y']}", "dmy": f"{b['y']}-{b['m']:02d}-{b['d']:02d}",
               "long": f"{b['d']}/{b['m']}/{b['y']}" if b["d"] > 12 else str(b["y"]), "dm": str(b["y"])}[fmt]
    aid = r.alert(b["name"], account_ref=b["acc"])
    hid = r.hit(aid, f"{b['last']}, {b['first']}", dobs=[hit_dob], countries=[b["country"]], category="PEP")
    r.attach(aid, hid)
    r.label(f"dob_format_{fmt}_agrees", aid, hid, "SAME_ENTITY", ["NAME_DOB_LOCATION_MATCH", "NAME_DOB_MATCH"],
            [b["cid"]], [b["cid"], b["kid"]])


# --------------------------------------------------------------------------
# Edge cases (batch 2). Each targets one sentence of POLICY.md.
# --------------------------------------------------------------------------

def _person_customer(r, country=None, dob=None, kyc_dob=None, name=None, result="approved", checked="2024-06-10"):
    first, last, fem = r.person()
    name = name or f"{first} {last}"
    country = country or r.rng.choice(COUNTRIES)
    cid, email = r.customer(name, dob, country)
    acc = r.account([cid])
    kid, app = r.kyc(acc, cid, name.upper(), kyc_dob if kyc_dob is not None else dob, country, result=result, checked=checked)
    return dict(first=first, last=last, name=name, country=country, cid=cid, email=email, acc=acc, kid=kid, app=app)


def e_ddmm_ambiguous_blocks_clear(r):
    # The bank writes slash dates day-first (dev: second number is never > 12). 04/07/1980 is 4 July.
    # The hit gives 7 April: a same-year month clash, and the countries differ too -> cleared.
    y = r.rng.randrange(1960, 1990); d, m = r.rng.randrange(1, 13), r.rng.randrange(1, 13)
    while d == m: m = r.rng.randrange(1, 13)
    c1, c2 = r.rng.sample(COUNTRIES, 2)
    b = _person_customer(r, country=c1, dob=f"{d:02d}/{m:02d}/{y}", kyc_dob=f"{d:02d}/{m:02d}/{y}")
    aid = r.alert(b["name"], account_ref=b["acc"])
    hid = r.hit(aid, f"{b['last']}, {b['first']}", dobs=[f"{y}-{d:02d}-{m:02d}"], countries=[c2])
    r.attach(aid, hid)
    r.label("edge_day_first_month_swap_clears", aid, hid, "DIFFERENT_ENTITY", ["DOB_MISMATCH", "LOCATION_MISMATCH"], [b["cid"]], [b["cid"], b["kid"]])


def e_ddmm_both_readings_contradict(r):
    y = r.rng.randrange(1960, 1990); d, m = r.rng.randrange(1, 13), r.rng.randrange(1, 13)
    other = next(x for x in range(1, 13) if x not in (d, m))
    b = _person_customer(r, dob=f"{d:02d}/{m:02d}/{y}", kyc_dob=f"{d:02d}/{m:02d}/{y}")
    aid = r.alert(b["name"], account_ref=b["acc"])
    hid = r.hit(aid, f"{b['last']}, {b['first']}", dobs=[f"{y}-{other:02d}-{other:02d}"], countries=[b["country"]])
    r.attach(aid, hid)
    r.label("edge_day_first_small_numbers_month_clash", aid, hid, "DIFFERENT_ENTITY", ["DOB_MISMATCH"], [b["cid"]], [b["kid"]])


def e_year_only_customer_agrees(r):
    y = r.rng.randrange(1960, 1990)
    b = _person_customer(r, dob=str(y), kyc_dob=str(y))
    aid = r.alert(b["name"], account_ref=b["acc"])
    hid = r.hit(aid, f"{b['last']}, {b['first']}", dobs=[f"{y}-0{r.rng.randrange(1, 9)}-1{r.rng.randrange(0, 9)}"], countries=[b["country"]])
    r.attach(aid, hid)
    r.label("edge_year_only_agrees_with_full_date", aid, hid, "SAME_ENTITY", ["NAME_DOB_LOCATION_MATCH", "NAME_DOB_MATCH"],
            [b["cid"]], [b["cid"], b["kid"]])


def e_hit_month_only_contradicts(r):
    y = r.rng.randrange(1960, 1990)
    b = _person_customer(r, dob=f"{y}-09-14")
    aid = r.alert(b["name"], account_ref=b["acc"])
    hid = r.hit(aid, f"{b['last']}, {b['first']}", dobs=[f"{y}-03"], countries=[b["country"]])
    r.attach(aid, hid)
    r.label("edge_hit_month_only_contradicts", aid, hid, "DIFFERENT_ENTITY", ["DOB_MISMATCH"], [b["cid"]], [b["kid"]])


def e_latest_approved_wins(r):
    # Two APPROVED checks; the newer one corrected the DOB and agrees with the hit. Older one would clear.
    y = r.rng.randrange(1960, 1985)
    b = _person_customer(r, dob=f"{y + 10}-02-02", kyc_dob=f"{y + 10}-02-02", checked="2021-03-03")
    kid2, _ = r.kyc(b["acc"], b["cid"], b["name"].upper(), f"{y}-05-05", b["country"], checked="2025-01-15", app=b["app"])
    aid = r.alert(b["name"], account_ref=b["acc"])
    hid = r.hit(aid, f"{b['last']}, {b['first']}", dobs=[str(y)], countries=[b["country"]], category="Sanctions")
    r.attach(aid, hid)
    r.label("edge_latest_approved_check_wins", aid, hid, "SAME_ENTITY", ["NAME_DOB_LOCATION_MATCH", "NAME_DOB_MATCH"],
            [b["cid"]], [b["cid"], kid2])


def e_failed_note_not_evidence(r):
    first, last, _ = r.person(); country = r.rng.choice(COUNTRIES); y = r.rng.randrange(1960, 1990)
    cid, email = r.customer(f"{first} {last}", None, country)
    r.note(email, f"Onfido could not verify {first.upper()} {last.upper()}, born {y}-03-03: the document check was rejected.",
           channel="kyc", created="2024-02-02")
    aid = r.alert(f"{first} {last}", email=email)
    hid = r.hit(aid, f"{last}, {first}", dobs=[str(y - 15)], countries=[country])
    r.attach(aid, hid)
    r.label("edge_rejected_note_not_evidence", aid, hid, "REVIEW", ["INSUFFICIENT_DATA"], [cid], [cid])


def e_initials_ignored(r):
    y = r.rng.randrange(1960, 1990)
    first, last, _ = r.person(); country = r.rng.choice(COUNTRIES)
    name = f"{r.rng.choice('JKMRT')}. {first} {last}"
    cid, _ = r.customer(name, f"{y}-06-06", country)
    acc = r.account([cid]); kid, _ = r.kyc(acc, cid, name.upper(), f"{y}-06-06", country)
    aid = r.alert(name, account_ref=acc)
    hid = r.hit(aid, f"{last}, {first}", dobs=[str(y)], countries=[country])
    r.attach(aid, hid)
    r.label("edge_initials_are_not_parts", aid, hid, "SAME_ENTITY", ["NAME_DOB_LOCATION_MATCH", "NAME_DOB_MATCH"], [cid], [cid, kid])


def e_joined_name(r):
    y = r.rng.randrange(1960, 1990); country = r.rng.choice(COUNTRIES); last = r.surname()
    a, b2 = r.rng.choice([("Maria", "Jose"), ("Abdul", "Karim"), ("Jean", "Luc"), ("Anna", "Lena")])
    cid, _ = r.customer(f"{a} {b2} {last}", f"{y}-10-10", country)
    acc = r.account([cid]); kid, _ = r.kyc(acc, cid, f"{a} {b2} {last}".upper(), f"{y}-10-10", country)
    aid = r.alert(f"{a} {b2} {last}", account_ref=acc)
    hid = r.hit(aid, f"{a}{b2.lower()} {last}", dobs=[str(y)], countries=[country])
    r.attach(aid, hid)
    r.label("edge_joined_name_parts", aid, hid, "SAME_ENTITY", ["NAME_DOB_LOCATION_MATCH", "NAME_DOB_MATCH"], [cid], [cid, kid])


def e_short_part_must_be_identical(r):
    # Ivo vs Ian: parts under 4 letters must be identical. Only the surname matches -> names do not agree.
    y = r.rng.randrange(1960, 1990); country = r.rng.choice(COUNTRIES); last = r.surname()
    f1, f2 = r.rng.choice([("Ivo", "Ian"), ("Ana", "Ann"), ("Eva", "Eve"), ("Leo", "Lev")])
    cid, _ = r.customer(f"{f1} {last}", f"{y}-01-01", country)
    acc = r.account([cid]); kid, _ = r.kyc(acc, cid, f"{f1} {last}".upper(), f"{y}-01-01", country)
    aid = r.alert(f"{f1} {last}", account_ref=acc)
    hid = r.hit(aid, f"{last}, {f2}", category="Adverse Media")
    r.attach(aid, hid)
    r.label("edge_short_parts_must_be_identical", aid, hid, "DIFFERENT_ENTITY", ["NAME_MISMATCH_VERIFIED"], [cid], [kid])


def e_transposition_is_two_edits(r):
    # 5-letter part allows 1 edit; a swap of two letters is 2 edits -> no match on that part.
    y = r.rng.randrange(1960, 1990); country = r.rng.choice(COUNTRIES); last = r.surname()
    f1, f2 = r.rng.choice([("Marta", "Mrata"), ("Pavel", "Pvael"), ("Nadia", "Ndaia"), ("Oskar", "Oksar")])
    cid, _ = r.customer(f"{f1} {last}", f"{y}-01-01", country)
    acc = r.account([cid]); kid, _ = r.kyc(acc, cid, f"{f1} {last}".upper(), f"{y}-01-01", country)
    aid = r.alert(f"{f1} {last}", account_ref=acc)
    hid = r.hit(aid, f"{last}, {f2}", category="Adverse Media")
    r.attach(aid, hid)
    r.label("edge_letter_swap_is_two_edits", aid, hid, "DIFFERENT_ENTITY", ["NAME_MISMATCH_VERIFIED"], [cid], [kid])


def e_single_part_alias_blocks_name_clear(r):
    # The verified first name differs, but the hit's single-part alias (the surname) agrees -> no name clear.
    first, last, _ = r.person(); other, _, _ = r.person(); country = r.rng.choice(COUNTRIES)
    cid, _ = r.customer(f"{first} {last}", None, country)
    acc = r.account([cid]); kid, _ = r.kyc(acc, cid, f"{first} {last}".upper(), None, country)
    aid = r.alert(f"{first} {last}", account_ref=acc)
    hid = r.hit(aid, f"{other} {last}", aliases=[f"{last} (Nickname)"], countries=[country])
    r.attach(aid, hid)
    r.label("edge_single_part_alias_agrees", aid, hid, "REVIEW", ["INSUFFICIENT_DATA"], [cid], [cid, kid])


def e_brackets_ignored(r):
    y = r.rng.randrange(1960, 1990)
    b = _person_customer(r, dob=f"{y}-11-11")
    aid = r.alert(b["name"], account_ref=b["acc"])
    hid = r.hit(aid, f"{b['last']}, {b['first']} (Dr.) [formerly {r.surname()}]", dobs=[f"{y}-11-11"], countries=[b["country"]])
    r.attach(aid, hid)
    r.label("edge_brackets_ignored", aid, hid, "SAME_ENTITY", ["NAME_DOB_LOCATION_MATCH", "NAME_DOB_MATCH"], [b["cid"]], [b["cid"], b["kid"]])


def e_not_countries(r):
    b = _person_customer(r, dob="1970-01-01")
    aid = r.alert(b["name"], account_ref=b["acc"])
    hid = r.hit(aid, f"{b['last']}, {b['first']}", countries=[r.rng.choice(["International", "Europe"])], category="Sanctions")
    r.attach(aid, hid)
    r.label("edge_international_europe_not_countries", aid, hid, "REVIEW", ["INSUFFICIENT_DATA"], [b["cid"]], [b["cid"], b["kid"]])


def e_country_from_address_and_pob(r):
    y = r.rng.randrange(1960, 1990)
    b = _person_customer(r, dob=f"{y}-04-04")
    aid = r.alert(b["name"], account_ref=b["acc"])
    hid = r.hit(aid, f"{b['last']}, {b['first']}", dobs=[str(y)])
    h = r.rows["hits"][-1]
    other = r.rng.choice([c for c in COUNTRIES if c != b["country"]])
    h["addresses"] = [f"12 Station Road, {CITY.get(b['country'], 'Capital')}, {b['country']}"]
    h["place_of_birth"] = f"{CITY.get(other, 'Capital')}, {other}"
    r.attach(aid, hid)
    r.label("edge_hit_country_from_address", aid, hid, "SAME_ENTITY", ["NAME_DOB_LOCATION_MATCH", "NAME_DOB_MATCH"],
            [b["cid"]], [b["cid"], b["kid"]])


def e_off_country_search_ignored(r):
    # Right listing phrase, but a country not tied to the hit: not about the hit -> no DOB -> REVIEW.
    b = _person_customer(r, dob=f"{r.rng.randrange(1960, 1990)}-02-02")
    hit_name = f"{b['last']}, {b['first']}"
    other = r.rng.choice([c for c in COUNTRIES if c != b["country"]])
    r.sr(hit_name, f"{b['first']} {b['last']}, 23, a politically exposed person from {other}, was mentioned in a notice in May 2015.")
    aid = r.alert(b["name"], account_ref=b["acc"])
    hid = r.hit(aid, hit_name, countries=[b["country"]], category="PEP")
    r.attach(aid, hid)
    r.label("edge_search_result_wrong_country_ignored", aid, hid, "REVIEW", ["INSUFFICIENT_DATA"], [b["cid"]], [b["cid"], b["kid"]])


def e_earliest_report_counts(r):
    y = r.rng.randrange(2002, 2006)
    b = _person_customer(r, dob=f"{y}-08-08")
    notes = (f"According to Reuters; March 2, {y + 25}: {b['first']} {b['last']} was charged.\n"
             f"According to AP; June 9, {y + 12}: {b['first']} {b['last']} was first named in the case.")
    aid = r.alert(b["name"], account_ref=b["acc"])
    hid = r.hit(aid, f"{b['first']} {b['last']}", countries=[b["country"]], category="Adverse Media", notes=notes)
    r.attach(aid, hid)
    r.label("edge_earliest_dated_report_counts", aid, hid, "DIFFERENT_ENTITY", ["TEMPORAL_IMPOSSIBILITY"], [b["cid"]], [b["kid"]])


def e_exactly_sixteen(r):
    y = r.rng.randrange(2000, 2006)
    b = _person_customer(r, dob=f"{y}-03-01")
    notes = f"According to Reuters; June 5, {y + 16}: {b['first']} {b['last']} was named in a fraud report."
    aid = r.alert(b["name"], account_ref=b["acc"])
    hid = r.hit(aid, f"{b['first']} {b['last']}", countries=[b["country"]], category="Adverse Media", notes=notes)
    r.attach(aid, hid)
    r.label("edge_exactly_16_not_temporal", aid, hid, "REVIEW", ["INSUFFICIENT_DATA"], [b["cid"]], [b["cid"], b["kid"]])


def e_deceased_year_only(r):
    b = _person_customer(r, dob="1950-05-05")
    aid = r.alert(b["name"], account_ref=b["acc"])
    hid = r.hit(aid, f"{b['last']}, {b['first']}", countries=[b["country"]], deceased=str(r.rng.randrange(2005, 2020)))
    r.attach(aid, hid)
    r.label("edge_deceased_year_only", aid, hid, "DIFFERENT_ENTITY", ["DECEASED"], [b["cid"]], [b["cid"]])


def e_merge_document_number(r):
    # Two records on separate accounts; approved checks share a document number -> one person.
    first, last, _ = r.person(); c1, c2 = r.rng.sample(COUNTRIES, 2); doc = f"X{r.rng.randrange(10**7, 10**8)}"
    a, _ = r.customer(f"{first} {last}", None, c1); acc_a = r.account([a])
    r.kyc(acc_a, a, f"{first} {last}".upper(), None, c1, docno=doc)
    b2, _ = r.customer(f"{first} {last}", None, c2); acc_b = r.account([b2])
    kb, _ = r.kyc(acc_b, b2, f"{first} {last}".upper(), None, c1, docno=doc)
    aid = r.alert(f"{first} {last}", account_ref=acc_a)
    hid = r.hit(aid, f"{last}, {first}", countries=[c2], category="Adverse Media")
    r.attach(aid, hid)
    r.label("edge_merge_on_document_number", aid, hid, "REVIEW", ["INSUFFICIENT_DATA"], [a, b2], [b2])


def e_doc_number_rejected_no_merge(r):
    first, last, _ = r.person(); c1, c2 = r.rng.sample(COUNTRIES, 2); doc = f"X{r.rng.randrange(10**7, 10**8)}"
    a, _ = r.customer(f"{first} {last}", None, c1); acc_a = r.account([a])
    ka, _ = r.kyc(acc_a, a, f"{first} {last}".upper(), None, c1, docno=doc)
    b2, _ = r.customer(f"{r.person()[0]} {last}", None, c2); acc_b = r.account([b2])
    r.kyc(acc_b, b2, f"{first} {last}".upper(), None, c2, docno=doc, result="rejected")
    aid = r.alert(f"{first} {last}", account_ref=acc_a)
    hid = r.hit(aid, f"{last}, {first}", countries=[c2], category="Adverse Media")
    r.attach(aid, hid)
    r.label("edge_rejected_check_does_not_merge", aid, hid, "DIFFERENT_ENTITY", ["LOCATION_MISMATCH"], [a], [a, ka])


def e_login_link(r):
    first, last, _ = r.person(); country = r.rng.choice(COUNTRIES); y = r.rng.randrange(1960, 1990)
    cid, _ = r.customer(f"{first} {last}", f"{y}-12-12", country)
    login = f"{last.lower()[:6]}{r.rng.randrange(1000, 9999)}"
    acc = r.account([cid], login=login); kid, _ = r.kyc(acc, cid, f"{first} {last}".upper(), f"{y}-12-12", country)
    aid = r.alert(login, login=login)
    hid = r.hit(aid, f"{last}, {first}", dobs=[str(y - 9)], countries=[country])
    r.attach(aid, hid)
    r.label("edge_login_link_screened_as_handle", aid, hid, "DIFFERENT_ENTITY", ["DOB_MISMATCH"], [cid], [kid])


def e_company_verified_name_mismatch(r):
    b = base(r, company=True)
    core = b["name"].rsplit(" ", 1)[0]
    r.rows["kyc_checks"][-1]["verified_name"] = f"{r.surname()} Logistics Ltd"
    aid = r.alert(b["name"], etype="Company", account_ref=b["acc"])
    hid = r.hit(aid, core, etype="Company", countries=[b["country"]], category="Enforcement")
    r.attach(aid, hid)
    r.label("edge_company_registry_name_differs", aid, hid, "DIFFERENT_ENTITY", ["NAME_MISMATCH_VERIFIED"], [b["cid"]], [b["kid"]])


def e_multi_hit_deceased_and_review(r):
    b = _person_customer(r, dob="1972-07-07")
    aid = r.alert(b["name"], account_ref=b["acc"])
    h1 = r.hit(aid, f"{b['last']}, {b['first']}", countries=[b["country"]], deceased="2011-02-02")
    h2 = r.hit(aid, f"{b['first']} {b['last']}", countries=[b["country"]], category="PEP")
    r.attach(aid, h1); r.attach(aid, h2)
    r.label("edge_multi_hit_deceased", aid, h1, "DIFFERENT_ENTITY", ["DECEASED"], [b["cid"]], [b["cid"]])
    r.label("edge_multi_hit_still_open", aid, h2, "REVIEW", ["INSUFFICIENT_DATA"], [b["cid"]], [b["cid"], b["kid"]])


EDGES = [e_ddmm_ambiguous_blocks_clear, e_ddmm_both_readings_contradict, e_year_only_customer_agrees,
         e_hit_month_only_contradicts, e_latest_approved_wins, e_failed_note_not_evidence, e_initials_ignored,
         e_joined_name, e_short_part_must_be_identical, e_transposition_is_two_edits,
         e_single_part_alias_blocks_name_clear, e_brackets_ignored, e_not_countries, e_country_from_address_and_pob,
         e_off_country_search_ignored, e_earliest_report_counts, e_exactly_sixteen, e_deceased_year_only,
         e_merge_document_number, e_doc_number_rejected_no_merge, e_login_link, e_company_verified_name_mismatch,
         e_multi_hit_deceased_and_review]


def build(r, reps):
    simple = [s_dob_field_mismatch, s_dob_same_year_other_month, s_dob_one_year_off, s_one_agreeing_date_blocks,
              s_temporal_person, s_temporal_spanish_line_ignored, s_temporal_company, s_company_incorporation_mismatch,
              s_company_match, s_company_age_note_not_a_date, s_deceased, s_death_after_screening, s_entity_type,
              s_location_mismatch, s_location_name_dob_agree, s_demonym_iso, s_territory, s_verified_name_mismatch,
              s_nickname_match, s_rejected_check_ignored, s_expired_check_ignored, s_merge_phone_dob,
              s_shared_phone_not_merged, s_joint_account, s_unlinked_ambiguous, s_unlinked_attribute_search,
              s_email_link_note_identity, s_no_customer_dob, s_placeholder_name, s_multi_hit_alert]
    for _ in range(reps):
        for fn in simple:
            fn(r)
        for k in range(len(AGE_TEMPLATES)):
            s_age_note_mismatch(r, k)
            s_age_note_match(r, k)
        for w in range(3):
            s_location_blocked_by_note(r, w)
        s_search_result_dob(r, False)
        s_search_result_dob(r, True)
        for fmt in ("iso", "dmy", "long", "dm"):
            s_dob_formats(r, fmt)
        for fn in EDGES:
            fn(r)


def main():
    args = sys.argv[1:]
    if len(args) < 2:
        sys.exit(__doc__)
    dev, out = args[0], args[1]
    seed = int(args[args.index("--seed") + 1]) if "--seed" in args else 2026
    reps = int(args[args.index("--reps") + 1]) if "--reps" in args else 3
    r = Room(dev, random.Random(seed))
    build(r, reps)
    os.makedirs(out, exist_ok=True)
    for f in ["POLICY.md", "name_variants.json"]:
        if os.path.exists(os.path.join(dev, f)):
            shutil.copy(os.path.join(dev, f), os.path.join(out, f))
    for f in FILES:
        with open(os.path.join(dev, f + ".jsonl"), encoding="utf-8") as src, \
             open(os.path.join(out, f + ".jsonl"), "w", encoding="utf-8") as dst:
            for line in src:
                if line.strip():
                    dst.write(line if line.endswith("\n") else line + "\n")
            for row in r.rows[f]:
                dst.write(json.dumps(row, ensure_ascii=False) + "\n")
    with open(os.path.join(out, "practice_labels.jsonl"), "w", encoding="utf-8") as h:
        for lab in r.labels:
            h.write(json.dumps({k: v for k, v in lab.items() if k != "scenario"}) + "\n")
    with open(os.path.join(out, "holdout_cases.jsonl"), "w", encoding="utf-8") as h:
        for lab in r.labels:
            h.write(json.dumps(lab) + "\n")
    print(f"holdout: {len(r.labels)} labelled hits in {len(set(l['scenario'] for l in r.labels))} scenarios -> {out}")


if __name__ == "__main__":
    main()
