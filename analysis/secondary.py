"""Secondary tests H2, H3a, H3b, H4, H5 (spec 0001 section 5.4) with the minimum-events gate."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from analysis import confirmatory, design, models, study

MIN_EVENTS = 20
SEEDS = {"H3a": 20261101, "H3b": 20261102, "H4": 20261103}


def _own_rows(df):
    keep = ((df["cross_solver"] == False)  # noqa: E712
            & df["cross_family"].notna() & df["in_window"].astype(bool)
            & df["parent_method"].isin(["declared", "text", "tree"]))
    return df[keep].reset_index(drop=True)


def _arm_events(rows, flag) -> int:
    cf = rows["cross_family"].astype(bool)
    f = rows[flag].astype(bool)
    return int(min((f & cf).sum(), (f & ~cf).sum()))


def _entry(h, bench, events, p, est=None, se=None, n=None, extra=None):
    e = {"hypothesis": h, "benchmark": bench, "min_arm_events": int(events),
         "status": "confirmatory" if events >= MIN_EVENTS else "descriptive",
         "p": p, "p_holm": None, "estimate": est, "se": se, "n": n}
    e.update(extra or {})
    return e


def _unidentified(h, bench, n=0):
    """No rows or no identified effect: reported, never in the Holm family."""
    return {"hypothesis": h, "benchmark": bench, "min_arm_events": 0, "status": "unidentified",
            "method": "unidentified", "p": None, "p_holm": None, "estimate": None, "se": None,
            "n": n}


def _failed(h, bench, events, n, method="failed"):
    """A test that passed the events gate but gave no estimate stays in the family with p = 1."""
    e = _entry(h, bench, events, 1.0 if events >= MIN_EVENTS else None, None, None, n,
               {"method": method})
    return e


def _fit_entry(h, bench, rows, outcome_col):
    if len(rows) == 0:
        return _unidentified(h, bench)
    events = _arm_events(rows.assign(_f=rows[outcome_col].astype(bool)), "_f")
    try:
        est = confirmatory.fit_rows(rows, outcome=rows[outcome_col].astype(float))
    except Exception:
        return _failed(h, bench, events, len(rows))
    if est.method == "unidentified":
        return _failed(h, bench, events, est.n, method="unidentified")
    if not confirmatory.valid(est):
        return _failed(h, bench, events, est.n)
    return _entry(h, bench, events, confirmatory.normal_p(est.log_or, est.se),
                  est.log_or, est.se, est.n, {"method": est.method})


def _h1_entry(bench, prim):
    """ecdsa.fail's single-benchmark primary test, a member of the secondary Holm family."""
    return _fit_entry("H1", bench, prim, "y")


def _perm_entry(h, bench, prom, flag, draws):
    if len(prom) == 0:
        return _unidentified(h, bench)
    events = _arm_events(prom, flag)
    d = pd.DataFrame({"label": prom["cross_family"].astype(bool), "flag": prom[flag].astype(bool),
                      "week": prom["week"]})
    try:
        share, p = models.permutation_share(d, "label", "flag", "week", draws=draws, seed=SEEDS[h])
    except Exception:
        return _failed(h, bench, events, len(d))
    return _entry(h, bench, events, p, share, None, len(d))


def _h4_entry(bench, prom, boot):
    g = prom[prom["gain_log"].notna()].reset_index(drop=True)
    if len(g) == 0:
        return _unidentified("H4", bench)
    cf = g["cross_family"].astype(bool)
    events = int(min(cf.sum(), (~cf).sum()))
    X, _, groups = design.build(g)
    time = [c for c in X.columns if c.startswith("time_s")]
    d = X[["cross_family"] + time].copy()
    d["y3"] = g["gain_log"].to_numpy(float)
    d["solver"] = groups
    try:
        est = models.median_reg(d, "y3", "cross_family", time, "solver", boot=boot, seed=SEEDS["H4"])
        p = confirmatory.normal_p(est.log_or, est.se)
    except Exception:
        return _failed("H4", bench, events, len(d))
    if p is None:
        return _failed("H4", bench, events, len(d))
    return _entry("H4", bench, events, p, est.log_or, est.se, est.n)


def run(root=None, draws=10000, boot=2000) -> dict:
    root = study.guard(root)
    snap = study.RootSnapshot(root)
    tests = []
    for name in study.study_names(root):
        b = study.load_bench(root, name, snap)
        df = b.df
        own = _own_rows(df)
        tests.append(_fit_entry("H2", name, own, "y"))
        prim = design.primary_rows(df)
        if name == study.ECDSA:
            tests.append(_h1_entry(name, prim))
        prom = prim[prim["y"] > 0].reset_index(drop=True)
        tests.append(_perm_entry("H3a", name, prom, "large_jump", draws))
        tests.append(_perm_entry("H3b", name, prom, "plateau_break", draws))
        tests.append(_h4_entry(name, prom, boot))
        if name == study.ECDSA:
            tests.append(_fit_entry("H5", name, prim, "pareto_gain"))
    tests = [study.clean(t) for t in tests]
    conf = {f"{t['hypothesis']}:{t['benchmark']}": t["p"] for t in tests
            if t["status"] == "confirmatory" and t["p"] is not None}
    adj = models.holm(conf)
    for t in tests:
        k = f"{t['hypothesis']}:{t['benchmark']}"
        if k in adj:
            t["p_holm"] = adj[k]
    tests.sort(key=lambda t: (t["hypothesis"], t["benchmark"]))
    return study.dump({"tests": tests}, Path(root) / "results" / "secondary.json")
