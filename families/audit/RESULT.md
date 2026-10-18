# AT3 label audit

Sample: 200 notes from benchmarks with at least 500 rows, seed 17 (`sample.py`, `sample.jsonl`). Verdicts: `verdicts.jsonl`, one per note in sample order.

Five fresh-context Claude Opus 5.5 auditors scored 40 notes each as agree, contradict or silent against the `Model:` line. The header line and verbatim copies of it in the body are not evidence. Auditors located evidence by keyword search plus reading around each hit; batch 3 was read line by line.

## Result

| Verdict | Notes |
|---|---|
| agree | 69 |
| contradict | 5 |
| silent | 126 |

Agreement among non-silent notes is 69 of 74, or 93.2%. This is below the 95% bar in spec AT3. AT3 is a recorded test (milestone M2), not a gate, so the shortfall is reported as a limitation.

## Contradictions

| Note | Declared | Body |
|---|---|---|
| 69012c38 | GPT 6 Astra | GPT 5.6 Luna and Muse Spark 1.3 also did part of the work |
| 152d320b | SWE-1.7 Max | "Model: GLM-5.2 High via Devin CLI" |
| cd20ea59 | Claude Fable 5.1 | GLM 5.3 authored the design and port layers |
| ed54ff77 | Gemini 3.7 Flash | submit command names Gemini 2.5 Flash |
| 03163692 | Claude Opus 5 | part of the work came from a GPT-5 / Codex operator |

Four of the five change the family: three are multi-vendor work under a single-vendor label, and one names another vendor. ed54ff77 stays Google. Family-level agreement is therefore 70 of 74, or 94.6%.

## Rule variation between auditors

Batches 0, 1 and 3 counted an agent line that names the declared vendor's harness ("Agent: Claude Code", "Agent: Codex") as agree. Batch 2 counted it as silent. Recoding those 13 notes to silent gives 56 of 61, or 91.8%, at model level.

Wisdom waived the 20-note spot-check on 2026-10-18.
