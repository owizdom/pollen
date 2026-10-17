"""Track C: lineage (spec 0001 sections 3.3, 8; AT4/AT15 unit level)."""
import gzip

import pytest

from tests.fixtures_lineage import at, lines, make_repo, sub, tree

from lineage import declared, distance, parents, trees


# ---------------------------------------------------------------- declared

def test_declared_tokens_prefixes_in_order():
    note = ("**Base:** jieyilong's 4a8ade4, which is gnuchev's ... (3f1c7ce)\n"
            "more text")
    assert declared.declared_base_tokens(note) == ["4a8ade4", "3f1c7ce"]


def test_declared_tokens_lowercase_base_full_sha_and_uuid():
    sha = "a" * 40
    uid = "123e4567-e89b-12d3-a456-426614174000"
    assert declared.declared_base_tokens(f"base: {sha}") == [sha]
    assert declared.declared_base_tokens(f"Base: {uid}") == [uid]


def test_declared_tokens_none_without_base_line():
    assert declared.declared_base_tokens("Model: GPT-5\nno parent here 4a8ade4") == []
    assert declared.declared_base_tokens("") == []


def test_resolve_by_id_prefix_and_commit_sha():
    subs = [sub("4a8ade41-0000", 1), sub("zz", 2, commit_sha="3f1c7ce9" + "0" * 32)]
    assert declared.resolve("4a8ade4", subs) == "4a8ade41-0000"
    assert declared.resolve("3f1c7ce", subs) == "zz"


def test_resolve_ambiguous_and_unknown_none():
    subs = [sub("abcdef01", 1), sub("abcdef02", 2)]
    assert declared.resolve("abcdef0", subs) is None
    assert declared.resolve("9999999", subs) is None
    assert declared.resolve("abcdef01", subs) == "abcdef01"


# ---------------------------------------------------------------- distance

A = {"f": ["1", "2", "3"], "g": ["x"]}


def test_changed_lines_identical_zero():
    assert distance.changed_lines(A, {k: list(v) for k, v in A.items()}) == 0


def test_changed_lines_one_edit_is_two():
    assert distance.changed_lines({"f": ["1", "2", "3"]}, {"f": ["1", "X", "3"]}) == 2


def test_changed_lines_added_and_deleted_file():
    assert distance.changed_lines({"f": ["1"]}, {"f": ["1"], "n": ["a", "b", "c"]}) == 3
    assert distance.changed_lines({"f": ["1"], "n": ["a", "b"]}, {"f": ["1"]}) == 2


def test_changed_lines_symmetric_and_size():
    b = {"f": ["1", "9"], "h": ["q", "r"]}
    assert distance.changed_lines(A, b) == distance.changed_lines(b, A)
    assert distance.changed_lines(A, b) > 0
    assert distance.size(A) == 4
    assert distance.size({}) == 0


# ----------------------------------------------------------------- parents

def P(child, earlier, attribution=None, tr=None, own=None):
    return parents.parents(child, earlier, attribution or {}, tr or {}, own or [])


BASE = lines("l", 20)


def edit(base, n):
    out = list(base)
    for k in range(n):
        out[k] = f"changed{k}"
    return {"src/main.py": out}


def T(base=BASE):
    return {"src/main.py": list(base)}


def test_declared_single_parent():
    p1, p2 = sub("p1", 1, promoted=True), sub("p2", 2, promoted=True)
    child = sub("c", 10)
    r = P(child, [p1, p2], {"c": ["p1"]}, {"c": T(), "p2": T()})
    assert r.method == "declared"
    assert tuple(r.parent_ids) == ("p1",)
    assert isinstance(r.parent_ids, tuple)


def test_declared_multi_keeps_order():
    p1, p2 = sub("p1", 1, promoted=True), sub("p2", 2, promoted=True)
    child = sub("c", 10)
    r = P(child, [p1, p2], {"c": ["p2", "p1"]}, {})
    assert r.method == "multi"
    assert r.parent_ids == ("p2", "p1")


def test_tree_picks_min_distance():
    near = sub("near", 1, promoted=True)
    far = sub("far", 2, promoted=True)
    child = sub("c", 10)
    tr = {"c": T(), "near": edit(BASE, 1), "far": edit(BASE, 5)}
    r = P(child, [near, far], tr=tr)
    assert r.method == "tree"
    assert r.parent_ids == ("near",)
    assert r.distance == 2


def test_tree_tie_goes_to_most_recent():
    a, b = sub("a", 1, promoted=True), sub("b", 5, promoted=True)
    tr = {"c": T(), "a": edit(BASE, 1), "b": {"src/main.py": ["zz"] + BASE[1:]}}
    r = P(sub("c", 10), [a, b], tr=tr)
    assert r.method == "tree"
    assert r.parent_ids == ("b",)


def test_identical_trees_collapse_to_most_recent():
    old = sub("old", 1, promoted=True)
    new = sub("new", 7, promoted=True)
    tr = {"c": T(), "old": edit(BASE, 1), "new": edit(BASE, 1)}
    r = P(sub("c", 10), [old, new], tr=tr)
    assert r.parent_ids == ("new",)
    assert r.distance == 2


def test_candidates_limited_to_last_50_promoted_plus_own():
    child = sub("c", 1000, solver="alice")
    exact_old = sub("exact_old", 0, solver="bob", promoted=True)  # 51st back
    recent = [sub(f"r{i}", 10 + i, solver="bob", promoted=True) for i in range(50)]
    tr = {"c": T(), "exact_old": T()}
    for s in recent:
        tr[s.id] = edit(BASE, 3)
    r = P(child, [exact_old] + recent, tr=tr)
    assert r.parent_ids != ("exact_old",)
    assert r.parent_ids[0].startswith("r")


def test_unpromoted_other_solver_not_candidate():
    other = sub("other", 1, solver="bob", promoted=False)
    prom = sub("prom", 2, solver="bob", promoted=True)
    tr = {"c": T(), "other": T(), "prom": edit(BASE, 2)}
    r = P(sub("c", 10), [other, prom], tr=tr)
    assert r.parent_ids == ("prom",)


def test_own_history_is_candidate_even_if_unpromoted():
    mine = sub("mine", 1, solver="alice", promoted=False)
    prom = sub("prom", 2, solver="bob", promoted=True)
    tr = {"c": T(), "mine": edit(BASE, 1), "prom": edit(BASE, 4)}
    r = P(sub("c", 10, solver="alice"), [mine, prom], tr=tr, own=[mine])
    assert r.parent_ids == ("mine",)


def test_novel_when_distance_over_half_child_size():
    p = sub("p", 1, promoted=True)
    child_tree = {"src/main.py": lines("n", 10)}
    r = P(sub("c", 10), [p], tr={"c": child_tree, "p": {"src/main.py": lines("o", 10)}})
    assert r.method == "novel"
    assert r.parent_ids == ()


def test_not_novel_at_exactly_half():
    p = sub("p", 1, promoted=True)
    child_tree = {"src/main.py": ["a", "b", "c", "d"]}
    # one line replaced: distance 2, half of size 4 is 2, not exceeded
    par = {"src/main.py": ["a", "b", "c", "X"]}
    r = P(sub("c", 10), [p], tr={"c": child_tree, "p": par})
    assert r.method == "tree"
    assert r.parent_ids == ("p",)


def test_child_without_tree_is_none():
    p = sub("p", 1, promoted=True)
    r = P(sub("c", 10), [p], tr={"p": T()})
    assert r.method == "none"
    assert r.parent_ids == ()
    assert r.distance is None


def test_candidates_without_trees_skipped():
    a = sub("a", 1, promoted=True)
    b = sub("b", 2, promoted=True)
    r = P(sub("c", 10), [a, b], tr={"c": T(), "a": edit(BASE, 2)})
    assert r.parent_ids == ("a",)


def test_later_rows_never_chosen():
    early = sub("early", 1, promoted=True)
    later = sub("later", 20, promoted=True)
    tr = {"c": T(), "early": edit(BASE, 4), "later": T()}
    r = P(sub("c", 10), [early, later], tr=tr)
    assert r.parent_ids == ("early",)


def test_parentlink_fields():
    p = sub("p", 1, promoted=True)
    r = P(sub("c", 10), [p], tr={"c": T(), "p": edit(BASE, 1)})
    assert isinstance(r.parent_ids, tuple)
    assert r.method in ("declared", "multi", "tree", "novel", "none")
    assert isinstance(r.distance, int)


# ------------------------------------------------------------------- trees

def test_read_trees_editable_only_and_missing(tmp_path):
    repo, sha1, sha2 = make_repo(tmp_path)
    bogus = "f" * 40
    got, missing = trees.read_trees(str(repo), ["src/main.py"],
                                    {sha1, sha2, bogus}, tmp_path / "cache")
    assert got[sha1] == {"src/main.py": ["a", "b", "c"]}
    assert got[sha2] == {"src/main.py": ["a", "B", "c", "d"]}
    assert bogus not in got
    assert set(missing) == {bogus}


def test_write_manifests_deterministic_gzip(tmp_path):
    manifests = {"abc": {"src/main.py": "1" * 40}, "def": {"src/main.py": "2" * 40}}
    o1, o2 = tmp_path / "o1", tmp_path / "o2"
    trees.write_manifests(o1, manifests)
    import time
    time.sleep(1.1)
    trees.write_manifests(o2, manifests)
    f1, f2 = o1 / "manifests.json.gz", o2 / "manifests.json.gz"
    assert f1.read_bytes() == f2.read_bytes()
    import json
    assert json.loads(gzip.decompress(f1.read_bytes())) == manifests
