"""Load a local .env file. Never overrides existing variables and never prints values."""

from __future__ import annotations

import os
from pathlib import Path


def load_dotenv(path=None):
    """Read KEY=VALUE lines into os.environ.

    Existing variables win. Blank lines and comments are skipped.
    Missing files are ignored. Values are never logged.
    """
    if path is None:
        path = Path(__file__).resolve().parents[1] / ".env"
    else:
        path = Path(path)
    if not path.is_file():
        return
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or key in os.environ:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ[key] = value
