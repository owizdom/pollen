"""Pre-registration manifest and lock check (spec 0001 section 5.8)."""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = "docs/prereg-manifest.json"
TAG = "prereg-v1"
REQUIRED = ["docs/prereg.md", "families/table.yaml", "outcomes/denominator.yaml",
            "snapshot/raw/SHA256SUMS", "lineage/frozen/SHA256SUMS"]
CODE_DIRS = ("snapshot", "families", "lineage", "outcomes", "analysis")
SUMMED = ("lineage/frozen", "snapshot/raw")


class LockError(Exception):
    pass


def _is_data(rel: Path) -> bool:
    s = rel.as_posix()
    return (any(s.startswith(d + "/") for d in SUMMED) or s.startswith("lineage/cache/")
            or s.startswith("outcomes/sealed/") or "__pycache__" in rel.parts)


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def compute(root=ROOT) -> dict:
    """Hashes of the required files and every code file; raises if a required file is absent."""
    root = Path(root)
    missing = [r for r in REQUIRED if not (root / r).is_file()]
    if missing:
        raise LockError("required files missing: " + ", ".join(missing))
    out = set(REQUIRED)
    for top in CODE_DIRS:
        for p in (root / top).rglob("*.py") if (root / top).is_dir() else []:
            rel = p.relative_to(root)
            if p.is_file() and not _is_data(rel):
                out.add(rel.as_posix())
    return {rel: _sha(root / rel) for rel in sorted(out)}


def write_manifest(root=ROOT) -> Path:
    root = Path(root)
    data = compute(root)
    out = root / MANIFEST
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    return out


def verify_sums(base: Path) -> None:
    """Every file under base matches base/SHA256SUMS and none is unlisted."""
    sums = base / "SHA256SUMS"
    if not sums.is_file():
        raise LockError(f"missing {sums}")
    listed = {}
    for line in sums.read_text().splitlines():
        if line.strip():
            digest, _, rel = line.partition("  ")
            listed[rel.strip()] = digest.strip()
    present = {p.relative_to(base).as_posix() for p in base.rglob("*")
               if p.is_file() and p.name != "SHA256SUMS" and "__pycache__" not in p.parts}
    bad = sorted((present ^ set(listed)) | {r for r in present & set(listed)
                                           if _sha(base / r) != listed[r]})
    if bad:
        raise LockError(f"{base}: differs from SHA256SUMS: " + ", ".join(bad))


def check(root=ROOT) -> None:
    root = Path(root)
    mp = root / MANIFEST
    if not mp.is_file():
        raise LockError(f"missing {MANIFEST}")
    try:
        recorded = json.loads(mp.read_text())
    except ValueError as e:
        raise LockError(f"unreadable {MANIFEST}: {e}") from e
    if not isinstance(recorded, dict):
        raise LockError(f"malformed {MANIFEST}")
    recorded = recorded.get("files", recorded)
    absent = [r for r in REQUIRED if r not in recorded]
    if absent:
        raise LockError("manifest lacks required keys: " + ", ".join(absent))
    now = compute(root)
    bad = sorted(k for k in set(recorded) | set(now) if recorded.get(k) != now.get(k))
    if bad:
        raise LockError("working tree differs from manifest: " + ", ".join(bad))
    for d in SUMMED:
        verify_sums(root / d)
    try:
        tagged = subprocess.run(["git", "show", f"{TAG}:{MANIFEST}"], cwd=root, check=True,
                                capture_output=True).stdout
    except (subprocess.CalledProcessError, OSError) as e:
        raise LockError(f"cannot read {MANIFEST} at tag {TAG}") from e
    if tagged != mp.read_bytes():
        raise LockError(f"{MANIFEST} differs from the copy at tag {TAG}")
