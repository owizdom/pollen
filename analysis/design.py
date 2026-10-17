"""The single section 5.1 design builder. Power and confirmatory both import it."""
from __future__ import annotations

import numpy as np
import pandas as pd

REQUIRED_COLUMNS = ("cross_solver", "cross_family", "in_window", "parent_method")
CATEGORICAL = ("child_family_folded", "parent_family_folded")
TIME = "days_since_open"
NUMERIC = ("parent_is_current_best", "log_prior_rows")
Y_NAME = "y_sim"
KNOT_COLS = tuple(f"spline_knot_{i}" for i in range(5))


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


def time_spline(x, knots=None) -> pd.DataFrame:
    """Natural (restricted) cubic spline basis, 4 df: x itself plus three nonlinear terms
    (Harrell's form). knots are the five knot positions: the boundary minimum, the three
    interior quartiles and the boundary maximum of days_since_open over the benchmark's
    analysis rows. When omitted they come from x itself."""
    x = np.asarray(x, float)
    t = np.quantile(x, [0, 0.25, 0.5, 0.75, 1.0]) if knots is None else np.asarray(knots, float)
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


def knots_of(frame):
    """The knots carried by the frame's spline_knot_* columns, else None."""
    if len(frame) and all(c in frame.columns for c in KNOT_COLS):
        return [float(frame[c].iloc[0]) for c in KNOT_COLS]
    return None


def build(frame, knots=None):
    """(X, y_column_name, groups). X holds cross_family first, then time_s1..time_s4 (spline on days_since_open), child_family_folded
    and parent_family_folded dummies (drop_first), parent_is_current_best, log_prior_rows.
    The outcome is not part of X; callers add a column named y_column_name."""
    parts = [frame["cross_family"].astype(bool).astype(float).rename("cross_family"),
             time_spline(frame[TIME], knots if knots is not None else knots_of(frame)).set_index(frame.index)]
    for c in CATEGORICAL:
        parts.append(pd.get_dummies(frame[c].astype(str), prefix=c, drop_first=True,
                                    dtype=float))
    for c in NUMERIC:
        parts.append(frame[c].astype(float))
    X = pd.concat(parts, axis=1)
    return X, Y_NAME, frame["solver"].to_numpy()
