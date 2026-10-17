"""Synthetic data builders for tests/test_models.py. No real data."""
import numpy as np
import pandas as pd


def make_treatment(seed=0, n_solvers=40, rows_per_solver=25, varying_share=0.5, n_weeks=10):
    """Real-like treatment structure: about 1,000 rows, ~40 solvers, half with
    treatment variation (the rest are all-treated or all-control)."""
    rng = np.random.default_rng(seed)
    recs = []
    n_vary = int(round(n_solvers * varying_share))
    for s in range(n_solvers):
        n = max(4, int(rng.poisson(rows_per_solver)))
        if s < n_vary:
            t = rng.random(n) < 0.5
            t[0], t[1] = True, False  # guarantee variation
        else:
            t = np.full(n, bool(rng.random() < 0.5))
        for j in range(n):
            recs.append(
                {
                    "solver": f"s{s:02d}",
                    "week": f"2026-W{int(rng.integers(1, n_weeks + 1)):02d}",
                    "cross_family": bool(t[j]),
                    "log_prior_rows": float(np.log1p(j)),
                }
            )
    return pd.DataFrame(recs)


def stratified_logit_data(seed=1, n_groups=300, per_group=10, log_or=0.7, group_sd=1.0):
    """Alternating treatment inside every group, so every group has treatment
    variation by construction. Outcome follows logit = a_g + log_or * t."""
    rng = np.random.default_rng(seed)
    rows = []
    for g in range(n_groups):
        a = rng.normal(-0.5, group_sd)
        for j in range(per_group):
            t = j % 2
            p = 1 / (1 + np.exp(-(a + log_or * t)))
            rows.append({"g": g, "t": t, "y": int(rng.random() < p)})
    return pd.DataFrame(rows)


def add_constant_outcome_groups(df, n_extra=15, per_group=8, value=0):
    """Append groups whose outcome never varies (non-informative strata)."""
    start = int(df["g"].max()) + 1
    rows = [
        {"g": start + k, "t": j % 2, "y": value}
        for k in range(n_extra)
        for j in range(per_group)
    ]
    return pd.concat([df, pd.DataFrame(rows)], ignore_index=True)


def separated_data(n_groups=20):
    """In every group the treated rows all succeed and the controls all fail."""
    rows = []
    for g in range(n_groups):
        for t in (1, 1, 0, 0):
            rows.append({"g": g, "t": t, "y": t})
    return pd.DataFrame(rows)


def hksj_example():
    y = [0.10, 0.40, -0.20, 0.50]
    se = [0.20, 0.25, 0.30, 0.15]
    return y, se


def stratified_flag_data(seed=3, n_strata=4, per_stratum=200):
    """Label and flag both depend on the stratum but are independent inside it."""
    rng = np.random.default_rng(seed)
    rows = []
    for k in range(n_strata):
        p_label = 0.1 + 0.8 * k / (n_strata - 1)
        p_flag = 0.1 + 0.8 * k / (n_strata - 1)
        for _ in range(per_stratum):
            rows.append(
                {
                    "stratum": f"w{k}",
                    "label": bool(rng.random() < p_label),
                    "flag": bool(rng.random() < p_flag),
                }
            )
    return pd.DataFrame(rows)


def median_shift_data(seed=5, n_clusters=40, per_cluster=15, shift=2.0, cluster_sd=0.0):
    rng = np.random.default_rng(seed)
    rows = []
    for c in range(n_clusters):
        u = rng.normal(0, cluster_sd) if cluster_sd else 0.0
        tc = c % 2  # treatment varies at the cluster level
        for i in range(per_cluster):
            t = tc if cluster_sd else int(rng.random() < 0.5)
            y = 5.0 + shift * t + u + rng.standard_t(3)
            rows.append({"cluster": f"c{c}", "rid": f"{c}-{i}", "t": t, "y": y, "w": int(rng.integers(0, 3))})
    return pd.DataFrame(rows)


def exactly_independent_flag_data(n_strata=3, n_label=100, n_other=100, n_flagged=30):
    """In every stratum the flag rate is identical among label and non-label rows."""
    rows = []
    for k in range(n_strata):
        for lab, n in ((True, n_label), (False, n_other)):
            flagged = round(n_flagged * n / 100)
            for i in range(n):
                rows.append({"stratum": f"w{k}", "label": lab, "flag": i < flagged})
    return pd.DataFrame(rows)


def quasi_separated_data(seed=8, n_groups=None):
    """Treated rows always succeed; controls vary (at least one control fails per group).
    Strata sizes and control success rates vary with the seed."""
    rng = np.random.default_rng(seed)
    n_groups = n_groups or int(rng.integers(120, 260))
    p_ctrl = float(rng.uniform(0.15, 0.85))
    rows = []
    for g in range(n_groups):
        n_t = int(rng.integers(1, 4))
        n_c = int(rng.integers(2, 6))
        ctrl = [int(rng.random() < p_ctrl) for _ in range(n_c)]
        ctrl[int(rng.integers(0, n_c))] = 0  # guarantee outcome variation
        for t, y in [(1, 1)] * n_t + [(0, c) for c in ctrl]:
            rows.append({"g": g, "t": t, "y": y})
    return pd.DataFrame(rows)


def covariate_stratum_data(seed=9, n_groups=80, per_group=8):
    """Half the strata have alternating treatment, half constant treatment. The covariate x
    is correlated with treatment, so constant-treatment strata inform its coefficient."""
    rng = np.random.default_rng(seed)
    rows = []
    for g in range(n_groups):
        a = rng.normal(-0.3, 0.8)
        const = g % 2 == 1
        tc = int(rng.random() < 0.5)
        for j in range(per_group):
            t = tc if const else j % 2
            x = 0.8 * t + rng.normal()
            p = 1 / (1 + np.exp(-(a + 0.5 * t + 0.7 * x)))
            rows.append({"g": g, "t": t, "x": x, "y": int(rng.random() < p)})
    return pd.DataFrame(rows)
