"""TEST / SKIP perturbation catalogue and EXPECTED-vs-ACTUAL reconciliation.

Spec 7 (whitelist of allowed analysis-decision changes), spec 8.1 (hard
interrupt before execution, persisted comparison afterwards).

Phase 1 ships exactly one perturbation type — ``threshold_shift`` — per spec 12.
Later types are declared here with their phase so the catalogue stays the single
whitelist, but they are not offered until their phase is active.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.constants import ACTIVE_PHASE, AnalysisTrack

INCREASE = "increase"
DECREASE = "decrease"
UNCHANGED = "unchanged"
UNCERTAIN = "uncertain"


@dataclass(frozen=True)
class Expectation:
    """Direction and effect only. Never a promised numeric result (spec 8.1)."""

    metric: str
    metric_label: str
    direction: str
    reason: str


@dataclass(frozen=True)
class PerturbationOffer:
    key: str
    kind: str
    track: AnalysisTrack
    step: str
    parameter_key: str
    label: str
    #: How the new value is derived from the current one.
    transform: str  # "scale" | "set"
    transform_value: Any
    scientific_reason: str
    expectations: List[Expectation]
    what_to_observe: str
    limitation: str
    evidence_source_ids: List[str] = field(default_factory=list)
    #: Human-readable description of a "set" transform, for the dialog.
    transform_note: str = ""
    phase: int = 1


CATALOGUE: List[PerturbationOffer] = [
    PerturbationOffer(
        key="bulk.fdr_stricter",
        kind="threshold_shift",
        track=AnalysisTrack.FOUNDATION,
        step="differential_expression",
        parameter_key="bulk.de.fdr",
        label="Tighten the false discovery rate threshold",
        transform="scale",
        transform_value=0.2,
        scientific_reason=(
            "The significance cutoff is a decision about how much false discovery "
            "you accept, not a property of the data. Tightening it shows which "
            "conclusions survive a stricter standard of evidence and which "
            "depended on the threshold you happened to pick."
        ),
        expectations=[
            Expectation(
                "de.n_significant",
                "number of significant genes",
                DECREASE,
                "A stricter adjusted p-value cutoff can only retain a subset of "
                "the genes called before.",
            ),
            Expectation(
                "de.n_tested",
                "number of genes tested",
                UNCHANGED,
                "The cutoff is applied after testing, so the tested set is "
                "unaffected.",
            ),
        ],
        what_to_observe=(
            "Watch whether the genes driving your interpretation are still called. "
            "If your conclusion disappears at a stricter cutoff, it was resting on "
            "the threshold rather than on the effect."
        ),
        limitation=(
            "Surviving a stricter cutoff is evidence of statistical robustness "
            "only. It says nothing about whether the effect size is biologically "
            "meaningful or whether the design was confounded."
        ),
        evidence_source_ids=["love2014", "deseq2_vignette"],
    ),
    PerturbationOffer(
        key="sc.resolution_higher",
        kind="threshold_shift",
        track=AnalysisTrack.CORE,
        step="clustering",
        parameter_key="sc.cluster.resolution",
        label="Raise the clustering resolution",
        transform="scale",
        transform_value=2.0,
        scientific_reason=(
            "Cluster count follows from the resolution you choose. Raising it "
            "tests whether the populations you annotated are stable structure or "
            "an artefact of one setting."
        ),
        expectations=[
            Expectation(
                "cluster.n_clusters",
                "number of clusters",
                INCREASE,
                "A higher resolution penalises large communities, so the same "
                "graph partitions more finely.",
            ),
            Expectation(
                "cluster.min_cluster_size",
                "size of the smallest cluster",
                DECREASE,
                "Finer partitioning splits existing communities into smaller ones.",
            ),
            Expectation(
                "markers.n_clusters_with_markers",
                "clusters with distinguishing markers",
                UNCERTAIN,
                "New clusters may be genuine subtypes with their own markers, or "
                "splits of one population that share a marker profile. Which one "
                "occurred is exactly what this test reveals.",
            ),
        ],
        what_to_observe=(
            "Look at whether the new clusters carry distinct markers or simply "
            "divide a population that shares one profile. The second case is "
            "overclustering."
        ),
        limitation=(
            "Neither resolution is correct in itself. This comparison shows how "
            "sensitive your annotation is to the setting; it does not identify a "
            "true number of cell types."
        ),
        evidence_source_ids=["traag2019", "scanpy_docs"],
    ),
    PerturbationOffer(
        key="sc.mito_stricter",
        kind="threshold_shift",
        track=AnalysisTrack.CORE,
        step="cell_qc",
        parameter_key="sc.qc.max_mito_pct",
        label="Tighten the mitochondrial fraction cutoff",
        transform="scale",
        transform_value=0.5,
        scientific_reason=(
            "The mitochondrial cutoff decides which cells count as viable. A "
            "stricter cutoff tests whether your downstream structure depended on "
            "stressed cells being included."
        ),
        expectations=[
            Expectation(
                "qc.n_cells_kept",
                "number of cells retained",
                DECREASE,
                "A stricter cutoff can only remove more cells.",
            ),
            Expectation(
                "cluster.n_clusters",
                "number of clusters",
                UNCERTAIN,
                "Removing stressed cells may collapse a quality-driven cluster, or "
                "may leave the partition unchanged if no such cluster existed.",
            ),
        ],
        what_to_observe=(
            "Check whether any cluster disappears. A cluster that vanishes when "
            "stressed cells are removed was describing cell quality, not identity."
        ),
        limitation=(
            "A stricter cutoff also removes genuinely viable cell types with "
            "naturally high mitochondrial content. Fewer cells is not automatically "
            "cleaner data."
        ),
        evidence_source_ids=["scanpy_docs", "wolf2018"],
    ),
    # ---- Declared for later phases; not offered while ACTIVE_PHASE is 1 ----
    PerturbationOffer(
        key="bulk.design_add_batch",
        kind="design_change",
        track=AnalysisTrack.FOUNDATION,
        step="statistical_design",
        parameter_key="bulk.design.formula",
        label="Add the batch term to the design formula",
        transform="set",
        transform_value="~ batch + condition",
        scientific_reason=(
            "If samples cluster by batch, the contrast is confounded unless the "
            "model accounts for it."
        ),
        expectations=[
            Expectation(
                "de.n_significant",
                "number of significant genes",
                UNCERTAIN,
                "Adjusting for batch removes confounded signal but also reduces "
                "residual variance, and either effect can dominate.",
            )
        ],
        what_to_observe="Compare which genes are gained and lost, not only the count.",
        limitation="Adjusting for batch cannot rescue a design where batch and "
        "condition are perfectly confounded.",
        evidence_source_ids=["love2014"],
        transform_note="Sets the design formula to include the batch term.",
        phase=2,
    ),
    PerturbationOffer(
        key="sc.hvg_fewer",
        kind="feature_space_change",
        track=AnalysisTrack.CORE,
        step="feature_selection",
        parameter_key="sc.hvg.n_top_genes",
        label="Narrow the variable gene set",
        transform="scale",
        transform_value=0.5,
        scientific_reason=(
            "The variable gene set defines the feature space every later step "
            "sees. Narrowing it tests whether your structure rests on a broad "
            "expression programme or on a smaller set of strong genes."
        ),
        expectations=[
            Expectation(
                "cluster.n_clusters",
                "number of clusters",
                UNCERTAIN,
                "Fewer genes can merge populations that differed only in the "
                "genes removed, or sharpen the partition by dropping noise.",
            ),
            Expectation(
                "hvg.pct_counts_in_hvgs",
                "share of counts inside the variable gene set",
                DECREASE,
                "A smaller gene set necessarily covers fewer of the counts.",
            ),
        ],
        what_to_observe=(
            "Check whether the populations you annotated survive. A cell type "
            "that disappears when the gene set narrows was defined by a handful "
            "of genes."
        ),
        limitation=(
            "This tests sensitivity to the feature space only. Neither gene set "
            "is correct; a stable annotation is one that holds across both."
        ),
        evidence_source_ids=["scanpy_docs", "wolf2018"],
        phase=2,
    ),
    PerturbationOffer(
        key="spatial.resolution_higher",
        kind="threshold_shift",
        track=AnalysisTrack.ADVANCED,
        step="spatial_domains",
        parameter_key="spatial.domains.resolution",
        label="Raise the spatial domain resolution",
        transform="scale",
        transform_value=2.0,
        scientific_reason=(
            "Domain count follows from the resolution. Raising it tests whether "
            "the regions you annotated trace real tissue structure or are an "
            "artefact of one setting."
        ),
        expectations=[
            Expectation(
                "domains.n_domains",
                "number of spatial domains",
                INCREASE,
                "A higher resolution penalises large communities, so the same "
                "graph partitions more finely.",
            ),
            Expectation(
                "domains.min_domain_size",
                "size of the smallest domain",
                DECREASE,
                "Finer partitioning splits existing domains into smaller ones.",
            ),
            Expectation(
                "region.n_significant",
                "genes distinguishing the two largest regions",
                UNCERTAIN,
                "Splitting domains changes which two regions are compared, so "
                "the comparison is not the same one.",
            ),
        ],
        what_to_observe=(
            "Overlay both domain maps on the tissue image. Extra domains that do "
            "not correspond to anything visible are overpartitioning."
        ),
        limitation=(
            "Neither resolution is correct in itself. This shows how sensitive "
            "your region annotation is to the setting."
        ),
        evidence_source_ids=["traag2019", "palla2022"],
        phase=2,
    ),
    PerturbationOffer(
        key="comm.stricter_expression_floor",
        kind="threshold_shift",
        track=AnalysisTrack.CORE,
        step="candidate_pairs",
        parameter_key="comm.min_expression_pct",
        label="Raise the detection floor for ligands and receptors",
        transform="scale",
        transform_value=2.0,
        scientific_reason=(
            "A candidate interaction requires both partners to be detected in "
            "enough cells. Raising the floor tests whether your candidates rest "
            "on solid detection or on a handful of sparse counts."
        ),
        expectations=[
            Expectation(
                "interactions.n_tested",
                "number of interactions tested",
                DECREASE,
                "A stricter floor admits fewer ligand-receptor and cell type "
                "combinations to the test.",
            ),
            Expectation(
                "interactions.n_significant",
                "number of significant interactions",
                DECREASE,
                "Fewer tested combinations can only yield fewer significant ones.",
            ),
        ],
        what_to_observe=(
            "Check whether the candidate driving your mechanism survives. If it "
            "does not, it rested on sparse detection."
        ),
        limitation=(
            "A stricter floor also removes genuinely low-abundance signalling "
            "molecules, which are common. Fewer candidates is not cleaner data."
        ),
        evidence_source_ids=["efremova2020", "armingol2021"],
        phase=2,
    ),
    PerturbationOffer(
        key="spatial.geometry_change",
        kind="geometry_change",
        track=AnalysisTrack.ADVANCED,
        step="neighborhood_graph",
        parameter_key="spatial.graph.type",
        label="Replace capture-grid adjacency with a nearest-neighbour graph",
        transform="set",
        transform_value="knn",
        scientific_reason=(
            "Every spatial statistic is a statement about the neighbourhood "
            "graph. Changing the geometry shows how much of your spatial result "
            "is a property of the tissue and how much is a property of the graph "
            "you built over it."
        ),
        expectations=[
            Expectation(
                "svg.n_significant",
                "number of spatially variable genes",
                UNCERTAIN,
                "A different neighbourhood changes the autocorrelation of every "
                "gene, and the direction depends on how the two geometries "
                "differ on this section.",
            ),
            Expectation(
                "graph.n_edges",
                "edges in the spatial graph",
                UNCERTAIN,
                "The edge count depends on the neighbour count you set against "
                "the ring structure it replaces.",
            ),
        ],
        what_to_observe=(
            "A result that holds under both geometries is about the tissue. One "
            "that appears under only one is about the graph."
        ),
        limitation=(
            "On a regular capture array, ring adjacency is what the assay "
            "measured. A nearest-neighbour graph is a robustness check, not an "
            "equally valid description."
        ),
        evidence_source_ids=["palla2022", "visium_docs"],
        phase=3,
    ),
]

BY_KEY: Dict[str, PerturbationOffer] = {o.key: o for o in CATALOGUE}

#: Whitelist of analysis decisions an Expert learner may change themselves
#: (spec 7). Anything absent is not perturbable at any tier — notably
#: ``sc.de.grouping``, because sample-aware condition testing is not a setting
#: the platform lets anyone trade away.
PERTURBABLE_PARAMETERS = frozenset(
    {offer.parameter_key for offer in CATALOGUE}
    | {
        "bulk.filter.min_counts",
        "bulk.filter.min_samples",
        "sc.qc.min_genes",
        "sc.qc.max_genes",
        "sc.qc.min_counts",
        "sc.pca.n_comps",
        "sc.neighbors.k",
        "sc.de.fdr",
        "sc.de.min_cells_per_sample",
        "pathway.fdr",
        "pathway.min_gene_set_size",
        "spatial.qc.min_counts_per_spot",
        "spatial.qc.min_genes_per_spot",
        "spatial.svg.n_top",
        "spatial.graph.n_rings",
        "spatial.graph.n_neighbors",
        "spatial.mapping.confidence_cutoff",
        "comm.min_cells_per_type",
        "comm.min_expression_pct",
    }
)


def assert_perturbable(parameter_key: str) -> None:
    if parameter_key not in PERTURBABLE_PARAMETERS:
        raise PerturbationNotAllowed(
            f"'{parameter_key}' is not an analysis decision this platform allows "
            f"to be perturbed. Changes must come from the whitelist so that every "
            f"alternate run remains comparable and interpretable."
        )


def custom_expectation(parameter_key: str, before: Any, after: Any) -> List[Expectation]:
    """Expectations for a learner-authored change.

    A self-authored perturbation gets an honest, non-committal expectation
    rather than an invented prediction: the platform has no reviewed statement
    about what an arbitrary value change will do.
    """
    return [
        Expectation(
            metric="__unspecified__",
            metric_label=f"outputs downstream of {parameter_key}",
            direction=UNCERTAIN,
            reason=(
                "You authored this change, so the platform has no reviewed "
                "expectation for it. Write down what you expect before running "
                "it, then compare."
            ),
        )
    ]


class PerturbationNotAllowed(ValueError):
    """A requested change is outside the whitelist or the active phase."""


def available_for(track: AnalysisTrack, step: str) -> List[PerturbationOffer]:
    return [
        o
        for o in CATALOGUE
        if o.track is track and o.step == step and o.phase <= ACTIVE_PHASE
    ]


def get(key: str) -> PerturbationOffer:
    offer = BY_KEY.get(key)
    if offer is None:
        raise PerturbationNotAllowed(
            f"'{key}' is not in the perturbation whitelist. Analysis-decision "
            f"changes must be declared in the catalogue."
        )
    if offer.phase > ACTIVE_PHASE:
        raise PerturbationNotAllowed(
            f"'{offer.label}' is not available in this release."
        )
    return offer


def proposed_value(offer: PerturbationOffer, current: Any) -> Any:
    """Derive the alternate value. Still validated by the parameter registry."""
    if offer.transform == "scale":
        if not isinstance(current, (int, float)) or isinstance(current, bool):
            raise PerturbationNotAllowed(
                f"'{offer.label}' scales a numeric setting, but "
                f"{offer.parameter_key} currently holds a non-numeric value."
            )
        value = current * offer.transform_value
        return int(round(value)) if isinstance(current, int) else round(value, 6)
    return offer.transform_value


def _direction(before: float, after: float) -> str:
    if after > before:
        return INCREASE
    if after < before:
        return DECREASE
    return UNCHANGED


def reconcile(
    offer: PerturbationOffer,
    original_outputs: Dict[str, Any],
    alternate_outputs: Dict[str, Any],
) -> dict:
    """Compare EXPECTED against ACTUAL and explain any divergence (spec 8.1).

    The returned dict is persisted on the perturbation record; it is an
    auditable artifact, not transient UI state.
    """
    from app.copilot.grounding import UngroundedOutputError  # local: avoid cycle

    comparisons = []
    divergences = []
    for expectation in offer.expectations:
        before = _lookup(original_outputs, expectation.metric)
        after = _lookup(alternate_outputs, expectation.metric)
        if before is None or after is None:
            # The metric was not computed in one of the runs; report that
            # honestly rather than inventing a comparison.
            comparisons.append(
                {
                    "metric": expectation.metric,
                    "metricLabel": expectation.metric_label,
                    "expected": expectation.direction,
                    "observed": "not_computed",
                    "matched": None,
                    "before": before,
                    "after": after,
                }
            )
            continue
        observed = _direction(before, after)
        matched = expectation.direction in (UNCERTAIN, observed)
        comparisons.append(
            {
                "metric": expectation.metric,
                "metricLabel": expectation.metric_label,
                "expected": expectation.direction,
                "observed": observed,
                "matched": matched,
                "before": before,
                "after": after,
            }
        )
        if not matched:
            divergences.append((expectation, observed, before, after))

    explanation = _explain_divergence(offer, divergences)
    decided = [c for c in comparisons if c["matched"] is not None]
    return {
        "comparisons": comparisons,
        "matchedExpectation": all(c["matched"] for c in decided) if decided else None,
        "divergenceExplanation": explanation,
        "explanationEvidence": offer.evidence_source_ids,
    }


def _lookup(outputs: Dict[str, Any], path: str) -> Optional[float]:
    node: Any = outputs
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node if isinstance(node, (int, float)) and not isinstance(node, bool) else None


def _explain_divergence(offer: PerturbationOffer, divergences: List[tuple]) -> str:
    """Curated, evidence-linked reasons — never a free-form invented story."""
    if not divergences:
        return (
            "Every stated expectation matched the observed direction. The change "
            "behaved as the method predicts, so the comparison tells you how "
            "sensitive the result is, not that anything went wrong."
        )
    parts = []
    for expectation, observed, before, after in divergences:
        parts.append(
            f"The {expectation.metric_label} was expected to "
            f"{_phrase(expectation.direction)} because {expectation.reason} "
            f"It instead {_phrase_past(observed)}, going from {before} to {after}. "
            f"{_candidate_causes(offer, expectation, observed)}"
        )
    return " ".join(parts)


def _phrase(direction: str) -> str:
    return {
        INCREASE: "increase",
        DECREASE: "decrease",
        UNCHANGED: "stay unchanged",
        UNCERTAIN: "move in either direction",
    }[direction]


def _phrase_past(direction: str) -> str:
    return {INCREASE: "increased", DECREASE: "decreased", UNCHANGED: "stayed unchanged"}[
        direction
    ]


def _candidate_causes(offer: PerturbationOffer, expectation: Expectation, observed: str) -> str:
    if observed == UNCHANGED:
        return (
            "A flat response usually means the setting was not the binding "
            "constraint at this step: something else upstream was already "
            "determining the outcome. Check whether the changed value actually "
            "moved past a value present in the data."
        )
    return (
        "A reversal against the method's expectation points to an interaction "
        "with an earlier step rather than to the parameter itself. Compare the "
        "upstream outputs of the two runs before reading anything biological into "
        "the difference, and treat the result as needing validation."
    )
