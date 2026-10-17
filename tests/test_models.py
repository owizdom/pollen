"""Track E2 tests: analysis.models and analysis.simulate (spec 0001 s5.1-5.4, AT13, AT14).

Contract choices made by these tests where the spec is silent:
- meta_hksj takes a list of models.Estimate(log_or, se, n, n_groups_informative, method).
- meta_hksj with k=1 returns the single estimate with a normal 95% interval, tau2=0, k=1.
- ci95/ci90/tau2_ci are (lower, upper) pairs on the log-odds scale.
- permutation_share takes label/flag/strata as column names; label and flag are boolean.
- simulate.plant reads columns cross_family, solver, week and adds exactly one new binary column.
"""
import importlib
import math

import numpy as np
import pandas as pd
import pytest
from scipy import stats
from scipy.optimize import brentq

import fixtures_models as fx


@pytest.fixture(scope="module")
def models():
    return importlib.import_module("analysis.models")


@pytest.fixture(scope="module")
def simulate():
    return importlib.import_module("analysis.simulate")


def est(models, log_or, se):
    return models.Estimate(
        log_or=log_or, se=se, n=100, n_groups_informative=10, method="clogit", dropped_covariates=()
    )


# ---------------------------------------------------------------- cond_logit

def test_cond_logit_recovers_log_or(models):
    df = fx.stratified_logit_data(log_or=0.7)
    r = models.cond_logit(df, "y", "t", [], "g")
    assert r.method != "firth"
    assert r.se > 0
    assert abs(r.log_or - 0.7) < 3 * r.se


def test_cond_logit_reports_noninformative_strata(models):
    base = fx.stratified_logit_data(n_groups=100)
    expected = int((base.groupby("g")["y"].nunique() > 1).sum())
    assert 0 < expected < 100
    df = fx.add_constant_outcome_groups(base, n_extra=15, value=0)
    df = fx.add_constant_outcome_groups(df, n_extra=5, value=1)
    r = models.cond_logit(df, "y", "t", [], "g")
    assert r.n_groups_informative == expected
    r0 = models.cond_logit(base, "y", "t", [], "g")
    assert r0.n_groups_informative == expected
    assert r.log_or == pytest.approx(r0.log_or, abs=1e-6)


def test_cond_logit_separation_falls_back_to_firth(models):
    r = models.cond_logit(fx.separated_data(), "y", "t", [], "g")
    assert r.method == "firth"
    assert math.isfinite(r.log_or) and math.isfinite(r.se)
    assert r.log_or > 0
    assert r.se > 0


def test_cond_logit_accepts_covariates(models):
    df = fx.stratified_logit_data(n_groups=150, log_or=0.5)
    df["x"] = np.random.default_rng(0).normal(size=len(df))
    r = models.cond_logit(df, "y", "t", ["x"], "g")
    assert abs(r.log_or - 0.5) < 3.5 * r.se


def test_cond_logit_quasi_separation_uses_firth(models):
    bad = []
    for seed in range(30):
        df = fx.quasi_separated_data(seed=seed)
        r = models.cond_logit(df, "y", "t", [], "g")
        ok = (
            r.method == "firth"
            and math.isfinite(r.log_or)
            and math.isfinite(r.se)
            and abs(r.log_or) <= 8
        )
        if not ok:
            bad.append((seed, r.method, r.log_or))
    assert not bad, bad


def test_cond_logit_keeps_outcome_varying_strata_without_treatment_variation(models):
    from statsmodels.discrete.conditional_models import ConditionalLogit
    import warnings

    df = fx.covariate_stratum_data()
    ov = df[df.groupby("g")["y"].transform("nunique") > 1]
    n_ov = ov["g"].nunique()
    n_tv = ov[ov.groupby("g")["t"].transform("nunique") > 1]["g"].nunique()
    assert n_ov > n_tv > 0  # some outcome-varying strata have constant treatment
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        ref = ConditionalLogit(
            ov["y"].to_numpy(float), ov[["t", "x"]].to_numpy(float), groups=ov["g"].to_numpy()
        ).fit(disp=False)
    r = models.cond_logit(df, "y", "t", ["x"], "g")
    assert r.method == "clogit"
    assert r.n_groups_informative == n_ov
    assert r.log_or == pytest.approx(float(ref.params[0]), abs=1e-6)
    assert r.se == pytest.approx(float(ref.bse[0]), abs=1e-6)


# ---------------------------------------------------------------- meta_hksj

def _hand_hksj(y, se):
    y, se = np.array(y), np.array(se)
    k = len(y)
    w = 1 / se**2
    mu_f = (w * y).sum() / w.sum()
    Q = (w * (y - mu_f) ** 2).sum()
    C = w.sum() - (w**2).sum() / w.sum()
    tau2 = max(0.0, (Q - (k - 1)) / C)
    ws = 1 / (se**2 + tau2)
    mu = (ws * y).sum() / ws.sum()
    q = (ws * (y - mu) ** 2).sum() / (k - 1)
    sd = math.sqrt(q / ws.sum())
    ci = lambda lvl: (mu - stats.t.ppf(lvl, k - 1) * sd, mu + stats.t.ppf(lvl, k - 1) * sd)
    return mu, tau2, ci(0.975), ci(0.95)


def _hand_qprofile(y, se):
    y, se = np.array(y), np.array(se)
    k = len(y)

    def qgen(t):
        w = 1 / (se**2 + t)
        mu = (w * y).sum() / w.sum()
        return (w * (y - mu) ** 2).sum()

    def bound(target):
        if qgen(0.0) < target:
            return 0.0
        hi = 1.0
        while qgen(hi) > target:
            hi *= 2
        return brentq(lambda t: qgen(t) - target, 0.0, hi)

    return bound(stats.chi2.ppf(0.975, k - 1)), bound(stats.chi2.ppf(0.025, k - 1))


def test_meta_hksj_matches_hand_values(models):
    y, se = fx.hksj_example()
    mu, tau2, ci95, ci90 = _hand_hksj(y, se)
    assert tau2 > 0  # the example must exercise the heterogeneity path
    p = models.meta_hksj([est(models, a, b) for a, b in zip(y, se)])
    assert p.k == 4
    assert p.log_or == pytest.approx(mu, abs=1e-9)
    assert p.tau2 == pytest.approx(tau2, abs=1e-9)
    assert p.ci95[0] == pytest.approx(ci95[0], abs=1e-9)
    assert p.ci95[1] == pytest.approx(ci95[1], abs=1e-9)
    assert p.ci90[0] == pytest.approx(ci90[0], abs=1e-9)
    assert p.ci90[1] == pytest.approx(ci90[1], abs=1e-9)


def test_meta_hksj_uses_untruncated_q(models):
    # Homogeneous-ish studies: q < 1, so truncating at 1 would widen the interval.
    y, se = [0.30, 0.31, 0.29, 0.30], [0.5, 0.5, 0.5, 0.5]
    mu, tau2, ci95, _ = _hand_hksj(y, se)
    assert tau2 == 0
    p = models.meta_hksj([est(models, a, b) for a, b in zip(y, se)])
    assert p.ci95[1] - p.ci95[0] == pytest.approx(ci95[1] - ci95[0], abs=1e-9)
    assert p.ci95[1] - p.ci95[0] < 0.1


def test_meta_hksj_tau2_ci_q_profile(models):
    y, se = fx.hksj_example()
    lo, hi = _hand_qprofile(y, se)
    p = models.meta_hksj([est(models, a, b) for a, b in zip(y, se)])
    assert p.tau2_ci[0] >= 0
    assert p.tau2_ci[0] <= p.tau2 <= p.tau2_ci[1]
    assert p.tau2_ci[0] == pytest.approx(lo, abs=1e-4)
    assert p.tau2_ci[1] == pytest.approx(hi, abs=1e-3)


def test_meta_hksj_tau2_ci_lower_bound_nonnegative_when_homogeneous(models):
    p = models.meta_hksj([est(models, 0.2, s) for s in (0.1, 0.2, 0.3)])
    assert p.tau2 == 0
    assert p.tau2_ci[0] == 0
    assert p.tau2_ci[1] >= 0


def test_meta_hksj_k1_returns_single_estimate_with_normal_ci(models):
    p = models.meta_hksj([est(models, 0.4, 0.1)])
    assert p.k == 1
    assert p.log_or == pytest.approx(0.4)
    assert p.tau2 == 0
    assert p.ci95[0] == pytest.approx(0.4 - 1.959964 * 0.1, abs=1e-5)
    assert p.ci95[1] == pytest.approx(0.4 + 1.959964 * 0.1, abs=1e-5)
    assert p.ci90[0] == pytest.approx(0.4 - 1.644854 * 0.1, abs=1e-5)
    assert p.ci90[1] == pytest.approx(0.4 + 1.644854 * 0.1, abs=1e-5)
    assert len(p.tau2_ci) == 2
    assert math.isnan(p.tau2_ci[0]) and math.isnan(p.tau2_ci[1])


# ---------------------------------------------------------------- tost

M = (0.80, 1.25)
LO, HI = math.log(0.80), math.log(1.25)


def test_tost_effect_detected(models):
    assert models.tost(0.5, (0.2, 0.8), (0.3, 0.7), M) == "effect detected"
    assert models.tost(-0.5, (-0.8, -0.2), (-0.7, -0.3), M) == "effect detected"


def test_tost_equivalent(models):
    assert models.tost(0.0, (-0.12, 0.12), (-0.1, 0.1), M) == "equivalent to no effect"


def test_tost_inconclusive(models):
    assert models.tost(0.05, (-0.4, 0.5), (-0.3, 0.4), M) == "inconclusive"


def test_tost_margin_boundaries(models):
    eps = 1e-6
    ci95 = (-0.5, 0.5)
    assert models.tost(0.0, ci95, (LO + eps, HI - eps), M) == "equivalent to no effect"
    assert models.tost(0.0, ci95, (LO + eps, HI + eps), M) == "inconclusive"
    assert models.tost(0.0, ci95, (LO - eps, HI - eps), M) == "inconclusive"


def test_tost_uses_passed_ci95_for_zero_boundary(models):
    eps = 1e-6
    ci90 = (0.05, 0.35)  # outside the margin, so only ci95 decides
    assert models.tost(0.2, (eps, 0.4), ci90, M) == "effect detected"
    assert models.tost(0.2, (-eps, 0.4), ci90, M) == "inconclusive"
    assert models.tost(-0.2, (-0.4, -eps), (-0.35, -0.05), M) == "effect detected"
    assert models.tost(-0.2, (-0.4, eps), (-0.35, -0.05), M) == "inconclusive"


def test_tost_effect_takes_precedence_over_equivalence(models):
    # ci95 excludes 0 even though ci90 sits inside the margin.
    assert models.tost(0.02, (0.001, 0.04), (0.005, 0.035), M) == "effect detected"


def test_tost_never_derives_intervals(models):
    # Deriving ci95 from ci90 with normal ratios would give about (0.034, 0.166),
    # which excludes 0 and would say "effect detected". The passed ci95 contains 0.
    assert models.tost(0.1, (-0.01, 0.30), (0.05, 0.15), M) == "equivalent to no effect"
    # Mirror: the passed ci95 excludes 0 while ci90 is wide. Deriving ci95 from ci90
    # would give an interval containing 0.
    assert models.tost(0.1, (0.02, 0.18), (-0.3, 0.5), M) == "effect detected"
    assert models.tost(0.1, (-0.5, 0.7), (-0.05, 0.15), M) == "equivalent to no effect"


def test_tost_regression_hksj_ci95_covers_zero_ci90_does_not(models):
    z = np.array([-1.2, -0.7, 0.1, 0.6, 1.2])
    z = (z - z.mean()) / z.std(ddof=1)
    s = 0.3
    mu = 2.4 * s / math.sqrt(5)
    ests = [est(models, float(mu + s * zi), 0.12) for zi in z]
    p = models.meta_hksj(ests)
    assert p.ci95[0] < 0 < p.ci95[1]
    assert p.ci90[0] > 0
    v = models.tost(p.log_or, p.ci95, p.ci90, M)
    assert v != "effect detected"


def test_tost_null_type_i_rate_k3(models):
    rng = np.random.default_rng(2026)
    ses = (0.10, 0.15, 0.20)
    hits = 0
    n = 2000
    for _ in range(n):
        ests = [est(models, float(rng.normal(0, s)), s) for s in ses]
        p = models.meta_hksj(ests)
        hits += models.tost(p.log_or, p.ci95, p.ci90, M) == "effect detected"
    assert hits / n <= 0.065, hits / n


# ---------------------------------------------------------------- holm

def test_holm_hand_example(models):
    p = {"a": 0.01, "b": 0.04, "c": 0.03, "d": 0.005}
    out = models.holm(p)
    # sorted: d .005*4=.02, a .01*3=.03, c .03*2=.06, b .04*1=.04 -> monotone .06
    assert out["d"] == pytest.approx(0.02)
    assert out["a"] == pytest.approx(0.03)
    assert out["c"] == pytest.approx(0.06)
    assert out["b"] == pytest.approx(0.06)
    assert set(out) == set(p)


def test_holm_caps_at_one_and_single(models):
    assert models.holm({"x": 0.7}) == {"x": pytest.approx(0.7)}
    out = models.holm({"x": 0.6, "y": 0.9})
    assert out["x"] == pytest.approx(1.0)
    assert out["y"] == pytest.approx(1.0)


# ---------------------------------------------------------------- permutation_share

def test_permutation_share_deterministic(models):
    df = fx.stratified_flag_data()
    a = models.permutation_share(df, "label", "flag", "stratum", draws=300, seed=7)
    b = models.permutation_share(df, "label", "flag", "stratum", draws=300, seed=7)
    assert a == b


def test_permutation_share_independent_gives_large_p(models):
    df = fx.exactly_independent_flag_data()
    obs, p = models.permutation_share(df, "label", "flag", "stratum", draws=500, seed=1)
    assert p > 0.5


def test_permutation_share_strong_association_gives_small_p(models):
    rng = np.random.default_rng(12)
    n = 600
    label = rng.random(n) < 0.5
    flag = np.where(label, rng.random(n) < 0.8, rng.random(n) < 0.2)
    df = pd.DataFrame({"stratum": rng.choice(["a", "b", "c"], n), "label": label, "flag": flag})
    _, p = models.permutation_share(df, "label", "flag", "stratum", draws=500, seed=1)
    assert p < 0.01


def test_permutation_share_permutes_within_strata(models):
    df = fx.stratified_flag_data()
    df["all"] = 0
    _, p_unstrat = models.permutation_share(df, "label", "flag", "all", draws=500, seed=2)
    _, p_strat = models.permutation_share(df, "label", "flag", "stratum", draws=500, seed=2)
    assert p_unstrat < 0.01  # confounded by stratum
    assert p_strat > 0.05  # independent once stratum is respected


# ---------------------------------------------------------------- median_reg

def test_median_reg_recovers_planted_shift(models):
    df = fx.median_shift_data(shift=2.0)
    r = models.median_reg(df, "y", "t", ["w"], "cluster", boot=200, seed=3)
    assert r.se > 0
    assert abs(r.log_or - 2.0) < 3 * r.se
    assert abs(r.log_or - 2.0) < 0.6


def test_median_reg_deterministic(models):
    df = fx.median_shift_data()
    a = models.median_reg(df, "y", "t", [], "cluster", boot=60, seed=4)
    b = models.median_reg(df, "y", "t", [], "cluster", boot=60, seed=4)
    assert (a.log_or, a.se) == (b.log_or, b.se)


def test_median_reg_bootstrap_is_clustered(models):
    # Treatment varies only between clusters and clusters share a big random shift,
    # so resampling clusters gives a far larger SE than resampling rows.
    df = fx.median_shift_data(cluster_sd=3.0, shift=0.0)
    clustered = models.median_reg(df, "y", "t", [], "cluster", boot=150, seed=5)
    rowwise = models.median_reg(df, "y", "t", [], "rid", boot=150, seed=5)
    assert clustered.se > 2 * rowwise.se


# ---------------------------------------------------------------- simulate.plant

def test_plant_preserves_structure_and_adds_binary_outcome(simulate):
    t = fx.make_treatment(seed=0)
    out = simulate.plant(t, odds_ratio=1.0, base_rate=0.25, icc=0.05, seed=1)
    for c in ("cross_family", "solver", "week"):
        pd.testing.assert_series_equal(out[c], t[c])
    new = [c for c in out.columns if c not in t.columns]
    assert len(new) == 1
    y = out[new[0]]
    assert set(y.unique()) <= {0, 1, True, False}
    assert abs(float(y.mean()) - 0.25) < 0.06
    assert len(out) == len(t)


def test_plant_deterministic_and_seed_sensitive(simulate):
    t = fx.make_treatment(seed=0)
    a = simulate.plant(t, 1.5, 0.2, 0.05, seed=1)
    b = simulate.plant(t, 1.5, 0.2, 0.05, seed=1)
    c = simulate.plant(t, 1.5, 0.2, 0.05, seed=2)
    pd.testing.assert_frame_equal(a, b)
    assert not a.equals(c)


def test_plant_does_not_mutate_input(simulate):
    t = fx.make_treatment(seed=0)
    before = t.copy()
    simulate.plant(t, 1.5, 0.2, 0.05, seed=1)
    pd.testing.assert_frame_equal(t, before)


# ---------------------------------------------------------------- realistic design

def _ref_fit(d, ycol, cov, group="solver"):
    """Rank-reduced statsmodels ConditionalLogit on outcome-varying strata."""
    import warnings
    from statsmodels.discrete.conditional_models import ConditionalLogit

    ov = d[d.groupby(group)[ycol].transform("nunique") > 1]
    X = ov[["t"] + list(cov)].astype(float)
    Xd = X - X.groupby(ov[group]).transform("mean")
    keep = []
    for c in X.columns:
        if np.linalg.matrix_rank(Xd[keep + [c]].to_numpy(), tol=1e-9) > len(keep):
            keep.append(c)
    assert keep[0] == "t"
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        res = ConditionalLogit(
            ov[ycol].to_numpy(float), X[keep].to_numpy(), groups=ov[group].to_numpy()
        ).fit(method="newton", maxiter=2000, disp=False)
    return float(res.params[0]), ov, Xd


def test_realistic_design_uses_clogit_and_matches_reference(models, simulate):
    n_clogit = 0
    n = 30
    for seed in range(n):
        orr = 1.0 if seed % 2 == 0 else 1.5
        f = fx.primary(fx.realistic_frame(seed))
        d = simulate.plant(f, odds_ratio=orr, base_rate=0.25, icc=0.05, seed=seed)
        d = d.assign(t=d["cross_family"].astype(int), y=d["y_sim"].astype(int))
        cov = fx.realistic_covariates(d)
        r = models.cond_logit(d, "y", "t", cov, "solver")
        if r.method != "clogit":
            continue
        n_clogit += 1
        ref, ov, Xd = _ref_fit(d, "y", cov)
        assert r.log_or == pytest.approx(ref, abs=1e-4), (seed, r.log_or, ref)
        constant = {c for c in cov if np.allclose(Xd[c].to_numpy(), 0)}
        assert any(c.startswith("cf_") for c in constant)
        assert constant <= set(r.dropped_covariates), (seed, constant - set(r.dropped_covariates))
        assert "t" not in set(r.dropped_covariates)
        assert r.n_groups_informative == ov["solver"].nunique()
    assert n_clogit >= 28, n_clogit


def test_cond_logit_treatment_constant_within_strata_is_unidentified(models):
    r = models.cond_logit(fx.constant_treatment_data(), "y", "t", ["x"], "g")
    assert r.method == "unidentified"
    assert math.isnan(r.log_or)


def test_firth_on_rank_deficient_design_drops_columns_and_converges(models):
    d = fx.separated_rank_deficient_data()
    r = models.cond_logit(d, "y", "t", ["c", "x", "x2"], "g")
    assert r.method == "firth"
    assert math.isfinite(r.log_or) and math.isfinite(r.se)
    assert r.log_or > 0
    dropped = set(r.dropped_covariates)
    assert "c" in dropped
    assert len(dropped & {"x", "x2"}) == 1


def test_firth_forced_nonconvergence_is_failed_never_a_number(models, monkeypatch):
    d = fx.separated_data()
    ok = models.cond_logit(d, "y", "t", [], "g")
    assert ok.method == "firth"

    orig = models._firth
    monkeypatch.setattr(models, "_firth", lambda *a, **k: orig(*a, **{**k, "max_iter": 1}))
    for name in dir(models):
        v = getattr(models, name)
        if isinstance(v, int) and not isinstance(v, bool) and "MAX" in name.upper() and "ITER" in name.upper():
            monkeypatch.setattr(models, name, 1)
    r = models.cond_logit(d, "y", "t", [], "g")
    assert r.method == "failed"
    assert math.isnan(r.log_or)


def test_cond_logit_joint_separation_by_treatment_and_covariate_uses_firth(models):
    r = models.cond_logit(fx.joint_separated_data(), "y", "t", ["x"], "g")
    assert r.method == "firth"
    assert math.isfinite(r.log_or) and abs(r.log_or) < 8
    assert math.isfinite(r.se)


# ---------------------------------------------------------------- AT13 / AT14 (realistic design)

def _outcome_col(planted, t):
    return [c for c in planted.columns if c not in t.columns][0]


def _fit(models, df, ycol):
    d = df.assign(t=df["cross_family"].astype(int), y=df[ycol].astype(int))
    return models.cond_logit(d, "y", "t", fx.realistic_covariates(d), "solver")


def test_at13_planted_or_recovered_in_90_of_100(models, simulate):
    t = fx.primary(fx.realistic_frame(seed=100))
    assert 500 <= len(t) <= 900
    assert t["solver"].nunique() >= 45
    covered = 0
    for seed in range(100):
        d = simulate.plant(t, odds_ratio=1.5, base_rate=0.25, icc=0.05, seed=seed)
        r = _fit(models, d, _outcome_col(d, t))
        if r.log_or - 1.96 * r.se <= math.log(1.5) <= r.log_or + 1.96 * r.se:
            covered += 1
    assert covered >= 90, covered


def test_at14_placebo_shuffle_covers_zero_in_90_of_100(models, simulate):
    t = fx.primary(fx.realistic_frame(seed=101))
    covered = 0
    for seed in range(100):
        d = simulate.plant(t, odds_ratio=1.5, base_rate=0.25, icc=0.05, seed=seed)
        ycol = _outcome_col(d, t)
        rng = np.random.default_rng(10_000 + seed)
        d = d.copy()
        d["cross_family"] = d.groupby("solver")["cross_family"].transform(
            lambda s: rng.permutation(s.to_numpy())
        )
        r = _fit(models, d, ycol)
        if r.log_or - 1.96 * r.se <= 0 <= r.log_or + 1.96 * r.se:
            covered += 1
    assert covered >= 90, covered


def test_at13_or_one_equivalence_rate_matches_power_prediction(models, simulate):
    power = importlib.import_module("analysis.power")
    frame = fx.realistic_frame(seed=100)
    t = fx.primary(frame)
    sims = 150
    predicted = power.equivalence_power(frame, 0.25, icc=0.05, sims=sims, seed=20261017)
    n = 100
    hits = 0
    for seed in range(n):
        d = simulate.plant(t, odds_ratio=1.0, base_rate=0.25, icc=0.05, seed=seed)
        r = _fit(models, d, _outcome_col(d, t))
        c95 = (r.log_or - 1.959964 * r.se, r.log_or + 1.959964 * r.se)
        c90 = (r.log_or - 1.644854 * r.se, r.log_or + 1.644854 * r.se)
        hits += models.tost(r.log_or, c95, c90, (0.80, 1.25)) == "equivalent to no effect"
    rate = hits / n
    half = 2.576 * math.sqrt(predicted * (1 - predicted) * (1 / n + 1 / sims))
    assert predicted - half <= rate <= predicted + half, (rate, predicted, half)
