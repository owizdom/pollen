"""Track E3: analysis drivers (spec 0001 sections 4, 5, 5.8; AT6, AT7, AT8).

Output contracts pinned here (the spec names the contents, not the key names):

results/confirmatory.json (sorted keys, floats at 6 significant digits)
  {"benchmarks": {name: {"estimate": {"log_or","se","n","n_groups_informative","method"},
                         "counts": {"analysis_rows","fit_rows","strata_kept",
                                    "strata_no_treatment_variation","firth",
                                    "excluded": {"own_lineage","multi_parent","novel",
                                                 "unknown_family","outside_window"}}}},
   "pooled": {"log_or","ci95":[lo,hi],"ci90":[lo,hi],"tau2","k"},
   "verdict": str,                       # models.tost on the pooled result and margin
   "case_study": {"benchmark": str, "verdict": str},   # ecdsa.fail, else the first benchmark
   "margin": [lo, hi],
   "excluded_benchmarks": {name: reason}}   # failed/unidentified fits; empty when none
confirmatory.run must build its rows and design through analysis.design.primary_rows and
analysis.design.build (called as module attributes); a benchmark whose estimate is not finite
(method "failed" or "unidentified") is listed in excluded_benchmarks and not counted in pooled k.
results/secondary.json
  {"tests": [{"hypothesis": "H2"|"H3a"|"H3b"|"H4"|"H5", "benchmark": str,
              "status": "confirmatory"|"descriptive", "min_arm_events": int,
              "p": float|None, "p_holm": float|None}]}      # member id is "<hypothesis>:<benchmark>"
results/sensitivity.json
  {"sensitivities": {"s1_*".."s9_*": {"pooled": {"log_or","ci95"}} | {"not_applicable": reason}}}
results/exploratory.json   {"label": "exploratory", "E1": ..., "E2": ...}
paper/figures/*.png|*.pdf, paper/numbers.tex

Signatures: confirmatory.run(root), secondary.run(root, draws=, boot=), sensitivity.run(root),
exploratory.run(root, boot=), figures.run(root), numbers.write(root),
run.main(root, draws=, boot=), study.benchmarks(snapshot, lineage_root=).
"""
from __future__ import annotations

import importlib
import json
import math
import re
import shutil
import socket

import pandas as pd
import pytest

from analysis import dataset, lock, models
from tests.fixtures_drivers import (BENCH_A, BENCH_B, CRITERIA, ECDSA, SPECS, RootSnapshot,
                                    build_criteria_study, build_study, git)

SMALL = dict(draws=200, boot=40)
MARGIN = [0.80, 1.25]


def drv(name):
    return importlib.import_module(f"analysis.{name}")


def jload(path):
    return json.loads(path.read_text())


def copy_root(src, dst):
    shutil.copytree(src, dst, symlinks=True)
    return dst


def no_files(path):
    return (not path.exists()) or not any(p.is_file() for p in path.rglob("*"))


@pytest.fixture(scope="module")
def pristine(tmp_path_factory):
    root = tmp_path_factory.mktemp("study") / "repo"
    root.mkdir()
    return build_study(root)


@pytest.fixture
def fresh(pristine, tmp_path):
    return copy_root(pristine.root, tmp_path / "repo")


@pytest.fixture(scope="module")
def done_factory(pristine, tmp_path_factory):
    """Lazily runs the whole chain once with small draws; the root is shared and read-only."""
    cache = {}

    def get():
        if "root" not in cache:
            root = copy_root(pristine.root, tmp_path_factory.mktemp("done") / "repo")
            drv("confirmatory").run(root)
            drv("secondary").run(root, **SMALL)
            drv("sensitivity").run(root)
            drv("exploratory").run(root, boot=SMALL["boot"])
            drv("figures").run(root)
            drv("numbers").write(root)
            cache["root"] = root
        return cache["root"]

    return get


def truth_frame(study, name, root):
    """dataset.build joined to the planted promotions (the test-side oracle)."""
    snap = RootSnapshot(root)
    df = dataset.build(name, snapshot=snap, lineage_root=root / "lineage" / "frozen")
    t = {r["id"]: r for r in study.truth[name]}
    df["y"] = df["id"].map(lambda i: float(t[i]["promoted"]))
    df["kind"] = df["id"].map(lambda i: t[i]["kind"])
    return df


def fit_frame(df):
    one = df["parent_ids"].map(len) == 1
    return df[(df["cross_solver"] == True) & one & df["cross_family"].notna() & df["in_window"]]  # noqa: E712


# ------------------------------------------------------------------ lock (AT6)

def test_pristine_tree_passes_lock(fresh):
    lock.check(fresh)


def test_refuses_when_tag_missing(fresh):
    git(fresh, "tag", "-d", "prereg-v1")
    with pytest.raises(lock.LockError):
        drv("confirmatory").run(fresh)
    assert no_files(fresh / "results")
    assert no_files(fresh / "outcomes" / "sealed")


def test_refuses_when_locked_file_changed_after_tagging(fresh):
    (fresh / "docs" / "prereg.md").write_text("edited after the tag\n")
    with pytest.raises(lock.LockError):
        drv("confirmatory").run(fresh)
    assert no_files(fresh / "results")
    assert no_files(fresh / "outcomes" / "sealed")


def test_refuses_when_code_file_changed_after_tagging(fresh):
    (fresh / "analysis" / "dataset.py").write_text("# tampered\n")
    with pytest.raises(lock.LockError):
        drv("confirmatory").run(fresh)
    assert no_files(fresh / "results")


def test_refuses_when_manifest_rewritten_but_tag_differs(fresh):
    (fresh / "docs" / "prereg.md").write_text("edited after the tag\n")
    lock.write_manifest(fresh)     # manifest now matches the tree but not the tagged copy
    with pytest.raises(lock.LockError):
        drv("confirmatory").run(fresh)
    assert no_files(fresh / "results")


# ------------------------------------------------------------------ confirmatory

def test_confirmatory_writes_result_shape(done_factory):
    root = done_factory()
    out = jload(root / "results" / "confirmatory.json")
    assert set(out["benchmarks"]) == set(SPECS)
    for b in out["benchmarks"].values():
        assert {"log_or", "se", "n", "n_groups_informative", "method"} <= set(b["estimate"])
        assert {"analysis_rows", "fit_rows", "strata_kept", "strata_no_treatment_variation",
                "firth", "excluded"} <= set(b["counts"])
        assert isinstance(b["counts"]["firth"], bool)
    p = out["pooled"]
    assert {"log_or", "ci95", "ci90", "tau2", "k"} <= set(p)
    assert len(p["ci95"]) == 2 and len(p["ci90"]) == 2
    assert p["k"] == 3 and p["tau2"] >= 0
    assert out["margin"] == MARGIN
    assert out["excluded_benchmarks"] == {}
    assert out["verdict"] in ("effect detected", "equivalent to no effect", "inconclusive")
    assert out["case_study"]["benchmark"] == ECDSA
    assert out["case_study"]["verdict"] in ("effect detected", "equivalent to no effect",
                                            "inconclusive")


def test_confirmatory_uses_the_shared_design(fresh, monkeypatch):
    design = importlib.import_module("analysis.design")
    calls = {"primary_rows": 0, "build": 0}
    real_rows, real_build = design.primary_rows, design.build

    def rows(*a, **k):
        calls["primary_rows"] += 1
        return real_rows(*a, **k)

    def build(*a, **k):
        calls["build"] += 1
        return real_build(*a, **k)

    monkeypatch.setattr(design, "primary_rows", rows)
    monkeypatch.setattr(design, "build", build)
    drv("confirmatory").run(fresh)
    assert calls["primary_rows"] >= len(SPECS)
    assert calls["build"] >= len(SPECS)


def test_failed_benchmark_is_listed_and_not_pooled(fresh, monkeypatch):
    import dataclasses
    real = models.cond_logit
    seen = []

    def flaky(*a, **k):
        est = real(*a, **k)
        seen.append(1)
        if len(seen) == 1:
            return dataclasses.replace(est, log_or=float("nan"), se=float("nan"),
                                       method="failed")
        return est

    monkeypatch.setattr(models, "cond_logit", flaky)
    out = drv("confirmatory").run(fresh)
    out = json.loads(json.dumps(out))
    assert len(out["excluded_benchmarks"]) == 1
    name, reason = next(iter(out["excluded_benchmarks"].items()))
    assert name in SPECS and isinstance(reason, str) and reason.strip()
    assert out["benchmarks"][name]["estimate"]["method"] == "failed"
    assert out["pooled"]["k"] == len(SPECS) - 1
    assert math.isfinite(out["pooled"]["log_or"])


def test_confirmatory_run_returns_what_it_wrote(done_factory):
    root = done_factory()
    again = drv("confirmatory").run(root)
    assert json.loads(json.dumps(again)) == jload(root / "results" / "confirmatory.json")


def test_planted_positive_effect_gives_positive_log_or(done_factory):
    out = jload(done_factory() / "results" / "confirmatory.json")
    for name, b in out["benchmarks"].items():
        assert b["estimate"]["log_or"] > 0, name
    assert out["pooled"]["log_or"] > 0
    lo, hi = out["pooled"]["ci95"]
    assert lo < out["pooled"]["log_or"] < hi


def test_verdicts_follow_tost_and_pooling(done_factory):
    out = jload(done_factory() / "results" / "confirmatory.json")
    p = out["pooled"]
    assert out["verdict"] == models.tost(p["log_or"], p["ci95"], p["ci90"], MARGIN)
    ests = [models.Estimate(b["estimate"]["log_or"], b["estimate"]["se"], b["estimate"]["n"],
                            b["estimate"]["n_groups_informative"], b["estimate"]["method"])
            for b in out["benchmarks"].values()]
    want = models.meta_hksj(ests)
    assert p["log_or"] == pytest.approx(want.log_or, rel=1e-3, abs=1e-4)
    assert p["tau2"] == pytest.approx(want.tau2, rel=1e-2, abs=1e-4)
    case = out["benchmarks"][ECDSA]["estimate"]
    single = models.meta_hksj([models.Estimate(case["log_or"], case["se"], case["n"],
                                               case["n_groups_informative"], case["method"])])
    assert out["case_study"]["verdict"] == models.tost(
        single.log_or, single.ci95, single.ci90, MARGIN)


@pytest.mark.parametrize("name", list(SPECS))
def test_restriction_counts(pristine, done_factory, name):
    root = done_factory()
    spec = SPECS[name]
    counts = jload(root / "results" / "confirmatory.json")["benchmarks"][name]["counts"]
    t = pristine.truth[name]
    n_normal_in_window = sum(1 for r in t if r["kind"] == "normal" and not r["week0"])
    assert counts["analysis_rows"] == len(t) == 560
    assert counts["excluded"] == {
        "own_lineage": spec["own"], "multi_parent": spec["multi"], "novel": spec["novel"],
        "unknown_family": spec["unk"], "outside_window": sum(1 for r in t if r["week0"])}
    assert counts["fit_rows"] == n_normal_in_window
    # the oracle agrees: dataset.build restricted the same way gives the same rows
    df = truth_frame(pristine, name, root)
    fit = fit_frame(df)
    assert len(fit) == counts["fit_rows"]
    assert set(fit["kind"]) == {"normal"}


@pytest.mark.parametrize("name", list(SPECS))
def test_strata_counts(pristine, done_factory, name):
    root = done_factory()
    counts = jload(root / "results" / "confirmatory.json")["benchmarks"][name]["counts"]
    fit = fit_frame(truth_frame(pristine, name, root))
    by = fit.groupby("solver")
    varies = by["y"].nunique() > 1
    kept = set(varies[varies].index)
    no_treat = {s for s in kept if fit[fit["solver"] == s]["cross_family"].astype(bool).nunique() == 1}
    assert counts["strata_kept"] == len(kept)
    assert counts["strata_no_treatment_variation"] == len(no_treat) >= 1   # the planted "mono"
    assert "dud" not in kept                                              # never promotes: dropped
    est = jload(root / "results" / "confirmatory.json")["benchmarks"][name]["estimate"]
    assert counts["firth"] == est["method"].startswith("firth")


@pytest.mark.parametrize("name", list(SPECS))
def test_estimate_matches_independent_primary_model(pristine, done_factory, name):
    root = done_factory()
    est = jload(root / "results" / "confirmatory.json")["benchmarks"][name]["estimate"]
    full = truth_frame(pristine, name, root)
    # spec 5.1: 4-df natural cubic spline on days_since_open, knots at the quartiles of the
    # benchmark's analysis rows (all rows of the frame, not the modelled subset), evaluated on
    # the modelled rows; patsy cr with explicit knots (cr df=4 picks other knots)
    from patsy import dmatrix
    import numpy as np
    xall = full["days_since_open"].to_numpy(float)
    q = list(np.quantile(xall, [0.25, 0.5, 0.75]))
    x = fit_frame(full)["days_since_open"].to_numpy(float)
    spl = dmatrix('cr(x, knots=q, lower_bound=lo, upper_bound=hi, constraints="center")',
                  {"x": x, "q": q, "lo": float(xall.min()), "hi": float(xall.max())},
                  return_type="dataframe").drop(columns="Intercept")
    spl.columns = [f"t{i}" for i in range(spl.shape[1])]
    assert spl.shape[1] == 4
    d = fit_frame(full).reset_index(drop=True)
    d["cross"] = d["cross_family"].astype(float)
    d["pib"] = d["parent_is_current_best"].astype(float)
    cols = [spl,
            pd.get_dummies(d["child_family_folded"], prefix="c", drop_first=True, dtype=float),
            pd.get_dummies(d["parent_family_folded"], prefix="p", drop_first=True, dtype=float),
            d[["pib", "log_prior_rows"]]]
    X = pd.concat(cols, axis=1)
    frame = pd.concat([d[["y", "cross", "solver"]], X], axis=1)
    want = models.cond_logit(frame, "y", "cross", list(X.columns), "solver")
    assert est["log_or"] == pytest.approx(want.log_or, abs=2e-3)
    assert est["se"] == pytest.approx(want.se, rel=2e-2)
    assert est["n_groups_informative"] == want.n_groups_informative


def sig6_ok(x):
    if isinstance(x, float):
        return x == float(f"{x:.6g}")
    if isinstance(x, dict):
        return all(sig6_ok(v) for v in x.values())
    if isinstance(x, list):
        return all(sig6_ok(v) for v in x)
    return True


def sorted_keys(x):
    if isinstance(x, dict):
        ks = list(x)
        return ks == sorted(ks) and all(sorted_keys(v) for v in x.values())
    if isinstance(x, list):
        return all(sorted_keys(v) for v in x)
    return True


def test_confirmatory_json_is_sorted_and_rounded(done_factory):
    text = (done_factory() / "results" / "confirmatory.json").read_text()
    obj = json.loads(text)
    assert sig6_ok(obj)
    assert sorted_keys(json.loads(text, object_pairs_hook=lambda kv: dict(kv)))


def test_confirmatory_is_byte_identical_across_runs(done_factory, pristine, tmp_path):
    root = done_factory()
    first = (root / "results" / "confirmatory.json").read_bytes()
    drv("confirmatory").run(root)
    assert (root / "results" / "confirmatory.json").read_bytes() == first
    other = copy_root(pristine.root, tmp_path / "elsewhere" / "repo")
    drv("confirmatory").run(other)
    assert (other / "results" / "confirmatory.json").read_bytes() == first


def test_confirmatory_seals_outcomes_only_after_the_lock(done_factory):
    root = done_factory()
    sealed = list((root / "outcomes" / "sealed").glob("*"))
    assert len(sealed) >= len(SPECS)


# ------------------------------------------------------------------ secondary

def entries(sec, h):
    return {e["benchmark"]: e for e in sec["tests"] if e["hypothesis"] == h}


def test_secondary_minimum_events_gate(pristine, done_factory):
    sec = jload(done_factory() / "results" / "secondary.json")
    h2 = entries(sec, "H2")
    assert set(h2) == set(SPECS)
    # events in each own-lineage arm, from the planted truth
    for name in SPECS:
        t = [r for r in pristine.truth[name] if r["kind"] == "own"]
        sw = sum(r["promoted"] for r in t if r["own_switch"])
        same = sum(r["promoted"] for r in t if not r["own_switch"])
        assert h2[name]["min_arm_events"] == min(sw, same)
    assert h2[BENCH_A]["status"] == "descriptive" and h2[BENCH_A]["min_arm_events"] < 20
    assert h2[BENCH_A].get("p_holm") is None
    for name in (ECDSA, BENCH_B):
        assert h2[name]["min_arm_events"] >= 20
        assert h2[name]["status"] == "confirmatory"
        assert h2[name]["p_holm"] is not None


def test_secondary_status_is_exactly_the_gate_and_holm_is_applied(done_factory):
    sec = jload(done_factory() / "results" / "secondary.json")
    hyps = {e["hypothesis"] for e in sec["tests"]}
    assert hyps == {"H1", "H2", "H3a", "H3b", "H4", "H5"}
    assert {e["benchmark"] for e in sec["tests"] if e["hypothesis"] == "H1"} == {ECDSA}
    assert {e["benchmark"] for e in sec["tests"] if e["hypothesis"] == "H5"} == {ECDSA}
    assert all(e["status"] == "confirmatory" for e in sec["tests"]
               if e["min_arm_events"] >= 20)
    assert all(e["status"] == "descriptive" for e in sec["tests"]
               if e["min_arm_events"] < 20)
    conf = {f"{e['hypothesis']}:{e['benchmark']}": e for e in sec["tests"]
            if e["status"] == "confirmatory"}
    assert len(conf) >= 3
    adj = models.holm({k: e["p"] for k, e in conf.items()})
    for k, e in conf.items():
        assert e["p_holm"] == pytest.approx(adj[k], rel=1e-4, abs=1e-6)
        assert e["p_holm"] >= e["p"] - 1e-9
    for e in sec["tests"]:
        if e["status"] == "descriptive":
            assert e.get("p_holm") is None


def test_secondary_h3b_has_no_plateau_breaks_so_is_descriptive(done_factory):
    sec = jload(done_factory() / "results" / "secondary.json")
    for e in entries(sec, "H3b").values():
        assert e["status"] == "descriptive" and e["min_arm_events"] < 20


def test_secondary_is_deterministic(done_factory, pristine, tmp_path):
    root = done_factory()
    first = (root / "results" / "secondary.json").read_bytes()
    drv("secondary").run(root, **SMALL)
    assert (root / "results" / "secondary.json").read_bytes() == first


# ------------------------------------------------------------------ sensitivity

def test_all_nine_sensitivities_are_named_and_reported(done_factory):
    out = jload(done_factory() / "results" / "sensitivity.json")["sensitivities"]
    keys = {}
    for n in range(1, 10):
        hit = [k for k in out if re.match(rf"s{n}_", k)]
        assert len(hit) == 1, (n, sorted(out))
        keys[n] = hit[0]
    assert len(out) == 9
    for n, k in keys.items():
        v = out[k]
        if "not_applicable" in v:
            assert isinstance(v["not_applicable"], str) and v["not_applicable"].strip()
        else:
            p = v["pooled"]
            assert math.isfinite(p["log_or"])
            lo, hi = p["ci95"]
            assert math.isfinite(lo) and math.isfinite(hi) and lo < hi
    base = jload(done_factory() / "results" / "confirmatory.json")["pooled"]["log_or"]
    # these always apply to the synthetic study and keep the planted direction
    for n in (1, 2, 4, 5, 6, 7):
        assert "pooled" in out[keys[n]], (n, out[keys[n]])
    for n in (1, 4, 5, 7):
        assert out[keys[n]]["pooled"]["log_or"] > 0
    # dropping solver owizdom (ecdsa only) must change the estimate
    assert out[keys[7]]["pooled"]["log_or"] != pytest.approx(base, abs=1e-9)
    # sibling pairs do not exist in the synthetic study
    assert "not_applicable" in out[keys[8]]


def test_sensitivity_is_deterministic(done_factory):
    root = done_factory()
    first = (root / "results" / "sensitivity.json").read_bytes()
    drv("sensitivity").run(root)
    assert (root / "results" / "sensitivity.json").read_bytes() == first


def test_exploratory_is_labelled(done_factory):
    out = jload(done_factory() / "results" / "exploratory.json")
    assert out["label"] == "exploratory"
    assert "E1" in out and "E2" in out


# ------------------------------------------------------------------ study.benchmarks (5.6)

def test_study_benchmarks_applies_the_rule(tmp_path):
    root = build_criteria_study(tmp_path / "repo")
    snap = RootSnapshot(root)
    got = drv("study").benchmarks(snap, lineage_root=root / "lineage" / "frozen")
    assert set(got) == {"x/pass", "x/edge", ECDSA}
    assert len(got) == len(set(got))
    assert set(CRITERIA) - set(got) == {"x/few-rows", "x/few-promoted", "x/one-family",
                                        "x/unfetchable"}


def test_study_benchmarks_on_the_synthetic_study(pristine):
    snap = RootSnapshot(pristine.root)
    got = drv("study").benchmarks(snap, lineage_root=pristine.root / "lineage" / "frozen")
    assert set(got) == set(SPECS)


# ------------------------------------------------------------------ numbers (AT7)

MACRO = re.compile(r"^\\newcommand\{\\([^}]*)\}\{(.*)\}\s*$")
NUM = re.compile(r"-?\d+(?:\.\d+)?")


def leaves(x, out):
    if isinstance(x, dict):
        for v in x.values():
            leaves(v, out)
    elif isinstance(x, list):
        for v in x:
            leaves(v, out)
    elif isinstance(x, bool) or x is None:
        pass
    elif isinstance(x, (int, float)):
        out["num"].append(float(x))
    elif isinstance(x, str):
        out["str"].append(x)
    return out


def candidates(v):
    c = [v, -v, 100 * v, 100 * abs(v), 1 - v]
    if abs(v) < 50:
        e = math.exp(v)
        c += [e, 1 / e, 100 * e, 100 * (e - 1)]
    return c


def traces(token, nums):
    dec = len(token.split(".")[1]) if "." in token else 0
    x = float(token)
    tol = 0.5 * 10 ** -dec + 1e-9
    return any(abs(c - x) <= tol + 1e-6 * abs(x) for v in nums for c in candidates(v))


def read_macros(path):
    lines = [ln for ln in path.read_text().splitlines() if ln.strip() and not ln.startswith("%")]
    out = []
    for ln in lines:
        m = MACRO.match(ln)
        assert m, f"not a one-line \\newcommand: {ln!r}"
        out.append((m.group(1), m.group(2)))
    return out


def test_numbers_tex_macros_are_letters_only_and_trace_to_results(done_factory):
    root = done_factory()
    macros = read_macros(root / "paper" / "numbers.tex")
    assert len(macros) >= 8
    names = [n for n, _ in macros]
    assert all(re.fullmatch(r"[A-Za-z]+", n) for n in names), names
    assert len(names) == len(set(names))
    pool = {"num": [], "str": []}
    for f in ("confirmatory", "secondary", "sensitivity", "exploratory"):
        leaves(jload(root / "results" / f"{f}.json"), pool)
    for name, val in macros:
        clean = val.replace("{,}", "").replace("\\,", "").replace(",", "")
        toks = NUM.findall(clean)
        if not toks:
            plain = re.sub(r"\\[A-Za-z]+\s*|[{}$]", "", val).replace("\\_", "_").strip()
            assert any(plain and plain in s for s in pool["str"]), (name, val)
            continue
        for t in toks:
            assert traces(t, pool["num"]), (name, val, t)


def test_numbers_tex_covers_the_headline_results(done_factory):
    root = done_factory()
    text = (root / "paper" / "numbers.tex").read_text()
    out = jload(root / "results" / "confirmatory.json")
    # the pooled estimate appears in some macro, to at least two decimals
    est = out["pooled"]["log_or"]
    vals = [m for _, m in read_macros(root / "paper" / "numbers.tex")]
    nums = [float(t) for v in vals for t in NUM.findall(v.replace("{,}", "").replace(",", ""))]
    assert any(abs(x - c) < 0.006 for x in nums for c in (est, math.exp(est))), text


def test_numbers_tex_is_deterministic(done_factory, tmp_path):
    root = done_factory()
    first = (root / "paper" / "numbers.tex").read_bytes()
    drv("numbers").write(root)
    assert (root / "paper" / "numbers.tex").read_bytes() == first
    other = copy_root(root, tmp_path / "again" / "repo")
    (other / "paper" / "numbers.tex").unlink()
    drv("numbers").write(other)
    assert (other / "paper" / "numbers.tex").read_bytes() == first


# ------------------------------------------------------------------ figures (AT8)

def figure_files(root):
    d = root / "paper" / "figures"
    return {p.name: p.read_bytes() for p in sorted(d.glob("*")) if p.suffix in (".png", ".pdf")}


def test_figures_write_png_and_pdf(done_factory):
    files = figure_files(done_factory())
    pngs = {n for n in files if n.endswith(".png")}
    pdfs = {n for n in files if n.endswith(".pdf")}
    assert pngs and pdfs
    assert {n[:-4] for n in pngs} == {n[:-4] for n in pdfs}
    for n in pngs:
        assert files[n][:8] == b"\x89PNG\r\n\x1a\n"
    for n in pdfs:
        assert files[n][:5] == b"%PDF-"


def test_figures_are_byte_identical_across_runs(done_factory, tmp_path):
    root = done_factory()
    first = figure_files(root)
    assert first
    other = copy_root(root, tmp_path / "elsewhere" / "repo")
    shutil.rmtree(other / "paper" / "figures")
    drv("figures").run(other)
    second = figure_files(other)
    assert second.keys() == first.keys()
    for n in first:
        assert second[n] == first[n], n
    drv("figures").run(other)          # again over existing files
    assert figure_files(other) == first


# ------------------------------------------------------------------ run.main (AT8)

def test_run_main_runs_the_whole_chain_offline(pristine, tmp_path, monkeypatch):
    root = copy_root(pristine.root, tmp_path / "repo")
    real = socket.socket

    class NoNet(real):
        def __init__(self, *a, **k):
            raise AssertionError("network used")

    def refuse(*a, **k):
        raise AssertionError("network used")

    monkeypatch.setattr(socket, "socket", NoNet)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    drv("run").main(root, **SMALL)

    res = root / "results"
    order = [res / "confirmatory.json", res / "secondary.json", res / "sensitivity.json",
             res / "exploratory.json"]
    figs = sorted((root / "paper" / "figures").glob("*.png"))
    assert figs, "no figures written"
    order += [figs[0], root / "paper" / "numbers.tex"]
    for p in order:
        assert p.is_file(), p
    stamps = [p.stat().st_mtime_ns for p in order]
    assert stamps == sorted(stamps) and len(set(stamps)) == len(stamps), \
        "chain order is confirmatory, secondary, sensitivity, exploratory, figures, numbers"
    assert jload(res / "confirmatory.json")["pooled"]["log_or"] > 0


def test_run_main_refuses_without_the_lock(pristine, tmp_path):
    root = copy_root(pristine.root, tmp_path / "repo")
    git(root, "tag", "-d", "prereg-v1")
    with pytest.raises(lock.LockError):
        drv("run").main(root, **SMALL)
    assert no_files(root / "results")
    assert not (root / "paper" / "numbers.tex").exists()


# ================================================================== E-review round regressions
# (docs/TASKS.md "E-review round (2026-10-17, review at 4e680a6)", findings 1 to 11)

import dataclasses
import os
import subprocess
import sys

import numpy as np

from tests.fixtures_drivers import (OPEN_HOURS, T0, edit_notes, edit_parents)

TAG = {n: "abc"[s["idx"]] for n, s in SPECS.items()}
TIME_COLS = [f"time_s{i}" for i in range(1, 5)]
_TF = {}


def bench_of(ids):
    return next(n for n, t in TAG.items() if str(next(iter(ids))).startswith(t))


def cached_truth_frame(study, name, root):
    key = (id(study), name)
    if key not in _TF:
        _TF[key] = truth_frame(study, name, root)
    return _TF[key]


def base_ids(study, root):
    return {n: set(fit_frame(cached_truth_frame(study, n, root))["id"]) for n in SPECS}


def facts(study, key):
    return {r["id"] for n in SPECS for r in study.truth[n] if r[key]}


# ---- 1: H4 time control

def test_f1_h4_covariates_are_the_time_spline(fresh, monkeypatch):
    real = models.median_reg
    seen = []

    def spy(df, outcome, treatment, covariates, cluster, *a, **k):
        seen.append(list(covariates))
        return real(df, outcome, treatment, covariates, cluster, *a, **k)

    monkeypatch.setattr(models, "median_reg", spy)
    drv("secondary").run(fresh, draws=20, boot=10)
    assert len(seen) == len(SPECS)
    for cov in seen:
        assert cov == TIME_COLS


# ---- 2 and 7: tau2 interval, strata and Firth counts, intervals in numbers.tex

def macro_map(root):
    return dict(read_macros(root / "paper" / "numbers.tex"))


def test_f2_tau2_interval_in_json_and_numbers(done_factory):
    root = done_factory()
    pooled = jload(root / "results" / "confirmatory.json")["pooled"]
    ci = pooled["tau2_ci"]
    assert len(ci) == 2 and all(isinstance(v, (int, float)) for v in ci)
    assert ci[0] <= ci[1]
    macros = macro_map(root)
    tau = {k: v for k, v in macros.items() if "Tau" in k}
    assert len(tau) >= 3, sorted(macros)     # tau2 and the two interval ends
    nums = [float(NUM.findall(v)[0]) for v in tau.values() if NUM.findall(v)]
    for end in ci:
        assert any(abs(x - end) < 6e-4 for x in nums), (end, tau)


def test_f7_counts_in_json(pristine, done_factory):
    root = done_factory()
    out = jload(root / "results" / "confirmatory.json")["benchmarks"]
    for name in SPECS:
        fit = fit_frame(cached_truth_frame(pristine, name, root))
        c = out[name]["counts"]
        total = fit["solver"].nunique()
        assert c["strata_dropped"] == total - c["strata_kept"] > 0     # the planted "dud"
        assert isinstance(c["firth"], bool)


def test_f7_numbers_tex_macros_for_counts_and_intervals(done_factory):
    root = done_factory()
    macros = macro_map(root)
    conf = jload(root / "results" / "confirmatory.json")["benchmarks"]
    for i, name in enumerate(sorted(conf)):
        L = chr(65 + i)
        mine = {k: v for k, v in macros.items() if k.startswith(f"Bench{L}")}
        c = conf[name]["counts"]

        def find(pat):
            hit = {k: v for k, v in mine.items() if re.search(pat, k)}
            assert hit, (name, pat, sorted(mine))
            return hit

        kept = find(r"Strata.*Kept|Kept.*Strata")
        assert str(c["strata_kept"]) in kept.values()
        nt = find(r"Strata.*(Treat|Variation)")
        assert str(c["strata_no_treatment_variation"]) in nt.values()
        dr = find(r"Strata.*Dropped|Dropped.*Strata")
        assert str(c["strata_dropped"]) in dr.values()
        find(r"Firth")
        find(r"Low")
        find(r"High")
    assert any("Tau" in k and ("Low" in k or "Lower" in k) for k in macros)
    assert any("Tau" in k and ("High" in k or "Upper" in k) for k in macros)


# ---- 3: ecdsa.fail's H1 in the Holm family

def test_f3_ecdsa_h1_is_a_secondary_test_in_the_family(pristine, done_factory):
    root = done_factory()
    sec = jload(root / "results" / "secondary.json")
    h1 = entries(sec, "H1")
    assert set(h1) == {ECDSA}
    e = h1[ECDSA]
    fit = fit_frame(cached_truth_frame(pristine, ECDSA, root))
    cf = fit["cross_family"].astype(bool)
    events = int(min(((fit["y"] > 0) & cf).sum(), ((fit["y"] > 0) & ~cf).sum()))
    assert e["min_arm_events"] == events
    assert events >= 20 and e["status"] == "confirmatory"
    est = jload(root / "results" / "confirmatory.json")["benchmarks"][ECDSA]["estimate"]
    from scipy import stats
    assert e["p"] == pytest.approx(2 * stats.norm.sf(abs(est["log_or"] / est["se"])), rel=1e-3)
    conf = {f"{t['hypothesis']}:{t['benchmark']}": t for t in sec["tests"]
            if t["status"] == "confirmatory"}
    assert f"H1:{ECDSA}" in conf
    adj = models.holm({k: t["p"] for k, t in conf.items()})
    assert e["p_holm"] == pytest.approx(adj[f"H1:{ECDSA}"], rel=1e-4, abs=1e-6)


# ---- 4: a gate-passing test that fails stays in the family with p = 1

@pytest.mark.parametrize("mode", ["failed", "raises"])
def test_f4_failed_test_stays_in_holm_family(fresh, done_factory, monkeypatch, mode):
    confirmatory = drv("confirmatory")
    real = confirmatory.fit_rows

    def fake(rows, outcome=None, extra=None):
        own = len(rows) > 0 and bool((rows["cross_solver"] == False).all())  # noqa: E712
        if own and str(rows["id"].iloc[0]).startswith(TAG[ECDSA]):
            if mode == "raises":
                raise RuntimeError("fit exploded")
            e = real(rows, outcome=outcome, extra=extra)
            return dataclasses.replace(e, log_or=float("nan"), se=float("nan"), method="failed")
        return real(rows, outcome=outcome, extra=extra)

    monkeypatch.setattr(confirmatory, "fit_rows", fake)
    drv("secondary").run(fresh, draws=20, boot=10)
    sec = jload(fresh / "results" / "secondary.json")
    base = jload(done_factory() / "results" / "secondary.json")
    h2 = entries(sec, "H2")[ECDSA]
    assert h2["status"] == "confirmatory" and h2["min_arm_events"] >= 20
    assert h2["p"] == 1.0
    assert h2["method"] == "failed"
    conf = {f"{t['hypothesis']}:{t['benchmark']}": t for t in sec["tests"]
            if t["status"] == "confirmatory"}
    assert len(conf) == sum(1 for t in base["tests"] if t["status"] == "confirmatory")
    assert all(t["p"] is not None for t in conf.values())
    adj = models.holm({k: t["p"] for k, t in conf.items()})
    for k, t in conf.items():
        assert t["p_holm"] == pytest.approx(adj[k], rel=1e-4, abs=1e-6), k
    assert h2["p_holm"] == 1.0


# ---- 5: every sensitivity changes the input of the primary fit in the stated way

def run_sens_spy(root):
    confirmatory = drv("confirmatory")
    real_fit, real_pool = confirmatory.fit_rows, confirmatory.pool
    events = []

    def fit(rows, outcome=None, extra=None):
        events.append(("fit", rows.copy(), None if extra is None else extra.copy()))
        return real_fit(rows, outcome=outcome, extra=extra)

    def pool(ests, margin):
        events.append(("pool",))
        return real_pool(ests, margin)

    mp = pytest.MonkeyPatch()
    mp.setattr(confirmatory, "fit_rows", fit)
    mp.setattr(confirmatory, "pool", pool)
    try:
        out = drv("sensitivity").run(root)
    finally:
        mp.undo()
    sens = out["sensitivities"]
    applicable = [k for k in sorted(sens) if "pooled" in sens[k]]
    groups = [[]]
    for ev in events:
        if ev[0] == "fit":
            groups[-1].append(ev)
        else:
            groups.append([])
    groups = groups[:-1]
    assert len(groups) == len(applicable), (applicable, len(groups))
    res = {}
    for k, g in zip(applicable, groups):
        rows = pd.concat([e[1] for e in g]) if g else pd.DataFrame()
        res[k.split("_")[0]] = {"rows": rows, "extras": [e[2] for e in g],
                                "ids": set(rows["id"]) if len(rows) else set()}
    return res, sens


@pytest.fixture(scope="module")
def sens_run(pristine, tmp_path_factory):
    cache = {}

    def get():
        if "v" not in cache:
            root = copy_root(pristine.root, tmp_path_factory.mktemp("sens") / "repo")
            cache["v"] = run_sens_spy(root) + (root,)
        return cache["v"]

    return get


def test_f5_s1_unknown_family_rows_enter(pristine, sens_run):
    res, _, root = sens_run()
    base = base_ids(pristine, root)
    unk = facts_kind(pristine, "unk")
    assert "s1" in res
    assert res["s1"]["ids"] == set().union(*base.values()) | unk
    assert unk and not (unk & set().union(*base.values()))


def facts_kind(study, kind):
    return {r["id"] for n in SPECS for r in study.truth[n] if r["kind"] == kind}


def test_f5_s2_uses_tree_distance_parents(pristine, sens_run):
    res, _, root = sens_run()
    assert "s2" in res
    from families import mapper
    want = {}
    for name in SPECS:
        b = pristine.benches[name]
        raw = {r["id"]: r for r in b.raw}
        fam = lambda i: mapper.family_of(raw[i]["note"].splitlines()[0].partition(":")[2].strip())  # noqa: E731
        week0 = {r["id"] for r in pristine.truth[name] if r["week0"]}
        for rid, (_, tree) in b.parents.items():
            if rid in week0 or raw[rid]["status"] == "cancelled" or len(tree[0]) != 1:
                continue
            p = tree[0][0]
            if raw[p]["solverUsername"] == raw[rid]["solverUsername"]:
                continue
            cf, pf = fam(rid), fam(p)
            if "Unknown" in (cf, pf) or "Multi" in (cf, pf):
                continue
            want[rid] = cf != pf
    got = dict(zip(res["s2"]["rows"]["id"], res["s2"]["rows"]["cross_family"].astype(bool)))
    assert got == want
    base = set().union(*base_ids(pristine, root).values())
    assert set(got) != base                       # the stated change is visible in the row set


def test_f5_s3_drops_nonce_rows(pristine, sens_run):
    res, _, root = sens_run()
    base = set().union(*base_ids(pristine, root).values())
    nonce = facts(pristine, "nonce")
    assert base & nonce
    assert "s3" in res
    assert res["s3"]["ids"] == base - nonce


def test_f5_s5_drops_first_72_hours_after_opening(pristine, sens_run):
    res, _, root = sens_run()
    base = set().union(*base_ids(pristine, root).values())
    hours = {r["id"]: r["hours"] for n in SPECS for r in pristine.truth[n]}
    early = {i for i in base if hours[i] < OPEN_HOURS + 72}
    assert early and early != base
    assert "s5" in res
    assert res["s5"]["ids"] == base - early


def test_f5_s6_adds_harness_columns(pristine, sens_run):
    res, _, root = sens_run()
    assert "s6" in res
    base = set().union(*base_ids(pristine, root).values())
    assert res["s6"]["ids"] == base
    extras = [e for e in res["s6"]["extras"] if e is not None]
    assert len(extras) == len(SPECS)
    for e in extras:
        assert e.shape[1] >= 1
        assert all(str(c).startswith("harness") for c in e.columns)


def test_f5_s9_drops_ambiguous_failures(pristine, sens_run):
    res, _, root = sens_run()
    base = set().union(*base_ids(pristine, root).values())
    failed = facts(pristine, "failed")
    assert base & failed
    assert "s9" in res
    assert res["s9"]["ids"] == base - failed


# ---- 6: study.margin refuses without exactly one canonical line

@pytest.mark.parametrize("text", [
    "prereg without a margin\n",
    "Margin: [0.67, 1.50]\n",
    "margin: [0.67, 1.50]\nmargin: [0.80, 1.25]\n",
    "the margin is [0.67, 1.50]\n",
])
def test_f6_margin_refuses_without_one_canonical_line(tmp_path, text):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "prereg.md").write_text(text)
    with pytest.raises(Exception):
        drv("study").margin(tmp_path)


def test_f6_margin_refuses_without_prereg(tmp_path):
    with pytest.raises(Exception):
        drv("study").margin(tmp_path)


def test_f6_margin_reads_the_one_canonical_line(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "prereg.md").write_text("text\nmargin: [0.67, 1.50]\nmore\n")
    assert drv("study").margin(tmp_path) == [0.67, 1.5]


# ---- 8: python -m analysis.confirmatory checks the lock

def run_module(root):
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT)
    return subprocess.run([sys.executable, "-m", "analysis.confirmatory", "--root", str(root)],
                          cwd=str(REPO_ROOT), env=env, capture_output=True, text=True, timeout=300)


REPO_ROOT = __import__("pathlib").Path(__file__).resolve().parent.parent


def test_f8_module_entry_exits_nonzero_without_manifest(fresh):
    (fresh / "docs" / "prereg-manifest.json").unlink()
    r = run_module(fresh)
    assert r.returncode != 0, r.stdout + r.stderr
    assert no_files(fresh / "results")
    assert no_files(fresh / "outcomes" / "sealed")


def test_f8_module_entry_exits_nonzero_after_tamper(fresh):
    (fresh / "docs" / "prereg.md").write_text("edited\nmargin: [0.80, 1.25]\n")
    r = run_module(fresh)
    assert r.returncode != 0, r.stdout + r.stderr
    assert no_files(fresh / "results")


def test_f8_module_entry_runs_on_a_valid_lock(fresh):
    r = run_module(fresh)
    assert r.returncode == 0, r.stdout + r.stderr
    assert (fresh / "results" / "confirmatory.json").is_file()


# ---- 9: nonce phrasings

NONCE_POS = {
    "Changed only the nonce.": True,
    "Nonce-only change.": True,
    "Only change: new validation draw.": True,
    "Re-roll of the validation draw only.": True,
    "Only the draw-call batching changed in the kernel.": False,
}


def test_f9_nonce_phrasings(pristine, tmp_path):
    root = copy_root(pristine.root, tmp_path / "repo")
    base = base_ids(pristine, pristine.root)[ECDSA]
    nonce = facts(pristine, "nonce")
    pick = sorted(base - nonce - facts(pristine, "failed"))[:len(NONCE_POS)]
    mapping = dict(zip(pick, NONCE_POS))
    edit_notes(root, ECDSA, {i: ph for i, ph in mapping.items()})
    res, _ = run_sens_spy(root)
    assert "s3" in res
    kept = res["s3"]["ids"]
    for i, ph in mapping.items():
        assert (i not in kept) == NONCE_POS[ph], ph
    allbase = set().union(*base_ids(pristine, pristine.root).values())
    dropped = {i for i, ph in mapping.items() if NONCE_POS[ph]} | nonce
    assert kept == allbase - dropped


# ---- 10: an empty restricted frame never crashes a driver

def test_f10_empty_restricted_frame(pristine, tmp_path, monkeypatch):
    root = copy_root(pristine.root, tmp_path / "repo")
    edit_parents(root, BENCH_A, lambda d: [d.__setitem__(
        k, {**v, "primary": [[], "none", None, None]}) for k, v in list(d.items())])
    drv("run").main(root, **SMALL)
    conf = jload(root / "results" / "confirmatory.json")
    assert BENCH_A in conf["excluded_benchmarks"]
    assert conf["excluded_benchmarks"][BENCH_A].strip()
    assert conf["benchmarks"][BENCH_A]["counts"]["fit_rows"] == 0
    assert set(conf["excluded_benchmarks"]) == {BENCH_A}
    assert conf["pooled"]["k"] == len(SPECS) - 1
    sec = jload(root / "results" / "secondary.json")
    mine = [t for t in sec["tests"] if t["benchmark"] == BENCH_A]
    assert mine
    for t in mine:
        assert "unidentified" in (t.get("status"), t.get("method")), t
        assert t["p_holm"] is None
    others = [t for t in sec["tests"] if t["benchmark"] != BENCH_A and t["hypothesis"] == "H2"]
    assert others and all("unidentified" not in (t.get("status"), t.get("method"))
                          for t in others)
    assert (root / "paper" / "numbers.tex").is_file()


# ---- 11: spline knots come from the benchmark's analysis rows

def analysis_basis(x, xall):
    from patsy import dmatrix
    q = list(np.quantile(xall, [0.25, 0.5, 0.75]))
    m = dmatrix('cr(x, knots=q, lower_bound=lo, upper_bound=hi, constraints="center")',
                {"x": np.asarray(x, float), "q": q, "lo": float(np.min(xall)),
                 "hi": float(np.max(xall))}, return_type="dataframe")
    return m.drop(columns="Intercept").to_numpy()


def span_gap(A, B):
    """Largest distance of the columns of A from the span of [1, B]."""
    M = np.column_stack([np.ones(len(B)), B])
    c, *_ = np.linalg.lstsq(M, A, rcond=None)
    return float(np.abs(A - M @ c).max())


def test_f11_spline_knots_are_analysis_row_quartiles(pristine, fresh, monkeypatch):
    design = importlib.import_module("analysis.design")
    real = design.build
    calls = []

    def spy(frame, *a, **k):
        out = real(frame, *a, **k)
        calls.append((frame.copy(), out[0].copy()))
        return out

    monkeypatch.setattr(design, "build", spy)
    drv("confirmatory").run(fresh)
    drv("secondary").run(fresh, draws=20, boot=10)
    assert len(calls) >= 2 * len(SPECS)
    checked = 0
    for frame, X in calls:
        if len(frame) < 12:
            continue
        name = bench_of(frame["id"])
        full = cached_truth_frame(pristine, name, fresh)
        xall = full["days_since_open"].to_numpy(float)
        x = frame["days_since_open"].to_numpy(float)
        cols = X[[c for c in X.columns if c.startswith("time_s")]].to_numpy(float)
        assert cols.shape[1] == 4
        assert span_gap(cols, analysis_basis(x, xall)) < 1e-6 * max(1.0, np.abs(cols).max())
        assert span_gap(analysis_basis(x, xall), cols) < 1e-6
        checked += 1
    assert checked >= 2 * len(SPECS)
    # the case is not vacuous: knots from the modelled rows would give a different space
    for name in SPECS:
        full = cached_truth_frame(pristine, name, fresh)
        fit = fit_frame(full)
        xs = fit["days_since_open"].to_numpy(float)
        other = analysis_basis(xs, xs)
        mine = analysis_basis(xs, full["days_since_open"].to_numpy(float))
        assert span_gap(other, mine) > 1e-3


# ================================================================== E-review round 2 (N2, N3)

def synthetic_h2_frame(prefix, per_solver=12):
    """Own-lineage rows where every solver always (or never) switches family: the treatment is
    constant inside each stratum, so the conditional fit has nothing to identify."""
    rows = []
    for s in range(10):
        switch = s < 5
        for j in range(per_solver):
            rows.append({
                "id": f"{prefix}{s:02d}{j:02d}", "solver": f"u{s}", "cross_solver": False,
                "cross_family": switch, "in_window": True, "parent_method": "declared",
                "days_since_open": float(2 + 3 * j + s), "child_family_folded": "OpenAI",
                "parent_family_folded": "Anthropic" if switch else "OpenAI",
                "parent_is_current_best": float(j % 4 == 0), "log_prior_rows": float(np.log1p(j)),
                "y": float(j % 2)})
    return pd.DataFrame(rows)


def test_n2_precondition_the_synthetic_frame_is_unidentified():
    frame = synthetic_h2_frame("zz")
    confirmatory = drv("confirmatory")
    est = confirmatory.fit_rows(frame, outcome=frame["y"])
    assert est.method == "unidentified"
    switch = frame["cross_family"].astype(bool)
    assert min(((frame["y"] > 0) & switch).sum(), ((frame["y"] > 0) & ~switch).sum()) >= 20


def test_n2_nonempty_unidentified_test_stays_in_the_family(fresh, done_factory, monkeypatch):
    secondary = drv("secondary")
    real = secondary._own_rows

    def own(df):
        if str(df["id"].iloc[0]).startswith(TAG[ECDSA]):
            return synthetic_h2_frame(TAG[ECDSA])
        return real(df)

    monkeypatch.setattr(secondary, "_own_rows", own)
    secondary.run(fresh, draws=20, boot=10)
    sec = jload(fresh / "results" / "secondary.json")
    e = entries(sec, "H2")[ECDSA]
    assert e["min_arm_events"] >= 20
    assert e["status"] == "confirmatory"
    assert e["p"] == 1.0
    assert e["method"] == "unidentified"
    conf = {f"{t['hypothesis']}:{t['benchmark']}": t for t in sec["tests"]
            if t["status"] == "confirmatory"}
    assert f"H2:{ECDSA}" in conf
    assert all(t["p"] is not None for t in conf.values())
    adj = models.holm({k: t["p"] for k, t in conf.items()})
    for k, t in conf.items():
        assert t["p_holm"] == pytest.approx(adj[k], rel=1e-4, abs=1e-6), k
    assert e["p_holm"] == 1.0
    base = jload(done_factory() / "results" / "secondary.json")
    assert len(conf) == sum(1 for t in base["tests"] if t["status"] == "confirmatory")


def test_n2_empty_frame_is_unidentified_and_outside_the_family(fresh, monkeypatch):
    secondary = drv("secondary")
    real = secondary._own_rows

    def own(df):
        out = real(df)
        if str(df["id"].iloc[0]).startswith(TAG[BENCH_A]):
            return out.iloc[0:0]
        return out

    monkeypatch.setattr(secondary, "_own_rows", own)
    secondary.run(fresh, draws=20, boot=10)
    sec = jload(fresh / "results" / "secondary.json")
    e = entries(sec, "H2")[BENCH_A]
    assert "unidentified" in (e.get("status"), e.get("method"))
    assert e["p"] is None and e["p_holm"] is None
    conf = {f"{t['hypothesis']}:{t['benchmark']}": t for t in sec["tests"]
            if t["status"] == "confirmatory"}
    assert f"H2:{BENCH_A}" not in conf
    adj = models.holm({k: t["p"] for k, t in conf.items()})
    for k, t in conf.items():
        assert t["p_holm"] == pytest.approx(adj[k], rel=1e-4, abs=1e-6), k


NONCE_PHRASES = {
    # round 1
    "Changed only the nonce.": True,
    "Nonce-only change.": True,
    "Only change: new validation draw.": True,
    "Re-roll of the validation draw only.": True,
    "Only the draw-call batching changed in the kernel.": False,
    # round 2 (negatives only)
    "Not only the nonce: the whole adder was rewritten.": False,
    "Rewrote the reducer; the nonce only seeds the validation draw.": False,
}


def test_n3_nonce_phrasings_round_two(pristine, tmp_path):
    root = copy_root(pristine.root, tmp_path / "repo")
    base = base_ids(pristine, pristine.root)[ECDSA]
    nonce = facts(pristine, "nonce")
    pick = sorted(base - nonce - facts(pristine, "failed"))[:len(NONCE_PHRASES)]
    mapping = dict(zip(pick, NONCE_PHRASES))
    edit_notes(root, ECDSA, mapping)
    res, _ = run_sens_spy(root)
    assert "s3" in res
    kept = res["s3"]["ids"]
    for i, ph in mapping.items():
        assert (i not in kept) == NONCE_PHRASES[ph], ph
    allbase = set().union(*base_ids(pristine, pristine.root).values())
    dropped = {i for i, ph in mapping.items() if NONCE_PHRASES[ph]} | nonce
    assert kept == allbase - dropped
