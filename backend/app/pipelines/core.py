"""Core pipeline — single-cell RNA-seq (spec 4.2).

Scientific track name only; it carries no commercial meaning.

The condition contrast in this pipeline is always sample-aware: counts are
aggregated to pseudobulk profiles per sample and cell type before any test, so
the replicate unit is the donor rather than the cell.
"""

from typing import Dict, List

import numpy as np
from scipy import sparse, stats

from app.constants import PIPELINE_VERSIONS, AnalysisTrack
from app.pipelines import locked, reference as ref
from app.pipelines.base import Pipeline, Step, StepContext, StepFailure


def _validate(ctx: StepContext) -> Dict[str, object]:
    n_cells, n_genes = ctx.data.matrix.shape
    obs = ctx.data.obs
    if len(obs) != n_cells:
        raise StepFailure(
            "The expression matrix has a different number of cells than the cell "
            "annotation table has rows.",
            f"matrix rows={n_cells}, obs rows={len(obs)}",
        )
    for field in ("sample_id", "condition"):
        if not all(field in row for row in obs):
            raise StepFailure(
                f"Every cell must carry a '{field}' annotation. Without sample "
                f"identity, condition effects cannot be tested with the sample as "
                f"the unit of replication."
            )
    samples = sorted({row["sample_id"] for row in obs})
    conditions = sorted({row["condition"] for row in obs})
    per_condition = {
        c: len({row["sample_id"] for row in obs if row["condition"] == c}) for c in conditions
    }
    return {
        "n_cells": int(n_cells),
        "n_genes": int(n_genes),
        "n_samples": len(samples),
        "samples": samples,
        "conditions": conditions,
        "samples_per_condition": per_condition,
        "min_replicates": int(min(per_condition.values())) if per_condition else 0,
    }


def _cell_qc(ctx: StepContext) -> Dict[str, object]:
    matrix = np.asarray(ctx.data.matrix)
    n_input = matrix.shape[0]
    counts_per_cell = matrix.sum(axis=1)
    genes_per_cell = (matrix > 0).sum(axis=1)
    mito_mask = np.array([str(g).upper().startswith("MT-") for g in ctx.data.var])
    with np.errstate(invalid="ignore", divide="ignore"):
        mito_pct = np.where(
            counts_per_cell > 0, matrix[:, mito_mask].sum(axis=1) / counts_per_cell * 100, 0.0
        )

    keep = (
        (genes_per_cell >= ctx.parameters["sc.qc.min_genes"])
        & (genes_per_cell <= ctx.parameters["sc.qc.max_genes"])
        & (counts_per_cell >= ctx.parameters["sc.qc.min_counts"])
        & (mito_pct <= ctx.parameters["sc.qc.max_mito_pct"])
    )

    n_doublets = 0
    if ctx.parameters["sc.qc.doublet_filter"]:
        doublets = locked.scrublet_doublet_scores(matrix)
        n_doublets = int(doublets["predicted"].sum())
        keep &= ~doublets["predicted"]

    if not keep.any():
        raise StepFailure(
            "Quality control removed every cell. Relax the gene, count or "
            "mitochondrial thresholds — the current settings describe no cell in "
            "this dataset."
        )

    ctx.data.matrix = matrix[keep]
    ctx.data.obs = [row for row, k in zip(ctx.data.obs, keep) if k]
    per_sample_loss = {}
    for sample in {row["sample_id"] for row in ctx.data.obs}:
        before = sum(1 for row in ctx.data.meta.get("obs_before", []) if row["sample_id"] == sample)
        after = sum(1 for row in ctx.data.obs if row["sample_id"] == sample)
        if before:
            per_sample_loss[sample] = round((1 - after / before) * 100, 1)

    return {
        "n_cells_input": int(n_input),
        "n_cells_kept": int(keep.sum()),
        "n_doublets_flagged": n_doublets,
        "median_genes_per_cell": float(np.median(genes_per_cell[keep])),
        "median_mito_pct": round(float(np.median(mito_pct[keep])), 2),
        "pct_cells_lost_per_sample": per_sample_loss,
    }


def _feature_selection(ctx: StepContext) -> Dict[str, object]:
    matrix = np.asarray(ctx.data.matrix, dtype=float)
    totals = matrix.sum(axis=1, keepdims=True)
    totals[totals == 0] = 1.0
    normalised = np.log1p(matrix / totals * 1e4)
    ctx.data.layers["normalised"] = normalised

    considered = int((matrix.sum(axis=0) > 0).sum())
    n_top = min(ctx.parameters["sc.hvg.n_top_genes"], considered)
    if n_top < 2:
        raise StepFailure(
            "Too few genes are detected after quality control to select a "
            "variable gene set."
        )
    dispersion = normalised.var(axis=0)
    hvg_index = np.argsort(dispersion)[::-1][:n_top]
    ctx.data.meta["hvg_index"] = hvg_index
    pct_in_hvgs = float(matrix[:, hvg_index].sum() / max(matrix.sum(), 1) * 100)
    return {
        "n_genes_considered": considered,
        "n_hvgs": int(n_top),
        "pct_counts_in_hvgs": round(pct_in_hvgs, 1),
    }


def _dimensionality_reduction(ctx: StepContext) -> Dict[str, object]:
    normalised = ctx.data.layers["normalised"][:, ctx.data.meta["hvg_index"]]
    result = ref.pca(normalised.T, n_components=ctx.parameters["sc.pca.n_comps"])
    coordinates = np.asarray(result["coordinates"])
    ctx.data.layers["pca"] = coordinates
    ctx.data.layers["connectivities"] = _knn_graph(coordinates, ctx.parameters["sc.neighbors.k"])
    ratio = np.asarray(result["variance_ratio"])
    return {
        "n_comps": int(coordinates.shape[1]),
        "variance_ratio": [round(float(v), 5) for v in ratio],
        "cumulative_variance_pct": round(float(ratio.sum()) * 100, 1),
    }


def _knn_graph(coordinates: np.ndarray, k: int) -> "sparse.csr_matrix":
    n = coordinates.shape[0]
    k = int(min(k, max(n - 1, 1)))
    distances = np.linalg.norm(coordinates[:, None, :] - coordinates[None, :, :], axis=2)
    np.fill_diagonal(distances, np.inf)
    neighbours = np.argsort(distances, axis=1)[:, :k]
    rows = np.repeat(np.arange(n), k)
    cols = neighbours.ravel()
    weights = 1.0 / (1.0 + distances[rows, cols])
    graph = sparse.csr_matrix((weights, (rows, cols)), shape=(n, n))
    return graph.maximum(graph.T)


def _clustering(ctx: StepContext) -> Dict[str, object]:
    membership = locked.leiden_clustering(
        ctx.data.layers["connectivities"], ctx.parameters["sc.cluster.resolution"]
    )
    ctx.data.meta["clusters"] = membership
    sizes = np.bincount(membership)
    return {
        "n_clusters": int(sizes.size),
        "cluster_sizes": [int(v) for v in sizes],
        "min_cluster_size": int(sizes.min()),
        "max_cluster_size": int(sizes.max()),
        "resolution": ctx.parameters["sc.cluster.resolution"],
    }


def _marker_genes(ctx: StepContext) -> Dict[str, object]:
    normalised = ctx.data.layers["normalised"]
    clusters = ctx.data.meta["clusters"]
    genes = list(ctx.data.var)
    per_cluster: Dict[str, List[dict]] = {}
    for cluster in sorted(set(clusters.tolist())):
        mask = clusters == cluster
        if mask.sum() < 3 or (~mask).sum() < 3:
            per_cluster[str(cluster)] = []
            continue
        stat, pvalues = stats.mannwhitneyu(
            normalised[mask], normalised[~mask], alternative="greater", axis=0
        )
        padj = ref.benjamini_hochberg(pvalues)
        order = np.argsort(padj)
        per_cluster[str(cluster)] = [
            {"gene": genes[i], "padj": float(padj[i]), "statistic": float(stat[i])}
            for i in order[:20]
            if padj[i] < 0.05
        ]
    largest = str(int(np.argmax(np.bincount(clusters))))
    ctx.data.meta["markers"] = per_cluster
    return {
        "test": ctx.parameters["sc.markers.test"],
        "n_clusters_with_markers": sum(1 for rows in per_cluster.values() if rows),
        "top_genes_largest_cluster": [r["gene"] for r in per_cluster[largest][:5]],
        "markers": per_cluster,
    }


def _cell_type_labels(ctx: StepContext) -> List[str]:
    """Learner annotations when present; otherwise the cluster id.

    Cluster ids are used as provisional labels so composition and the condition
    contrast remain computable before annotation, and the report records which
    labels were learner-assigned.
    """
    annotations = ctx.data.meta.get("annotations", {})
    return [str(annotations.get(str(c), f"cluster_{c}")) for c in ctx.data.meta["clusters"]]


def _composition(ctx: StepContext) -> Dict[str, object]:
    cell_types = np.asarray(_cell_type_labels(ctx))
    samples = np.asarray([row["sample_id"] for row in ctx.data.obs])
    table = {}
    for sample in sorted(set(samples.tolist())):
        mask = samples == sample
        total = int(mask.sum())
        table[sample] = {
            ct: round(float((cell_types[mask] == ct).sum()) / total * 100, 2)
            for ct in sorted(set(cell_types.tolist()))
        }
    spreads = {
        ct: [table[s][ct] for s in table] for ct in sorted(set(cell_types.tolist()))
    }
    most_variable = max(spreads, key=lambda ct: max(spreads[ct]) - min(spreads[ct]))
    return {
        "n_samples": len(table),
        "proportions": table,
        "most_variable_population": most_variable,
        "min_proportion_pct": min(spreads[most_variable]),
        "max_proportion_pct": max(spreads[most_variable]),
    }


def _differential_expression(ctx: StepContext) -> Dict[str, object]:
    """Sample-aware contrast. Cell-level testing is not reachable from here."""
    if ctx.parameters["sc.de.grouping"] != "pseudobulk_by_sample":
        raise StepFailure(
            "Condition testing on this platform aggregates to the sample level. "
            "Cell-level condition tests treat correlated cells as independent "
            "replicates and are not available."
        )
    matrix = np.asarray(ctx.data.matrix)
    samples = [row["sample_id"] for row in ctx.data.obs]
    cell_types = _cell_type_labels(ctx)
    aggregated = ref.pseudobulk(
        matrix, samples, cell_types, ctx.parameters["sc.de.min_cells_per_sample"]
    )
    profiles = aggregated["profiles"]
    keys = aggregated["keys"]
    if profiles.shape[0] == 0:
        raise StepFailure(
            "No sample and cell type combination reached the minimum cell count, "
            "so no pseudobulk profile could be built. Lower the minimum cells per "
            "profile or use coarser cell type labels."
        )

    condition_of = {row["sample_id"]: row["condition"] for row in ctx.data.obs}
    genes = list(ctx.data.var)
    threshold = ctx.parameters["sc.de.fdr"]
    results: Dict[str, List[dict]] = {}
    significant_total = 0
    untestable: List[str] = []

    for cell_type in sorted({ct for _, ct in keys}):
        rows = [i for i, (_, ct) in enumerate(keys) if ct == cell_type]
        groups: Dict[str, List[int]] = {}
        for i in rows:
            groups.setdefault(condition_of[keys[i][0]], []).append(i)
        if len(groups) < 2 or any(len(v) < 2 for v in groups.values()):
            untestable.append(cell_type)
            continue
        (label_a, rows_a), (label_b, rows_b) = sorted(groups.items())[:2]
        cpm = ref.cpm_log(profiles.T).T
        stat, pvalues = stats.ttest_ind(cpm[rows_b], cpm[rows_a], axis=0, equal_var=False)
        pvalues = np.nan_to_num(pvalues, nan=1.0)
        padj = ref.benjamini_hochberg(pvalues)
        lfc = cpm[rows_b].mean(axis=0) - cpm[rows_a].mean(axis=0)
        order = np.argsort(padj)
        hits = [
            {
                "gene": genes[i],
                "log2FoldChange": float(lfc[i]),
                "padj": float(padj[i]),
                "contrast": f"{label_b} vs {label_a}",
            }
            for i in order
            if padj[i] < threshold
        ]
        significant_total += len(hits)
        results[cell_type] = hits[:200]

    ctx.data.meta["de_significant_genes"] = sorted(
        {row["gene"] for rows in results.values() for row in rows}
    )
    ctx.data.meta["de_background_genes"] = genes
    return {
        "n_profiles": int(profiles.shape[0]),
        "n_profiles_dropped": len(aggregated["dropped"]),
        "dropped_profiles": aggregated["dropped"],
        "n_cell_types_tested": len(results),
        "untestable_cell_types": untestable,
        "n_significant": int(significant_total),
        "by_cell_type": results,
        "replicate_unit": "sample",
    }


def _pathway(ctx: StepContext) -> Dict[str, object]:
    from app.pipelines.foundation import _pathway as shared_pathway

    return shared_pathway(ctx)


PIPELINE = Pipeline(
    track=AnalysisTrack.CORE,
    version=PIPELINE_VERSIONS[AnalysisTrack.CORE],
    steps=[
        Step("validate", "Validate the single-cell object", [], "validate", _validate),
        Step(
            "cell_qc",
            "Cell quality control",
            [
                "sc.qc.min_genes",
                "sc.qc.max_genes",
                "sc.qc.min_counts",
                "sc.qc.max_mito_pct",
                "sc.qc.doublet_filter",
            ],
            "qc",
            _cell_qc,
            requires_method="doublet_detection",
        ),
        Step(
            "feature_selection",
            "Normalisation and variable genes",
            ["sc.hvg.n_top_genes"],
            "hvg",
            _feature_selection,
        ),
        Step(
            "dimensionality_reduction",
            "Principal components and neighbour graph",
            ["sc.pca.n_comps", "sc.neighbors.k"],
            "pca",
            _dimensionality_reduction,
        ),
        Step(
            "clustering",
            "Leiden clustering",
            ["sc.cluster.resolution"],
            "cluster",
            _clustering,
            requires_method="clustering",
        ),
        Step("marker_genes", "Marker genes", ["sc.markers.test"], "markers", _marker_genes),
        Step("composition", "Cell type composition", [], "composition", _composition),
        Step(
            "differential_expression",
            "Sample-aware differential expression",
            ["sc.de.grouping", "sc.de.fdr", "sc.de.min_cells_per_sample"],
            "de",
            _differential_expression,
        ),
        Step(
            "pathway_analysis",
            "Pathway enrichment",
            ["pathway.fdr", "pathway.min_gene_set_size"],
            "pathway",
            _pathway,
            requires_method="pathway_enrichment",
        ),
    ],
)
