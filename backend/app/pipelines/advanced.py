"""Advanced pipeline — spatial transcriptomics (spec 4.3).

Scientific track name only; it carries no commercial meaning.

Two hard rules are enforced by this pipeline rather than by UI copy:

  * Spot-level cell type estimates are compositional and probabilistic. Every
    output carrying them is stamped ``estimate_kind = "compositional"`` and
    ``per_spot_identity = False``.
  * When the package holds a single specimen, any region comparison is
    descriptive and hypothesis-generating. The comparison output is stamped
    ``inference_scope``, and the Copilot's label rules downgrade conclusions
    drawn from it.
"""

from typing import Dict, List

import numpy as np
from scipy import sparse, stats

from app.constants import PIPELINE_VERSIONS, AnalysisTrack
from app.pipelines import locked, reference as ref
from app.pipelines.base import BackendUnavailable, Pipeline, Step, StepContext, StepFailure

#: Cap on the spots and genes serialised into a tissue map, so a run record
#: stays a record rather than a copy of the matrix.
MAP_SPOT_LIMIT = 2000
MAP_GENE_LIMIT = 4


def _validate(ctx: StepContext) -> Dict[str, object]:
    n_spots, n_genes = ctx.data.matrix.shape
    obs = ctx.data.obs
    if len(obs) != n_spots:
        raise StepFailure(
            "The expression matrix has a different number of spots than the spot "
            "annotation table has rows.",
            f"matrix rows={n_spots}, obs rows={len(obs)}",
        )
    for field in ("spot_id", "x", "y"):
        if not all(field in row for row in obs):
            raise StepFailure(
                f"Every spot must carry a '{field}' value. Without coordinates "
                f"there is no spatial analysis to do, only an expression matrix."
            )

    has_grid = all("array_row" in row and "array_col" in row for row in obs)
    sections = sorted({str(row.get("section_id", "section1")) for row in obs})
    specimens = sorted({str(row.get("specimen_id", row.get("section_id", "specimen1"))) for row in obs})
    conditions = sorted({str(row["condition"]) for row in obs if "condition" in row})

    return {
        "n_spots": int(n_spots),
        "n_genes": int(n_genes),
        "n_sections": len(sections),
        "n_specimens": len(specimens),
        "sections": sections,
        "conditions": conditions,
        "platform": str(ctx.data.meta.get("platform", "unspecified")),
        "has_capture_grid": has_grid,
        # Stated up front so the learner reads every later result knowing it.
        "inference_scope": (
            "descriptive_single_specimen" if len(specimens) < 2 else "multi_specimen"
        ),
    }


def _spatial_qc(ctx: StepContext) -> Dict[str, object]:
    matrix = np.asarray(ctx.data.matrix)
    n_input = matrix.shape[0]
    counts = matrix.sum(axis=1)
    genes = (matrix > 0).sum(axis=1)

    keep = (counts >= ctx.parameters["spatial.qc.min_counts_per_spot"]) & (
        genes >= ctx.parameters["spatial.qc.min_genes_per_spot"]
    )
    if not keep.any():
        raise StepFailure(
            "Quality control removed every spot. Lower the count or gene floor — "
            "the current settings describe no spot on this section."
        )

    ctx.data.matrix = matrix[keep]
    ctx.data.obs = [row for row, k in zip(ctx.data.obs, keep) if k]

    return {
        "n_spots_input": int(n_input),
        "n_spots_kept": int(keep.sum()),
        "median_counts_per_spot": float(np.median(counts[keep])),
        "median_genes_per_spot": float(np.median(genes[keep])),
        "note": (
            "Spots are removed for depth, not for being uninteresting. Check the "
            "removed positions against the tissue image before trusting the "
            "filter: a block of removed spots can be a tear, a fold, or real "
            "acellular tissue."
        ),
    }


def _feature_selection(ctx: StepContext) -> Dict[str, object]:
    matrix = np.asarray(ctx.data.matrix, dtype=float)
    totals = matrix.sum(axis=1, keepdims=True)
    totals[totals == 0] = 1.0
    normalised = np.log1p(matrix / totals * 1e4)
    ctx.data.layers["normalised"] = normalised

    considered = int((matrix.sum(axis=0) > 0).sum())
    n_top = int(min(ctx.parameters["sc.hvg.n_top_genes"], considered))
    if n_top < 2:
        raise StepFailure("Too few genes are detected after quality control to continue.")
    hvg_index = np.argsort(normalised.var(axis=0))[::-1][:n_top]
    ctx.data.meta["hvg_index"] = hvg_index
    return {"n_genes_considered": considered, "n_hvgs": n_top}


def _neighborhood_graph(ctx: StepContext) -> Dict[str, object]:
    geometry = ctx.parameters["spatial.graph.type"]
    obs = ctx.data.obs
    has_grid = all("array_row" in row and "array_col" in row for row in obs)

    if geometry == "grid" and not has_grid:
        raise StepFailure(
            "This package has no capture-grid positions, so ring adjacency "
            "cannot be built for it. Choose a geometry the platform supports.",
        )
    if geometry != "grid" and has_grid:
        # Not fatal, but the learner should know they left the measured geometry.
        ctx.data.meta["geometry_note"] = (
            "This platform captures on a regular array, so ring adjacency "
            "reflects what the assay measured. The geometry you chose imposes a "
            "different neighbourhood on the same spots."
        )

    coordinates = np.array([[float(row["x"]), float(row["y"])] for row in obs])
    grid = (
        np.array([[int(row["array_row"]), int(row["array_col"])] for row in obs])
        if has_grid
        else None
    )
    try:
        graph = ref.spatial_graph(
            coordinates,
            geometry,
            n_rings=ctx.parameters["spatial.graph.n_rings"],
            n_neighbors=ctx.parameters["spatial.graph.n_neighbors"],
            radius=ctx.parameters["spatial.graph.radius"],
            grid=grid,
        )
    except ValueError as exc:
        raise StepFailure(str(exc))

    ctx.data.layers["spatial_graph"] = graph
    degrees = np.asarray(graph.sum(axis=1)).ravel()
    return {
        "geometry": geometry,
        "n_edges": int(graph.nnz // 2),
        "median_neighbours": float(np.median(degrees)),
        "isolated_spots": int((degrees == 0).sum()),
        "note": ctx.data.meta.get("geometry_note", ""),
    }


def _spatially_variable_genes(ctx: StepContext) -> Dict[str, object]:
    normalised = ctx.data.layers["normalised"]
    hvg_index = ctx.data.meta["hvg_index"]
    genes = list(ctx.data.var)
    result = ref.morans_i(normalised[:, hvg_index], ctx.data.layers["spatial_graph"])

    order = np.argsort(result["padj"])
    n_top = min(ctx.parameters["spatial.svg.n_top"], len(order))
    table = [
        {
            "gene": genes[hvg_index[i]],
            "moransI": float(result["I"][i]),
            "pvalue": float(result["pvalue"][i]),
            "padj": float(result["padj"][i]),
        }
        for i in order[:n_top]
    ]
    significant = [row for row in table if row["padj"] < ctx.parameters["pathway.fdr"]]
    ctx.data.meta["svg_genes"] = [row["gene"] for row in significant]

    return {
        "n_tested": int(len(hvg_index)),
        "n_significant": len(significant),
        "top_genes": [row["gene"] for row in table[:5]],
        "table": table,
        "gene_maps": _gene_maps(ctx, [row["gene"] for row in table[:MAP_GENE_LIMIT]]),
        "caveat": (
            "Spatial autocorrelation measures whether expression is spatially "
            "structured. It does not say the structure is biologically "
            "meaningful, and it is sensitive to the neighbourhood geometry."
        ),
    }


def _gene_maps(ctx: StepContext, gene_names: List[str]) -> dict:
    """Tissue-aligned values for a few genes, downsampled to stay a record."""
    genes = list(ctx.data.var)
    normalised = ctx.data.layers["normalised"]
    n_spots = normalised.shape[0]
    step = max(1, n_spots // MAP_SPOT_LIMIT)
    index = np.arange(0, n_spots, step)
    coordinates = [
        [float(ctx.data.obs[i]["x"]), float(ctx.data.obs[i]["y"])] for i in index
    ]
    return {
        "coordinates": coordinates,
        "genes": {
            name: [round(float(v), 3) for v in normalised[index, genes.index(name)]]
            for name in gene_names
            if name in genes
        },
        "downsampledEvery": int(step),
    }


def _spatial_domains(ctx: StepContext) -> Dict[str, object]:
    """Communities of spots that are both similar in expression and adjacent."""
    normalised = ctx.data.layers["normalised"][:, ctx.data.meta["hvg_index"]]
    pca = ref.pca(normalised.T, n_components=ctx.parameters["sc.pca.n_comps"])
    coordinates = np.asarray(pca["coordinates"])

    expression_graph = _expression_graph(coordinates, ctx.parameters["sc.neighbors.k"])
    spatial = ctx.data.layers["spatial_graph"]
    # Expression similarity restricted to spots the assay recorded as adjacent,
    # plus the adjacency itself, so a domain is contiguous by construction.
    combined = (expression_graph.multiply(spatial > 0) + spatial * 0.5).tocsr()
    if combined.nnz == 0:
        combined = expression_graph

    membership = locked.leiden_clustering(combined, ctx.parameters["spatial.domains.resolution"])
    ctx.data.meta["domains"] = membership
    sizes = np.bincount(membership)
    return {
        "n_domains": int(sizes.size),
        "domain_sizes": [int(v) for v in sizes],
        "min_domain_size": int(sizes.min()),
        "max_domain_size": int(sizes.max()),
        "resolution": ctx.parameters["spatial.domains.resolution"],
        "assignments": _downsampled_domains(ctx, membership),
        "caveat": (
            "A spatial domain is a model output. It becomes an anatomical region "
            "only when you annotate it against the tissue image and marker "
            "evidence, and that annotation is your claim, not the model's."
        ),
    }


def _expression_graph(coordinates: np.ndarray, k: int) -> "sparse.csr_matrix":
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


def _downsampled_domains(ctx: StepContext, membership: np.ndarray) -> dict:
    n_spots = membership.size
    step = max(1, n_spots // MAP_SPOT_LIMIT)
    index = np.arange(0, n_spots, step)
    return {
        "coordinates": [
            [float(ctx.data.obs[i]["x"]), float(ctx.data.obs[i]["y"])] for i in index
        ],
        "domain": [int(membership[i]) for i in index],
        "downsampledEvery": int(step),
    }


def _reference_mapping(ctx: StepContext) -> Dict[str, object]:
    """Optional deconvolution against a compatible single-cell reference.

    Skipped, and reported as skipped, when no reference is selected. It is never
    run against an incompatible reference.
    """
    reference_id = ctx.parameters.get("spatial.mapping.reference_dataset") or ""
    if not reference_id:
        return {
            "performed": False,
            "reason": (
                "No single-cell reference was selected, so no cell type "
                "composition was estimated for this section."
            ),
            "estimate_kind": "none",
            "per_spot_identity": False,
        }

    resolved = ctx.data.meta.get("reference_dataset")
    if resolved is None:
        raise StepFailure(
            "A reference dataset was named but could not be resolved. Reference "
            "mapping did not run."
        )
    try:
        locked.assert_reference_compatible(ctx.data.meta["spatial_dataset"], resolved)
        estimates = locked.cell2location_deconvolve(
            ctx.data.matrix, list(ctx.data.var), None, [], []
        )
    except BackendUnavailable:
        raise
    return {
        "performed": True,
        "estimates": estimates,
        # Stamped on the output itself so no caller can present it otherwise.
        "estimate_kind": "compositional",
        "per_spot_identity": False,
        "confidence_cutoff": ctx.parameters["spatial.mapping.confidence_cutoff"],
        "caveat": (
            "These are estimated proportions of cell types within the mixture "
            "captured under each spot. They are probabilistic and compositional, "
            "and are never the identity of a single cell."
        ),
    }


def _neighborhood_analysis(ctx: StepContext) -> Dict[str, object]:
    results = ref.neighborhood_enrichment(
        ctx.data.meta["domains"], ctx.data.layers["spatial_graph"]
    )
    significant = [row for row in results if row["padj"] < ctx.parameters["pathway.fdr"]]
    return {
        "n_pairs_tested": len(results),
        "n_significant": len(significant),
        "table": results,
        "caveat": (
            "Adjacency describes how the tissue is organised. Two domains sitting "
            "together is not evidence that they interact."
        ),
    }


def _region_comparison(ctx: StepContext) -> Dict[str, object]:
    """Compare expression between the two largest domains.

    With one specimen this is a description of one section, not an inference
    about a population, and the output says so.
    """
    domains = ctx.data.meta["domains"]
    normalised = ctx.data.layers["normalised"]
    genes = list(ctx.data.var)
    sizes = np.bincount(domains)
    if sizes.size < 2:
        raise StepFailure(
            "Only one spatial domain was detected, so there are no regions to "
            "compare. Raise the domain resolution or revisit quality control."
        )
    first, second = np.argsort(sizes)[::-1][:2]
    mask_a, mask_b = domains == first, domains == second

    stat, pvalues = stats.mannwhitneyu(
        normalised[mask_b], normalised[mask_a], alternative="two-sided", axis=0
    )
    pvalues = np.nan_to_num(pvalues, nan=1.0)
    padj = ref.benjamini_hochberg(pvalues)
    difference = normalised[mask_b].mean(axis=0) - normalised[mask_a].mean(axis=0)
    order = np.argsort(padj)
    threshold = ctx.parameters["pathway.fdr"]
    hits = [
        {
            "gene": genes[i],
            "difference": float(difference[i]),
            "padj": float(padj[i]),
        }
        for i in order
        if padj[i] < threshold
    ]

    ctx.data.meta["de_significant_genes"] = [row["gene"] for row in hits]
    ctx.data.meta["de_background_genes"] = genes
    scope = ctx.outputs.get("validate", {}).get("inference_scope", "descriptive_single_specimen")

    return {
        "regionA": f"domain_{int(first)}",
        "regionB": f"domain_{int(second)}",
        "n_significant": len(hits),
        "table": hits[:300],
        "replicate_unit": "spot",
        "inference_scope": scope,
        "caveat": (
            "Spots within one section are not independent biological replicates. "
            "This comparison describes how two regions of this section differ; it "
            "is hypothesis-generating and does not support a claim about "
            "patients or conditions."
            if scope == "descriptive_single_specimen"
            else "Spots within a section are not independent replicates. Treat "
            "the specimen as the replication unit for any condition claim."
        ),
    }


def _pathway(ctx: StepContext) -> Dict[str, object]:
    from app.pipelines.foundation import _pathway as shared_pathway

    return shared_pathway(ctx)


PIPELINE = Pipeline(
    track=AnalysisTrack.ADVANCED,
    version=PIPELINE_VERSIONS[AnalysisTrack.ADVANCED],
    steps=[
        Step("validate", "Validate the spatial package", [], "validate", _validate),
        Step(
            "spatial_qc",
            "Spatial quality control",
            ["spatial.qc.min_counts_per_spot", "spatial.qc.min_genes_per_spot"],
            "qc",
            _spatial_qc,
        ),
        Step(
            "feature_selection",
            "Normalisation and variable genes",
            ["sc.hvg.n_top_genes"],
            "hvg",
            _feature_selection,
        ),
        Step(
            "neighborhood_graph",
            "Spatial neighbourhood graph",
            [
                "spatial.graph.type",
                "spatial.graph.n_rings",
                "spatial.graph.n_neighbors",
                "spatial.graph.radius",
            ],
            "graph",
            _neighborhood_graph,
            requires_method="spatial_graph",
        ),
        Step(
            "spatially_variable_genes",
            "Spatially variable genes and gene maps",
            ["spatial.svg.n_top", "pathway.fdr"],
            "svg",
            _spatially_variable_genes,
            requires_method="spatially_variable_genes",
        ),
        Step(
            "spatial_domains",
            "Spatial domains",
            ["spatial.domains.resolution", "sc.pca.n_comps", "sc.neighbors.k"],
            "domains",
            _spatial_domains,
            requires_method="clustering",
        ),
        Step(
            "reference_mapping",
            "Reference mapping and deconvolution",
            ["spatial.mapping.reference_dataset", "spatial.mapping.confidence_cutoff"],
            "mapping",
            _reference_mapping,
        ),
        Step(
            "neighborhood_analysis",
            "Neighbourhood analysis",
            ["pathway.fdr"],
            "neighborhood",
            _neighborhood_analysis,
        ),
        Step(
            "region_comparison",
            "Region comparison",
            ["pathway.fdr"],
            "region",
            _region_comparison,
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
