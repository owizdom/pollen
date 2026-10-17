# Tasks

Spec: `docs/specs/0001-cross-model-pollination.md` (approved 2026-10-17).
Tracks own disjoint files. A track touches nothing outside its list.

## Wave 1

### Track A: snapshot (AT1)

Owns: `snapshot/__init__.py`, `snapshot/fetch.py`, `snapshot/load.py`, `snapshot/model.py`, `snapshot/raw/` (gzipped JSON, `SHA256SUMS`, `FREEZE.json`), `snapshot/FREEZE.md`, `tests/test_snapshot.py`, `tests/conftest.py`.

- `fetch.py`: download `GET https://api.yukon.org/api/benchmarks`, then per benchmark `/api/benchmarks/{id}` and `/api/benchmarks/{id}/submissions`. No auth. Write gzipped JSON per benchmark under `snapshot/raw/<slug>/`, then `SHA256SUMS` and `FREEZE.md` (UTC fetch time, API URL, per-benchmark row counts, redistribution note).
- `model.py`: the `Submission` and `Benchmark` dataclasses from spec §8.
- `load.py`: `load(benchmark) -> list[Submission]`, `benchmark_meta(benchmark) -> Benchmark`, `benchmarks() -> list[str]`. Reads frozen files only; verifies the checksum of each file it opens.
- Tests: checksum mismatch raises; row counts equal `FREEZE.md`; `promoted` is true exactly when `status == "accepted"` and `promotionStatus == "promoted"`; cancelled rows load but are flagged; loader never touches the network.

Status: implemented, 19/19 tests green; under review; real freeze running.

## Wave 2 (after A)

Shared rule: test files use their own fixture helpers (`tests/fixtures_<track>.py`); nobody edits `tests/conftest.py` except Track A. Tests may read the real frozen snapshot through `snapshot.load` (it exists after M1); no test may skip.

### Track B: families (AT2, AT3)

Owns: `families/__init__.py`, `families/mapper.py`, `families/table.yaml`, `families/build_table.py`, `families/audit/`, `tests/test_families.py`, `tests/fixtures_families.py`.

- `families/table.yaml`: `strings: {<exact model line>: <family>}` where family is one of Anthropic, OpenAI, Google, xAI, Moonshot, MiniMax, Zhipu, DeepSeek, Alibaba, Mistral, Meta, Other:<vendor>, Multi, Unknown. Exact strings, case preserved.
- `families/build_table.py`: proposes a family for every distinct `model_line` in the frozen study benchmarks using vendor keyword rules, keeps existing entries untouched, writes new ones, and prints the strings it could not resolve. A string naming two or more vendors (separators such as "+", "/", "&", " and ", ",") is Multi. Product names without a model (Devin, Droid, Composer, Factory) and vendor-ambiguous names (bare "Astra") are Unknown.
- `families/mapper.py`: `family_of(model_line: str | None) -> str` is a pure table lookup (None gives "Unknown"; a string absent from the table raises `UnmappedModel`). `harness_of(note: str) -> str | None` reads a line starting "Harness:" (case-insensitive). `vendors_in(model_line) -> frozenset[str]` is the keyword detector `build_table` uses.
- AT2: every distinct `model_line` in every study benchmark of the frozen snapshot maps without raising; golden cases from spec §9 pass.
- AT3 (live, later): `families/audit/sample.py` draws 200 seeded notes for the reviewer audit.

### Track C: lineage (AT4, AT15)

Owns: `lineage/__init__.py`, `lineage/declared.py`, `lineage/distance.py`, `lineage/trees.py`, `lineage/parents.py`, `lineage/frozen/`, `tests/test_lineage.py`, `tests/fixtures_lineage.py`.

- `declared.py`: `declared_base_tokens(note) -> list[str]` extracts candidate ids after "Base:" or "base:" (submission-id prefixes of 7+ hex, full 40-hex SHAs, full UUIDs). `resolve(token, subs) -> str | None` maps a token to a submission id by matching submission id prefix, `commit_sha`, or the API's `promotedSourceRef`; ambiguous or unknown tokens give None.
- `distance.py`: `changed_lines(a: dict[str, list[str]], b: dict[str, list[str]]) -> int`, the number of added plus removed lines over the union of paths (a missing path counts as empty). `size(tree) -> int`, total lines.
- `trees.py`: given a benchmark's repo URL, editable paths and a set of commit SHAs, maintains a bare mirror under `lineage/cache/` (gitignored), reads each commit's editable-path files with `git cat-file`, and returns `{sha: {path: lines}}`. Writes `lineage/frozen/<slug>/manifests.json.gz` (`{sha: {path: blob_sha}}`). SHAs that cannot be fetched are recorded in `missing.json`.
- `parents.py`: `parents(sub, earlier, attribution, trees, own_history) -> ParentLink(parent_ids, method, distance)`. Order: declared attribution (one parent: method "declared"; two or more: method "multi"); else tree distance over candidates = earlier rows with trees, identical trees collapsed by hash, limited to the last 50 promoted rows plus the solver's own earlier rows, minimum `changed_lines`, ties to the most recent (method "tree"); if that minimum exceeds half of `size(child tree)`, method "novel" with no parent; if the child has no tree, method "none".
- Writes `lineage/frozen/<slug>/parents.json.gz` and `lineage/frozen/SHA256SUMS`.
- AT4 and AT15 run on the real data once frozen.

### Track D: outcomes (AT5)

Owns: `outcomes/__init__.py`, `outcomes/denominator.yaml`, `outcomes/denominator.py`, `outcomes/promotion.py`, `outcomes/frontier.py`, `outcomes/pareto.py`, `outcomes/jumps.py`, `outcomes/sealed/`, `tests/test_outcomes.py`, `tests/fixtures_outcomes.py`.

- `denominator.yaml`: per benchmark, the list of `rejection_reason` strings that mean "never evaluated" (for ecdsa.fail: claimed score did not improve; does not contain code change; packaging errors), plus a default list applied to every benchmark. `denominator.py`: `analysis_rows(subs, benchmark) -> list[Submission]` drops cancelled and never-evaluated rows.
- `promotion.py`: `y1(sub) -> bool` is `promotionStatus == "promoted"` (the loader's `promoted`). `recompute(subs, meta) -> list[bool]` recomputes promotion from the running best score: a row with a score strictly better than the best promoted score before it (by `created_at`), by at least `min_improvement_bips` when set, under the benchmark direction. Returns a report of disagreements; the 4 ecdsa.fail accepted-but-failed rows are named expected exceptions.
- `frontier.py`: `best_before(subs, meta)` per row; `gain_log(row)` for promoted rows, signed so larger is better.
- `jumps.py`: `large_jumps(rows)` top decile of gain within benchmark; `plateau_breaks(rows, hours=72, threshold=0.01)`.
- `pareto.py` (ecdsa.fail): `pareto_gain(rows)` true when (qubits, toffoli) from `metrics` is not dominated by any earlier valid row.
- `annotate(subs, meta)` writes `outcomes/sealed/<slug>.json.gz` and returns nothing that splits outcomes by treatment.
- AT5: recomputation agrees with `promotionStatus` on every analysis row except named exceptions, reported as pass or fail.

## Wave 3

- Track E analysis (AT6, AT9): `analysis/`, `docs/prereg.md`, `tests/test_analysis.py`.

## Wave 4

- Track F paper (AT7, AT8, AT10, AT11, AT12): `paper/`, `cases/`, `README.md`.
