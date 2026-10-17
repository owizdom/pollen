"""Track B: AT2, family table, mapper, build_table."""
import copy
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import yaml  # noqa: E402

from families import build_table, mapper  # noqa: E402
from fixtures_families import (ALLOWED_FAMILIES, GOLDEN, COMPANY_MODEL, GOLDEN_EXTRA, LONG_MARK, LONG_NOTE, NO_VENDOR,  # noqa: E402
                               REVIEW_NO, REVIEW_YES, SINGLE_VENDOR, VENDORS)

TABLE = REPO / "families" / "table.yaml"


# family_of

def test_family_of_none_is_unknown():
    assert mapper.family_of(None) == "Unknown"


def test_family_of_unmapped_string_raises():
    with pytest.raises(mapper.UnmappedModel):
        mapper.family_of("Zzyzx Neural Frobnicator 9000 (never in any table)")


def test_unmapped_model_is_an_exception_class():
    assert issubclass(mapper.UnmappedModel, Exception)


@pytest.mark.parametrize("line,family", GOLDEN)
def test_golden_cases_against_checked_in_table(line, family):
    assert mapper.family_of(line) == family


def test_table_yaml_format_is_strings_mapping():
    data = yaml.safe_load(TABLE.read_text())
    assert isinstance(data, dict) and isinstance(data["strings"], dict)
    assert data["strings"]
    for k, v in data["strings"].items():
        assert isinstance(k, str) and isinstance(v, str) and v


def test_table_golden_strings_are_exact_keys():
    strings = yaml.safe_load(TABLE.read_text())["strings"]
    for line, family in GOLDEN:
        assert strings[line] == family


@pytest.mark.parametrize("line,family", GOLDEN_EXTRA)
def test_review_golden_labels_against_checked_in_table(line, family):
    assert mapper.family_of(line) == family


def test_checked_in_table_values_are_allowed():
    mapper.validate_table(TABLE)
    import re
    for k, v in yaml.safe_load(TABLE.read_text())["strings"].items():
        assert v in ALLOWED_FAMILIES or re.match(r"^Other:\S.*$", v), (k, v)


@pytest.mark.parametrize("bad", ["Openai", "Mutli", "Other:", "Other", "unknown", ""])
def test_validate_table_rejects_bad_family(tmp_path, bad):
    p = tmp_path / "table.yaml"
    p.write_text(yaml.safe_dump({"strings": {"GPT-5 Codex": "OpenAI", "X": bad}}))
    validate = mapper.validate_table  # AttributeError here must not count as a raise
    with pytest.raises(Exception) as ei:
        validate(p)
    assert not isinstance(ei.value, (AttributeError, TypeError, NameError))


def test_validate_table_accepts_good_table(tmp_path):
    p = tmp_path / "table.yaml"
    p.write_text(yaml.safe_dump({"strings": {"A": "OpenAI", "B": "Other:Cursor",
                                             "C": "Multi", "D": "Unknown"}}))
    mapper.validate_table(p)


# vendors_in

@pytest.mark.parametrize("line,expected", VENDORS)
def test_vendors_in_detects_vendors(line, expected):
    got = mapper.vendors_in(line)
    assert isinstance(got, frozenset)
    assert got == frozenset(expected)


@pytest.mark.parametrize("line,vendor", SINGLE_VENDOR)
def test_vendors_in_single_vendor_stays_single(line, vendor):
    assert mapper.vendors_in(line) == frozenset({vendor})


@pytest.mark.parametrize("line,expected", COMPANY_MODEL)
def test_vendors_in_company_model_rule(line, expected):
    assert mapper.vendors_in(line) == frozenset(expected)


def test_composer_plus_claude_is_multi_in_propose():
    out = build_table.propose(["Composer 2.5 + Claude Opus 5.5", "Doubao", "Poolside Preview",
                               "Grok Bot"], {})
    assert out["Composer 2.5 + Claude Opus 5.5"] == "Multi"
    assert out["Doubao"] == "Other:ByteDance"
    assert out["Poolside Preview"] == "Other:Poolside"
    assert out["Grok Bot"] == "xAI"


@pytest.mark.parametrize("line", NO_VENDOR)
def test_vendors_in_empty_for_products_and_junk(line):
    assert mapper.vendors_in(line) == frozenset()


def test_vendors_in_none_is_empty():
    assert mapper.vendors_in(None) == frozenset()


# harness_of

def test_harness_of_basic():
    assert mapper.harness_of("Model: GPT-5 Codex\nHarness: Claude Code\nbody") == "Claude Code"


def test_harness_of_anywhere_in_note():
    note = "Model: Kimi K3\n\nlong prose\nmore prose\nHarness: codex cli\nend"
    assert mapper.harness_of(note) == "codex cli"


def test_harness_of_case_insensitive_key():
    assert mapper.harness_of("Model: x\nHARNESS: Claude Code") == "Claude Code"
    assert mapper.harness_of("harness: Claude Code") == "Claude Code"


def test_harness_of_strips_whitespace():
    assert mapper.harness_of("Model: x\nHarness:   Claude Code   \n") == "Claude Code"


def test_harness_of_absent_is_none():
    assert mapper.harness_of("Model: GPT-5 Codex\nno harness here") is None
    assert mapper.harness_of("") is None


def test_harness_of_must_start_the_line():
    assert mapper.harness_of("Model: x\nthe harness: Claude Code") is None


# build_table.propose

def test_propose_adds_new_strings_with_rule_families():
    out = build_table.propose(
        ["GPT-5 Codex", "Kimi K3", "Claude Opus 5.5 + GPT-6.1 Sol", "Devin", "Astra"], {})
    assert out["GPT-5 Codex"] == "OpenAI"
    assert out["Kimi K3"] == "Moonshot"
    assert out["Claude Opus 5.5 + GPT-6.1 Sol"] == "Multi"
    assert out["Devin"] == "Unknown"
    assert out["Astra"] == "Unknown"


def test_propose_keeps_existing_entries_untouched():
    existing = {"GPT-5 Codex": "Anthropic", "Mystery": "Other:Acme"}
    snapshot = copy.deepcopy(existing)
    out = build_table.propose(["GPT-5 Codex", "Mystery", "Kimi K3"], existing)
    assert out["GPT-5 Codex"] == "Anthropic"
    assert out["Mystery"] == "Other:Acme"
    assert out["Kimi K3"] == "Moonshot"
    assert existing == snapshot, "propose must not mutate its input"


def test_propose_only_adds_given_strings():
    existing = {"Old Entry": "Google"}
    out = build_table.propose(["Kimi K3"], existing)
    assert set(out) == {"Old Entry", "Kimi K3"}
    assert out["Old Entry"] == "Google"


def test_propose_unresolvable_string_is_unknown():
    out = build_table.propose(["benchmark"], {})
    assert out["benchmark"] == "Unknown"


def test_propose_is_idempotent():
    first = build_table.propose(["Kimi K3", "Devin"], {})
    assert build_table.propose(["Kimi K3", "Devin"], first) == first


def test_propose_empty():
    assert build_table.propose([], {"A": "Google"}) == {"A": "Google"}


# build_table.review_list

@pytest.mark.parametrize("line", REVIEW_YES)
def test_review_list_flags_separator_with_under_two_vendors(line):
    assert line in build_table.review_list([line], {})


@pytest.mark.parametrize("line", REVIEW_NO)
def test_review_list_skips_clean_strings(line):
    assert line not in build_table.review_list([line], {})


def test_review_list_mixed_input_exact():
    got = build_table.review_list(REVIEW_YES + REVIEW_NO, {})
    assert sorted(got) == sorted(REVIEW_YES)


# AT2 completeness against the frozen snapshot

def test_at2_every_model_line_maps_in_large_benchmarks():
    from snapshot import load

    checked = 0
    bad = []
    for bench in load.benchmarks():
        rows = load.load(bench)
        if len(rows) < 500:
            continue
        checked += 1
        for line in sorted({r.model_line for r in rows if r.model_line is not None}):
            try:
                mapper.family_of(line)
            except mapper.UnmappedModel:
                bad.append((bench, line))
    assert checked > 0, "no benchmark with >= 500 rows in the snapshot"
    assert not bad, f"unmapped model lines: {bad[:20]} ({len(bad)} total)"


# AT3 sample keeps the whole note

def test_at3_sample_writes_full_note_and_note_chars(tmp_path, monkeypatch):
    import json

    import conftest
    from families.audit import sample as sample_mod

    bench = "yukon/big-bench"
    subs = [conftest._sub(f"p{i:04d}", "b9", "rejected", f"2026-03-01T10:{i % 60:02d}:00.000Z",
                          note="Model: Kimi K3\nshort") for i in range(520)]
    subs.append(conftest._sub("long", "b9", "rejected", "2026-03-02T10:00:00.000Z",
                              note=LONG_NOTE))
    assert len(LONG_NOTE) == 9000 and LONG_NOTE.index(LONG_MARK) > 6000
    monkeypatch.setattr(conftest, "BENCHES", {bench: ("-", subs, "b9")})
    monkeypatch.setattr(conftest, "ATTRIBUTION", {})
    root = conftest.build_snapshot(tmp_path / "raw")
    from snapshot import load
    monkeypatch.setattr(load, "DEFAULT_ROOT", root)

    out = tmp_path / "sample.jsonl"
    recs = sample_mod.sample(n=10_000, out=out)
    written = [json.loads(line) for line in out.read_text().splitlines()]
    assert len(written) == len(recs) == 521
    long_rec = next(r for r in written if r["id"] == "long")
    assert LONG_MARK in long_rec["note"]
    assert long_rec["note"] == LONG_NOTE
    assert long_rec["note_chars"] == 9000
    assert all(r["note_chars"] == len(r["note"]) for r in written)
