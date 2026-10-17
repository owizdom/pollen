"""Exploratory analyses E1 and E2 (spec 0001 section 4). Reported without correction."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from analysis import confirmatory, design, models, study

SEED = 20261104


def _weeks(d):
    return pd.get_dummies(d["week"].astype(str), prefix="week", drop_first=True, dtype=float)


def _e1_bench(df, boot):
    """Multi-family or multi-source rows against single-family, single-parent rows, in the window."""
    d = df[df["in_window"].astype(bool)].copy()
    multi = d["multi_family"].astype(bool) | (d["parent_method"] == "multi")
    single = (~multi) & (d["parent_ids"].map(len) == 1) & ~d["child_family"].isin(["Unknown"])
    d = d[multi | single].copy()
    d["multi"] = (multi[d.index]).astype(float)
    d = d.reset_index(drop=True)
    out = {"n_multi": int(d["multi"].sum()), "n_single": int((d["multi"] == 0).sum()),
           "promoted_rate_multi": _rate(d, 1.0), "promoted_rate_single": _rate(d, 0.0)}
    X = _weeks(d)
    f = pd.concat([d[["y", "multi", "solver"]], X], axis=1)
    try:
        e = models.cond_logit(f, "y", "multi", list(X.columns), "solver")
        out["y1"] = confirmatory.est_dict(e)
    except Exception as ex:
        out["y1"] = {"method": "failed", "error": type(ex).__name__}
    prom = pd.concat([d, X], axis=1)
    prom = prom[(prom["y"] > 0) & prom["gain_log"].notna()]
    try:
        e = models.median_reg(prom, "gain_log", "multi", list(X.columns), "solver", boot=boot, seed=SEED)
        out["y3"] = confirmatory.est_dict(e)
    except Exception as ex:
        out["y3"] = {"method": "failed", "error": type(ex).__name__}
    return out


def _rate(d, v):
    s = d[d["multi"] == v]["y"]
    return float(s.mean()) if len(s) else None


def _third(df):
    n = len(df)
    return pd.Series([min(2, (3 * i) // n) for i in range(n)], index=df.index)


def run(root=None, boot=2000) -> dict:
    root = study.guard(root)
    snap = study.RootSnapshot(root)
    margin = study.margin(root)
    e1, e2 = {}, {}
    thirds = {0: [], 1: [], 2: []}
    for name in study.study_names(root):
        b = study.load_bench(root, name, snap)
        e1[name] = _e1_bench(b.df, boot)
        t = _third(b.df)
        e2[name] = {}
        for k in (0, 1, 2):
            rows = design.primary_rows(b.df[t == k])
            if len(rows) == 0:
                e2[name][f"third{k + 1}"] = {"method": "unidentified", "n": 0}
                continue
            est = confirmatory.fit_rows(rows)
            e2[name][f"third{k + 1}"] = confirmatory.est_dict(est)
            thirds[k].append(confirmatory.rounded(est))
    pooled = {}
    for k in (0, 1, 2):
        p = confirmatory.pool(thirds[k], margin)
        pooled[f"third{k + 1}"] = None if p is None else {q: p[q] for q in ("log_or", "ci95", "tau2", "k")}
    out = {"label": "exploratory", "E1": e1, "E2": {"benchmarks": e2, "pooled": pooled}}
    return study.dump(out, Path(root) / "results" / "exploratory.json")
