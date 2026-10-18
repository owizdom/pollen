"""AT4 and AT15 on the frozen snapshot and lineage (spec 0001 section 8)."""
import json
from pathlib import Path

from lineage import validate

ROOT = Path(__file__).resolve().parent.parent
FREEZE = ROOT / "snapshot/raw/FREEZE.json"


def _study():
    return json.loads(FREEZE.read_text())["attribution"]


def test_at4_inferred_cell_agrees_with_both_labelled_sets():
    pooled = {"declared": [0, 0], "text": [0, 0]}
    for b in _study():
        for kind, counts in validate.at4_benchmark(b).items():
            a, n = validate.agreement(counts)
            pooled[kind][0] += a
            pooled[kind][1] += n
    a, n = pooled["text"]
    assert n > 0, "no text-declared labelled rows"
    assert a / n >= validate.AT4_MIN, f"AT4 text: {a}/{n} = {a / n:.3f}"
    # declared edges are reported, not gated (spec v2.9: only 24 are checkable)
    print(f"AT4 declared: {pooled['declared'][0]}/{pooled['declared'][1]}")


def test_at15_window_balance_in_every_study_benchmark():
    for b in _study():
        r = validate.at15_benchmark(b)
        assert r["start"] is not None, f"{b}: no balanced window"
        gap = abs(r["promoted_share"] - r["other_share"])
        assert gap <= validate.AT15_TOL + 1e-12, f"{b}: gap {gap:.3f}"
