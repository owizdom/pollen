import gzip
import hashlib
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))


def _sub(i, bench, status, created, **kw):
    row = {
        "id": i,
        "benchmarkId": bench,
        "solverUsername": kw.pop("solver", "alice"),
        "status": status,
        "note": kw.pop("note", "Model: GPT-5 Codex\n\nTried a new window size."),
        "officialScore": kw.pop("officialScore", None),
        "officialMetrics": kw.pop("officialMetrics", None),
        "promotionStatus": kw.pop("promotionStatus", None),
        "promotedSourceRef": kw.pop("promotedSourceRef", None),
        "submissionCommitSha": kw.pop("submissionCommitSha", None),
        "createdAt": created,
        "rejectionReason": kw.pop("rejectionReason", None),
    }
    row.update(kw)
    return row


# Deliberately out of chronological order to check sorting.
LOWER_SUBS = [
    _sub("s3", "b1", "rejected", "2026-03-03T10:00:00.000Z", solver="bob",
         note="Model: Claude Opus 4.8 (1M context)\nregressed", officialScore=105.0,
         rejectionReason="did not improve on best score",
         submissionCommitSha="cccc333"),
    _sub("s1", "b1", "accepted", "2026-03-01T10:00:00.000Z",
         officialScore=100.0, officialMetrics={"size": 100, "time": 1.5},
         promotionStatus="promoted", promotedSourceRef="aaaa111",
         submissionCommitSha="zzzz000"),
    _sub("s2", "b1", "accepted", "2026-03-02T10:00:00.000Z", solver="bob",
         note="\n  Model:   Kimi K3  \nbody", officialScore=95.0,
         promotionStatus="failed", submissionCommitSha="bbbb222"),
    _sub("s4", "b1", "failed", "2026-03-04T10:00:00.000Z",
         note="no model line here, just prose", officialScore=None),
    _sub("s5", "b1", "cancelled", "2026-03-05T10:00:00.000Z",
         note="Model: Devin\nstopped"),
]
HIGHER_SUBS = [
    _sub("h1", "b2", "accepted", "2026-04-01T08:30:00.000Z", officialScore=0.5,
         promotionStatus="promoted", submissionCommitSha="dddd444"),
]

BENCHES = {
    "yukon/lower-bench": ("-", LOWER_SUBS, "b1"),
    "yukon/higher-bench": ("+", HIGHER_SUBS, "b2"),
}


def _attr(sid, decl, parents):
    return {"submissionId": sid, "declaration": decl,
            "dependencies": [{"submissionId": p, "rationale": "r", "evidence": "e"}
                             for p in parents],
            "proposals": [], "edges": [], "nextCursor": None}


# Only the lower benchmark has an attribution file (large benchmarks only).
ATTRIBUTION = {
    "yukon/lower-bench": [
        _attr("s3", "provided", ["s2", "s1"]),
        _attr("s2", "provided", ["s1"]),
        _attr("s4", "not_provided", []),
    ],
}


def _gz(path: Path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.GzipFile(path, "wb", mtime=0) as f:
        f.write(json.dumps(obj).encode())


def build_snapshot(root: Path) -> Path:
    counts = {}
    for name, (direction, subs, bid) in BENCHES.items():
        slug = name.replace("/", "__")
        meta = {"benchmark": {
            "id": bid, "name": name,
            "direction": direction,
            "editablePaths": ["src/main.py"],
            "sourceUrl": f"https://example.invalid/{slug}",
            "openedAt": "2026-02-01T00:00:00.000Z",
            "minScoreImprovementBips": 50 if direction == "-" else None,
        }}
        _gz(root / slug / "benchmark.json.gz", meta)
        _gz(root / slug / "submissions.json.gz", {"submissions": subs})
        counts[name] = len(subs)
        if name in ATTRIBUTION:
            _gz(root / slug / "attribution.json.gz", ATTRIBUTION[name])
    (root / "FREEZE.json").write_text(json.dumps(
        {"fetched_at": "2026-10-10T12:00:00Z", "api": "https://example.invalid/api",
         "counts": counts, "attribution": sorted(ATTRIBUTION)}))
    write_sums(root)
    return root


def write_sums(root: Path) -> None:
    """SHA256SUMS over every .gz and FREEZE.json (the frozen set)."""
    files = sorted(root.rglob("*.gz")) + [root / "FREEZE.json"]
    lines = [f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.relative_to(root)}"
             for p in files]
    (root / "SHA256SUMS").write_text("\n".join(lines) + "\n")


def edit_freeze(root: Path, fn) -> None:
    """Edit FREEZE.json via fn(dict) and re-sign SHA256SUMS."""
    f = json.loads((root / "FREEZE.json").read_text())
    fn(f)
    (root / "FREEZE.json").write_text(json.dumps(f))
    write_sums(root)


@pytest.fixture
def snap(tmp_path):
    return build_snapshot(tmp_path / "raw")
