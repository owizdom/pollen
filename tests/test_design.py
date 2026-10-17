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


def test_build_columns_and_groups():
    from analysis import design
    frame = design.primary_rows(cells_frame(8, 6, seed=3))
    X, y_name, groups = design.build(frame)
    assert isinstance(X, pd.DataFrame)
    assert isinstance(y_name, str)
    cols = list(X.columns)
    assert cols[0] == "cross_family"
    assert "parent_is_current_best" in cols and "log_prior_rows" in cols
    week_cols = [c for c in cols if c.startswith("week")]
    assert len(week_cols) == frame["week"].nunique() - 1          # drop_first
    child = [c for c in cols if c.startswith("child_family_folded")]
    parent = [c for c in cols if c.startswith("parent_family_folded")]
    assert len(child) == frame["child_family_folded"].nunique() - 1
    assert len(parent) == frame["parent_family_folded"].nunique() - 1
    assert len(X) == len(frame) == len(groups)
    assert list(pd.Series(groups).astype(str)) == list(frame["solver"].astype(str))
    assert X.notna().all().all()
