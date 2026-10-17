"""Track C: lineage (spec 0001 v2.2 sections 3.3, 8; AT4/AT15 unit level)."""
import datetime as dt
import gzip
import hashlib
import json
import subprocess

import pytest

from tests.fixtures_lineage import PATHS, Repo, World, at, git, lines, sub

from lineage import build, declared, distance, parents, trees, window
from snapshot.model import Benchmark


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


def test_resolve_promoted_ref_and_submission_sha():
    ref = "9b2d4e6" + "1" * 33
    subs = [sub("p1", 1, promoted=True, promoted_ref=ref),
            sub("p2", 2, submission_sha="c0ffee1" + "2" * 33)]
    assert declared.resolve("9b2d4e6", subs) == "p1"
    assert declared.resolve(ref, subs) == "p1"
    assert declared.resolve("c0ffee1", subs) == "p2"
    assert declared.resolve("c0ffee1" + "2" * 33, subs) == "p2"


def test_resolve_ambiguous_and_unknown_none():
    subs = [sub("abcdef01", 1), sub("abcdef02", 2)]
    assert declared.resolve("abcdef0", subs) is None
    assert declared.resolve("9999999", subs) is None
    assert declared.resolve("abcdef01", subs) == "abcdef01"


# ---------------------------------------------------------------- distance

@pytest.fixture
def repo(tmp_path):
    return Repo(tmp_path / "r")


def cl(repo, a, b):
    return distance.changed_lines(repo.path, a, b, PATHS)


def test_one_line_change_is_two_and_symmetric(repo):
    a = repo.commit({"src/main.py": ["1", "2", "3"]})
    b = repo.commit({"src/main.py": ["1", "X", "3"]})
    assert cl(repo, a, b) == 2
    assert cl(repo, b, a) == 2
    assert distance.numstat(repo.path, a, b, PATHS) == (1, 1, 0)


def test_identical_is_zero(repo):
    a = repo.commit({"src/main.py": ["1", "2"]})
    b = repo.commit({"src/main.py": ["1", "2"]})
    assert cl(repo, a, b) == 0


def test_minimal_diff_not_greedy(repo):
    a = repo.commit({"src/main.py": ["b", "a", "b"]})
    b = repo.commit({"src/main.py": ["a", "c", "b", "c"]})
    assert cl(repo, a, b) == 3
    assert cl(repo, b, a) == 3


def test_added_and_deleted_file_count_all_lines(repo):
    paths = ["src/main.py", "src/extra.py"]
    a = repo.commit({"src/main.py": ["1"]})
    b = repo.commit({"src/main.py": ["1"], "src/extra.py": ["a", "b", "c"]})
    assert distance.changed_lines(repo.path, a, b, paths) == 3
    assert distance.changed_lines(repo.path, b, a, paths) == 3


def test_binary_file_counts_one_whatever_its_size(repo):
    a = repo.commit({"src/main.py": b"\x00" + b"a" * 10})
    b = repo.commit({"src/main.py": b"\x00" + b"b" * 50000})
    assert distance.numstat(repo.path, a, b, PATHS) == (0, 0, 1)
    assert distance.numstat(repo.path, b, a, PATHS) == (0, 0, 1)
    assert cl(repo, a, b) == 1
    assert cl(repo, b, a) == 1


def test_non_editable_paths_ignored(repo):
    a = repo.commit({"src/main.py": ["1"], "README.md": ["x"]})
    b = repo.commit({"src/main.py": ["1"], "README.md": ["y", "z"]})
    assert cl(repo, a, b) == 0


def test_child_side_counts_only_added_lines(repo):
    parent = repo.commit({"src/main.py": lines("l", 10)})
    child = repo.commit({"src/main.py": lines("l", 10)[:6] + ["n1", "n2"]})
    # direction parent -> child: 2 added, 4 removed
    assert distance.child_side(repo.path, parent, child, PATHS) == 2
    assert distance.child_side(repo.path, child, parent, PATHS) == 4


def test_text_size_excludes_binary_files(repo):
    paths = ["src/main.py", "src/blob.bin"]
    c = repo.commit({"src/main.py": ["a", "b", "c"], "src/blob.bin": b"\x00\x01" * 100})
    assert distance.text_size(repo.path, c, paths) == 3
    assert distance.text_size(repo.path, c, ["src/blob.bin"]) == 0


# ------------------------------------------------------------------- trees

def make_remote(tmp_path, n=6):
    remote = Repo(tmp_path / "remote")
    shas = [remote.commit({"src/main.py": lines("v", i + 1), "README.md": [f"r{i}"]})
            for i in range(n)]
    return remote, shas


def test_chunked_fetch_isolates_bad_shas(tmp_path):
    remote, shas = make_remote(tmp_path)
    bad = ["f" * 40, "e" * 40]
    want = shas[:3] + [bad[0]] + shas[3:] + [bad[1]]
    mirror, missing = trees.ensure_mirror(str(remote.path), want, tmp_path / "cache",
                                          chunk_size=3)
    assert set(missing) == set(bad)
    for s in shas:
        out = git(mirror, "rev-parse", "--verify", f"refs/pollen/{s}^{{commit}}")
        assert out == s
    for s in bad:
        r = subprocess.run(["git", "-C", str(mirror), "rev-parse", "--verify", "-q",
                            f"refs/pollen/{s}"], capture_output=True)
        assert r.returncode != 0


def test_mirror_has_gc_auto_off(tmp_path):
    remote, shas = make_remote(tmp_path, 2)
    mirror, missing = trees.ensure_mirror(str(remote.path), shas, tmp_path / "cache",
                                          chunk_size=2)
    assert not missing
    assert git(mirror, "config", "--get", "gc.auto") == "0"


def test_tree_ids_identity_over_editable_paths(tmp_path):
    r = Repo(tmp_path / "r")
    a = r.commit({"src/main.py": ["a", "b"], "README.md": ["one"]})
    b = r.commit({"src/main.py": ["a", "b"], "README.md": ["two"], "docs/x": ["y"]})
    c = r.commit({"src/main.py": ["a", "B"], "README.md": ["two"]})
    ta, tb, tc = (trees.tree_ids(r.path, s, PATHS) for s in (a, b, c))
    assert isinstance(ta, tuple) and len(ta) == 1
    assert ta == tb
    assert ta != tc
    both = trees.tree_ids(r.path, a, ["src/main.py", "nope.py"])
    assert len(both) == 2 and both[0] == ta[0] and both[1] is None


def test_write_manifests_deterministic_gzip(tmp_path):
    manifests = {"abc": {"src/main.py": "1" * 40}, "def": {"src/main.py": "2" * 40}}
    o1, o2 = tmp_path / "o1", tmp_path / "o2"
    trees.write_manifests(o1, manifests)
    import time
    time.sleep(1.1)
    trees.write_manifests(o2, manifests)
    f1, f2 = o1 / "manifests.json.gz", o2 / "manifests.json.gz"
    assert f1.read_bytes() == f2.read_bytes()
    assert json.loads(gzip.decompress(f1.read_bytes())) == manifests


# ----------------------------------------------------------------- parents

BASE = lines("l", 10)


def variant(k, tag="c"):
    out = list(BASE)
    for i in range(k):
        out[i] = f"{tag}{i}"
    return out


def test_tree_link_computed_even_with_attribution(tmp_path):
    w = World(tmp_path)
    w.add("decl", 1, lines("zz", 10), promoted=True)
    w.add("near", 2, variant(1), promoted=True)
    child = w.add("c", 10, BASE)
    r = w.parents(child, attribution={"c": ["decl"]})
    assert r.primary.method == "declared"
    assert r.primary.parent_ids == ("decl",)
    assert r.tree.method == "tree"
    assert r.tree.parent_ids == ("near",)
    assert r.tree.distance == 2
    assert r.dropped_declared == ()


def test_declared_multi_keeps_order_and_dedups(tmp_path):
    w = World(tmp_path)
    w.add("p", 1, variant(1), promoted=True)
    w.add("q", 2, variant(2), promoted=True)
    child = w.add("c", 10, BASE)
    r = w.parents(child, attribution={"c": ["q", "p"]})
    assert (r.primary.method, r.primary.parent_ids) == ("multi", ("q", "p"))
    r = w.parents(child, attribution={"c": ["p", "p"]})
    assert (r.primary.method, r.primary.parent_ids) == ("declared", ("p",))


def test_unknown_and_future_declared_ids_dropped(tmp_path):
    w = World(tmp_path)
    w.add("p", 1, variant(1), promoted=True)
    w.add("fut", 50, variant(2), promoted=True)
    child = w.add("c", 10, BASE)
    r = w.parents(child, attribution={"c": ["p", "ghost", "fut"]})
    assert r.primary.method == "declared"
    assert r.primary.parent_ids == ("p",)
    assert r.dropped_declared == ("ghost", "fut")


def test_no_declaration_primary_is_tree_link(tmp_path):
    w = World(tmp_path)
    w.add("p", 1, variant(1), promoted=True)
    child = w.add("c", 10, BASE)
    r = w.parents(child)
    assert r.primary == r.tree
    assert isinstance(r.tree.parent_ids, tuple)
    assert r.tree.method == "tree"
    assert r.tree.distance == 2
    assert r.tree.child_side == 1


def test_tree_picks_min_distance(tmp_path):
    w = World(tmp_path)
    w.add("far", 1, variant(5), promoted=True)
    w.add("near", 2, variant(1), promoted=True)
    w.add("mid", 3, variant(3), promoted=True)
    r = w.parents(w.add("c", 10, BASE))
    assert r.tree.parent_ids == ("near",)


def test_tie_goes_to_most_recent_created_at(tmp_path):
    w = World(tmp_path)
    w.add("a", 1, variant(1, "x"), promoted=True)
    w.add("b", 5, variant(1, "y"), promoted=True)
    r = w.parents(w.add("c", 10, BASE))
    assert r.tree.parent_ids == ("b",)


def test_tie_on_created_at_is_deterministic_by_id(tmp_path):
    w = World(tmp_path)
    s1 = w.add("a", 5, variant(1, "x"), promoted=True)
    s2 = w.add("b", 5, variant(1, "y"), promoted=True)
    child = w.add("c", 10, BASE)
    r1 = w.parents(child, earlier=[s1, s2])
    r2 = w.parents(child, earlier=[s2, s1])
    assert r1.tree.parent_ids == r2.tree.parent_ids
    assert len(r1.tree.parent_ids) == 1


def test_identical_trees_collapse_to_most_recent(tmp_path):
    w = World(tmp_path)
    w.add("old", 1, variant(1), promoted=True)
    w.add("new", 7, variant(1), promoted=True)
    r = w.parents(w.add("c", 10, BASE))
    assert r.tree.parent_ids == ("new",)
    assert r.tree.distance == 2


def test_window_filters_to_rows_with_trees_before_slicing(tmp_path):
    w = World(tmp_path)
    w.add("exact", 0, BASE, promoted=True)
    for i in range(1, 50):
        w.add(f"p{i}", i, lines(f"u{i}_", 10), promoted=True)
    for i in range(5):  # newest promoted rows have no tree
        w.add(f"nt{i}", 60 + i, None, promoted=True)
    r = w.parents(w.add("c", 100, BASE))
    assert r.tree.parent_ids == ("exact",)
    assert r.tree.distance == 0


def test_collapse_by_tree_identity_happens_before_slicing(tmp_path):
    w = World(tmp_path)
    w.add("exact", 0, BASE, promoted=True)
    for i in range(1, 5):
        w.add(f"o{i}", i, lines(f"o{i}_", 10), promoted=True)
    for i in range(55):  # 55 newer rows sharing one tree
        w.add(f"x{i}", 10 + i, lines("X", 10), promoted=True)
    r = w.parents(w.add("c", 100, BASE))
    assert r.tree.parent_ids == ("exact",)


def test_only_last_50_promoted_are_candidates(tmp_path):
    w = World(tmp_path)
    w.add("exact_old", 0, BASE, promoted=True)
    for i in range(50):
        w.add(f"r{i}", 10 + i, variant(3, f"r{i}_"), promoted=True)
    r = w.parents(w.add("c", 100, BASE))
    assert r.tree.parent_ids != ("exact_old",)
    assert r.tree.parent_ids[0].startswith("r")


def test_promotion_counts_only_if_finished_before_child_created(tmp_path):
    w = World(tmp_path)
    w.add("late", 1, BASE, promoted=True, finished=at(50))  # finished after child
    w.add("ok", 2, variant(2), promoted=True)
    r = w.parents(w.add("c", 10, BASE))
    assert r.tree.parent_ids == ("ok",)


def test_unpromoted_other_solver_not_a_candidate(tmp_path):
    w = World(tmp_path)
    w.add("other", 1, BASE, solver="bob", promoted=False)
    w.add("prom", 2, variant(2), solver="bob", promoted=True)
    r = w.parents(w.add("c", 10, BASE, solver="alice"))
    assert r.tree.parent_ids == ("prom",)


def test_own_history_is_candidate_even_if_unpromoted(tmp_path):
    w = World(tmp_path)
    mine = w.add("mine", 1, variant(1), solver="alice")
    w.add("prom", 2, variant(4), solver="bob", promoted=True)
    child = w.add("c", 10, BASE, solver="alice")
    r = w.parents(child, own=[mine])
    assert r.tree.parent_ids == ("mine",)


def test_own_history_capped_at_50(tmp_path):
    w = World(tmp_path)
    own = [w.add("mine_exact_old", 0, BASE, solver="alice")]
    for i in range(50):
        own.append(w.add(f"m{i}", 10 + i, variant(3, f"m{i}_"), solver="alice"))
    child = w.add("c", 100, BASE, solver="alice")
    r = w.parents(child, own=own)
    assert r.tree.parent_ids != ("mine_exact_old",)


def test_later_rows_never_chosen(tmp_path):
    w = World(tmp_path)
    w.add("early", 1, variant(4), promoted=True)
    w.add("later", 20, BASE, promoted=True)
    r = w.parents(w.add("c", 10, BASE))
    assert r.tree.parent_ids == ("early",)


def test_novel_uses_child_side_not_total_distance(tmp_path):
    w = World(tmp_path)
    w.add("p", 1, BASE, promoted=True)
    child = w.add("c", 10, variant(3, "n"))  # 3 replaced of 10: child_side 3 <= 5
    r = w.parents(child)
    assert r.tree.method == "tree"
    assert r.tree.parent_ids == ("p",)
    assert r.tree.distance == 6
    assert r.tree.child_side == 3


def test_pure_deletions_are_not_novel(tmp_path):
    w = World(tmp_path)
    w.add("p", 1, BASE, promoted=True)
    r = w.parents(w.add("c", 10, BASE[:3]))
    assert r.tree.method == "tree"
    assert r.tree.child_side == 0


def test_not_novel_at_exactly_half(tmp_path):
    w = World(tmp_path)
    w.add("p", 1, BASE, promoted=True)
    r = w.parents(w.add("c", 10, variant(5, "n")))
    assert r.tree.child_side == 5
    assert r.tree.method == "tree"


def test_mostly_rewritten_child_is_novel(tmp_path):
    w = World(tmp_path)
    w.add("p", 1, BASE, promoted=True)
    r = w.parents(w.add("c", 10, variant(8, "n")))
    assert r.tree.method == "novel"
    assert r.tree.parent_ids == ()
    assert r.primary.method == "novel"


def test_child_without_tree_is_none(tmp_path):
    w = World(tmp_path)
    w.add("p", 1, BASE, promoted=True)
    r = w.parents(w.add("c", 10, None))
    assert r.tree.method == "none"
    assert r.tree.parent_ids == ()
    assert r.tree.distance is None


def test_no_candidates_with_trees_is_none(tmp_path):
    w = World(tmp_path)
    w.add("p", 1, None, promoted=True)
    r = w.parents(w.add("c", 10, BASE))
    assert r.tree.method == "none"


# ------------------------------------------------------------------- build

class Calls:
    def __init__(self, monkeypatch):
        self.diffs = 0
        real_run, real_popen = subprocess.run, subprocess.Popen
        real_co = subprocess.check_output

        def count(args):
            if isinstance(args, (list, tuple)) and "diff" in [str(a) for a in args]:
                self.diffs += 1

        def run(args, *a, **k):
            count(args)
            return real_run(args, *a, **k)

        def popen(args, *a, **k):
            count(args)
            return real_popen(args, *a, **k)

        def co(args, *a, **k):
            count(args)
            return real_co(args, *a, **k)

        monkeypatch.setattr(subprocess, "run", run)
        monkeypatch.setattr(subprocess, "Popen", popen)
        monkeypatch.setattr(subprocess, "check_output", co)


class StubSnapshot:
    def __init__(self, subs, meta, attr):
        self._subs, self._meta, self._attr = subs, meta, attr

    def load(self, benchmark):
        return list(self._subs)

    def benchmark_meta(self, benchmark):
        return self._meta

    def attribution(self, benchmark):
        return self._attr


def tiny_benchmark(tmp_path):
    remote = Repo(tmp_path / "remote")
    c0 = remote.commit({"src/main.py": lines("l", 10), "README.md": ["a"]})
    c1 = remote.commit({"src/main.py": variant(1), "README.md": ["b"]})
    c2 = remote.commit({"src/main.py": variant(2), "README.md": ["c"]})
    bogus = "d" * 40
    subs = [
        sub("s1", 1, solver="alice", promoted=True, promoted_ref=c0),
        sub("s2", 2, solver="bob", submission_sha=c1),
        sub("s3", 3, solver="bob", submission_sha=bogus),
        sub("s4", 4, solver="alice", submission_sha=c2),
    ]
    meta = Benchmark(id="b1", name="tiny", slug="tiny", direction="lower",
                     editable_paths=["src/main.py"], source_url=str(remote.path),
                     opened_at=None, min_improvement_bips=None)
    return StubSnapshot(subs, meta, {"s4": ["s1"]}), bogus


def run_build(stub, root, cache):
    build.run("yukon/tiny", snapshot=stub, frozen_root=root, cache_dir=cache)


def frozen_files(root):
    return {p.relative_to(root).as_posix(): p.read_bytes()
            for p in sorted(root.rglob("*")) if p.is_file()}


def test_build_writes_outputs_deterministically(tmp_path):
    stub, bogus = tiny_benchmark(tmp_path)
    cache = tmp_path / "cache"
    r1, r2 = tmp_path / "f1", tmp_path / "f2"
    run_build(stub, r1, cache)
    out = frozen_files(r1)
    for name in ("manifests.json.gz", "distances.json.gz", "parents.json.gz", "missing.json"):
        assert f"tiny/{name}" in out
    assert "SHA256SUMS" in out
    assert bogus in out["tiny/missing.json"].decode()
    parents_json = json.loads(gzip.decompress(out["tiny/parents.json.gz"]))
    assert "s4" in parents_json and "s2" in parents_json
    for line in out["SHA256SUMS"].decode().splitlines():
        digest, name = line.split("  ", 1)
        assert hashlib.sha256(out[name]).hexdigest() == digest
    run_build(stub, r2, tmp_path / "cache2")
    assert frozen_files(r2) == out


def test_build_second_run_reuses_distance_memo(tmp_path, monkeypatch):
    stub, _ = tiny_benchmark(tmp_path)
    cache, root = tmp_path / "cache", tmp_path / "f"
    calls = Calls(monkeypatch)
    run_build(stub, root, cache)
    first = calls.diffs
    before = frozen_files(root)
    assert first > 0
    run_build(stub, root, cache)
    assert calls.diffs == first
    assert frozen_files(root) == before


# ------------------------------------------------------------------ window

def mk_rows(week, n_prom, n_other, tree_prom, tree_other, tag):
    start = dt.datetime(2026, 3, 2, tzinfo=dt.timezone.utc) + dt.timedelta(weeks=week)
    rows, has = [], set()
    for k in range(n_prom + n_other):
        prom = k < n_prom
        s = sub(f"{tag}{k}", 0, promoted=prom)
        s = type(s)(**{**s.__dict__, "created_at": start + dt.timedelta(hours=k + 1)})
        rows.append(s)
        idx = k if prom else k - n_prom
        if idx < (tree_prom if prom else tree_other):
            has.add(s.id)
    return rows, has


def test_window_start_is_first_balanced_week():
    rows, has = [], set()
    for week, (tp, to) in enumerate([(10, 2), (10, 2), (5, 5), (5, 5)]):
        r, h = mk_rows(week, 10, 10, tp, to, f"w{week}_")
        rows += r
        has |= h
    start = window.start(rows, has)
    start = start.date() if isinstance(start, dt.datetime) else start
    assert start == dt.date(2026, 3, 16)


def test_window_start_first_week_when_balanced_throughout():
    rows, has = [], set()
    for week in range(3):
        r, h = mk_rows(week, 10, 10, 6, 6, f"w{week}_")
        rows += r
        has |= h
    start = window.start(rows, has)
    start = start.date() if isinstance(start, dt.datetime) else start
    assert start == dt.date(2026, 3, 2)


# ------------------------------------------- build: denominator, offline, resume

NEVER_EVAL = "claimed score did not improve current best"


def mixed_benchmark(tmp_path):
    remote = Repo(tmp_path / "remote")
    c0 = remote.commit({"src/main.py": lines("l", 10), "README.md": ["a"]})
    c_nae = remote.commit({"src/main.py": variant(1), "README.md": ["nae"]})
    c_kid = remote.commit({"src/main.py": variant(1), "README.md": ["kid"]})
    c_dec = remote.commit({"src/main.py": variant(2), "README.md": ["dec"]})
    c_can = remote.commit({"src/main.py": variant(1), "README.md": ["can"]})
    subs = [
        sub("s1", 1, solver="alice", promoted=True, promoted_ref=c0),
        sub("nae", 5, solver="bob", submission_sha=c_nae, rejection_reason=NEVER_EVAL),
        sub("can", 5, solver="bob", submission_sha=c_can, cancelled=True),
        sub("kid", 6, solver="bob", submission_sha=c_kid),
        sub("dec", 7, solver="carol", submission_sha=c_dec),
    ]
    meta = Benchmark(id="b1", name="mixed", slug="mixed", direction="lower",
                     editable_paths=["src/main.py"], source_url=str(remote.path),
                     opened_at=None, min_improvement_bips=None)
    return StubSnapshot(subs, meta, {"dec": ["nae"]})


def test_build_uses_analysis_rows_only(tmp_path):
    stub = mixed_benchmark(tmp_path)
    root = tmp_path / "f"
    build.run("yukon/mixed", snapshot=stub, frozen_root=root, cache_dir=tmp_path / "cache")
    pj = json.loads(gzip.decompress((root / "mixed" / "parents.json.gz").read_bytes()))
    # identical-tree never-evaluated row is not chosen as the tree parent
    assert pj["kid"]["tree"][0] == ["s1"]
    assert "nae" not in pj and "can" not in pj
    assert {"s1", "kid", "dec"} <= set(pj)


def test_declared_dependency_checked_against_all_snapshot_rows(tmp_path):
    stub = mixed_benchmark(tmp_path)
    root = tmp_path / "f"
    build.run("yukon/mixed", snapshot=stub, frozen_root=root, cache_dir=tmp_path / "cache")
    pj = json.loads(gzip.decompress((root / "mixed" / "parents.json.gz").read_bytes()))
    assert pj["dec"]["primary"][0] == ["nae"]
    assert pj["dec"]["primary"][1] == "declared"
    assert pj["dec"]["dropped"] == []


def test_offline_rerun_never_overwrites_a_good_freeze(tmp_path):
    stub, _ = tiny_benchmark(tmp_path)
    root = tmp_path / "f"
    build.run("yukon/tiny", snapshot=stub, frozen_root=root, cache_dir=tmp_path / "cache")
    before = frozen_files(root)
    gone = Benchmark(**{**stub._meta.__dict__, "source_url": str(tmp_path / "does-not-exist")})
    offline = StubSnapshot(stub._subs, gone, stub._attr)
    try:
        build.run("yukon/tiny", snapshot=offline, frozen_root=root,
                  cache_dir=tmp_path / "empty-cache")
    except Exception as e:  # a clear refusal is allowed
        assert str(e).strip()
    assert frozen_files(root) == before


def many_row_benchmark(tmp_path, n=12):
    remote = Repo(tmp_path / "remote")
    subs = []
    for i in range(n):
        sha = remote.commit({"src/main.py": lines(f"t{i}_", 10)})
        subs.append(sub(f"r{i:02d}", i + 1, solver="alice", submission_sha=sha))
    meta = Benchmark(id="b1", name="many", slug="many", direction="lower",
                     editable_paths=["src/main.py"], source_url=str(remote.path),
                     opened_at=None, min_improvement_bips=None)
    return StubSnapshot(subs, meta, {})


def test_build_resumes_from_flushed_memo_after_crash(tmp_path, monkeypatch):
    stub = many_row_benchmark(tmp_path)
    monkeypatch.setattr(build, "FLUSH_EVERY", 1)
    calls = Calls(monkeypatch)

    cold_root = tmp_path / "cold"
    build.run("yukon/many", snapshot=stub, frozen_root=cold_root, cache_dir=tmp_path / "cache")
    cold = calls.diffs
    assert cold > 0

    real = parents.parents
    seen = {"n": 0}

    def crashing(*a, **k):
        seen["n"] += 1
        if seen["n"] > 9:
            raise RuntimeError("simulated crash")
        return real(*a, **k)

    root = tmp_path / "crash"
    monkeypatch.setattr(parents, "parents", crashing)
    with pytest.raises(RuntimeError, match="simulated crash"):
        build.run("yukon/many", snapshot=stub, frozen_root=root, cache_dir=tmp_path / "cache")
    monkeypatch.setattr(parents, "parents", real)
    assert (root / "many" / "distances.json.gz").exists()

    calls.diffs = 0
    build.run("yukon/many", snapshot=stub, frozen_root=root, cache_dir=tmp_path / "cache")
    assert 0 < calls.diffs < cold
    assert frozen_files(root) == frozen_files(cold_root)
