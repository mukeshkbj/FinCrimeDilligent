#!/usr/bin/env python3
"""Optional typed model calls. Python standard library only.

Provider order, first key wins:

1. OPENROUTER_API_KEY -> https://openrouter.ai/api/v1
   Objections use the pinned id typesafe/jev-router.
   Reason wording uses the pinned id x-ai/grok-4.3.
2. XAI_API_KEY -> https://api.x.ai/v1 (OpenAI-compatible)
   The same typed question goes to the pinned id grok-4.3.
   That call is still not a free-form decision.
3. Neither key -> every function returns None and the rules stand.

The model may only object to a clearance. It cannot supply a birth year or
any other fact that would create DIFFERENT_ENTITY or SAME_ENTITY. An objection
is kept only when its confidence is at least 60/63 and its quote is copied
from the source. Anything lower, or any error, leaves the rules in place.

Calls use seed 1 (xAI rejects seed 0). Temperature is 0. Each call waits at
most 8 seconds. The whole run stops calling after 120 calls or 10 minutes,
whichever comes first, and the remaining hits stay on the rules. Successful
responses are cached by the hash of the request, under system/.llm-cache/,
which is gitignored. Failures are not cached. Keys are read from the
environment and are never written to disk or logged.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.request

CLEAR_CONFIDENCE = 60 / 63
CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".llm-cache")
# Pinned ids. Aliases such as grok-4 move when the provider ships a new model.
PINNED_JEV_MODEL = "typesafe/jev-router"
PINNED_GROK_MODEL = "x-ai/grok-4.3"
PINNED_XAI_MODEL = "grok-4.3"
CALL_TIMEOUT = 8
MAX_CALLS = 120
MAX_WALL_SECONDS = 10 * 60

_calls = 0
_wall = 0.0

def reset_budget():
    """Start a run's model clock. Called once from the engine, before any hit."""
    global _calls, _wall
    _calls = 0
    _wall = 0.0


def budget_open():
    return _calls < MAX_CALLS and _wall < MAX_WALL_SECONDS


def endpoint():
    """Return the active chat endpoint, or None when the run must stay on rules."""
    import dotenv
    dotenv.load_dotenv()
    openrouter = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if openrouter:
        return {
            "base": "https://openrouter.ai/api/v1",
            "key": openrouter,
            "provider": "openrouter",
            "typed_model": os.environ.get("JEV_MODEL", PINNED_JEV_MODEL),
            "reason_model": os.environ.get("GROK_MODEL", PINNED_GROK_MODEL),
        }
    xai = os.environ.get("XAI_API_KEY", "").strip()
    if xai:
        model = os.environ.get("XAI_MODEL", PINNED_XAI_MODEL)
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
    with urllib.request.urlopen(request, timeout=CALL_TIMEOUT) as response:
        return json.loads(response.read().decode("utf-8"))


def _charge(started):
    global _calls, _wall
    _calls += 1
    _wall += time.time() - started


def complete_json(kind, system, user):
    """Cached temperature-0 JSON completion. None when there is no key, no budget, or the call fails."""
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
    if not budget_open():
        return None
    # seed 1: xAI rejects 0. If a provider still rejects the field, retry once without it.
    body = {
        "model": model,
        "temperature": 0,
        "seed": 1,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    started = time.time()
    try:
        try:
            raw = _post(ep, body)
        except urllib.error.HTTPError as error:
            detail = ""
            try:
                detail = error.read().decode("utf-8", "replace")[:240].lower()
            except Exception:
                detail = ""
            if error.code == 400 and "seed" in detail:
                body.pop("seed", None)
                raw = _post(ep, body)
            else:
                _charge(started)
                return None
        content = raw["choices"][0]["message"]["content"]
        parsed = _extract_json(content)
    except (urllib.error.URLError, TimeoutError, KeyError, IndexError, TypeError, json.JSONDecodeError, ValueError):
        _charge(started)
        return None
    _charge(started)
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
    """Closed. Birth years come from the deterministic parser in the engine.

    A model year used to become a date of birth, and that date could clear a
    hit or confirm one. The model's own confidence number is not a fact.
    Returning None means a caller cannot turn a completion into DIFFERENT_ENTITY
    or SAME_ENTITY. Objections go through downgrade_clearance instead.
    """
    return None


def downgrade_clearance(profile_notes, reason):
    """Object to a clearance. Never returns a decision to clear. None means keep the rules."""
    text = profile_notes or ""
    if endpoint() is None or not text.strip():
        return None
    parsed = complete_json(
        "typed",
        (
            "You may only object to a clearance. Reply with JSON only: "
            '{"object": false, "quote": "", "confidence": 0}. '
            "Set object true only when the profile contradicts the clearance. "
            "quote must be copied verbatim from the profile. If unsure, object false."
        ),
        json.dumps({"profile": text[:2000], "clearance_reason": (reason or "")[:500]}, ensure_ascii=False),
    )
    if not parsed or not parsed.get("object"):
        return None
    confidence = _confidence(parsed)
    quote = parsed.get("quote") or ""
    if confidence is None or confidence < CLEAR_CONFIDENCE or not quote or quote not in text:
        return None
    return {"quote": quote}


def search_about(snippet, listing_phrase):
    """Whether a snippet is about this hit. The quote must occur verbatim in the snippet."""
    text = snippet or ""
    if endpoint() is None or not text.strip():
        return None
    parsed = complete_json(
        "typed",
        (
            "Decide if the snippet is about this listing. Reply with JSON only: "
            '{"about": false, "quote": "", "confidence": 0}. '
            "quote must be copied verbatim from the snippet. If unsure, about false."
        ),
        json.dumps({"snippet": text[:1500], "listing_phrase": listing_phrase}, ensure_ascii=False),
    )
    if not parsed:
        return None
    confidence = _confidence(parsed)
    quote = parsed.get("quote") or ""
    if confidence is None or confidence < CLEAR_CONFIDENCE or not quote or quote not in text:
        return None
    return {"about": bool(parsed.get("about")), "quote": quote}


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
