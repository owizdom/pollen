"""AT4 (treatment validity) and AT15 (window balance) on the frozen data."""
from __future__ import annotations

from collections import Counter

from families import mapper
from lineage import declared, window
from lineage.build import tree_sha

AT4_MIN = 0.85
AT15_TOL = window.TOL


def _known(f) -> bool:
    return f not in (None, "Unknown", "Multi")


def _cell(child, parent, fam):
    if parent is None or not (_known(fam[child.id]) and _known(fam[parent.id])):
        return None
    return (("other_" if parent.solver != child.solver else "own_")
            + ("switch" if fam[child.id] != fam[parent.id] else "same"))


def at4_benchmark(benchmark, snapshot=None, lineage_root=None) -> dict:
    """Counts of inferred-cell agreement against declared and text-declared parents,
    split by whether the labelled parent was the current best."""
    from analysis import dataset

    if snapshot is None:
        from snapshot import load as snapshot
    allsubs = {s.id: s for s in snapshot.load(benchmark)}
    fam = {i: mapper.family_of(s.model_line) for i, s in allsubs.items()}
    df = dataset.build(benchmark, snapshot=snapshot, lineage_root=lineage_root)
    rows = sorted(allsubs.values(), key=lambda s: (s.created_at, s.id))
    holders = dataset._best_holders(
        [s for s in rows if s.id in set(df["id"])], snapshot.benchmark_meta(benchmark).direction)
    order = {s.id: k for k, s in enumerate(rows)}
    out = {"declared": Counter(), "text": Counter()}
    for r in df.itertuples():
        child = allsubs[r.id]
        tree_parent = allsubs.get(r.tree_parent_id) if r.tree_parent_id else None
        inferred = _cell(child, tree_parent, fam)
        labelled = {}
        if r.parent_method == "declared" and len(r.parent_ids) == 1:
            labelled["declared"] = allsubs.get(r.parent_ids[0])
        tok = declared.declared_base(child.note)
        if tok:
            pid = declared.resolve(tok, rows[:order[child.id]])
            if pid:
                labelled["text"] = allsubs[pid]
        for kind, parent in labelled.items():
            truth = _cell(child, parent, fam)
            if truth is None or inferred is None:
                continue
            side = "frontier" if holders.get(child.id) == parent.id else "other"
            out[kind][(side, truth == inferred)] += 1
    return {k: dict(v) for k, v in out.items()}


def agreement(counts: dict) -> tuple[int, int]:
    """(agreeing rows, labelled rows) from an at4_benchmark entry."""
    agree = sum(n for (side, ok), n in counts.items() if ok)
    return agree, sum(counts.values())


def at15_benchmark(benchmark, snapshot=None, lineage_root=None) -> dict:
    """Tree-recoverable share for promoted and other rows inside the confirmatory window."""
    from analysis import dataset
    from outcomes import denominator

    if snapshot is None:
        from snapshot import load as snapshot
    slug = snapshot.benchmark_meta(benchmark).slug
    root = dataset.LINEAGE_ROOT if lineage_root is None else lineage_root
    missing = dataset._missing_shas(root, slug)
    rows = denominator.analysis_rows(snapshot.load(benchmark), benchmark)
    has_tree = {s.id for s in rows if tree_sha(s) and tree_sha(s) not in missing}
    start = window.start(rows, has_tree)
    inside = [s for s in rows if start is not None and s.created_at >= start]
    prom = [s for s in inside if s.promoted]
    oth = [s for s in inside if not s.promoted]
    share = lambda xs: sum(s.id in has_tree for s in xs) / len(xs) if xs else None  # noqa: E731
    return {"start": start.isoformat() if start else None, "rows": len(inside),
            "promoted_share": share(prom), "other_share": share(oth)}
