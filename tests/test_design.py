"""Track E1: analysis.design, the single design builder (spec 0001 section 5.1)."""
from __future__ import annotations

import pandas as pd
import pytest

from tests.fixtures_analysis import add_non_primary_rows, cells_frame


def test_primary_rows_keeps_only_primary():
    from analysis import design
    base = cells_frame(6, 5, seed=1)
    frame = add_non_primary_rows(base)
    out = design.primary_rows(frame)
    assert len(out) == len(base)
    assert out["cross_solver"].astype(bool).all()
    assert out["in_window"].astype(bool).all()
    assert out["cross_family"].notna().all()
    assert out["parent_method"].isin(["declared", "tree"]).all()


@pytest.mark.parametrize("col", ["cross_solver", "cross_family", "in_window", "parent_method"])
def test_primary_rows_raises_on_missing_column(col):
    from analysis import design
    with pytest.raises((KeyError, ValueError)):
        design.primary_rows(cells_frame(6, 5, seed=1).drop(columns=[col]))


def _built(seed=3):
    from analysis import design
    frame = design.primary_rows(cells_frame(8, 6, seed=seed))
    return frame, design.build(frame)


def test_build_columns_and_groups():
    frame, (X, y_name, groups) = _built()
    assert isinstance(X, pd.DataFrame)
    assert isinstance(y_name, str)
    cols = list(X.columns)
    assert cols[0] == "cross_family"
    assert cols[1:5] == ["time_s1", "time_s2", "time_s3", "time_s4"]
    assert not [c for c in cols if c.startswith("week")]
    child = [c for c in cols if c.startswith("child_family_folded")]
    parent = [c for c in cols if c.startswith("parent_family_folded")]
    assert len(child) == frame["child_family_folded"].nunique() - 1   # drop_first
    assert len(parent) == frame["parent_family_folded"].nunique() - 1
    assert cols == (["cross_family", "time_s1", "time_s2", "time_s3", "time_s4"] + child
                    + parent + ["parent_is_current_best", "log_prior_rows"])
    assert len(X) == len(frame) == len(groups)
    assert list(pd.Series(groups).astype(str)) == list(frame["solver"].astype(str))
    assert X.notna().all().all()


def test_spline_basis_is_deterministic():
    from analysis import design
    frame, (X, _, _) = _built()
    X2, _, _ = design.build(frame.copy())
    pd.testing.assert_frame_equal(X[[f"time_s{i}" for i in range(1, 5)]],
                                  X2[[f"time_s{i}" for i in range(1, 5)]])


def test_spline_basis_depends_only_on_days_since_open():
    from analysis import design
    frame, (X, _, _) = _built()
    shuffled = frame.assign(week="2026-W09")
    X2, _, _ = design.build(shuffled)
    pd.testing.assert_frame_equal(X[[f"time_s{i}" for i in range(1, 5)]],
                                  X2[[f"time_s{i}" for i in range(1, 5)]])


def test_spline_columns_not_collinear_with_intercept_given_five_days():
    import numpy as np
    frame, (X, _, _) = _built()
    assert frame["days_since_open"].nunique() >= 5
    T = X[[f"time_s{i}" for i in range(1, 5)]].to_numpy(float)
    M = np.column_stack([np.ones(len(T)), T])
    assert np.linalg.matrix_rank(M) == 5
    assert (T.std(axis=0) > 0).all()


def test_spline_columns_vary_with_days():
    frame, (X, _, _) = _built()
    day = frame["days_since_open"].to_numpy()
    lo, hi = day.argmin(), day.argmax()
    assert not (X.iloc[lo][["time_s1", "time_s2", "time_s3", "time_s4"]].to_numpy()
                == X.iloc[hi][["time_s1", "time_s2", "time_s3", "time_s4"]].to_numpy()).all()
