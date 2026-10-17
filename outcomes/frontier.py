"""Running frontier and log gain (spec 0001 section 3.5)."""
from __future__ import annotations

import math


def best_before(subs, meta) -> list:
    """Best score among promoted rows strictly earlier by created_at."""
    lower = meta.direction == "lower"
    order = sorted(range(len(subs)), key=lambda i: (subs[i].created_at, i))
    out = [None] * len(subs)
    best = None
    k = 0
    while k < len(order):
        j = k
        while j < len(order) and subs[order[j]].created_at == subs[order[k]].created_at:
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
