"""Frozen platform vocabulary and locked method choices.

Two vocabularies live here and MUST NOT mix (spec Section 1):

  * ``AnalysisTrack``    -- the scientific dimension  (Foundation / Core / Advanced)
  * ``AccessTier``       -- the commercial dimension  (Basic / Moderate / Expert)

``scripts/lint_naming.py`` fails the build if either vocabulary leaks into the
other's context, so add new labels here rather than as free-standing strings.
"""

from enum import Enum


class AnalysisTrack(str, Enum):
    """Scientific analysis track. Never used to express commercial permission."""

    FOUNDATION = "foundation"  # Bulk RNA-seq
    CORE = "core"  # Single-cell RNA-seq
    ADVANCED = "advanced"  # Spatial transcriptomics


class AccessTier(str, Enum):
    """Commercial access tier. Never used to label a scientific track."""

    BASIC = "basic"
    MODERATE = "moderate"
    EXPERT = "expert"

    @property
    def rank(self) -> int:
        return _TIER_RANK[self]

    def satisfies(self, required: "AccessTier") -> bool:
        return self.rank >= required.rank


_TIER_RANK = {AccessTier.BASIC: 0, AccessTier.MODERATE: 1, AccessTier.EXPERT: 2}

TRACK_LABELS = {
    AnalysisTrack.FOUNDATION: "Foundation — Bulk RNA-seq",
    AnalysisTrack.CORE: "Core — Single-cell RNA-seq",
    AnalysisTrack.ADVANCED: "Advanced — Spatial Transcriptomics",
}

TIER_LABELS = {
    AccessTier.BASIC: "Basic",
    AccessTier.MODERATE: "Moderate",
    AccessTier.EXPERT: "Expert",
}


class RunStatus(str, Enum):
    QUEUED = "queued"
    VALIDATING = "validating"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class InterpretationLabel(str, Enum):
    """Fixed vocabulary (spec 8). The Copilot may not invent new labels."""

    SUPPORTED = "supported"
    PARTIALLY_SUPPORTED = "partially_supported"
    NEEDS_VALIDATION = "needs_validation"
    SPECULATIVE = "speculative"


class AuditAction(str, Enum):
    ACCEPT = "accept"
    MODIFY = "modify"
    REJECT = "reject"
    NEEDS_VALIDATION = "needs_validation"


# --------------------------------------------------------------------------
# Locked method choices (spec 0.4, 5.2, 10). Changing any entry below is a
# pipeline version bump, not an edit: bump PIPELINE_VERSIONS in the same PR and
# route the change through the SME sign-off in docs/method-lock.md.
# --------------------------------------------------------------------------

LOCKED_METHODS = {
    "bulk_statistics": {
        "method": "DESeq2",
        "engine": "R/Bioconductor",
        "model": "negative-binomial GLM, Wald test, BH adjustment",
        "version": "1.42.0",
        "rationale": "Count-based model required by spec 4.1; standard for bulk DE.",
        "sme_signoff": False,
    },
    "single_cell_toolkit": {
        "method": "Scanpy",
        "engine": "Python/AnnData",
        "version": "1.10.1",
        "rationale": "Spec 10 names AnnData/.h5ad as the internal preferred object.",
        "sme_signoff": False,
    },
    "clustering": {
        "method": "Leiden",
        "engine": "leidenalg",
        "version": "0.10.2",
        "rationale": "Spec 10; resolution exposed as a constrained model choice.",
        "sme_signoff": False,
    },
    "embedding": {
        "method": "UMAP",
        "engine": "umap-learn",
        "version": "0.5.12",
        "rationale": (
            "Spec 5.2: neighbours -> UMAP -> Leiden. A layout for looking at the "
            "neighbour graph, not a measurement; the seed is fixed so a run "
            "reproduces."
        ),
        "sme_signoff": False,
    },
    "doublet_detection": {
        "method": "Scrublet",
        "engine": "scanpy.pp.scrublet",
        "version": "1.10.1",
        "rationale": (
            "Chosen and frozen per spec 0.5. Simulation-based, ships inside the "
            "locked Scanpy version so no extra dependency surface, widely "
            "benchmarked on 10x droplet data of the guided GSE96583 type."
        ),
        "sme_signoff": False,
    },
    "pathway_enrichment": {
        "method": "over-representation analysis (hypergeometric) via GSEApy",
        "engine": "gseapy",
        "version": "1.1.3",
        "database": "MSigDB Hallmark (h.all) v2023.2.Hs",
        "gene_id_space": "HGNC symbol",
        "background_rule": "genes detected in the analysed matrix, not the whole genome",
        "rationale": (
            "Chosen and frozen per spec 0.5. Hallmark is small, curated and "
            "non-redundant, which keeps Week 4 interpretable; ID conversion and "
            "background are locked here so results are reproducible."
        ),
        "sme_signoff": False,
    },
    "cell_communication": {
        "method": (
            "mean ligand-receptor expression per cell type pair, with a "
            "cell-label permutation null (the CellPhoneDB statistic)"
        ),
        "engine": "omicslab.pipelines.communication",
        "version": "communication-1.0.0",
        "database": "CellPhoneDB v5 curated ligand-receptor interactions",
        "gene_id_space": "HGNC symbol",
        "rationale": (
            "Chosen and frozen per spec 0.5/5.2 before the module was built, so "
            "no runtime tool switching is possible without revalidation. The "
            "statistic is fully specified and computed in the validated "
            "pipeline; the curated interaction database is the external asset "
            "and is version-locked alongside it, exactly as the pathway "
            "collection is."
        ),
        "phase": 2,
        "sme_signoff": False,
    },
    "spatial_deconvolution": {
        "method": "Cell2location",
        "engine": "cell2location",
        "version": "0.1.4",
        "rationale": (
            "Chosen and frozen per spec 0.5. Estimates cell type abundance per "
            "spot from a compatible reference; its output is compositional and is "
            "surfaced as such, never as a single-cell identity per spot."
        ),
        "phase": 2,
        "sme_signoff": False,
    },
    "spatially_variable_genes": {
        "method": "Moran's I spatial autocorrelation with a permutation null",
        "engine": "omicslab.pipelines.reference",
        "version": "advanced-1.0.0",
        "rationale": (
            "Chosen and frozen per spec 0.5. A single closed-form, interpretable "
            "statistic for spatial structure, computed on the locked spatial "
            "graph inside the validated pipeline."
        ),
        "phase": 2,
        "sme_signoff": False,
    },
    "spatial_graph": {
        "method": "capture-grid ring adjacency, with kNN, radius and Delaunay "
        "alternatives restricted to platforms that have no regular grid",
        "engine": "omicslab.pipelines.reference",
        "version": "advanced-1.0.0",
        "rationale": (
            "Chosen and frozen per spec 0.5/7. Geometry is exactly specified by "
            "the capture platform, so it is computed in the validated pipeline "
            "rather than delegated; only platform-compatible geometries are "
            "offered."
        ),
        "phase": 2,
        "sme_signoff": False,
    },
}

# Version stamped onto every run record (spec 10). Bump on any method change.
PIPELINE_VERSIONS = {
    AnalysisTrack.FOUNDATION: "foundation-1.0.0",
    AnalysisTrack.CORE: "core-1.1.0",
    AnalysisTrack.ADVANCED: "advanced-1.0.0",
}

#: Extension pipelines that run on a track's data but are their own versioned
#: workflow, so a change to one does not silently revise a guided run.
MODULE_PIPELINE_VERSIONS = {
    "core_communication": "communication-1.0.0",
}

# Phase gate (spec 12). Modules above the active phase are not routable.
#
# Phase 1 shipped the free Basic experience; Phase 2 added the Moderate paid
# upgrade (trial datasets, reruns, wider parameter ranges, the communication
# explorer, the spatial workflow, Compare Runs, full exports, purchase); Phase 3
# added the Expert premium tier (upload, custom contrasts, advanced spatial and
# reference options, extended perturbations, the capstone workspace).
#
# Raw sequencing processing remains gated behind a separate compute, storage and
# security sign-off and is not scaffolded here.
ACTIVE_PHASE = 3
