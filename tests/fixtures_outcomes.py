"""Synthetic rows for tests/test_outcomes.py (spec 0001 section 3.1, 3.5)."""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from snapshot.model import Benchmark, Submission

T0 = dt.datetime(2026, 3, 1, 0, 0, tzinfo=dt.timezone.utc)


def at(hours: float) -> dt.datetime:
    return T0 + dt.timedelta(hours=hours)


def sub(i, hours, score=None, promoted=False, status=None, cancelled=False,
        reason=None, metrics=None, bench="yukon/b", finished=None,
        promotion_status=None) -> Submission:
    """finished: hours offset for finished_at (None leaves finished_at unset)."""
    if status is None:
        status = "cancelled" if cancelled else ("accepted" if promoted else "rejected")
    return Submission(
        id=i, benchmark=bench, solver="alice", created_at=at(hours), status=status,
        promoted=promoted, cancelled=cancelled, score=score,
        metrics=metrics or {}, rejection_reason=reason,
        promotion_status=promotion_status,
        finished_at=None if finished is None else at(finished))


def meta(direction="lower", bips=None, slug="b", baseline=None, opened=None) -> Benchmark:
    return Benchmark(id="b1", name="yukon/b", slug=slug, direction=direction,
                     editable_paths=[], source_url="https://example.invalid",
                     opened_at=None if opened is None else at(opened),
                     min_improvement_bips=bips, baseline_score=baseline)


@dataclass(frozen=True)
class Row:
    """Minimal analysis row for jumps and pareto tests."""
    id: str
    created_at: dt.datetime
    promoted: bool = True
    gain_log: float | None = None
    score: float | None = None
    best_before: float | None = None
    metrics: dict = field(default_factory=dict)


def row(i, hours, gain=None, promoted=True, metrics=None, score=None, best_before=None) -> Row:
    return Row(i, at(hours), promoted, gain, score, best_before, metrics or {})


DENOM_CONFIG = {
    "default": ["never scored default"],
    "benchmarks": {"yukon/b": ["never scored specific"]},
    "failure_classes": {
        "ordinary failure": "evaluated",
        "rate limited": "infrastructure",
        "^validation job interrupted.*": "infrastructure",
        "unclear failure": "ambiguous",
    },
}
