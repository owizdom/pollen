"""Plant a known effect into the real treatment structure (spec 0001 s5.4)."""
from __future__ import annotations

import math

import numpy as np
from scipy.optimize import brentq
from scipy.special import expit

OUTCOME = "y_sim"


def plant(df_treatment, odds_ratio, base_rate, icc, seed):
    """Add one binary column from a logistic model with a solver random intercept.

    Latent-scale ICC = s2 / (s2 + pi^2/3) equals icc. The intercept is calibrated
    so the realised marginal rate equals base_rate."""
    df = df_treatment.copy()
    rng = np.random.default_rng(seed)
    s2 = icc / (1 - icc) * math.pi**2 / 3 if icc > 0 else 0.0
    solvers, inv = np.unique(df["solver"].to_numpy(), return_inverse=True)
    u = rng.normal(0.0, math.sqrt(s2), len(solvers))[inv]
    lin = math.log(odds_ratio) * df["cross_family"].to_numpy().astype(float) + u
    b0 = brentq(lambda b: expit(b + lin).mean() - base_rate, -30, 30)
    df[OUTCOME] = (rng.random(len(df)) < expit(b0 + lin)).astype(int)
    return df
