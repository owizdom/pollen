"""Statistical models for the pollination study (spec 0001 s5.1-5.4)."""
from __future__ import annotations

import math
import warnings
from dataclasses import dataclass

import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy import stats
from scipy.special import expit
from scipy.optimize import brentq
from statsmodels.discrete.conditional_models import ConditionalLogit


@dataclass(frozen=True)
class Estimate:
    log_or: float
    se: float
    n: int
    n_groups_informative: int
    method: str
    dropped_covariates: tuple = ()


@dataclass(frozen=True)
class Pooled:
    log_or: float
    ci95: tuple
    ci90: tuple
    tau2: float
    tau2_ci: tuple
    k: int


# ------------------------------------------------------------------ cond_logit

FIRTH_MAX_ITER = 1000
CLOGIT_MAX_ITER = 2000
_NAN = float("nan")


def _penalised_ll(X, y, beta):
    eta = X @ beta
    mu = expit(eta)
    W = mu * (1 - mu)
    info = X.T @ (X * W[:, None])
    sign, logdet = np.linalg.slogdet(info)
    if sign <= 0:
        logdet = -1e10
    return float((y * eta - np.logaddexp(0, eta)).sum() + 0.5 * logdet)


def _solve(info, rhs):
    """Solve info @ x = rhs; least squares when ill-conditioned (cond > 1e12)."""
    if np.linalg.cond(info) > 1e12:
        return np.linalg.lstsq(info, rhs, rcond=None)[0]
    return np.linalg.solve(info, rhs)


def _penalised_score(X, y, beta):
    mu = expit(X @ beta)
    W = mu * (1 - mu)
    info = X.T @ (X * W[:, None])
    inv = np.linalg.pinv(info, hermitian=True)
    h = W * ((X @ inv) * X).sum(axis=1)
    return X.T @ (y - mu + h * (0.5 - mu)), info


def _firth(X: np.ndarray, y: np.ndarray, max_iter=None, tol: float = 1e-9):
    """Jeffreys-penalised logistic regression.

    The penalised likelihood is invariant to invertible linear maps of the columns, so the
    fit runs on an orthonormal basis of X (QR) and maps back. Returns (beta, cov, converged)."""
    X = np.asarray(X, float)
    Q, R = np.linalg.qr(X)
    if np.min(np.abs(np.diag(R))) < 1e-10 * max(np.max(np.abs(np.diag(R))), 1e-300):
        return _firth_core(X, y, max_iter, tol)  # rank-deficient: fit as given
    gamma, cov_g, ok = _firth_core(Q * np.sqrt(len(y)), y, max_iter, tol)
    Rinv = np.linalg.inv(R / np.sqrt(len(y)))
    return Rinv @ gamma, Rinv @ cov_g @ Rinv.T, ok


def _firth_core(X: np.ndarray, y: np.ndarray, max_iter=None, tol: float = 1e-9):
    """Newton with step-halving on the penalised log-likelihood. Converged means the
    penalised score is below tol."""
    max_iter = FIRTH_MAX_ITER if max_iter is None else max_iter
    n, p = X.shape
    beta = np.zeros(p)
    ll = _penalised_ll(X, y, beta)
    converged = False
    for _ in range(max_iter):
        score, info = _penalised_score(X, y, beta)
        if np.max(np.abs(score)) < tol:
            converged = True
            break
        step = _solve(info, score)
        mx = np.max(np.abs(step))
        if not np.isfinite(mx):
            break
        if mx > 5:
            step = step * (5 / mx)
        t = 1.0
        for _ in range(40):
            new = beta + t * step
            new_ll = _penalised_ll(X, y, new)
            if new_ll >= ll - 1e-10 * (1 + abs(ll)):
                break
            t /= 2
        else:
            break  # no improving step found
        beta, ll = new, new_ll
    else:
        score, info = _penalised_score(X, y, beta)
        converged = bool(np.max(np.abs(score)) < tol)
    mu = expit(X @ beta)
    W = mu * (1 - mu)
    cov = np.linalg.pinv(X.T @ (X * W[:, None]), hermitian=True)
    return beta, cov, converged


def _firth_fit(d, outcome, treatment, keep, group, dropped) -> Estimate:
    dummies = pd.get_dummies(d[group].astype(str), dtype=float)
    X = np.column_stack([d[c].to_numpy(float) for c in [treatment] + keep] + [dummies.to_numpy()])
    y = d[outcome].to_numpy(float)
    n_g = int(d[group].nunique())
    beta, cov, ok = _firth(X, y)
    if not ok or not np.all(np.isfinite(beta)) or not np.isfinite(cov[0, 0]) or cov[0, 0] < 0:
        return Estimate(_NAN, _NAN, int(len(d)), n_g, "failed", tuple(dropped))
    return Estimate(float(beta[0]), float(math.sqrt(cov[0, 0])), int(len(d)), n_g, "firth", tuple(dropped))


def _independent_columns(d, treatment, covariates, group):
    """Greedy pivoted QR on the stratum-demeaned design, treatment first.
    Returns (kept covariates, dropped covariates, treatment_identified)."""
    cols = [treatment] + list(covariates)
    X = d[cols].to_numpy(float)
    Xd = X - pd.DataFrame(X).groupby(d[group].to_numpy()).transform("mean").to_numpy()
    basis = []
    kept = []
    for j, c in enumerate(cols):
        v = Xd[:, j].copy()
        for q in basis:
            v -= q * (q @ v)
        for q in basis:  # second pass for stability
            v -= q * (q @ v)
        nv = np.linalg.norm(v)
        scale = max(np.linalg.norm(X[:, j]), 1e-12)
        if nv <= 1e-8 * scale or nv <= 1e-10:
            if j == 0:
                return [], list(covariates), False
            continue
        basis.append(v / nv)
        if j > 0:
            kept.append(c)
    dropped = [c for c in covariates if c not in kept]
    return kept, dropped, True


def _quasi_separated(d, outcome, treatment, group) -> bool:
    """Exact criterion for a binary treatment: in every stratum the treated
    successes equal min(n_t, s) (positive direction) or max(0, s - n_c)
    (negative direction)."""
    t = (d[treatment].to_numpy() > 0)
    y = (d[outcome].to_numpy() > 0)
    f = pd.DataFrame({"g": d[group].to_numpy(), "t": t, "y": y, "ty": t & y}).groupby("g")
    n_t = f["t"].sum().to_numpy()
    n = f["t"].size().to_numpy()
    s = f["y"].sum().to_numpy()
    ts = f["ty"].sum().to_numpy()
    n_c = n - n_t
    pos = np.all(ts == np.minimum(n_t, s))
    neg = np.all(ts == np.maximum(0, s - n_c))
    return bool(pos or neg)


def cond_logit(df, outcome, treatment, covariates, group) -> Estimate:
    covariates = list(covariates)
    d = df[[outcome, treatment, group] + covariates].dropna().copy()
    d = d[d.groupby(group)[outcome].transform("nunique") > 1]
    n_inf = int(d[group].nunique())
    if n_inf == 0:
        return Estimate(_NAN, _NAN, 0, 0, "unidentified")
    keep, dropped, ident = _independent_columns(d, treatment, covariates, group)
    if not ident:
        return Estimate(_NAN, _NAN, int(len(d)), n_inf, "unidentified", tuple(dropped))
    if _quasi_separated(d, outcome, treatment, group):
        return _firth_fit(d, outcome, treatment, keep, group, dropped)

    exog = d[[treatment] + keep].to_numpy(float)
    endog = d[outcome].to_numpy(float)
    bad = True
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            model = ConditionalLogit(endog, exog, groups=d[group].to_numpy())
            res = model.fit(method="newton", maxiter=CLOGIT_MAX_ITER, disp=False)
            params = np.asarray(res.params, float)
            bse = np.asarray(res.bse, float)
            bad = (
                not np.all(np.isfinite(params))
                or not np.all(np.isfinite(bse))
                or np.max(np.abs(params)) > 15
                or np.max(bse) > 15
                or np.min(bse) <= 0
            )
            if not bad:
                # the wrapper hides statsmodels' convergence flag, so check the score directly
                bad = bool(np.max(np.abs(model.score(params))) > 1e-5)
            if not bad:
                # likelihood still rising along the fitted direction means no finite MLE
                bad = bool(model.loglike(2 * params) > model.loglike(params) + 1e-8)
        except Exception:
            bad = True
    if bad:
        return _firth_fit(d, outcome, treatment, keep, group, dropped)
    return Estimate(float(params[0]), float(bse[0]), int(len(d)), n_inf, "clogit", tuple(dropped))


# ------------------------------------------------------------------ meta_hksj

def _q_profile(y, se, k):
    def qgen(t):
        w = 1 / (se**2 + t)
        mu = (w * y).sum() / w.sum()
        return float((w * (y - mu) ** 2).sum())

    def bound(target):
        if qgen(0.0) < target:
            return 0.0
        hi = 1.0
        for _ in range(200):
            if qgen(hi) <= target:
                break
            hi *= 2
        return float(brentq(lambda t: qgen(t) - target, 0.0, hi, xtol=1e-12))

    return bound(stats.chi2.ppf(0.975, k - 1)), bound(stats.chi2.ppf(0.025, k - 1))


def meta_hksj(estimates) -> Pooled:
    y = np.array([e.log_or for e in estimates], float)
    se = np.array([e.se for e in estimates], float)
    k = len(y)
    if k == 0:
        raise ValueError("no estimates")
    if k == 1:
        z95, z90 = stats.norm.ppf(0.975), stats.norm.ppf(0.95)
        return Pooled(
            float(y[0]),
            (float(y[0] - z95 * se[0]), float(y[0] + z95 * se[0])),
            (float(y[0] - z90 * se[0]), float(y[0] + z90 * se[0])),
            0.0,
            (float("nan"), float("nan")),
            1,
        )
    w = 1 / se**2
    mu_f = (w * y).sum() / w.sum()
    Q = (w * (y - mu_f) ** 2).sum()
    C = w.sum() - (w**2).sum() / w.sum()
    tau2 = max(0.0, (Q - (k - 1)) / C)
    ws = 1 / (se**2 + tau2)
    mu = (ws * y).sum() / ws.sum()
    q = (ws * (y - mu) ** 2).sum() / (k - 1)
    sd = math.sqrt(q / ws.sum())

    def ci(level):
        t = stats.t.ppf(level, k - 1)
        return (float(mu - t * sd), float(mu + t * sd))

    lo, hi = _q_profile(y, se, k)
    return Pooled(float(mu), ci(0.975), ci(0.95), float(tau2), (lo, hi), k)


# ------------------------------------------------------------------ tost / holm

def tost(log_or, ci95, ci90, margin) -> str:
    if ci95[0] > 0 or ci95[1] < 0:
        return "effect detected"
    if ci90[0] > math.log(margin[0]) and ci90[1] < math.log(margin[1]):
        return "equivalent to no effect"
    return "inconclusive"


def holm(pvals: dict) -> dict:
    items = sorted(pvals.items(), key=lambda kv: kv[1])
    m = len(items)
    out, running = {}, 0.0
    for i, (name, p) in enumerate(items):
        running = max(running, min(1.0, (m - i) * p))
        out[name] = running
    return out


# ------------------------------------------------------------------ permutation

def permutation_share(df, label, flag, strata, draws=10000, seed=0):
    """Share of label rows carrying the flag, and a two-sided permutation p-value
    from shuffling the label within strata (+1 corrected).

    Shuffling the label within a stratum makes the number of flagged label rows
    hypergeometric, so the null is sampled from that distribution directly."""
    lab = df[label].to_numpy(bool)
    flg = df[flag].to_numpy(bool)
    n_label = int(lab.sum())
    if n_label == 0:
        return float("nan"), 1.0
    observed_count = int((lab & flg).sum())
    observed = observed_count / n_label
    s = pd.DataFrame({"s": df[strata].to_numpy(), "l": lab, "f": flg}).groupby("s")
    N = s["l"].size().to_numpy()
    L = s["l"].sum().to_numpy().astype(int)
    F = s["f"].sum().to_numpy().astype(int)
    rng = np.random.default_rng(seed)
    sims = rng.hypergeometric(F, N - F, L, size=(draws, len(N))).sum(axis=1)
    expected = float((L * F / N).sum())
    b = int((np.abs(sims - expected) >= abs(observed_count - expected) - 1e-9).sum())
    return observed, (b + 1) / (draws + 1)


# ------------------------------------------------------------------ median_reg

def _qr_coef(d, outcome, treatment, covariates):
    X = sm.add_constant(d[[treatment] + list(covariates)].to_numpy(float), has_constant="add")
    res = sm.QuantReg(d[outcome].to_numpy(float), X).fit(q=0.5, max_iter=5000)
    return float(res.params[1])


def median_reg(df, outcome, treatment, covariates, cluster, boot=2000, seed=0) -> Estimate:
    covariates = list(covariates)
    d = df[[outcome, treatment, cluster] + covariates].dropna().reset_index(drop=True)
    point = _qr_coef(d, outcome, treatment, covariates)
    groups = {k: v.to_numpy() for k, v in d.groupby(cluster).groups.items()}
    keys = list(groups)
    rng = np.random.default_rng(seed)
    draws = []
    for _ in range(boot):
        pick = rng.integers(0, len(keys), len(keys))
        idx = np.concatenate([groups[keys[i]] for i in pick])
        b = d.iloc[idx]
        if b[treatment].nunique() < 2:
            continue
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                draws.append(_qr_coef(b, outcome, treatment, covariates))
        except Exception:
            continue
    se = float(np.std(draws, ddof=1)) if len(draws) > 1 else float("nan")
    return Estimate(point, se, int(len(d)), len(keys), "quantreg")
