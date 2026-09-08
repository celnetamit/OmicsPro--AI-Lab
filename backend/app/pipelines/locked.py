"""Adapters to the locked scientific runtimes.

Each function here is the *only* route to its method. If the runtime is not
provisioned, the adapter raises ``BackendUnavailable`` and the run fails with a
readable message — it never falls back to a different algorithm, because the
method version stamped on the run record must remain true (spec 10, 14.6).
"""

import json
import os
from typing import Any, Dict, List, Sequence

import numpy as np

from app.constants import LOCKED_METHODS
from app.pipelines.base import BackendUnavailable
from app.settings import settings


def _unavailable(method_key: str, install_hint: str) -> BackendUnavailable:
    method = LOCKED_METHODS[method_key]
    return BackendUnavailable(
        f"{method['method']} {method['version']} is the locked method for this "
        f"step and is not available in this environment. {install_hint} "
        f"No substitute method is used, because the method version recorded "
        f"against a run must match what actually ran."
    )


def deseq2_differential_expression(
    counts: np.ndarray,
    gene_names: Sequence[str],
    sample_metadata: List[dict],
    design_formula: str,
    reference_group: str,
    condition_field: str = "condition",
) -> Dict[str, object]:
    """Negative-binomial GLM with Wald test, via the locked R/DESeq2 runtime."""
    try:
        from rpy2 import robjects  # noqa: F401
        from rpy2.robjects.packages import importr
    except ImportError:
        raise _unavailable(
            "bulk_statistics",
            "Provision the R worker image, which carries R, Bioconductor and rpy2.",
        )
    try:
        deseq2 = importr("DESeq2")
    except Exception:
        raise _unavailable(
            "bulk_statistics", "The R runtime is present but DESeq2 is not installed."
        )
    return _run_deseq2(
        deseq2, counts, gene_names, sample_metadata, design_formula,
        reference_group, condition_field,
    )


def _run_deseq2(deseq2, counts, gene_names, sample_metadata, design_formula,
                reference_group, condition_field):
    from rpy2 import robjects
    from rpy2.robjects import pandas2ri
    import pandas as pd

    with (robjects.default_converter + pandas2ri.converter).context():
        count_df = pd.DataFrame(
            np.asarray(counts, dtype=int),
            index=list(gene_names),
            columns=[row["sample_id"] for row in sample_metadata],
        )
        col_df = pd.DataFrame(sample_metadata).set_index("sample_id")
        col_df[condition_field] = pd.Categorical(
            col_df[condition_field],
            categories=[reference_group]
            + [c for c in col_df[condition_field].unique() if c != reference_group],
        )
        dds = deseq2.DESeqDataSetFromMatrix(
            countData=count_df, colData=col_df, design=robjects.Formula(design_formula)
        )
        dds = deseq2.DESeq(dds)
        results = robjects.r["as.data.frame"](deseq2.results(dds))

    return {
        "gene": list(results.index),
        "log2FoldChange": [float(v) for v in results["log2FoldChange"]],
        "pvalue": [float(v) for v in results["pvalue"]],
        "padj": [float(v) for v in results["padj"]],
        "method_version": LOCKED_METHODS["bulk_statistics"]["version"],
    }


def leiden_clustering(connectivities, resolution: float) -> np.ndarray:
    """Community detection via the locked Leiden implementation."""
    try:
        import leidenalg
        import igraph
    except ImportError:
        raise _unavailable(
            "clustering",
            "Provision the single-cell worker image, which carries leidenalg and igraph.",
        )
    sources, targets = connectivities.nonzero()
    graph = igraph.Graph(
        n=connectivities.shape[0],
        edges=list(zip(sources.tolist(), targets.tolist())),
        directed=False,
    )
    graph.es["weight"] = connectivities[sources, targets].A1.tolist()
    partition = leidenalg.find_partition(
        graph,
        leidenalg.RBConfigurationVertexPartition,
        resolution_parameter=resolution,
        weights="weight",
        seed=0,
    )
    return np.asarray(partition.membership)


def scrublet_doublet_scores(counts) -> Dict[str, np.ndarray]:
    """Predicted-doublet scores from the locked detection method."""
    try:
        import scanpy as sc
        import anndata as ad
    except ImportError:
        raise _unavailable(
            "doublet_detection",
            "Provision the single-cell worker image, which carries Scanpy.",
        )
    adata = ad.AnnData(np.asarray(counts))
    sc.pp.scrublet(adata, random_state=0)
    return {
        "score": np.asarray(adata.obs["doublet_score"]),
        "predicted": np.asarray(adata.obs["predicted_doublet"], dtype=bool),
    }


def load_gene_sets() -> Dict[str, List[str]]:
    """Load the locked curated gene set collection.

    Gene identifier space and background rule are fixed in ``LOCKED_METHODS`` so
    an enrichment result is reproducible across releases.
    """
    method = LOCKED_METHODS["pathway_enrichment"]
    path = os.path.join(settings.data_dir, "gene_sets", "hallmark.json")
    if not os.path.exists(path):
        raise BackendUnavailable(
            f"The locked gene set collection ({method['database']}, "
            f"{method['gene_id_space']} identifiers) is not present at {path}. "
            f"Run scripts/fetch_gene_sets.py to install it. No alternative "
            f"collection is substituted."
        )
    with open(path) as handle:
        return json.load(handle)


def load_ligand_receptor_pairs() -> List[Dict[str, object]]:
    """Load the locked curated ligand-receptor interaction database.

    The statistic is computed in the validated pipeline; this curated database
    is the external asset it reads, and it is version-locked the same way the
    pathway collection is. No substitute database is accepted, because the set
    of interactions tested defines what the module can and cannot find.
    """
    method = LOCKED_METHODS["cell_communication"]
    path = os.path.join(settings.data_dir, "interactions", "ligand_receptor.json")
    if not os.path.exists(path):
        raise BackendUnavailable(
            f"The locked ligand-receptor database ({method['database']}, "
            f"{method['gene_id_space']} identifiers) is not present at {path}. "
            f"Run scripts/fetch_interactions.py to install it. No alternative "
            f"interaction set is substituted."
        )
    with open(path) as handle:
        pairs = json.load(handle)
    if not isinstance(pairs, list) or not pairs:
        raise BackendUnavailable(
            f"The ligand-receptor database at {path} is empty or malformed."
        )
    return pairs


def cell2location_deconvolve(
    spot_counts,
    spot_genes: Sequence[str],
    reference_profiles,
    reference_cell_types: Sequence[str],
    reference_genes: Sequence[str],
):
    """Estimate cell type abundance per spot from a compatible reference.

    The output is compositional: it describes the mixture captured under a spot,
    never the identity of a single cell. Callers must surface it as such.
    """
    try:
        import cell2location  # noqa: F401
    except ImportError:
        raise _unavailable(
            "spatial_deconvolution",
            "Provision the spatial worker image, which carries cell2location and "
            "its GPU or CPU inference dependencies.",
        )
    raise _unavailable(
        "spatial_deconvolution",
        "The package is importable but the platform's validated inference "
        "wrapper has not been provisioned in this environment.",
    )


def assert_reference_compatible(spatial_dataset, reference_dataset) -> None:
    """Refuse an incompatible reference before any estimate is produced.

    An incompatible reference yields confident-looking abundances for cell types
    that were never in the section, which is worse than no estimate at all.
    """
    problems = []
    spatial_meta = spatial_dataset.validation_report or {}
    reference_meta = reference_dataset.validation_report or {}

    tissue = spatial_meta.get("tissue")
    reference_tissue = reference_meta.get("tissue")
    if tissue and reference_tissue and tissue != reference_tissue:
        problems.append(
            f"the section is {tissue} and the reference is {reference_tissue}"
        )
    if reference_dataset.track != "core":
        problems.append("the reference must be a single-cell dataset")
    if reference_dataset.validation_status != "validated":
        problems.append("the reference has not passed validation")

    if problems:
        raise BackendUnavailable(
            "This reference is not compatible with the selected section: "
            + "; ".join(problems)
            + ". Deconvolution against an incompatible reference reports cell "
            "types that were never in the tissue."
        )
