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
      best score among promoted rows strictly earlier in evaluation order
      (finished_at, else created_at); meta.baseline_score seeds it when set
  promotion.at5_report({name: (rows, meta)}) -> {"counts": {name: {"rows": int,
      "disagreements": int, "exceptions": int}}, "not_reproduced": [names above 1%]};
      exceptions are accepted-but-failed (status accepted, not promoted) and
      promotion_status == "superseded" rows, found automatically
  jumps.plateau_breaks(rows, hours=72, threshold=0.01, opened_at=None, direction="lower")
      uses row.score and row.best_before (relative 1%), not gain_log
  denominator: config["failure_classes"] maps reason (exact or regex search) to
      evaluated | infrastructure | ambiguous; analysis_rows(..., drop_ambiguous=False)
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


def _p(i, hours, score, best):
    return row(i, hours, score=score, best_before=best)


def test_plateau_first_qualifying_promotion_after_72h_from_opening_is_break():
    from outcomes import jumps
    rows = [_p("a", 100, 98.0, 100.0)]
    out = jumps.plateau_breaks(rows, 72, 0.01, opened_at=at(0), direction="lower")
    assert [r.id for r in out] == ["a"]


def test_plateau_first_promotion_within_72h_of_opening_is_not_break():
    from outcomes import jumps
    rows = [_p("a", 50, 98.0, 100.0)]
    assert jumps.plateau_breaks(rows, 72, 0.01, opened_at=at(0), direction="lower") == []


def test_plateau_break_after_quiet_window_following_earlier_promotion():
    from outcomes import jumps
    rows = [_p("a", 100, 98.0, 100.0), _p("b", 200, 95.0, 98.0)]
    out = jumps.plateau_breaks(rows, 72, 0.01, opened_at=at(0), direction="lower")
    assert [r.id for r in out] == ["a", "b"]


def test_plateau_not_break_when_recent_qualifying_promotion():
    from outcomes import jumps
    rows = [_p("a", 100, 98.0, 100.0), _p("b", 150, 95.0, 98.0)]
    out = jumps.plateau_breaks(rows, 72, 0.01, opened_at=at(0), direction="lower")
    assert [r.id for r in out] == ["a"]


def test_plateau_small_recent_promotion_does_not_count_as_activity():
    from outcomes import jumps
    rows = [_p("tiny", 90, 99.5, 100.0), _p("b", 100, 98.0, 99.5)]
    out = jumps.plateau_breaks(rows, 72, 0.01, opened_at=at(0), direction="lower")
    assert [r.id for r in out] == ["b"]


def test_plateau_lower_boundary_exactly_1pct_counts_and_just_under_does_not():
    from outcomes import jumps
    exact = jumps.plateau_breaks([_p("x", 100, 99.0, 100.0)], 72, 0.01,
                                 opened_at=at(0), direction="lower")
    under = jumps.plateau_breaks([_p("y", 100, 99.01, 100.0)], 72, 0.01,
                                 opened_at=at(0), direction="lower")
    assert [r.id for r in exact] == ["x"]
    assert under == []


def test_plateau_higher_boundary_exactly_1pct_counts_and_just_under_does_not():
    from outcomes import jumps
    exact = jumps.plateau_breaks([_p("x", 100, 101.0, 100.0)], 72, 0.01,
                                 opened_at=at(0), direction="higher")
    exact2 = jumps.plateau_breaks([_p("z", 100, 202.0, 200.0)], 72, 0.01,
                                  opened_at=at(0), direction="higher")
    under = jumps.plateau_breaks([_p("y", 100, 100.99, 100.0)], 72, 0.01,
                                 opened_at=at(0), direction="higher")
    assert [r.id for r in exact] == ["x"]
    assert [r.id for r in exact2] == ["z"]
    assert under == []


def test_plateau_window_boundary_exactly_72h_is_not_a_break():
    from outcomes import jumps
    rows = [_p("a", 72, 98.0, 100.0)]
    assert jumps.plateau_breaks(rows, 72, 0.01, opened_at=at(0), direction="lower") == []


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


def test_pareto_equal_point_not_gain_and_one_strict_dominates():
    from outcomes import pareto
    rows = [row("a", 1, metrics=_m(10, 10)),
            row("b", 2, metrics=_m(10, 10)),   # identical to a -> not a gain
            row("c", 3, metrics=_m(10, 11))]   # a weakly better, one strict -> dominated
    assert pareto.pareto_gain(rows) == [True, False, False]


def test_pareto_identical_point_to_earlier_valid_row_is_not_a_gain():
    from outcomes import pareto
    rows = [row("a", 1, metrics=_m(10, 10)), row("b", 2, metrics=_m(10, 10))]
    assert pareto.pareto_gain(rows) == [True, False]


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


# ----------------------------------------------------- v2.1 evaluation order

def _finish_order_subs():
    # X created first but finished last; Y created later but finished first.
    return [sub("X", 1, 95.0, promoted=True, finished=10),
            sub("Y", 5, 100.0, promoted=True, finished=3)]


def test_recompute_uses_finished_at_not_created_at():
    from outcomes import promotion
    # finish order: Y(100) promotes, X(95) beats it. Creation order would
    # give [True, False].
    assert promotion.recompute(_finish_order_subs(), meta("lower")) == [True, True]


def test_best_before_uses_finished_at_reference():
    from outcomes import frontier
    assert frontier.best_before(_finish_order_subs(), meta("lower")) == [100.0, None]


def test_gain_log_positive_when_finish_order_differs_from_creation_order():
    from outcomes import frontier
    subs = _finish_order_subs()
    m = meta("lower")
    bb = frontier.best_before(subs, m)
    gains = [frontier.gain_log(s, b, m) for s, b in zip(subs, bb)]
    assert gains[0] == pytest.approx(math.log(100 / 95))
    assert gains[1] is None  # no prior best, no baseline
    assert all(g is None or g > 0 for g in gains)


def test_missing_finished_at_falls_back_to_created_at():
    from outcomes import promotion
    subs = [sub("a", 1, 100.0), sub("b", 2, 95.0, finished=3), sub("c", 4, 90.0)]
    # a: created 1 (no finish) -> 1; b: finished 3; c: created 4.
    assert promotion.recompute(subs, meta("lower")) == [True, True, True]
    subs2 = [sub("a", 1, 100.0), sub("b", 9, 95.0, finished=0.5)]
    # b finished before a's created_at: b first (promote), a (100) does not beat 95.
    assert promotion.recompute(subs2, meta("lower")) == [False, True]


# ------------------------------------------------------------ v2.1 seeding

def test_recompute_baseline_seed_lower_first_row_worse_not_promoted():
    from outcomes import promotion
    subs = [sub("a", 1, 120.0), sub("b", 2, 90.0), sub("c", 3, 95.0)]
    assert promotion.recompute(subs, meta("lower", baseline=100.0)) == [False, True, False]


def test_recompute_baseline_seed_higher_first_row_worse_not_promoted():
    from outcomes import promotion
    subs = [sub("a", 1, 0.4), sub("b", 2, 0.7)]
    assert promotion.recompute(subs, meta("higher", baseline=0.5)) == [False, True]


def test_first_promotion_gain_log_is_against_baseline_lower():
    from outcomes import frontier
    subs = [sub("a", 1, 90.0, promoted=True)]
    m = meta("lower", baseline=100.0)
    bb = frontier.best_before(subs, m)
    assert bb == [100.0]
    assert frontier.gain_log(subs[0], bb[0], m) == pytest.approx(math.log(100 / 90))


def test_first_promotion_gain_log_is_against_baseline_higher():
    from outcomes import frontier
    subs = [sub("a", 1, 0.66, promoted=True)]
    m = meta("higher", baseline=0.6)
    bb = frontier.best_before(subs, m)
    assert bb == [0.6]
    assert frontier.gain_log(subs[0], bb[0], m) == pytest.approx(math.log(0.66 / 0.6))


def test_best_before_after_promotion_overrides_baseline():
    from outcomes import frontier
    subs = [sub("a", 1, 90.0, promoted=True), sub("b", 2, 80.0, promoted=True)]
    assert frontier.best_before(subs, meta("lower", baseline=100.0)) == [100.0, 90.0]


# ----------------------------------------------------- v2.1 named exceptions

def test_superseded_rows_are_a_named_exception_class():
    from outcomes import promotion
    subs = [
        sub("a", 1, 100.0, promoted=True),
        sub("s", 2, 90.0, promoted=False, status="accepted", promotion_status="superseded"),
        sub("z", 3, 105.0, promoted=True),   # genuine disagreement
    ]
    assert promotion.disagreements(subs, meta("lower")) == ["z"]


def test_non_superseded_non_promoted_better_row_is_still_a_disagreement():
    from outcomes import promotion
    subs = [
        sub("a", 1, 100.0, promoted=True),
        sub("n", 2, 90.0, promoted=False, status="rejected", promotion_status=None),
    ]
    assert promotion.disagreements(subs, meta("lower")) == ["n"]


def test_at5_report_counts_exceptions_and_not_reproduced_list():
    from outcomes import promotion
    good = [sub("g1", 1, 100.0, promoted=True), sub("g2", 2, 90.0, promoted=True)]
    exc = [sub("e1", 1, 100.0, promoted=True),
           sub("e2", 2, 90.0, status="accepted", promoted=False, promotion_status="failed"),
           sub("e3", 3, 80.0, status="accepted", promoted=False, promotion_status="superseded")]
    bad = [sub(f"b{i}", i, 100.0 - i, promoted=False) for i in range(1, 6)]
    rep = promotion.at5_report({
        "good": (good, meta("lower")), "exc": (exc, meta("lower")),
        "bad": (bad, meta("lower"))})
    assert rep["counts"]["good"]["disagreements"] == 0
    assert rep["counts"]["exc"]["disagreements"] == 0
    assert rep["counts"]["exc"]["exceptions"] == 2
    assert rep["counts"]["bad"]["rows"] == 5
    assert rep["counts"]["bad"]["disagreements"] > 0
    assert rep["not_reproduced"] == ["bad"]


def test_at5_report_threshold_is_one_percent():
    from outcomes import promotion
    # 100 rows, 1 disagreement = exactly 1%: reproduced; 2 = 2%: not.
    def build(n_bad):
        rows = [sub(f"r{i}", i, 1000.0 - i, promoted=True) for i in range(100)]
        for k in range(n_bad):
            rows[k * 2] = sub(f"r{k * 2}", k * 2, 1000.0 - k * 2, promoted=False)
        return rows
    rep = promotion.at5_report({"one": (build(1), meta("lower")),
                                "two": (build(2), meta("lower"))})
    assert rep["not_reproduced"] == ["two"]


# --------------------------------------------------- v2.1 denominator classes

def test_analysis_rows_drops_infrastructure_failures_exact_and_regex():
    from outcomes import denominator
    subs = [
        sub("i1", 1, status="failed", reason="rate limited"),
        sub("i2", 2, status="failed", reason="validation job interrupted by host"),
        sub("e", 3, status="failed", reason="ordinary failure"),
    ]
    out = denominator.analysis_rows(subs, "yukon/b", config=DENOM_CONFIG)
    assert [s.id for s in out] == ["e"]


def test_analysis_rows_keeps_ambiguous_by_default_drops_with_flag():
    from outcomes import denominator
    subs = [sub("amb", 1, status="failed", reason="unclear failure"),
            sub("e", 2, status="failed", reason="ordinary failure")]
    kept = denominator.analysis_rows(subs, "yukon/b", config=DENOM_CONFIG)
    assert [s.id for s in kept] == ["amb", "e"]
    dropped = denominator.analysis_rows(subs, "yukon/b", config=DENOM_CONFIG,
                                        drop_ambiguous=True)
    assert [s.id for s in dropped] == ["e"]


def test_analysis_rows_drops_non_final_statuses():
    from outcomes import denominator
    subs = [sub("v", 1, status="validating"), sub("q", 2, status="queued"),
            sub("r", 3, status="running"), sub("ok", 4, score=1.0, status="accepted"),
            sub("f", 5, status="failed")]
    out = denominator.analysis_rows(subs, "yukon/b", config=DENOM_CONFIG)
    assert [s.id for s in out] == ["ok", "f"]


# ------------------------------------------------------------------------ AT5

STUDY_MARKERS = [
    "ecdsafail", "sig-golf", "flock-challenge", "flock-challenge-multi",
    "eip8200", "lighter-prover", "qwen38-125b-a6b-cuda-v1",
    "mlxfast-gemma4-26b-a4b", "mlxfast-challenge",
]


def test_at5_all_study_benchmarks_in_snapshot_report_counts():
    from outcomes import denominator, promotion
    from snapshot import load as snap
    names = snap.benchmarks()
    study = [n for n in names if any(m in n for m in STUDY_MARKERS)]
    ecdsa = [n for n in study if "ecdsafail" in n]
    assert ecdsa == ["gpsanant/ecdsafail-challenge"], "ecdsa.fail must be in the snapshot"
    items = {}
    for n in study:
        rows = denominator.analysis_rows(snap.load(n), n)
        items[n] = (rows, snap.benchmark_meta(n))
    rep = promotion.at5_report(items)
    assert set(rep["counts"]) == set(study)
    for n in study:
        c = rep["counts"][n]
        assert isinstance(c["disagreements"], int) and c["rows"] == len(items[n][0])
    assert isinstance(rep["not_reproduced"], list)
    e = "gpsanant/ecdsafail-challenge"
    assert rep["counts"][e]["disagreements"] == 0
    assert e not in rep["not_reproduced"]
    accepted_failed = [s for s in items[e][0]
                       if s.status == "accepted" and not s.promoted]
    assert len(accepted_failed) == 4
