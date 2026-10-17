"""Synthetic rows for tests/test_outcomes.py (spec 0001 section 3.1, 3.5)."""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from snapshot.model import Benchmark, Submission

T0 = dt.datetime(2026, 3, 1, 0, 0, tzinfo=dt.timezone.utc)


def at(hours: float) -> dt.datetime:
    return T0 + dt.timedelta(hours=hours)


def sub(i, hours, score=None, promoted=False, status=None, cancelled=False,
        reason=None, metrics=None, bench="yukon/b") -> Submission:
    if status is None:
        status = "cancelled" if cancelled else ("accepted" if promoted else "rejected")
    return Submission(
        id=i, benchmark=bench, solver="alice", created_at=at(hours), status=status,
        promoted=promoted, cancelled=cancelled, score=score,
        metrics=metrics or {}, rejection_reason=reason)


def meta(direction="lower", bips=None, slug="b") -> Benchmark:
    return Benchmark(id="b1", name="yukon/b", slug=slug, direction=direction,
                     editable_paths=[], source_url="https://example.invalid",
                     opened_at=None, min_improvement_bips=bips)


@dataclass(frozen=True)
class Row:
    """Minimal analysis row for jumps and pareto tests."""
    id: str
    created_at: dt.datetime
    promoted: bool = True
    gain_log: float | None = None
    metrics: dict = field(default_factory=dict)


def row(i, hours, gain=None, promoted=True, metrics=None) -> Row:
    return Row(i, at(hours), promoted, gain, metrics or {})


DENOM_CONFIG = {
    "default": ["never scored default"],
    "benchmarks": {"yukon/b": ["never scored specific"]},
}
