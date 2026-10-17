"""Y1 and its recomputation from the running best score (spec 0001 section 3.5)."""
from __future__ import annotations

from ._order import eval_order

NOT_REPRODUCED_SHARE = 0.01


def y1(sub) -> bool:
    return bool(sub.promoted)


def recompute(subs, meta) -> list[bool]:
    """Y1 recomputed in evaluation order from the baseline-seeded running best."""
    lower = meta.direction == "lower"
    bips = meta.min_improvement_bips or 0
    seed = getattr(meta, "baseline_score", None)
    best = seed if seed is not None else (float("inf") if lower else float("-inf"))
    unbounded = seed is None
    out = [False] * len(subs)
    for i in eval_order(subs):
        score = subs[i].score
        if score is None:
            continue
        if unbounded:
            ok = score < best if lower else score > best
        elif lower:
            ok = score < best and score <= best * (1 - bips / 10000)
        else:
            ok = score > best and score >= best * (1 + bips / 10000)
        if ok:
            out[i] = True
            best = score
            unbounded = False
    return out


def exception_ids(subs, explicit=()) -> set:
    """Named exceptions: explicit ids and superseded rows."""
    ids = set(explicit)
    ids.update(s.id for s in subs if getattr(s, "promotion_status", None) == "superseded")
    return ids


def recompute_excluding(subs, meta, exceptions=()) -> list:
    """recompute() with exception rows removed from the series; None for them."""
    skip = exception_ids(subs, exceptions)
    kept = [s for s in subs if s.id not in skip]
    rec = iter(recompute(kept, meta))
    return [None if s.id in skip else next(rec) for s in subs]


def disagreements(subs, meta, exceptions=()) -> list[str]:
    """Ids whose recomputed value differs from sub.promoted.

    Named exceptions (given ids and superseded rows) are removed from the
    series first, so they cannot raise the running best for later rows.
    """
    rec = recompute_excluding(subs, meta, exceptions)
    return [s.id for s, r in zip(subs, rec) if r is not None and r != s.promoted]


def at5_report(items) -> dict:
    """items: {name: (analysis_rows, meta)}. Counts and the not-reproduced list only."""
    counts = {}
    not_reproduced = []
    for name, (rows, meta) in items.items():
        exc = {s.id for s in rows if s.status == "accepted" and not s.promoted}
        exc |= exception_ids(rows)
        dis = disagreements(rows, meta, exc)
        counts[name] = {"rows": len(rows), "disagreements": len(dis),
                        "exceptions": len(exc)}
        if rows and len(dis) / len(rows) > NOT_REPRODUCED_SHARE:
            not_reproduced.append(name)
    return {"counts": counts, "not_reproduced": not_reproduced}
