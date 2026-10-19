"""paper/descriptive.tex and paper/tables/*.tex: descriptive numbers and tables for the paper.

Reads results/*.json, the frozen snapshot and the frozen lineage. Not part of the prereg-v1
lock: nothing here feeds a confirmatory estimate.
"""
import json
import math
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from analysis import dataset, study  # noqa: E402
from lineage import validate  # noqa: E402
from outcomes import denominator, promotion  # noqa: E402
from snapshot import load as snapshot  # noqa: E402

AUTHOR = "owizdom"


def _load(name):
    return json.loads((ROOT / "results" / f"{name}.json").read_text())


def pct(a, n):
    return f"{100 * a / n:.1f}\\%"


def thousands(n):
    return f"{n:,}"


def ortex(log_or, lo, hi):
    return f"{math.exp(log_or):.2f} [{math.exp(lo):.2f}, {math.exp(hi):.2f}]"


def tt(name):
    return f"\\bench{{{name}}}"


def coverage():
    """AT13 and AT14 coverage counts, replicating the two tests in tests/test_models.py."""
    import numpy as np
    import fixtures_models as fx
    import test_models as tm
    from analysis import models, simulate

    out = []
    for seed_frame, placebo in ((100, False), (101, True)):
        t = fx.primary(fx.realistic_frame(seed=seed_frame))
        covered = 0
        for seed in range(100):
            d = simulate.plant(t, odds_ratio=1.5, base_rate=0.25, icc=0.05, seed=seed)
            ycol = tm._outcome_col(d, t)
            target = math.log(1.5)
            if placebo:
                rng = np.random.default_rng(10_000 + seed)
                d = d.copy()
                d["cross_family"] = d.groupby("solver")["cross_family"].transform(
                    lambda s: rng.permutation(s.to_numpy()))
                target = 0.0
            r = tm._fit(models, d, ycol)
            covered += r.log_or - 1.96 * r.se <= target <= r.log_or + 1.96 * r.se
        out.append(covered)
    return out


def main():
    conf, sec, sens = _load("confirmatory"), _load("secondary"), _load("sensitivity")
    expl, pw = _load("exploratory"), _load("power")
    names = study.benchmarks()
    m = {"StudyK": str(len(names))}

    # sample flow
    excl = Counter()
    for b in conf["benchmarks"].values():
        excl.update(b["counts"]["excluded"])
    m["AnalysisRowsTotal"] = thousands(sum(b["counts"]["analysis_rows"] for b in conf["benchmarks"].values()))
    m["PrimaryRowsTotal"] = thousands(sum(b["counts"]["fit_rows"] for b in conf["benchmarks"].values()))
    m["FitRowsTotal"] = thousands(sum(b["estimate"]["n"] for b in conf["benchmarks"].values()))
    for k, label in (("own_lineage", "OwnLineage"), ("multi_parent", "MultiParent"), ("novel", "Novel"),
                     ("unknown_family", "UnknownFamily"), ("outside_window", "OutsideWindow")):
        m[f"Excl{label}"] = thousands(excl[k])
    methods = Counter(b["estimate"]["method"] for b in conf["benchmarks"].values())
    m["FirthCount"] = str(methods["firth"])

    # cells and parent methods over analysis rows
    cells, pm, nrows = Counter(), Counter(), 0
    for b in names:
        f = dataset.build(b)
        nrows += len(f)
        cells.update(f["cell"].dropna())
        pm.update(f["parent_method"])
    for k, label in (("own_same", "OwnSame"), ("own_switch", "OwnSwitch"),
                     ("other_same", "OtherSame"), ("other_switch", "OtherSwitch")):
        m[f"Cell{label}"] = thousands(cells[k])
    for k, label in (("declared", "Declared"), ("text", "Text"), ("tree", "Tree"),
                     ("novel", "Novel"), ("none", "NoParent"), ("multi", "Multi")):
        m[f"{label}Share"] = pct(pm[k], nrows)

    # AT4, AT15
    pooled = {"declared": [0, 0], "text": [0, 0]}
    side = {"frontier": [0, 0], "other": [0, 0]}
    for b in names:
        for kind, counts in validate.at4_benchmark(b).items():
            for (s, ok), n in counts.items():
                pooled[kind][0] += n * ok
                pooled[kind][1] += n
                side[s][0] += n * ok
                side[s][1] += n
    for kind, label in (("declared", "Declared"), ("text", "Text")):
        a, n = pooled[kind]
        m[f"ATFour{label}Agree"] = f"{a:,} of {n:,} ({pct(a, n)})"
    for s, label in (("frontier", "Frontier"), ("other", "NonFrontier")):
        a, n = side[s]
        m[f"ATFour{label}Agree"] = f"{a:,} of {n:,} ({pct(a, n)})"
    win = validate.at15_benchmark("gpsanant/ecdsafail-challenge")
    m["WindowStartEcdsa"] = win["start"][:10]

    # AT5
    items = {n: (denominator.analysis_rows(snapshot.load(n), n), snapshot.benchmark_meta(n)) for n in names}
    rep = promotion.at5_report(items)
    m["ATFiveReproduced"] = f"{len(names) - len(rep['not_reproduced'])} of {len(names)}"
    m["ATFiveNotReproducedList"] = (", ".join(tt(n) for n in rep["not_reproduced"])
                                    if rep["not_reproduced"] else "none")

    # power, margin, lock
    m["PowerEquivalence"] = f"{pw['power']:.4f}"
    m["PowerWidened"] = f"{pw['power_widened']:.4f}"
    m["PowerFailedShare"] = f"{pw['failed_share']:.4f}"
    m["PowerSims"] = thousands(pw["sims"])
    lo, hi = conf["margin"]
    m["MarginFinal"] = f"$[{lo:.2f}, {hi:.2f}]$"
    m["PreregTag"] = "\\texttt{" + subprocess.run(
        ["git", "rev-parse", "--short=7", "prereg-v1^{commit}"], cwd=ROOT, capture_output=True,
        text=True, check=True).stdout.strip() + "}"
    m["PreregOTSDate"] = subprocess.run(
        ["git", "log", "-1", "--format=%cs", "--", "docs/timestamps/prereg-v1.commit.ots"],
        cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()

    # secondary
    holm = [t for t in sec["tests"] if t["status"] == "confirmatory"]
    m["HolmFamilySize"] = str(len(holm))
    m["HolmMinP"] = f"{min(t['p_holm'] for t in holm):.3f}"

    # E1 rows
    e1 = expl["E1"]
    m["EOneMultiRows"] = thousands(sum(v["n_multi"] for v in e1.values()))
    m["EOneSingleRows"] = thousands(sum(v["n_single"] for v in e1.values()))

    # author rows
    own = {n: [s for s in snapshot.load(n) if s.solver == AUTHOR] for n in names}
    m["AuthorRows"] = str(sum(len(v) for v in own.values()))
    m["AuthorPromoted"] = str(sum(s.promoted for v in own.values() for s in v))
    m["AuthorBenchmarks"] = ", ".join(tt(n) for n, v in own.items() if v)

    # descriptive additions: prediction interval, ecdsa 90%, modexp raw p, flock under s1
    from scipy import stats
    from analysis import confirmatory, design, sensitivity
    p = conf["pooled"]
    k = p["k"]
    se = (p["ci95"][1] - p["ci95"][0]) / 2 / stats.t.ppf(0.975, k - 1)
    half = stats.t.ppf(0.95, k - 2) * math.sqrt(p["tau2"] + se ** 2)
    m["PooledSE"] = f"{se:.3f}"
    m["PredLow"] = f"{math.exp(p['log_or'] - half):.2f}"
    m["PredHigh"] = f"{math.exp(p['log_or'] + half):.2f}"
    m["PooledORNinetyHighFine"] = f"{math.exp(p['ci90'][1]):.3f}"
    e = conf["benchmarks"]["gpsanant/ecdsafail-challenge"]["estimate"]
    m["EcdsaNinetyLow"] = f"{math.exp(e['log_or'] - 1.644854 * e['se']):.2f}"
    m["EcdsaNinetyHigh"] = f"{math.exp(e['log_or'] + 1.644854 * e['se']):.2f}"
    for n in names:
        e = conf["benchmarks"][n]["estimate"]
        if math.exp(e["ci95"][0]) > 1 or math.exp(e["ci95"][1]) < 1:
            m["ExcludesOneBench"] = tt(n)
            m["ExcludesOneP"] = f"{2 * stats.norm.sf(abs(e['log_or'] / e['se'])):.3f}"
    root = study.guard(None)
    fb = study.load_bench(root, "eigenlabs/flock-challenge", study.RootSnapshot(root)).df
    fe = confirmatory.fit_rows(design.primary_rows(sensitivity._s1(fb)))
    m["FlockSOneOR"] = f"{math.exp(fe.log_or):.2f}"
    m["FlockSOneLow"] = f"{math.exp(fe.log_or - 1.959964 * fe.se):.2f}"
    m["FlockSOneHigh"] = f"{math.exp(fe.log_or + 1.959964 * fe.se):.2f}"
    cs = fb[fb["cross_solver"] == True]  # noqa: E712
    unk = cs[cs["cross_family"].isna()]
    m["FlockUnknownCell"] = thousands(len(unk))
    m["FlockUnknownParent"] = thousands(int((unk["parent_family"].isin(["Unknown", "Multi"]) | unk["parent_family"].isna()).sum()))
    m["FlockAnalysisRows"] = thousands(conf["benchmarks"]["eigenlabs/flock-challenge"]["counts"]["analysis_rows"])

    cov13, cov14 = coverage()
    m["ATThirteenCoverage"] = f"{cov13} of 100"
    m["ATFourteenCoverage"] = f"{cov14} of 100"

    lines = ["% Generated by tools/paper_numbers.py. Do not edit."]
    lines += [f"\\newcommand{{\\{k}}}{{{v}}}" for k, v in sorted(m.items()) if v != ""]
    (ROOT / "paper/descriptive.tex").write_text("\n".join(lines) + "\n")

    # tables
    tdir = ROOT / "paper/tables"
    tdir.mkdir(exist_ok=True)
    rows = []
    for n in sorted(conf["benchmarks"]):
        b = conf["benchmarks"][n]
        c, e = b["counts"], b["estimate"]
        rows.append(f"\\bench{{{n.split('/', 1)[1]}}} & {c['analysis_rows']:,} & {e['n']:,} & {c['strata_kept']} & "
                    f"{c['strata_no_treatment_variation']} & {e['method'].capitalize()} & "
                    f"{ortex(e['log_or'], *e['ci95'])} \\\\")
    (tdir / "perbench.tex").write_text("\n".join(rows) + "\n")

    p = conf["pooled"]
    srows = [f"Primary & {conf['pooled']['k']} & {ortex(p['log_or'], *p['ci95'])} & "
             f"[{math.exp(p['ci90'][0]):.2f}, {math.exp(p['ci90'][1]):.2f}] \\\\", "\\midrule"]
    labels = {"s1_unknown_family": "1. Unknown as a family", "s2_tree_parents": "2. Tree parent for every row",
              "s3_drop_nonce_rows": "3. Drop nonce-only rows", "s4_coarse_family": "4. Coarse families",
              "s5_drop_first_72h": "5. Drop first 72 hours", "s6_harness_effects": "6. Harness indicators",
              "s7_drop_author_rows": "7. Drop the author's rows", "s8_one_per_sibling_pair": "8. One per sibling pair",
              "s9_drop_ambiguous_failures": "9. Drop ambiguous failures"}
    for k in sorted(sens["sensitivities"]):
        q = sens["sensitivities"][k]["pooled"]
        srows.append(f"{labels[k]} & {q['k']} & {ortex(q['log_or'], *q['ci95'])} & "
                     f"[{math.exp(q['ci90'][0]):.2f}, {math.exp(q['ci90'][1]):.2f}] \\\\")
    (tdir / "sensitivity.tex").write_text("\n".join(srows) + "\n")

    short = {n: n.split("/", 1)[1] for n in names}
    hrows = []
    for t in sec["tests"]:
        if t["hypothesis"] == "H3b":
            continue
        est = "--" if t["estimate"] is None else f"{t['estimate']:.3f}"
        p_ = "--" if t["p"] is None else f"{t['p']:.3f}"
        ph = "--" if t["p_holm"] is None else f"{t['p_holm']:.3f}"
        status = "C" if t["status"] == "confirmatory" else "D"
        hrows.append(f"{t['hypothesis']} & \\bench{{{short[t['benchmark']]}}} & {t['min_arm_events']} & "
                     f"{est} & {p_} & {ph} & {status} \\\\")
    (tdir / "secondary.tex").write_text("\n".join(hrows) + "\n")
    print(json.dumps(m, indent=1))


if __name__ == "__main__":
    main()
