"""Offline loader for the frozen Yukon snapshot. Never touches the network.

Every file opened is checked against SHA256SUMS; any .gz file in a benchmark
directory that is absent from SHA256SUMS is an integrity error.
"""
from __future__ import annotations

import datetime as dt
import gzip
import hashlib
import json
from pathlib import Path

from .model import Benchmark, Submission

DEFAULT_ROOT = Path(__file__).resolve().parent / "raw"


class IntegrityError(Exception):
    pass


def slug_of(name: str) -> str:
    return name.replace("/", "__")


def _root(root) -> Path:
    return Path(root) if root is not None else DEFAULT_ROOT


def _sums(root: Path) -> dict[str, str]:
    p = root / "SHA256SUMS"
    if not p.exists():
        raise IntegrityError(f"missing {p}")
    out = {}
    for line in p.read_text().splitlines():
        if not line.strip():
            continue
        digest, _, rel = line.partition("  ")
        out[rel.strip()] = digest.strip()
    return out


def _verify_freeze(root: Path, sums: dict[str, str]) -> None:
    p = root / "FREEZE.json"
    if not p.exists():
        raise IntegrityError(f"missing {p}")
    if "FREEZE.json" not in sums:
        raise IntegrityError("FREEZE.json not listed in SHA256SUMS")
    if hashlib.sha256(p.read_bytes()).hexdigest() != sums["FREEZE.json"]:
        raise IntegrityError("checksum mismatch for FREEZE.json")


def _verify_dir(root: Path, name: str) -> None:
    sums = _sums(root)
    _verify_freeze(root, sums)
    d = root / slug_of(name)
    prefix = slug_of(name) + "/"
    for rel in sums:
        if rel.startswith(prefix) and not (root / rel).exists():
            raise IntegrityError(f"{rel} listed in SHA256SUMS but missing")
    for p in sorted(d.glob("*.gz")):
        rel = p.relative_to(root).as_posix()
        if rel not in sums:
            raise IntegrityError(f"{rel} not listed in SHA256SUMS")
        if hashlib.sha256(p.read_bytes()).hexdigest() != sums[rel]:
            raise IntegrityError(f"checksum mismatch for {rel}")


def _read(root: Path, name: str, fname: str):
    _verify_dir(root, name)
    p = root / slug_of(name) / fname
    if not p.exists():
        raise IntegrityError(f"missing {p}")
    with gzip.open(p, "rb") as f:
        return json.loads(f.read())


def _freeze(root: Path) -> dict:
    p = root / "FREEZE.json"
    if not p.exists():
        raise IntegrityError(f"missing {p}")
    _verify_freeze(root, _sums(root))
    return json.loads(p.read_text())


def _ts(s) -> dt.datetime | None:
    if not s:
        return None
    t = dt.datetime.fromisoformat(s)
    return t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)


def parse_model_line(note: str | None) -> str | None:
    """Text after 'Model:' on the first non-empty line of the note, else None."""
    for line in (note or "").splitlines():
        line = line.strip()
        if not line:
            continue
        head, sep, rest = line.partition(":")
        if sep and head.strip().lower() == "model":
            return rest.strip() or None
        return None
    return None


def benchmarks(root=None) -> list[str]:
    return sorted(_freeze(_root(root))["counts"])


def benchmark_meta(benchmark: str, root=None) -> Benchmark:
    data = _read(_root(root), benchmark, "benchmark.json.gz")
    b = data.get("benchmark", data)
    return Benchmark(
        id=b["id"],
        name=b["name"],
        slug=slug_of(b["name"]),
        direction="lower" if b["direction"] == "-" else "higher",
        editable_paths=list(b.get("editablePaths") or []),
        source_url=b.get("sourceUrl"),
        opened_at=_ts(b.get("openedAt")),
        min_improvement_bips=b.get("minScoreImprovementBips"),
    )


def load(benchmark: str, root=None) -> list[Submission]:
    root = _root(root)
    data = _read(root, benchmark, "submissions.json.gz")
    raw = data["submissions"] if isinstance(data, dict) else data
    expected = _freeze(root)["counts"].get(benchmark)
    if expected is None or expected != len(raw):
        raise IntegrityError(
            f"{benchmark}: {len(raw)} rows, FREEZE.json says {expected}")
    rows = []
    for r in raw:
        status = r.get("status")
        rows.append(Submission(
            id=r["id"],
            benchmark=benchmark,
            solver=r.get("solverUsername"),
            created_at=_ts(r["createdAt"]),
            status=status,
            promoted=status == "accepted" and r.get("promotionStatus") == "promoted",
            cancelled=status == "cancelled",
            score=r.get("officialScore"),
            metrics=r.get("officialMetrics") or {},
            note=r.get("note") or "",
            model_line=parse_model_line(r.get("note")),
            commit_sha=r.get("promotedSourceRef") or r.get("submissionCommitSha"),
            rejection_reason=r.get("rejectionReason"),
            submission_sha=r.get("submissionCommitSha"),
            promoted_ref=r.get("promotedSourceRef"),
        ))
    rows.sort(key=lambda s: (s.created_at, s.id))
    return rows


def attribution(benchmark: str, root=None) -> dict[str, list[str]]:
    """Submission id -> declared parent ids, in listed order. Empty if no file."""
    root = _root(root)
    _verify_dir(root, benchmark)
    p = root / slug_of(benchmark) / "attribution.json.gz"
    listed = benchmark in (_freeze(root).get("attribution") or [])
    if not p.exists():
        if listed:
            raise IntegrityError(f"{benchmark}: attribution file listed in FREEZE.json is missing")
        return {}
    if not listed:
        raise IntegrityError(f"{benchmark}: attribution file present but not listed in FREEZE.json")
    with gzip.open(p, "rb") as f:
        recs = json.loads(f.read())
    partial = set((_freeze(root).get("attribution_partial") or {}).get(benchmark, []))
    for rec in recs:
        if rec.get("nextCursor") and rec["submissionId"] not in partial:
            raise IntegrityError(
                f"{benchmark}: {rec['submissionId']} has a nextCursor but is not listed as partial")
    out = {}
    for rec in recs:
        deps = [d["submissionId"] for d in rec.get("dependencies") or []]
        if rec.get("declaration") == "provided" and deps:
            out[rec["submissionId"]] = deps
    return out
