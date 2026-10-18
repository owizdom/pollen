"""Parent inference: declared attribution, then a text-declared base, plus an always-computed
tree link over promoted rows (spec 3.3, v2.9)."""
from __future__ import annotations

from dataclasses import dataclass

from lineage import declared as declared_mod, trees as trees_mod
from lineage.distance import Memo, ident

WINDOW = 50


@dataclass(frozen=True)
class ParentLink:
    parent_ids: tuple[str, ...]
    method: str  # declared | multi | text | tree | novel | none
    distance: int | None = None
    child_side: int | None = None


@dataclass(frozen=True)
class ParentResult:
    primary: ParentLink
    tree: ParentLink
    dropped_declared: tuple[str, ...] = ()


def _key(s):
    return (s.created_at, s.id)


def candidates(child, earlier, trees, own_history, ids) -> list:
    """Window: promoted rows with trees, collapsed by tree identity (newest kept), then last 50.

    own_history is accepted for compatibility and ignored (v2.9): a solver's own unpromoted
    attempts are usually siblings built on the same base, not the base itself."""
    def pool(rows):
        rows = sorted((s for s in rows if s.id in trees and s.id != child.id
                       and s.created_at < child.created_at), key=_key)
        kept = {}
        for s in rows:
            kept[ids[s.id]] = s
        return sorted(kept.values(), key=_key)[-WINDOW:]

    promoted = [s for s in earlier
                if s.promoted and (s.finished_at or s.created_at) < child.created_at]
    return pool(promoted)


def _ids_for(rows, trees, mirror, paths, ids):
    need = [s for s in rows if s.id in trees and s.id not in ids]
    if need:
        got = trees_mod.tree_ids_many(mirror, [trees[s.id] for s in need], paths)
        for s in need:
            ids[s.id] = got[trees[s.id]]
    return ids


def tree_link(child, earlier, trees, own_history, mirror, paths, ids, memo) -> ParentLink:
    if child.id not in trees:
        return ParentLink((), "none")
    rows = list(earlier) + list(own_history) + [child]
    _ids_for(rows, trees, mirror, paths, ids)
    cands = candidates(child, earlier, trees, own_history, ids)
    if not cands:
        return ParentLink((), "none")
    cid, csha = ident(ids[child.id]), trees[child.id]
    best = None
    for s in cands:  # ascending (created_at, id); later row wins ties
        a, r, b = memo.pair(mirror, ident(ids[s.id]), trees[s.id], cid, csha, paths)
        d = a + r + b
        if best is None or d <= best[0]:
            best = (d, a, s)
    d, side, s = best
    if side > memo.text_size(mirror, cid, csha, paths) / 2:
        return ParentLink((), "novel", d, side)
    return ParentLink((s.id,), "tree", d, side)


def parents(child, earlier, attribution, trees, own_history, mirror, paths,
            ids=None, memo=None, all_rows=None) -> ParentResult:
    """trees: row id -> commit sha. ids: optional cache of row id -> tree identity."""
    ids = {} if ids is None else ids
    memo = Memo() if memo is None else memo
    earlier = [s for s in earlier if s.id != child.id and s.created_at < child.created_at]
    link = tree_link(child, earlier, trees, [s for s in own_history if s.id != child.id],
                     mirror, paths, ids, memo)
    pool = earlier if all_rows is None else all_rows
    known = {s.id for s in pool if s.id != child.id and s.created_at < child.created_at}
    kept, dropped = [], []
    for d in attribution.get(child.id) or []:
        if d in kept or d in dropped:
            continue
        (kept if d in known else dropped).append(d)
    if not kept:
        tok = declared_mod.declared_base(child.note)
        pid = declared_mod.resolve(tok, [s for s in pool if s.id in known]) if tok else None
        if pid:
            return ParentResult(ParentLink((pid,), "text"), link, tuple(dropped))
        return ParentResult(link, link, tuple(dropped))
    method = "declared" if len(kept) == 1 else "multi"
    return ParentResult(ParentLink(tuple(kept), method), link, tuple(dropped))
