"""Parent inference: declared attribution, then tree distance (spec 3.3)."""
from __future__ import annotations

import gzip
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from lineage.distance import changed_lines, size, tree_hash

RECENT_PROMOTED = 50


@dataclass(frozen=True)
class ParentLink:
    parent_ids: tuple[str, ...]
    method: str  # declared | multi | tree | novel | none
    distance: int | None


def parents(sub, earlier, attribution, trees, own_history) -> ParentLink:
    declared = attribution.get(sub.id) or []
    if len(declared) == 1:
        return ParentLink(tuple(declared), "declared", None)
    if len(declared) >= 2:
        return ParentLink(tuple(declared), "multi", None)

    child = trees.get(sub.id)
    if child is None:
        return ParentLink((), "none", None)

    before = [s for s in earlier if s.created_at < sub.created_at and s.id != sub.id]
    before.sort(key=lambda s: s.created_at)
    promoted = [s for s in before if s.promoted][-RECENT_PROMOTED:]
    cands = {s.id: s for s in promoted}
    for s in own_history:
        if s.created_at < sub.created_at and s.id != sub.id:
            cands[s.id] = s

    cache: dict[str, int] = {}
    best_id, best_d = None, None
    for s in sorted(cands.values(), key=lambda s: s.created_at, reverse=True):
        t = trees.get(s.id)
        if t is None:
            continue
        h = tree_hash(t)
        d = cache.get(h)
        if d is None:
            d = cache[h] = changed_lines(t, child)
        if best_d is None or d < best_d:  # strict: ties keep the most recent
            best_id, best_d = s.id, d
    if best_id is None:
        return ParentLink((), "none", None)
    if best_d > size(child) / 2:
        return ParentLink((), "novel", best_d)
    return ParentLink((best_id,), "tree", best_d)


def _gz(path: Path, obj) -> None:
    data = json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", mtime=0, filename="") as f:
        f.write(data)


def write_parents(out_dir, links: dict[str, ParentLink]) -> Path:
    """Write deterministic parents.json.gz: {sub_id: [parent_ids, method, distance]}."""
    path = Path(out_dir) / "parents.json.gz"
    _gz(path, {k: [list(v.parent_ids), v.method, v.distance] for k, v in links.items()})
    return path


def write_sha256sums(frozen_dir) -> Path:
    """Write lineage/frozen/SHA256SUMS over every file below frozen_dir."""
    root = Path(frozen_dir)
    lines = []
    for p in sorted(root.rglob("*")):
        if p.is_file() and p.name != "SHA256SUMS":
            lines.append(f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.relative_to(root).as_posix()}")
    out = root / "SHA256SUMS"
    out.write_text("\n".join(lines) + ("\n" if lines else ""))
    return out
