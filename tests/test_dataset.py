"""Track E1: analysis.dataset.build and analysis.power (spec 0001 section 3, 5.1, 5.3)."""
from __future__ import annotations

import datetime as dt
import math
import re

import pandas as pd
import pytest

from tests.fixtures_analysis import (CLAUDE, DEVIN, GPT, KIMI, MULTI, NEVER_EVALUATED,
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
                "multi_family", "harness", "parent_ids", "parent_method", "tree_parent_id",
                "parent_solver", "parent_family", "cross_solver", "cross_family", "cell",
                "parent_is_current_best", "log_prior_rows", "in_window",
                "child_family_folded", "parent_family_folded"}
    assert expected <= set(df.columns)


def test_one_row_per_analysis_row_in_a_dataframe(tmp_path):
    df = build(four_cell_rows(), FOUR_CELLS, tmp_path)
    assert isinstance(df, pd.DataFrame)
    assert len(df) == 5 and df["id"].is_unique


# ---------------------------------------------------------------- power

def test_equivalence_power_in_unit_interval():
    from analysis import power
    p = power.equivalence_power(cells_frame(20, 10, seed=1), 0.3, sims=40, seed=7)
    assert 0.0 <= p <= 1.0


def test_equivalence_power_deterministic_for_fixed_seed():
    from analysis import power
    cells = cells_frame(20, 10, seed=1)
    a = power.equivalence_power(cells, 0.3, sims=60, seed=11)
    b = power.equivalence_power(cells, 0.3, sims=60, seed=11)
    assert a == b


def test_equivalence_power_rises_with_more_rows():
    from analysis import power
    small = power.equivalence_power(cells_frame(8, 6, seed=2), 0.3, sims=80, seed=3)
    big = power.equivalence_power(cells_frame(60, 40, purity=0.7, seed=2), 0.3, sims=80, seed=3)
    assert big > small


def test_equivalence_power_falls_with_higher_icc():
    from analysis import power
    cells = cells_frame(40, 30, purity=0.9, seed=4)
    low = power.equivalence_power(cells, 0.3, icc=0.01, sims=150, seed=5)
    high = power.equivalence_power(cells, 0.3, icc=0.6, sims=150, seed=5)
    assert low > high


def test_min_events_returns_smaller_arms_count():
    from analysis import power
    cells = pd.DataFrame({
        "solver": list("abcdefghijklmnopqrstuvwxyz")[:24],
        "cross_family": [True] * 7 + [False] * 12 + [None] * 5,
    })
    assert power.min_events(cells) == 7
    flipped = cells.assign(cross_family=cells.cross_family.map(
        lambda v: None if v is None else (not v)))
    assert power.min_events(flipped) == 7
