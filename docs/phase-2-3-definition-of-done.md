# Phase 2 and Phase 3 Definition of Done

Checked against spec 12 and 13. Phase 1's record is in
[phase-1-definition-of-done.md](phase-1-definition-of-done.md); the rows there
still hold and are not repeated.

`ACTIVE_PHASE` is now `3`. The phase gate itself is still live and still tested
(`test_the_phase_gate_still_withholds_unreleased_perturbations`), so a future
module can be declared before it is routable.

## Phase 2 — Moderate

| Item | Status | Where |
|---|---|---|
| Trial datasets | done | Seeded with provenance and gated behind `trial_dataset`; `datasets.py` |
| Independent reruns | done | Any run carrying learner parameters requires `independent_rerun`; `test_phase2.py::test_moderate_may_rerun_with_its_own_parameters` |
| Parameter controls at the Moderate range | done | Registry `full` scope; the same test asserts the range is enforced server-side |
| Cell-Cell Communication Explorer | done | `pipelines/communication.py`, versioned `communication-1.0.0`; `test_phase2.py` |
| Full spatial guided workflow | done | `pipelines/advanced.py`, ten steps, `advanced-1.0.0`; runs end to end on a fixture |
| Compare Runs | done | `GET /api/runs/compare/pair` returns changed settings, moved metrics and changed conclusions |
| Full exports | done | `pdf_full`, `csv`, `figure_pack` in `reports.py`; audit sheet and perturbation record included |
| Paid entitlement and payment flow | partial by design | Order, activation, term-limited entitlement and expiry behaviour are complete and tested. **No payment provider is integrated**: an order records as `awaiting_payment` and an administrator activates it once payment clears out of band. |

## Phase 3 — Expert

| Item | Status | Where |
|---|---|---|
| Supported analysis-ready user upload | done | `POST /api/datasets/upload`; every governance gate runs before anything is written, and the stored artefact is the validated internal object, never the raw file |
| Custom contrasts | done | `bulk.design.formula` and `bulk.design.contrast` open only at the `extended` scope |
| Advanced spatial and reference options | done | Extended geometries (radius, Delaunay) and reference deconvolution are Expert-gated; deconvolution refuses an incompatible reference |
| Extended perturbations | done | `POST /api/runs/{id}/perturbations/custom`, bounded by the whitelist and the registry |
| Capstone workspace | done | `capstone.py`: run attachment, figure pack with per-panel provenance, defence deck (8 slides, within spec 13's five-to-eight), two-page research memo, final defence score, readiness report, submission lock |
| Premium usage controls | done | Unmetered runs, twenty perturbations per run, admin-editable upload cap |

## Scientific rules enforced in code, not copy

- **Single-specimen spatial data.** The Advanced pipeline stamps
  `inference_scope` on its own `validate` and `region` outputs. The workspace
  reads that stamp rather than deciding for itself, and the Copilot's label
  rules downgrade a conclusion drawn from one specimen to Speculative.
- **Spot-level cell type estimates.** Every deconvolution output carries
  `estimate_kind = "compositional"` and `per_spot_identity = False`.
- **Inferred communication.** Interaction and mechanism outputs carry
  `evidenceKind = "inferred_candidate_communication"`, and each candidate
  mechanism states the perturbation experiment that would be needed to confirm
  it.
- **Sample-aware condition inference.** `sc.de.grouping` remains single-valued
  at every tier and is deliberately absent from the perturbation whitelist, so
  no tier and no self-authored what-if can reach cell-level condition testing.
- **Platform-compatible geometry only.** Ring adjacency uses true hex distance
  in axial coordinates, so one ring is six neighbours rather than a Manhattan
  ball; asking for grid geometry on a package with no array positions fails
  rather than falling back to a distance rule the assay never measured.
- **Learner-authored perturbations get no invented expectation.** The platform
  proposes nothing it has not reviewed; the learner states their expectation and
  the comparison is recorded against what they wrote.

## Still outstanding

- **SME sign-off on every locked method**, now including the communication
  statistic and its database, the spatial graph, Moran's I and Cell2location.
  `sme_signoff` is `False` throughout; `GET /api/admin/method-lock` reports it.
- **Payment provider integration.** See the Phase 2 table above.
- **Guided teaching data ingestion.** GSE52778, GSE96583 and the Visium section
  are seeded with provenance but remain `pending_data_ingest`. Two synthetic
  fixtures — one single-cell, one spatial — exercise the workflows meanwhile and
  are labelled as synthetic in their name, provenance and limitations.
- **External assets.** The Hallmark gene sets and the CellPhoneDB interaction
  database are fetched by script and are not bundled; without them, pathway
  enrichment and the communication module fail with a message naming the missing
  asset rather than substituting another.
- **R and spatial worker images.** Bulk differential expression (DESeq2) and
  spatial deconvolution (Cell2location) need runtimes not provisioned here and
  fail cleanly, preserving every earlier step's results.

## Deliberately not built

Raw FASTQ/BAM/CRAM processing, large remote imports and the workflow
marketplace remain gated behind a separate compute, storage and security
sign-off (spec 12, "Future — Compute Heavy"). Nothing has been scaffolded for
them; the ingestion validator actively rejects raw sequencing formats.


## Added 2026-09-09, after re-reading spec 13 and 16

Three things spec 13 asks for had no implementation, and one build could not
be produced at all.

| Item | What was missing | Where it is now |
|---|---|---|
| Week assessment (screen 11) | `AssessmentResult` existed but only the **pre-lab** ever wrote one. The week assessment — concept understanding, analytical decisions, interpretation quality — had no endpoint and no scoring. | `content/assessment.py` (20 concept questions across the eight weeks), `core/assessment.py` (scoring), `GET`/`POST /api/program/assessment` |
| Two-page research memo | Not implemented. | `GET /api/capstone/memo` |
| Final defence score | Submission recorded `submitted_at` only. | Computed at submission from the record, stored on the capstone, exposed as `defenceScore` and `defenceBreakdown` |
| Defence deck length | 11 slides, where spec 13 asks for five to eight. | Consolidated to 8; the count is asserted in the endpoint and in the test suite |
| `INCLUDE_SCIENCE=true` | The build failed: `requirements-science.txt` carried `rpy2`, which cannot install without R. With that removed the Core pipeline still died at cell QC on a missing `scikit-image`. | `rpy2` moved to `requirements-r-worker.txt`; `scikit-image` pinned. A Core run now completes end to end, nine steps. |

### The rule the assessment follows

A component with no recorded work is reported as **not assessable**, never
scored zero, and the overall figure is the mean of the components that could be
assessed. A zero would claim the learner reasoned badly when the truth is that
they have not reached that part of the week.

The same discipline governs the defence score: every part states what it
counted, and the note says plainly that it measures whether the work is
defensible — complete, adjudicated, tested, stated with its limits — and not
whether the biology is right, which the platform cannot know.
