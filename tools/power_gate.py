"""Pre-lock power gate (spec 0001 section 5.3): equivalence power at OR 1 on the real frames.

Uses treatment counts and each benchmark's marginal promotion rate only. Writes results/power.json.
"""
import json
import sys
import time
from pathlib import Path

WORKERS = 6
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from analysis import dataset, power, study  # noqa: E402
from outcomes import denominator  # noqa: E402
from snapshot import load as snapshot  # noqa: E402


def main(sims: int = 2000) -> dict:
    names = study.benchmarks()
    frames, rates = {}, {}
    for b in names:
        frames[b] = dataset.build(b)
        rows = denominator.analysis_rows(snapshot.load(b), b)
        rates[b] = sum(s.promoted for s in rows) / len(rows)
    t = time.time()
    rep = power.pooled_equivalence_power_report(frames, rates, sims=sims, workers=WORKERS)
    out = {"benchmarks": names, "sims": sims, "margin": [0.80, 1.25], **rep,
           "seconds": round(time.time() - t)}
    if rep["power"] < 0.80:
        out["widened_margin"] = [0.67, 1.50]
        out["power_widened"] = power.pooled_equivalence_power_report(
            frames, rates, margin=(0.67, 1.50), sims=sims, workers=WORKERS)["power"]
    (ROOT / "results").mkdir(exist_ok=True)
    (ROOT / "results/power.json").write_text(json.dumps(out, indent=2) + "\n")
    return out


if __name__ == "__main__":
    print(json.dumps(main(int(sys.argv[1]) if len(sys.argv) > 1 else 2000), indent=2))
