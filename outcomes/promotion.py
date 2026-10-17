"""Y1 and its recomputation from the running best score (spec 0001 section 3.5)."""
from __future__ import annotations


def y1(sub) -> bool:
    return bool(sub.promoted)


def recompute(subs, meta) -> list[bool]:
    lower = meta.direction == "lower"
    bips = meta.min_improvement_bips or 0
    best = float("inf") if lower else float("-inf")
    out = [False] * len(subs)
    order = sorted(range(len(subs)), key=lambda i: (subs[i].created_at, i))
    for i in order:
        score = subs[i].score
        if score is None:
            continue
        if best in (float("inf"), float("-inf")):
            ok = score < best if lower else score > best
        elif lower:
            ok = score < best and score <= best * (1 - bips / 10000)
        else:
            ok = score > best and score >= best * (1 + bips / 10000)
        if ok:
            out[i] = True
            best = score
    return out


def disagreements(subs, meta, exceptions=()) -> list[str]:
    """Ids whose recomputed value differs from sub.promoted.

    Named exceptions are removed from the series first, so a known
    accepted-but-failed row cannot raise the running best for later rows.
    """
    skip = set(exceptions)
    kept = [s for s in subs if s.id not in skip]
    rec = recompute(kept, meta)
    return [s.id for s, r in zip(kept, rec) if r != s.promoted]
