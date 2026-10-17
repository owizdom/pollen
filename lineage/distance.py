"""Distances between editable-path trees, measured by `git diff --numstat`."""
from __future__ import annotations

import gzip
import json
import subprocess
from pathlib import Path

EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"


def numstat(mirror, sha_a: str, sha_b: str, paths) -> tuple[int, int, int]:
    """(added, removed, binary_changed) going from a to b over the editable paths."""
    out = subprocess.run(
        ["git", "-C", str(mirror), "diff", "--numstat", "--minimal", "--no-renames",
         "--no-ext-diff", "--no-textconv", sha_a, sha_b, "--", *paths],
        capture_output=True, check=True).stdout.decode("utf-8", "replace")
    added = removed = binary = 0
    for line in out.splitlines():
        a, r, _ = line.split("\t", 2)
        if a == "-" or r == "-":
            binary += 1
        else:
            added += int(a)
            removed += int(r)
    return added, removed, binary


def changed_lines(mirror, sha_a, sha_b, paths) -> int:
    a, r, b = numstat(mirror, sha_a, sha_b, paths)
    return a + r + b


def child_side(mirror, parent_sha, child_sha, paths) -> int:
    """Text lines present in the child but not the parent."""
    return numstat(mirror, parent_sha, child_sha, paths)[0]


def text_size(mirror, sha, paths) -> int:
    """Text lines in the editable paths; binary files do not count."""
    return numstat(mirror, EMPTY_TREE, sha, paths)[0]


def ident(tree_ids) -> str:
    """Stable string for a tree identity tuple."""
    return ",".join(o or "-" for o in tree_ids)


class Memo:
    """Persistent memo keyed by tree identity: pairs (parent>child) and sizes."""

    def __init__(self, dist=None, size=None):
        self.dist: dict[str, list[int]] = dist or {}
        self.size: dict[str, int] = size or {}

    @classmethod
    def load(cls, path) -> "Memo":
        p = Path(path)
        if not p.exists():
            return cls()
        d = json.loads(gzip.decompress(p.read_bytes()))
        return cls(d.get("dist"), d.get("size"))

    def pair(self, mirror, id_a, sha_a, id_b, sha_b, paths):
        if id_a == id_b:
            return (0, 0, 0)
        k = f"{id_a}>{id_b}"
        v = self.dist.get(k)
        if v is None:
            v = self.dist[k] = list(numstat(mirror, sha_a, sha_b, paths))
        return tuple(v)

    def text_size(self, mirror, id_c, sha, paths) -> int:
        v = self.size.get(id_c)
        if v is None:
            v = self.size[id_c] = text_size(mirror, sha, paths)
        return v
