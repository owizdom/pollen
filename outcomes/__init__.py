"""Outcomes (spec 0001 section 3.5). Sealed until prereg-v1 (section 5.8)."""
from __future__ import annotations

import gzip
import json
from pathlib import Path

SEALED_DIR = Path(__file__).resolve().parent / "sealed"


def annotate(subs, meta, out_dir=None) -> None:
    """Write per-row outcome columns to <out_dir>/<meta.slug>.json.gz.

    Returns nothing; no output is split by treatment.
    """
    from . import frontier, jumps, pareto, promotion

    out = Path(out_dir) if out_dir is not None else SEALED_DIR
    out.mkdir(parents=True, exist_ok=True)
    ordered = sorted(subs, key=lambda s: (s.created_at, s.id))
    bb = frontier.best_before(ordered, meta)
    rec = promotion.recompute_excluding(ordered, meta, _accepted_not_promoted(ordered))
    rows = [
        _Row(s.id, s.created_at, s.promoted, frontier.gain_log(s, b, meta), s.metrics,
             s.score, b)
        for s, b in zip(ordered, bb)
    ]
    big = {r.id for r in jumps.large_jumps(rows)}
    plateau = {r.id for r in jumps.plateau_breaks(
        rows, opened_at=meta.opened_at, direction=meta.direction)}
    pg = pareto.pareto_gain(rows)
    data = [
        {
            "id": s.id,
            "created_at": s.created_at.isoformat(),
            "y1": promotion.y1(s),
            "recomputed_promoted": rec[k],
            "best_before": bb[k],
            "gain_log": rows[k].gain_log,
            "large_jump": s.id in big,
            "plateau_break": s.id in plateau,
            "pareto_gain": pg[k],
        }
        for k, s in enumerate(ordered)
    ]
    payload = json.dumps({"slug": meta.slug, "rows": data}, sort_keys=True).encode()
    with open(out / f"{meta.slug}.json.gz", "wb") as raw:
        with gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as f:
            f.write(payload)


def _accepted_not_promoted(subs):
    return [s.id for s in subs if s.status == "accepted" and not s.promoted]


class _Row:
    __slots__ = ("id", "created_at", "promoted", "gain_log", "metrics", "score", "best_before")

    def __init__(self, id, created_at, promoted, gain_log, metrics, score=None, best_before=None):
        self.score = score
        self.best_before = best_before
        self.id = id
        self.created_at = created_at
        self.promoted = promoted
        self.gain_log = gain_log
        self.metrics = metrics
