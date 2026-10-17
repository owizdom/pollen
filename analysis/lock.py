"""Pre-registration manifest and lock check (spec 0001 section 5.8)."""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = "docs/prereg-manifest.json"
TAG = "prereg-v1"
FIXED = ["docs/prereg.md", "families/table.yaml", "outcomes/denominator.yaml",
         "snapshot/raw/SHA256SUMS", "lineage/frozen/SHA256SUMS"]


class LockError(Exception):
    pass


def _skip(rel: Path) -> bool:
    parts = rel.parts
    if "__pycache__" in parts or rel.suffix == ".pyc":
        return True
    if parts[0] == "lineage" and len(parts) > 1:
        if parts[1] == "cache":
            return True
        if parts[1] == "frozen" and rel.as_posix() != "lineage/frozen/SHA256SUMS":
            return True
    return False


def _paths(root: Path) -> list[str]:
    out = {r for r in FIXED if (root / r).is_file()}
    for top in ("analysis", "lineage"):
        for p in (root / top).rglob("*") if (root / top).is_dir() else []:
            if p.is_file() and not _skip(p.relative_to(root)):
                out.add(p.relative_to(root).as_posix())
    return sorted(out)


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def compute(root=ROOT) -> dict:
    root = Path(root)
    return {rel: _sha(root / rel) for rel in _paths(root)}


def write_manifest(root=ROOT) -> Path:
    root = Path(root)
    out = root / MANIFEST
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(compute(root), indent=2, sort_keys=True) + "\n")
    return out


def check(root=ROOT) -> None:
    root = Path(root)
    mp = root / MANIFEST
    if not mp.is_file():
        raise LockError(f"missing {MANIFEST}")
    try:
        recorded = json.loads(mp.read_text())
    except ValueError as e:
        raise LockError(f"unreadable {MANIFEST}: {e}") from e
    recorded = recorded.get("files", recorded)
    now = compute(root)
    bad = sorted(k for k in set(recorded) | set(now) if recorded.get(k) != now.get(k))
    if bad:
        raise LockError("working tree differs from manifest: " + ", ".join(bad))
    try:
        tagged = subprocess.run(["git", "show", f"{TAG}:{MANIFEST}"], cwd=root, check=True,
                                capture_output=True).stdout
    except (subprocess.CalledProcessError, OSError) as e:
        raise LockError(f"cannot read {MANIFEST} at tag {TAG}") from e
    if tagged != mp.read_bytes():
        raise LockError(f"{MANIFEST} differs from the copy at tag {TAG}")
