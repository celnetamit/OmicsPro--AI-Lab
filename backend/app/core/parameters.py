"""Parameter registry — every adjustable scientific setting in one place.

Spec 7: no undocumented hard-coded threshold may exist anywhere else in the
codebase. Each parameter declares a method rule (why it exists), a default, a
safe range per tier scope, and the message shown when validation fails.

Tier constraint is expressed as three nested scopes — ``limited`` (Basic),
``full`` (Moderate), ``extended`` (Expert) — resolved through
``entitlements.allowance(tier).parameter_scope`` so there is exactly one
entitlement system, not two.
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from app.constants import AccessTier, AnalysisTrack
from app.core.entitlements import allowance

SCOPES = ("limited", "full", "extended")


@dataclass(frozen=True)
class Parameter:
    key: str
    label: str
    #: The track a parameter belongs to. ``None`` means it applies everywhere;
    #: a tuple means it is shared by exactly those tracks. Kept explicit so a
    #: setting cannot drift into a pipeline that does not read it.
    track: Union[AnalysisTrack, Tuple[AnalysisTrack, ...], None]
    step: str
    kind: str  # "int" | "float" | "choice" | "dataset_choice" | "bool" | "formula"
    default: Any
    method_rule: str
    validation_message: str
    #: Inclusive numeric bounds per scope, widest last. ``None`` for non-numeric.
    ranges: Optional[Dict[str, Tuple[float, float]]] = None
    #: Allowed values per scope, for ``choice`` parameters.
    choices: Optional[Dict[str, Sequence[Any]]] = None
    #: Extra copy shown next to the control, e.g. "model choice, not biology".
    caveat: str = ""

    def applies_to(self, track: AnalysisTrack) -> bool:
        if self.track is None:
            return True
        if isinstance(self.track, tuple):
            return track in self.track
        return self.track is track

    @property
    def track_values(self) -> Optional[List[str]]:
        if self.track is None:
            return None
        if isinstance(self.track, tuple):
            return [t.value for t in self.track]
        return [self.track.value]

    def bounds_for(self, scope: str) -> Optional[Tuple[float, float]]:
        if self.ranges is None:
            return None
        # Scopes are nested: fall back to the widest scope at or below the one
        # requested so a parameter need not restate identical bounds.
        for candidate in reversed(SCOPES[: SCOPES.index(scope) + 1]):
            if candidate in self.ranges:
                return self.ranges[candidate]
        return None

    def choices_for(self, scope: str) -> Optional[Sequence[Any]]:
        if self.choices is None:
            return None
        for candidate in reversed(SCOPES[: SCOPES.index(scope) + 1]):
            if candidate in self.choices:
                return self.choices[candidate]
        return None


class ParameterError(ValueError):
    """Invalid parameter value. Carries the registry's validation message."""


def _p(**kw) -> Parameter:
    return Parameter(**kw)


_REGISTRY: List[Parameter] = [
    # ---- Foundation (Bulk RNA-seq) ------------------------------------
    _p(
        key="bulk.filter.min_counts",
        label="Minimum counts per gene",
        track=AnalysisTrack.FOUNDATION,
        step="low_information_filtering",
        kind="int",
        default=10,
        method_rule=(
            "Genes with almost no counts carry no information and inflate the "
            "multiple-testing burden. Filtering before DE is a variance-"
            "stabilisation and power decision, not a biological one."
        ),
        validation_message="Minimum counts per gene must be between {min} and {max}.",
        ranges={"limited": (5, 20), "full": (1, 100), "extended": (0, 1000)},
    ),
    _p(
        key="bulk.filter.min_samples",
        label="Minimum samples expressing a gene",
        track=AnalysisTrack.FOUNDATION,
        step="low_information_filtering",
        kind="int",
        default=3,
        method_rule=(
            "A gene must be detected in at least as many samples as the smallest "
            "group, otherwise the model fits a group with no observations."
        ),
        validation_message="Minimum samples must be between {min} and {max}.",
        ranges={"limited": (2, 4), "full": (1, 12), "extended": (1, 100)},
    ),
    _p(
        key="bulk.design.formula",
        label="Design formula",
        track=AnalysisTrack.FOUNDATION,
        step="statistical_design",
        kind="formula",
        default="~ condition",
        method_rule=(
            "The design formula states which sources of variation the negative-"
            "binomial GLM adjusts for. Batch belongs here, not in a post-hoc "
            "correction of the counts."
        ),
        validation_message=(
            "Custom design formulas require the Expert tier. Guided analyses use "
            "the validated design for this dataset."
        ),
        choices={
            "limited": ["~ condition"],
            "full": ["~ condition", "~ batch + condition"],
            # Expert may author a formula; validated against dataset metadata.
            "extended": None,
        },
    ),
    _p(
        key="bulk.design.reference_group",
        label="Reference group",
        track=AnalysisTrack.FOUNDATION,
        step="statistical_design",
        # Valid values come from the selected dataset's metadata, so they are
        # resolved at run time rather than enumerated here.
        kind="dataset_choice",
        default="untreated",
        method_rule=(
            "Log2 fold changes are reported relative to the reference group, so "
            "the sign of every result depends on this choice."
        ),
        validation_message="Reference group must be a condition present in the sample metadata.",
    ),
    _p(
        key="bulk.de.fdr",
        label="FDR threshold",
        track=AnalysisTrack.FOUNDATION,
        step="differential_expression",
        kind="float",
        default=0.05,
        method_rule=(
            "Benjamini-Hochberg adjusted p-value cutoff. It controls the expected "
            "proportion of false discoveries among called genes — it is not a "
            "measure of effect size."
        ),
        validation_message="FDR threshold must be between {min} and {max}.",
        ranges={"limited": (0.01, 0.1), "full": (0.001, 0.2), "extended": (0.0001, 0.5)},
    ),
    # ---- Core (scRNA-seq) ---------------------------------------------
    _p(
        key="sc.qc.min_genes",
        label="Minimum genes per cell",
        track=AnalysisTrack.CORE,
        step="cell_qc",
        kind="int",
        default=200,
        method_rule=(
            "Barcodes with very few detected genes are usually empty droplets or "
            "debris rather than cells."
        ),
        validation_message="Minimum genes per cell must be between {min} and {max}.",
        ranges={"limited": (100, 500), "full": (50, 1500), "extended": (0, 5000)},
    ),
    _p(
        key="sc.qc.max_genes",
        label="Maximum genes per cell",
        track=AnalysisTrack.CORE,
        step="cell_qc",
        kind="int",
        default=2500,
        method_rule=(
            "An unusually high gene count can indicate a doublet. This is a "
            "heuristic that should agree with the doublet score, not replace it."
        ),
        validation_message="Maximum genes per cell must be between {min} and {max}.",
        ranges={"limited": (1500, 5000), "full": (800, 10000), "extended": (500, 50000)},
    ),
    _p(
        key="sc.qc.min_counts",
        label="Minimum counts per cell",
        track=AnalysisTrack.CORE,
        step="cell_qc",
        kind="int",
        default=500,
        method_rule="Total UMI floor; removes low-complexity barcodes.",
        validation_message="Minimum counts per cell must be between {min} and {max}.",
        ranges={"limited": (200, 1500), "full": (100, 5000), "extended": (0, 50000)},
    ),
    _p(
        key="sc.qc.max_mito_pct",
        label="Maximum mitochondrial fraction (%)",
        track=AnalysisTrack.CORE,
        step="cell_qc",
        kind="float",
        default=5.0,
        method_rule=(
            "A high mitochondrial fraction indicates stressed or lysing cells. "
            "The appropriate cutoff is tissue-dependent; 5% suits PBMCs and is "
            "too strict for many solid tissues."
        ),
        validation_message="Mitochondrial fraction must be between {min}% and {max}%.",
        ranges={"limited": (2.0, 15.0), "full": (1.0, 30.0), "extended": (0.0, 100.0)},
    ),
    _p(
        key="sc.qc.doublet_filter",
        label="Remove predicted doublets",
        track=AnalysisTrack.CORE,
        step="cell_qc",
        kind="bool",
        default=True,
        method_rule=(
            "Doublet calls come from the locked detection method (see "
            "LOCKED_METHODS['doublet_detection']). Predictions are probabilistic; "
            "a flagged barcode is a candidate doublet, not a confirmed one."
        ),
        validation_message="Doublet filtering must be true or false.",
    ),
    _p(
        key="sc.hvg.n_top_genes",
        label="Highly variable genes",
        track=(AnalysisTrack.CORE, AnalysisTrack.ADVANCED),
        step="feature_selection",
        kind="int",
        default=2000,
        method_rule=(
            "HVG selection defines the feature space every downstream step sees. "
            "Too few genes hides structure; too many amplifies technical noise."
        ),
        validation_message="Highly variable gene count must be between {min} and {max}.",
        ranges={"limited": (1000, 3000), "full": (500, 5000), "extended": (200, 20000)},
    ),
    _p(
        key="sc.pca.n_comps",
        label="Principal components",
        track=(AnalysisTrack.CORE, AnalysisTrack.ADVANCED),
        step="dimensionality_reduction",
        kind="int",
        default=30,
        method_rule=(
            "PCs retained for the neighbourhood graph. Judge against the variance "
            "ratio elbow rather than picking a round number."
        ),
        validation_message="Principal components must be between {min} and {max}.",
        ranges={"limited": (15, 50), "full": (5, 100), "extended": (2, 200)},
    ),
    _p(
        key="sc.neighbors.k",
        label="Neighbours (k)",
        track=(AnalysisTrack.CORE, AnalysisTrack.ADVANCED),
        step="neighborhood_graph",
        kind="int",
        default=15,
        method_rule=(
            "Graph connectivity. Small k fragments the graph into many small "
            "clusters; large k smooths real distinctions away."
        ),
        validation_message="Neighbour count must be between {min} and {max}.",
        ranges={"limited": (10, 30), "full": (5, 100), "extended": (2, 300)},
    ),
    _p(
        key="sc.cluster.resolution",
        label="Leiden resolution",
        track=AnalysisTrack.CORE,
        step="clustering",
        kind="float",
        default=1.0,
        method_rule=(
            "Resolution controls how finely the graph is partitioned. There is no "
            "correct value: it is chosen so clusters are supported by markers."
        ),
        caveat=(
            "Resolution is a model choice, not biological truth. Changing it "
            "changes the number of clusters without changing the underlying cells."
        ),
        validation_message="Leiden resolution must be between {min} and {max}.",
        ranges={"limited": (0.4, 1.5), "full": (0.1, 3.0), "extended": (0.01, 10.0)},
    ),
    _p(
        key="sc.markers.test",
        label="Marker test",
        track=AnalysisTrack.CORE,
        step="marker_genes",
        kind="choice",
        default="wilcoxon",
        method_rule=(
            "Marker ranking compares cells within one dataset and is descriptive. "
            "It is not a test of a condition effect — see sc.de.grouping."
        ),
        validation_message="Marker test must be one of: {choices}.",
        choices={"limited": ["wilcoxon"], "full": ["wilcoxon", "t-test_overestim_var", "logreg"]},
    ),
    _p(
        key="sc.de.grouping",
        label="Condition DE grouping",
        track=AnalysisTrack.CORE,
        step="differential_expression",
        kind="choice",
        default="pseudobulk_by_sample",
        method_rule=(
            "Cells from one donor are not independent biological replicates. "
            "Condition inference must aggregate to the sample level "
            "(pseudobulk) so the replicate unit is the donor, not the cell."
        ),
        caveat=(
            "Cell-level condition tests are disabled platform-wide: they treat "
            "thousands of correlated cells as independent samples and produce "
            "p-values that are not interpretable."
        ),
        validation_message=(
            "Condition DE must be sample-aware. Cell-level testing across "
            "conditions is not an available option on this platform."
        ),
        # Deliberately single-valued at every scope, including Expert.
        choices={"limited": ["pseudobulk_by_sample"]},
    ),
    _p(
        key="sc.de.fdr",
        label="FDR threshold",
        track=AnalysisTrack.CORE,
        step="differential_expression",
        kind="float",
        default=0.05,
        method_rule="BH-adjusted p-value cutoff on the pseudobulk model.",
        validation_message="FDR threshold must be between {min} and {max}.",
        ranges={"limited": (0.01, 0.1), "full": (0.001, 0.2), "extended": (0.0001, 0.5)},
    ),
    _p(
        key="sc.de.min_cells_per_sample",
        label="Minimum cells per pseudobulk sample",
        track=AnalysisTrack.CORE,
        step="differential_expression",
        kind="int",
        default=10,
        method_rule=(
            "A pseudobulk profile built from a handful of cells is unstable; "
            "sample/cell-type combinations below this floor are dropped and "
            "reported rather than silently included."
        ),
        validation_message="Minimum cells per pseudobulk sample must be between {min} and {max}.",
        ranges={"limited": (10, 50), "full": (3, 200), "extended": (1, 1000)},
    ),
    # ---- Shared: pathway analysis --------------------------------------
    _p(
        key="pathway.fdr",
        label="Enrichment FDR threshold",
        track=None,
        step="pathway_analysis",
        kind="float",
        default=0.05,
        method_rule=(
            "Over-representation is tested against the locked background rule "
            "(genes detected in the analysed matrix), not the whole genome."
        ),
        validation_message="Enrichment FDR threshold must be between {min} and {max}.",
        ranges={"limited": (0.01, 0.1), "full": (0.001, 0.25), "extended": (0.0001, 0.5)},
    ),
    _p(
        key="pathway.min_gene_set_size",
        label="Minimum gene set size",
        track=None,
        step="pathway_analysis",
        kind="int",
        default=15,
        method_rule=(
            "Very small gene sets produce unstable enrichment statistics driven "
            "by one or two genes."
        ),
        validation_message="Minimum gene set size must be between {min} and {max}.",
        ranges={"limited": (10, 50), "full": (5, 200), "extended": (2, 500)},
    ),
    # ---- Foundation, Expert-authored statistical design ------------------
    _p(
        key="bulk.design.contrast",
        label="Contrast",
        track=AnalysisTrack.FOUNDATION,
        step="statistical_design",
        kind="formula",
        default="",
        method_rule=(
            "A contrast names which two levels of a design term are compared. "
            "Leaving it empty compares the non-reference level against the "
            "reference. Authoring one only makes sense for a design with more "
            "than two levels or an interaction term."
        ),
        validation_message=(
            "Custom contrasts require the Expert tier, and every term must exist "
            "in the design formula and the sample metadata."
        ),
        choices={"limited": [""], "full": [""], "extended": None},
    ),
    # ---- Advanced (Spatial transcriptomics) -----------------------------
    _p(
        key="spatial.qc.min_counts_per_spot",
        label="Minimum counts per spot",
        track=AnalysisTrack.ADVANCED,
        step="spatial_qc",
        kind="int",
        default=500,
        method_rule=(
            "Spots with very low total counts usually sit off tissue or over a "
            "tear in the section. Removing them prevents empty regions from "
            "appearing as a distinct spatial domain."
        ),
        validation_message="Minimum counts per spot must be between {min} and {max}.",
        ranges={"limited": (200, 2000), "full": (50, 10000), "extended": (0, 100000)},
    ),
    _p(
        key="spatial.qc.min_genes_per_spot",
        label="Minimum genes per spot",
        track=AnalysisTrack.ADVANCED,
        step="spatial_qc",
        kind="int",
        default=200,
        method_rule=(
            "A detection floor per spot, applied for the same reason as the count "
            "floor and checked against the tissue image before it is trusted."
        ),
        validation_message="Minimum genes per spot must be between {min} and {max}.",
        ranges={"limited": (100, 800), "full": (20, 3000), "extended": (0, 10000)},
    ),
    _p(
        key="spatial.svg.n_top",
        label="Spatially variable genes to report",
        track=AnalysisTrack.ADVANCED,
        step="spatially_variable_genes",
        kind="int",
        default=200,
        method_rule=(
            "Genes are ranked by spatial autocorrelation on the locked spatial "
            "graph. The statistic measures whether expression is spatially "
            "structured, not whether the structure is biologically important."
        ),
        validation_message="Spatially variable gene count must be between {min} and {max}.",
        ranges={"limited": (50, 500), "full": (10, 2000), "extended": (5, 10000)},
    ),
    _p(
        key="spatial.domains.resolution",
        label="Spatial domain resolution",
        track=AnalysisTrack.ADVANCED,
        step="spatial_domains",
        kind="float",
        default=0.8,
        method_rule=(
            "Domains are communities of spots detected on a graph that combines "
            "expression similarity with physical adjacency. As with cell "
            "clustering, the number of domains follows from this setting."
        ),
        caveat=(
            "A spatial domain is a model output, not an annotated anatomical "
            "region. Naming a domain is a separate, evidenced step."
        ),
        validation_message="Spatial domain resolution must be between {min} and {max}.",
        ranges={"limited": (0.3, 1.2), "full": (0.1, 2.5), "extended": (0.01, 10.0)},
    ),
    _p(
        key="spatial.graph.type",
        label="Spatial neighbourhood geometry",
        track=AnalysisTrack.ADVANCED,
        step="neighborhood_graph",
        kind="choice",
        default="grid",
        method_rule=(
            "The neighbourhood geometry must match the capture platform. A "
            "hexagonal spot array has a defined ring structure; imposing a "
            "distance radius or a triangulation on it invents adjacencies the "
            "assay did not measure."
        ),
        caveat=(
            "Only geometries compatible with the selected platform are offered. "
            "An incompatible geometry is not a stylistic choice, it is wrong."
        ),
        validation_message="Spatial neighbourhood geometry must be one of: {choices}.",
        choices={
            "limited": ["grid"],
            "full": ["grid", "knn"],
            "extended": ["grid", "knn", "radius", "delaunay"],
        },
    ),
    _p(
        key="spatial.graph.n_rings",
        label="Neighbour rings",
        track=AnalysisTrack.ADVANCED,
        step="neighborhood_graph",
        kind="int",
        default=1,
        method_rule=(
            "How many rings of the capture grid count as a neighbourhood. One "
            "ring is the immediate six neighbours of a hexagonal spot."
        ),
        validation_message="Neighbour rings must be between {min} and {max}.",
        ranges={"limited": (1, 2), "full": (1, 4), "extended": (1, 10)},
    ),
    _p(
        key="spatial.graph.n_neighbors",
        label="Neighbours (k) for a kNN spatial graph",
        track=AnalysisTrack.ADVANCED,
        step="neighborhood_graph",
        kind="int",
        default=6,
        method_rule=(
            "Used only when the geometry is a nearest-neighbour graph rather than "
            "the capture grid."
        ),
        validation_message="Spatial neighbour count must be between {min} and {max}.",
        ranges={"limited": (6, 12), "full": (3, 30), "extended": (2, 100)},
    ),
    _p(
        key="spatial.graph.radius",
        label="Neighbourhood radius",
        track=AnalysisTrack.ADVANCED,
        step="neighborhood_graph",
        kind="float",
        default=0.0,
        method_rule=(
            "Physical distance defining a neighbourhood, in the coordinate units "
            "of the capture package. Used only with the radius geometry, which is "
            "available where the platform has no regular grid."
        ),
        validation_message="Neighbourhood radius must be between {min} and {max}.",
        ranges={"limited": (0.0, 0.0), "full": (0.0, 0.0), "extended": (0.0, 5000.0)},
    ),
    _p(
        key="spatial.mapping.confidence_cutoff",
        label="Reference mapping confidence cutoff",
        track=AnalysisTrack.ADVANCED,
        step="reference_mapping",
        kind="float",
        default=0.3,
        method_rule=(
            "Estimated cell type abundances below this proportion of a spot are "
            "reported as low confidence. The estimate is compositional: it "
            "describes the mixture captured under a spot, never the identity of a "
            "single cell."
        ),
        caveat=(
            "Spot-level cell type estimates are probabilistic and compositional. "
            "They must never be read as exact single-cell identities."
        ),
        validation_message="Mapping confidence cutoff must be between {min} and {max}.",
        ranges={"limited": (0.2, 0.5), "full": (0.05, 0.8), "extended": (0.0, 1.0)},
    ),
    _p(
        key="spatial.mapping.reference_dataset",
        label="Reference dataset for mapping",
        track=AnalysisTrack.ADVANCED,
        step="reference_mapping",
        # Valid values are the compatible references available to this user, so
        # they are resolved against the dataset catalogue at run time.
        kind="dataset_choice",
        default="",
        method_rule=(
            "Deconvolution can only use a single-cell reference from a compatible "
            "tissue and platform. An incompatible reference produces confident "
            "looking estimates of cell types that were never in the section."
        ),
        validation_message=(
            "The reference must be a compatible single-cell dataset you have "
            "access to. Reference selection requires the Expert tier."
        ),
    ),
    # ---- Cell-cell communication (Core extension module) -----------------
    _p(
        key="comm.min_cells_per_type",
        label="Minimum cells per cell type",
        track=AnalysisTrack.CORE,
        step="communication",
        kind="int",
        default=25,
        method_rule=(
            "Ligand and receptor expression summarised over a handful of cells is "
            "unstable, and an unstable summary produces confident looking "
            "interactions that do not reproduce."
        ),
        validation_message="Minimum cells per cell type must be between {min} and {max}.",
        ranges={"limited": (25, 100), "full": (10, 500), "extended": (3, 2000)},
    ),
    _p(
        key="comm.min_expression_pct",
        label="Minimum percent of cells expressing",
        track=AnalysisTrack.CORE,
        step="communication",
        kind="float",
        default=10.0,
        method_rule=(
            "A ligand or receptor counts as present in a cell type when at least "
            "this percentage of its cells detect it. Detection in single-cell "
            "data is sparse, so a low floor admits noise."
        ),
        validation_message="Minimum percent expressing must be between {min}% and {max}%.",
        ranges={"limited": (5.0, 25.0), "full": (1.0, 50.0), "extended": (0.0, 100.0)},
    ),
    _p(
        key="comm.interaction_fdr",
        label="Interaction FDR threshold",
        track=AnalysisTrack.CORE,
        step="communication",
        kind="float",
        default=0.05,
        method_rule=(
            "Adjusted significance for the permutation test on each candidate "
            "ligand-receptor pair between two cell types."
        ),
        caveat=(
            "A significant pair is a candidate inferred from co-expression. It is "
            "not evidence that the two cells touched or signalled."
        ),
        validation_message="Interaction FDR threshold must be between {min} and {max}.",
        ranges={"limited": (0.01, 0.1), "full": (0.001, 0.2), "extended": (0.0001, 0.5)},
    ),
]

REGISTRY: Dict[str, Parameter] = {p.key: p for p in _REGISTRY}


def get(key: str) -> Parameter:
    try:
        return REGISTRY[key]
    except KeyError:
        raise KeyError(
            f"Unknown parameter '{key}'. Scientific settings must be declared in "
            f"the parameter registry, never hard-coded at the call site."
        )


def scope_for(tier: AccessTier) -> str:
    return allowance(tier).parameter_scope


def defaults_for(track: AnalysisTrack) -> Dict[str, Any]:
    return {p.key: p.default for p in _REGISTRY if p.applies_to(track)}


def describe_for(track: AnalysisTrack, tier: AccessTier) -> List[dict]:
    """Registry view the parameter panel renders, already tier-constrained."""
    scope = scope_for(tier)
    out = []
    for p in _REGISTRY:
        if not p.applies_to(track):
            continue
        bounds = p.bounds_for(scope)
        choices = p.choices_for(scope)
        out.append(
            {
                "key": p.key,
                "label": p.label,
                "step": p.step,
                "kind": p.kind,
                "default": p.default,
                "methodRule": p.method_rule,
                "caveat": p.caveat,
                "min": bounds[0] if bounds else None,
                "max": bounds[1] if bounds else None,
                "choices": list(choices) if choices else None,
                # Free-text authoring (Expert design formulas) is signalled by a
                # declared choice list that resolves to None at this scope.
                "freeform": p.choices is not None and choices is None,
            }
        )
    return out


def validate(key: str, value: Any, tier: AccessTier) -> Any:
    """Coerce and bounds-check one value against the tier's scope.

    Raises ``ParameterError`` carrying the registry's own validation message.
    """
    p = get(key)
    scope = scope_for(tier)

    if p.kind == "bool":
        if not isinstance(value, bool):
            raise ParameterError(p.validation_message)
        return value

    if p.kind in ("int", "float"):
        try:
            value = int(value) if p.kind == "int" else float(value)
        except (TypeError, ValueError):
            raise ParameterError(_msg(p, scope))
        bounds = p.bounds_for(scope)
        if bounds and not (bounds[0] <= value <= bounds[1]):
            raise ParameterError(_msg(p, scope))
        return value

    choices = p.choices_for(scope)
    if choices is None:
        if p.choices is None:
            # Free-text with no declared choice list (e.g. reference group);
            # membership is checked by the pipeline against dataset metadata.
            return value
        # Declared but unrestricted at this scope: Expert free authoring.
        if scope != "extended":
            raise ParameterError(_msg(p, scope))
        return value
    if value not in choices:
        raise ParameterError(_msg(p, scope))
    return value


def validate_many(values: Dict[str, Any], track: AnalysisTrack, tier: AccessTier) -> Dict[str, Any]:
    """Validate a full parameter set, filling registry defaults for omissions."""
    resolved = defaults_for(track)
    errors: Dict[str, str] = {}
    for key, value in values.items():
        p = get(key)
        if not p.applies_to(track):
            errors[key] = f"'{p.label}' does not apply to this analysis track."
            continue
        try:
            resolved[key] = validate(key, value, tier)
        except ParameterError as exc:
            errors[key] = str(exc)
    if errors:
        raise ParameterError(errors)
    return resolved


def _msg(p: Parameter, scope: str) -> str:
    bounds = p.bounds_for(scope)
    choices = p.choices_for(scope)
    return p.validation_message.format(
        min=bounds[0] if bounds else "-",
        max=bounds[1] if bounds else "-",
        choices=", ".join(str(c) for c in choices) if choices else "-",
    )
