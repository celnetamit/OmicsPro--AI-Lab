"""Phase 2 (Moderate): spatial workflow, communication explorer, trial datasets,
reruns, wider parameter ranges, Compare Runs, full exports, purchase."""

import numpy as np
import pytest

from app.constants import AccessTier, AnalysisTrack, RunStatus
from app.core import parameters as params
from app.governance.loader import load
from app.models import Entitlement, Purchase, Run
from app.pipelines import advanced, communication, locked, reference as ref, registry, runner
from app.pipelines.base import BackendUnavailable


# ------------------------------------------------------------- spatial ----
def test_hex_ring_adjacency_matches_the_capture_array():
    """One ring on a hexagonal array is six neighbours, not a Manhattan ball."""
    grid = np.array([[r, c] for r in range(6) for c in range(r % 2, 12, 2)])
    graph = ref.spatial_graph(np.zeros((len(grid), 2)), "grid", n_rings=1, grid=grid)
    degrees = np.asarray(graph.sum(axis=1)).ravel()
    assert int(degrees.max()) == 6
    two_rings = ref.spatial_graph(np.zeros((len(grid), 2)), "grid", n_rings=2, grid=grid)
    assert int(np.asarray(two_rings.sum(axis=1)).ravel().max()) == 18


def test_grid_geometry_is_refused_without_array_positions():
    with pytest.raises(ValueError, match="array position"):
        ref.spatial_graph(np.random.default_rng(0).random((10, 2)), "grid")


def _spatial_run(db_session, dataset, parameters=None, tier=AccessTier.MODERATE):
    resolved = params.validate_many(parameters or {}, AnalysisTrack.ADVANCED, tier)
    run = Run(
        user_id="u1",
        dataset_id=dataset.id,
        track=AnalysisTrack.ADVANCED,
        access_tier=tier,
        pipeline_version=registry.get(AnalysisTrack.ADVANCED).version,
        parameters=resolved,
    )
    db_session.add(run)
    db_session.commit()
    data = load(dataset)
    data.meta["spatial_dataset"] = dataset
    return runner.execute(db_session, run, data)


def test_spatial_pipeline_runs_and_stamps_its_own_limits(db_session, spatial_dataset):
    run = _spatial_run(db_session, spatial_dataset)
    # Pathway enrichment needs the locked gene set collection, absent in tests.
    assert run.last_valid_step == "region_comparison"

    assert run.outputs["validate"]["n_specimens"] == 1
    assert run.outputs["validate"]["inference_scope"] == "descriptive_single_specimen"
    # Spec 4.3: a single-specimen region comparison must be labelled descriptive
    # by the pipeline itself, not by interface copy.
    assert run.outputs["region"]["inference_scope"] == "descriptive_single_specimen"
    assert "hypothesis-generating" in run.outputs["region"]["caveat"]
    assert run.outputs["graph"]["geometry"] == "grid"
    assert run.outputs["domains"]["n_domains"] >= 2


def test_spot_estimates_are_never_presented_as_single_cell_identities(
    db_session, spatial_dataset
):
    run = _spatial_run(db_session, spatial_dataset)
    mapping = run.outputs["mapping"]
    assert mapping["per_spot_identity"] is False
    # No reference was selected, so nothing was estimated and it says so.
    assert mapping["performed"] is False
    assert mapping["estimate_kind"] == "none"


def test_deconvolution_refuses_an_incompatible_reference(db_session, spatial_dataset):
    from app.models import Dataset

    reference = Dataset(
        slug="wrong-reference",
        name="A bulk dataset offered as a reference",
        track=AnalysisTrack.FOUNDATION,
        kind="guided",
        source="test",
        accession="X",
        license="test",
        validation_status="validated",
    )
    db_session.add(reference)
    db_session.commit()
    with pytest.raises(BackendUnavailable, match="not compatible"):
        locked.assert_reference_compatible(spatial_dataset, reference)


def test_spatial_pipeline_is_reproducible(db_session, spatial_dataset):
    first = _spatial_run(db_session, spatial_dataset)
    second = _spatial_run(db_session, spatial_dataset)
    assert first.outputs["domains"]["domain_sizes"] == second.outputs["domains"]["domain_sizes"]
    assert first.outputs["svg"]["top_genes"] == second.outputs["svg"]["top_genes"]


def test_the_advanced_track_carries_no_bulk_or_communication_defaults():
    defaults = params.defaults_for(AnalysisTrack.ADVANCED)
    assert not any(key.startswith("bulk.") for key in defaults)
    assert "spatial.domains.resolution" in defaults
    # Shared embedding settings are shared deliberately, not by leakage.
    assert "sc.pca.n_comps" in defaults


# ------------------------------------------------------ communication ----
def _synthetic_pairs(genes):
    return [{"ligand": genes[i], "receptor": genes[i + 1]} for i in range(0, 60, 2)]


def test_communication_refuses_to_run_without_the_locked_database(
    db_session, fixture_dataset, monkeypatch, tmp_path
):
    from app.settings import settings

    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    with pytest.raises(BackendUnavailable, match="ligand-receptor database"):
        locked.load_ligand_receptor_pairs()


def test_communication_reports_candidates_not_demonstrated_signalling(
    db_session, monkeypatch
):
    from tests.test_pipeline_runs import _fixture_object

    data = _fixture_object()
    monkeypatch.setattr(
        locked, "load_ligand_receptor_pairs", lambda: _synthetic_pairs(list(data.var))
    )
    resolved = params.validate_many(
        {"sc.qc.doublet_filter": False}, AnalysisTrack.CORE, AccessTier.MODERATE
    )
    run = Run(
        user_id="u1",
        dataset_id="d1",
        track=AnalysisTrack.CORE,
        module="core_communication",
        access_tier=AccessTier.MODERATE,
        pipeline_version=communication.PIPELINE.version,
        parameters=resolved,
    )
    db_session.add(run)
    db_session.commit()
    runner.execute(db_session, run, data)

    assert run.status == RunStatus.COMPLETED
    assert run.method_versions["pipeline"] == "communication-1.0.0"
    assert run.outputs["interactions"]["evidenceKind"] == "inferred_candidate_communication"
    assert "not demonstrated physical signalling" in run.outputs["interactions"]["caveat"]
    assert run.outputs["mechanism"]["evidenceKind"] == "inferred_candidate_communication"
    for candidate in run.outputs["mechanism"]["candidates"]:
        # Every candidate states what would actually be needed to confirm it.
        assert "perturbation" in candidate["wouldConfirmIt"]


def test_communication_module_is_versioned_separately_from_the_guided_core():
    assert communication.PIPELINE.version != registry.get(AnalysisTrack.CORE).version
    entry = registry.get_module("core_communication")
    assert entry["feature"] == "cell_communication"
    assert entry["track"] is AnalysisTrack.CORE


# ----------------------------------------------------------- API gates ----
def test_basic_cannot_start_the_communication_module(client, auth, fixture_dataset):
    response = client.post(
        "/api/runs",
        headers=auth,
        json={"dataset_id": fixture_dataset.id, "track": "core", "module": "core_communication"},
    )
    assert response.status_code == 403
    assert response.json()["detail"]["feature"] == "cell_communication"


def test_moderate_may_rerun_with_its_own_parameters(client, moderate_auth, fixture_dataset):
    """The gate is the tier, and the range is the tier's — both server-side."""
    ok = client.post(
        "/api/runs",
        headers=moderate_auth,
        json={
            "dataset_id": fixture_dataset.id,
            "track": "core",
            "parameters": {"sc.cluster.resolution": 2.4},
        },
    )
    assert ok.status_code != 403

    too_wide = client.post(
        "/api/runs",
        headers=moderate_auth,
        json={
            "dataset_id": fixture_dataset.id,
            "track": "core",
            "parameters": {"sc.cluster.resolution": 8.0},
        },
    )
    assert too_wide.status_code == 422
    assert "sc.cluster.resolution" in too_wide.json()["detail"]["fields"]


def test_compare_runs_is_gated_and_refuses_incomparable_runs(
    client, auth, moderate_auth, db_session, fixture_dataset, learner, moderate_user
):
    def _run(user_id, tier, track=AnalysisTrack.CORE, dataset_id=None):
        run = Run(
            user_id=user_id,
            dataset_id=dataset_id or fixture_dataset.id,
            track=track,
            access_tier=tier,
            pipeline_version="core-1.0.0",
            parameters={"sc.cluster.resolution": 1.0},
            status=RunStatus.COMPLETED,
        )
        db_session.add(run)
        db_session.commit()
        return run

    basic_run = _run(learner.id, AccessTier.BASIC)
    assert (
        client.get(
            "/api/runs/compare/pair",
            headers=auth,
            params={"original": basic_run.id, "alternate": basic_run.id},
        ).status_code
        == 403
    )

    first = _run(moderate_user.id, AccessTier.MODERATE)
    other_track = _run(moderate_user.id, AccessTier.MODERATE, track=AnalysisTrack.FOUNDATION)
    mismatch = client.get(
        "/api/runs/compare/pair",
        headers=moderate_auth,
        params={"original": first.id, "alternate": other_track.id},
    )
    assert mismatch.status_code == 422
    assert "same analysis track" in mismatch.json()["detail"]


def test_compare_reports_settings_metrics_and_changed_conclusions(
    client, moderate_auth, db_session, fixture_dataset, moderate_user
):
    from app.models import Interpretation

    original = Run(
        user_id=moderate_user.id,
        dataset_id=fixture_dataset.id,
        track=AnalysisTrack.CORE,
        access_tier=AccessTier.MODERATE,
        pipeline_version="core-1.0.0",
        parameters={"sc.cluster.resolution": 1.0},
        outputs={"cluster": {"n_clusters": 7}},
        status=RunStatus.COMPLETED,
    )
    alternate = Run(
        user_id=moderate_user.id,
        dataset_id=fixture_dataset.id,
        track=AnalysisTrack.CORE,
        access_tier=AccessTier.MODERATE,
        pipeline_version="core-1.0.0",
        parameters={"sc.cluster.resolution": 2.0},
        outputs={"cluster": {"n_clusters": 12}},
        status=RunStatus.COMPLETED,
        is_original=False,
    )
    db_session.add_all([original, alternate])
    db_session.flush()
    db_session.add_all(
        [
            Interpretation(
                run_id=original.id,
                user_id=moderate_user.id,
                step="clustering",
                label="supported",
            ),
            Interpretation(
                run_id=alternate.id,
                user_id=moderate_user.id,
                step="clustering",
                label="needs_validation",
            ),
        ]
    )
    db_session.commit()

    payload = client.get(
        "/api/runs/compare/pair",
        headers=moderate_auth,
        params={"original": original.id, "alternate": alternate.id},
    ).json()

    assert [row["key"] for row in payload["changedSettings"]] == ["sc.cluster.resolution"]
    moved = {row["metric"]: row["direction"] for row in payload["metrics"] if row["changed"]}
    assert moved["cluster.n_clusters"] == "increase"
    assert payload["changedConclusions"] == [
        {"step": "clustering", "before": "supported", "after": "needs_validation"}
    ]


def test_moderate_may_export_the_full_report(
    client, moderate_auth, db_session, fixture_dataset, moderate_user
):
    run = Run(
        user_id=moderate_user.id,
        dataset_id=fixture_dataset.id,
        track=AnalysisTrack.CORE,
        access_tier=AccessTier.MODERATE,
        pipeline_version="core-1.0.0",
        status=RunStatus.COMPLETED,
    )
    db_session.add(run)
    db_session.commit()
    report = client.post(
        "/api/reports",
        headers=moderate_auth,
        json={"run_id": run.id, "export_format": "pdf_full"},
    )
    assert report.status_code == 201
    content = report.json()["content"]
    assert "aiAudit" in content and "perturbations" in content


# ------------------------------------------------------------- billing ----
def test_basic_is_never_sold(client, auth):
    options = client.get("/api/billing/catalogue", headers=auth).json()["options"]
    assert "basic" not in {option["tier"] for option in options}
    refused = client.post("/api/billing/checkout", headers=auth, json={"tier": "basic"})
    assert refused.status_code == 422


def test_checkout_records_an_order_without_granting_access(client, auth, db_session, learner):
    from app.core.access import effective_tier

    order = client.post("/api/billing/checkout", headers=auth, json={"tier": "moderate"})
    assert order.status_code == 201
    assert order.json()["status"] == "awaiting_payment"
    # Access is unchanged until payment is confirmed.
    assert effective_tier(db_session, learner.id) is AccessTier.BASIC


def test_activation_grants_a_terminating_entitlement_and_is_idempotent(
    client, auth, admin_auth, db_session, learner
):
    from app.core.access import effective_tier

    purchase_id = client.post(
        "/api/billing/checkout", headers=auth, json={"tier": "moderate"}
    ).json()["id"]

    first = client.post(
        f"/api/admin/purchases/{purchase_id}/activate",
        headers=admin_auth,
        json={"provider_reference": "ref-1"},
    ).json()
    assert first["expiresAt"] is not None
    assert effective_tier(db_session, learner.id) is AccessTier.MODERATE

    second = client.post(
        f"/api/admin/purchases/{purchase_id}/activate",
        headers=admin_auth,
        json={"provider_reference": "ref-1"},
    ).json()
    assert second["entitlementId"] == first["entitlementId"]
    grants = db_session.query(Entitlement).filter(Entitlement.user_id == learner.id).all()
    assert len([g for g in grants if g.tier == AccessTier.MODERATE]) == 1


def test_buying_a_tier_already_held_is_refused(client, moderate_auth):
    response = client.post(
        "/api/billing/checkout", headers=moderate_auth, json={"tier": "moderate"}
    )
    assert response.status_code == 409


def test_expiry_view_states_what_is_retained(client, moderate_auth):
    payload = client.get("/api/billing/expiry", headers=moderate_auth).json()
    assert "never deletes prior work" in payload["note"]
