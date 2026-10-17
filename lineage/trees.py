"""Bare-mirror reader: fetch by SHA into refs/pollen/<sha>, tree identities, manifests."""
from __future__ import annotations

import gzip
import hashlib
import json
import subprocess
from pathlib import Path


def _git(repo, *args, input=None, check=True):
    return subprocess.run(["git", "-C", str(repo), *args], input=input,
                          capture_output=True, check=check)


def mirror_path(repo: str, cache_dir) -> Path:
    key = hashlib.sha256(str(repo).encode()).hexdigest()[:16]
    return Path(cache_dir) / f"{key}.git"


def _have(mirror) -> set[str]:
    out = _git(mirror, "for-each-ref", "--format=%(refname)", "refs/pollen/").stdout.decode()
    return {r.rsplit("/", 1)[1] for r in out.split()}


def _fetch(mirror, repo, chunk: list[str]) -> None:
    """Fetch a chunk; on failure split in halves until bad SHAs are isolated."""
    if not chunk:
        return
    specs = [f"+{s}:refs/pollen/{s}" for s in chunk]
    r = _git(mirror, "fetch", "-q", "--no-tags", str(repo), *specs, check=False)
    if r.returncode == 0 or len(chunk) == 1:
        return
    mid = len(chunk) // 2
    _fetch(mirror, repo, chunk[:mid])
    _fetch(mirror, repo, chunk[mid:])


def ensure_mirror(repo: str, shas, cache_dir, chunk_size: int = 200):
    """Create the mirror if needed and fetch each SHA. Returns (mirror, missing)."""
    mirror = mirror_path(repo, cache_dir)
    if not mirror.exists():
        mirror.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "init", "-q", "--bare", str(mirror)], check=True)
    _git(mirror, "config", "gc.auto", "0")
    shas = sorted(set(shas))
    have = _have(mirror)
    todo = [s for s in shas if s not in have]
    for i in range(0, len(todo), chunk_size):
        _fetch(mirror, repo, todo[i:i + chunk_size])
    have = _have(mirror)
    return mirror, [s for s in shas if s not in have]


def tree_ids_many(repo, shas, paths) -> dict[str, tuple]:
    """Tree identity per commit: the git object id of each editable path (None if absent)."""
    shas = list(dict.fromkeys(shas))
    paths = [p.rstrip("/") for p in paths]
    if not shas:
        return {}
    inp = "".join(f"{s}:{p}\n" for s in shas for p in paths).encode()
    out = _git(repo, "cat-file", "--batch-check", input=inp).stdout.decode().splitlines()
    res, k = {}, 0
    for s in shas:
        ids = []
        for _ in paths:
            parts = out[k].split()
            ids.append(None if parts[-1] == "missing" else parts[0])
            k += 1
        res[s] = tuple(ids)
    return res


def tree_ids(repo, sha: str, paths) -> tuple:
    return tree_ids_many(repo, [sha], paths)[sha]


def read_manifests(mirror, shas, paths) -> dict[str, dict[str, str]]:
    """{sha: {path: blob_sha}} for files under the editable paths (dirs recurse)."""
    paths = [p.rstrip("/") for p in paths]
    res = {}
    for sha in sorted(set(shas)):
        out = _git(mirror, "ls-tree", "-r", "-z", sha, "--", *paths, check=False).stdout
        m = {}
        for rec in out.split(b"\0"):
            if not rec:
                continue
            meta, _, name = rec.partition(b"\t")
            _, typ, blob = meta.decode().split()
            if typ == "blob":
                m[name.decode("utf-8", "surrogateescape")] = blob
        res[sha] = m
    return res


def _gz(path: Path, obj) -> Path:
    data = json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", mtime=0, filename="") as f:
        f.write(data)
    return path


def write_manifests(out_dir, manifests) -> Path:
    return _gz(Path(out_dir) / "manifests.json.gz", manifests)


def write_missing(out_dir, missing) -> Path:
    p = Path(out_dir) / "missing.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(sorted(missing), indent=0) + "\n")
    return p
