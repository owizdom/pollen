"""Running frontier and log gain (spec 0001 section 3.5)."""
from __future__ import annotations

import math

from ._order import eval_order, eval_time


def best_before(subs, meta) -> list:
    """Best promoted score among rows that finished strictly earlier.

    Seeded with meta.baseline_score when set.
    """
    lower = meta.direction == "lower"
    order = eval_order(subs)
    out = [None] * len(subs)
    best = getattr(meta, "baseline_score", None)
    k = 0
    while k < len(order):
        j = k
        t = eval_time(subs[order[k]])
        while j < len(order) and eval_time(subs[order[j]]) == t:
            j += 1
        for i in order[k:j]:
            out[i] = best
        for i in order[k:j]:
            s = subs[i]
            if s.promoted and s.score is not None:
                if best is None or (s.score < best if lower else s.score > best):
                    best = s.score
        k = j
    return out


def gain_log(sub, best_before, meta):
    """Log improvement of a promoted row over the prior best; larger is better."""
    if not sub.promoted or best_before is None or sub.score is None:
        return None
    if sub.score <= 0 or best_before <= 0:
        return None
    if meta.direction == "lower":
        return math.log(best_before / sub.score)
    return math.log(sub.score / best_before)
