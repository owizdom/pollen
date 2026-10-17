"""Equivalence power from treatment counts only (spec 0001 section 5.3). Uses no outcomes.

Outcomes are planted at an odds ratio of 1 on the real treatment frame and the primary
model is fitted to each run.
"""
from __future__ import annotations

import math

import pandas as pd

from analysis import models, simulate

Z90 = 1.6448536269514722
CATEGORICAL = ("week", "child_family_folded", "parent_family_folded")
OUTCOME = simulate.OUTCOME


def _known(frame) -> pd.DataFrame:
    return frame[frame["cross_family"].notna()].reset_index(drop=True)


def min_rows(cells) -> int:
    """Row count of the smaller treatment arm (rows with a known cross_family)."""
    x = _known(cells)["cross_family"].astype(bool)
    return int(min(x.sum(), len(x) - x.sum()))


def _design(frame):
    """Numeric design frame and covariate names (section 5.1); constant columns dropped."""
    d = _known(frame)
    d["cross_family"] = d["cross_family"].astype(bool)
    parts, covs = [], []
    for c in CATEGORICAL:
        if c in d:
            dm = pd.get_dummies(d[c].astype(str), prefix=c, drop_first=True, dtype=float)
            parts.append(dm)
    for c in ("parent_is_current_best", "log_prior_rows"):
        if c in d:
            parts.append(d[[c]].astype(float))
    if parts:
        x = pd.concat(parts, axis=1)
        x = x.loc[:, x.nunique() > 1]
        covs = list(x.columns)
        d = pd.concat([d[["solver", "cross_family"]], x], axis=1)
    else:
        d = d[["solver", "cross_family"]].copy()
    return d, covs


def _one_fit(design, covs, base_rate, icc, seed):
    d = simulate.plant(design, 1.0, base_rate, icc, seed)
    d["cross_family"] = d["cross_family"].astype(float)
    return models.cond_logit(d, OUTCOME, "cross_family", covs, "solver")


def _valid(e) -> bool:
    return e is not None and math.isfinite(e.log_or) and math.isfinite(e.se) and e.se > 0


def _inside(lo_hi, margin) -> bool:
    return lo_hi[0] > math.log(margin[0]) and lo_hi[1] < math.log(margin[1])


def equivalence_power(frame, base_rate, margin=(0.80, 1.25), icc=0.05, sims=2000,
                      seed=20261017) -> float:
    """Share of runs whose 90% interval for the odds ratio lies inside margin, at a true OR
    of 1, for one benchmark."""
    design, covs = _design(frame)
    ok = 0
    for i in range(sims):
        e = _one_fit(design, covs, base_rate, icc, seed * 100003 + i)
        if _valid(e):
            ok += _inside((e.log_or - Z90 * e.se, e.log_or + Z90 * e.se), margin)
    return ok / sims


def pooled_equivalence_power(frames, base_rates, margin=(0.80, 1.25), icc=0.05, sims=2000,
                             seed=20261017) -> float:
    """As equivalence_power for the primary estimand: each run pools the per-benchmark
    estimates with the HKSJ meta-analysis and tests the pooled 90% interval."""
    designs = {k: _design(f) for k, f in frames.items()}
    ok = 0
    for i in range(sims):
        ests = []
        for j, k in enumerate(sorted(designs)):
            d, covs = designs[k]
            e = _one_fit(d, covs, base_rates[k], icc, seed * 100003 + i * 1009 + j)
            if _valid(e):
                ests.append(e)
        if ests:
            ok += _inside(models.meta_hksj(ests).ci90, margin)
    return ok / sims
