"""The single section 5.1 design builder. Power and confirmatory both import it."""
from __future__ import annotations

import numpy as np
import pandas as pd

REQUIRED_COLUMNS = ("cross_solver", "cross_family", "in_window", "parent_method")
CATEGORICAL = ("child_family_folded", "parent_family_folded")
TIME = "days_since_open"
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


def time_spline(x) -> pd.DataFrame:
    """Natural (restricted) cubic spline basis, 4 df: x itself plus three nonlinear terms, with
    knots at the minimum, the three quartiles and the maximum of x (Harrell's form)."""
    x = np.asarray(x, float)
    t = np.quantile(x, [0, 0.25, 0.5, 0.75, 1.0])
    k = len(t)
    pos = lambda v: np.clip(v, 0, None) ** 3  # noqa: E731
    span = t[-1] - t[-2]
    cols = [x]
    if span > 0 and t[-1] > t[0]:
        for j in range(k - 2):
            cols.append((pos(x - t[j])
                         - pos(x - t[-2]) * (t[-1] - t[j]) / span
                         + pos(x - t[-1]) * (t[-2] - t[j]) / span) / (t[-1] - t[0]) ** 2)
    else:
        cols += [np.zeros_like(x)] * (k - 2)
    return pd.DataFrame(np.column_stack(cols), columns=[f"time_s{i}" for i in range(1, k)])


def build(frame):
    """(X, y_column_name, groups). X holds cross_family first, then time_s1..time_s4 (spline on days_since_open), child_family_folded
    and parent_family_folded dummies (drop_first), parent_is_current_best, log_prior_rows.
    The outcome is not part of X; callers add a column named y_column_name."""
    parts = [frame["cross_family"].astype(bool).astype(float).rename("cross_family"),
             time_spline(frame[TIME]).set_index(frame.index)]
    for c in CATEGORICAL:
        parts.append(pd.get_dummies(frame[c].astype(str), prefix=c, drop_first=True,
                                    dtype=float))
    for c in NUMERIC:
        parts.append(frame[c].astype(float))
    X = pd.concat(parts, axis=1)
    return X, Y_NAME, frame["solver"].to_numpy()
