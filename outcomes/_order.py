"""Evaluation order (spec 0001 section 3.5): finished_at, else created_at."""
from __future__ import annotations


def eval_time(sub):
    return getattr(sub, "finished_at", None) or sub.created_at


def eval_order(subs) -> list[int]:
    return sorted(range(len(subs)), key=lambda i: (eval_time(subs[i]), subs[i].created_at, i))
