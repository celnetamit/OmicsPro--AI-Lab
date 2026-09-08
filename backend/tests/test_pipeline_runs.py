"""Definition of Done: pipelines run reproducibly, runs record full provenance,
failures preserve the last valid state, and a perturbation preserves the
original run while creating a comparable alternate (spec 10, 13)."""

import json
import os

import numpy as np
import pytest

from app.constants import AccessTier, AnalysisTrack, RunStatus
from app.copilot import perturbation as pert, service as copilot
from app.core import parameters as params
from app.governance.loader import load
from app.models import Dataset, Run
from app.pipelines import registry, runner
from app.pipelines.base import BackendUnavailable, DataObject, StepContext, StepFailure
from app.settings import settings


def _fixture_object(n_cells=200, n_genes=600):
    rng = np.random.default_rng(1)
    genes = [f"GENE{i:03d}" for i in range(n_genes - 2)] + ["MT-A", "MT-B"]
    obs, blocks = [], []
    for donor in range(4):
        condition = "stimulated" if donor % 2 else "control"
        cells = n_cells // 4
        block = rng.negative_binomial(6, 0.3, size=(cells, n_genes))
        if condition == "stimulated":
            block[:, :40] *= 4
        blocks.append(block)
        obs.extend(
            {
                "cell_id": f"d{donor}_c{i}",
                "sample_id": f"donor{donor}",
                "condition": condition,
                "batch": "b1",
            }
            for i in range(cells)
        )
    return DataObject(
        matrix=np.vstack(blocks), obs=obs, var=genes, track=AnalysisTrack.CORE
    )


def _make_run(db_session, parameters=None, parent=None):
    run = Run(
        user_id="u1",
        dataset_id="d1",
        track=AnalysisTrack.CORE,
        access_tier=AccessTier.BASIC,
        pipeline_version=registry.get(AnalysisTrack.CORE).version,
        parameters=parameters
        or params.validate_many({}, AnalysisTrack.CORE, AccessTier.BASIC),
        parent_run_id=parent.id if parent else None,
        is_original=parent is None,
    )
    db_session.add(run)
    db_session.commit()
    return run


def _execute(db_session, run, data=None):
    #: Doublet detection needs the locked runtime; the guided default is on, so
    #: tests that do not exercise it turn it off explicitly.
    return runner.execute(db_session, run, data or _fixture_object())


def test_run_records_full_provenance(db_session):
    run = _make_run(db_session)
    run.parameters = {**run.parameters, "sc.qc.doublet_filter": False}
    _execute(db_session, run)

    assert run.pipeline_version == registry.get(AnalysisTrack.CORE).version
    assert run.method_versions["pipeline"] == run.pipeline_version
    assert "clustering" in run.method_versions
    assert run.parameters and run.outputs
    assert run.started_at is not None


def test_pipeline_is_reproducible(db_session):
    overrides = {"sc.qc.doublet_filter": False}
    first = _make_run(db_session, {**params.defaults_for(AnalysisTrack.CORE), **overrides})
    second = _make_run(db_session, {**params.defaults_for(AnalysisTrack.CORE), **overrides})
    _execute(db_session, first)
    _execute(db_session, second)
    assert first.status == RunStatus.COMPLETED
    assert first.outputs["cluster"] == second.outputs["cluster"]
    assert first.outputs["de"]["n_significant"] == second.outputs["de"]["n_significant"]


def test_condition_testing_is_sample_aware(db_session):
    run = _make_run(db_session, {**params.defaults_for(AnalysisTrack.CORE), "sc.qc.doublet_filter": False})
    _execute(db_session, run)
    assert run.outputs["de"]["replicate_unit"] == "sample"
    # Four donors, so pseudobulk profiles never exceed four per cell type.
    profiles = run.outputs["de"]["n_profiles"]
    types = max(run.outputs["de"]["n_cell_types_tested"], 1)
    assert profiles <= 4 * max(types, run.outputs["cluster"]["n_clusters"])


def test_a_failing_step_preserves_the_last_valid_state(db_session):
    """Spec 10: no corrupted partial state, and a readable message."""
    run = _make_run(
        db_session,
        {
            **params.defaults_for(AnalysisTrack.CORE),
            "sc.qc.doublet_filter": False,
        },
    )
    #: A shallow object where the guided floor of 200 detected genes per cell
    #: describes no cell at all.
    _execute(db_session, run, _fixture_object(n_genes=60))
    assert run.status == RunStatus.FAILED
    assert "Relax" in run.error_message
    assert run.last_valid_step == "validate"
    assert "validate" in run.outputs


def test_locked_runtime_absence_fails_the_run_rather_than_substituting(db_session, monkeypatch):
    def _boom(*_args, **_kwargs):
        raise BackendUnavailable("Scrublet 1.10.1 is the locked method and is not available.")

    monkeypatch.setattr("app.pipelines.locked.scrublet_doublet_scores", _boom)
    run = _make_run(db_session)  # default leaves doublet filtering on
    _execute(db_session, run)
    assert run.status == RunStatus.FAILED
    assert "locked method" in run.error_message
    assert run.last_valid_step == "validate"


def test_perturbation_preserves_the_original_and_creates_a_comparable_alternate(db_session):
    baseline = {**params.defaults_for(AnalysisTrack.CORE), "sc.qc.doublet_filter": False}
    original = _make_run(db_session, baseline)
    _execute(db_session, original)
    original_outputs = json.loads(json.dumps(original.outputs))

    offer = pert.get("sc.resolution_higher")
    proposed = pert.proposed_value(offer, baseline["sc.cluster.resolution"])
    alternate = _make_run(
        db_session, {**baseline, offer.parameter_key: proposed}, parent=original
    )
    _execute(db_session, alternate)

    # The original run is untouched and still recoverable.
    assert original.outputs == original_outputs
    assert original.is_original and not alternate.is_original
    assert alternate.parent_run_id == original.id

    reconciliation = pert.reconcile(offer, original.outputs, alternate.outputs)
    assert reconciliation["comparisons"]
    assert reconciliation["divergenceExplanation"]


def test_expected_consequences_never_promise_a_number():
    for offer in pert.CATALOGUE:
        for expectation in offer.expectations:
            assert expectation.direction in (
                pert.INCREASE,
                pert.DECREASE,
                pert.UNCHANGED,
                pert.UNCERTAIN,
            )
        assert offer.limitation.strip()
        assert offer.what_to_observe.strip()
        assert offer.scientific_reason.strip()


def test_perturbation_outside_the_whitelist_is_refused():
    with pytest.raises(pert.PerturbationNotAllowed):
        pert.get("sc.delete_all_cells")


def test_the_phase_gate_still_withholds_unreleased_perturbations(monkeypatch):
    """The gate is live even though every declared phase is now active."""
    monkeypatch.setattr(pert, "ACTIVE_PHASE", 1)
    with pytest.raises(pert.PerturbationNotAllowed, match="not available"):
        pert.get("spatial.geometry_change")
    assert [o.key for o in pert.available_for(AnalysisTrack.ADVANCED, "spatial_domains")] == []


def test_reconciliation_reports_a_divergence_honestly():
    offer = pert.get("sc.resolution_higher")
    result = pert.reconcile(
        offer,
        {"cluster": {"n_clusters": 8, "min_cluster_size": 10}},
        {"cluster": {"n_clusters": 5, "min_cluster_size": 20}},
    )
    assert result["matchedExpectation"] is False
    assert "expected to increase" in result["divergenceExplanation"]


def test_copilot_explains_a_real_run_only(db_session):
    run = _make_run(db_session, {**params.defaults_for(AnalysisTrack.CORE), "sc.qc.doublet_filter": False})
    _execute(db_session, run)
    payload = copilot.explain(db_session, "u1", run, "clustering")
    assert str(run.outputs["cluster"]["n_clusters"]) in payload["text"]
    assert payload["evidence"]
    assert payload["caveats"]


def test_copilot_refuses_a_step_it_has_no_reviewed_content_for(db_session):
    run = _make_run(db_session)
    with pytest.raises(KeyError, match="no reviewed Copilot content|No reviewed"):
        copilot.explain(db_session, "u1", run, "spatial_domains")
