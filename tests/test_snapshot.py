"""AT1: snapshot integrity and typed loading (spec 0001 sections 3.1, 8, 9)."""
import datetime as dt
import gzip
import json
import socket

import pytest

from conftest import build_snapshot, edit_freeze, write_sums  # noqa: F401

LOWER = "yukon/lower-bench"
HIGHER = "yukon/higher-bench"


def mod():
    import snapshot.load as load
    return load


def by_id(rows):
    return {r.id: r for r in rows}


def test_benchmarks_lists_frozen_names(snap):
    assert sorted(mod().benchmarks(root=snap)) == sorted([LOWER, HIGHER])


def test_load_sorted_by_created_at_and_complete(snap):
    rows = mod().load(LOWER, root=snap)
    assert [r.id for r in rows] == ["s1", "s2", "s3", "s4", "s5"]
    assert all(r.created_at.tzinfo is not None for r in rows)
    assert rows[0].created_at == dt.datetime(2026, 3, 1, 10, tzinfo=dt.timezone.utc)
    assert all(r.benchmark == LOWER for r in rows)


def test_promoted_requires_accepted_and_promoted(snap):
    rows = by_id(mod().load(LOWER, root=snap))
    assert rows["s1"].promoted is True
    assert rows["s2"].promoted is False  # accepted, promotion failed
    assert rows["s3"].promoted is False  # rejected
    assert rows["s4"].promoted is False  # failed


def test_cancelled_rows_kept_and_flagged(snap):
    rows = by_id(mod().load(LOWER, root=snap))
    assert rows["s5"].cancelled is True
    assert rows["s5"].promoted is False
    assert [r.cancelled for r in rows.values() if r.id != "s5"] == [False] * 4


def test_model_line_parsing(snap):
    rows = by_id(mod().load(LOWER, root=snap))
    assert rows["s1"].model_line == "GPT-5 Codex"
    assert rows["s2"].model_line == "Kimi K3"  # leading blank line, padding stripped
    assert rows["s3"].model_line == "Claude Opus 4.8 (1M context)"
    assert rows["s4"].model_line is None
    assert rows["s5"].model_line == "Devin"


def test_model_line_only_from_first_nonempty_line(snap, tmp_path):
    import json as j
    root = snap
    p = root / "yukon__higher-bench" / "submissions.json.gz"
    data = j.loads(gzip.open(p).read())
    data["submissions"][0]["note"] = "intro first\nModel: Late Model"
    with gzip.GzipFile(p, "wb", mtime=0) as f:
        f.write(j.dumps(data).encode())
    _resum(root)
    assert mod().load(HIGHER, root=root)[0].model_line is None


def test_score_metrics_commit_sha(snap):
    rows = by_id(mod().load(LOWER, root=snap))
    assert rows["s1"].score == 100.0
    assert rows["s1"].metrics == {"size": 100, "time": 1.5}
    assert rows["s1"].commit_sha == "aaaa111"  # promotedSourceRef wins
    assert rows["s2"].commit_sha == "bbbb222"  # falls back to submissionCommitSha
    assert rows["s2"].metrics == {}
    assert rows["s4"].score is None
    assert rows["s4"].commit_sha is None
    assert rows["s4"].solver == "alice"


def test_benchmark_meta_direction(snap):
    lo = mod().benchmark_meta(LOWER, root=snap)
    hi = mod().benchmark_meta(HIGHER, root=snap)
    assert lo.direction == "lower"
    assert hi.direction == "higher"
    assert lo.name == LOWER
    assert lo.editable_paths == ["src/main.py"]
    assert lo.source_url.startswith("https://")
    assert lo.opened_at == dt.datetime(2026, 2, 1, tzinfo=dt.timezone.utc)


def _resum(root):
    write_sums(root)


def test_checksum_mismatch_raises(snap):
    p = snap / "yukon__lower-bench" / "submissions.json.gz"
    p.write_bytes(p.read_bytes() + b"x")
    with pytest.raises(mod().IntegrityError):
        mod().load(LOWER, root=snap)


def test_file_missing_from_sums_raises(snap):
    extra = snap / "yukon__lower-bench" / "extra.json.gz"
    extra.write_bytes(gzip.compress(b"{}"))
    with pytest.raises(mod().IntegrityError):
        mod().load(LOWER, root=snap)


def test_row_count_mismatch_raises(snap):
    # re-signed, so only the row-count check can catch it (lower-bench has 5 rows)
    edit_freeze(snap, lambda f: f["counts"].update({LOWER: 6}))
    with pytest.raises(mod().IntegrityError, match=r"(?i)rows?|count"):
        mod().load(LOWER, root=snap)


def test_clean_snapshot_does_not_raise(snap):
    assert len(mod().load(HIGHER, root=snap)) == 1


def test_load_never_touches_network(snap, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("network used")
    monkeypatch.setattr(socket, "socket", boom)
    assert len(mod().load(LOWER, root=snap)) == 5
    mod().benchmark_meta(LOWER, root=snap)
    mod().benchmarks(root=snap)
    assert "s3" in mod().attribution(LOWER, root=snap)


def test_rejection_reason(snap):
    rows = by_id(mod().load(LOWER, root=snap))
    assert rows["s3"].rejection_reason == "did not improve on best score"
    assert rows["s1"].rejection_reason is None


def test_min_improvement_bips(snap):
    assert mod().benchmark_meta(LOWER, root=snap).min_improvement_bips == 50
    assert mod().benchmark_meta(HIGHER, root=snap).min_improvement_bips is None


def test_attribution_declared_parents_in_order(snap):
    assert mod().attribution(LOWER, root=snap) == {
        "s3": ["s2", "s1"],  # listed order kept, not sorted
        "s2": ["s1"],
    }  # not_provided "s4" has no entry


def test_attribution_missing_file_is_empty(snap):
    assert mod().attribution(HIGHER, root=snap) == {}


def test_attribution_checksum_mismatch_raises(snap):
    p = snap / "yukon__lower-bench" / "attribution.json.gz"
    assert p.exists()
    p.write_bytes(p.read_bytes() + b"x")
    with pytest.raises(mod().IntegrityError):
        mod().attribution(LOWER, root=snap)


def test_attribution_missing_from_sums_raises(snap):
    sums = snap / "SHA256SUMS"
    kept = [l for l in sums.read_text().splitlines() if "attribution" not in l]
    sums.write_text("\n".join(kept) + "\n")
    with pytest.raises(mod().IntegrityError):
        mod().attribution(LOWER, root=snap)


def test_submission_sha_and_promoted_ref(snap):
    rows = by_id(mod().load(LOWER, root=snap))
    assert rows["s1"].submission_sha == "zzzz000"
    assert rows["s1"].promoted_ref == "aaaa111"
    assert rows["s2"].submission_sha == "bbbb222"
    assert rows["s2"].promoted_ref is None
    assert rows["s4"].submission_sha is None and rows["s4"].promoted_ref is None


def test_benchmark_meta_slug_derived_from_name(snap):
    raw = json.loads(gzip.open(snap / "yukon__lower-bench" / "benchmark.json.gz").read())
    assert "slug" not in raw["benchmark"]  # real API detail has no slug
    assert mod().benchmark_meta(LOWER, root=snap).slug == "yukon__lower-bench"


def _add_unselected_attribution(snap):
    """A signed attribution.json.gz for HIGHER, which FREEZE['attribution'] omits."""
    p = snap / "yukon__higher-bench" / "attribution.json.gz"
    with gzip.GzipFile(p, "wb", mtime=0) as f:
        f.write(b"[]")
    write_sums(snap)
    return p


def test_listed_file_missing_raises_even_if_not_opened(snap):
    # load() never opens attribution.json.gz, so only a listed-file check catches this
    p = _add_unselected_attribution(snap)
    assert "yukon__higher-bench/attribution.json.gz" in (snap / "SHA256SUMS").read_text()
    p.unlink()
    with pytest.raises(mod().IntegrityError):
        mod().load(HIGHER, root=snap)


def test_attribution_file_for_unselected_benchmark_raises(snap):
    _add_unselected_attribution(snap)
    with pytest.raises(mod().IntegrityError):
        mod().attribution(HIGHER, root=snap)


def test_benchmarks_verifies_freeze_against_sums(snap):
    freeze = json.loads((snap / "FREEZE.json").read_text())
    del freeze["counts"][HIGHER]
    (snap / "FREEZE.json").write_text(json.dumps(freeze))  # not re-signed
    with pytest.raises(mod().IntegrityError):
        mod().benchmarks(root=snap)


def test_listed_attribution_file_missing_raises(snap):
    (snap / "yukon__lower-bench" / "attribution.json.gz").unlink()
    with pytest.raises(mod().IntegrityError):
        mod().attribution(LOWER, root=snap)


def test_freeze_json_edit_after_the_fact_raises(snap):
    freeze = json.loads((snap / "FREEZE.json").read_text())
    freeze["counts"][HIGHER] = 7
    (snap / "FREEZE.json").write_text(json.dumps(freeze))  # SHA256SUMS not re-signed
    with pytest.raises(mod().IntegrityError):
        mod().load(LOWER, root=snap)


def _set_cursor(snap):
    p = snap / "yukon__lower-bench" / "attribution.json.gz"
    recs = json.loads(gzip.open(p).read())
    recs[0]["nextCursor"] = "page2"
    with gzip.GzipFile(p, "wb", mtime=0) as f:
        f.write(json.dumps(recs).encode())
    write_sums(snap)
    return recs[0]["submissionId"]


def test_nonnull_next_cursor_raises_unless_partial(snap):
    sid = _set_cursor(snap)
    with pytest.raises(mod().IntegrityError):
        mod().attribution(LOWER, root=snap)
    edit_freeze(snap, lambda f: f.update(attribution_partial={LOWER: [sid]}))
    mod().attribution(LOWER, root=snap)  # no raise
