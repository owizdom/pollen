# Journal

## Snapshot

- Phase: M1 (freeze), Wave 1 Track A in progress.
- Spec 0001 approved 2026-10-17 with five replication benchmarks, MIT, no advance notice to Eigen, margin [0.80, 1.25].
- Nothing committed yet; every commit needs Wisdom's go.
- Spec review by a fresh-context Opus reviewer is running; findings land here.
- Next: freeze the snapshot, then Wave 2 (families, lineage, outcomes) in parallel.

## Evidence (append-only)

### 2026-10-17

- Duplication check: arXiv:2609.09582v2 read in full. Cross-pollination appears only as prose in §4.1, §4.3.2, §4.3.3 and §5.4.1. §6 disclaims model attribution. The supplement repo (`jieyilong/ecdsafail-supplemental-materials` @ `ef7ecd2`) has no model column; Note C line 8 holds an open TODO to gather Claude and Codex sessions.
- Data probe: `yukon submissions gpsanant/ecdsafail-challenge --all --json` returned 1,586 rows, 1,441 with a `Model:` line, 628 promoted.
- Submission refs: `git ls-remote` counts under `refs/heads/submissions/` were ecdsafail-challenge 1,016, sig.golf 920, flock-challenge 4,625, eip8200-challenges 2,942.
- `GET https://api.yukon.org/api/benchmarks/{id}/submissions` is public: 1,586 rows for ecdsa.fail, field set identical to the CLI output.
- Disclosed peek (spec §5.7): crude H4 and H3 on ecdsa.fail showed no visible effect.
- Model of record for this session: Claude Opus 5.5 (architect).
- Spec review (fresh-context reviewer agent, model Opus 5.5 `claude-opus-5-5`): 18 findings, 17 in scope, verdict "needs rework before the M3 lock". Key verified counts: accepted rows without `submissionCommitSha` 322/632 vs rejected 163/721; 25 multi-family solvers hold 861 of 1,583 non-cancelled rows; TOST arithmetic 1.645 × 0.137 = 0.226 > log 1.25 = 0.223 on ecdsa.fail alone; `flock-challenge-multi/x86` has `minScoreImprovementBips: 100`; attribution endpoint "provided" on 24 of 80 sampled rows. The reviewer computed a crude H1/H2 outcome split and withheld it from the author; disclosed in spec §5.7.
- Spec v2 written, folding in F1 to F17; F18 trims applied (census analysis dropped). Two decisions open: D-A primary estimand, D-B closed benchmarks.
- `GET /api/benchmarks` lists 48 benchmarks including closed ones; total raw submissions JSON about 631 MB, 172 MB gzipped. `yukon benchmark list` shows open benchmarks only.
- Track A test-writer (Sonnet, `claude-sonnet-5-5`): 13 tests, 13 failing on `ModuleNotFoundError: snapshot.load` (red state confirmed by `uv run pytest`). Being extended for v2 fields.
- First real freeze attempt crashed at `eigenlabs/sig-golf/full` on an attribution 404 (submission 372ca131, a rejected no-code row; cancelled rows also 404). 16 benchmark dirs written, no FREEZE.json; the partial snapshot is not used.
- Track A review (fresh-context reviewer, Opus 5.5 `claude-opus-5-5`): 9 in-scope findings (7 CONFIRMED, 2 PLAUSIBLE): 404 crash; `--resume` drops attribution; `benchmark_meta` KeyError on real `slug`-less API objects (fixture invented the field); listed-but-missing files load silently; FREEZE.json unchecksummed; attribution rate limit is 120/min vs 480/min fired; cursor pages can duplicate parents; `--only` shrinks FREEZE.json; FREEZE.md never written. Regression tests requested from the Track A test-writer before fixes. Attribution scope narrowed to the study benchmarks (about 31,500 calls, about 4.5 h at the limit).
- Track B families (Sonnet): 49/50, the remaining AT2 test needs the frozen snapshot. Table has 91 entries. Architect correction: bare "Daybreak Blue" to Unknown (no vendor evidence in notes); Muse Spark stays Meta; SWE-2 stays Other:Cognition.
- Track C lineage (Sonnet): 25/25 after one fix (digit rule wrongly applied to full SHAs and UUIDs). The implementer's first report came back empty ("placeholder"); state checked directly with pytest.
- Track D outcomes (Sonnet): 33/35. One test was self-contradictory (expected [True, False, True] where time order gives [True, True, True]); sent back to its test-writer. AT5 waits on the frozen snapshot. Implementer's scratch check on live API data: 1,472 analysis rows, 4 named exceptions, 0 disagreements at a null threshold.
