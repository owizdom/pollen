"""Track E1: analysis.dataset.build and analysis.power (spec 0001 section 3, 5.1, 5.3)."""
from __future__ import annotations

import datetime as dt
import math
import re

import pandas as pd
import pytest

from tests.fixtures_analysis import (add_non_primary_rows, CLAUDE, DEVIN, GPT, KIMI, MULTI, NEVER_EVALUATED,
                                     StubSnapshot, at, cells_frame, declared, link, meta,
                                     sub, write_parents)



def build(subs, mapping, tmp_path, direction="lower", extra=None):
    from analysis import dataset as ds
    root = write_parents(tmp_path / "frozen", mapping)
    snap = StubSnapshot(subs, meta(direction))
    return ds.build("yukon/pollen-test", snapshot=snap, lineage_root=root).set_index(
        "id", drop=False)


def isnull(v):
    return v is None or bool(pd.isna(v))


# ---------------------------------------------------------------- cells

def four_cell_rows():
    return [
        sub("a1", 0, "alice", GPT),
        sub("b1", 1, "bob", CLAUDE),
        sub("a2", 2, "alice", GPT),
        sub("a3", 3, "alice", CLAUDE),
        sub("b2", 4, "bob", GPT),
    ]


FOUR_CELLS = {
    "b1": declared("a1"),   # other solver, GPT -> Claude   : other_switch
    "a2": declared("a1"),   # own lineage, same family      : own_same
    "a3": declared("a1"),   # own lineage, GPT -> Claude    : own_switch
    "b2": declared("a1"),   # other solver, same family     : other_same
}


def test_all_four_cells_assigned(tmp_path):
    df = build(four_cell_rows(), FOUR_CELLS, tmp_path)
    assert df.loc["a2", "cell"] == "own_same"
    assert df.loc["a3", "cell"] == "own_switch"
    assert df.loc["b2", "cell"] == "other_same"
    assert df.loc["b1", "cell"] == "other_switch"
    assert df.loc["b1", "cross_solver"] is True or df.loc["b1", "cross_solver"] == True  # noqa: E712
    assert df.loc["a2", "cross_solver"] == False  # noqa: E712
    assert df.loc["b1", "cross_family"] == True and df.loc["b2", "cross_family"] == False  # noqa: E712
    assert df.loc["b1", "parent_solver"] == "alice"
    assert df.loc["b1", "parent_family"] == "OpenAI"
    assert df.loc["b1", "child_family"] == "Anthropic"
    assert df.loc["b1", "parent_method"] == "declared"


def test_cell_none_without_a_single_parent(tmp_path):
    rows = four_cell_rows() + [
        sub("m1", 5, "bob", CLAUDE), sub("n1", 6, "bob", CLAUDE), sub("z1", 7, "bob", CLAUDE),
    ]
    mapping = dict(FOUR_CELLS)
    mapping["m1"] = declared("a1", "a3")           # multi-source
    mapping["n1"] = link((), "novel")              # novel
    # z1 absent from mapping: no parent at all
    df = build(rows, mapping, tmp_path)
    for i in ("m1", "n1", "z1"):
        assert isnull(df.loc[i, "cell"]), i
        assert isnull(df.loc[i, "cross_family"]), i
    assert df.loc["m1", "parent_method"] == "multi"
    assert df.loc["n1", "parent_method"] == "novel"
    assert df.loc["z1", "parent_method"] == "none"


def test_cell_none_for_unknown_and_multi_family(tmp_path):
    rows = four_cell_rows() + [
        sub("u1", 5, "carol", DEVIN),      # Unknown child
        sub("mf", 6, "carol", MULTI),      # Multi child
        sub("c1", 7, "bob", GPT),          # known child, parent will be Unknown
    ]
    mapping = dict(FOUR_CELLS)
    mapping.update({"u1": declared("a1"), "mf": declared("a1"), "c1": declared("u1")})
    df = build(rows, mapping, tmp_path)
    assert df.loc["u1", "child_family"] == "Unknown"
    assert df.loc["mf", "child_family"] == "Multi"
    assert df.loc["mf", "multi_family"] == True  # noqa: E712
    assert df.loc["a1", "multi_family"] == False  # noqa: E712
    assert df.loc["c1", "parent_family"] == "Unknown"
    for i in ("u1", "mf", "c1"):
        assert isnull(df.loc[i, "cell"]), i


def test_cross_family_is_none_not_false_when_family_unknown(tmp_path):
    rows = four_cell_rows() + [sub("u1", 5, "carol", DEVIN), sub("c1", 6, "bob", GPT)]
    mapping = dict(FOUR_CELLS)
    mapping.update({"u1": declared("a1"), "c1": declared("u1")})
    df = build(rows, mapping, tmp_path)
    for i in ("u1", "c1"):
        v = df.loc[i, "cross_family"]
        assert isnull(v), (i, v)
        assert v is not False
    # cross_solver is still defined: a different solver authored the parent
    assert df.loc["u1", "cross_solver"] == True  # noqa: E712


def test_child_model_and_harness_columns(tmp_path):
    rows = [sub("a1", 0, "alice", GPT)]
    rows[0] = rows[0].__class__(**{**rows[0].__dict__, "note": "Model: GPT-5 Codex\nHarness: codex-cli\nbody"})
    df = build(rows, {}, tmp_path)
    assert df.loc["a1", "child_model"] == GPT
    assert df.loc["a1", "harness"] == "codex-cli"


# ---------------------------------------------------------------- covariates

def test_parent_is_current_best_uses_evaluation_finish_order(tmp_path):
    rows = [
        sub("p1", 0, "alice", GPT, promoted=True, score=10.0, finished=5),
        # created before c_a/c_b but finishes at hour 20: lower score is better
        sub("p2", 2, "alice", GPT, promoted=True, score=8.0, finished=20),
        sub("c_a", 10, "bob", GPT),   # p2 has not finished: p1 is best
        sub("c_b", 10, "bob", GPT),   # parent p2 not finished yet: not best
        sub("c_c", 30, "bob", GPT),   # p2 finished: p2 is best
        sub("c_d", 30, "bob", GPT),   # p1 was best only until hour 20
    ]
    mapping = {"c_a": declared("p1"), "c_b": declared("p2"),
               "c_c": declared("p2"), "c_d": declared("p1")}
    df = build(rows, mapping, tmp_path)
    assert df.loc["c_a", "parent_is_current_best"] == True  # noqa: E712
    assert df.loc["c_b", "parent_is_current_best"] == False  # noqa: E712
    assert df.loc["c_c", "parent_is_current_best"] == True  # noqa: E712
    assert df.loc["c_d", "parent_is_current_best"] == False  # noqa: E712


def test_parent_is_current_best_respects_direction(tmp_path):
    rows = [
        sub("p1", 0, "alice", GPT, promoted=True, score=10.0, finished=1),
        sub("p2", 1, "alice", GPT, promoted=True, score=8.0, finished=2),
        sub("c1", 10, "bob", GPT), sub("c2", 10, "bob", GPT),
    ]
    mapping = {"c1": declared("p1"), "c2": declared("p2")}
    higher = build(rows, mapping, tmp_path / "h", direction="higher")
    assert higher.loc["c1", "parent_is_current_best"] == True  # noqa: E712
    assert higher.loc["c2", "parent_is_current_best"] == False  # noqa: E712


def test_log_prior_rows_counts_only_the_solvers_earlier_analysis_rows(tmp_path):
    rows = [
        sub("a1", 0, "alice"),
        sub("x1", 0.5, "alice", cancelled=True),                  # not an analysis row
        sub("x2", 0.7, "alice", reason=NEVER_EVALUATED),          # never evaluated
        sub("a2", 1, "alice"),
        sub("b1", 1.5, "bob"),                                    # another solver
        sub("a3", 2, "alice"),
    ]
    df = build(rows, {}, tmp_path)
    assert df.loc["a1", "log_prior_rows"] == pytest.approx(0.0)
    assert df.loc["a2", "log_prior_rows"] == pytest.approx(math.log(2))
    assert df.loc["a3", "log_prior_rows"] == pytest.approx(math.log(3))
    assert df.loc["b1", "log_prior_rows"] == pytest.approx(0.0)


def test_week_is_iso_year_week(tmp_path):
    cases = {
        "w1": dt.datetime(2025, 12, 29, 12, tzinfo=dt.timezone.utc),  # Mon, ISO 2026-W01
        "w2": dt.datetime(2026, 1, 1, 12, tzinfo=dt.timezone.utc),    # Thu, ISO 2026-W01
        "w3": dt.datetime(2026, 1, 5, 0, 30, tzinfo=dt.timezone.utc), # Mon, ISO 2026-W02
        "w4": dt.datetime(2026, 12, 31, 9, tzinfo=dt.timezone.utc),   # Thu, ISO 2026-W53
    }
    rows = [sub(i, 0, "alice", created=c) for i, c in cases.items()]
    df = build(rows, {}, tmp_path)
    assert df.loc["w1", "week"] == "2026-W01"
    assert df.loc["w2", "week"] == "2026-W01"
    assert df.loc["w3", "week"] == "2026-W02"
    assert df.loc["w4", "week"] == "2026-W53"


def test_days_since_open_is_float_days_from_benchmark_opening(tmp_path):
    rows = [sub("d0", 0), sub("d1", 12), sub("d2", 36), sub("d3", 24 * 10 + 6)]
    df = build(rows, {}, tmp_path)   # meta().opened_at is at(0)
    assert df.loc["d0", "days_since_open"] == pytest.approx(0.0)
    assert df.loc["d1", "days_since_open"] == pytest.approx(0.5)
    assert df.loc["d2", "days_since_open"] == pytest.approx(1.5)
    assert df.loc["d3", "days_since_open"] == pytest.approx(10.25)
    assert df["days_since_open"].dtype.kind == "f"


def test_sparse_families_fold_below_thirty_rows(tmp_path):
    rows = ([sub(f"g{i}", i, "alice", GPT) for i in range(30)]      # exactly 30: kept
            + [sub(f"c{i}", 100 + i, "bob", CLAUDE) for i in range(29)]  # 29: folded
            + [sub("k0", 200, "carol", KIMI)])                      # 1: folded
    mapping = {"c0": declared("g0"), "k0": declared("c1"), "g1": declared("c0")}
    df = build(rows, mapping, tmp_path)
    assert (df.loc[df.child_family == "OpenAI", "child_family_folded"] == "OpenAI").all()
    assert (df.loc[df.child_family == "Anthropic", "child_family_folded"] == "Other").all()
    assert df.loc["k0", "child_family_folded"] == "Other"
    assert df.loc["k0", "parent_family"] == "Anthropic"
    assert df.loc["k0", "parent_family_folded"] == "Other"
    assert df.loc["c0", "parent_family_folded"] == "OpenAI"
    assert df.loc["g1", "parent_family_folded"] == "Other"
    # folding never alters the raw family
    assert df.loc["k0", "child_family"] == "Moonshot"


def test_cancelled_and_never_evaluated_rows_excluded(tmp_path):
    rows = [
        sub("keep1", 0), sub("keep2", 1, status="accepted", promoted=True, score=1.0),
        sub("gone1", 2, cancelled=True),
        sub("gone2", 3, reason=NEVER_EVALUATED),
        sub("gone3", 4, status="validating"),
    ]
    df = build(rows, {}, tmp_path)
    assert set(df["id"]) == {"keep1", "keep2"}
    assert len(df) == 2


def test_no_outcome_columns(tmp_path):
    rows = four_cell_rows() + [
        sub("p1", 8, "alice", GPT, promoted=True, score=3.0, finished=9)]
    df = build(rows, FOUR_CELLS, tmp_path)
    bad = re.compile(r"(^y\d|promot|score|gain|pareto|jump|plateau|accept|reject)", re.I)
    assert [c for c in df.columns if bad.search(c)] == []
    expected = {"id", "solver", "created_at", "week", "child_model", "child_family",
                "multi_family", "harness", "parent_ids", "parent_method", "tree_parent_id", "days_since_open",
                "parent_solver", "parent_family", "cross_solver", "cross_family", "cell",
                "parent_is_current_best", "log_prior_rows", "in_window",
                "child_family_folded", "parent_family_folded"}
    assert expected <= set(df.columns)


def test_one_row_per_analysis_row_in_a_dataframe(tmp_path):
    df = build(four_cell_rows(), FOUR_CELLS, tmp_path)
    assert isinstance(df, pd.DataFrame)
    assert len(df) == 5 and df["id"].is_unique


# ---------------------------------------------------------------- frozen inputs

def _frozen_error(excinfo_type):
    return not issubclass(excinfo_type, (ImportError, TypeError, AttributeError, NameError))


def _run_build(root):
    from analysis import dataset as ds
    return ds.build("yukon/pollen-test", snapshot=StubSnapshot([sub("a1", 0)], meta()),
                    lineage_root=root)


@pytest.mark.parametrize("name", ["parents.json.gz", "missing.json"])
def test_build_raises_when_frozen_file_absent(tmp_path, name):
    root = write_parents(tmp_path / "frozen", {}, sign=False)
    (root / "pollen-test" / name).unlink()
    from lineage import build as lbuild
    lbuild.write_sha256sums(root)
    with pytest.raises(Exception) as ei:
        _run_build(root)
    assert _frozen_error(ei.type), ei.value


def test_build_raises_when_parents_do_not_match_sha256sums(tmp_path):
    root = write_parents(tmp_path / "frozen", {"a1": declared("zz")})
    # replace the file with different content without re-signing
    write_parents(tmp_path / "other", {"a1": link()}, sign=False)
    (root / "pollen-test" / "parents.json.gz").write_bytes(
        (tmp_path / "other" / "pollen-test" / "parents.json.gz").read_bytes())
    with pytest.raises(Exception) as ei:
        _run_build(root)
    assert _frozen_error(ei.type), ei.value


def test_build_accepts_correctly_signed_frozen_files(tmp_path):
    root = write_parents(tmp_path / "frozen", {})
    assert len(_run_build(root)) == 1


# ---------------------------------------------------------------- power

def test_equivalence_power_in_unit_interval():
    from analysis import power
    p = power.equivalence_power(cells_frame(12, 6, seed=1), 0.3, sims=10, seed=7)
    assert 0.0 <= p <= 1.0


def test_equivalence_power_deterministic_for_fixed_seed():
    from analysis import power
    cells = cells_frame(12, 6, seed=1)
    a = power.equivalence_power(cells, 0.3, sims=10, seed=11)
    b = power.equivalence_power(cells, 0.3, sims=10, seed=11)
    assert a == b


def test_equivalence_power_uses_design_module(monkeypatch):
    from analysis import design, power
    seen = {"rows": 0, "build": 0}
    real_rows, real_build = design.primary_rows, design.build

    def rows(f):
        seen["rows"] += 1
        return real_rows(f)

    def build(f):
        seen["build"] += 1
        return real_build(f)

    monkeypatch.setattr(design, "primary_rows", rows)
    monkeypatch.setattr(design, "build", build)
    power.equivalence_power(cells_frame(12, 6, seed=1), 0.3, sims=3, seed=2)
    assert seen["rows"] >= 1 and seen["build"] >= 1


def test_power_ignores_non_primary_rows():
    from analysis import power
    base = cells_frame(12, 6, seed=1)
    noisy = add_non_primary_rows(base)
    a = power.equivalence_power(base, 0.3, sims=10, seed=5)
    b = power.equivalence_power(noisy, 0.3, sims=10, seed=5)
    assert a == b


def _failing(monkeypatch, should_fail):
    from analysis import models
    real, state = models.cond_logit, {"n": 0}

    def fake(*a, **k):
        state["n"] += 1
        if should_fail(state["n"]):
            return models.Estimate(float("nan"), float("nan"), 0, 0, "failed")
        return real(*a, **k)

    monkeypatch.setattr(models, "cond_logit", fake)


def test_failed_fits_count_as_non_equivalent_and_are_reported(monkeypatch):
    from analysis import power
    frame = cells_frame(12, 6, seed=1)
    _failing(monkeypatch, lambda n: True)
    rep = power.equivalence_power_report(frame, 0.3, sims=6, seed=2)
    assert rep["power"] == 0.0
    assert rep["failed_share"] == pytest.approx(1.0)
    assert power.equivalence_power(frame, 0.3, sims=6, seed=2) == 0.0


def test_partial_failures_report_share(monkeypatch):
    from analysis import power
    _failing(monkeypatch, lambda n: n % 2 == 0)
    rep = power.equivalence_power_report(cells_frame(12, 6, seed=1), 0.3, sims=10, seed=2)
    assert rep["failed_share"] == pytest.approx(0.5)
    assert rep["power"] <= 0.5


def test_pooled_power_never_drops_a_benchmark_silently(monkeypatch):
    from analysis import power
    frames = {f"b{i}": cells_frame(12, 6, seed=i) for i in range(3)}
    rates = {k: 0.3 for k in frames}
    _failing(monkeypatch, lambda n: n % 3 == 2)   # one benchmark fails in every run
    rep = power.pooled_equivalence_power_report(frames, rates, sims=5, seed=4)
    assert rep["failed_share"] == pytest.approx(1 / 3)
    assert rep["power"] == 0.0
    assert power.pooled_equivalence_power(frames, rates, sims=5, seed=4) == 0.0


def test_equivalence_power_calls_cond_logit_once_per_sim(monkeypatch):
    from analysis import models, power
    real, calls = models.cond_logit, []

    def counting(*a, **k):
        calls.append(1)
        return real(*a, **k)

    monkeypatch.setattr(models, "cond_logit", counting)
    power.equivalence_power(cells_frame(12, 6, seed=1), 0.3, sims=8, seed=2)
    assert len(calls) == 8


def test_pooled_equivalence_power_uses_cond_logit_and_meta_hksj(monkeypatch):
    from analysis import models, power
    real, calls = models.cond_logit, []
    real_meta, metas = models.meta_hksj, []

    def counting(*a, **k):
        calls.append(1)
        return real(*a, **k)

    def counting_meta(*a, **k):
        metas.append(1)
        return real_meta(*a, **k)

    monkeypatch.setattr(models, "cond_logit", counting)
    monkeypatch.setattr(models, "meta_hksj", counting_meta)
    frames = {f"b{i}": cells_frame(12, 6, seed=i) for i in range(3)}
    rates = {k: 0.3 for k in frames}
    p = power.pooled_equivalence_power(frames, rates, sims=6, seed=4)
    assert 0.0 <= p <= 1.0
    assert len(calls) == 3 * 6
    assert len(metas) >= 1
    q = power.pooled_equivalence_power(frames, rates, sims=6, seed=4)
    assert p == q


def test_min_rows_returns_smaller_arms_row_count():
    from analysis import power
    cells = pd.DataFrame({
        "solver": list("abcdefghijklmnopqrstuvwxyz")[:24],
        "cross_family": [True] * 7 + [False] * 12 + [None] * 5,
    })
    assert power.min_rows(cells) == 7
    flipped = cells.assign(cross_family=cells.cross_family.map(
        lambda v: None if v is None else (not v)))
    assert power.min_rows(flipped) == 7


# ---------------------------------------------------------------- spline knots (E-review round 2, N1)

KNOT_COLS = [f"spline_knot_{i}" for i in range(5)]


def test_n1_build_emits_spline_knots_from_all_analysis_rows(tmp_path):
    import numpy as np
    hours = [0, 6, 12, 36, 60, 120, 300]
    subs = [sub(f"r{i}", h, "alice" if i % 2 else "bob", GPT if i % 3 else CLAUDE)
            for i, h in enumerate(hours)]
    subs.append(sub("cx", 5000, "carol", GPT, cancelled=True))      # not an analysis row
    df = build(subs, {}, tmp_path)
    assert set(df.index) == {f"r{i}" for i in range(len(hours))}
    want = np.quantile(np.array(hours) / 24.0, [0, 0.25, 0.5, 0.75, 1.0])
    for c, w in zip(KNOT_COLS, want):
        assert c in df.columns, c
        assert df[c].nunique() == 1
        assert df[c].iloc[0] == pytest.approx(w)


def test_n1_power_builds_the_spline_from_the_carried_knots(monkeypatch):
    import numpy as np
    from analysis import design, power
    cells = cells_frame(12, 6, seed=1)
    knots = [0.0, 10.0, 20.0, 30.0, 80.0]        # analysis-row knots; the primary rows lie in 1..52.5
    for c, v in zip(KNOT_COLS, knots):
        cells[c] = v
    own = np.quantile(cells["days_since_open"], [0, 0.25, 0.5, 0.75, 1.0])
    assert not np.allclose(own, knots)
    seen = []
    real = design.time_spline

    def spy(x, knots=None):
        seen.append(None if knots is None else list(np.asarray(knots, float)))
        return real(x, knots)

    monkeypatch.setattr(design, "time_spline", spy)
    power.equivalence_power(cells, 0.3, sims=2, seed=3)
    assert seen
    for k in seen:
        assert k is not None and k == pytest.approx(knots)


def test_n1_power_on_a_dataset_frame_uses_dataset_knots(tmp_path, monkeypatch):
    """A late window: the early analysis rows stretch the knots beyond the primary rows' range."""
    import numpy as np
    from analysis import design, power
    subs, mapping = [], {}
    for i in range(6):                                  # early rows with no parent: not primary
        subs.append(sub(f"e{i}", 2 * i, "early", GPT))
    for i in range(24):                                 # late cross-solver rows with parents
        pid = f"e{i % 6}"
        subs.append(sub(f"l{i}", 2000 + 3 * i, f"s{i % 6}", CLAUDE if i % 2 else GPT))
        mapping[f"l{i}"] = declared(pid)
    df = build(subs, mapping, tmp_path).reset_index(drop=True)
    df["in_window"] = df["id"].str.startswith("l")      # the window opens late
    prim = design.primary_rows(df)
    assert 0 < len(prim) < len(df)
    all_days = df["days_since_open"].to_numpy(float)
    want = list(np.quantile(all_days, [0, 0.25, 0.5, 0.75, 1.0]))
    assert not np.allclose(want, np.quantile(prim["days_since_open"], [0, 0.25, 0.5, 0.75, 1.0]))
    seen = []
    real = design.time_spline

    def spy(x, knots=None):
        seen.append(None if knots is None else list(np.asarray(knots, float)))
        return real(x, knots)

    monkeypatch.setattr(design, "time_spline", spy)
    power.equivalence_power(df, 0.3, sims=1, seed=1)
    assert seen and all(k is not None and k == pytest.approx(want) for k in seen)


def test_pooled_power_is_identical_across_worker_counts():
    from analysis import power
    frames = {f"b{i}": cells_frame(12, 6, seed=i) for i in range(3)}
    rates = {k: 0.3 for k in frames}
    serial = power.pooled_equivalence_power_report(frames, rates, sims=6, seed=4)
    pooled = power.pooled_equivalence_power_report(frames, rates, sims=6, seed=4, workers=2)
    assert pooled == serial
