"""Track D acceptance tests (spec 0001 section 3.1, 3.5, 5.8, AT5).

API chosen where the spec is silent (implementers must match):
  denominator.analysis_rows(subs, benchmark, config=None) -> list[Submission]
      config is {"default": [reasons], "benchmarks": {name: [reasons]}};
      None reads outcomes/denominator.yaml.
  promotion.y1(sub) -> bool
  promotion.recompute(subs, meta) -> list[bool], aligned with input order
  promotion.disagreements(subs, meta, exceptions=()) -> list[str] of ids whose
      recomputed value differs from sub.promoted, minus exceptions
  frontier.best_before(subs, meta) -> list[float | None] aligned with input,
      best score among promoted rows strictly earlier by created_at
  frontier.gain_log(sub, best_before, meta) -> float | None
  jumps.large_jumps(rows) -> list of rows; jumps.plateau_breaks(rows, hours, threshold)
      -> list of rows (rows carry created_at, promoted, gain_log)
  pareto.pareto_gain(rows) -> list[bool] aligned with input (rows carry created_at, metrics)
  annotate(subs, meta, out_dir=None) -> None, writes <out_dir>/<meta.slug>.json.gz
"""
import gzip
import json
import math
from pathlib import Path

import pytest

from tests.fixtures_outcomes import DENOM_CONFIG, at, meta, row, sub


# ---------------------------------------------------------------- denominator

def test_denominator_yaml_exists_and_nonempty():
    import yaml
    p = Path(__file__).resolve().parent.parent / "outcomes" / "denominator.yaml"
    data = yaml.safe_load(p.read_text())
    assert data, "denominator.yaml must list rejection reasons"


def test_analysis_rows_drops_cancelled():
    from outcomes import denominator
    subs = [sub("a", 1, score=1.0), sub("c", 2, cancelled=True)]
    out = denominator.analysis_rows(subs, "yukon/b", config=DENOM_CONFIG)
    assert [s.id for s in out] == ["a"]


def test_analysis_rows_drops_default_and_benchmark_reasons():
    from outcomes import denominator
    subs = [
        sub("d", 1, reason="never scored default"),
        sub("s", 2, reason="never scored specific"),
        sub("k", 3, score=2.0),
    ]
    out = denominator.analysis_rows(subs, "yukon/b", config=DENOM_CONFIG)
    assert [s.id for s in out] == ["k"]


def test_analysis_rows_benchmark_list_is_per_benchmark():
    from outcomes import denominator
    subs = [sub("s", 1, reason="never scored specific", bench="yukon/other")]
    out = denominator.analysis_rows(subs, "yukon/other", config=DENOM_CONFIG)
    assert [s.id for s in out] == ["s"]


def test_analysis_rows_keeps_failed_and_ordinary_rejections():
    from outcomes import denominator
    subs = [
        sub("f", 1, status="failed"),
        sub("r", 2, score=9.0, reason="score did not improve current best"),
    ]
    out = denominator.analysis_rows(subs, "yukon/b", config=DENOM_CONFIG)
    assert [s.id for s in out] == ["f", "r"]


# ------------------------------------------------------------------ promotion

def test_y1_equals_promoted():
    from outcomes import promotion
    assert promotion.y1(sub("a", 1, score=1.0, promoted=True)) is True
    assert promotion.y1(sub("b", 2, score=1.0, promoted=False)) is False


def test_recompute_lower_running_best():
    from outcomes import promotion
    subs = [sub("a", 1, 100.0), sub("b", 2, 105.0), sub("c", 3, 95.0),
            sub("d", 4, 95.0), sub("e", 5, 90.0)]
    assert promotion.recompute(subs, meta("lower")) == [True, False, True, False, True]


def test_recompute_higher_running_best():
    from outcomes import promotion
    subs = [sub("a", 1, 0.5), sub("b", 2, 0.4), sub("c", 3, 0.6), sub("d", 4, 0.6)]
    assert promotion.recompute(subs, meta("higher")) == [True, False, True, False]


def test_recompute_orders_by_created_at_not_input_order():
    from outcomes import promotion
    subs = [sub("late", 5, 97.0), sub("early", 1, 100.0), sub("mid", 3, 95.0)]
    # time order: early 100 (T), mid 95 (T), late 97 (F); input-order would give [T, F, T]
    assert promotion.recompute(subs, meta("lower")) == [False, True, True]


def test_recompute_compares_only_against_promoted_best():
    # a non-promotable better score earlier must not raise the bar: the
    # reference is the best *predicted promoted* score, which equals the
    # running best here, so a later row only needs to beat 100.
    from outcomes import promotion
    subs = [sub("a", 1, 100.0), sub("b", 2, 120.0), sub("c", 3, 99.0)]
    assert promotion.recompute(subs, meta("lower")) == [True, False, True]


def test_recompute_null_scores_never_promote():
    from outcomes import promotion
    subs = [sub("a", 1, None), sub("b", 2, 10.0), sub("c", 3, None)]
    assert promotion.recompute(subs, meta("lower")) == [False, True, False]


def test_recompute_first_scored_row_compared_against_infinity_no_baseline():
    # Benchmark has no baseline field: the first row with a score is compared
    # against +inf (lower) or -inf (higher), so it is promoted.
    from outcomes import promotion
    assert promotion.recompute([sub("a", 1, 1e9)], meta("lower")) == [True]
    assert promotion.recompute([sub("a", 1, -1e9)], meta("higher")) == [True]


def test_recompute_min_improvement_bips_lower():
    from outcomes import promotion
    subs = [sub("a", 1, 100.0), sub("b", 2, 99.5), sub("c", 3, 98.5)]
    # b: 0.5% better than 100 -> no. c: 1.5% better than 100 -> yes.
    assert promotion.recompute(subs, meta("lower", bips=100)) == [True, False, True]


def test_recompute_min_improvement_bips_higher():
    from outcomes import promotion
    subs = [sub("a", 1, 100.0), sub("b", 2, 100.5), sub("c", 3, 101.5)]
    assert promotion.recompute(subs, meta("higher", bips=100)) == [True, False, True]


def test_recompute_none_bips_means_any_strict_improvement():
    from outcomes import promotion
    subs = [sub("a", 1, 100.0), sub("b", 2, 99.999)]
    assert promotion.recompute(subs, meta("lower", bips=None)) == [True, True]


def test_disagreements_lists_ids_and_exceptions_suppress():
    from outcomes import promotion
    subs = [
        sub("a", 1, 100.0, promoted=True),
        sub("b", 2, 95.0, promoted=False, status="accepted"),   # recompute says True
        sub("c", 3, 105.0, promoted=True),                      # recompute says False
        sub("d", 4, 90.0, promoted=True),
    ]
    m = meta("lower")
    assert sorted(promotion.disagreements(subs, m)) == ["b", "c"]
    assert promotion.disagreements(subs, m, exceptions=("b",)) == ["c"]
    assert promotion.disagreements(subs, m, exceptions=("b", "c")) == []


def test_disagreements_empty_when_consistent():
    from outcomes import promotion
    subs = [sub("a", 1, 100.0, promoted=True), sub("b", 2, 110.0),
            sub("c", 3, 90.0, promoted=True)]
    assert promotion.disagreements(subs, meta("lower")) == []


# ------------------------------------------------------------------- frontier

def test_best_before_lower_uses_promoted_rows_strictly_earlier():
    from outcomes import frontier
    subs = [sub("a", 1, 100.0, promoted=True), sub("b", 2, 120.0),
            sub("c", 3, 90.0, promoted=True), sub("d", 4, 80.0)]
    assert frontier.best_before(subs, meta("lower")) == [None, 100.0, 100.0, 90.0]


def test_best_before_higher():
    from outcomes import frontier
    subs = [sub("a", 1, 0.5, promoted=True), sub("b", 2, 0.7, promoted=True),
            sub("c", 3, 0.6)]
    assert frontier.best_before(subs, meta("higher")) == [None, 0.5, 0.7]


def test_gain_log_lower_and_higher_positive():
    from outcomes import frontier
    s = sub("a", 2, 90.0, promoted=True)
    assert frontier.gain_log(s, 100.0, meta("lower")) == pytest.approx(math.log(100 / 90))
    h = sub("b", 2, 0.66, promoted=True)
    assert frontier.gain_log(h, 0.6, meta("higher")) == pytest.approx(math.log(0.66 / 0.6))
    assert frontier.gain_log(s, 100.0, meta("lower")) > 0
    assert frontier.gain_log(h, 0.6, meta("higher")) > 0


def test_gain_log_none_for_non_promoted_and_for_no_prior_best():
    from outcomes import frontier
    assert frontier.gain_log(sub("a", 2, 90.0), 100.0, meta("lower")) is None
    assert frontier.gain_log(sub("b", 1, 90.0, promoted=True), None, meta("lower")) is None


# ---------------------------------------------------------------------- jumps

def test_large_jumps_top_decile_ceil():
    from outcomes import jumps
    rows = [row(f"r{i}", i, gain=0.001 * (i + 1)) for i in range(25)]
    out = jumps.large_jumps(rows)
    assert math.ceil(25 / 10) == 3
    assert [r.id for r in out] == ["r24", "r23", "r22"] or \
        sorted(r.id for r in out) == ["r22", "r23", "r24"]


def test_large_jumps_ceil_for_small_n_and_ignores_non_promoted():
    from outcomes import jumps
    rows = [row("a", 1, gain=0.1), row("b", 2, gain=0.5),
            row("x", 3, gain=None, promoted=False)]
    out = jumps.large_jumps(rows)
    assert [r.id for r in out] == ["b"]  # ceil(2/10) = 1


def test_plateau_break_flags_gain_after_quiet_window():
    from outcomes import jumps
    rows = [row("a", 0, gain=0.02), row("b", 100, gain=0.02)]
    out = jumps.plateau_breaks(rows, hours=72, threshold=0.01)
    assert "b" in [r.id for r in out]


def test_plateau_break_not_flagged_when_recent_big_promotion():
    from outcomes import jumps
    rows = [row("a", 0, gain=0.02), row("b", 50, gain=0.02)]
    assert "b" not in [r.id for r in jumps.plateau_breaks(rows, 72, 0.01)]


def test_plateau_break_small_recent_promotion_does_not_count_as_activity():
    from outcomes import jumps
    rows = [row("a", 0, gain=0.02), row("tiny", 90, gain=0.001),
            row("b", 100, gain=0.02)]
    ids = [r.id for r in jumps.plateau_breaks(rows, 72, 0.01)]
    assert "b" in ids and "tiny" not in ids


def test_plateau_break_requires_gain_at_least_threshold():
    from outcomes import jumps
    rows = [row("a", 0, gain=0.02), row("small", 200, gain=0.005)]
    assert "small" not in [r.id for r in jumps.plateau_breaks(rows, 72, 0.01)]


def test_plateau_break_boundary_gain_equal_threshold_counts():
    from outcomes import jumps
    rows = [row("a", 0, gain=0.01), row("b", 100, gain=0.01)]
    assert "b" in [r.id for r in jumps.plateau_breaks(rows, 72, 0.01)]


# --------------------------------------------------------------------- pareto

def _m(q, t):
    return {"qubits": q, "toffoli": t}


def test_pareto_first_valid_row_is_gain():
    from outcomes import pareto
    assert pareto.pareto_gain([row("a", 1, metrics=_m(10, 10))]) == [True]


def test_pareto_dominated_and_nondominated():
    from outcomes import pareto
    rows = [row("a", 1, metrics=_m(10, 10)),
            row("b", 2, metrics=_m(12, 12)),   # dominated by a
            row("c", 3, metrics=_m(8, 14)),    # tradeoff: not dominated
            row("d", 4, metrics=_m(9, 9))]     # dominates a
    assert pareto.pareto_gain(rows) == [True, False, True, True]


def test_pareto_equal_point_is_dominated_only_with_one_strict():
    from outcomes import pareto
    rows = [row("a", 1, metrics=_m(10, 10)),
            row("b", 2, metrics=_m(10, 10)),   # equal, no strict -> not dominated
            row("c", 3, metrics=_m(10, 11))]   # a weakly better, one strict -> dominated
    assert pareto.pareto_gain(rows) == [True, True, False]


def test_pareto_rows_without_metrics_false_and_do_not_dominate():
    from outcomes import pareto
    rows = [row("a", 1, metrics={}),
            row("b", 2, metrics=_m(10, 10)),
            row("c", 3, metrics={"qubits": 1}),
            row("d", 4, metrics=_m(11, 11))]
    assert pareto.pareto_gain(rows) == [False, True, False, False]


def test_pareto_only_earlier_rows_dominate():
    from outcomes import pareto
    rows = [row("late", 5, metrics=_m(1, 1)), row("early", 1, metrics=_m(10, 10))]
    assert pareto.pareto_gain(rows) == [True, True]


# ------------------------------------------------------------------- annotate

def test_annotate_writes_sealed_gz_and_returns_none(tmp_path):
    import outcomes
    subs = [sub("a", 1, 100.0, promoted=True), sub("b", 2, 110.0)]
    out = outcomes.annotate(subs, meta("lower", slug="myslug"), out_dir=tmp_path)
    assert out is None
    p = tmp_path / "myslug.json.gz"
    assert p.exists()
    with gzip.open(p, "rb") as f:
        data = json.loads(f.read())
    assert data  # non-empty, parseable
    assert "a" in json.dumps(data) and "b" in json.dumps(data)


# ------------------------------------------------------------------------ AT5

def test_at5_recompute_agrees_with_promotion_status_on_real_snapshot():
    from outcomes import denominator, promotion
    from snapshot import load as snap
    name = "gpsanant/ecdsafail-challenge"
    subs = snap.load(name)
    m = snap.benchmark_meta(name)
    rows = denominator.analysis_rows(subs, name)
    exceptions = [s.id for s in rows if s.status == "accepted" and not s.promoted]
    assert len(exceptions) == 4
    assert promotion.disagreements(rows, m, exceptions=exceptions) == []
