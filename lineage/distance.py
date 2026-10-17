"""Line-diff distance between editable-path trees."""
from __future__ import annotations

from difflib import SequenceMatcher


def _file_distance(x: list[str], y: list[str]) -> int:
    if x == y:
        return 0
    if not x:
        return len(y)
    if not y:
        return len(x)
    # strip common prefix/suffix cheaply before diffing
    lo = 0
    n = min(len(x), len(y))
    while lo < n and x[lo] == y[lo]:
        lo += 1
    hi = 0
    while hi < n - lo and x[-1 - hi] == y[-1 - hi]:
        hi += 1
    x2, y2 = x[lo:len(x) - hi], y[lo:len(y) - hi]
    if not x2:
        return len(y2)
    if not y2:
        return len(x2)
    sm = SequenceMatcher(None, x2, y2, autojunk=False)
    return sum((i2 - i1) + (j2 - j1)
               for tag, i1, i2, j1, j2 in sm.get_opcodes() if tag != "equal")


def changed_lines(a: dict[str, list[str]], b: dict[str, list[str]]) -> int:
    """Added plus removed lines over the union of paths (missing path = empty)."""
    if a is b:
        return 0
    return sum(_file_distance(a.get(p, []), b.get(p, [])) for p in set(a) | set(b))


def size(tree: dict[str, list[str]]) -> int:
    return sum(len(v) for v in tree.values())


def tree_hash(tree: dict[str, list[str]]) -> str:
    import hashlib
    h = hashlib.sha256()
    for p in sorted(tree):
        h.update(p.encode()); h.update(b"\0")
        for ln in tree[p]:
            h.update(ln.encode()); h.update(b"\n")
        h.update(b"\1")
    return h.hexdigest()
