# Tasks

Spec: `docs/specs/0001-cross-model-pollination.md` (approved 2026-10-17).
Tracks own disjoint files. A track touches nothing outside its list.

## Wave 1

### Track A: snapshot (AT1)

Owns: `snapshot/__init__.py`, `snapshot/fetch.py`, `snapshot/load.py`, `snapshot/model.py`, `snapshot/raw/` (gzipped JSON, `SHA256SUMS`, `FREEZE.json`), `snapshot/FREEZE.md`, `tests/test_snapshot.py`, `tests/test_fetch.py`, `tests/conftest.py`.

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
- `families/build_table.py`: proposes a family for every distinct `model_line` in the frozen study benchmarks using vendor keyword rules, keeps existing entries untouched, writes new ones, and prints the strings it could not resolve. A string naming two or more vendors (separators such as "+", "/", "&", " and ", ",") is Multi. Agent products or harnesses without a model (Devin, Droid, Factory, Codex, Codex CLI) and vendor-ambiguous names (bare "Astra") are Unknown. A company's own named model maps to that company (spec §3.2 company-model rule): Composer Other:Cursor, SWE-2 Other:Cognition, Doubao Other:ByteDance, Poolside Other:Poolside.
- `families/mapper.py`: `family_of(model_line: str | None) -> str` is a pure table lookup (None gives "Unknown"; a string absent from the table raises `UnmappedModel`). `harness_of(note: str) -> str | None` reads a line starting "Harness:" (case-insensitive). `vendors_in(model_line) -> frozenset[str]` is the keyword detector `build_table` uses.
- AT2: every distinct `model_line` in every study benchmark of the frozen snapshot maps without raising; golden cases from spec §9 pass.
- AT3 (live, later): `families/audit/sample.py` draws 200 seeded notes for the reviewer audit.

### Track C: lineage (AT4, AT15), rework after review (spec v2.2)

Owns: `lineage/__init__.py`, `lineage/declared.py`, `lineage/distance.py`, `lineage/trees.py`, `lineage/parents.py`, `lineage/build.py`, `lineage/window.py`, `lineage/frozen/`, `tests/test_lineage.py`, `tests/fixtures_lineage.py`.

- `trees.py`: bare mirror per repo under `lineage/cache/` with `gc.auto=0`; fetch SHAs in chunks into `refs/pollen/<sha>`, splitting a failing chunk in halves until bad SHAs are isolated (recorded in `missing`); `tree_ids(sha, editable_paths) -> tuple` of git object ids (one per editable path; missing path gives None) used as tree identity.
- `distance.py`: `numstat(mirror, sha_a, sha_b, paths) -> (added, removed, binary_changed)` from `git diff --numstat --minimal --no-renames`; `changed_lines = added + removed + binary_changed`; `child_side = added` (direction parent to child); `text_size(mirror, sha, paths)` counts text lines only (numstat against the empty tree). A persistent memo keyed by tree identity pair, written to `lineage/frozen/<slug>/distances.json.gz`.
- `parents.py`: `parents(child, earlier, attribution, trees, own_history) -> ParentResult(primary, tree, dropped_declared)`. Tree link always computed. Candidates: rows with trees, collapsed by tree identity keeping the most recent, then the last 50 rows promoted with `finished_at` before the child's `created_at`, plus the child solver's last 50 earlier rows; ties by `created_at` then id. Novel when `child_side > text_size(child) / 2`. Declared ids de-duplicated in order; unknown or not-earlier ids dropped and listed.
- `declared.py`: `resolve` matches id prefix, `commit_sha`, `submission_sha` and `promoted_ref`.
- `build.py`: per study benchmark, maps each analysis row to its tree SHA (`promoted_ref` for promoted rows, else `submission_sha`), fetches, computes parents, writes `lineage/frozen/<slug>/{manifests,distances,parents}.json.gz`, `missing.json`, and `lineage/frozen/SHA256SUMS`. Resumable from the distance memo.
- `window.py` (AT15): confirmatory window start per benchmark from tree availability by promoted vs other rows, per spec §3.1.
- Performance target: ecdsa.fail end to end in under 1 hour on the M1 Pro after the mirror exists.

### Track D: outcomes (AT5)

Owns: `outcomes/__init__.py`, `outcomes/denominator.yaml`, `outcomes/denominator.py`, `outcomes/promotion.py`, `outcomes/frontier.py`, `outcomes/pareto.py`, `outcomes/jumps.py`, `outcomes/sealed/`, `tests/test_outcomes.py`, `tests/fixtures_outcomes.py`.

- `denominator.yaml`: per benchmark, the list of `rejection_reason` strings that mean "never evaluated" (for ecdsa.fail: claimed score did not improve; does not contain code change; packaging errors), plus a default list applied to every benchmark. `denominator.py`: `analysis_rows(subs, benchmark) -> list[Submission]` drops cancelled and never-evaluated rows.
- `promotion.py`: `y1(sub) -> bool` is `promotionStatus == "promoted"` (the loader's `promoted`). `recompute(subs, meta) -> list[bool]` recomputes promotion from the running best score: a row with a score strictly better than the best promoted score before it (by `created_at`), by at least `min_improvement_bips` when set, under the benchmark direction. Returns a report of disagreements; the 4 ecdsa.fail accepted-but-failed rows are named expected exceptions.
- `frontier.py`: `best_before(subs, meta)` per row; `gain_log(row)` for promoted rows, signed so larger is better.
- `jumps.py`: `large_jumps(rows)` top decile of gain within benchmark; `plateau_breaks(rows, hours=72, threshold=0.01)`.
- `pareto.py` (ecdsa.fail): `pareto_gain(rows)` true when (qubits, toffoli) from `metrics` is not dominated by any earlier valid row.
- `annotate(subs, meta)` writes `outcomes/sealed/<slug>.json.gz` and returns nothing that splits outcomes by treatment.
- AT5: recomputation agrees with `promotionStatus` on every analysis row except named exceptions, reported as pass or fail.

## Wave 3 (analysis)

Blinding: until tag `prereg-v1`, no code path may join sealed outcomes to treatment. Tests use synthetic data only, except dataset tests, which may read real treatment fields.

### Track E1: dataset, power, lock (AT6, AT15 consumer)

Owns: `analysis/__init__.py`, `analysis/dataset.py`, `analysis/power.py`, `analysis/lock.py`, `docs/prereg-manifest.json`, `tests/test_dataset.py`, `tests/test_lock.py`, `tests/fixtures_analysis.py`.

- `dataset.build(benchmark, *, snapshot, lineage_root) -> DataFrame`, one row per analysis row (outcomes.denominator.analysis_rows), with columns: id, solver, created_at, week (ISO year-week of created_at), child_model, child_family, multi_family, harness, parent_ids, parent_method (declared, multi, tree, novel, none), tree_parent_id, parent_solver, parent_family, cross_solver, cross_family (True or False only when both families are known single-family and a single parent exists, else None), cell (own_same, own_switch, other_same, other_switch, or None), parent_is_current_best (the parent is the best promoted row whose evaluation finished before the child was created), log_prior_rows (ln(1 + the solver's earlier analysis rows)), in_window (from lineage.window), child_family_folded and parent_family_folded (families with fewer than 30 analysis rows on the benchmark become "Other"). No outcome columns.
- `power.equivalence_power(frame, base_rate, margin=(0.80, 1.25), icc=0.05, sims=..., seed=...) -> float` for one benchmark, and `power.pooled_equivalence_power(frames: dict, base_rates: dict, ...) -> float` for the primary estimand. Both simulate outcomes on the real treatment frame with `analysis.simulate.plant` at OR 1, fit `analysis.models.cond_logit` with the §5.1 covariates, and (pooled) combine with `analysis.models.meta_hksj`; power is the share of runs whose 90% interval lies inside the margin. `power.min_rows(cells)` is the pre-lock row count of the smaller arm.
- `lock.write_manifest(root)` hashes `docs/prereg.md`, every code file under `snapshot/`, `families/`, `lineage/`, `outcomes/` and `analysis/` (excluding caches, raw data and frozen data, which their SHA256SUMS cover), `families/table.yaml`, `outcomes/denominator.yaml`, `snapshot/raw/SHA256SUMS` and `lineage/frozen/SHA256SUMS`; it raises `LockError` if any required file is missing. `lock.check(root)` raises `LockError` unless every hash matches, the manifest holds every required key, every file under `lineage/frozen/` and `snapshot/raw/` matches its SHA256SUMS with no unlisted files, and `git show prereg-v1:docs/prereg-manifest.json` equals the working copy.
- `dataset.build` raises if a benchmark's `parents.json.gz` or `missing.json` is absent, and verifies them against `lineage/frozen/SHA256SUMS`.

### Track E2: models and simulation (AT13, AT14)

Owns: `analysis/models.py`, `analysis/simulate.py`, `tests/test_models.py`, `tests/fixtures_models.py`.

- `models.cond_logit(df, outcome, treatment, covariates, group) -> Estimate(log_or, se, n, n_groups_informative, method)`: conditional logistic regression stratified by group (statsmodels ConditionalLogit). If separation or non-convergence is detected, fall back to Firth-penalised unconditional logistic regression with group fixed effects, and set method="firth".
- `models.meta_hksj(estimates) -> Pooled(log_or, ci95, ci90, tau2, tau2_ci, k)`: DerSimonian-Laird tau², then the Hartung-Knapp-Sidik-Jonkman variance with a t distribution on k-1 df (untruncated q). tau2_ci by the Q-profile method.
- `models.tost(log_or, ci95, ci90, margin) -> verdict` in {"effect detected", "equivalent to no effect", "inconclusive"}: "effect detected" when ci95 excludes 0 (takes precedence); "equivalent" when ci90 lies inside log(margin); otherwise "inconclusive". Intervals are passed, never derived.
- `models.holm(pvals: dict) -> dict` of adjusted p-values.
- `models.permutation_share(df, label, flag, strata, draws=10000, seed=...) -> (observed, p_two_sided)` for H3.
- `models.median_reg(df, outcome, treatment, covariates, cluster, boot=2000, seed=...) -> Estimate` (quantile regression at 0.5 with cluster bootstrap) for H4.
- `simulate.plant(df_treatment, odds_ratio, base_rate, icc, seed) -> df with a synthetic outcome`, preserving the real treatment, solver and week structure.
- AT13: across 100 seeds, a planted OR of 1.5 falls inside the 95% interval in at least 90 seeds; at OR 1.0 the equivalence decision behaves as simulated power predicts. AT14: shuffling family within solver gives an H1 interval covering 1 in at least 90 of 100 seeds.

### Track E3 (after E1 and E2): confirmatory and secondary drivers, numbers

Owns: `analysis/confirmatory.py`, `analysis/secondary.py`, `analysis/exploratory.py`, `analysis/figures.py`, `analysis/numbers.py`, `docs/prereg.md`, `tests/test_drivers.py`.

## Wave 4

- Track F paper (AT7, AT8, AT10, AT11, AT12): `paper/`, `cases/`, `README.md`.
