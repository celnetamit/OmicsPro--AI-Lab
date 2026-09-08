"""Assignment of the fixed interpretation vocabulary (spec 8).

Only four labels exist and the Copilot cannot mint a fifth: the label is chosen
by the deterministic rules below from the run's own computed evidence, and the
rationale names which rule fired. A learner may revise the label on the audit
record; the AI's original assignment stays immutable.
"""

from typing import Any, Dict, List, Optional, Tuple

from app.constants import InterpretationLabel


class LabelRule:
    """One named, auditable reason for downgrading or supporting a conclusion."""

    def __init__(self, key: str, label: InterpretationLabel, rationale: str):
        self.key = key
        self.label = label
        self.rationale = rationale


#: Ordered worst-first: the first rule that fires sets the label.
RULES: List[Tuple[str, LabelRule]] = [
    (
        "no_replication",
        LabelRule(
            "no_replication",
            InterpretationLabel.SPECULATIVE,
            "The design has fewer than two biological replicates in at least one "
            "condition group, so no condition-level statistical claim is "
            "supportable from this data regardless of the result.",
        ),
    ),
    (
        "single_specimen",
        LabelRule(
            "single_specimen",
            InterpretationLabel.SPECULATIVE,
            "The comparison is drawn within a single specimen, which makes it "
            "descriptive and hypothesis-generating rather than population-level "
            "inference.",
        ),
    ),
    (
        "cell_level_inference",
        LabelRule(
            "cell_level_inference",
            InterpretationLabel.SPECULATIVE,
            "The claim rests on cells treated as independent replicates, which "
            "inflates false discoveries. Sample-aware testing is required before "
            "this can be assessed.",
        ),
    ),
    (
        "no_significant_result",
        LabelRule(
            "no_significant_result",
            InterpretationLabel.NEEDS_VALIDATION,
            "Nothing passed the significance threshold, so the analysis neither "
            "supports nor refutes the hypothesis at the current power.",
        ),
    ),
    (
        "threshold_sensitive",
        LabelRule(
            "threshold_sensitive",
            InterpretationLabel.NEEDS_VALIDATION,
            "The conclusion did not survive a perturbation of its own threshold, "
            "so it depends on the setting rather than on a stable effect.",
        ),
    ),
    (
        "confounded_structure",
        LabelRule(
            "confounded_structure",
            InterpretationLabel.PARTIALLY_SUPPORTED,
            "Sample structure is driven by a factor other than the condition of "
            "interest, so part of the observed difference may be technical.",
        ),
    ),
    (
        "few_supporting_genes",
        LabelRule(
            "few_supporting_genes",
            InterpretationLabel.PARTIALLY_SUPPORTED,
            "The result rests on a small number of genes, which is consistent with "
            "the hypothesis but is not strong evidence on its own.",
        ),
    ),
]

RULES_BY_KEY = {key: rule for key, rule in RULES}

SUPPORTED_RATIONALE = (
    "The design carries biological replication, the effect passed the "
    "significance threshold, and it survived the robustness check that was run. "
    "This is the strongest label available from a single dataset; it is not "
    "independent confirmation."
)


def assign(triggered_rule_keys: List[str]) -> Dict[str, Any]:
    """Pick the label from the rules the evidence triggered."""
    for key, rule in RULES:
        if key in triggered_rule_keys:
            return {
                "label": rule.label.value,
                "rationale": rule.rationale,
                "rule": rule.key,
                "allTriggered": triggered_rule_keys,
            }
    return {
        "label": InterpretationLabel.SUPPORTED.value,
        "rationale": SUPPORTED_RATIONALE,
        "rule": "none_triggered",
        "allTriggered": [],
    }


def evaluate(computed: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> List[str]:
    """Derive which downgrade rules the run's own outputs trigger."""
    context = context or {}
    triggered: List[str] = []

    min_replicates = _get(computed, "validate.min_replicates")
    if min_replicates is not None and min_replicates < 2:
        triggered.append("no_replication")

    n_specimens = _get(computed, "validate.n_specimens")
    if n_specimens is not None and n_specimens < 2:
        triggered.append("single_specimen")

    if context.get("grouping") not in (None, "pseudobulk_by_sample"):
        triggered.append("cell_level_inference")

    n_significant = _get(computed, "de.n_significant")
    if n_significant is not None and n_significant == 0:
        triggered.append("no_significant_result")

    if context.get("perturbation_overturned_conclusion") is True:
        triggered.append("threshold_sensitive")

    dominant = _get(computed, "exploratory.dominant_grouping")
    if dominant is not None and context.get("condition_field") not in (None, dominant):
        triggered.append("confounded_structure")

    if n_significant is not None and 0 < n_significant < 5:
        triggered.append("few_supporting_genes")

    return triggered


def _get(computed: Dict[str, Any], path: str) -> Any:
    node: Any = computed
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node
