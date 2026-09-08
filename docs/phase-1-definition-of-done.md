# Phase 1 Definition of Done

> **Superseded in part.** Phases 2 and 3 have since been built and
> `ACTIVE_PHASE` is now `3`. The rows below still describe Phase 1's scope and
> still hold, except where noted inline. Items this document listed as
> deliberately deferred are covered in
> [phase-2-3-definition-of-done.md](phase-2-3-definition-of-done.md).

Checked against spec 13. Each row names where the behaviour lives and the test
that holds it.

| Item | Status | Where |
|---|---|---|
| Tiers implemented separately from tracks, no shared enums or naming overlap | done | `constants.py`; `test_entitlements.py::test_tier_and_track_vocabularies_do_not_overlap`, `scripts/lint_naming.py` |
| Basic auto-granted to qualifying flagship learners; paid tiers gated end to end | done | `core/access.py`, `api/deps.py`; `test_entitlements.py` |
| Week 1 Design Studio functional, produces a saved design/metadata output | done | `api/routers/design.py`; `test_api_flow.py::test_design_studio_saves_a_plan_and_records_its_warnings` |
| Guided datasets have validated provenance, files, metadata, supported analyses | partial | Provenance and validation gate are done; the GSE52778 and GSE96583 **files are not ingested** and the datasets are correctly non-selectable until an operator runs `scripts/fetch_guided_data.py` |
| Foundation, Core, Advanced pipelines run reproducibly on their guided datasets | partial | Core and Advanced both run end to end and are reproducible (`test_pipeline_is_reproducible`, `test_spatial_pipeline_is_reproducible`). Foundation's DE step needs the R/DESeq2 worker, absent here, and fails cleanly. |
| Every adjustable parameter has a default, allowed range, validation rule | done | `core/parameters.py`; `test_parameters.py` |
| AI explanations cite approved evidence; cannot invent results or references | done | `copilot/grounding.py`, `copilot/evidence.py`; `test_copilot_grounding.py` |
| TEST/SKIP preserves the original run and creates a comparable alternate | done | `api/routers/runs.py`, `copilot/perturbation.py`; `test_pipeline_runs.py::test_perturbation_preserves_the_original_and_creates_a_comparable_alternate` |
| Observation / statistical evidence / biological interpretation / hypothesis separated in UI and report | done | `pages/Workspace.tsx`, `api/routers/reports.py`; `test_api_flow.py` |
| Cell-level condition inference uses sample-aware logic | done | `pipelines/core.py`, `sc.de.grouping` is single-valued at every tier; `test_parameters.py::test_cell_level_condition_testing_is_unreachable_at_every_tier` |
| Expert upload validates type, structure, governance before execution | done | `governance/validation.py` and `POST /api/datasets/upload`; `test_governance.py`, `test_phase3.py` |
| Every run stores dataset, method version, parameters, decisions, references | done | `models.Run`, `pipelines/runner.py`; `test_pipeline_runs.py::test_run_records_full_provenance` |
| Access expiry and upgrade/downgrade behaviour tested | done | `test_entitlements.py::test_expiry_downgrades_access_but_keeps_reports` |
| Reports and AI audit records export correctly for the allowed tier | done | `api/routers/reports.py`; `test_api_flow.py::test_basic_cannot_export_the_full_report` |
| Admin can configure entitlements, datasets, module availability, defaults | done | `api/routers/admin.py` |
| Error, empty-state, failed-run, invalid-input behaviour tested per module | done | `test_pipeline_runs.py::test_a_failing_step_preserves_the_last_valid_state`, `test_governance.py` |
| SME sign-off on each canonical pipeline before production release | **outstanding** | `sme_signoff` is `False` for every locked method; `GET /api/admin/method-lock` reports what is pending |

## Deferred at the time, since built

Everything this section originally listed for Phases 2 and 3 has been
implemented — see
[phase-2-3-definition-of-done.md](phase-2-3-definition-of-done.md) for its own
status table, including what remains outstanding there (SME sign-off, payment
provider integration, guided data ingestion, external assets and the R and
spatial worker images).

Raw FASTQ/BAM/CRAM processing remains gated behind a separate compute, storage
and security sign-off and has not been scaffolded.
