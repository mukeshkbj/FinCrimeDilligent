#!/usr/bin/env python3
"""Run system/run five times and write ui/static/repro.json if the files match."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def file_hash(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main():
    data_dir = sys.argv[1] if len(sys.argv) > 1 else str(ROOT / "dev")
    out_path = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "ui" / "static" / "repro.json"
    run = ROOT / "system" / "run"
    hashes = []
    paths = []
    for index in range(5):
        handle = tempfile.NamedTemporaryFile(prefix=f"repro-{index}-", suffix=".jsonl", delete=False)
        handle.close()
        paths.append(handle.name)
        subprocess.check_call([str(run), data_dir, handle.name])
        hashes.append(file_hash(handle.name))
    identical = len(set(hashes)) == 1
    payload = {
        "runs": 5,
        "identical": identical,
        "hashes": hashes,
        "label": "5 of 5 runs identical" if identical else "runs differed",
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2))
    for path in paths:
        try:
            os.unlink(path)
            side = path[:-6] + ".verify.jsonl" if path.endswith(".jsonl") else path + ".verify.jsonl"
            if os.path.isfile(side):
                os.unlink(side)
        except OSError:
            pass
    return 0 if identical else 1


if __name__ == "__main__":
    raise SystemExit(main())
