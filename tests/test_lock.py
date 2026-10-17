"""Track E1: analysis.lock (spec 0001 section 5.8, AT6). Runs in a throwaway git repo."""
from __future__ import annotations

import json
import re
import subprocess

import pytest

from tests.fixtures_analysis import CODE, FROZEN_DATA, HASHED, NOT_HASHED, REQUIRED, make_tree

GIT = ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid",
       "-c", "commit.gpgsign=false", "-c", "tag.gpgsign=false"]


def git(root, *args):
    return subprocess.run(GIT + list(args), cwd=root, check=True, capture_output=True,
                          text=True).stdout


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    make_tree(root)
    git(root, "init", "-q")
    return root


def manifest_files(root):
    m = json.loads((root / "docs" / "prereg-manifest.json").read_text())
    return m.get("files", m)


def lock_and_tag(root, tag="prereg-v1"):
    from analysis import lock
    lock.write_manifest(root)
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "lock")
    if tag:
        git(root, "tag", tag)


def test_write_manifest_hashes_listed_paths_and_skips_cache(repo):
    from analysis import lock
    lock.write_manifest(repo)
    files = manifest_files(repo)
    for rel in HASHED:
        assert rel in files, rel
        assert re.fullmatch(r"[0-9a-f]{64}", files[rel]), rel
    for rel in NOT_HASHED:
        assert rel not in files, rel


def test_manifest_hash_is_sha256_of_file_bytes(repo):
    import hashlib
    from analysis import lock
    lock.write_manifest(repo)
    files = manifest_files(repo)
    want = hashlib.sha256((repo / "analysis/dataset.py").read_bytes()).hexdigest()
    assert files["analysis/dataset.py"] == want


def test_write_manifest_is_deterministic(repo):
    from analysis import lock
    lock.write_manifest(repo)
    first = (repo / "docs/prereg-manifest.json").read_bytes()
    lock.write_manifest(repo)
    assert (repo / "docs/prereg-manifest.json").read_bytes() == first


def test_check_passes_when_unchanged_and_manifest_matches_tag(repo):
    from analysis import lock
    lock_and_tag(repo)
    lock.check(repo)  # does not raise


def test_check_ignores_lineage_cache(repo):
    from analysis import lock
    lock_and_tag(repo)
    (repo / "lineage/cache/blob.bin").write_text("changed\n")
    (repo / "lineage/cache/new.bin").write_text("new\n")
    lock.check(repo)


@pytest.mark.parametrize("rel", FROZEN_DATA)
def test_check_raises_when_frozen_data_edited_without_resigning(repo, rel):
    from analysis import lock
    lock_and_tag(repo)
    (repo / rel).write_text("tampered\n")
    with pytest.raises(lock.LockError):
        lock.check(repo)


@pytest.mark.parametrize("rel", ["lineage/frozen/slug/extra.json",
                                 "snapshot/raw/slug/extra.json.gz"])
def test_check_raises_on_unlisted_extra_frozen_file(repo, rel):
    from analysis import lock
    lock_and_tag(repo)
    (repo / rel).write_text("surprise\n")
    with pytest.raises(lock.LockError):
        lock.check(repo)


@pytest.mark.parametrize("rel", ["families/mapper.py", "outcomes/promotion.py",
                                 "snapshot/load.py", "lineage/parents.py",
                                 "analysis/dataset.py"])
def test_check_raises_when_rule_code_changes_after_tag(repo, rel):
    from analysis import lock
    lock_and_tag(repo)
    (repo / rel).write_text("# edited after the tag\n")
    with pytest.raises(lock.LockError):
        lock.check(repo)


def test_manifest_covers_code_in_every_rule_package(repo):
    from analysis import lock
    lock.write_manifest(repo)
    files = manifest_files(repo)
    for rel in CODE:
        assert rel in files, rel


@pytest.mark.parametrize("rel", REQUIRED)
def test_write_manifest_raises_when_a_required_file_is_missing(repo, rel):
    from analysis import lock
    (repo / rel).unlink()
    with pytest.raises(lock.LockError):
        lock.write_manifest(repo)


@pytest.mark.parametrize("rel", REQUIRED)
def test_check_raises_when_tagged_manifest_lacks_a_required_key(repo, rel):
    from analysis import lock
    lock.write_manifest(repo)
    p = repo / "docs/prereg-manifest.json"
    m = json.loads(p.read_text())
    files = m.get("files", m)
    del files[rel]
    p.write_text(json.dumps(m, indent=2, sort_keys=True) + "\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "lock")
    git(repo, "tag", "prereg-v1")
    with pytest.raises(lock.LockError):
        lock.check(repo)


@pytest.mark.parametrize("rel", ["docs/prereg.md", "analysis/sub/deep.py",
                                 "lineage/parents.py", "families/table.yaml",
                                 "outcomes/denominator.yaml", "snapshot/raw/SHA256SUMS",
                                 "lineage/frozen/SHA256SUMS"])
def test_check_raises_when_a_hashed_file_changes(repo, rel):
    from analysis import lock
    lock_and_tag(repo)
    (repo / rel).write_text("tampered\n")
    with pytest.raises(lock.LockError):
        lock.check(repo)


def test_check_raises_when_a_hashed_file_is_deleted(repo):
    from analysis import lock
    lock_and_tag(repo)
    (repo / "analysis/dataset.py").unlink()
    with pytest.raises(lock.LockError):
        lock.check(repo)


def test_check_raises_when_manifest_differs_from_tagged_copy(repo):
    from analysis import lock
    lock_and_tag(repo)
    (repo / "analysis/dataset.py").write_text("x = 2\n")
    lock.write_manifest(repo)  # working tree and manifest agree, tag does not
    with pytest.raises(lock.LockError):
        lock.check(repo)


def test_check_raises_when_manifest_is_hand_edited(repo):
    from analysis import lock
    lock_and_tag(repo)
    p = repo / "docs/prereg-manifest.json"
    p.write_text(p.read_text() + "\n")
    with pytest.raises(lock.LockError):
        lock.check(repo)


def test_check_raises_when_tag_is_missing(repo):
    from analysis import lock
    lock_and_tag(repo, tag=None)
    with pytest.raises(lock.LockError):
        lock.check(repo)


def test_check_raises_when_tag_is_named_differently(repo):
    from analysis import lock
    lock_and_tag(repo, tag="prereg-v2")
    with pytest.raises(lock.LockError):
        lock.check(repo)
