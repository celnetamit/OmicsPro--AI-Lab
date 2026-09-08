# The naming rule (spec 1)

Two dimensions exist and they never share vocabulary.

| Dimension | Labels | Governs | Declared in |
|---|---|---|---|
| Scientific analysis track | Foundation / Core / Advanced | Type and complexity of the omics analysis | `AnalysisTrack` in `backend/app/constants.py` |
| Commercial access tier | Basic / Moderate / Expert | What the user may access, run, change, upload, export | `AccessTier` in `backend/app/constants.py` |

Never use Basic/Moderate/Expert to label a scientific track. Never use
Foundation/Core/Advanced to label a commercial permission. This covers UI
strings, routes and slugs, database values, analytics event names and admin
console labels.

## How it is enforced

- The two enums are separate types with disjoint value sets, asserted by
  `test_tier_and_track_vocabularies_do_not_overlap`.
- `scripts/lint_naming.py` scans the repository for leakage in either direction
  and for scientific thresholds assigned outside the parameter registry. It runs
  as part of the test suite (`test_guardrails.py`) so it cannot be skipped at
  review.
- Only `constants.py`, `parameters.py`, this document, the linter and the
  linter's own fixture file are allowlisted.

Run it directly with:

    python scripts/lint_naming.py
