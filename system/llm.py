#!/usr/bin/env python3
"""Optional typed model calls. Python standard library only.

Provider order, first key wins:

1. OPENROUTER_API_KEY -> https://openrouter.ai/api/v1
   Typed questions use typesafe/jev-router. Reasons use x-ai/grok-4.
2. XAI_API_KEY -> https://api.x.ai/v1 (OpenAI-compatible)
   Jev is not hosted here, so the same typed JSON question goes to grok-4.
   That call is still not a free-form decision.
3. Neither key -> every function returns None and the rules stand.

A birth year or a rewritten reason is kept only when the model's confidence
is at least 60/63 (about 95%). Anything lower, or any error, is ignored.
Successful responses are cached by the hash of the request, under
system/.llm-cache/, which is gitignored. Keys are read from the environment
and are never written to disk.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.error
import urllib.request

CLEAR_CONFIDENCE = 60 / 63
CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".llm-cache")

_AGEISH = re.compile(r"year-old|years old|aged\s+\d|age of\s+\d|\bwas\s+\d{1,2}\b", re.I)


def endpoint():
    """Return the active chat endpoint, or None when the run must stay on rules."""
    openrouter = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if openrouter:
        return {
            "base": "https://openrouter.ai/api/v1",
            "key": openrouter,
            "provider": "openrouter",
            "typed_model": os.environ.get("JEV_MODEL", "typesafe/jev-router"),
            "reason_model": os.environ.get("GROK_MODEL", "x-ai/grok-4"),
        }
    xai = os.environ.get("XAI_API_KEY", "").strip()
    if xai:
        model = os.environ.get("XAI_MODEL", "grok-4")
        return {
            "base": "https://api.x.ai/v1",
            "key": xai,
            "provider": "xai",
            "typed_model": model,
            "reason_model": model,
        }
    return None


def _cache_file(digest):
    return os.path.join(CACHE_DIR, digest + ".json")


def _read_cache(digest):
    path = _cache_file(digest)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None
    if isinstance(payload, dict) and "parsed" in payload:
        return payload["parsed"]
    return None


def _write_cache(digest, parsed):
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = _cache_file(digest)
    temporary = path + ".tmp"
    with open(temporary, "w", encoding="utf-8") as handle:
        json.dump({"parsed": parsed}, handle, ensure_ascii=False, sort_keys=True)
    os.replace(temporary, path)


def _extract_json(text):
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.S)
        if not match:
            return None
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return None


def _post(ep, body):
    request = urllib.request.Request(
        ep["base"].rstrip("/") + "/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": "Bearer " + ep["key"],
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=25) as response:
        return json.loads(response.read().decode("utf-8"))


def complete_json(kind, system, user):
    """Cached temperature-0 JSON completion. None when there is no key or the call fails."""
    ep = endpoint()
    if ep is None:
        return None
    model = ep["typed_model"] if kind == "typed" else ep["reason_model"]
    material = json.dumps(
        {
            "provider": ep["provider"],
            "model": model,
            "system": system,
            "user": user,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()
    cached = _read_cache(digest)
    if cached is not None:
        return cached
    body = {
        "model": model,
        "temperature": 0,
        "seed": 0,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    try:
        raw = _post(ep, body)
        content = raw["choices"][0]["message"]["content"]
        parsed = _extract_json(content)
    except (urllib.error.URLError, TimeoutError, KeyError, IndexError, TypeError, json.JSONDecodeError, ValueError):
        return None
    if not isinstance(parsed, dict):
        return None
    _write_cache(digest, parsed)
    return parsed


def _confidence(parsed):
    try:
        value = float(parsed.get("confidence"))
    except (AttributeError, TypeError, ValueError):
        return None
    if value > 1:
        value = value / 100.0
    if value < 0 or value > 1:
        return None
    return value


def birth_years(text):
    """Two possible birth years from an age-at-a-date sentence the rules did not parse.

    Returns a sorted list of years, or None. None leaves the deterministic
    path unchanged. A low-confidence answer is not used to clear a hit.
    """
    if not text or not _AGEISH.search(text):
        return None
    if endpoint() is None:
        return None
    parsed = complete_json(
        "typed",
        (
            "You extract birth years. Reply with JSON only: "
            '{"birth_years": [<int>, <int>], "confidence": <0 to 1>}. '
            "If the text gives a person's age at a date, birth_years must be "
            "year-age and year-age-1. If it does not, return an empty list and "
            "confidence 0. Do not decide whether two people are the same."
        ),
        text[:2000],
    )
    if not parsed:
        return None
    confidence = _confidence(parsed)
    if confidence is None or confidence < CLEAR_CONFIDENCE:
        return None
    years = []
    for item in parsed.get("birth_years") or []:
        try:
            year = int(item)
        except (TypeError, ValueError):
            continue
        if 1800 < year < 2100 and year not in years:
            years.append(year)
    if not years:
        return None
    return sorted(years)


def polish_reason(reason, decision, reason_code, hit_name):
    """Rephrase a finished reason. Never changes the decision. Off unless asked."""
    if os.environ.get("RESOLVE_POLISH_REASONS", "").strip() != "1":
        return None
    if endpoint() is None or not reason:
        return None
    parsed = complete_json(
        "reason",
        (
            "Rewrite the reason in 2 to 4 sentences. Keep every fact, name, date, "
            "country, and record id. Do not add facts and do not change the decision. "
            'Reply with JSON only: {"reason": "...", "confidence": <0 to 1>}.'
        ),
        json.dumps(
            {
                "decision": decision,
                "reason_code": reason_code,
                "hit_name": hit_name,
                "reason": reason,
            },
            ensure_ascii=False,
            sort_keys=True,
        ),
    )
    if not parsed:
        return None
    confidence = _confidence(parsed)
    text = parsed.get("reason")
    if confidence is None or confidence < CLEAR_CONFIDENCE or not isinstance(text, str):
        return None
    sentences = [part for part in text.split(".") if part.strip()]
    if not 2 <= len(sentences) <= 4:
        return None
    return text.strip()
