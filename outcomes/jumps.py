"""Large jumps and plateau breaks (spec 0001 section 3.5)."""
from __future__ import annotations

import datetime as dt
import math


def _gained(rows):
    return [r for r in rows if r.promoted and r.gain_log is not None]


def large_jumps(rows) -> list:
    """Top decile (ceil(n/10)) of promoted rows by gain_log, largest first."""
    g = _gained(rows)
    if not g:
        return []
    n = math.ceil(len(g) / 10)
    return sorted(g, key=lambda r: r.gain_log, reverse=True)[:n]


def plateau_breaks(rows, hours=72, threshold=0.01) -> list:
    """Rows with gain >= threshold and no earlier gain >= threshold within `hours`.

    The first qualifying row has no preceding window and is not flagged.
    """
    big = sorted((r for r in _gained(rows) if r.gain_log >= threshold),
                 key=lambda r: r.created_at)
    window = dt.timedelta(hours=hours)
    out = []
    for k in range(1, len(big)):
        if big[k].created_at - big[k - 1].created_at >= window:
            out.append(big[k])
    return out
