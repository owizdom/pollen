"""Large jumps and plateau breaks (spec 0001 section 3.5)."""
from __future__ import annotations

import datetime as dt
import math

from ._order import eval_time

_EPS = 1e-12


def _gained(rows):
    return [r for r in rows if r.promoted and r.gain_log is not None]


def large_jumps(rows) -> list:
    """Top decile (ceil(n/10)) of promoted rows by gain_log, largest first."""
    g = _gained(rows)
    if not g:
        return []
    n = math.ceil(len(g) / 10)
    return sorted(g, key=lambda r: r.gain_log, reverse=True)[:n]


def _gains_enough(row, threshold, direction) -> bool:
    if not row.promoted or row.score is None or row.best_before is None:
        return False
    if direction == "lower":
        return row.score <= row.best_before * (1 - threshold) * (1 + _EPS)
    return row.score >= row.best_before * (1 + threshold) * (1 - _EPS)


def plateau_breaks(rows, hours=72, threshold=0.01, opened_at=None, direction="lower") -> list:
    """Promotions gaining >= threshold (relative) after at least `hours` with no
    such promotion. The window starts at opened_at; without it the first
    qualifying promotion has no window and is not flagged.
    """
    q = sorted((r for r in rows if _gains_enough(r, threshold, direction)),
               key=eval_time)
    window = dt.timedelta(hours=hours)
    out = []
    prev = opened_at
    for r in q:
        if prev is not None and eval_time(r) - prev >= window:
            out.append(r)
        prev = eval_time(r)
    return out
