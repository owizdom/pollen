"""Pareto-frontier gain for ecdsa.fail (qubits, toffoli), both minimised."""
from __future__ import annotations

from ._order import eval_time


def _point(row):
    m = row.metrics or {}
    q, t = m.get("qubits"), m.get("toffoli")
    if q is None or t is None:
        return None
    return (q, t)


def _blocks(a, b) -> bool:
    """Earlier point a blocks b if it dominates b or is identical to it."""
    return a[0] <= b[0] and a[1] <= b[1]


def pareto_gain(rows) -> list[bool]:
    order = sorted(range(len(rows)), key=lambda i: (eval_time(rows[i]), i))
    out = [False] * len(rows)
    seen: list[tuple] = []
    k = 0
    while k < len(order):
        j = k
        while j < len(order) and eval_time(rows[order[j]]) == eval_time(rows[order[k]]):
            j += 1
        group = order[k:j]
        pts = {}
        for i in group:
            p = _point(rows[i])
            pts[i] = p
            out[i] = p is not None and not any(_blocks(e, p) for e in seen)
        seen.extend(p for p in pts.values() if p is not None)
        k = j
    return out
