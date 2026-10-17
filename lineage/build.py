"""Build lineage/frozen/<slug>/ for one benchmark (resumable from the distance memo)."""
from __future__ import annotations

import gzip
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from lineage import distance, parents as parents_mod, trees as trees_mod

HERE = Path(__file__).resolve().parent
WORKERS = 8
FLUSH_EVERY = 200


def tree_sha(s) -> str | None:
    if s.promoted:
        return s.promoted_ref or s.submission_sha or s.commit_sha
    return s.submission_sha or s.commit_sha


def write_sha256sums(frozen_root) -> Path:
    root = Path(frozen_root)
    lines = [f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.relative_to(root).as_posix()}"
             for p in sorted(root.rglob("*")) if p.is_file() and p.name != "SHA256SUMS"]
    out = root / "SHA256SUMS"
    out.write_text("\n".join(lines) + ("\n" if lines else ""))
    return out


def _link(l):
    return [list(l.parent_ids), l.method, l.distance, l.child_side]


def _flush(out_dir, memo) -> None:
    trees_mod._gz(out_dir / "distances.json.gz", {"dist": memo.dist, "size": memo.size})


def run(benchmark: str, snapshot=None, frozen_root=None, cache_dir=None) -> None:
    if snapshot is None:
        from snapshot import load as snapshot
    frozen_root = Path(frozen_root or HERE / "frozen")
    cache_dir = Path(cache_dir or HERE / "cache")
    all_subs = sorted(snapshot.load(benchmark), key=lambda s: (s.created_at, s.id))
    from outcomes import denominator
    subs = denominator.analysis_rows(all_subs, benchmark)
    subs.sort(key=lambda s: (s.created_at, s.id))
    meta = snapshot.benchmark_meta(benchmark)
    attr = snapshot.attribution(benchmark)
    paths = list(meta.editable_paths)
    out_dir = frozen_root / meta.slug

    want = {s.id: tree_sha(s) for s in subs if tree_sha(s)}
    mirror, missing = trees_mod.ensure_mirror(meta.source_url, set(want.values()),
                                              cache_dir)
    bad = set(missing)
    frozen = out_dir / "manifests.json.gz"
    if frozen.exists() and bad:
        held = set(json.loads(gzip.decompress(frozen.read_bytes())))
        lost = sorted(bad & held)
        if lost:
            raise RuntimeError(
                f"{benchmark}: refusing to rebuild; {len(lost)} commits in the frozen "
                f"manifests are not available in the mirror (first: {lost[0]}). "
                f"Restore the mirror before rebuilding.")
    trees = {i: sha for i, sha in want.items() if sha not in bad}
    ids = {}
    tid = trees_mod.tree_ids_many(mirror, set(trees.values()), paths)
    for i, sha in trees.items():
        ids[i] = tid[sha]

    memo = distance.Memo.load(out_dir / "distances.json.gz")
    results, by_solver = {}, {}
    with ThreadPoolExecutor(WORKERS) as pool:
        for k, child in enumerate(subs):
            earlier = subs[:k]
            own = by_solver.setdefault(child.solver, [])
            if child.id in trees:
                cid, csha = distance.ident(ids[child.id]), trees[child.id]
                jobs = {}
                for c in parents_mod.candidates(child, earlier, trees, own, ids):
                    key = (distance.ident(ids[c.id]), cid)
                    if key[0] != cid and f"{key[0]}>{key[1]}" not in memo.dist:
                        jobs[key] = trees[c.id]
                futs = {key: pool.submit(distance.numstat, mirror, sha, csha, paths)
                        for key, sha in jobs.items()}
                if cid not in memo.size:
                    futs_size = pool.submit(distance.text_size, mirror, csha, paths)
                    memo.size[cid] = futs_size.result()
                for (a, b), f in futs.items():
                    memo.dist[f"{a}>{b}"] = list(f.result())
            results[child.id] = parents_mod.parents(
                child, earlier, attr, trees, own, mirror, paths, ids=ids, memo=memo, all_rows=all_subs)
            own.append(child)
            if (k + 1) % FLUSH_EVERY == 0:
                _flush(out_dir, memo)

    manifests = trees_mod.read_manifests(mirror, set(trees.values()), paths)
    trees_mod.write_manifests(out_dir, manifests)
    trees_mod.write_missing(out_dir, missing)
    _flush(out_dir, memo)
    trees_mod._gz(out_dir / "parents.json.gz", {
        i: {"primary": _link(r.primary), "tree": _link(r.tree),
            "dropped": list(r.dropped_declared)} for i, r in results.items()})
    write_sha256sums(frozen_root)
