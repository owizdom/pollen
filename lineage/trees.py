"""Bare-mirror tree reader for editable paths, fetched by SHA."""
from __future__ import annotations

import gzip
import hashlib
import json
import subprocess
from pathlib import Path


def _git(mirror, *args, input=None, check=True):
    return subprocess.run(["git", "-C", str(mirror), *args], input=input,
                          capture_output=True, check=check)


def mirror_path(repo: str, cache_dir) -> Path:
    key = hashlib.sha256(str(repo).encode()).hexdigest()[:16]
    return Path(cache_dir) / f"{key}.git"


def _present(mirror, shas) -> set[str]:
    if not shas:
        return set()
    inp = "".join(f"{s}^{{commit}}\n" for s in shas).encode()
    out = _git(mirror, "cat-file", "--batch-check", input=inp).stdout.decode().splitlines()
    return {s for s, line in zip(shas, out) if not line.endswith("missing")}


def ensure_mirror(repo: str, shas, cache_dir) -> tuple[Path, list[str]]:
    """Create the mirror if needed and fetch each SHA. Returns (mirror, unfetchable)."""
    mirror = mirror_path(repo, cache_dir)
    if not mirror.exists():
        mirror.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "init", "-q", "--bare", str(mirror)], check=True)
    _git(mirror, "remote", "remove", "origin", check=False)
    _git(mirror, "remote", "add", "origin", str(repo))
    shas = sorted(set(shas))
    todo = [s for s in shas if s not in _present(mirror, shas)]
    if todo:
        r = _git(mirror, "fetch", "-q", "--no-tags", "origin", *todo, check=False)
        if r.returncode != 0:
            for s in todo:
                _git(mirror, "fetch", "-q", "--no-tags", "origin", s, check=False)
    have = _present(mirror, shas)
    return mirror, [s for s in shas if s not in have]


def _ls_tree(mirror, sha, paths) -> dict[str, str]:
    out = _git(mirror, "ls-tree", "-r", "-z", sha, "--", *paths, check=False).stdout
    res = {}
    for rec in out.split(b"\0"):
        if not rec:
            continue
        meta, _, name = rec.partition(b"\t")
        mode, typ, blob = meta.decode().split()
        if typ == "blob":
            res[name.decode("utf-8", "surrogateescape")] = blob
    return res


def read_manifests(repo: str, editable_paths, shas, cache_dir):
    """Return ({sha: {path: blob_sha}}, missing)."""
    mirror, missing = ensure_mirror(repo, shas, cache_dir)
    paths = [p.rstrip("/") for p in editable_paths]
    bad = set(missing)
    manifests = {s: _ls_tree(mirror, s, paths) for s in sorted(set(shas)) if s not in bad}
    return manifests, missing


def read_blobs(mirror, blob_shas) -> dict[str, list[str]]:
    """Read many blobs through one `git cat-file --batch` process."""
    blob_shas = sorted(set(blob_shas))
    if not blob_shas:
        return {}
    data = _git(mirror, "cat-file", "--batch",
                input="".join(b + "\n" for b in blob_shas).encode()).stdout
    out, pos = {}, 0
    for b in blob_shas:
        nl = data.index(b"\n", pos)
        header = data[pos:nl].split()
        if len(header) == 2:  # "<sha> missing"
            pos = nl + 1
            out[b] = []
            continue
        n = int(header[2])
        body = data[nl + 1:nl + 1 + n]
        out[b] = body.decode("utf-8", "replace").splitlines()
        pos = nl + 1 + n + 1
    return out


def read_trees(repo: str, editable_paths, shas, cache_dir):
    """Return ({sha: {path: lines}}, missing) for the editable paths only."""
    manifests, missing = read_manifests(repo, editable_paths, shas, cache_dir)
    mirror = mirror_path(repo, cache_dir)
    blobs = read_blobs(mirror, (b for m in manifests.values() for b in m.values()))
    trees = {s: {p: blobs[b] for p, b in m.items()} for s, m in manifests.items()}
    return trees, missing


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
