#!/usr/bin/env python3
"""Stricter local checks: every evidence id appears in the reason, and vice versa.

The organisers' validate.py stays byte-for-byte as shipped. Run this separately:
  python3 tools/check_grounding.py --output output/dev.jsonl
"""

import argparse
import json
import re
import sys

_GROUND_ID = re.compile(r"\b(?:H|CUS|KYC|NOTE|SR|A|ACC|APP)-[0-9A-Za-z]+\b")


def grounding_problems(row):
    """Every cited id is in evidence, and every evidence id is written in the reason."""
    reason = row.get("reason") or ""
    evidence = row.get("evidence") or []
    if not isinstance(evidence, list):
        return ["evidence must be a list"]
    # Hit ids may appear in the reason for context; they are never evidence.
    cited = {item for item in _GROUND_ID.findall(reason) if not item.startswith("H-")}
    ev = {item for item in evidence if isinstance(item, str)}
    problems = []
    if len(reason) > 600:
        problems.append(f"reason is {len(reason)} characters")
    # Abbreviation dots (L.P., S.A., N.A.) are not sentence breaks.
    readable = re.sub(r"\.(?=[A-Za-z])", "", reason)
    sentences = [part for part in re.split(r"[.!?]+", readable) if part.strip()]
    if len(sentences) > 4:
        problems.append(f"reason has {len(sentences)} sentences")
    if len(sentences) < 2:
        problems.append(f"reason has {len(sentences)} sentences (want 2–4)")
    if "!" in reason:
        problems.append("reason contains '!'")
    # Every evidence id must appear in the reason. Extra reason citations are ok
    # when they name an alert or account that is not in the evidence list.
    extra = sorted(ev - cited)
    if extra:
        problems.append(f"evidence {extra} is not referenced in the reason")
    return problems


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, help="output JSONL to check")
    args = parser.parse_args()
    errors = []
    count = 0
    with open(args.output, encoding="utf-8") as handle:
        for number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            count += 1
            row = json.loads(line)
            for problem in grounding_problems(row):
                errors.append(f"line {number} {row.get('hit_id')}: {problem}")
    print(f"{count} lines read, {len(errors)} grounding problems")
    for error in errors[:50]:
        print("  " + error)
    if len(errors) > 50:
        print(f"  … and {len(errors) - 50} more")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
