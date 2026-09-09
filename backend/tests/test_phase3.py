"""Phase 3 (Expert): supported upload, custom contrasts, advanced spatial and
reference options, extended perturbations, capstone workspace."""

import io
import json
import os

import pytest

from app.constants import AccessTier, AnalysisTrack, RunStatus
from app.copilot import perturbation as pert
from app.core import parameters as params
from app.models import Dataset, Interpretation, Run

MATRIX_CSV = (
    "gene,S1,S2,S3,S4\n"
    + "\n".join(f"GENE{i:03d},{10 + i},{12 + i},{40 + i},{38 + i}" for i in range(30))
    + "\n"
)
METADATA_CSV = (
    "sample_id,condition,batch,donor\n"
    "S1,untreated,b1,d1\nS2,untreated,b2,d2\nS3,treated,b1,d3\nS4,treated,b2,d4\n"
)


def _upload(client, headers, matrix=MATRIX_CSV, metadata=METADATA_CSV, filename="counts.csv"):
    return client.post(
        "/api/datasets/upload",
        headers=headers,
        data={
            "track": "foundation",
            "name": "My dataset",
            "source": "Institutional repository",
            "accession": "LOCAL-001",
            "license": "Internal teaching use",
        },
        files={
            "matrix": (filename, io.BytesIO(matrix.encode()), "text/csv"),
            "metadata": ("meta.csv", io.BytesIO(metadata.encode()), "text/csv"),
        },
    )


# -------------------------------------------------------------- upload ----
def test_upload_is_expert_only(client, auth, moderate_auth):
    assert _upload(client, auth).status_code == 403
    assert _upload(client, moderate_auth).status_code == 403


def test_expert_upload_stores_a_validated_internal_object(
    client, expert_auth, tmp_path, monkeypatch
):
    from app.settings import settings

    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    response = _upload(client, expert_auth)
    assert response.status_code == 201
    body = response.json()

    assert body["provenance"]["accession"] == "LOCAL-001"
    assert body["governance"]["usedForTraining"] is False
    assert body["governance"]["sharedWithOtherUsers"] is False
    assert body["governance"]["retentionDays"]

    # Stored as the internal object, never as the raw upload (spec 10).
    written = [
        name
        for _, _, files in os.walk(tmp_path / "uploads")
        for name in files
    ]
    assert any(name.endswith(".npz") for name in written)
    assert any(name.endswith(".meta.json") for name in written)


def test_raw_sequencing_upload_is_refused(client, expert_auth, tmp_path, monkeypatch):
    from app.settings import settings

    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    response = _upload(client, expert_auth, filename="reads.fastq")
    assert response.status_code == 422
    codes = [error["code"] for error in response.json()["detail"]["errors"]]
    assert "raw_sequencing_not_supported" in codes


def test_identifiable_metadata_blocks_the_upload_and_writes_nothing(
    client, expert_auth, tmp_path, monkeypatch
):
    from app.settings import settings

    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    metadata = (
        "sample_id,condition,patient_name\n"
        "S1,untreated,Jane Doe\nS2,untreated,John Roe\n"
        "S3,treated,Ann Poe\nS4,treated,Sam Moe\n"
    )
    response = _upload(client, expert_auth, metadata=metadata)
    assert response.status_code == 422
    codes = [error["code"] for error in response.json()["detail"]["errors"]]
    assert "identifiable_information" in codes
    assert not os.path.exists(tmp_path / "uploads")


def test_upload_warns_about_a_confounded_design_without_blocking(
    client, expert_auth, tmp_path, monkeypatch
):
    from app.settings import settings

    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    metadata = (
        "sample_id,condition,batch\n"
        "S1,untreated,b1\nS2,untreated,b1\nS3,treated,b2\nS4,treated,b2\n"
    )
    response = _upload(client, expert_auth, metadata=metadata)
    assert response.status_code == 201
    codes = [w["code"] for w in response.json()["validation"]["warnings"]]
    assert "confounded_batch" in codes


def test_the_upload_cap_is_admin_editable(client, expert_auth, admin_auth, tmp_path, monkeypatch):
    from app.settings import settings

    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    client.put(
        "/api/admin/settings",
        headers=admin_auth,
        json={"key": "upload.max_bytes", "value": {"expert": 10}},
    )
    response = _upload(client, expert_auth)
    assert response.status_code == 422
    codes = [error["code"] for error in response.json()["detail"]["errors"]]
    assert "file_too_large" in codes


def test_an_owner_can_delete_their_upload_and_keep_prior_records(
    client, expert_auth, tmp_path, monkeypatch
):
    from app.settings import settings

    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    dataset_id = _upload(client, expert_auth).json()["id"]
    deleted = client.delete(f"/api/datasets/{dataset_id}", headers=expert_auth)
    assert deleted.status_code == 200
    assert "retained" in deleted.json()["note"]
    assert client.get(f"/api/datasets/{dataset_id}", headers=expert_auth).status_code == 404


# ---------------------------------------------------- custom contrasts ----
def test_only_expert_may_author_a_design_formula():
    with pytest.raises(params.ParameterError):
        params.validate("bulk.design.formula", "~ donor + condition", AccessTier.MODERATE)
    assert (
        params.validate("bulk.design.formula", "~ donor + condition", AccessTier.EXPERT)
        == "~ donor + condition"
    )


def test_moderate_keeps_the_validated_design_choices():
    assert params.validate("bulk.design.formula", "~ batch + condition", AccessTier.MODERATE)
    with pytest.raises(params.ParameterError):
        params.validate("bulk.design.formula", "~ batch + condition", AccessTier.BASIC)


def test_contrast_authoring_is_expert_only():
    for tier in (AccessTier.BASIC, AccessTier.MODERATE):
        with pytest.raises(params.ParameterError):
            params.validate("bulk.design.contrast", "treated-untreated", tier)
    assert params.validate("bulk.design.contrast", "treated-untreated", AccessTier.EXPERT)


# ------------------------------------------- extended spatial options ----
def test_extended_geometries_are_expert_only():
    for tier in (AccessTier.BASIC, AccessTier.MODERATE):
        with pytest.raises(params.ParameterError):
            params.validate("spatial.graph.type", "delaunay", tier)
    assert params.validate("spatial.graph.type", "delaunay", AccessTier.EXPERT) == "delaunay"
    # Grid remains available at every tier because it is what the assay measured.
    assert params.validate("spatial.graph.type", "grid", AccessTier.BASIC) == "grid"


def test_reference_mapping_requires_expert(client, moderate_auth, spatial_dataset):
    response = client.post(
        "/api/runs",
        headers=moderate_auth,
        json={
            "dataset_id": spatial_dataset.id,
            "track": "advanced",
            "parameters": {"spatial.mapping.reference_dataset": "some-reference"},
        },
    )
    assert response.status_code == 403
    assert response.json()["detail"]["feature"] == "spatial_reference_mapping"


# ------------------------------------------ extended perturbations ----
def test_the_perturbation_whitelist_excludes_sample_aware_testing():
    """Spec 4.2 is not a setting anyone may trade away, at any tier."""
    assert "sc.de.grouping" not in pert.PERTURBABLE_PARAMETERS
    with pytest.raises(pert.PerturbationNotAllowed):
        pert.assert_perturbable("sc.de.grouping")
    pert.assert_perturbable("sc.cluster.resolution")


def test_custom_perturbation_is_expert_only(client, auth, moderate_auth, db_session, learner):
    run = Run(
        user_id=learner.id,
        dataset_id="d1",
        track=AnalysisTrack.CORE,
        access_tier=AccessTier.BASIC,
        pipeline_version="core-1.0.0",
        parameters={"sc.cluster.resolution": 1.0},
    )
    db_session.add(run)
    db_session.commit()
    response = client.post(
        f"/api/runs/{run.id}/perturbations/custom",
        headers=auth,
        json={"parameter_key": "sc.cluster.resolution", "value": 2.0},
    )
    assert response.status_code == 403


def test_custom_perturbation_preserves_the_original_and_invents_no_expectation(
    client, expert_auth, db_session, expert_user, fixture_dataset, tmp_path, monkeypatch
):
    import numpy as np

    from app.settings import settings

    directory = tmp_path / "fixtures"
    directory.mkdir()
    rng = np.random.default_rng(5)
    genes = [f"GENE{i:03d}" for i in range(598)] + ["MT-A", "MT-B"]
    obs, blocks = [], []
    for donor in range(4):
        condition = "stimulated" if donor % 2 else "control"
        block = rng.negative_binomial(6, 0.3, size=(50, 600))
        blocks.append(block)
        obs.extend(
            {"cell_id": f"d{donor}c{i}", "sample_id": f"donor{donor}", "condition": condition}
            for i in range(50)
        )
    np.savez_compressed(directory / "synthetic-core.npz", matrix=np.vstack(blocks))
    (directory / "synthetic-core.meta.json").write_text(json.dumps({"obs": obs, "var": genes}))
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    fixture_dataset.storage_path = "fixtures/synthetic-core"
    db_session.commit()

    run = client.post(
        "/api/runs",
        headers=expert_auth,
        json={
            "dataset_id": fixture_dataset.id,
            "track": "core",
            "parameters": {"sc.qc.doublet_filter": False},
        },
    ).json()
    assert run["status"] == "completed"
    original_outputs = json.loads(json.dumps(run["outputs"]))

    result = client.post(
        f"/api/runs/{run['id']}/perturbations/custom",
        headers=expert_auth,
        json={
            "parameter_key": "sc.cluster.resolution",
            "value": 2.5,
            "rationale": "Testing whether my annotation survives finer partitioning.",
            "expected_direction": "increase",
        },
    )
    assert result.status_code == 200
    body = result.json()

    assert body["originalRun"]["outputs"] == original_outputs
    assert body["alternateRun"]["parentRunId"] == run["id"]
    assert body["alternateRun"]["isOriginal"] is False
    # The platform does not manufacture an expectation for a change it did not
    # propose, and cites no evidence for the learner's own reasoning.
    assert body["perturbation"]["expectedConsequence"]["authoredBy"] == "learner"
    assert "no reviewed expectation" in body["perturbation"]["limitation"]


def test_a_custom_perturbation_outside_the_whitelist_is_refused(
    client, expert_auth, db_session, expert_user
):
    run = Run(
        user_id=expert_user.id,
        dataset_id="d1",
        track=AnalysisTrack.CORE,
        access_tier=AccessTier.EXPERT,
        pipeline_version="core-1.0.0",
        parameters={"sc.de.grouping": "pseudobulk_by_sample"},
    )
    db_session.add(run)
    db_session.commit()
    response = client.post(
        f"/api/runs/{run.id}/perturbations/custom",
        headers=expert_auth,
        json={"parameter_key": "sc.de.grouping", "value": "per_cell"},
    )
    assert response.status_code == 422
    assert "not an analysis decision" in response.json()["detail"]


# ------------------------------------------------------------ capstone ----
def test_capstone_is_expert_only(client, auth, moderate_auth):
    assert client.get("/api/capstone", headers=auth).status_code == 403
    assert client.get("/api/capstone", headers=moderate_auth).status_code == 403


def test_capstone_only_accepts_completed_runs(
    client, expert_auth, db_session, expert_user, fixture_dataset
):
    failed = Run(
        user_id=expert_user.id,
        dataset_id=fixture_dataset.id,
        track=AnalysisTrack.CORE,
        access_tier=AccessTier.EXPERT,
        pipeline_version="core-1.0.0",
        status=RunStatus.FAILED,
    )
    db_session.add(failed)
    db_session.commit()
    response = client.put(
        "/api/capstone", headers=expert_auth, json={"run_ids": [failed.id]}
    )
    assert response.status_code == 422
    assert "cannot support a capstone claim" in response.json()["detail"]


def _completed_run(db_session, user, dataset) -> Run:
    run = Run(
        user_id=user.id,
        dataset_id=dataset.id,
        track=AnalysisTrack.CORE,
        access_tier=AccessTier.EXPERT,
        pipeline_version="core-1.0.0",
        method_versions={"pipeline": "core-1.0.0", "clustering": "Leiden 0.10.2"},
        parameters={"sc.cluster.resolution": 1.0},
        outputs={
            "cluster": {"n_clusters": 6, "cluster_sizes": [10, 20, 30, 5, 8, 9]},
            "de": {"n_significant": 12, "table": [{"gene": "GENE001", "padj": 0.01}]},
        },
        status=RunStatus.COMPLETED,
    )
    db_session.add(run)
    db_session.commit()
    return run


def test_figures_are_offered_only_where_an_output_backs_them(
    client, expert_auth, db_session, expert_user, fixture_dataset
):
    run = _completed_run(db_session, expert_user, fixture_dataset)
    client.put("/api/capstone", headers=expert_auth, json={"run_ids": [run.id]})
    offered = client.get("/api/capstone/available-figures", headers=expert_auth).json()
    ids = {figure["id"] for figure in offered}
    assert {"cluster_sizes", "de_volcano"} <= ids
    # Nothing spatial is offered, because no spatial output exists on this run.
    assert "domain_map" not in ids and "gene_maps" not in ids


def test_figure_panels_carry_their_own_provenance(
    client, expert_auth, db_session, expert_user, fixture_dataset
):
    run = _completed_run(db_session, expert_user, fixture_dataset)
    client.put(
        "/api/capstone",
        headers=expert_auth,
        json={
            "run_ids": [run.id],
            "figures": [{"figureId": "cluster_sizes", "runId": run.id}],
        },
    )
    pack = client.get("/api/capstone/figure-pack", headers=expert_auth).json()
    assert pack["count"] == 1
    panel = pack["panels"][0]
    assert panel["data"] == [10, 20, 30, 5, 8, 9]
    assert panel["provenance"]["methodVersions"]["clustering"] == "Leiden 0.10.2"
    assert panel["provenance"]["parameters"]["sc.cluster.resolution"] == 1.0


def test_the_deck_reports_what_is_missing_and_refuses_a_thin_submission(
    client, expert_auth, db_session, expert_user, fixture_dataset
):
    run = _completed_run(db_session, expert_user, fixture_dataset)
    client.put("/api/capstone", headers=expert_auth, json={"run_ids": [run.id]})

    deck = client.get("/api/capstone/deck", headers=expert_auth).json()
    #: Spec 13 asks for a five-to-eight slide defence deck.
    assert 5 <= len(deck["slides"]) <= 8
    assert deck["slideCount"] == len(deck["slides"])
    assert [slide["title"] for slide in deck["slides"]][:3] == [
        "Capstone",
        "Design and data",
        "Methods and versions",
    ]
    #: Merging design with provenance must not drop the provenance itself.
    design = deck["slides"][1]["body"]
    assert "datasets" in design
    assert deck["readiness"]["ready"] is False
    assert any("research question" in gap for gap in deck["readiness"]["gaps"])
    assert "not an assessment" in deck["readiness"]["note"]

    refused = client.post("/api/capstone/submit", headers=expert_auth)
    assert refused.status_code == 422
    assert refused.json()["detail"]["error"] == "capstone_incomplete"


def test_a_complete_capstone_submits_and_then_locks(
    client, expert_auth, db_session, expert_user, fixture_dataset
):
    run = _completed_run(db_session, expert_user, fixture_dataset)
    db_session.add(
        Interpretation(
            run_id=run.id,
            user_id=expert_user.id,
            step="clustering",
            observation="Six clusters at the recorded resolution.",
            statistical_evidence="Each cluster carries distinct markers.",
            biological_interpretation="Consistent with known blood populations.",
            hypothesis="Test the smallest cluster in an independent donor set.",
            label="partially_supported",
        )
    )
    db_session.commit()

    client.put(
        "/api/capstone",
        headers=expert_auth,
        json={
            "title": "Immune population structure",
            "research_question": "Which populations are present and how confident am I?",
            "run_ids": [run.id],
            "figures": [{"figureId": "cluster_sizes", "runId": run.id}],
            "limitations": ["Four donors is a small basis for any claim."],
            "future_work": "Replicate in an independent cohort.",
        },
    )
    submitted = client.post("/api/capstone/submit", headers=expert_auth)
    assert submitted.status_code == 200
    assert submitted.json()["submittedAt"]

    # Submission closes the record.
    again = client.put("/api/capstone", headers=expert_auth, json={"title": "changed"})
    assert again.status_code == 409
    assert client.post("/api/capstone/submit", headers=expert_auth).status_code == 409
