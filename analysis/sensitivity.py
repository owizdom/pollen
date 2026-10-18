"""Sensitivity analyses 1 to 9 (spec 0001 section 5.5): the pooled primary estimate with one change each."""
from __future__ import annotations

import re
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from analysis import confirmatory, dataset, design, study
from outcomes import denominator

OWN_SOLVER = "owizdom"
SIBLINGS = (("eigenlabs/flock-challenge", "eigenlabs/flock-challenge-multi/x86"),
            ("eigenlabs/eip8200-challenges/modexp", "eigenlabs/eip8200-challenges/ripemd160"))
_ART = r"(?:(?:the|a|an|new|fresh|another|different)\s+)*"
_TERM = r"(?:validation\s+nonce|validation\s+draw|nonce)"
NONCE = re.compile(rf"(?<!not )\bonly(?:\s+change[sd]?)?\s*:?\s*{_ART}{_TERM}\b"
                   rf"|\b{_TERM}(?:-only\b|\s+only\s*(?:[.,;:!]|$))", re.I)
NAMES = {1: "s1_unknown_family", 2: "s2_tree_parents", 3: "s3_drop_nonce_rows",
         4: "s4_coarse_family", 5: "s5_drop_first_72h", 6: "s6_harness_effects",
         7: "s7_drop_author_rows", 8: "s8_one_per_sibling_pair", 9: "s9_drop_ambiguous_failures"}


def _pooled(frames, margin, extra=None) -> dict | None:
    """frames: name -> DataFrame (with y and the design columns). extra: name -> fn(rows)->columns."""
    ests = []
    for name in sorted(frames):
        rows = design.primary_rows(frames[name])
        if len(rows) == 0:
            continue
        add = extra(rows) if extra else None
        ests.append(confirmatory.rounded(confirmatory.fit_rows(rows, extra=add)))
    p = confirmatory.pool(ests, margin)
    if p is None:
        return None
    return {k: p[k] for k in ("log_or", "ci95", "ci90", "tau2", "k")}


def _result(p, reason="no benchmark gave a finite estimate", note=None):
    if p is None:
        return {"not_applicable": reason}
    out = {"pooled": p}
    if note:
        out["note"] = note
    return out


def _s1(df):
    """Unknown family as a family of its own: only Multi and missing labels stay excluded."""
    d = df.copy()
    ok = (d["parent_solver"].notna() & (d["parent_family"].notna()) & ~d["child_family"].isin(["Multi"])
          & ~d["parent_family"].isin(["Multi"]) & d["child_family"].notna())
    d["cross_family"] = pd.Series(np.where(ok, d["child_family"] != d["parent_family"], None),
                                  index=d.index, dtype=object)
    return d


def _coarse(f):
    return f if f in ("Anthropic", "OpenAI") else "Other"


def _s4(df):
    d = df.copy()
    known = d["cross_family"].notna()
    cf = d["child_family"].map(lambda f: _coarse(f) if f is not None else None)
    pf = d["parent_family"].map(lambda f: _coarse(f) if isinstance(f, str) else None)
    d["cross_family"] = pd.Series(np.where(known, cf != pf, None), index=d.index, dtype=object)
    d["child_family_folded"] = cf
    d["parent_family_folded"] = pf
    return d


def _harness_columns(rows):
    """Harness dummies that add rank to the primary design (harness and family are nearly collinear)."""
    X, _, _ = design.build(rows)
    dum = pd.get_dummies(rows["harness"].fillna("none").astype(str), prefix="harness",
                         drop_first=True, dtype=float)
    keep, M = [], X.to_numpy(float)
    rank = np.linalg.matrix_rank(M)
    for c in dum.columns:
        trial = np.column_stack([M, dum[c].to_numpy(float)])
        r = np.linalg.matrix_rank(trial)
        if r > rank:
            M, rank = trial, r
            keep.append(c)
    return dum[keep]


def run(root=None) -> dict:
    root = study.guard(root)
    snap = study.RootSnapshot(root)
    margin = study.margin(root)
    names = study.study_names(root)
    benches = {n: study.load_bench(root, n, snap) for n in names}
    base = {n: b.df for n, b in benches.items()}
    out = {}

    out[NAMES[1]] = _result(_pooled({n: _s1(d) for n, d in base.items()}, margin))

    tree = {}
    with study.tree_parents_only():
        for n in names:
            sealed = study.seal(root, n, snap)
            tree[n] = study.attach_outcomes(
                dataset.build(n, snapshot=snap, lineage_root=study.lineage_root(root)), sealed)
    out[NAMES[2]] = _result(_pooled(tree, margin),
                            note="immediate code parent, a different estimand from the declared origin")

    hit = {n: d["id"].map(lambda i, b=benches[n]: bool(NONCE.search(b.notes.get(i, "")))) for n, d in base.items()}
    if any(h.any() for h in hit.values()):
        out[NAMES[3]] = _result(_pooled({n: d[~hit[n]] for n, d in base.items()}, margin))
    else:
        out[NAMES[3]] = {"not_applicable": "no note says only a nonce or validation draw changed"}

    out[NAMES[4]] = _result(_pooled({n: _s4(d) for n, d in base.items()}, margin))

    cut = {}
    for n, d in base.items():
        opened = benches[n].meta.opened_at or d["created_at"].min()
        cut[n] = d[d["created_at"] >= opened + timedelta(hours=72)]
    out[NAMES[5]] = _result(_pooled(cut, margin))

    out[NAMES[6]] = _result(_pooled(base, margin, extra=_harness_columns),
                            note="harness dummies enter only when they add rank beyond the family dummies")

    out[NAMES[7]] = _result(_pooled({n: d[d["solver"] != OWN_SOLVER] for n, d in base.items()}, margin))

    drop = set()
    for a, b in SIBLINGS:
        if a in base and b in base:
            drop.add(min((a, b), key=lambda n: (-len(base[n]), n)))
    if drop:
        out[NAMES[8]] = _result(_pooled({n: d for n, d in base.items() if n not in drop}, margin))
    else:
        out[NAMES[8]] = {"not_applicable": "no sibling benchmark pair is in the study"}

    kept = {}
    for n, b in benches.items():
        ids = {s.id for s in denominator.analysis_rows(b.subs, n, drop_ambiguous=True)}
        kept[n] = base[n][base[n]["id"].isin(ids)]
    if any(len(kept[n]) < len(base[n]) for n in base):
        out[NAMES[9]] = _result(_pooled(kept, margin))
    else:
        out[NAMES[9]] = {"not_applicable": "no analysis row has an ambiguous failure reason"}
    return study.dump({"sensitivities": out}, Path(root) / "results" / "sensitivity.json")
