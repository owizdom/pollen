"""Confirmatory driver (spec 0001 sections 5.1, 5.2, 5.8). Refuses unless lock.check passes."""
from __future__ import annotations

import dataclasses
import math
from pathlib import Path

import pandas as pd
from scipy import stats

from analysis import design, models, study

Z95 = 1.959964
EXCLUDED_METHODS = ("failed", "unidentified")


# ------------------------------------------------------------------ shared building blocks

def fit_rows(rows, outcome=None, extra=None):
    """The single section 5.1 model on already restricted rows (design.build is the design).

    outcome: a Series/array aligned to rows (default rows['y']). extra: extra covariate columns."""
    X, yname, groups = design.build(rows)
    if extra is not None:
        X = pd.concat([X, extra.reset_index(drop=True)], axis=1)
    d = X.copy()
    d[yname] = (rows["y"] if outcome is None else pd.Series(outcome)).to_numpy(float)
    d["solver"] = groups
    return models.cond_logit(d, yname, "cross_family", list(X.columns[1:]), "solver")


def valid(e) -> bool:
    return (e is not None and getattr(e, "method", "") not in EXCLUDED_METHODS
            and math.isfinite(e.log_or) and math.isfinite(e.se) and e.se > 0)


def est_dict(e) -> dict:
    out = {"log_or": e.log_or, "se": e.se, "n": e.n,
           "n_groups_informative": e.n_groups_informative, "method": e.method}
    if math.isfinite(e.log_or) and math.isfinite(e.se):
        out["ci95"] = [e.log_or - Z95 * e.se, e.log_or + Z95 * e.se]
    if hasattr(e, "dropped_covariates"):
        out["dropped_covariates"] = sorted(getattr(e, "dropped_covariates") or [])
    return out


def rounded(e):
    """The estimate as written to JSON, as an Estimate (so pooling sees what the file holds)."""
    d = study.clean(dataclasses.asdict(e) if dataclasses.is_dataclass(e) else dict(e))
    nan = float("nan")
    return models.Estimate(nan if d["log_or"] is None else d["log_or"],
                           nan if d["se"] is None else d["se"], d["n"],
                           d["n_groups_informative"], d["method"])


def pool(ests, margin) -> dict | None:
    """HKSJ pooled result of the valid estimates, with its tost verdict; None when none are valid."""
    good = [e for e in ests if valid(e)]
    if not good:
        return None
    p = models.meta_hksj(good)
    out = study.clean({"log_or": p.log_or, "ci95": list(p.ci95), "ci90": list(p.ci90),
                       "tau2": p.tau2, "tau2_ci": list(p.tau2_ci), "k": p.k})
    out["verdict"] = models.tost(out["log_or"], out["ci95"], out["ci90"], margin)
    return out


def normal_p(est, se):
    if est is None or se is None or not (math.isfinite(est) and math.isfinite(se)) or se <= 0:
        return None
    return float(2 * stats.norm.sf(abs(est / se)))


def exclusion_counts(df) -> dict:
    """Mutually exclusive reasons a row is not a primary row, applied in a fixed order."""
    multi = df["parent_method"] == "multi"
    no_parent = ~multi & (df["cross_solver"].isna())
    own = df["cross_solver"] == False  # noqa: E712
    cross = df["cross_solver"] == True  # noqa: E712
    unknown = cross & df["cross_family"].isna()
    outside = cross & df["cross_family"].notna() & ~df["in_window"].astype(bool)
    return {"own_lineage": int(own.sum()), "multi_parent": int(multi.sum()),
            "novel": int(no_parent.sum()), "unknown_family": int(unknown.sum()),
            "outside_window": int(outside.sum())}


def strata_counts(fit) -> tuple:
    by = fit.groupby("solver")
    varies = by["y"].nunique() > 1
    kept = list(varies[varies].index)
    no_treat = [s for s in kept if fit[fit["solver"] == s]["cross_family"].astype(bool).nunique() == 1]
    return len(kept), len(no_treat), int(fit["solver"].nunique()) - len(kept)


def benchmark_result(b) -> tuple:
    """(Estimate, result dict, fit rows) for one study benchmark."""
    fit = design.primary_rows(b.df)
    if len(fit) == 0:
        est = models.Estimate(float("nan"), float("nan"), 0, 0, "unidentified")
        kept = no_treat = dropped = 0
    else:
        est = fit_rows(fit)
        kept, no_treat, dropped = strata_counts(fit)
    res = {"name": b.name,
           "estimate": est_dict(est),
           "counts": {"analysis_rows": len(b.df), "fit_rows": len(fit), "strata_kept": kept,
                      "strata_no_treatment_variation": no_treat,
                      "strata_dropped": dropped,
                      "firth": bool(est.method.startswith("firth")),
                      "excluded": exclusion_counts(b.df)}}
    return est, res, fit


# ------------------------------------------------------------------ driver

def run(root=None) -> dict:
    root = study.guard(root)
    names = study.study_names(root)
    margin = study.margin(root)
    snap = study.RootSnapshot(root)
    bench_out, ests, excluded = {}, {}, {}
    for name in names:
        b = study.load_bench(root, name, snap)
        est, res, _ = benchmark_result(b)
        res = study.clean(res)
        bench_out[name] = res
        r = rounded(est)
        ests[name] = r
        if not valid(r):
            excluded[name] = (f"no finite estimate (method {r.method}, "
                              f"{r.n_groups_informative} informative strata)")
    pooled = pool(list(ests.values()), margin)
    case = study.ECDSA if study.ECDSA in ests else (names[0] if names else None)
    case_verdict = "inconclusive"
    if case is not None and valid(ests[case]):
        case_verdict = pool([ests[case]], margin)["verdict"]
    out = {
        "benchmarks": bench_out,
        "pooled": None if pooled is None else {k: v for k, v in pooled.items() if k != "verdict"},
        "verdict": "inconclusive" if pooled is None else pooled["verdict"],
        "case_study": {"benchmark": case, "verdict": case_verdict},
        "margin": margin,
        "excluded_benchmarks": excluded,
    }
    return study.dump(out, Path(root) / "results" / "confirmatory.json")


if __name__ == "__main__":
    import argparse
    import sys

    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=None)
    args = ap.parse_args()
    try:
        run(args.root)
    except Exception as exc:  # the lock refusing, or any failure, is a non-zero exit
        print(f"confirmatory refused: {type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(1)
