#!/usr/bin/env python3
"""Score the full engine against two weaker name matchers on the same data folder.

Writes ui/static/matchers.json for the desk panel. Stdlib only.
"""

from __future__ import annotations

import difflib
import importlib
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "system"))
sys.path.insert(0, str(ROOT))

import engine  # noqa: E402
import normalize  # noqa: E402

COST = {
    "DIFFERENT_ENTITY": {"DIFFERENT_ENTITY": 0, "SAME_ENTITY": 3, "REVIEW": 3},
    "SAME_ENTITY": {"DIFFERENT_ENTITY": 60, "SAME_ENTITY": 0, "REVIEW": 2},
    "REVIEW": {"DIFFERENT_ENTITY": 60, "SAME_ENTITY": 2, "REVIEW": 0},
}


def read_jsonl(path):
    with open(path, encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def plain_names_agree(left, right):
    if not left or not right:
        return False
    a = " ".join(sorted(left))
    b = " ".join(sorted(right))
    return difflib.SequenceMatcher(None, a, b).ratio() >= 0.85


def multilingual_off(customer_raw, hit_names, is_company):
    return False, False, ""


def score(answers, labels):
    cost = sum(
        COST[row["decision"]][answers.get(row["hit_id"], {}).get("decision", "REVIEW")]
        for row in labels
    )
    baseline = sum(COST[row["decision"]]["REVIEW"] for row in labels)
    right = sum(
        1 for row in labels if answers.get(row["hit_id"], {}).get("decision") == row["decision"]
    )
    unsafe = sum(
        1
        for row in labels
        if row["decision"] != "DIFFERENT_ENTITY"
        and answers.get(row["hit_id"], {}).get("decision") == "DIFFERENT_ENTITY"
    )
    score_value = 100 * max(0.0, 1 - cost / baseline) if baseline else 0.0
    return {
        "right": right,
        "labels": len(labels),
        "unsafe": unsafe,
        "decision_score": round(score_value, 1),
    }


def decisions_from(path):
    return {
        row["hit_id"]: row["decision"]
        for row in read_jsonl(path)
    }


def change_summary(full, other):
    changes = {}
    examples = []
    for hit_id, decision in full.items():
        got = other.get(hit_id)
        if got == decision:
            continue
        key = f"{decision}→{got}"
        changes[key] = changes.get(key, 0) + 1
        if decision != "DIFFERENT_ENTITY" and got == "DIFFERENT_ENTITY" and len(examples) < 3:
            examples.append(hit_id)
    return {
        "changed": sum(changes.values()),
        "by_transition": dict(sorted(changes.items())),
        "cleared_examples": examples,
    }


def run_matcher(data_dir, label, patch):
    originals = {}
    for name, replacement in patch.items():
        if name.startswith("normalize."):
            attr = name.split(".", 1)[1]
            originals[name] = getattr(normalize, attr)
            setattr(normalize, attr, replacement)
        else:
            originals[name] = getattr(engine, name)
            setattr(engine, name, replacement)
    # Name-part caches must not keep answers from another matcher.
    if hasattr(engine.name_parts, "cache_clear"):
        engine.name_parts.cache_clear()
    if hasattr(engine.levenshtein, "cache_clear"):
        engine.levenshtein.cache_clear()
    try:
        handle = tempfile.NamedTemporaryFile(
            prefix=f"matcher-{label}-", suffix=".jsonl", delete=False
        )
        path = handle.name
        handle.close()
        engine.run(data_dir, path)
        return path
    finally:
        for name, original in originals.items():
            if name.startswith("normalize."):
                setattr(normalize, name.split(".", 1)[1], original)
            else:
                setattr(engine, name, original)
        if hasattr(engine.name_parts, "cache_clear"):
            engine.name_parts.cache_clear()
        if hasattr(engine.levenshtein, "cache_clear"):
            engine.levenshtein.cache_clear()


def example_blurb(data_dir, hit_id, answers):
    hits = {row["hit_id"]: row for row in read_jsonl(os.path.join(data_dir, "hits.jsonl"))}
    hit = hits.get(hit_id) or {}
    row = answers.get(hit_id) or {}
    return {
        "hit_id": hit_id,
        "list_name": hit.get("name"),
        "decision": row.get("decision"),
        "reason_code": row.get("reason_code"),
        "reason": row.get("reason"),
    }


def main():
    data_dir = sys.argv[1] if len(sys.argv) > 1 else str(ROOT / "dev")
    out_path = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "ui" / "static" / "matchers.json"
    labels_path = os.path.join(data_dir, "practice_labels.jsonl")
    labels = read_jsonl(labels_path)

    configs = [
        ("full", {}),
        (
            "plain",
            {
                "names_agree": plain_names_agree,
                "multilingual_relation": multilingual_off,
            },
        ),
        (
            "novar",
            {
                "variants_match": lambda left, right: False,
                "normalize.skeleton_match": lambda left, right: False,
                "multilingual_relation": multilingual_off,
            },
        ),
    ]

    results = {}
    paths = {}
    for label, patch in configs:
        print(f"running {label}…", flush=True)
        paths[label] = run_matcher(data_dir, label, patch)

    full_decisions = decisions_from(paths["full"])
    full_answers = {row["hit_id"]: row for row in read_jsonl(paths["full"])}
    for label, _patch in configs:
        answers = {row["hit_id"]: row for row in read_jsonl(paths[label])}
        decisions = decisions_from(paths[label])
        scored = score(answers, labels)
        block = {
            "label": label,
            "title": {
                "full": "Our matcher",
                "plain": "Plain fuzzy matcher",
                "novar": "Without name variants",
            }[label],
            **scored,
        }
        if label != "full":
            block.update(change_summary(full_decisions, decisions))
            block["examples"] = [
                example_blurb(data_dir, hit_id, answers)
                for hit_id in block.get("cleared_examples") or []
            ]
        results[label] = block
        print(
            f"{label}: {scored['right']}/{scored['labels']} right, "
            f"{scored['unsafe']} unsafe, score {scored['decision_score']}",
            flush=True,
        )

    # Prefer the known demo examples when plain clears them.
    preferred = ["H-05C815", "H-060092"]
    plain_answers = {row["hit_id"]: row for row in read_jsonl(paths["plain"])}
    demo_examples = []
    for hit_id in preferred:
        if plain_answers.get(hit_id, {}).get("decision") == "DIFFERENT_ENTITY":
            if full_decisions.get(hit_id) != "DIFFERENT_ENTITY":
                demo_examples.append(example_blurb(data_dir, hit_id, plain_answers))
    if len(demo_examples) < 2:
        for hit_id in results["plain"].get("cleared_examples") or []:
            if hit_id in {item["hit_id"] for item in demo_examples}:
                continue
            demo_examples.append(example_blurb(data_dir, hit_id, plain_answers))
            if len(demo_examples) >= 2:
                break
    results["plain"]["demo_examples"] = demo_examples[:2]

    payload = {
        "note": (
            "The plain fuzzy matcher is one we built for comparison: "
            "whole-name similarity of 85% or more."
        ),
        "matchers": results,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {out_path}", flush=True)
    for path in paths.values():
        try:
            os.unlink(path)
            side = path[:-6] + ".verify.jsonl" if path.endswith(".jsonl") else path + ".verify.jsonl"
            if os.path.isfile(side):
                os.unlink(side)
        except OSError:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
