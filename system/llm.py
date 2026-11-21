#!/usr/bin/env python3
"""Grok writes the reason wording. Python standard library only.

Provider order, first key wins:

1. OPENROUTER_API_KEY -> https://openrouter.ai/api/v1, pinned id x-ai/grok-4.3
2. XAI_API_KEY -> https://api.x.ai/v1, pinned id grok-4.3
3. Neither key -> every function returns None and the template reason stands.

The model never changes the decision, the reason code or the customer record.
It only rewrites the reason text. A rewrite is kept only when it has 2 to 4
sentences, keeps every record id the template cites, and adds no id, date or
number that the template does not already contain. Anything else keeps the
template.

Calls use seed 1 (xAI rejects seed 0). Temperature is 0. Each call waits at
most 8 seconds. A run stops calling after 120 calls or 10 minutes. Successful
responses are cached by the hash of the request, under system/.llm-cache/,
which is gitignored. Failures are not cached. Keys are read from the
environment and are never written to disk or logged.

Set RESOLVE_POLISH_REASONS=0 to keep the template wording.
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
PINNED_GROK_MODEL = "x-ai/grok-4.3"
PINNED_XAI_MODEL = "grok-4.3"
CALL_TIMEOUT = 8
MAX_CALLS = 120
MAX_WALL_SECONDS = 10 * 60
# Record ids such as NOTE-23FC8E or SR-01BFC3, and dates or numbers such as 1977-01-11.
FACT_PATTERN = re.compile(r"[A-Za-z]+-[A-Za-z0-9]+|\d+(?:[-/.]\d+)*")
ID_PATTERN = re.compile(r"\b[A-Za-z]+-[A-Za-z0-9]+\b")

_calls = 0
_wall = 0.0


def reset_budget() -> None:
    """Start a run's model clock. Called once from the engine, before any hit."""
    global _calls, _wall
    _calls = 0
    _wall = 0.0


def budget_open() -> bool:
    return _calls < MAX_CALLS and _wall < MAX_WALL_SECONDS


def endpoint() -> dict | None:
    """Return the Grok endpoint, or None when the run must use the template reasons."""
    import dotenv

    dotenv.load_dotenv()
    model_override = os.environ.get("GROK_MODEL", "").strip()
    openrouter = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if openrouter:
        return {
            "base": "https://openrouter.ai/api/v1",
            "key": openrouter,
            "provider": "openrouter",
            "model": model_override or PINNED_GROK_MODEL,
        }
    xai = os.environ.get("XAI_API_KEY", "").strip()
    if xai:
        return {
            "base": "https://api.x.ai/v1",
            "key": xai,
            "provider": "xai",
            "model": os.environ.get("XAI_MODEL", "").strip() or PINNED_XAI_MODEL,
        }
    return None


def _cache_file(digest: str) -> str:
    return os.path.join(CACHE_DIR, digest + ".json")


def _read_cache(digest: str) -> dict | None:
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


def _write_cache(digest: str, parsed: dict) -> None:
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = _cache_file(digest)
    temporary = path + ".tmp"
    with open(temporary, "w", encoding="utf-8") as handle:
        json.dump({"parsed": parsed}, handle, ensure_ascii=False, sort_keys=True)
    os.replace(temporary, path)


def _extract_json(text: str | None) -> dict | None:
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


def _post(ep: dict, body: dict) -> dict:
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


def _charge(started: float) -> None:
    global _calls, _wall
    _calls += 1
    _wall += time.time() - started


def complete_json(system: str, user: str) -> dict | None:
    """Cached temperature-0 JSON completion. None when there is no key, no budget, or the call fails."""
    ep = endpoint()
    if ep is None:
        return None
    material = json.dumps(
        {"provider": ep["provider"], "model": ep["model"], "system": system, "user": user},
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
        "model": ep["model"],
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


def _confidence(parsed: dict) -> float | None:
    try:
        value = float(parsed.get("confidence"))
    except (AttributeError, TypeError, ValueError):
        return None
    if value > 1:
        value = value / 100.0
    if value < 0 or value > 1:
        return None
    return value


def facts_in(text: str | None) -> set[str]:
    """Record ids, dates and numbers in a text. The reply may not add any the template lacks."""
    return set(FACT_PATTERN.findall(text or ""))


def polish_reason(reason: str | None, decision: str | None, reason_code: str | None, hit_name: str | None) -> str | None:
    """Grok writes the reason wording, checked against the template. Never changes the decision.

    Returns None, so the caller keeps the template, unless every check passes.
    """
    if os.environ.get("RESOLVE_POLISH_REASONS", "").strip() == "0":
        return None
    if not reason or endpoint() is None:
        return None
    parsed = complete_json(
        (
            "Rewrite the reason in 2 to 4 sentences. Keep every record id, name, date, "
            "country and number. Do not add facts and do not change the decision. "
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
    if not facts_in(text) <= facts_in(reason):
        return None
    if not set(ID_PATTERN.findall(reason)) <= facts_in(text):
        return None
    return text.strip()
