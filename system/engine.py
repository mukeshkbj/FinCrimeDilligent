#!/usr/bin/env python3
"""Deterministic sanctions identity resolver.

Decisions follow dev/POLICY.md literally. Decisions are deterministic rules
only; no model is used. The same inputs always produce the same file.
See PRINCIPLES.md.
"""

from __future__ import annotations

import json
import re
import sys
import time
import unicodedata

import normalize
from collections import defaultdict
from functools import lru_cache
from pathlib import Path

# ---------------------------------------------------------------------------
# Countries. Codes and demonyms count. Territories stay their own country.
# "International" and "Europe" are not countries.
# ---------------------------------------------------------------------------

_COUNTRY_LINES = """
Afghanistan|afghan
Albania|albanian
Algeria|algerian|dz
Andorra
Angola|angolan
Argentina|argentine|argentinian|ar
Armenia|armenian|am
Australia|australian|au
Austria|austrian|at
Azerbaijan|azerbaijani
Bahamas|bahamian
Bahrain|bahraini
Bangladesh|bangladeshi|bd
Barbados|barbadian
Belarus|belarusian
Belgium|belgian|be
Belize|belizean
Benin|beninese
Bhutan|bhutanese
Bolivia|bolivian
Bosnia and Herzegovina|bosnian
Botswana|botswanan
Brazil|brazilian|br
Brunei|bruneian
Bulgaria|bulgarian
Burkina Faso|burkinabe
Cambodia|cambodian
Cameroon|cameroonian
Canada|canadian|ca
Chile|chilean
China|chinese|cn|people's republic of china
Colombia|colombian|co
Costa Rica|costa rican
Croatia|croatian|hr
Cuba|cuban
Cyprus|cypriot
Czech Republic|czech|czechia|cz
Côte d'Ivoire|cote d'ivoire|ivory coast|ivorian|ci
Denmark|danish|dk
Dominican Republic|dominican|do
Ecuador|ecuadorian|ecuadoran|ec
Egypt|egyptian|eg
El Salvador|salvadoran
Estonia|estonian
Ethiopia|ethiopian
Finland|finnish|fi
France|french|fr
Georgia|georgian
Germany|german|de
Ghana|ghanaian|gh
Greece|greek|gr
Guatemala|guatemalan
Guinea|guinean
Guinea-Bissau
Haiti|haitian|ht
Honduras|honduran
Hong Kong|hong kong sar
Hungary|hungarian|hu
Iceland|icelandic
India|indian|in
Indonesia|indonesian|id
Iran|iranian
Iraq|iraqi
Ireland|irish|ie
Israel|israeli|il
Italy|italian|it
Jamaica|jamaican|jm
Japan|japanese|jp
Jordan|jordanian
Kazakhstan|kazakh|kazakhstani
Kenya|kenyan|ke
Kosovo|kosovar
Kuwait|kuwaiti
Latvia|latvian
Lebanon|lebanese|lb
Liberia|liberian
Libya|libyan
Lithuania|lithuanian
Luxembourg|luxembourgish
Madagascar|malagasy
Malaysia|malaysian|my
Mali|malian
Malta|maltese
Mexico|mexican|mx
Moldova|moldovan|md
Monaco|monegasque
Mongolia|mongolian
Montenegro|montenegrin|me
Morocco|moroccan|ma
Mozambique|mozambican
Myanmar|burmese|burma
Nepal|nepalese|nepali
Netherlands|dutch|the netherlands|nl|holland
New Zealand|new zealander|nz
Nicaragua|nicaraguan
Nigeria|nigerian|ng
North Korea|dprk|kp
North Macedonia|macedonian
Northern Mariana Islands|northern marianas
Norway|norwegian|no
Oman|omani
Pakistan|pakistani|pk
Palestine|palestinian
Panama|panamanian|pa
Papua New Guinea
Paraguay|paraguayan
Peru|peruvian|pe
Philippines|filipino|philippine|ph
Poland|polish|pl
Portugal|portuguese|pt
Qatar|qatari
Romania|romanian|ro
Russia|russian|russian federation|ru
Rwanda|rwandan
Saudi Arabia|saudi|ksa
Senegal|senegalese
Serbia|serbian|rs
Singapore|singaporean|sg
Slovakia|slovak
Slovenia|slovenian|slovene|si
Somalia|somali
South Africa|south african|za
South Korea|republic of korea|kr
South Sudan
Spain|spanish|es
Sri Lanka|sri lankan
Sudan|sudanese
Sweden|swedish|se
Switzerland|swiss|ch
Syria|syrian|sy
Taiwan|taiwanese
Tanzania|tanzanian
Thailand|thai|th
Trinidad and Tobago
Tunisia|tunisian
Turkey|turkish|turkiye|tr
Uganda|ugandan
Ukraine|ukrainian|ua
United Arab Emirates|emirati|uae|ae
United Kingdom|uk|u.k.|british|great britain|gb
United States|usa|u.s.|u.s.a.|american|us
Uruguay|uruguayan
Uzbekistan|uzbek
Venezuela|venezuelan
Vietnam|viet nam|vietnamese|vn
Yemen|yemeni
Zambia|zambian
Zimbabwe|zimbabwean
"""

NOT_COUNTRIES = {"international", "europe", "eu", "unknown", "n/a", "none", "global", "worldwide"}


def fold(value):
    if not value:
        return ""
    text = unicodedata.normalize("NFD", str(value))
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    text = text.lower().replace("’", "'")
    text = re.sub(r"\s+", " ", text).strip()
    return text


NAME_MAP = {}
SCAN = []  # (folded alias, canon) longest first
for _line in _COUNTRY_LINES.splitlines():
    _parts = [p.strip() for p in _line.split("|") if p.strip()]
    if not _parts:
        continue
    _canon = _parts[0]
    for _alias in _parts:
        NAME_MAP[fold(_alias)] = _canon
    for _alias in _parts:
        _fa = fold(_alias)
        if len(_fa) >= 4 or _fa in {"usa", "uae", "uk"}:
            SCAN.append((_fa, _canon))
SCAN.sort(key=lambda item: len(item[0]), reverse=True)


def lookup_whole(value):
    key = fold(value).replace(".", "")
    # Keep dotted abbreviations (u.s.) as well as stripped (us).
    dotted = fold(value)
    if dotted in NOT_COUNTRIES or key in NOT_COUNTRIES:
        return None
    if dotted in NAME_MAP:
        return NAME_MAP[dotted]
    if key in NAME_MAP:
        return NAME_MAP[key]
    return None


def find_countries(value, include_short=True):
    """Return (index, canon) matches, longest-first and non-overlapping."""
    text = fold(re.sub(r"\[[^\]]*\]", " ", value or ""))
    occupied = [False] * len(text)
    found = []
    for alias, canon in SCAN:
        if not include_short and len(alias) < 4:
            continue
        start = 0
        while True:
            index = text.find(alias, start)
            if index < 0:
                break
            end = index + len(alias)
            left_ok = index == 0 or not text[index - 1].isalnum()
            right_ok = end == len(text) or not text[end].isalnum()
            if left_ok and right_ok and not any(occupied[index:end]):
                for pos in range(index, end):
                    occupied[pos] = True
                found.append((index, canon))
            start = index + 1
    return found


def canon_field(value):
    if value is None:
        return None
    raw = re.sub(r"\[[^\]]*\]", " ", str(value))
    raw = re.sub(r"\s+", " ", raw).strip(" ,;")
    if not raw:
        return None
    whole = lookup_whole(raw)
    if whole:
        return whole
    parts = [part.strip() for part in raw.split(",") if part.strip()]
    if parts:
        whole = lookup_whole(parts[-1])
        if whole:
            return whole
    found = find_countries(raw)
    if not found:
        return None
    return max(found, key=lambda item: item[0])[1]


def country_set_from_values(values):
    found = set()
    for value in values:
        if not value:
            continue
        canon = canon_field(value)
        if canon:
            found.add(canon)
    return found


# ---------------------------------------------------------------------------
# Dates. Numeric dates are day/month/year, matching the bank's own files.
# ---------------------------------------------------------------------------

MONTHS = {
    name.lower(): number
    for number, name in enumerate(
        [
            "January",
            "February",
            "March",
            "April",
            "May",
            "June",
            "July",
            "August",
            "September",
            "October",
            "November",
            "December",
        ],
        1,
    )
}
MON = r"(?:January|February|March|April|May|June|July|August|September|October|November|December)"
DATE_RE = re.compile(
    rf"(\d{{4}}-\d{{2}}-\d{{2}}|\d{{1,2}}/\d{{1,2}}/\d{{4}}|{MON}\s+\d{{1,2}},\s+\d{{4}}|\d{{1,2}}\s+{MON}\s+\d{{4}}|\d{{4}}-\d{{2}}|{MON}\s+\d{{4}}|\d{{4}})",
    re.I,
)


class Date:
    __slots__ = ("y", "m", "d")

    def __init__(self, y, m=None, d=None):
        self.y = y
        self.m = m
        self.d = d

    def full(self):
        return self.y is not None and self.m is not None and self.d is not None

    def key(self):
        return (self.y, self.m or 0, self.d or 0)

    def iso(self):
        if self.y is None:
            return ""
        if self.m and self.d:
            return f"{self.y:04d}-{self.m:02d}-{self.d:02d}"
        if self.m:
            return f"{self.y:04d}-{self.m:02d}"
        return f"{self.y:04d}"

    def __repr__(self):
        return self.iso()


def _valid(y, m, d):
    if y is None or y < 1800 or y > 2100:
        return False
    if m is not None and not 1 <= m <= 12:
        return False
    if d is not None and not 1 <= d <= 31:
        return False
    return True


def parse_date(value):
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    match = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", text)
    if match:
        y, m, d = (int(part) for part in match.groups())
        return Date(y, m, d) if _valid(y, m, d) else None
    match = re.fullmatch(r"(\d{4})-(\d{2})", text)
    if match:
        y, m = int(match.group(1)), int(match.group(2))
        return Date(y, m, None) if _valid(y, m, None) else None
    match = re.fullmatch(r"(\d{4})", text)
    if match:
        y = int(match.group(1))
        return Date(y, None, None) if _valid(y, None, None) else None
    match = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", text)
    if match:
        first, second, y = (int(part) for part in match.groups())
        # Unambiguous when one side cannot be a month; otherwise the bank uses DD/MM.
        if first > 12 and second <= 12:
            day, month = first, second
        elif second > 12 and first <= 12:
            day, month = second, first
        else:
            day, month = first, second
        return Date(y, month, day) if _valid(y, month, day) else None
    match = re.fullmatch(rf"({MON})\s+(\d{{1,2}}),\s+(\d{{4}})", text, re.I)
    if match:
        month = MONTHS[match.group(1).lower()]
        day, y = int(match.group(2)), int(match.group(3))
        return Date(y, month, day) if _valid(y, month, day) else None
    match = re.fullmatch(rf"(\d{{1,2}})\s+({MON})\s+(\d{{4}})", text, re.I)
    if match:
        day = int(match.group(1))
        month = MONTHS[match.group(2).lower()]
        y = int(match.group(3))
        return Date(y, month, day) if _valid(y, month, day) else None
    match = re.fullmatch(rf"({MON})\s+(\d{{4}})", text, re.I)
    if match:
        month = MONTHS[match.group(1).lower()]
        y = int(match.group(2))
        return Date(y, month, None) if _valid(y, month, None) else None
    return None


def dates_fit(screened, record):
    """Equal in every part both sides actually give. Missing is not a mismatch."""
    if screened is None or screened.y is None:
        return True
    if record is None or record.y is None:
        return False
    if screened.y != record.y:
        return False
    if screened.m and record.m and screened.m != record.m:
        return False
    if screened.d and record.d and screened.d != record.d:
        return False
    return True


def dob_agrees(customer, hit):
    if customer is None or hit is None or customer.y is None or hit.y is None:
        return False
    if customer.y != hit.y:
        return False
    if customer.m and hit.m and customer.m != hit.m:
        return False
    if customer.d and hit.d and (customer.m is None or hit.m is None or customer.m == hit.m):
        if customer.d != hit.d:
            return False
    return True


def same_year_risky(customer, hit, verified):
    """Same-year month or day clash that is not safe to clear on.

    Unverified customer dates, a 1 January hit date, and a day/month swap that
    would make the two dates agree all go to review instead of a clearance.
    """
    if customer is None or hit is None or customer.y is None or hit.y is None or customer.y != hit.y:
        return False
    months_differ = bool(customer.m and hit.m and customer.m != hit.m)
    days_differ = bool(
        customer.m and hit.m and customer.m == hit.m and customer.d and hit.d and customer.d != hit.d
    )
    if not months_differ and not days_differ:
        return False
    if not verified:
        return True
    if hit.m == 1 and hit.d == 1:
        return True
    if customer.m and customer.d and hit.m and hit.d and customer.d <= 12 and hit.d <= 12:
        swapped = customer.d == hit.m and customer.m == hit.d
        same = customer.m == hit.m and customer.d == hit.d
        if swapped and not same:
            return True
    return False


def dob_contradicts(customer, hit):
    if customer is None or hit is None or customer.y is None or hit.y is None:
        return False
    if abs(customer.y - hit.y) > 1:
        return True
    if customer.y == hit.y and customer.m and hit.m and customer.m != hit.m:
        return True
    if (
        customer.y == hit.y
        and customer.m
        and hit.m
        and customer.m == hit.m
        and customer.d
        and hit.d
        and customer.d != hit.d
    ):
        return True
    return False


def period_end(date):
    if date.d and date.m:
        return (date.y, date.m, date.d)
    if date.m:
        # Last day of that month. February uses 28, which is early enough to stay safe.
        last = {1: 31, 2: 28, 3: 31, 4: 30, 5: 31, 6: 30, 7: 31, 8: 31, 9: 30, 10: 31, 11: 30, 12: 31}[date.m]
        return (date.y, date.m, last)
    return (date.y, 12, 31)


def period_start(date):
    return (date.y, date.m or 1, date.d or 1)


def before(left, right):
    return left < right


def definitely_before(earlier, later):
    """True only when the latest possible earlier date is still before the earliest later date."""
    if earlier is None or later is None or earlier.y is None or later.y is None:
        return False
    return before(period_end(earlier), period_start(later))


def definitely_after(later, earlier):
    if earlier is None or later is None or earlier.y is None or later.y is None:
        return False
    return before(period_end(earlier), period_start(later))


def max_age(birth, report):
    """Oldest the person could be at the latest instant of the report."""
    if birth is None or report is None or birth.y is None or report.y is None:
        return None
    born = (birth.y, birth.m or 1, birth.d or 1)
    when = period_end(report)
    age = when[0] - born[0]
    if (when[1], when[2]) < (born[1], born[2]):
        age -= 1
    return age


# ---------------------------------------------------------------------------
# Names. Principle 8.
# ---------------------------------------------------------------------------

PLACEHOLDERS = {"na", "test", "unknown", "xxx", "none", "null", "nil"}


def load_variants(path):
    try:
        with open(path, encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError, UnicodeError):
        return defaultdict(set), set()
    if not isinstance(payload, dict):
        return defaultdict(set), set()
    groups = payload.get("groups") or []
    forms = {fold(item) for item in (payload.get("company_legal_forms") or []) if item}
    index = defaultdict(set)
    for number, group in enumerate(groups):
        for part in group:
            index[fold(part)].add(number)
    return index, forms


VARIANT_INDEX = {}
LEGAL_FORMS = set()


def variants_match(left, right):
    return bool(VARIANT_INDEX.get(left) and VARIANT_INDEX.get(right) and (VARIANT_INDEX[left] & VARIANT_INDEX[right]))


@lru_cache(maxsize=200000)
def levenshtein(left, right):
    if abs(len(left) - len(right)) > 2:
        return 3
    previous = list(range(len(right) + 1))
    for i, ch_left in enumerate(left, 1):
        current = [i]
        for j, ch_right in enumerate(right, 1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[j] + 1,
                    previous[j - 1] + (ch_left != ch_right),
                )
            )
        previous = current
    return previous[-1]


def parts_match(left, right):
    if not left or not right:
        return False
    # Native script is exact. CJK is never romanised, and a guess is not a match.
    if any(ord(ch) > 127 for ch in left + right):
        return left == right
    if left == right or variants_match(left, right):
        return True
    if normalize.skeleton_match(left, right):
        return True
    shortest = min(len(left), len(right))
    if shortest < 4:
        return False
    limit = 1 if shortest <= 6 else 2
    if abs(len(left) - len(right)) > limit:
        return False
    return levenshtein(left, right) <= limit


@lru_cache(maxsize=200000)
def name_parts(name, is_company):
    if not name:
        return tuple()
    text = re.sub(r"\([^)]*\)|\[[^\]]*\]", " ", str(name))
    text = fold(text)
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    parts = []
    seen = set()
    for part in text.split():
        if len(part) <= 1:
            continue
        if part in PLACEHOLDERS or part.isdigit():
            continue
        if is_company and part in LEGAL_FORMS:
            continue
        if part not in seen:
            seen.add(part)
            parts.append(part)
    return tuple(parts)


def name_coverage(short, longer):
    """How much of the shorter name is covered, and how many part-matches that took.

    Writing two parts as one word (Abdul Salam / Abdulsalam) consumes both parts
    and counts as one match. A name agrees when every part of the shorter name
    is covered, or when at least two separate parts match.
    """
    n_short = len(short)
    n_long = len(longer)
    best_consumed = 0
    best_groups = 0

    def walk(index, used, consumed, groups):
        nonlocal best_consumed, best_groups
        if consumed > best_consumed:
            best_consumed = consumed
        if groups > best_groups:
            best_groups = groups
        if index >= n_short or consumed == n_short:
            return
        if consumed + (n_short - index) <= best_consumed and groups + (n_short - index) <= best_groups:
            return
        walk(index + 1, used, consumed, groups)
        for pos in range(n_long):
            if pos in used:
                continue
            if parts_match(short[index], longer[pos]):
                used.add(pos)
                walk(index + 1, used, consumed + 1, groups + 1)
                used.remove(pos)
        if index + 1 < n_short:
            joined = short[index] + short[index + 1]
            for pos in range(n_long):
                if pos in used:
                    continue
                if parts_match(joined, longer[pos]):
                    used.add(pos)
                    walk(index + 2, used, consumed + 2, groups + 1)
                    used.remove(pos)
        for pos in range(n_long - 1):
            if pos in used or (pos + 1) in used:
                continue
            if parts_match(short[index], longer[pos] + longer[pos + 1]):
                used.add(pos)
                used.add(pos + 1)
                walk(index + 1, used, consumed + 1, groups + 1)
                used.remove(pos)
                used.remove(pos + 1)

    walk(0, set(), 0, 0)
    return best_consumed, best_groups


def names_agree(left, right):
    if not left or not right:
        return False
    short, longer = (left, right) if len(left) <= len(right) else (right, left)
    consumed, groups = name_coverage(short, longer)
    if consumed == len(short):
        return True
    return groups >= 2


def _normalized_parts(name, is_company):
    parts = []
    seen = set()
    for part in normalize.normalize_parts(name, is_company):
        if is_company and part in LEGAL_FORMS:
            continue
        if part not in seen:
            seen.add(part)
            parts.append(part)
    return tuple(parts)


def _script_note(customer_raw, hit_raw):
    left = normalize.normalize_parts(customer_raw)
    right = normalize.normalize_parts(hit_raw)
    shared_cjk = [part for part in left if part in right and any(ord(ch) > 127 for ch in part)]
    if shared_cjk:
        return f"CJK name {shared_cjk[0]} matches the same characters on both sides"
    for raw, other in ((hit_raw, "the customer"), (customer_raw, "the hit")):
        scripts = normalize.scripts_in(raw) & {"Cyrillic", "Greek", "Arabic"}
        if not scripts:
            continue
        excerpt = normalize.native_excerpt(raw)
        latin = " ".join(part for part in normalize.normalize_parts(raw) if part and ord(part[0]) < 128)
        if excerpt and latin:
            return f"{sorted(scripts)[0]} name {excerpt} transliterates to {latin}, matching {other}"
    return ""


def multilingual_relation(customer_raw, hit_names, is_company):
    """Extra agreement from transliteration. Never a reason to clear.

    Returns agree, uncertain, note. Agree may confirm. Uncertain means the
    names could be transliterations, so a name clearance is not safe.
    """
    left = _normalized_parts(customer_raw, is_company)
    agree = False
    uncertain = False
    note = ""
    for raw in hit_names:
        if not raw:
            continue
        right = _normalized_parts(raw, is_company)
        if left and right and names_agree(left, right):
            agree = True
            written = _script_note(customer_raw, raw)
            if written:
                note = written
            continue
        scripts = (normalize.scripts_in(customer_raw) | normalize.scripts_in(raw)) & {"Cyrillic", "Greek", "Arabic"}
        if scripts and left and right and normalize._close_tokens(
            tuple(part for part in left if ord(part[0]) < 128),
            tuple(part for part in right if ord(part[0]) < 128),
        ):
            uncertain = True
    if agree:
        uncertain = False
    elif uncertain and not note:
        note = "The names could be transliterations of each other, so this is not cleared on name"
    return agree, uncertain, note


def any_name_agrees(customer_parts, hit_names, is_company):
    if not customer_parts:
        return False
    for hit_name in hit_names:
        if names_agree(customer_parts, name_parts(hit_name, is_company)):
            return True
    return False


# ---------------------------------------------------------------------------
# Free text: identity notes, residence notes, ages, dated reports.
# ---------------------------------------------------------------------------

DOC_RE = re.compile(r"passport|national id|driving licen[cs]e|identity card|id card|registry extract", re.I)
OK_RE = re.compile(r"verif|validat|approv|confirm|passed|cleared|successful|processed|completed|accepted", re.I)
REJECT_RE = re.compile(
    r"\b(rejected|rejection|failed|failure|expired|could not verify|unable to verify|not verified|unsuccessful)\b",
    re.I,
)
PROV_RE = re.compile(r"onfido|persona|sumsub|veriff|jumio|trulioo", re.I)
DOB_LABEL_RE = re.compile(r"(?:date of birth|birth date|born|dob)\s*(?:of|on|:|-)?\s*", re.I)
CHECK_RE = re.compile(r"(?:on|as of)\s+(\d{4}-\d{2}-\d{2})", re.I)
# Letters outside Latin-1 (Ć, Š, Ž) have to count as part of the name.
CAPS_RE = re.compile(r"[^\W\d_]+(?:['’\-][^\W\d_]+)*", re.UNICODE)
NAME_STOP = {"DOB", "ID", "USA", "UK", "UAE", "THE", "AND", "FOR", "VIA", "PER", "FROM"}
_NUM_WORD = (
    r"(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|"
    r"sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety)"
    r"(?:[-\s](?:one|two|three|four|five|six|seven|eight|nine))?"
)
_AGE_TOKEN = rf"(?:\d{{1,3}}|{_NUM_WORD})"
AGE_RE = re.compile(
    rf"\b(?:aged\s+({_AGE_TOKEN})|age\s+of\s+({_AGE_TOKEN})|age[:\s]+({_AGE_TOKEN})|"
    rf"({_AGE_TOKEN})\s*-\s*years?\s*-\s*old|({_AGE_TOKEN})\s+years?\s+old|"
    rf"was\s+({_AGE_TOKEN})(?:\s+years?\s+old)?|then\s+({_AGE_TOKEN})|"
    rf"reached\s+({_AGE_TOKEN})\s+years?\s+of\s+age|(?:^|[\s,])({_AGE_TOKEN})\s+year\s+old)\b",
    re.I,
)
BORN_RE = re.compile(r"\bborn\s+(?:on\s+|in\s+)?", re.I)
_WORD_ONES = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
    "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
    "seventeen": 17, "eighteen": 18, "nineteen": 19,
}
_WORD_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}
AGE_COMMA_RE = re.compile(r",\s*(\d{1,3})\s*,")
REPORT_RE = re.compile(
    rf"According to [^;\n]+;\s+({MON})\s+(?:(\d{{1,2}}),\s+)?(\d{{4}})\s*:",
    re.I,
)
ROLE_PHRASES = {
    "sanctions": "a sanctioned individual",
    "pep": "a politically exposed person",
    "enforcement": "the subject of enforcement action",
    "adverse media": "named in adverse media",
    "soe": "a state-owned enterprise official",
}


def extract_dates_after(pattern, text):
    for match in pattern.finditer(text):
        found = DATE_RE.match(text, match.end())
        if not found:
            continue
        parsed = parse_date(found.group(0))
        if parsed and parsed.y:
            return parsed
    return None


def extract_paren_date(text):
    for match in re.finditer(r"\(([^)]{4,48})\)", text):
        inner = re.sub(r"^dob\s+", "", match.group(1).strip(), flags=re.I)
        parsed = parse_date(inner)
        if parsed and parsed.y:
            return parsed
    return None


def extract_name(text):
    tokens = CAPS_RE.findall(text or "")
    best = []
    current = []

    def flush():
        nonlocal best
        words = [word for word in current if word.upper() not in NAME_STOP and sum(ch.isalpha() for ch in word) > 1]
        if len(words) > len(best):
            best = words
        current.clear()

    for token in tokens:
        letters = [ch for ch in token if ch.isalpha()]
        if letters and len(letters) >= 2 and all(ch.isupper() for ch in letters):
            current.append(token)
        else:
            flush()
    flush()
    if len(best) >= 1:
        return " ".join(best)
    labeled = re.search(
        r"(?:name on document|holder as|held by|identifying the holder as|name)\s*[:\-]?\s*((?:[A-Z][A-Za-zÀ-ÿ'’\-]+\s*){1,6})",
        text or "",
    )
    if labeled:
        return re.sub(r"\s+", " ", labeled.group(1)).strip()
    return None


def extract_doc_country(text):
    found = find_countries(text or "")
    if not found:
        return None
    anchors = [match.start() for match in re.finditer(r"passport|national id|driving licen|issued|document|from", text or "", re.I)]
    if not anchors:
        return found[-1][1]

    def distance(pos):
        return min(abs(pos - anchor) for anchor in anchors)

    return min(found, key=lambda item: distance(item[0]))[1]


def parse_identity_note(text):
    if not text:
        return None
    # A rejected, failed, or expired check is not a verified identity, even if a
    # provider name or the word "completed" also appears.
    if REJECT_RE.search(text):
        return None
    has_doc = DOC_RE.search(text)
    has_ok = OK_RE.search(text)
    has_prov = PROV_RE.search(text)
    if not ((has_doc and (has_ok or has_prov)) or (has_prov and has_ok)):
        return None
    dob = extract_dates_after(DOB_LABEL_RE, text) or extract_paren_date(text)
    name = extract_name(text)
    if not name and not dob:
        return None
    checked = None
    for match in CHECK_RE.finditer(text):
        candidate = parse_date(match.group(1))
        if candidate and (dob is None or candidate.iso() != dob.iso()):
            checked = candidate
            break
    return {
        "name": name,
        "dob": dob,
        "country": extract_doc_country(text),
        "checked": checked,
    }


def lived_countries(text):
    """Every country named in a non-identity note counts as a place the customer is tied to.

    The note may say settled, domiciled, stayed and worked, located and employed,
    lived, resides, moved to, or based in. Matching only those words misses the
    rest, and a missed country is what lets a location clear through. Naming the
    country is enough. Callers must not let a note country create a clear by itself.
    """
    if not text:
        return set()
    return {canon for _, canon in find_countries(text)}


def _word_number(token):
    text = token.lower().replace("-", " ")
    parts = text.split()
    if len(parts) == 1 and parts[0].isdigit():
        return int(parts[0])
    if len(parts) == 1 and parts[0] in _WORD_ONES:
        return _WORD_ONES[parts[0]]
    if len(parts) == 1 and parts[0] in _WORD_TENS:
        return _WORD_TENS[parts[0]]
    if len(parts) == 2 and parts[0] in _WORD_TENS and parts[1] in _WORD_ONES and _WORD_ONES[parts[1]] < 10:
        return _WORD_TENS[parts[0]] + _WORD_ONES[parts[1]]
    return None


def _age_from_match(match):
    for group in match.groups():
        if not group:
            continue
        if group.isdigit():
            age = int(group)
            spelled = False
        else:
            age = _word_number(group)
            spelled = True
        if age is None or not 1 <= age <= 120:
            continue
        # "one of the" is not an age. Spelled ages under 10 are not used.
        if spelled and age < 10:
            continue
        return age
    return None


def _anchor_date(chunk):
    """The date an age is measured against. A month-and-year beats a bare year."""
    month_date = None
    year_only = None
    for match in DATE_RE.finditer(chunk):
        parsed = parse_date(match.group(0))
        if not parsed or not parsed.y or not 1900 < parsed.y < 2100:
            continue
        if parsed.m and month_date is None:
            month_date = parsed
        elif parsed.m is None and parsed.d is None and year_only is None:
            year_only = parsed
    return month_date or year_only


def ages_in_text(text):
    """Return possible birth years from an age-at-a-date sentence."""
    if not text:
        return []
    years = []
    chunks = re.split(r"(?<=[.!?])\s+|\n+", text)
    for chunk in chunks:
        ages = []
        for match in AGE_RE.finditer(chunk):
            age = _age_from_match(match)
            if age:
                ages.append(age)
        for match in AGE_COMMA_RE.finditer(chunk):
            age = int(match.group(1))
            if 1 <= age <= 120:
                ages.append(age)
        if not ages:
            continue
        date_found = _anchor_date(chunk)
        if not date_found:
            continue
        for age in ages:
            years.append(date_found.y - age)
            years.append(date_found.y - age - 1)
    # Unique, stable.
    seen = []
    for year in years:
        if 1800 < year < 2100 and year not in seen:
            seen.append(year)
    return sorted(seen)


def birth_dates_in_text(text):
    """Explicit 'born on 30 June 1969' or 'born in 1966' dates. Full dates stay full."""
    if not text:
        return []
    found = []
    seen = set()
    for match in BORN_RE.finditer(text):
        window = text[match.end():match.end() + 32]
        date_match = DATE_RE.search(window)
        if not date_match or date_match.start() > 3:
            continue
        parsed = parse_date(date_match.group(0))
        if not parsed or not parsed.y:
            continue
        key = parsed.iso()
        if key not in seen:
            seen.add(key)
            found.append(parsed)
    return found


def _dob_phrase(dates):
    if len(dates) == 2 and all(item.m is None and item.d is None for item in dates):
        return f"{dates[0].y} or {dates[1].y}"
    return ", ".join(item.iso() for item in dates)


def dated_reports(notes):
    found = []
    if not notes:
        return found
    for match in REPORT_RE.finditer(notes):
        month = MONTHS[match.group(1).lower()]
        day = int(match.group(2)) if match.group(2) else None
        year = int(match.group(3))
        if _valid(year, month, day):
            found.append(Date(year, month, day))
    found.sort(key=lambda item: item.key())
    return found


def first_paragraph(notes):
    if not notes:
        return ""
    return re.split(r"\n\s*\n", notes, maxsplit=1)[0]


def search_key(name):
    text = fold(name)
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    words = [word for word in text.split() if word]
    return " ".join(sorted(words))


def role_phrase(hit):
    category = hit.get("primary_category") or ((hit.get("categories") or [None])[0])
    if not category:
        return "named on a watchlist"
    return ROLE_PHRASES.get(str(category).strip().lower(), "named on a watchlist")


def country_in_text(text, canon):
    folded = fold(text)
    aliases = [alias for alias, name in SCAN if name == canon]
    aliases.append(fold(canon))
    for alias in aliases:
        if len(alias) < 4 and alias not in {"usa", "uae", "uk"}:
            continue
        for match in re.finditer(re.escape(alias), folded):
            start, end = match.start(), match.end()
            left_ok = start == 0 or not folded[start - 1].isalnum()
            right_ok = end == len(folded) or not folded[end].isalnum()
            if left_ok and right_ok:
                return True
    return False


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------


def read_jsonl(path):
    """Missing files and bad lines are skipped. A broken file must not erase the run."""
    rows = []
    try:
        handle = open(path, encoding="utf-8")
    except OSError:
        sys.stderr.write(f"missing {path}\n")
        return rows
    with handle:
        for number, line in enumerate(handle, 1):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                sys.stderr.write(f"bad json {path}:{number}\n")
                continue
            if isinstance(row, dict):
                rows.append(row)
            else:
                sys.stderr.write(f"bad json {path}:{number}\n")
    return rows


def as_list(value):
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        return [part.strip() for part in value.split(";") if part.strip()]
    return [value]


def company_flag(entity_type):
    if not entity_type:
        return None
    text = str(entity_type).strip().lower()
    if text in {"company", "organization", "organisation", "org", "entity"}:
        return True
    if text in {"individual", "person"}:
        return False
    return None


class Store:
    def __init__(self, data_dir):
        global VARIANT_INDEX, LEGAL_FORMS
        VARIANT_INDEX, LEGAL_FORMS = load_variants(f"{data_dir}/name_variants.json")
        self.alerts = {}
        for row in read_jsonl(f"{data_dir}/alerts.jsonl"):
            if row.get("alert_id"):
                self.alerts[row["alert_id"]] = row
        self.hits = [row for row in read_jsonl(f"{data_dir}/hits.jsonl") if row.get("hit_id")]
        self.hit_ids = {row["hit_id"] for row in self.hits}
        self.customers = {}
        for row in read_jsonl(f"{data_dir}/customers.jsonl"):
            if row.get("record_id"):
                self.customers[row["record_id"]] = row
        accounts = [row for row in read_jsonl(f"{data_dir}/accounts.jsonl") if row.get("account_id") and row.get("customer_id")]
        onboarding = [row for row in read_jsonl(f"{data_dir}/onboarding.jsonl") if row.get("account_id") and row.get("customer_id")]
        checks = [row for row in read_jsonl(f"{data_dir}/kyc_checks.jsonl") if row.get("check_id") and row.get("applicant_id")]
        notes = [row for row in read_jsonl(f"{data_dir}/notes.jsonl") if row.get("note_id")]
        searches = [row for row in read_jsonl(f"{data_dir}/search_results.jsonl") if row.get("result_id")]

        self.accounts_by_id = defaultdict(list)
        self.accounts_by_customer = defaultdict(list)
        self.by_login = defaultdict(list)
        for account in accounts:
            self.accounts_by_id[account["account_id"]].append(account["customer_id"])
            self.accounts_by_customer[account["customer_id"]].append(account)
            login = (account.get("login_handle") or "").strip().lower()
            if login:
                self.by_login[login].append(account["customer_id"])

        self.onboarding = defaultdict(list)
        for row in onboarding:
            applicant = row.get("kyc_applicant_id")
            if applicant:
                self.onboarding[(row["account_id"], row["customer_id"])].append(applicant)

        self.checks_by_applicant = defaultdict(list)
        self.kyc = {}
        for check in checks:
            self.checks_by_applicant[check["applicant_id"]].append(check)
            self.kyc[check["check_id"]] = check

        self.notes_by_email = defaultdict(list)
        self.notes = {}
        for note in notes:
            self.notes[note["note_id"]] = note
            email = (note.get("requester_email") or "").strip().lower()
            if email:
                self.notes_by_email[email].append(note)

        self.by_email = defaultdict(list)
        self.by_year = defaultdict(set)
        self.by_country = defaultdict(set)
        self.by_part = defaultdict(set)
        self.customer_dob = {}
        self.customer_countries = {}
        for record_id, customer in self.customers.items():
            email = (customer.get("email") or "").strip().lower()
            if email:
                self.by_email[email].append(record_id)
            dob = parse_date(customer.get("dob"))
            self.customer_dob[record_id] = dob
            if dob and dob.y:
                self.by_year[dob.y].add(record_id)
            countries = set()
            for field in ("nationality", "residence_country"):
                canon = canon_field(customer.get(field))
                if canon:
                    countries.add(canon)
                    self.by_country[canon].add(record_id)
            self.customer_countries[record_id] = countries
            is_co = company_flag(customer.get("entity_type")) is True
            for field in ("full_name", "preferred_name", "login_name"):
                for part in name_parts(customer.get(field), is_co):
                    self.by_part[part].add(record_id)

        self.search_by_query = defaultdict(list)
        self.search = {}
        for result in searches:
            self.search[result["result_id"]] = result
            self.search_by_query[(result.get("query") or "").strip().lower()].append(result)

        self._phone_dob = defaultdict(list)
        self._docs = defaultdict(list)
        self._docs_of = defaultdict(set)
        self._person_cache = {}
        self._build_links()

    def _build_links(self):
        approved = defaultdict(list)
        for record_id in self.customers:
            for check in self.approved_checks(record_id):
                number = re.sub(r"\s+", "", (check.get("document_number") or "")).upper()
                if len(number) < 5 or number in {"NONE", "UNKNOWN", "NULL", "TEST", "N/A", "NA"}:
                    continue
                self._docs_of[record_id].add(number)
                approved[number].append(record_id)
        for number, ids in approved.items():
            unique = list(dict.fromkeys(ids))
            if 1 < len(unique) <= 8:
                self._docs[number] = unique
        for record_id, customer in self.customers.items():
            phone = re.sub(r"\D", "", customer.get("phone") or "")
            dob = self.customer_dob.get(record_id)
            if len(phone) >= 8 and dob and dob.full():
                self._phone_dob[(phone, dob.iso())].append(record_id)

    def approved_checks(self, record_id):
        found = []
        for account in self.accounts_by_customer.get(record_id, []):
            for applicant in self.onboarding.get((account["account_id"], record_id), []):
                for check in self.checks_by_applicant.get(applicant, []):
                    if str(check.get("result") or "").lower() == "approved":
                        found.append(check)
        return found

    def expand(self, seed):
        cached = self._person_cache.get(seed)
        if cached:
            return cached
        seen = set()
        stack = [seed]
        while stack:
            current = stack.pop()
            if current in seen or current not in self.customers:
                continue
            seen.add(current)
            customer = self.customers[current]
            phone = re.sub(r"\D", "", customer.get("phone") or "")
            dob = self.customer_dob.get(current)
            if len(phone) >= 8 and dob and dob.full():
                for other in self._phone_dob.get((phone, dob.iso()), []):
                    if other not in seen:
                        stack.append(other)
            for number in self._docs_of.get(current, ()):
                for other in self._docs.get(number, []):
                    if other not in seen:
                        stack.append(other)
        group = frozenset(seen)
        for record_id in seen:
            self._person_cache[record_id] = group
        return group


def screened_customer(alert):
    customer = alert.get("customer") or {}
    if not isinstance(customer, dict):
        customer = {}
    return {
        "name": customer.get("name") or alert.get("customer_name"),
        "entity_type": customer.get("entity_type") or alert.get("entity_type"),
        "dob": parse_date(customer.get("dob") if "dob" in customer else alert.get("dob")),
        "country": canon_field(customer.get("country") if "country" in customer else alert.get("country")),
        "city": customer.get("city") if "city" in customer else alert.get("city"),
    }


def norm_city(value):
    text = fold(value)
    return re.sub(r"[^a-z0-9\s]", " ", text)


def city_fits(screened_city, customer):
    if not screened_city:
        return True
    needle = norm_city(screened_city).strip()
    if not needle:
        return True
    for field in (customer.get("city"), customer.get("address")):
        if field and needle in norm_city(field):
            return True
    return False


def name_fits(screened_name, customer):
    is_company = company_flag(customer.get("entity_type")) is True
    screened_parts = name_parts(screened_name, is_company)
    if not screened_parts:
        return False
    for field in ("full_name", "preferred_name", "login_name"):
        parts = name_parts(customer.get(field), is_company)
        if parts and names_agree(screened_parts, parts):
            return True
    return False


def type_compatible(screened_type, customer):
    left = company_flag(screened_type)
    right = company_flag(customer.get("entity_type"))
    if left is None or right is None:
        return True
    return left == right


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------


def unique(seq):
    seen = set()
    out = []
    for item in seq:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


def resolve_seeds(store, alert, screened):
    account_ref = (alert.get("account_ref") or "").strip()
    login = (alert.get("login_handle") or "").strip().lower()
    email = (alert.get("email") or "").strip().lower()
    if account_ref:
        holders = unique(store.accounts_by_id.get(account_ref, []))
        if len(holders) <= 1:
            return holders
        fit = []
        for record_id in holders:
            customer = store.customers.get(record_id)
            if not customer:
                continue
            if name_fits(screened["name"], customer) and dates_fit(screened["dob"], store.customer_dob.get(record_id)):
                fit.append(record_id)
        return fit
    if login:
        holders = unique(store.by_login.get(login, []))
        return _filter_holders(store, holders, screened)
    if email:
        holders = unique(store.by_email.get(email, []))
        return _filter_holders(store, holders, screened)
    return attribute_search(store, screened)


def _filter_holders(store, holders, screened):
    if len(holders) <= 1:
        return holders
    fit = []
    for record_id in holders:
        customer = store.customers[record_id]
        if not type_compatible(screened["entity_type"], customer):
            continue
        if not name_fits(screened["name"], customer):
            continue
        if not dates_fit(screened["dob"], store.customer_dob.get(record_id)):
            continue
        if screened["country"] and screened["country"] not in store.customer_countries.get(record_id, set()):
            continue
        if not city_fits(screened["city"], customer):
            continue
        fit.append(record_id)
    return fit or holders


def attribute_search(store, screened):
    pools = []
    if screened["dob"] and screened["dob"].y:
        pools.append(store.by_year.get(screened["dob"].y, set()))
    if screened["country"]:
        pools.append(store.by_country.get(screened["country"], set()))
    if not pools:
        ids = set()
        is_company = company_flag(screened["entity_type"]) is True
        for part in name_parts(screened["name"], is_company):
            ids |= store.by_part.get(part, set())
            for other, groups in VARIANT_INDEX.items():
                if groups & VARIANT_INDEX.get(part, set()):
                    ids |= store.by_part.get(other, set())
        pools.append(ids)
    candidates = set.intersection(*[set(pool) for pool in pools]) if pools else set()
    found = []
    for record_id in sorted(candidates):
        customer = store.customers[record_id]
        if not type_compatible(screened["entity_type"], customer):
            continue
        if not name_fits(screened["name"], customer):
            continue
        if not dates_fit(screened["dob"], store.customer_dob.get(record_id)):
            continue
        if screened["country"] and screened["country"] not in store.customer_countries.get(record_id, set()):
            continue
        if not city_fits(screened["city"], customer):
            continue
        found.append(record_id)
    return sorted(found)


def person_groups(store, seeds):
    groups = []
    seen = set()
    for seed in seeds:
        if seed in seen or seed not in store.customers:
            continue
        group = store.expand(seed)
        seen |= set(group)
        groups.append((seed, group))
    groups.sort(key=lambda item: min(item[1]))
    return groups


def hit_country_set(hit):
    values = []
    for field in ("countries", "nationality", "citizenship"):
        values.extend(as_list(hit.get(field)))
    values.extend(as_list(hit.get("addresses")))
    if hit.get("place_of_birth"):
        values.append(hit.get("place_of_birth"))
    return country_set_from_values(values)


def hit_name_list(hit):
    names = [hit.get("name")]
    names.extend(as_list(hit.get("aliases")))
    return [name for name in names if name]


def gather_hit_dobs(store, hit, hit_countries, is_company):
    raw = [parse_date(item) for item in as_list(hit.get("dobs"))]
    parsed = [item for item in raw if item and item.y]
    if parsed:
        phrase = ", ".join(item.iso() for item in parsed)
        return parsed, "field", phrase, []
    if is_company:
        return [], "none", "", []
    paragraph = first_paragraph(hit.get("profile_notes"))
    born = birth_dates_in_text(paragraph)
    if born:
        return born, "notes", _dob_phrase(born), []
    years = ages_in_text(paragraph)
    if years:
        dates = [Date(year) for year in years]
        return dates, "notes", _dob_phrase(dates), []
    if not hit_countries:
        return [], "none", "", []
    phrase_role = role_phrase(hit)
    matched = []
    years = []
    dates = []
    seen_dates = set()
    seen_results = set()
    queries = []
    for name in hit_name_list(hit):
        key = search_key(name)
        if key and key not in queries:
            queries.append(key)
    for query in queries:
        for result in store.search_by_query.get(query, []):
            if result["result_id"] in seen_results:
                continue
            seen_results.add(result["result_id"])
            blob = f"{result.get('title') or ''} {result.get('snippet') or ''}"
            if phrase_role not in blob.lower():
                continue
            if not any(country_in_text(blob, country) for country in hit_countries):
                continue
            matched.append(result["result_id"])
            snippet = result.get("snippet") or ""
            explicit = birth_dates_in_text(snippet)
            if explicit:
                for item in explicit:
                    if item.iso() not in seen_dates:
                        seen_dates.add(item.iso())
                        dates.append(item)
                continue
            for year in ages_in_text(snippet):
                if year not in years:
                    years.append(year)
    for year in sorted(years):
        key = f"{year:04d}"
        if key not in seen_dates:
            seen_dates.add(key)
            dates.append(Date(year))
    if not dates:
        return [], "none", "", []
    dates.sort(key=lambda item: item.key())
    return dates, "search", _dob_phrase(dates), sorted(matched)


def identity_facts(store, group):
    """Latest approved check wins name, DOB and document country. Older checks only add a new country."""
    candidates = []
    for record_id in sorted(group):
        for check in store.approved_checks(record_id):
            dob = parse_date(check.get("verified_dob"))
            candidates.append(
                {
                    "id": check["check_id"],
                    "when": check.get("checked_at") or "",
                    "name": check.get("verified_name"),
                    "dob": dob,
                    "country": canon_field(check.get("document_country")),
                }
            )
        email = (store.customers[record_id].get("email") or "").strip().lower()
        for note in store.notes_by_email.get(email, []):
            parsed = parse_identity_note(note.get("text") or "")
            if not parsed:
                continue
            when = parsed["checked"].iso() if parsed["checked"] else (note.get("created_at") or "")
            candidates.append(
                {
                    "id": note["note_id"],
                    "when": when,
                    "name": parsed["name"],
                    "dob": parsed["dob"],
                    "country": parsed["country"],
                }
            )
    candidates.sort(key=lambda item: (item["when"], item["id"]), reverse=True)
    name = dob = country = None
    name_source = dob_source = country_source = None
    extra_countries = []
    for item in candidates:
        if name is None and item["name"]:
            name, name_source = item["name"], item["id"]
        if dob is None and item["dob"] and item["dob"].y:
            dob, dob_source = item["dob"], item["id"]
        if country is None and item["country"]:
            country, country_source = item["country"], item["id"]
        elif item["country"] and item["country"] != country:
            extra_countries.append((item["id"], item["country"]))
    verified = name_source is not None
    return {
        "name": name,
        "name_source": name_source,
        "dob": dob,
        "dob_source": dob_source,
        "country": country,
        "country_source": country_source,
        "extra_countries": extra_countries,
        "verified_name": verified,
        "candidates": candidates,
    }


def residence_facts(store, group, identity_ids):
    notes = []
    for record_id in sorted(group):
        email = (store.customers[record_id].get("email") or "").strip().lower()
        for note in store.notes_by_email.get(email, []):
            if note["note_id"] in identity_ids:
                continue
            countries = lived_countries(note.get("text") or "")
            if countries:
                notes.append((note["note_id"], countries))
    return notes


def join_countries(countries):
    return ", ".join(sorted(countries))


def second_fact(code, hit_name, cust_places, hit_places, dob_bit, dob_phrase, compare_name, earliest, at_most):
    """A second sentence. It names the hit and does not repeat the first sentence's dates or countries."""
    if code == "LOCATION_MISMATCH":
        return sentence(f"Hit {hit_name} shares none of the customer's countries")
    if code == "NAME_MISMATCH_VERIFIED":
        return sentence(f"No name on hit {hit_name} agrees with the verified name")
    if code == "DOB_MISMATCH":
        return sentence(f"No date for hit {hit_name} agrees with the customer")
    if code == "TEMPORAL_IMPOSSIBILITY":
        return sentence(f"Hit {hit_name} could not be the customer at the date of that report")
    if code == "DECEASED":
        return sentence(f"Hit {hit_name} had already died before this customer was screened")
    if code == "ENTITY_TYPE_MISMATCH":
        return sentence(f"Hit {hit_name} cannot be the same entity as the customer")
    return sentence(f"Hit {hit_name} is not resolved as the same entity")


def sentence(*parts):
    text = " ".join(part.strip().rstrip(".") for part in parts if part and part.strip())
    if not text:
        return ""
    return text + "."


def decide_person(store, alert, hit, seed, group, screened):
    hit_company = company_flag(hit.get("entity_type"))
    customer_company = company_flag(store.customers[seed].get("entity_type"))
    if customer_company is None:
        customer_company = company_flag(screened["entity_type"])
    is_company = customer_company is True

    facts = identity_facts(store, group)
    identity_ids = {item["id"] for item in facts["candidates"]}
    residence = residence_facts(store, group, identity_ids)

    record_sources = []
    record_countries = set()
    for record_id in sorted(group):
        countries = set(store.customer_countries.get(record_id, set()))
        if countries:
            record_sources.append((record_id, countries))
            record_countries |= countries
    # Record and verified-document countries can justify a location clear.
    # A country named only in a note can overlap the hit and block that clear,
    # but it cannot create one: this change only removes clears.
    anchor_countries = set(record_countries)
    if facts["country"]:
        anchor_countries.add(facts["country"])
    for _, country in facts["extra_countries"]:
        anchor_countries.add(country)
    residence_countries = set()
    for _, countries in residence:
        residence_countries |= countries
    customer_countries = set(anchor_countries) | residence_countries

    hit_countries = hit_country_set(hit)
    overlap = customer_countries & hit_countries
    location_mismatch = bool(anchor_countries) and bool(hit_countries) and not overlap

    # Name used for the comparison. Verified legal name outranks the record.
    if facts["name"]:
        compare_name = facts["name"]
        name_source = facts["name_source"]
        name_verified = True
    else:
        compare_name = store.customers[seed].get("full_name")
        name_source = seed
        name_verified = False
    compare_parts = name_parts(compare_name, is_company)
    hit_names = hit_name_list(hit)
    too_thin = (not is_company and len(compare_parts) < 2) or len(compare_parts) == 0
    if too_thin:
        name_agree = False
        name_mismatch = False
    else:
        name_agree = any_name_agrees(compare_parts, hit_names, is_company)
        name_mismatch = bool(name_verified and not name_agree)
    # Transliteration may confirm, or stop a name clearance. It never creates one.
    # A single real name part still cannot confirm an individual.
    script_agree, script_uncertain, script_note = multilingual_relation(compare_name, hit_names, is_company)
    enough_parts = is_company or len(_normalized_parts(compare_name, False)) >= 2
    applied_agree = bool(script_agree and enough_parts)
    applied_uncertain = False
    if applied_agree:
        name_agree = True
        name_mismatch = False
    elif script_uncertain and name_mismatch:
        name_mismatch = False
        applied_uncertain = True

    dob_verified = bool(facts["dob"] and facts["dob"].y)
    if dob_verified:
        customer_dob = facts["dob"]
        dob_source = facts["dob_source"]
    else:
        customer_dob = store.customer_dob.get(seed)
        dob_source = seed if customer_dob and customer_dob.y else None
        if customer_dob is None or customer_dob.y is None:
            for record_id in sorted(group):
                other = store.customer_dob.get(record_id)
                if other and other.y:
                    customer_dob = other
                    dob_source = record_id
                    break

    hit_dobs, dob_origin, dob_phrase, search_ids = gather_hit_dobs(store, hit, hit_countries, is_company)

    def contradicts(item):
        if not dob_contradicts(customer_dob, item):
            return False
        if same_year_risky(customer_dob, item, dob_verified):
            return False
        return True

    dob_agree = bool(customer_dob and customer_dob.y and any(dob_agrees(customer_dob, item) for item in hit_dobs))
    dob_mismatch = bool(
        customer_dob
        and customer_dob.y
        and hit_dobs
        and not dob_agree
        and all(contradicts(item) for item in hit_dobs)
    )
    dob_risky = bool(
        customer_dob
        and customer_dob.y
        and hit_dobs
        and not dob_agree
        and not dob_mismatch
        and any(same_year_risky(customer_dob, item, dob_verified) for item in hit_dobs)
    )

    reports = [] if is_company else dated_reports(hit.get("profile_notes"))
    if is_company:
        reports = dated_reports(hit.get("profile_notes"))
    earliest = reports[0] if reports else None
    temporal = False
    at_most = None
    if earliest and not is_company and customer_dob and customer_dob.y:
        at_most = earliest.y - customer_dob.y
        precise = max_age(customer_dob, earliest)
        temporal = (at_most is not None and at_most < 16) or (precise is not None and precise < 16)
        if at_most is None or at_most >= 16:
            at_most = precise
    incorporated_after = bool(is_company and earliest and customer_dob and definitely_after(customer_dob, earliest))
    if incorporated_after:
        temporal = True

    death = parse_date(hit.get("deceased_date"))
    screened_on = parse_date(alert.get("screened_at"))
    # A deceased flag with no date is not a clearance. A dated death before screening is.
    deceased = definitely_before(death, screened_on)
    undated_death = str(hit.get("life_status") or "").lower() == "deceased" and death is None

    type_mismatch = (
        customer_company is not None and hit_company is not None and customer_company != hit_company
    )

    # Location does not clear a hit whose name and date agree.
    name_and_date = name_agree and dob_agree
    location_clears = location_mismatch and not name_and_date

    applicable = []
    if type_mismatch:
        applicable.append("ENTITY_TYPE_MISMATCH")
    if deceased:
        applicable.append("DECEASED")
    if temporal:
        applicable.append("TEMPORAL_IMPOSSIBILITY")
    if dob_mismatch:
        applicable.append("DOB_MISMATCH")
    if location_clears:
        applicable.append("LOCATION_MISMATCH")
    if name_mismatch:
        applicable.append("NAME_MISMATCH_VERIFIED")

    blocked_review = bool(location_mismatch and name_and_date and not applicable)

    if applicable:
        decision = "DIFFERENT_ENTITY"
        # Prefer the contradiction the labelled examples list first.
        order = [
            "ENTITY_TYPE_MISMATCH",
            "DECEASED",
            "TEMPORAL_IMPOSSIBILITY",
            "DOB_MISMATCH",
            "LOCATION_MISMATCH",
            "NAME_MISMATCH_VERIFIED",
        ]
        code = next(item for item in order if item in applicable)
    elif is_company and name_agree and overlap and not applicable:
        decision = "SAME_ENTITY"
        code = "NAME_LOCATION_MATCH"
    elif (not is_company) and name_agree and dob_agree and not location_mismatch and not applicable:
        decision = "SAME_ENTITY"
        code = "NAME_DOB_LOCATION_MATCH" if overlap else "NAME_DOB_MATCH"
    else:
        decision = "REVIEW"
        code = "INSUFFICIENT_DATA"

    # A profile marked deceased without a date cannot be confirmed. A separate
    # contradiction can still clear it.
    if undated_death and decision == "SAME_ENTITY":
        decision = "REVIEW"
        code = "INSUFFICIENT_DATA"
        blocked_review = False

    reason = build_reason(
        decision=decision,
        code=code,
        applicable=applicable,
        blocked_review=blocked_review,
        undated_death=undated_death,
        hit=hit,
        customer_dob=customer_dob,
        dob_source=dob_source,
        dob_origin=dob_origin,
        dob_phrase=dob_phrase,
        compare_name=compare_name,
        name_source=name_source,
        customer_countries=customer_countries,
        hit_countries=hit_countries,
        overlap=overlap,
        earliest=earliest,
        at_most=at_most,
        death=death,
        screened_on=screened_on,
        is_company=is_company,
        name_agree=name_agree,
        seed=seed,
        dob_verified=dob_verified,
        dob_risky=dob_risky,
        script_note=script_note if (applied_agree or applied_uncertain) else "",
        script_blocked=applied_uncertain,
        store=store,
        facts=facts,
        search_ids=search_ids if dob_origin == "search" else [],
    )
    evidence = build_evidence(
        decision=decision,
        applicable=set(applicable),
        blocked_review=blocked_review,
        group=group,
        record_sources=record_sources,
        facts=facts,
        residence=residence,
        dob_source=dob_source,
        name_source=name_source,
        search_ids=search_ids if dob_origin == "search" else [],
        used_search=dob_origin == "search" and bool(search_ids) and (dob_agree or dob_mismatch or blocked_review or "DOB_MISMATCH" in applicable),
        hit_countries=hit_countries,
        seed=seed,
    )
    return {
        "decision": decision,
        "reason_code": code,
        "customer_record_id": seed,
        "reason": reason,
        "evidence": evidence,
        "group": sorted(group),
    }


_ID_RE = re.compile(r"\b(?:H|CUS|KYC|NOTE|SR|A|ACC|APP)-[0-9A-Za-z]+\b")


def cited_ids(reason):
    """IDs written in the reason, in a stable order. Evidence is this list."""
    found = []
    for item in _ID_RE.findall(reason or ""):
        if item not in found:
            found.append(item)
    return sorted(found)


def _approval_date(facts, source_id):
    if not facts or not source_id:
        return ""
    for item in facts.get("candidates") or []:
        if item.get("id") == source_id:
            when = str(item.get("when") or "")[:10]
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", when):
                return when
    return ""


def _plain(value):
    """Drop abbreviation dots so 'L.P.' is not counted as extra sentences."""
    return re.sub(r"\.(?=[A-Za-z]|\s|$)", "", str(value))


def _person_value(value, source_id, facts, field):
    """Quote a customer fact with the record that holds it. Never invent a date."""
    shown = _plain(value) if value not in (None, "") else "not on the customer record"
    if source_id and str(source_id).startswith(("KYC-", "NOTE-")):
        when = _approval_date(facts, source_id)
        if when:
            return f"{shown} ({source_id}, approved {when})"
        return f"{shown} ({source_id}, no approval date)"
    if source_id and str(source_id).startswith("CUS-"):
        return f"{shown} ({source_id} {field}; no approved check)"
    if source_id:
        return f"{shown} ({source_id} {field})"
    return f"{shown} (no approved check)"


def _hit_value(value, hit_id, field):
    if value in (None, "", []):
        return f"not on the list entry ({hit_id} {field})"
    return f"{_plain(value)} ({hit_id} {field})"


def _sentences(text):
    """Split on sentence ends. Periods inside L.P. or S.A. stay put."""
    parts = []
    buf = ""
    index = 0
    while index < len(text):
        if (
            text[index] == "."
            and index + 2 < len(text)
            and text[index + 1] == " "
            and text[index + 2].isupper()
        ):
            previous = buf.rstrip().split(" ")[-1] if buf.strip() else ""
            if "." not in previous:
                parts.append((buf + ".").strip())
                buf = ""
                index += 2
                continue
        buf += text[index]
        index += 1
    if buf.strip():
        parts.append(buf.strip())
    return parts


def _clip_reason(text):
    text = re.sub(r"\s+", " ", text or "").strip()
    if text and text[-1] not in ".!?":
        text += "."
    parts = _sentences(text)
    kept = []
    for part in parts:
        trial = " ".join(kept + [part])
        if len(trial) <= 300:
            kept.append(part)
        else:
            break
    text = " ".join(kept) if kept else text
    if len(text) > 300:
        cut = text[:299].rstrip(" ,;")
        text = cut + "."
    return text


def _country_field(hit):
    if hit.get("countries"):
        return "countries"
    if hit.get("nationality"):
        return "nationality"
    if hit.get("citizenship"):
        return "citizenship"
    if hit.get("addresses") or hit.get("place_of_birth"):
        return "addresses"
    return "countries"


def _short_places(countries, limit=3):
    names = sorted(countries or [])
    if not names:
        return "none"
    if len(names) <= limit:
        return ", ".join(names)
    return ", ".join(names[:limit]) + " +" + str(len(names) - limit)


def _customer_countries_cite(store, seed, countries, facts):
    customer = (store.customers.get(seed) if store and seed else None) or {}
    fields = []
    for field in ("residence_country", "nationality"):
        if canon_field(customer.get(field)) in (countries or set()):
            fields.append(field)
    if fields:
        return f"{_short_places(countries)} ({seed} {'/'.join(fields)})"
    if facts and facts.get("country_source") and facts.get("country"):
        return _person_value(facts["country"], facts["country_source"], facts, "document_country")
    if seed:
        return f"{_short_places(countries)} ({seed} residence_country)"
    return _short_places(countries)


def _hit_dob_cite(hit, origin, phrase, search_ids):
    hit_id = hit.get("hit_id")
    if origin == "field":
        raw = [str(item) for item in (hit.get("dobs") or []) if item]
        shown = ", ".join(raw[:3]) + ("…" if len(raw) > 3 else "")
        return _hit_value(shown or None, hit_id, "dobs")
    if origin == "notes":
        return _hit_value(phrase, hit_id, "profile_notes")
    if origin == "search" and search_ids:
        return f"{phrase} ({search_ids[0]} snippet)"
    return _hit_value(None, hit_id, "dobs")


def _alias_transliteration(hit, compare_name=""):
    hit_id = hit.get("hit_id")
    words = re.findall(r"[^\W\d_]+", compare_name or "", flags=re.UNICODE)
    folded_words = []
    for word in words:
        folded = "".join(ch for ch in normalize.fold_name(word) if ch.isalpha())
        folded_words.append((folded, word))
    for alias in hit.get("aliases") or []:
        scripts = normalize.scripts_in(alias) & {"Arabic", "Cyrillic", "Greek"}
        excerpt = normalize.native_excerpt(alias)
        latin_parts = [part for part in normalize.normalize_parts(alias) if part and ord(part[0]) < 128]
        if not (scripts and excerpt and latin_parts):
            continue
        gloss = []
        for part in latin_parts:
            chosen = part
            for folded, word in folded_words:
                close = folded == part or (
                    min(len(folded), len(part)) >= 4 and abs(len(folded) - len(part)) <= 2 and normalize._distance(folded, part) <= 2
                )
                if close:
                    chosen = word
                    break
            gloss.append(chosen)
        return f"{sorted(scripts)[0]} alias {excerpt} ({hit_id} aliases) may transliterate to {' '.join(gloss)}"
    return ""


def build_reason(
    decision,
    code,
    applicable,
    blocked_review,
    undated_death,
    hit,
    customer_dob,
    dob_source,
    dob_origin,
    dob_phrase,
    compare_name,
    name_source,
    customer_countries,
    hit_countries,
    overlap,
    earliest,
    at_most,
    death,
    screened_on,
    is_company,
    name_agree,
    seed,
    dob_verified=False,
    dob_risky=False,
    script_note="",
    script_blocked=False,
    store=None,
    facts=None,
    search_ids=None,
):
    """One or two sentences. Every fact names its value and the record that holds it."""
    facts = facts or {}
    search_ids = search_ids or []
    hit_id = hit.get("hit_id")
    alert_id = hit.get("alert_id")
    hit_name = hit.get("name") or "not on the list entry"
    dob_text = customer_dob.iso() if customer_dob and customer_dob.y else None
    if dob_text:
        cust_dob = _person_value(dob_text, dob_source, facts, "dob")
    elif seed:
        cust_dob = f"not on the customer record ({seed} dob; no approved check)"
    else:
        cust_dob = "not on the customer record (no approved check)"
    hit_dob = _hit_dob_cite(hit, dob_origin, dob_phrase, search_ids)
    if compare_name:
        name_cite = _person_value(compare_name, name_source, facts, "full_name")
    elif seed:
        name_cite = f"not on the customer record ({seed} full_name; no approved check)"
    else:
        name_cite = "not on the customer record (no approved check)"
    list_name = _hit_value(hit_name, hit_id, "primary_name")
    shared = _short_places(overlap)
    cust_places = _customer_countries_cite(store, seed, customer_countries, facts)
    hit_field = _country_field(hit)
    hit_places = _hit_value(_short_places(hit_countries) if hit_countries else None, hit_id, hit_field)
    years = [int(item) for item in re.findall(r"\b(?:19|20)\d{2}\b", dob_phrase or "")]
    gap = min(abs(customer_dob.y - year) for year in years) if customer_dob and customer_dob.y and years else None
    gap_text = f"{gap} years apart" if gap and gap > 1 else "more than 1 year apart"

    if script_blocked:
        alias = _alias_transliteration(hit, compare_name)
        if not alias:
            alias = f"A non-Latin alias ({hit_id} aliases) may transliterate to the list name"
        text = f"{alias}; verified name {name_cite}, so not cleared on name."
        if dob_origin == "none":
            text += f" Hit DOB is {_hit_value(None, hit_id, 'dobs')}."
        return _clip_reason(text)

    if undated_death and decision == "REVIEW" and not applicable and not blocked_review:
        return _clip_reason(
            f"life_status is Deceased ({hit_id} life_status) but deceased_date is not on the list entry. A death date would settle it."
        )

    if decision == "SAME_ENTITY" and code == "NAME_LOCATION_MATCH":
        return _clip_reason(
            f"Name {name_cite} agrees with {list_name}. Shared country {shared} ({seed}; {hit_id} {hit_field})."
        )
    if decision == "SAME_ENTITY":
        country = f" Shared country {shared} in {cust_places}." if overlap else ""
        return _clip_reason(f"DOB {cust_dob} agrees with hit DOB {hit_dob}; name agrees with {list_name}.{country}")

    if blocked_review:
        return _clip_reason(
            f"DOB {cust_dob} agrees with hit DOB {hit_dob} and name agrees with {list_name}, but countries do not: {cust_places} vs {hit_places}. A record placing the customer in the hit country would settle it."
        )

    if code == "DOB_MISMATCH":
        return _clip_reason(f"Hit DOB {hit_dob} contradicts customer DOB {cust_dob}; {gap_text}.")
    if code == "NAME_MISMATCH_VERIFIED":
        return _clip_reason(f"Verified name {name_cite} does not match list name {list_name}.")
    if code == "LOCATION_MISMATCH":
        return _clip_reason(f"Customer countries {cust_places} do not overlap hit countries {hit_places}.")
    if code == "DECEASED" and death and screened_on:
        return _clip_reason(
            f"Hit death date {death.iso()} ({hit_id} deceased_date) is before screening {screened_on.iso()} ({alert_id} screened_at)."
        )
    if code == "TEMPORAL_IMPOSSIBILITY" and earliest:
        if is_company:
            return _clip_reason(
                f"Incorporated {cust_dob} is after the earliest report {earliest.iso()} ({hit_id} profile_notes)."
            )
        return _clip_reason(
            f"DOB {cust_dob} is at most {at_most} on {earliest.iso()} ({hit_id} profile_notes); under 16."
        )
    if code == "ENTITY_TYPE_MISMATCH":
        cust_kind = "a company" if is_company else "an individual"
        hit_kind = "a company" if company_flag(hit.get("entity_type")) else "an individual"
        who = f"{seed} entity_type" if seed else "no customer record"
        return _clip_reason(
            f"Customer is {cust_kind} ({who}) and the hit is {hit_kind} ({hit_id} entity_type)."
        )

    # REVIEW. Name the missing or conflicting fact and the document that would settle it.
    if dob_risky:
        return _clip_reason(
            f"Customer DOB {cust_dob} and hit DOB {hit_dob} differ only by month or day in the same year. An identity document that matches the hit date exactly would settle it."
        )
    if not dob_text and dob_origin == "none":
        return _clip_reason(
            f"Customer DOB is {cust_dob} and hit DOB is {hit_dob}. An approved identity document with a date of birth would settle it."
        )
    if dob_text and dob_origin == "none":
        return _clip_reason(
            f"Customer DOB {cust_dob} cannot be compared: hit DOB is {hit_dob}. A listed date of birth would settle it."
        )
    if not dob_text and dob_phrase:
        return _clip_reason(
            f"Customer DOB is {cust_dob} against hit DOB {hit_dob}. An approved identity document with a date of birth would settle it."
        )
    if dob_text and dob_phrase:
        return _clip_reason(
            f"Customer DOB {cust_dob} and hit DOB {hit_dob} neither agree nor contradict. A full date of birth on both sides would settle it."
        )
    return _clip_reason(
        f"List name {list_name} has no contradiction and no confirming date of birth. An approved identity document with a date of birth would settle it."
    )



def build_evidence(
    decision,
    applicable,
    blocked_review,
    group,
    record_sources,
    facts,
    residence,
    dob_source,
    name_source,
    search_ids,
    used_search,
    hit_countries,
    seed,
):
    evidence = set()
    if decision == "SAME_ENTITY":
        evidence.update(group)
        if facts["name_source"]:
            evidence.add(facts["name_source"])
        if facts["dob_source"]:
            evidence.add(facts["dob_source"])
        if facts["country_source"]:
            evidence.add(facts["country_source"])
        if used_search:
            evidence.update(search_ids)
    if "LOCATION_MISMATCH" in applicable:
        for record_id, _countries in record_sources:
            evidence.add(record_id)
        if facts["country_source"]:
            evidence.add(facts["country_source"])
        for note_id, _countries in residence:
            evidence.add(note_id)
    if "DOB_MISMATCH" in applicable or "TEMPORAL_IMPOSSIBILITY" in applicable:
        if dob_source:
            evidence.add(dob_source)
        if used_search:
            evidence.update(search_ids)
    if "NAME_MISMATCH_VERIFIED" in applicable and name_source:
        evidence.add(name_source)
    if "DECEASED" in applicable or "ENTITY_TYPE_MISMATCH" in applicable:
        evidence.add(seed)
    if decision == "REVIEW":
        for record_id, countries in record_sources:
            if countries & hit_countries:
                evidence.add(record_id)
        if facts["country"] and facts["country"] in hit_countries and facts["country_source"]:
            evidence.add(facts["country_source"])
        for note_id, countries in residence:
            if countries & hit_countries:
                evidence.add(note_id)
        for extra_id, country in facts["extra_countries"]:
            if country in hit_countries:
                evidence.add(extra_id)
        if blocked_review:
            if dob_source:
                evidence.add(dob_source)
            if used_search:
                evidence.update(search_ids)
    # A review with nothing else to cite still names the customer record it used.
    if decision == "REVIEW" and seed and not evidence:
        evidence.add(seed)
    # A citation must be an id, never a bare null.
    return sorted(item for item in evidence if item)


def combine(alert, hit, outcomes):
    hit_id = hit["hit_id"]
    alert_id = hit["alert_id"]
    if not outcomes:
        screened = screened_customer(alert) if alert else {}
        hit_company = company_flag(hit.get("entity_type"))
        screened_company = company_flag(screened.get("entity_type"))
        if hit_company is not None and screened_company is not None and hit_company != screened_company:
            kind_c = "a company" if screened_company else "an individual"
            kind_h = "a company" if hit_company else "an individual"
            return {
                "hit_id": hit_id,
                "alert_id": alert_id,
                "decision": "DIFFERENT_ENTITY",
                "reason_code": "ENTITY_TYPE_MISMATCH",
                "customer_record_id": None,
                "reason": _clip_reason(
                    f"Screened customer is {kind_c} ({alert_id} customer.entity_type) and the hit is {kind_h} ({hit_id} entity_type)."
                ),
                "evidence": [],
            }
        return {
            "hit_id": hit_id,
            "alert_id": alert_id,
            "decision": "REVIEW",
            "reason_code": "INSUFFICIENT_DATA",
            "customer_record_id": None,
            "reason": _clip_reason(
                f"No customer record fits list name {hit.get('name') or 'not on the list entry'} ({hit_id} primary_name). An account link would settle it."
            ),
            "evidence": [],
        }

    decisions = {item["decision"] for item in outcomes}
    evidence = []
    seen = set()
    for item in outcomes:
        for evidence_id in item["evidence"]:
            if evidence_id not in seen:
                seen.add(evidence_id)
                evidence.append(evidence_id)
    if len(outcomes) == 1:
        chosen = outcomes[0]
        return {
            "hit_id": hit_id,
            "alert_id": alert_id,
            "decision": chosen["decision"],
            "reason_code": chosen["reason_code"],
            "customer_record_id": chosen["customer_record_id"],
            "reason": chosen["reason"],
            "evidence": chosen["evidence"],
        }
    if len(decisions) == 1:
        chosen = outcomes[0]
        return {
            "hit_id": hit_id,
            "alert_id": alert_id,
            "decision": chosen["decision"],
            "reason_code": chosen["reason_code"],
            "customer_record_id": "AMBIGUOUS",
            "reason": chosen["reason"],
            "evidence": evidence,
        }
    id_list = [item["customer_record_id"] for item in outcomes if item.get("customer_record_id")]
    ids = ", ".join(id_list[:3]) + (f" and {len(id_list) - 3} more" if len(id_list) > 3 else "")
    return {
        "hit_id": hit_id,
        "alert_id": alert_id,
        "decision": "REVIEW",
        "reason_code": "AMBIGUOUS_CUSTOMER_RECORD",
        "customer_record_id": "AMBIGUOUS",
        "reason": _clip_reason(
            f"Records {ids} lead to different decisions. A document that picks one person would settle it."
        ),
        "evidence": evidence,
    }


def resolve_hit(store, hit):
    alert = store.alerts.get(hit["alert_id"])
    if alert is None:
        return combine(None, hit, [])
    screened = screened_customer(alert)
    seeds = resolve_seeds(store, alert, screened)
    groups = person_groups(store, seeds)
    outcomes = [decide_person(store, alert, hit, seed, group, screened) for seed, group in groups]
    return combine(alert, hit, outcomes)


_CODE_DECISION = {
    "TEMPORAL_IMPOSSIBILITY": "DIFFERENT_ENTITY",
    "DOB_MISMATCH": "DIFFERENT_ENTITY",
    "LOCATION_MISMATCH": "DIFFERENT_ENTITY",
    "NAME_MISMATCH_VERIFIED": "DIFFERENT_ENTITY",
    "ENTITY_TYPE_MISMATCH": "DIFFERENT_ENTITY",
    "DECEASED": "DIFFERENT_ENTITY",
    "NAME_DOB_LOCATION_MATCH": "SAME_ENTITY",
    "NAME_DOB_MATCH": "SAME_ENTITY",
    "NAME_LOCATION_MATCH": "SAME_ENTITY",
    "INSUFFICIENT_DATA": "REVIEW",
    "AMBIGUOUS_CUSTOMER_RECORD": "REVIEW",
}


def _failsafe(hit):
    return {
        "hit_id": hit.get("hit_id"),
        "alert_id": hit.get("alert_id"),
        "decision": "REVIEW",
        "reason_code": "INSUFFICIENT_DATA",
        "customer_record_id": None,
        "reason": _clip_reason(
            f"Hit {hit.get('hit_id')} has no settled answer ({hit.get('hit_id')} primary_name). It is left for review."
        ),
        "evidence": [],
    }


def _write_rows(output_path, hits, answered):
    counts = defaultdict(int)
    with open(output_path, "w", encoding="utf-8") as handle:
        for hit in hits:
            row = dict(answered.get(hit["hit_id"]) or _failsafe(hit))
            row.pop("_audit", None)
            row.pop("group", None)
            row["evidence"] = cited_ids(row.get("reason"))
            counts[row["decision"]] += 1
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    return counts


def run(data_dir, output_path):
    started = time.time()
    store = None
    try:
        store = Store(data_dir)
        hits = sorted(store.hits, key=lambda row: row["hit_id"])
    except Exception as error:
        sys.stderr.write(f"load error: {error}\n")
        hits = sorted(read_jsonl(f"{data_dir}/hits.jsonl"), key=lambda row: row.get("hit_id") or "")
        hits = [row for row in hits if row.get("hit_id")]
        store = None
    answered = {}
    for hit in hits:
        if store is None:
            row = _failsafe(hit)
        else:
            try:
                row = resolve_hit(store, hit)
            except Exception as error:
                sys.stderr.write(f"error {hit.get('hit_id')}: {error}\n")
                row = _failsafe(hit)
            if not row or not row.get("hit_id") or row.get("decision") not in _CODE_DECISION.values():
                row = _failsafe(hit)
        if not row or not row.get("hit_id"):
            row = _failsafe(hit)
        answered[hit["hit_id"]] = row
    for hit in hits:
        if hit["hit_id"] not in answered:
            answered[hit["hit_id"]] = _failsafe(hit)
    try:
        counts = _write_rows(output_path, hits, answered)
    except Exception as error:
        sys.stderr.write(f"write error: {error}\n")
        answered = {hit["hit_id"]: _failsafe(hit) for hit in hits}
        counts = _write_rows(output_path, hits, answered)
    elapsed = time.time() - started
    sys.stderr.write(
        f"wrote {len(hits)} hits in {elapsed:.1f}s "
        f"DIFFERENT={counts['DIFFERENT_ENTITY']} SAME={counts['SAME_ENTITY']} REVIEW={counts['REVIEW']}\n"
    )


def self_test():
    assert parse_date("05/03/1968").iso() == "1968-03-05"
    assert parse_date("12/09/1985").iso() == "1985-09-12"
    assert parse_date("17 February 1968").iso() == "1968-02-17"
    assert parse_date("January 11, 1977").iso() == "1977-01-11"
    assert parse_date("1968-02").iso() == "1968-02"
    assert parse_date("February 1968").iso() == "1968-02"
    assert canon_field("GB") == "United Kingdom"
    assert canon_field("British") == "United Kingdom"
    assert canon_field("ES") == "Spain"
    assert canon_field("Dutch") == "Netherlands"
    assert canon_field("Belgrade, Serbia") == "Serbia"
    assert canon_field("Spain [Residency]") == "Spain"
    assert canon_field("International") is None
    global VARIANT_INDEX, LEGAL_FORMS
    VARIANT_INDEX = defaultdict(set)
    for number, group in enumerate([["mohammad", "muhammad"], ["john", "jon"], ["markus", "marcus"]]):
        for part in group:
            VARIANT_INDEX[part].add(number)
    LEGAL_FORMS = {"gmbh", "llc", "sa", "inc", "ltd"}
    assert names_agree(name_parts("Mohammad Nadeem", False), name_parts("Muhammad Nadeem", False))
    assert not names_agree(name_parts("Chinedu Azeez", False), name_parts("Ridwan Azeez", False))
    assert names_agree(name_parts("Tomasz Matteo Drozd", False), name_parts("Drozd, Tomasz Paweł", False))
    assert not names_agree(name_parts("Markus Gerhard Mueller", False), name_parts("Mark Mueller", False))
    assert names_agree(name_parts("Starling Bank GmbH", True), name_parts("Sterling Bank & Trust Co.", True))
    assert names_agree(name_parts("Abdulsalam", False), name_parts("Abdul Salam", False))
    assert names_agree(name_parts("Blue Grass", False), name_parts("Bluegrass Craft Coffee", False))
    assert not names_agree(name_parts("Blue Grass Holdings", False), name_parts("Bluegrass Craft Coffee Roasters", False))
    assert names_agree(name_parts("Giampiero Fiorani", False), name_parts("Gianpiero Fiorani", False))
    # Rule 8 edges that do not need the full variant file.
    assert not parts_match("sam", "pam")
    assert parts_match("ali", "ali")
    assert name_parts("Paweł N/A TEST 0000", False) == ("pawe",) or "pawe" in name_parts("Paweł N/A TEST 0000", False)
    assert "0000" not in name_parts("Sani 0000 0000", False)
    assert "na" not in name_parts("TD Bank, N.A.", True)
    assert "gmbh" not in name_parts("Stadtwerke München GmbH", True)
    variants_path = Path(__file__).resolve().parents[1] / "dev" / "name_variants.json"
    if variants_path.is_file():
        VARIANT_INDEX, LEGAL_FORMS = load_variants(str(variants_path))
        assert names_agree(
            name_parts("Mohammed Abdul Salam Ibrahim", False),
            name_parts("Muhammad Abdulsalam Ebrahim (AKA)", False),
        )
        assert names_agree(name_parts("Stadtwerke München GmbH", True), name_parts("STADTWERKE MUNCHEN", True))
        assert names_agree(name_parts("Bob J. Smith", False), name_parts("Robert Smyth", False))
        assert not names_agree(name_parts("Chukwuemeka Obi", False), name_parts("Emeka Okafor", False))
        assert not names_agree(name_parts("Markus Gerhard Mueller", False), name_parts("Mark Mueller", False))
        # Fewer than two real parts: the caller must not confirm or clear on name.
        assert len(name_parts("NA", False)) < 2
    years = ages_in_text("November 1998 saw Elvira Velasco Morillo, a 30-year-old, face charges.")
    assert years == [1967, 1968], years
    assert ages_in_text("November 1981 marked the date Pere Punti, then 37, was placed under charge.") == [1943, 1944]
    assert ages_in_text("Pere Punti reached 37 years of age by November 1981, the time he was charged.") == [1943, 1944]
    assert ages_in_text("Aged 45 at the time of the March 2019 report.") == [1973, 1974]
    assert ages_in_text("He was forty-five in March 2019.") == [1973, 1974]
    born = birth_dates_in_text("Christian Zaum was born on 30 June 1969.")
    assert [item.iso() for item in born] == ["1969-06-30"], born
    born = birth_dates_in_text("Martin Austin KAALUND was born in 1973.")
    assert [item.iso() for item in born] == ["1973"], born
    reports = dated_reports("According to the thenews.com.pk; January 08, 2020: In January 2020, Abdul Rahman was arrested.")
    assert reports and reports[0].iso() == "2020-01-08"
    note = "Verified via Veriff on 2023-09-15: passport from Spain, name ELVIRA VELASCO MORILLO, DOB 05/03/1968."
    parsed = parse_identity_note(note)
    assert parsed["name"] == "ELVIRA VELASCO MORILLO", parsed
    assert parsed["dob"].iso() == "1968-03-05"
    assert parsed["country"] == "Spain"
    assert parse_identity_note("Onfido could not verify the passport for JANE DOE, DOB 01/02/1990. The check failed.") is None
    assert parse_identity_note("Rejected Sumsub check: passport, name JANE DOE, DOB 01/02/1990.") is None
    june = parse_date("1962-06-10")
    september = parse_date("1962-09-10")
    assert same_year_risky(june, september, False)
    assert not same_year_risky(june, september, True)
    assert same_year_risky(parse_date("1985-01-03"), parse_date("1985-01-01"), True)
    assert same_year_risky(parse_date("1962-06-10"), parse_date("1962-10-06"), True)
    assert not same_year_risky(parse_date("1988-05-15"), parse_date("1988-05-17"), True)
    print("self-test ok")


def main():
    if len(sys.argv) == 2 and sys.argv[1] == "--self-test":
        self_test()
        return
    if len(sys.argv) != 3:
        sys.stderr.write("usage: system/run <data_dir> <output_file>\n")
        sys.exit(2)
    try:
        run(sys.argv[1], sys.argv[2])
    except Exception as error:
        sys.stderr.write(f"run error: {error}\n")
        hits = [row for row in read_jsonl(f"{sys.argv[1]}/hits.jsonl") if row.get("hit_id")]
        hits.sort(key=lambda row: row["hit_id"])
        answered = {hit["hit_id"]: _failsafe(hit) for hit in hits}
        _write_rows(sys.argv[2], hits, answered)


if __name__ == "__main__":
    main()
