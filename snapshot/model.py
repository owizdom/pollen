"""Typed rows for the frozen snapshot (spec 0001 section 8)."""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Literal


@dataclass(frozen=True)
class Submission:
    id: str
    benchmark: str
    solver: str | None
    created_at: dt.datetime
    status: str
    promoted: bool
    cancelled: bool
    score: float | None
    metrics: dict = field(default_factory=dict)
    note: str = ""
    model_line: str | None = None
    commit_sha: str | None = None
    rejection_reason: str | None = None
    submission_sha: str | None = None
    promoted_ref: str | None = None


@dataclass(frozen=True)
class Benchmark:
    id: str
    name: str
    slug: str
    direction: Literal["lower", "higher"]
    editable_paths: list
    source_url: str
    opened_at: dt.datetime | None
    min_improvement_bips: int | None
