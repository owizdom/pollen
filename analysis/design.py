"""The single section 5.1 design builder. Power and confirmatory both import it."""
from __future__ import annotations

import pandas as pd

REQUIRED_COLUMNS = ("cross_solver", "cross_family", "in_window", "parent_method")
CATEGORICAL = ("week", "child_family_folded", "parent_family_folded")
NUMERIC = ("parent_is_current_best", "log_prior_rows")
Y_NAME = "y_sim"


def primary_rows(frame) -> pd.DataFrame:
    """Cross-solver single-parent rows with a known cross_family, inside the window."""
    missing = [c for c in REQUIRED_COLUMNS if c not in frame.columns]
    if missing:
        raise ValueError(f"frame lacks columns: {missing}")
    keep = ((frame["cross_solver"] == True)  # noqa: E712
            & frame["cross_family"].notna()
            & (frame["in_window"] == True)  # noqa: E712
            & frame["parent_method"].isin(["declared", "tree"]))
    return frame[keep].reset_index(drop=True)


def build(frame):
    """(X, y_column_name, groups). X holds cross_family first, then week, child_family_folded
    and parent_family_folded dummies (drop_first), parent_is_current_best, log_prior_rows.
    The outcome is not part of X; callers add a column named y_column_name."""
    parts = [frame["cross_family"].astype(bool).astype(float).rename("cross_family")]
    for c in CATEGORICAL:
        parts.append(pd.get_dummies(frame[c].astype(str), prefix=c, drop_first=True,
                                    dtype=float))
    for c in NUMERIC:
        parts.append(frame[c].astype(float))
    X = pd.concat(parts, axis=1)
    return X, Y_NAME, frame["solver"].to_numpy()
