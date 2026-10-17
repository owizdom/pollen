"""Seeded sample of notes for the label audit (AT3)."""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from families.mapper import family_of  # noqa: E402
from snapshot import load  # noqa: E402

OUT = Path(__file__).resolve().parent / "sample.jsonl"
MIN_ROWS = 500


def sample(n: int = 200, seed: int = 17, out: Path = OUT) -> list[dict]:
    pool = []
    for bench in load.benchmarks():
        rows = load.load(bench)
        if len(rows) < MIN_ROWS:
            continue
        pool.extend(r for r in rows if r.note)
    pool.sort(key=lambda r: (r.benchmark, r.id))
    picked = random.Random(seed).sample(pool, min(n, len(pool)))
    recs = [{"id": r.id, "benchmark": r.benchmark, "model_line": r.model_line,
             "family": family_of(r.model_line), "note": r.note, "note_chars": len(r.note)}
            for r in picked]
    out.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in recs))
    return recs


if __name__ == "__main__":
    print(f"wrote {len(sample())} notes to {OUT}")
