"""Foundation pipeline — Bulk RNA-seq (spec 4.1).

Scientific track name only; it carries no commercial meaning.
"""

from typing import Dict

import numpy as np

from app.constants import PIPELINE_VERSIONS, AnalysisTrack
from app.pipelines import locked, reference as ref
from app.pipelines.base import Pipeline, Step, StepContext, StepFailure


def _validate(ctx: StepContext) -> Dict[str, object]:
    obs = ctx.data.obs
    n_genes, n_samples = ctx.data.matrix.shape
    if n_samples != len(obs):
        raise StepFailure(
            "The count matrix has a different number of sample columns than the "
            "sample sheet has rows. Every column must map to exactly one sample.",
            f"matrix columns={n_samples}, metadata rows={len(obs)}",
        )
    conditions = sorted({row["condition"] for row in obs})
    counts_per_condition = {c: sum(1 for r in obs if r["condition"] == c) for c in conditions}
    min_replicates = min(counts_per_condition.values()) if counts_per_condition else 0
    if len(conditions) < 2:
        raise StepFailure(
            "The sample sheet contains only one condition, so there is no "
            "contrast to test. Differential expression needs at least two groups."
        )
    return {
        "n_genes": int(n_genes),
        "n_samples": int(n_samples),
        "conditions": conditions,
        "replicates_per_condition": counts_per_condition,
        "min_replicates": int(min_replicates),
        "n_specimens": len({row.get("donor", row["sample_id"]) for row in obs}),
    }


def _qc(ctx: StepContext) -> Dict[str, object]:
    sizes = ref.library_sizes(ctx.data.matrix)
    detected = ref.detected_genes(ctx.data.matrix)
    smallest = float(sizes.min()) or 1.0
    return {
        "library_sizes": [int(v) for v in sizes],
        "min_library_size": int(sizes.min()),
        "max_library_size": int(sizes.max()),
        "depth_ratio": round(float(sizes.max()) / smallest, 2),
        "detected_genes": [int(v) for v in detected],
        "min_detected_genes": int(detected.min()),
        "max_detected_genes": int(detected.max()),
    }


def _filter(ctx: StepContext) -> Dict[str, object]:
    n_input = int(ctx.data.matrix.shape[0])
    filtered, keep = ref.filter_low_information(
        ctx.data.matrix,
        ctx.parameters["bulk.filter.min_counts"],
        ctx.parameters["bulk.filter.min_samples"],
    )
    if filtered.shape[0] == 0:
        raise StepFailure(
            "The filter removed every gene. Lower the minimum counts or minimum "
            "samples so that genes expressed in this dataset survive.",
        )
    ctx.data.layers["filtered"] = filtered
    ctx.data.meta["kept_genes"] = [g for g, k in zip(ctx.data.var, keep) if k]
    return {"n_genes_input": n_input, "n_genes_kept": int(filtered.shape[0])}


def _exploratory(ctx: StepContext) -> Dict[str, object]:
    matrix = ctx.data.layers.get("filtered", ctx.data.matrix)
    result = ref.pca(ref.cpm_log(matrix), n_components=2)
    ratio = result["variance_ratio"]
    candidates = {
        field: [row[field] for row in ctx.data.obs]
        for field in ("condition", "batch", "donor")
        if all(field in row for row in ctx.data.obs)
    }
    return {
        "pc1_variance_pct": round(float(ratio[0]) * 100, 1),
        "pc2_variance_pct": round(float(ratio[1]) * 100, 1) if len(ratio) > 1 else 0.0,
        "coordinates": np.asarray(result["coordinates"]).tolist(),
        "dominant_grouping": ref.dominant_grouping(result["coordinates"], candidates),
    }


def _differential_expression(ctx: StepContext) -> Dict[str, object]:
    matrix = ctx.data.layers.get("filtered", ctx.data.matrix)
    genes = ctx.data.meta.get("kept_genes", list(ctx.data.var))
    reference_group = ctx.parameters["bulk.design.reference_group"]
    conditions = {row["condition"] for row in ctx.data.obs}
    if reference_group not in conditions:
        raise StepFailure(
            f"The reference group '{reference_group}' is not one of the "
            f"conditions in the sample sheet. Log fold changes are reported "
            f"relative to the reference, so it must be a real group."
        )
    result = locked.deseq2_differential_expression(
        matrix,
        genes,
        ctx.data.obs,
        ctx.parameters["bulk.design.formula"],
        reference_group,
    )
    padj = np.asarray(result["padj"], dtype=float)
    lfc = np.asarray(result["log2FoldChange"], dtype=float)
    threshold = ctx.parameters["bulk.de.fdr"]
    significant = np.nan_to_num(padj, nan=1.0) < threshold
    order = np.argsort(np.nan_to_num(padj, nan=1.0))
    top = [result["gene"][i] for i in order[:5] if significant[i]]
    ctx.data.meta["de_significant_genes"] = [
        result["gene"][i] for i in range(len(significant)) if significant[i]
    ]
    ctx.data.meta["de_background_genes"] = genes
    return {
        "n_tested": int(np.isfinite(padj).sum()),
        "n_significant": int(significant.sum()),
        "n_up": int((significant & (lfc > 0)).sum()),
        "n_down": int((significant & (lfc < 0)).sum()),
        "top_genes": top,
        "table": [
            {
                "gene": result["gene"][i],
                "log2FoldChange": float(lfc[i]),
                "pvalue": float(result["pvalue"][i]),
                "padj": float(padj[i]),
            }
            for i in order[:500]
        ],
        "method_version": result["method_version"],
    }


def _pathway(ctx: StepContext) -> Dict[str, object]:
    query = ctx.data.meta.get("de_significant_genes", [])
    background = ctx.data.meta.get("de_background_genes", list(ctx.data.var))
    if not query:
        return {
            "n_input_genes": 0,
            "n_background_genes": len(background),
            "n_significant_sets": 0,
            "top_sets": [],
            "table": [],
            "note": (
                "No genes passed the differential expression threshold, so there "
                "is nothing to test for enrichment."
            ),
        }
    gene_sets = locked.load_gene_sets()
    rows = ref.hypergeometric_enrichment(
        query, background, gene_sets, ctx.parameters["pathway.min_gene_set_size"]
    )
    threshold = ctx.parameters["pathway.fdr"]
    significant = [r for r in rows if r["padj"] < threshold]
    return {
        "n_input_genes": len(query),
        "n_background_genes": len(background),
        "n_significant_sets": len(significant),
        "top_sets": [r["set"] for r in significant[:5]],
        "table": rows[:100],
    }


PIPELINE = Pipeline(
    track=AnalysisTrack.FOUNDATION,
    version=PIPELINE_VERSIONS[AnalysisTrack.FOUNDATION],
    steps=[
        Step("validate", "Validate matrix and metadata", [], "validate", _validate),
        Step("qc", "Library-size quality control", [], "qc", _qc),
        Step(
            "filter",
            "Low-information gene filtering",
            ["bulk.filter.min_counts", "bulk.filter.min_samples"],
            "filter",
            _filter,
        ),
        Step("exploratory", "Sample structure", [], "exploratory", _exploratory),
        Step(
            "differential_expression",
            "Differential expression",
            ["bulk.design.formula", "bulk.design.reference_group", "bulk.de.fdr"],
            "de",
            _differential_expression,
            requires_method="bulk_statistics",
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
