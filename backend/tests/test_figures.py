"""Spec 10.7: the analysis workspace shows a step's results as plots and tables.

A figure is drawn from the run's recorded output. The platform never offers a
figure it holds no computed value for, and the workspace and the capstone
figure pack read the same catalogue.
"""

import numpy as np

from app.constants import AccessTier, AnalysisTrack, RunStatus
from app.core import parameters as params
from app.core.figures import CATALOGUE_BY_ID, FIGURE_CATALOGUE, figure_context, figures_for_namespace
from app.models import Run
from app.pipelines import registry, runner
from app.pipelines.base import DataObject
from app.pipelines.registry import MODULES, PIPELINES


def _cells(n_cells=200, n_genes=600) -> DataObject:
    """Four donors in two conditions; the stimulated donors lift forty genes."""
    rng = np.random.default_rng(1)
    genes = [f"GENE{i:03d}" for i in range(n_genes - 2)] + ["MT-A", "MT-B"]
    obs, blocks = [], []
    for donor in range(4):
        condition = "stimulated" if donor % 2 else "control"
        block = rng.negative_binomial(6, 0.3, size=(n_cells // 4, n_genes))
        if condition == "stimulated":
            block[:, :40] *= 4
        blocks.append(block)
        obs.extend(
            {"cell_id": f"d{donor}_c{i}", "sample_id": f"donor{donor}", "condition": condition, "batch": "b1"}
            for i in range(n_cells // 4)
        )
    return DataObject(matrix=np.vstack(blocks), obs=obs, var=genes, track=AnalysisTrack.CORE)


def _completed_core_run(db_session, learner, dataset) -> str:
    #: Doublet detection needs the locked Scrublet runtime, which the test
    #: environment does not carry; none of the figures under test depend on it.
    run = Run(
        user_id=learner.id,
        dataset_id=dataset.id,
        track=AnalysisTrack.CORE,
        access_tier=AccessTier.BASIC,
        pipeline_version=registry.get(AnalysisTrack.CORE).version,
        parameters={**params.defaults_for(AnalysisTrack.CORE), "sc.qc.doublet_filter": False},
        is_original=True,
    )
    db_session.add(run)
    db_session.commit()
    runner.execute(db_session, run, _cells())
    assert run.status == RunStatus.COMPLETED, run.error_message
    return run.id


def _figures(client, auth, run_id, step) -> dict:
    response = client.get(f"/api/runs/{run_id}/figures", headers=auth, params={"step": step})
    assert response.status_code == 200
    return {figure["id"]: figure for figure in response.json()}


def test_every_figure_is_bound_to_an_output_a_pipeline_publishes():
    published = {
        step.publishes
        for pipeline in [*PIPELINES.values(), *(m["pipeline"] for m in MODULES.values())]
        for step in pipeline.steps
    }
    for figure in FIGURE_CATALOGUE:
        assert figure["namespace"] in published, figure["id"]


def test_figure_ids_saved_in_capstones_still_resolve():
    """A capstone stores figure ids; renaming one would orphan a saved selection."""
    assert {
        "qc_summary", "variance_ratio", "cluster_sizes", "composition", "de_volcano",
        "pathway_table", "sample_structure", "gene_maps", "domain_map", "neighborhood",
        "interaction_network",
    } <= set(CATALOGUE_BY_ID)


def test_the_embedding_step_draws_the_umap_layout_with_cluster_membership(
    client, auth, learner, db_session, fixture_dataset
):
    run_id = _completed_core_run(db_session, learner, fixture_dataset)
    drawn = _figures(client, auth, run_id, "embedding")
    assert set(drawn) == {"umap"}
    layout = drawn["umap"]
    assert layout["kind"] == "embedding"
    assert len(layout["data"]["x"]) == len(layout["data"]["y"]) > 0
    # Each drawn point carries its cluster, so the layout reads against the
    # clustering without a second request.
    assert len(layout["context"]["membership"]) == len(layout["data"]["x"])


def test_a_step_draws_only_what_it_computed(client, auth, learner, db_session, fixture_dataset):
    run_id = _completed_core_run(db_session, learner, fixture_dataset)
    qc = _figures(client, auth, run_id, "cell_qc")
    assert "qc_summary" in qc
    assert "umap" not in qc and "cluster_sizes" not in qc

    cluster = _figures(client, auth, run_id, "clustering")
    assert sum(cluster["cluster_sizes"]["data"]) > 0

    de = _figures(client, auth, run_id, "differential_expression")
    for figure in de.values():
        # The threshold drawn is the one the run used, not a default.
        assert figure["context"]["fdr"] == db_session.get(Run, run_id).parameters["sc.de.fdr"]

    assert _figures(client, auth, run_id, "no_such_step") == {}


def test_a_figure_with_no_computed_value_is_not_offered():
    run = Run(track="core", module=None, parameters={}, outputs={"cluster": {"cluster_sizes": []}})
    assert figures_for_namespace(run, "cluster") == []
    assert figures_for_namespace(run, "umap") == []


def test_the_threshold_a_figure_draws_is_the_one_the_run_used():
    run = Run(
        track="core",
        module=None,
        parameters={"sc.de.fdr": 0.01},
        outputs={"de": {"by_cell_type": {"T cell": [{"gene": "IL7R", "padj": 0.001}]}}},
    )
    assert figure_context(run, CATALOGUE_BY_ID["de_by_cell_type"])["fdr"] == 0.01


def test_another_learners_run_is_not_drawn(
    client, moderate_auth, learner, db_session, fixture_dataset
):
    run_id = _completed_core_run(db_session, learner, fixture_dataset)
    refused = client.get(
        f"/api/runs/{run_id}/figures", headers=moderate_auth, params={"step": "embedding"}
    )
    assert refused.status_code == 404
