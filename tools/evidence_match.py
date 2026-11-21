#!/usr/bin/env python3
"""Compare our evidence lists to the 50 practice labels (exact match + mean F1)."""

import argparse
import json
import sys


def read_jsonl(path):
    with open(path, encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def f1(ours, theirs):
    a = set(ours or [])
    b = set(theirs or [])
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    overlap = len(a & b)
    precision = overlap / len(a)
    recall = overlap / len(b)
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="output/dev.jsonl")
    parser.add_argument("--labels", default="dev/practice_labels.jsonl")
    args = parser.parse_args()
    answers = {row["hit_id"]: row for row in read_jsonl(args.output)}
    labels = read_jsonl(args.labels)
    exact = 0
    scores = []
    for label in labels:
        ours = answers.get(label["hit_id"], {}).get("evidence") or []
        theirs = label.get("evidence") or []
        if list(ours) == list(theirs):
            exact += 1
        scores.append(f1(ours, theirs))
    mean = sum(scores) / len(scores) if scores else 0.0
    print(f"evidence exact match: {exact}/{len(labels)}")
    print(f"evidence mean F1: {mean:.4f}")
    if exact == len(labels) and abs(mean - 1.0) < 1e-9:
        print("50/50 and 1.0")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
