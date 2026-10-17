"""Per-submission treatment dataset (spec 0001 sections 3 and 5.1).

Blinding: this module never reads outcomes/sealed and carries no outcome column. The
parent_is_current_best covariate uses the parent's own score and promoted flag to find the
frontier holder at the child's creation; the child's own promoted flag is never joined.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import math
from collections import Counter
from pathlib import Path

import pandas as pd

from families import mapper
from lineage import window
from lineage.build import tree_sha
from outcomes import denominator
from outcomes._order import eval_time

FOLD_BELOW = 30
LINEAGE_ROOT = Path(__file__).resolve().parent.parent / "lineage" / "frozen"


class FrozenError(Exception):
    """A frozen lineage file is absent, unlisted or does not match SHA256SUMS."""


def _verified(lineage_root, slug, name) -> Path:
    root = Path(lineage_root)
    p = root / slug / name
    if not p.is_file():
        raise FrozenError(f"missing {p}")
    sums = root / "SHA256SUMS"
    if not sums.is_file():
        raise FrozenError(f"missing {sums}")
    want = {}
    for line in sums.read_text().splitlines():
        digest, _, rel = line.partition("  ")
        if rel.strip():
            want[rel.strip()] = digest.strip()
    key = f"{slug}/{name}"
    if key not in want:
        raise FrozenError(f"{key} not listed in {sums}")
    if hashlib.sha256(p.read_bytes()).hexdigest() != want[key]:
        raise FrozenError(f"{key} does not match {sums}")
    return p


def _read_parents(lineage_root, slug) -> dict:
    p = _verified(lineage_root, slug, "parents.json.gz")
    with gzip.open(p, "rb") as f:
        return json.loads(f.read())


def _missing_shas(lineage_root, slug) -> set:
    return set(json.loads(_verified(lineage_root, slug, "missing.json").read_text()))


def _week(ts) -> str:
    y, w, _ = ts.astimezone(__import__("datetime").timezone.utc).isocalendar()
    return f"{y}-W{w:02d}"


def _known(family) -> bool:
    return family not in (None, "Unknown", "Multi")


def _best_holders(rows, direction):
    """For each row, the id of the best promoted row whose evaluation finished before the
    row was created (None when there is none)."""
    promoted = sorted((s for s in rows if s.promoted and s.score is not None),
                      key=lambda s: (eval_time(s), s.created_at, s.id))
    better = (lambda a, b: a < b) if direction == "lower" else (lambda a, b: a > b)
    out, k, best = {}, 0, None
    for c in sorted(rows, key=lambda s: (s.created_at, s.id)):
        while k < len(promoted) and eval_time(promoted[k]) < c.created_at:
            p = promoted[k]
            if best is None or better(p.score, best.score):
                best = p
            k += 1
        out[c.id] = best.id if best else None
    return out


def build(benchmark, *, snapshot=None, lineage_root=None) -> pd.DataFrame:
    if snapshot is None:
        from snapshot import load as snapshot
    lineage_root = LINEAGE_ROOT if lineage_root is None else lineage_root
    meta = snapshot.benchmark_meta(benchmark)
    allsubs = {s.id: s for s in snapshot.load(benchmark)}
    rows = sorted(denominator.analysis_rows(list(allsubs.values()), benchmark),
                  key=lambda s: (s.created_at, s.id))
    links = _read_parents(lineage_root, meta.slug)
    missing = _missing_shas(lineage_root, meta.slug)
    has_tree = {s.id for s in rows if tree_sha(s) and tree_sha(s) not in missing}
    start = window.start(rows, has_tree)
    holders = _best_holders(rows, meta.direction)

    fam = {i: mapper.family_of(s.model_line) for i, s in allsubs.items()}
    counts = Counter(fam[s.id] for s in rows)
    fold = lambda f: None if f is None else (f if counts[f] >= FOLD_BELOW else "Other")  # noqa: E731

    opened = meta.opened_at or (rows[0].created_at if rows else None)
    prior = Counter()
    recs = []
    for s in rows:
        link = links.get(s.id) or {}
        primary = link.get("primary") or [[], "none", None, None]
        tree = link.get("tree") or [[], "none", None, None]
        pids = tuple(primary[0])
        method = primary[1] if primary[1] in ("declared", "multi", "tree", "novel") else "none"
        single = len(pids) == 1 and pids[0] in allsubs
        parent = allsubs[pids[0]] if single else None
        cf = fam[s.id]
        pf = fam[parent.id] if parent else None
        cross_solver = (parent.solver != s.solver) if parent else None
        cross_family = (cf != pf) if parent and _known(cf) and _known(pf) else None
        cell = None
        if cross_family is not None:
            cell = ("other_" if cross_solver else "own_") + ("switch" if cross_family else "same")
        recs.append({
            "id": s.id, "solver": s.solver, "created_at": s.created_at, "week": _week(s.created_at),
            "days_since_open": (s.created_at - opened).total_seconds() / 86400.0,
            "child_model": s.model_line, "child_family": cf, "multi_family": cf == "Multi",
            "harness": mapper.harness_of(s.note), "parent_ids": pids, "parent_method": method,
            "tree_parent_id": tree[0][0] if tree[0] else None,
            "parent_solver": parent.solver if parent else None, "parent_family": pf,
            "cross_solver": cross_solver, "cross_family": cross_family, "cell": cell,
            "parent_is_current_best": bool(parent and holders[s.id] == parent.id),
            "log_prior_rows": math.log1p(prior[s.solver]),
            "in_window": start is not None and s.created_at >= start,
            "child_family_folded": fold(cf), "parent_family_folded": fold(pf),
        })
        prior[s.solver] += 1
    df = pd.DataFrame(recs)
    for c in ("cross_solver", "cross_family", "cell", "parent_family", "parent_solver",
              "parent_family_folded", "tree_parent_id"):
        df[c] = df[c].astype(object)
    return df
