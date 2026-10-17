"""Study benchmarks (spec 0001 section 5.6) and the shared plumbing of the E3 drivers.

Every function here is called only after lock.check has passed in the calling driver.
"""
from __future__ import annotations

import contextlib
import gzip
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from analysis import dataset, lock
from families import mapper
from lineage.build import tree_sha
from lineage.window import start as window_start
import outcomes
from outcomes import denominator

ECDSA = "gpsanant/ecdsafail-challenge"
DEFAULT_MARGIN = (0.80, 1.25)
MIN_ROWS, MIN_PROMOTED, MIN_SHARE_PCT, MIN_FETCHABLE_PCT = 500, 100, 10, 50
_KNOWN = ("Unknown", "Multi", None)


# ------------------------------------------------------------------ snapshot bound to a root

class RootSnapshot:
    """The snapshot package bound to <root>/snapshot/raw."""

    def __init__(self, root):
        self.raw = Path(root) / "snapshot" / "raw"

    def benchmarks(self):
        from snapshot import load
        return load.benchmarks(self.raw)

    def load(self, benchmark):
        from snapshot import load
        return load.load(benchmark, self.raw)

    def benchmark_meta(self, benchmark):
        from snapshot import load
        return load.benchmark_meta(benchmark, self.raw)

    def attribution(self, benchmark):
        from snapshot import load
        return load.attribution(benchmark, self.raw)


def lineage_root(root) -> Path:
    return Path(root) / "lineage" / "frozen"


# ------------------------------------------------------------------ 5.6 selection

def benchmarks(snapshot=None, lineage_root=None) -> list:
    """Benchmarks meeting section 5.6 on the frozen snapshot, plus ecdsa.fail always.

    Rule per benchmark: at least 500 analysis rows; at least 100 of them promoted; at least two
    families each holding at least 10% of the rows with a single known family; and recoverable
    trees: a confirmatory window exists and at least half of the promoted rows have a tree commit
    that lineage/frozen/<slug>/missing.json does not list as unfetchable.
    """
    if snapshot is None:
        from snapshot import load as snapshot
    lroot = dataset.LINEAGE_ROOT if lineage_root is None else lineage_root
    names = list(snapshot.benchmarks())
    chosen = []
    for name in names:
        if name == ECDSA:
            chosen.append(name)
            continue
        rows = denominator.analysis_rows(snapshot.load(name), name)
        if len(rows) < MIN_ROWS:
            continue
        promoted = [s for s in rows if s.promoted]
        if len(promoted) < MIN_PROMOTED:
            continue
        fams = [mapper.family_of(s.model_line) for s in rows]
        labelled = [f for f in fams if f not in _KNOWN]
        shares = [c for c in pd.Series(labelled).value_counts().tolist() if c * 100 >= MIN_SHARE_PCT * len(labelled)]
        if len(labelled) == 0 or len(shares) < 2:
            continue
        meta = snapshot.benchmark_meta(name)
        missing = dataset._missing_shas(lroot, meta.slug)
        ok = lambda s: bool(tree_sha(s)) and tree_sha(s) not in missing  # noqa: E731
        has_tree = {s.id for s in rows if ok(s)}
        if window_start(rows, has_tree) is None:
            continue
        if sum(1 for s in promoted if s.id in has_tree) * 100 < MIN_FETCHABLE_PCT * len(promoted):
            continue
        chosen.append(name)
    return sorted(set(chosen))


# ------------------------------------------------------------------ margin

def margin(root) -> list:
    """[0.80, 1.25] unless docs/prereg.md records a widened margin as a line 'margin: [lo, hi]'."""
    p = Path(root) / "docs" / "prereg.md"
    if p.is_file():
        m = re.search(r"^margin:\s*\[\s*([0-9.]+)\s*,\s*([0-9.]+)\s*\]", p.read_text(), re.M)
        if m:
            return [float(m.group(1)), float(m.group(2))]
    return list(DEFAULT_MARGIN)


# ------------------------------------------------------------------ per-benchmark bundle

@dataclass
class Bench:
    name: str
    meta: object
    subs: list           # every snapshot row
    rows: list           # analysis rows
    df: pd.DataFrame     # dataset.build + outcome columns
    notes: dict          # id -> note


OUTCOME_COLS = ("y1", "gain_log", "large_jump", "plateau_break", "pareto_gain")


def seal(root, name, snap=None):
    """Compute outcomes with the outcomes package into <root>/outcomes/sealed and return them by id."""
    root = Path(root)
    snap = snap or RootSnapshot(root)
    meta = snap.benchmark_meta(name)
    rows = denominator.analysis_rows(snap.load(name), name)
    out_dir = root / "outcomes" / "sealed"
    outcomes.annotate(rows, meta, out_dir=out_dir)
    with gzip.open(out_dir / f"{meta.slug}.json.gz", "rb") as f:
        data = json.loads(f.read())
    return {r["id"]: r for r in data["rows"]}


def load_bench(root, name, snap=None) -> Bench:
    root = Path(root)
    snap = snap or RootSnapshot(root)
    meta = snap.benchmark_meta(name)
    subs = snap.load(name)
    rows = denominator.analysis_rows(subs, name)
    sealed = seal(root, name, snap)
    df = dataset.build(name, snapshot=snap, lineage_root=lineage_root(root))
    df = attach_outcomes(df, sealed)
    return Bench(name, meta, subs, rows, df, {s.id: s.note for s in subs})


def attach_outcomes(df, sealed) -> pd.DataFrame:
    df = df.copy()
    df["y"] = df["id"].map(lambda i: float(bool(sealed[i]["y1"])))
    df["gain_log"] = df["id"].map(lambda i: sealed[i]["gain_log"]).astype(float)
    for c in ("large_jump", "plateau_break", "pareto_gain"):
        df[c] = df["id"].map(lambda i, c=c: bool(sealed[i][c]))
    return df


def study_names(root) -> list:
    root = Path(root)
    return benchmarks(RootSnapshot(root), lineage_root=lineage_root(root))


@contextlib.contextmanager
def tree_parents_only():
    """Within the block dataset.build takes each row's tree-distance link as its primary parent."""
    real = dataset._read_parents

    def swapped(lroot, slug):
        out = {}
        for k, v in real(lroot, slug).items():
            tree = (v or {}).get("tree") or [[], "none", None, None]
            out[k] = {"primary": tree, "tree": tree}
        return out

    dataset._read_parents = swapped
    try:
        yield
    finally:
        dataset._read_parents = real


# ------------------------------------------------------------------ deterministic JSON

def clean(x):
    """JSON-ready: sorted-key friendly, floats at 6 significant digits, non-finite as None."""
    if isinstance(x, dict):
        return {str(k): clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple, set, frozenset)):
        seq = sorted(x) if isinstance(x, (set, frozenset)) else x
        return [clean(v) for v in seq]
    if isinstance(x, (bool, np.bool_)):
        return bool(x)
    if isinstance(x, (int, np.integer)):
        return int(x)
    if isinstance(x, (float, np.floating)):
        x = float(x)
        return float(f"{x:.6g}") if math.isfinite(x) else None
    return x


def dump(obj, path) -> dict:
    """Write sorted-key JSON, return exactly what was written (parsed form)."""
    obj = clean(obj)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, sort_keys=True, indent=1, allow_nan=False) + "\n")
    return obj


def guard(root) -> Path:
    """lock.check first; the root every driver then works in."""
    root = Path(lock.ROOT if root is None else root)
    lock.check(root)
    return root
