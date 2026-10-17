"""Equivalence power from treatment counts only (spec 0001 section 5.3). Uses no outcomes.

Outcomes are planted at an odds ratio of 1 on the real treatment frame and the primary
model is fitted to each run.
"""
from __future__ import annotations

import math

import pandas as pd

from analysis import design, models, simulate

Z90 = 1.6448536269514722


def min_rows(cells) -> int:
    """Row count of the smaller treatment arm (rows with a known cross_family)."""
    x = cells[cells["cross_family"].notna()]["cross_family"].astype(bool)
    return int(min(x.sum(), len(x) - x.sum()))


def _prepare(frame):
    """Primary rows as a numeric design frame with a solver column, plus covariate names."""
    X, y_name, groups = design.build(design.primary_rows(frame))
    d = X.copy()
    d["solver"] = groups
    return d, y_name, list(X.columns[1:])


def _one_fit(prep, base_rate, icc, seed):
    d, y_name, covs = prep
    planted = simulate.plant(d, 1.0, base_rate, icc, seed)
    if y_name != simulate.OUTCOME:
        planted = planted.rename(columns={simulate.OUTCOME: y_name})
    return models.cond_logit(planted, y_name, "cross_family", covs, "solver")


def _valid(e) -> bool:
    return (e is not None and getattr(e, "method", "") not in ("failed", "unidentified")
            and math.isfinite(e.log_or) and math.isfinite(e.se) and e.se > 0)


def _inside(lo_hi, margin) -> bool:
    return lo_hi[0] > math.log(margin[0]) and lo_hi[1] < math.log(margin[1])


def equivalence_power_report(frame, base_rate, margin=(0.80, 1.25), icc=0.05, sims=2000,
                             seed=20261017) -> dict:
    """Power and the share of runs whose fit failed. A failed run is never equivalent."""
    prep = _prepare(frame)
    ok = failed = 0
    for i in range(sims):
        e = _one_fit(prep, base_rate, icc, seed * 100003 + i)
        if not _valid(e):
            failed += 1
        else:
            ok += _inside((e.log_or - Z90 * e.se, e.log_or + Z90 * e.se), margin)
    return {"power": ok / sims, "failed_share": failed / sims}


def equivalence_power(frame, base_rate, **kw) -> float:
    return equivalence_power_report(frame, base_rate, **kw)["power"]


def pooled_equivalence_power_report(frames, base_rates, margin=(0.80, 1.25), icc=0.05,
                                    sims=2000, seed=20261017) -> dict:
    """Pooled primary estimand. A run with any failed benchmark is non-equivalent; failed_share
    is the share of benchmark fits that failed."""
    keys = sorted(frames)
    preps = {k: _prepare(frames[k]) for k in keys}
    ok = failed = 0
    for i in range(sims):
        ests = []
        for j, k in enumerate(keys):
            e = _one_fit(preps[k], base_rates[k], icc, seed * 100003 + i * 1009 + j)
            if _valid(e):
                ests.append(e)
            else:
                failed += 1
        if len(ests) == len(keys):
            ok += _inside(models.meta_hksj(ests).ci90, margin)
    return {"power": ok / sims, "failed_share": failed / (sims * len(keys))}


def pooled_equivalence_power(frames, base_rates, **kw) -> float:
    return pooled_equivalence_power_report(frames, base_rates, **kw)["power"]
