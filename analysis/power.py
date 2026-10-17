"""Equivalence power from treatment counts only (spec 0001 section 5.3). Uses no outcomes."""
from __future__ import annotations

import math

import numpy as np

Z90 = 1.6448536269514722
_C2 = 0.3458  # (16*sqrt(3)/(15*pi))^2, logit-normal attenuation


def _arms(cells):
    d = cells[cells["cross_family"].notna()]
    return (d["solver"].to_numpy(), d["cross_family"].astype(bool).to_numpy().astype(float))


def min_events(cells) -> int:
    """Row count of the smaller treatment arm (rows with a known cross_family)."""
    _, x = _arms(cells)
    return int(min(x.sum(), len(x) - x.sum()))


def _fit(y, X, cid, ng):
    """Logistic IRLS with cluster-robust SE for the slope; None on failure."""
    b = np.zeros(2)
    for _ in range(30):
        p = 1 / (1 + np.exp(-X @ b))
        w = p * (1 - p)
        H = X.T @ (X * w[:, None])
        try:
            step = np.linalg.solve(H, X.T @ (y - p))
        except np.linalg.LinAlgError:
            return None
        b = b + step
        if np.abs(step).max() < 1e-8:
            break
    else:
        return None
    if np.abs(b).max() > 12:
        return None
    p = 1 / (1 + np.exp(-X @ b))
    sc = np.zeros((ng, 2))
    np.add.at(sc, cid, X * (y - p)[:, None])
    try:
        Hi = np.linalg.inv(X.T @ (X * (p * (1 - p))[:, None]))
    except np.linalg.LinAlgError:
        return None
    V = Hi @ (sc.T @ sc) @ Hi * (ng / max(ng - 1, 1))
    se = math.sqrt(V[1, 1]) if V[1, 1] > 0 else None
    return b[1], se


def equivalence_power(cells, base_rate, margin=(0.80, 1.25), alpha=0.05, icc=0.05,
                      sims=2000, seed=20261017) -> float:
    """Share of simulated datasets whose (1-2*alpha) interval for the odds ratio lies inside
    margin, at a true OR of 1, with a random solver intercept of the given ICC and the
    marginal rate base_rate in both arms."""
    from scipy.stats import norm
    solvers, x = _arms(cells)
    _, cid = np.unique(solvers, return_inverse=True)
    ng, n = int(cid.max()) + 1, len(x)
    lo, hi = math.log(margin[0]), math.log(margin[1])
    z = norm.ppf(1 - alpha)
    sigma = math.sqrt(icc / (1 - icc) * math.pi ** 2 / 3)
    intercept = math.log(base_rate / (1 - base_rate)) * math.sqrt(1 + _C2 * sigma ** 2)
    rng = np.random.default_rng(seed)
    X = np.column_stack([np.ones(n), x])
    ok = 0
    for _ in range(sims):
        eta = intercept + rng.normal(0, sigma, ng)[cid]
        y = (rng.random(n) < 1 / (1 + np.exp(-eta))).astype(float)
        r = _fit(y, X, cid, ng)
        if r is None or r[1] is None:
            continue
        b, se = r
        ok += (b - z * se > lo) and (b + z * se < hi)
    return ok / sims
