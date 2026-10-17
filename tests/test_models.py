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
    return models.Estimate(log_or=log_or, se=se, n=100, n_groups_informative=10, method="clogit")


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


# ---------------------------------------------------------------- tost

M = (0.80, 1.25)
LO, HI = math.log(0.80), math.log(1.25)


def _ci90_for(center, se):
    return (center - 1.644854 * se, center + 1.644854 * se)


def test_tost_effect_detected(models):
    assert models.tost(0.5, (0.3, 0.7), M) == "effect detected"
    assert models.tost(-0.5, (-0.7, -0.3), M) == "effect detected"


def test_tost_equivalent(models):
    assert models.tost(0.0, (-0.1, 0.1), M) == "equivalent to no effect"


def test_tost_inconclusive(models):
    assert models.tost(0.05, (-0.3, 0.4), M) == "inconclusive"


def test_tost_margin_boundaries(models):
    eps = 1e-6
    assert models.tost(0.0, (LO + eps, HI - eps), M) == "equivalent to no effect"
    assert models.tost(0.0, (LO + eps, HI + eps), M) == "inconclusive"
    assert models.tost(0.0, (LO - eps, HI - eps), M) == "inconclusive"


def test_tost_zero_boundary_of_95_interval(models):
    se = 0.1
    just_out = 1.96 * se * 1.02
    just_in = 1.96 * se * 0.98
    assert models.tost(just_out, _ci90_for(just_out, se), M) == "effect detected"
    assert models.tost(-just_out, _ci90_for(-just_out, se), M) == "effect detected"
    assert models.tost(just_in, _ci90_for(just_in, se), M) == "inconclusive"


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


# ---------------------------------------------------------------- AT13 / AT14

def _outcome_col(planted, t):
    return [c for c in planted.columns if c not in t.columns][0]


def _fit(models, df, ycol):
    d = df.assign(t=df["cross_family"].astype(int), y=df[ycol].astype(int))
    return models.cond_logit(d, "y", "t", ["log_prior_rows"], "solver")


def test_at13_planted_or_recovered_in_90_of_100(models, simulate):
    t = fx.make_treatment(seed=100)
    assert 800 <= len(t) <= 1250
    assert t["solver"].nunique() == 40
    covered = 0
    for seed in range(100):
        d = simulate.plant(t, odds_ratio=1.5, base_rate=0.25, icc=0.05, seed=seed)
        r = _fit(models, d, _outcome_col(d, t))
        if r.log_or - 1.96 * r.se <= math.log(1.5) <= r.log_or + 1.96 * r.se:
            covered += 1
    assert covered >= 90, covered


def test_at14_placebo_shuffle_covers_zero_in_90_of_100(models, simulate):
    t = fx.make_treatment(seed=101)
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
