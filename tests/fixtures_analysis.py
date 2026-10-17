"""Synthetic rows for tests/test_dataset.py and tests/test_lock.py (spec 0001 section 3, 5.3, 5.8).

Blinding: nothing here carries real data or joins outcomes to treatment. Parents come from a
hand-written lineage parents.json.gz in the layout lineage.build.run writes.
"""
from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd

from lineage import trees as trees_mod
from snapshot.model import Benchmark, Submission

BENCH = "yukon/pollen-test"
SLUG = "pollen-test"
T0 = dt.datetime(2026, 3, 2, 0, 0, tzinfo=dt.timezone.utc)  # a Monday

GPT = "GPT-5 Codex"                       # OpenAI
CLAUDE = "Claude Opus 4.8 (1M context)"   # Anthropic
KIMI = "Kimi K3"                          # Moonshot
DEVIN = "Devin"                           # Unknown
MULTI = "GPT 5.6 Sol, GPT 6 Luna and Claude Opus 5.5"  # Multi

NEVER_EVALUATED = "claimed score did not improve current best"


def at(hours: float) -> dt.datetime:
    return T0 + dt.timedelta(hours=hours)


def sub(i, hours, solver="alice", model=GPT, *, status="rejected", promoted=False,
        score=None, cancelled=False, reason=None, finished=None,
        created=None) -> Submission:
    """created overrides the hour offset with an absolute datetime."""
    if promoted:
        status = "accepted"
    if cancelled:
        status = "cancelled"
    return Submission(
        id=i, benchmark=BENCH, solver=solver,
        created_at=created if created is not None else at(hours),
        status=status, promoted=promoted, cancelled=cancelled, score=score,
        metrics={}, note=f"Model: {model}\nbody" if model else "body",
        model_line=model, rejection_reason=reason,
        promotion_status="promoted" if promoted else None,
        finished_at=None if finished is None else at(finished))


def meta(direction="lower") -> Benchmark:
    return Benchmark(id="b1", name=BENCH, slug=SLUG, direction=direction,
                     editable_paths=["src/"], source_url="https://example.invalid",
                     opened_at=at(0), min_improvement_bips=None, baseline_score=None)


class StubSnapshot:
    """Stands in for the snapshot package: load, benchmark_meta, attribution."""

    def __init__(self, subs, benchmark_meta=None, attribution=None):
        self._subs = list(subs)
        self._meta = benchmark_meta or meta()
        self._attr = attribution or {}

    def load(self, benchmark):
        return list(self._subs)

    def benchmark_meta(self, benchmark):
        return self._meta

    def attribution(self, benchmark):
        return dict(self._attr)


def link(ids=(), method="none", distance=None, child_side=None):
    return [list(ids), method, distance, child_side]


def declared(*ids):
    return link(ids, "declared" if len(ids) == 1 else "multi")


def write_parents(lineage_root, mapping, slug=SLUG):
    """mapping: id -> primary link (see link()) or (primary, tree) pair.

    Writes <lineage_root>/<slug>/parents.json.gz in lineage.build.run's layout and returns
    lineage_root. Ids absent from the mapping get method "none".
    """
    out = {}
    for sid, val in mapping.items():
        primary, tree = val if isinstance(val, tuple) else (val, link())
        out[sid] = {"primary": primary, "tree": tree, "dropped": []}
    trees_mod._gz(lineage_root / slug / "parents.json.gz", out)
    return lineage_root


def cells_frame(n_solvers, rows_per, p_cross=0.5, purity=0.9, seed=0) -> pd.DataFrame:
    """Treatment-only frame (no outcomes) for power tests: solver, cross_family, cell.

    Each solver leans one way (purity share of its rows in its preferred arm), so
    clustering matters.
    """
    rng = np.random.default_rng(seed)
    rows = []
    for s in range(n_solvers):
        lean = rng.random() < p_cross
        for _ in range(rows_per):
            cf = bool(lean if rng.random() < purity else not lean)
            rows.append({"solver": f"s{s}", "cross_family": cf,
                         "cell": "other_switch" if cf else "other_same"})
    return pd.DataFrame(rows)


FAKE_TREE = {
    "docs/prereg.md": "prereg text\n",
    "analysis/__init__.py": "",
    "analysis/dataset.py": "x = 1\n",
    "analysis/sub/deep.py": "y = 2\n",
    "lineage/parents.py": "z = 3\n",
    "lineage/cache/blob.bin": "cache bytes\n",
    "lineage/frozen/SHA256SUMS": "abc  slug/parents.json.gz\n",
    "lineage/frozen/slug/parents.json.gz": "frozen data\n",
    "families/table.yaml": "strings: {}\n",
    "outcomes/denominator.yaml": "default: []\n",
    "snapshot/raw/SHA256SUMS": "def  file\n",
}
HASHED = ["docs/prereg.md", "analysis/__init__.py", "analysis/dataset.py",
          "analysis/sub/deep.py", "lineage/parents.py", "lineage/frozen/SHA256SUMS",
          "families/table.yaml", "outcomes/denominator.yaml", "snapshot/raw/SHA256SUMS"]
NOT_HASHED = ["lineage/cache/blob.bin", "lineage/frozen/slug/parents.json.gz"]
