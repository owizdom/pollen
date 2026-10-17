# Spec 0001: Does cross-model pollination help open autoresearch?

- Status: v1 APPROVED 2026-10-17; v2 (review fixes, §16) with decisions D-A and D-B APPROVED by Wisdom Okechukwu, 2026-10-17.
- Owner: architect (Claude Opus 5.5)
- Author of record: Wisdom Okechukwu
- Repo: `~/Desktop/code/pollen` (local only, nothing committed or pushed)

## 0. Question and context

On 16 Oct 2026, Sreeram Kannan posted that ecdsa.fail participants beat Anthropic's Claude-only circuit search on the same point-addition task. The 843-qubit point he quoted came from jieyilong running GPT-5. Kydo replied that it is "a good case study of how cross modal pollination might produce better results."

The ecdsa.fail paper (arXiv:2609.09582v2) makes the same claim in prose, at four places:

- §4.1: "Independent branches using different models, tools, backgrounds, and objectives also make the search resilient to plateaus."
- §4.3.2: agents "from different model families (e.g. GPT, Claude, Grok, GLM, and Kimi) sometimes reviewed one another's conclusions", and watcher agents "enabled rapid cross-pollination without collapsing the search onto a single trajectory."
- §4.3.3: "apparent plateaus were repeatedly broken by existing or newly joined contributors using different models, tools, expertise, or circuit families."
- §5.4.1: "several plateau-ending advances came from participants other than those responsible for the preceding improvements."

The same paper states in §6 that its record cannot "establish that one model, prompting strategy, or collaboration structure caused a given frontier movement." Its supplement (`jieyilong/ecdsafail-supplemental-materials` @ `ef7ecd2`) has no model column in any data file. Note C still carries an open author note to gather the Claude and Codex sessions.

The question: when one participant builds on another participant's work, does it matter whether the two used models from different vendors?

The data exists to answer it. Every Yukon submission carries a declared model, a public note, and usually a public code commit. Many October submissions also declare their parents through a structured attribution endpoint. ecdsa.fail has 1,586 submissions, 1,441 with a `Model:` line (probe of 17 Oct). Other Yukon benchmarks hold thousands more.

## 1. Objective

Done means all of the following exist and pass their acceptance tests.

1. A public-ready repository, `pollen`, that rebuilds every number and figure-data file in the paper offline from a frozen snapshot with one command.
2. A per-submission dataset for every study benchmark: declared family, harness, parents, treatment cell, and sealed outcomes.
3. A pre-registration frozen under the git tag `prereg-v1`, covering the analysis text, the analysis code, the family table, the lineage rules and the snapshot checksums. The tag's commit hash is timestamped externally. The confirmatory script refuses to run against any other version.
4. A primary result (§5.1) reported as an odds ratio with a 95% interval, plus an equivalence verdict from 90% intervals, so that a null result is a finding.
5. Per-benchmark results for every study benchmark.
6. A research paper, single author "Wisdom Okechukwu", that reports the result whatever its sign. Every number in it comes from a generated macro file.

## 2. Non-goals

- No ranking of models by capability. A descriptive table of submissions per family is fine.
- No causal claim beyond what the design identifies. §6 lists what the design cannot rule out.
- No new circuits or benchmark submissions.
- No human-versus-AI comparison.
- No private data: no agent transcripts, no Yukon traces, no chat channels. Public API fields, public notes and public commits only.
- No per-person results. Solver identity is a control, never a reported outcome.
- No use of the Anthropic comparison as evidence. It motivates the introduction, with its interface caveats.
- No correction of the ecdsa.fail paper. This work tests claims that paper makes.
- No mechanism-census analysis. The census in Note C covers only accepted commits in one window and cannot be joined cleanly to submissions (dropped in v2, review F18).

## 3. Definitions

### 3.1 Units, snapshot, denominator

- Unit: one submission to one study benchmark.
- Snapshot: for every benchmark the API lists, the benchmark object and its submissions, fetched once from `https://api.yukon.org` without credentials, stored as gzipped JSON with SHA-256 sums and a `FREEZE.json` of fetch time and row counts. For study benchmarks the snapshot also holds each submission's attribution record (`/api/submissions/{id}/attribution`). The tree manifests and distance table from §3.3 are frozen separately under `lineage/frozen/` with their own checksums.
- Analysis rows: submissions that were evaluated. Dropped before any analysis: cancelled rows, rows not yet final (status `validating` or similar), rejections never scored, and failures caused by infrastructure rather than by the submission. Each failure reason is classed in `outcomes/denominator.yaml` as evaluated (kept), infrastructure (dropped, for example rate limits, interrupted validation jobs, dispatch or token errors, invalid state transitions) or ambiguous (kept; sensitivity 9 drops them). A failed row with no reason is ambiguous. A failure caused by the submission's own packaging (for example an over-long pull-request body) counts as never evaluated. On ecdsa.fail those reasons are "claimed score did not improve" (a pre-filter on the solver's own claim), "does not contain code change", and packaging errors. `families/` does not decide this list; `outcomes/denominator.yaml` holds the exact reason strings per benchmark, locked at `prereg-v1`.
- Confirmatory window (review F2): commit availability must not depend on outcome. On ecdsa.fail, 322 of 632 accepted rows lack `submissionCommitSha`, against 163 of 721 rejected, mostly in June. Every promoted row has `promotedSourceRef`, a commit on the benchmark's main history, so promoted trees are recoverable. The window for each benchmark starts at the first calendar week after which, through the freeze, the share of analysis rows with a recoverable tree differs by at most 5 percentage points between promoted and other rows. Rows before the window are reported descriptively only.

### 3.2 Model family and harness

- Declared model: the text after `Model:` on the first non-empty line of the note. The Yukon CLI writes it from the required `--model` flag.
- Family: the vendor of the declared model, from the checked-in table `families/table.yaml` (exact string to family).
- Multi-family: a `Model:` line naming two or more vendors (about 32 on ecdsa.fail, for example "Claude Opus 5.5 + GPT-6.1 Sol"). Multi-family rows are excluded from confirmatory tests and analysed in E1.
- Company-model rule: a model a company names as its own maps to that company, as `Other:<company>` when the company is not a listed vendor (SWE-2 Other:Cognition, Composer Other:Cursor, Doubao Other:ByteDance, Poolside Other:Poolside). A string naming a model family maps to that family's vendor ("Grok Bot" is xAI).
- Unknown: missing line, an agent product or harness with no model ("Devin", "Droid", "Codex", "Codex CLI"), a vendor-ambiguous name ("Astra"), or junk ("benchmark", "Scikit-learn", flags). Excluded from confirmatory tests; sensitivity 1 restores them.
- Sparse families: a family with fewer than 30 analysis rows on a benchmark folds into "Other" for that benchmark's models (review F14).
- Harness: the `Harness:` line when present (480 rows on ecdsa.fail). Recorded for sensitivity 6, because harness and family are nearly collinear (Codex and OpenAI).

### 3.3 Parents

A submission's parents are the earlier submissions it built on. Sources, in order of precedence:

1. Declared attribution: the structured `dependencies` of the attribution record. One dependency gives a single parent. Two or more give a multi-source row, analysed in E1 and excluded from confirmatory tests.
2. Tree distance: the earlier analysis row whose editable-path tree has the fewest changed lines against the child's tree, where changed lines are the added plus removed text lines of `git diff --numstat --minimal --no-renames` restricted to the editable paths. A changed binary file counts as 1. Ties go to the most recent, then by id. Candidates: rows whose tree exists, collapsed by tree identity (keeping the most recent), then the last 50 rows promoted before the child was created plus the child solver's last 50 earlier rows.
3. Novel: when the child-side differing lines (text lines present in the child but not in the nearest tree) exceed half of the child's text lines, the row has no parent. Binary files do not count toward size. Novel rows are excluded from H1 and H2 and reported descriptively. The paper shows the distance distribution split by outcome.

The tree-distance parent is computed for every row, including rows with declared attribution, so that AT4 and sensitivity 2 can compare the two. The primary parent is the declared one when it exists. Declared dependencies are de-duplicated in order; ids that are unknown or not earlier are dropped and the drop is recorded.

Trees come from `promotedSourceRef` for promoted rows and `submissionCommitSha` otherwise, fetched by SHA, never by branch name. On ecdsa.fail all 1,012 non-null `submissionCommitSha` values match a branch tip under `refs/heads/submissions/*`. `lineage/frozen/` holds the tree manifests (path to blob hash) and the computed distance table with SHA-256 sums, so the rebuild runs offline (review F8). The eip8200 pair shares one repository; trees are split by benchmark id.

Validation (AT4) compares the treatment cell, not the parent id. Two labelled sets exist: declared attribution edges, and the notes that name a base in text (142 on ecdsa.fail, five solvers write most of them).

### 3.4 Treatment cells

- Cross-solver: the parent was submitted by a different solver.
- Cross-family: parent family differs from child family, both known and single-family.
- Four cells: own lineage with the same family, own lineage with a switched family, someone else's work in the same family, someone else's work in another family.
- The primary contrast holds "someone else's work" fixed and varies only the family. Solver fixed effects (§5.1) compare each solver's cross-family attempts with that same solver's same-family attempts, which removes stable solver skill from the contrast. This separates model pollination from people pollination, which the ecdsa.fail paper's §5.4.1 conflates.

### 3.5 Outcomes

Outcome columns are sealed until `prereg-v1` exists (§5.8).

- Y1, promotion: `promotionStatus == "promoted"`, per analysis row. The 4 ecdsa.fail rows with status `accepted` and promotion `failed` count as not promoted.
- Y2, Pareto gain (ecdsa.fail only): the row has valid (Q, T), no earlier valid row dominates it, and no earlier valid row has the identical (Q, T).
- Evaluation order: rows are ordered by the time their evaluation finished (`promotionFinishedAt`, else `updatedAt`), not by creation time, because promotions can finish out of creation order. "Earlier" in every outcome definition of this section, Y2 and plateau breaks included, means earlier in evaluation order. Only rows with status accepted or rejected can promote or move the running best; failed rows cannot. The named exception classes are rows whose promotion status is `failed` or `superseded`; any other accepted row that is not promoted is not final and is dropped. The best score before a row is the best promoted score, seeded with the benchmark's `baselineScore`, among rows that finished earlier. Rows with `promotionStatus == "superseded"` are a named exception class.
- Y3, gain size: for promoted rows, the log ratio of the best score before the row to its score, signed so larger is better under the benchmark's direction.
- Large jump: a promotion in the top decile of Y3 within its benchmark.
- Plateau break: a promotion gaining at least 1% after at least 72 hours with no promotion gaining 1% or more. The window starts at the benchmark's opening time. "Gaining 1%" means the score improves by at least 1% of the best before it in the benchmark's direction (lower: score at most 0.99 times the best; higher: at least 1.01 times).
- Promotion threshold: the API field `minScoreImprovementBips` differs between benchmarks (for example 100 on `flock-challenge-multi/x86` and 10 on `davidtai/qwen38-125b-a6b-cuda-v1`). Recomputation applies it. On `flock-challenge-multi/x86` every row that disagrees on 17 Oct predates 25 Aug 2026, the date of its first "fell short of the required 100 bips" rejection, so the threshold appears to have started mid-benchmark. The replication table names the field and states whether AT5 reproduces each benchmark's promotions.

## 4. Hypotheses (pre-registered)

- H1 (primary): among cross-solver single-parent rows, cross-family rows have different odds of promotion (Y1) from same-family rows.
- H2: among own-lineage rows, a family switch changes the odds of promotion.
- H3a: among cross-solver promotions, large jumps are cross-family more often than other promotions.
- H3b: the same for plateau breaks.
- H4: among cross-solver promotions, gain size (Y3) differs between cross-family and same-family steps.
- H5 (ecdsa.fail): among cross-solver rows, cross-family rows differ in Pareto gain (Y2).
- E1 (exploratory): multi-family and multi-source rows differ from single-family, single-parent rows on Y1 and Y3.
- E2 (exploratory): the H1 effect varies over the life of a benchmark (thirds of its analysis rows).

Every hypothesis is two-sided.

## 5. Analysis plan (pre-registered)

### 5.1 Primary estimand and model

Decided (D-A): the primary result is H1 pooled across all study benchmarks, ecdsa.fail included. Each benchmark contributes a log odds ratio from the model below; a random-effects meta-analysis with the Hartung-Knapp-Sidik-Jonkman correction pools them and reports τ² with its interval. ecdsa.fail's own H1 is the headline case study, reported with its own verdict, and is a secondary test.

Per-benchmark model: conditional logistic regression of Y1 on the cross-family indicator, stratified by solver (solver fixed effects), among cross-solver single-parent rows with both families known, inside the confirmatory window. Covariates:

- calendar-week fixed effects;
- child-family and parent-family fixed effects (after sparse-family folding);
- an indicator that the parent was the current best at the time of the row;
- log of the solver's prior analysis rows.

Rows from solvers with no variation in treatment drop out of a conditional model by construction; the paper reports how many. If the model shows separation, Firth's penalised likelihood replaces it, and the paper says so.

### 5.2 Equivalence

Equivalence uses two one-sided tests at α = 0.05, which means checking whether the 90% interval of the odds ratio lies inside the margin. The margin is [0.80, 1.25] (Wisdom, 17 Oct). The verdict is one of: effect detected, equivalent to no effect, or inconclusive. The paper uses those words.

### 5.3 Power gate before the lock

Run from treatment counts only, never outcomes, before `prereg-v1`.

- Compute equivalence power at a true odds ratio of 1, with a design effect from solver clustering, for the primary estimand.
- Decided (D-A): if that power is below 80%, widen the margin to [0.67, 1.50] and state the reason in `docs/prereg.md` before the tag. Review F1 showed that on ecdsa.fail alone, even before clustering, 1.645 × SE ≈ 0.226 exceeds log 1.25 ≈ 0.223, so a single-benchmark verdict there is close to guaranteed "inconclusive".
- Minimum events (review F12): a secondary test runs as confirmatory only when its smaller arm has at least 20 events. Below that it is reported descriptively and leaves the Holm family. On ecdsa.fail H3b has about 5 plateau breaks, so it will likely be descriptive.

### 5.4 Secondary tests and corrections

- H2: the primary model restricted to own-lineage rows.
- H3a, H3b: permutation tests, 10,000 draws, shuffling family labels among cross-solver promotions within calendar-week strata (review F4).
- H4: median regression of Y3 on the cross-family indicator with week fixed effects; bootstrap interval clustered by solver.
- H5: the primary model with Y2 as the outcome, ecdsa.fail only.
- One Holm family holds every secondary test that passes the minimum-events gate, each benchmark's test as its own member (review F11).
- E1 and E2 are reported without correction, labelled exploratory.

### 5.5 Sensitivity analyses (fixed in advance)

1. Unknown family as its own family instead of excluded.
2. Tree-distance parents only, ignoring declared attribution. This is a different estimand (the immediate code parent rather than the declared origin), reported as such.
3. Drop rows whose note says only a nonce or validation draw changed.
4. Family coarsened to Anthropic, OpenAI and other.
5. Drop the first 72 hours of each benchmark.
9. Drop rows whose failure reason is classed ambiguous.
6. Add harness fixed effects.
7. Drop the author's own rows (solver `owizdom`, 5 rows on ecdsa.fail) (review F16).
8. Sibling benchmarks: pooled result with each sibling pair reduced to one member (flock pair; eip8200 pair).

### 5.6 Study benchmarks

Decided (D-B): ecdsa.fail plus every benchmark, open or closed, that meets all of the following at freeze, applied to the frozen snapshot:

- at least 500 analysis rows and at least 100 promoted;
- at least two families, each with at least 10% of labelled rows;
- tree commits fetchable from a public repository.

At the 17 Oct probe of open benchmarks, five qualified: `eigenlabs/sig-golf/full`, `eigenlabs/flock-challenge`, `eigenlabs/flock-challenge-multi/x86`, `eigenlabs/eip8200-challenges/modexp`, `eigenlabs/eip8200-challenges/ripemd160`. Counting closed benchmarks on 17 Oct, four more qualified: `eigenlabs/lighter-prover-challenge`, `davidtai/qwen38-125b-a6b-cuda-v1`, `davidtai/mlxfast-gemma4-26b-a4b`, `eigenlabs/mlxfast-challenge`. The freeze re-applies the rule; these lists are not binding.

### 5.7 What has already been seen

The analysis is not blind. Before the lock, the following were computed.

- The ecdsa.fail leaderboard frontier and its low-qubit Pareto points (author, 16 Oct).
- A crude H4 on ecdsa.fail, parent = previous promotion (author, 16 Oct). Family switch: 253 steps, median gain 0.063%, mean 0.306%. Same family: 302 steps, median 0.055%, mean 0.314%.
- A crude H3: 16 of 31 top-50 drops with known families switched, against a 46% base rate (author, 16 Oct).
- Counts of submissions, promotions and declared families on all API-listed benchmarks (author, 17 Oct). No outcome was split by family on any benchmark except ecdsa.fail.
- A crude H1 and H2 promotion-rate split on ecdsa.fail, parent = frontier holder at creation, computed by the fresh-context reviewer on 17 Oct. The numbers were withheld from the author and are not in this repository.

These hint at no effect on ecdsa.fail. The paper repeats this disclosure.

### 5.8 Lock and sealing (review F7)

- `outcomes/` writes outcome columns to `outcomes/sealed/` only. `analysis.dataset()` joins them only inside `confirmatory.py`, after the lock check passes.
- AT5 checks outcomes against the API and reports pass or fail, never the values split by treatment.
- `prereg-v1` locks a manifest, `docs/prereg-manifest.json`, holding the SHA-256 of `docs/prereg.md`, every file under `analysis/`, `lineage/`, `families/table.yaml`, `outcomes/denominator.yaml`, `snapshot/raw/SHA256SUMS` and `lineage/frozen/SHA256SUMS`.
- The tag's commit hash is stamped with OpenTimestamps on the day of the tag, and the `.ots` proof is committed. No account or upload of content is needed.

## 6. Threats the design cannot remove

- Self-selection: participants choose their parents and models. Solver fixed effects remove stable solver traits; they do not remove choices that vary within a solver, such as picking a model for a harder problem.
- Self-declared labels: the `Model:` line is what the solver typed. AT3 measures agreement with the note body.
- Missing attempts: the API holds only submitted work (the ecdsa.fail paper's §6 makes the same point). Y1 is promotion per evaluated submission, never per attempt.
- Dependence between rows: resubmissions of one idea, shared parents, and sibling benchmarks. Sensitivity 8 covers the siblings.
- One platform: every benchmark runs on Yukon, though promotion thresholds differ between benchmarks (§3.5).
- Conflict of interest: the author is solver `owizdom` on ecdsa.fail (5 submissions, 3 promoted, 2 Jun 2026) and a listed author of arXiv:2609.09582. The paper discloses both; sensitivity 7 drops his rows.
- Reviewer independence: AT10 uses Claude reviewers, who share weights with the writer. Agreement among them counts as one opinion. The paper invites outside statistical review.

## 7. Repository layout

```
pollen/
  README.md            result first, then how to rebuild it
  Makefile             make snapshot | labels | lineage | outcomes | analysis | paper | reproduce | check
  pyproject.toml       Python 3.12, pinned deps
  snapshot/            fetch.py, load.py, model.py, raw/ (gzipped JSON, attribution, trees manifests, SHA256SUMS, FREEZE.json), FREEZE.md
  families/            table.yaml, mapper.py, audit/
  lineage/             trees.py, distance.py, parents.py, declared.py, frozen/ (manifests, distances, SHA256SUMS)
  outcomes/            denominator.yaml, promotion.py, frontier.py, pareto.py, jumps.py, sealed/
  analysis/            dataset.py, power.py, confirmatory.py, secondary.py, exploratory.py, simulate.py, figures.py, numbers.py
  cases/               source-backed case studies
  paper/               main.tex, numbers.tex (generated), figures/ (generated), refs.bib
  docs/                specs/, prereg.md, prereg-manifest.json, TASKS.md, JOURNAL.md, DEVIATIONS.md
  tests/               one module per domain folder
```

## 8. Seam contract

```
snapshot.load(benchmark: str) -> list[Submission]
    # Submission(id, benchmark, solver, created_at, status, promoted: bool, cancelled: bool,
    #   score: float | None, metrics: dict, note: str, model_line: str | None,
    #   commit_sha: str | None, rejection_reason: str | None, submission_sha, promoted_ref,
    #   promotion_status: str | None, finished_at: datetime | None)
snapshot.benchmark_meta(benchmark: str) -> Benchmark
    # Benchmark(id, name, slug, direction: "lower" | "higher", editable_paths, source_url,
    #   opened_at, min_improvement_bips: int | None, baseline_score: float | None)
snapshot.attribution(benchmark: str) -> dict[str, list[str]]     # submission id -> declared parent ids
families.family_of(model_line: str | None) -> Family | Multi | Unknown
families.harness_of(note: str) -> str | None
lineage.parents.parents(child, earlier, attribution, trees, own_history, mirror, paths, ids=None, memo=None) -> ParentResult
    # earlier and own_history are analysis rows; declared ids are checked against all snapshot rows
    # ParentResult(primary: ParentLink, tree: ParentLink, dropped_declared: tuple[str, ...])
    # ParentLink(parent_ids, method: "declared" | "multi" | "tree" | "novel" | "none", distance, child_side)
lineage.build.run(benchmark) -> writes lineage/frozen/<slug>/{manifests,distances,parents}.json.gz, missing.json
lineage.declared_base(note: str) -> str | None   # submission-id prefix, promotedSourceRef, or commit SHA
outcomes.annotate(subs, meta) -> sealed table (written to outcomes/sealed/, not returned to analysis)
analysis.dataset(benchmark: str) -> pandas.DataFrame   # treatment and covariates; outcomes only after lock check
analysis.numbers.write(path="paper/numbers.tex")
```

## 9. Acceptance tests

T means automated. L means a live run recorded in `docs/JOURNAL.md`.

| # | Test | Type | Passes when |
|---|---|---|---|
| AT1 | Snapshot integrity | T | Every frozen file matches `SHA256SUMS`; row counts equal `FREEZE.json`; the loader works with the network disabled. |
| AT2 | Family table complete | T | Every distinct `Model:` string maps to a family, Multi or Unknown. Golden cases pass: "GPT-5 Codex" OpenAI; "Claude Opus 4.8 (1M context)" Anthropic; "Kimi K3" Moonshot; "Devin" Unknown; "Astra" Unknown; "Claude Opus 5.5 + GPT-6.1 Sol" Multi; "Grok 4.6 + Kimi k3" Multi. |
| AT3 | Label audit | L | A seeded sample of 200 notes is scored by a fresh-context reviewer as agree, contradict or silent. Among non-silent notes, agreement is at least 95%. Wisdom spot-checks 20. |
| AT4 | Treatment validity | T | Against declared attribution edges and against text-declared bases separately, the inferred treatment cell (cross-solver by cross-family) agrees in at least 85% of rows. Agreement is reported for frontier and non-frontier parents. Golden tests cover all three `declared_base` id formats. |
| AT5 | Outcome recomputation | T | On every study benchmark, Y1 recomputed in evaluation order from the baseline-seeded running best agrees with `promotionStatus` on every analysis row except named exception classes (accepted-but-failed promotions, superseded). A benchmark above 1% disagreement is reported as "promotion rule not reproduced" in the paper; Y1 still comes from `promotionStatus`. Reports pass, fail and counts only. |
| AT6 | Lock | T | `confirmatory.py` exits non-zero unless every hash in `docs/prereg-manifest.json` matches the working tree and the manifest is unchanged since tag `prereg-v1`. |
| AT7 | No hand-typed results | T | The paper builds only if every number macro is defined in `numbers.tex`; a lint finds no numeric literals in results sections outside macros, citations and an allowlist. |
| AT8 | Offline rebuild | L | A fresh clone with the network disabled runs `make reproduce` and regenerates `numbers.tex` and every figure-data file byte-identical. Figures render with fixed metadata and fonts. |
| AT9 | Tripwire | T | `make check` fails when pytest collects zero tests or skips any. |
| AT10 | Independent review | L | A fresh Opus 5.5 reviewer and a separate verifier trace every claim in the abstract and conclusion to `numbers.tex` or a cited source, with no in-scope confirmed finding. |
| AT11 | Byline | T | The paper's author block is exactly "Wisdom Okechukwu", with no affiliation. "Free Systems" and "Stanford" appear nowhere in `paper/`. The repo URL is allowlisted. |
| AT12 | Prose | T | `prose-check.py` passes on README.md and the paper's extracted text. |
| AT13 | Planted effect | T | On simulated data with the real treatment structure, the pipeline recovers a planted odds ratio of 1.5 inside its 95% interval in at least 90 of 100 fixed seeds (a correct 95% interval falls below 93 of 100 with probability about 0.12 and below 90 with probability about 0.03, Binomial(100, 0.95)). At an odds ratio of 1.0 the equivalence test behaves as designed (review F17). |
| AT14 | Placebo | T | Shuffling family within solver gives an H1 interval covering 1 in at least 90 of 100 fixed seeds. |
| AT15 | Window balance | T | Inside each confirmatory window, recoverable-tree share differs by at most 5 points between promoted and other rows (review F2). |

GitHub Actions is billing-blocked on this account. `make check` is the gate, run locally and recorded with its commit SHA in the JOURNAL.

## 10. Tracks

| Track | Owns | Depends on | AT |
|---|---|---|---|
| A snapshot | `snapshot/`, `tests/test_snapshot.py`, `tests/conftest.py` | none | AT1 |
| B families | `families/`, `tests/test_families.py` | A | AT2, AT3 |
| C lineage | `lineage/`, `tests/test_lineage.py` | A | AT4, AT15 |
| D outcomes | `outcomes/`, `tests/test_outcomes.py` | A | AT5 |
| E analysis | `analysis/`, `docs/prereg.md`, `docs/prereg-manifest.json`, `tests/test_analysis.py` | B, C, D | AT6, AT9, AT13, AT14 |
| F paper | `paper/`, `cases/`, `README.md` | E | AT7, AT8, AT10, AT11, AT12 |

Waves: A; then B, C, D in parallel; then E; then F. Implementers on Sonnet, reviewers and verifiers on Opus 5.5.

## 11. Milestones

| # | Milestone | Exit condition |
|---|---|---|
| M1 | Freeze | Snapshot, attribution records, tree manifests and distance tables frozen; AT1 green. |
| M2 | Dataset | AT2, AT4, AT5, AT15 green; AT3 recorded. Outcomes sealed. |
| M3 | Lock | Power gate run; AT13 and AT14 green; `docs/prereg.md` and manifest written; Wisdom approves; tag `prereg-v1`; OpenTimestamps proof committed. |
| M4 | Results | Confirmatory and secondary analyses run once; outputs committed. |
| M5 | Paper | Draft complete; AT7, AT8, AT11, AT12 green. |
| M6 | Review | AT10 loop closed under the groundtruth scope gate. |
| M7 | Publish | Wisdom's go: repo public, arXiv submission. |

Any change to §3 to §5 after M3 goes into `docs/DEVIATIONS.md` with date and reason, and the paper reports it.

## 12. Paper outline

Working title: "Does Cross-Model Pollination Help Open Autoresearch? Evidence from Yukon Leaderboards." Single author: Wisdom Okechukwu. Target 12 to 16 pages plus appendix; arXiv cs.AI with a cs.SE cross-list.

1. Introduction: the 16 Oct exchange, the ecdsa.fail paper's four prose claims, the question.
2. Setting: Yukon, promotion rules, the study benchmarks.
3. Data and measurement: snapshot, labels and audit, parents and validation, outcomes, window.
4. Pre-registered design, with the §5.7 disclosure and the conflict-of-interest statement.
5. Results: the primary estimate, then ecdsa.fail as the headline case.
6. Per-benchmark results and sensitivity analyses.
7. Case studies: the 843-qubit lineage across GPT-5 and Claude Opus 5.5 with a GPT-6 Sol sub-agent; the ping-pong divider; the largest single drop.
8. Threats to validity.
9. Discussion: what the result means for running open autoresearch, and what a platform would need to log to answer the causal version.

## 13. Pre-mortem: "the paper came out and failed; why?"

| # | Failure | Mitigation |
|---|---|---|
| 1 | The result is null and reads as a swipe at Kydo and the ecdsa.fail authors. | A question title, an equivalence verdict, framing as a follow-up test by one of that paper's authors. |
| 2 | Reviewers say the effect is the person, not the model. | Cross-solver contrast plus solver fixed effects (§5.1); H2 within solver. |
| 3 | Labels are noise. | Exact-string table, Multi and Unknown by rule, audit (AT3), sensitivities 1, 4 and 6. |
| 4 | Treatment is mislabelled. | Declared attribution first, novel cutoff, AT4 on the treatment cell. |
| 5 | Missing commits bias the sample. | Confirmatory window and AT15. |
| 6 | One benchmark, no generality. | Pooled primary across rule-selected benchmarks. |
| 7 | Forking paths. | Code and prose locked, outcomes sealed, external timestamp, §5.7 disclosure. |
| 8 | Inconclusive by construction. | Power gate with a pre-committed action (§5.3), minimum-events gate. |
| 9 | The estimator is wrong and nobody notices. | Planted-effect and placebo tests (AT13, AT14). |
| 10 | The rebuild breaks when branches move. | Trees and distances frozen; offline rebuild (AT8). |
| 11 | The author's stake undermines trust. | Disclosure and sensitivity 7. |
| 12 | It grows into a platform. | One snapshot, one dataset, one paper; no service, no dashboard. |

## 14. Rollout, rollback, removal

- Rollout: local and private through M6. At M7, with Wisdom's go, public at `owizdom/pollen` and on arXiv.
- Rollback: before M7, delete the repo. After M7, set it private and withdraw or replace the arXiv version.
- Removal: nothing temporary ships. `snapshot/fetch.py` stays so others can extend the study.

## 15. Decisions

Made by Wisdom, 2026-10-17: spec approved; margin [0.80, 1.25]; replication by the §5.6 rule; MIT licence; no advance notice to Eigen.

Made by Wisdom, 2026-10-17, after the v2 review:

- D-A: the primary is H1 pooled across all study benchmarks (HKSJ random effects); ecdsa.fail is the headline secondary. The margin widens to [0.67, 1.50] only if the pre-lock power gate fails.
- D-B: closed benchmarks that meet the §5.6 rule join the study.

## 16. Revision log

v2, 2026-10-17, after a fresh-context Opus 5.5 review (18 findings, 17 in scope). Changes by finding: F1 power gate and 90% interval wording (§5.2, §5.3); F2 confirmatory window and promoted trees from `promotedSourceRef` (§3.1, AT15); F3 solver fixed effects and corrected §6; F4 H3 restricted to cross-solver promotions; F5 declared attribution, novel cutoff, multi-source rows (§3.3); F6 AT4 on the treatment cell with two labelled sets; F7 code lock, sealed outcomes, external timestamp (§5.8); F8 frozen trees and distances, offline rebuild; F9 Multi and harness (§3.2, sensitivity 6); F10 promotion thresholds and the eip8200 sibling pair; F11 Holm membership and HKSJ; F12 minimum events; F13 denominator and real recomputation in AT5; F14 sparse families and Firth; F15 AT11 allowlist; F16 conflict of interest; F17 AT13, AT14 and the three-way audit. F18 (scope trims, out of scope): the mechanism-census analysis is dropped; H5 and E2 stay subject to the minimum-events gate.

v2.1, 2026-10-17, after the Track D review (architect decisions, pre-lock): evaluation-order frontier seeded with `baselineScore`; superseded rows as a named exception class; 1% defined as a relative score change; plateau window from opening; three-way failure classes with sensitivity 9; identical Pareto points are not gains; the false flock-multi threshold sentence corrected; AT5 across all study benchmarks.

v2.2, 2026-10-17, after the Track C review (architect decisions, pre-lock): git minimal numstat as the distance, binary files as one changed line and excluded from size; the novel test uses child-side lines; tree parents computed for every row; candidate window filtered and collapsed before slicing, promotions counted only if finished before the child was created, own history capped at 50; declared dependencies de-duplicated and validated; seam renamed to `lineage.parents.parents` returning both links; a build driver writes the frozen lineage outputs.

v2.3, 2026-10-17, after the Track D re-review (architect rulings, pre-lock): failed rows cannot promote; exception classes limited to promotion status failed or superseded; evaluation order applies to Y2 and plateaus; empty failure reasons are ambiguous; submission packaging failures are never-evaluated; the promotion-threshold sentence corrected (qwen38-cuda 10; flock-multi threshold began about 25 Aug).

v2.4, 2026-10-17: AT13 and AT14 thresholds set to 90 of 100 fixed seeds, because 93 of 100 fails a correct estimator about 12% of the time.
