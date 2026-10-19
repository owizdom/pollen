# Deviations from the pre-registration

Changes made after the `prereg-v1` tag (`09c0815`) to anything the lock covers, with date and reason.

None. The confirmatory, secondary, sensitivity and exploratory runs used the locked code and the locked `docs/prereg.md` unchanged, and `analysis.lock.check()` passed before each run.

Descriptive additions made after the lock live outside the locked directories and feed no pre-registered estimate:

- `tools/paper_numbers.py`: sample counts, AT4, AT5, AT13 and AT14 counts, a 90% prediction interval, the ECDSA.Fail 90% interval, and `eigenlabs/flock-challenge` alone under sensitivity analysis 1.
- `tools/paper_figures.py`: the paper's forest plots and the parent-by-child family table.
