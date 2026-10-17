"""Confirmatory window start (spec 3.1): first week after which tree availability balances."""
from __future__ import annotations

import datetime as dt
from collections import defaultdict

TOL = 0.05


def start(rows, has_tree) -> dt.datetime | None:
    """First calendar (Monday) week such that, from it through the end, the share of rows
    with a recoverable tree differs by at most 5 points between promoted and other rows."""
    weeks = defaultdict(lambda: [0, 0, 0, 0])  # prom_n, prom_tree, oth_n, oth_tree
    for s in rows:
        d = s.created_at.astimezone(dt.timezone.utc).date()
        w = d - dt.timedelta(days=d.weekday())
        c = weeks[w]
        i = 0 if s.promoted else 2
        c[i] += 1
        c[i + 1] += s.id in has_tree
    tot = [0, 0, 0, 0]
    good = None
    for w in sorted(weeks, reverse=True):
        tot = [a + b for a, b in zip(tot, weeks[w])]
        if tot[0] and tot[2] and abs(tot[1] / tot[0] - tot[3] / tot[2]) <= TOL:
            good = w
    # the earliest week whose suffix balances; later weeks need not stay balanced
    return None if good is None else dt.datetime.combine(good, dt.time(), dt.timezone.utc)
