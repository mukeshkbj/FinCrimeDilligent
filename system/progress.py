"""Stdlib progress bar (tqdm-like). No third-party deps — brief is stdlib only."""

from __future__ import annotations

import sys
import time


def log(message: str, file=None) -> None:
    file = file or sys.stderr
    file.write(f"{message}\n")
    file.flush()


def progress(iterable, total=None, desc="", unit="it", file=None, mininterval=0.1):
    """Yield items while drawing a one-line progress bar on stderr."""
    file = file or sys.stderr
    if total is None:
        try:
            total = len(iterable)
        except TypeError:
            total = None
    started = time.time()
    last_draw = 0.0
    done = 0
    width = 28

    def draw(force=False):
        nonlocal last_draw
        now = time.time()
        if not force and (now - last_draw) < mininterval and (total is None or done < total):
            return
        last_draw = now
        elapsed = max(now - started, 1e-6)
        rate = done / elapsed
        if total and total > 0:
            frac = min(done / total, 1.0)
            filled = int(width * frac)
            bar = "#" * filled + "-" * (width - filled)
            eta = (total - done) / rate if rate > 0 and done < total else 0.0
            line = (
                f"\r{desc + ': ' if desc else ''}"
                f"|{bar}| {done}/{total} {unit} "
                f"{frac:6.1%} {rate:6.1f}{unit}/s ETA {eta:5.1f}s"
            )
        else:
            line = (
                f"\r{desc + ': ' if desc else ''}"
                f"{done} {unit} {rate:6.1f}{unit}/s {elapsed:5.1f}s"
            )
        file.write(line)
        file.flush()

    for item in iterable:
        yield item
        done += 1
        draw(force=(total is not None and done >= total))
    if total is None or done != total:
        draw(force=True)
    file.write("\n")
    file.flush()
