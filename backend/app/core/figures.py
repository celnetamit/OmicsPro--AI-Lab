"""Figures a run's computed outputs can be drawn as (spec 5, 10.7, 13).

One catalogue serves both the analysis workspace and the capstone figure pack,
so a figure means the same thing wherever it appears. Every entry is bound to the
output namespace and key a pipeline publishes, and a figure with no computed
output behind it is never offered: the platform draws what was computed and
nothing else.
"""

from typing import List, Optional

from app.constants import AnalysisTrack
from app.models import Run
from app.pipelines import registry

FIGURE_CATALOGUE: List[dict] = [
    {
        "id": "qc_summary",
        "label": "Quality control summary",
        "namespace": "qc",
        "kind": "summary",
        "caption": "Cells or spots retained and removed under the recorded thresholds.",
    },
    {
        "id": "library_sizes",
        "label": "Library size per sample",
        "namespace": "qc",
        "key": "library_sizes",
        "kind": "bar",
        "caption": "Total counts per sample. A sample far below the rest is a depth outlier.",
    },
    {
        "id": "variance_ratio",
        "label": "Principal component variance",
        "namespace": "pca",
        "key": "variance_ratio",
        "kind": "line",
        "caption": "Variance explained by each retained component.",
    },
    {
        "id": "umap",
        "label": "UMAP layout",
        "namespace": "umap",
        "key": "x",
        "kind": "embedding",
        "caption": (
            "Cells placed by UMAP. Distances and areas are properties of the layout, "
            "not measurements."
        ),
    },
    {
        "id": "cluster_sizes",
        "label": "Cluster sizes",
        "namespace": "cluster",
        "key": "cluster_sizes",
        "kind": "bar",
        "caption": "Cells per cluster at the recorded resolution.",
    },
    {
        "id": "markers",
        "label": "Marker genes per cluster",
        "namespace": "markers",
        "key": "markers",
        "kind": "grouped_table",
        "caption": "The genes that most distinguish each cluster under the recorded test.",
    },
    {
        "id": "composition",
        "label": "Cell type composition by sample",
        "namespace": "composition",
        "key": "proportions",
        "kind": "stacked_bar",
        "caption": "Population proportions per sample. Proportions are compositional.",
    },
    {
        "id": "de_summary",
        "label": "What was tested",
        "namespace": "de",
        "kind": "summary",
        "caption": "What the test was run on, with the sample as the replicate, and how much passed the threshold.",
    },
    {
        "id": "de_volcano",
        "label": "Differential expression",
        "namespace": "de",
        "key": "table",
        "kind": "volcano",
        "caption": "Effect size against evidence for the recorded contrast.",
    },
    {
        "id": "de_by_cell_type",
        "label": "Differential expression by cell type",
        "namespace": "de",
        "key": "by_cell_type",
        "kind": "grouped_table",
        "caption": (
            "Genes that pass the threshold in each cell type, tested with the sample "
            "rather than the cell as the replicate."
        ),
    },
    {
        "id": "pathway_table",
        "label": "Pathway enrichment",
        "namespace": "pathway",
        "key": "table",
        "kind": "table",
        "caption": "Enriched gene sets against the detected-gene background.",
    },
    {
        "id": "sample_structure",
        "label": "Sample structure",
        "namespace": "exploratory",
        "key": "coordinates",
        "kind": "scatter",
        "caption": "Samples in principal component space.",
    },
    {
        "id": "gene_maps",
        "label": "Tissue gene maps",
        "namespace": "svg",
        "key": "gene_maps",
        "kind": "spatial_map",
        "caption": "Expression of the most spatially structured genes across the section.",
    },
    {
        "id": "domain_map",
        "label": "Spatial domains",
        "namespace": "domains",
        "key": "assignments",
        "kind": "spatial_map",
        "caption": "Domain assignment per spot. A domain is a model output, not an annotated region.",
    },
    {
        "id": "neighborhood",
        "label": "Neighbourhood adjacency",
        "namespace": "neighborhood",
        "key": "table",
        "kind": "table",
        "caption": "Domain pairs adjacent more often than chance predicts.",
    },
    {
        "id": "interaction_network",
        "label": "Candidate communication network",
        "namespace": "interactions",
        "key": "table",
        "kind": "network",
        "caption": "Inferred candidate ligand-receptor interactions, not demonstrated signalling.",
    },
]

CATALOGUE_BY_ID = {figure["id"]: figure for figure in FIGURE_CATALOGUE}


def figure_data(run: Run, figure: dict) -> Optional[object]:
    """The computed value a figure draws, or None when the run holds none."""
    namespace = (run.outputs or {}).get(figure["namespace"])
    if not namespace:
        return None
    key = figure.get("key")
    if figure["kind"] == "embedding":
        #: A layout is its two coordinate arrays together.
        if "x" not in namespace or "y" not in namespace:
            return None
        return {"x": namespace["x"], "y": namespace["y"]}
    return namespace.get(key) if key else namespace


def _pipeline_of(run: Run):
    """The pipeline this run executed, or None once it is no longer served."""
    try:
        return registry.get(AnalysisTrack(run.track), run.module or None)
    except KeyError:
        return None


def _step_publishing(run: Run, namespace: str):
    pipeline = _pipeline_of(run)
    if pipeline is None:
        return None
    for step in pipeline.steps:
        if step.publishes == namespace:
            return step
    return None


def figure_context(run: Run, figure: dict) -> dict:
    """What a figure needs beyond its own data to be read correctly.

    The threshold line on a volcano is the threshold this run used, read from
    the run's recorded parameters rather than assumed.
    """
    context: dict = {}
    if figure["kind"] == "embedding":
        membership = ((run.outputs or {}).get("cluster") or {}).get("embedding_membership")
        if membership:
            context["membership"] = membership
    step = _step_publishing(run, figure["namespace"])
    if step is not None:
        for key in step.reads_parameters:
            if key.endswith(".fdr") and key in (run.parameters or {}):
                context["fdr"] = run.parameters[key]
    return context


def figures_for_namespace(run: Run, namespace: str) -> List[dict]:
    """Every figure the run can draw from one output namespace."""
    drawn = []
    for figure in FIGURE_CATALOGUE:
        if figure["namespace"] != namespace:
            continue
        data = figure_data(run, figure)
        if data is None or data == [] or data == {}:
            continue
        drawn.append({**figure, "data": data, "context": figure_context(run, figure)})
    return drawn


def figures_for_step(run: Run, step_key: str) -> List[dict]:
    """Every figure one step of this run can draw.

    The step is resolved in the pipeline the run executed, so an extension
    module's step is never confused with a guided step of the same name.
    """
    pipeline = _pipeline_of(run)
    if pipeline is None:
        return []
    for step in pipeline.steps:
        if step.key == step_key:
            return figures_for_namespace(run, step.publishes)
    return []
