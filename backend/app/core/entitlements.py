"""Feature Entitlement Matrix — the single source of truth for commercial access.

Spec 2/3.1. Every UI control and every backend endpoint reads its permission
from this module; no module may re-implement a tier check with its own
conditional. The matrix is served to the front end verbatim by
``/api/entitlements/matrix`` so locked features can be rendered visible-but-
locked with the correct upgrade copy (spec 2: never silently hidden).

Governing rule: paid tiers sell depth, repetition, independence, advanced
controls, extra datasets, upload and richer outputs — never the core teaching
content. Anything a learner needs to reach the advertised weekly learning
outcome must have ``min_tier = BASIC``.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from app.constants import AccessTier


@dataclass(frozen=True)
class Feature:
    key: str
    label: str
    min_tier: AccessTier
    #: Shown on the locked control instead of hiding it (spec 2).
    locked_explanation: str
    #: Phase in which the feature becomes routable (spec 12).
    phase: int = 1
    #: True when the feature carries a promised learning outcome that Basic
    #: must always be able to complete. Asserted by the tests.
    teaching_core: bool = False


def _f(key, label, min_tier, locked_explanation, phase=1, teaching_core=False):
    return Feature(key, label, min_tier, locked_explanation, phase, teaching_core)


B, M, E = AccessTier.BASIC, AccessTier.MODERATE, AccessTier.EXPERT

FEATURES: Dict[str, Feature] = {
    f.key: f
    for f in [
        # ---- Teaching core: always Basic ---------------------------------
        _f("knowledge_bank", "Knowledge Bank", B, "", teaching_core=True),
        _f("pre_lab_assessment", "Pre-Lab Assessment", B, "", teaching_core=True),
        _f("design_studio", "Experimental Design Studio", B, "", teaching_core=True),
        _f("guided_dataset", "Guided datasets", B, "", teaching_core=True),
        _f("dataset_inspector", "Dataset Inspector", B, "", teaching_core=True),
        _f("run_guided_pipeline", "Run a guided analysis", B, "", teaching_core=True),
        _f("copilot_explain", "Copilot explanations", B, "", teaching_core=True),
        _f("copilot_interpret", "Copilot interpretation", B, "", teaching_core=True),
        _f("perturbation_guided", "Guided TEST/SKIP perturbation", B, "", teaching_core=True),
        _f("interpretation_panel", "Interpretation Panel", B, "", teaching_core=True),
        _f("ai_audit", "AI Research Audit", B, "", teaching_core=True),
        _f("assessment", "Week assessment", B, "", teaching_core=True),
        _f("report_summary", "Summary report", B, "", teaching_core=True),
        # ---- Moderate: depth, repetition, independence --------------------
        _f(
            "independent_rerun",
            "Rerun an analysis independently",
            M,
            "Moderate unlocks independent reruns so you can repeat an analysis "
            "with your own settings after the guided walkthrough.",
        ),
        _f(
            "parameters_full",
            "Full parameter ranges",
            M,
            "Moderate widens the adjustable range on QC, clustering and DE "
            "parameters beyond the guided defaults.",
        ),
        _f(
            "trial_dataset",
            "Trial datasets",
            M,
            "Moderate adds curated trial datasets to practise on beyond the "
            "guided teaching dataset.",
            phase=2,
        ),
        _f(
            "compare_runs",
            "Compare Runs",
            M,
            "Moderate unlocks side-by-side comparison of an original run against "
            "alternate settings.",
            phase=2,
        ),
        _f(
            "cell_communication",
            "Cell-Cell Communication Explorer",
            M,
            "Moderate unlocks the Week 5 ligand-receptor explorer.",
            phase=2,
        ),
        _f(
            "spatial_guided",
            "Advanced (Spatial) guided workflow",
            M,
            "Moderate unlocks the Week 6 guided spatial transcriptomics workflow.",
            phase=2,
        ),
        _f(
            "report_full",
            "Full report export",
            M,
            "Moderate exports the full report: methods, settings, every figure, "
            "AI audit sheet and references.",
            phase=2,
        ),
        # ---- Expert: research-grade independence --------------------------
        _f(
            "dataset_upload",
            "Upload your own dataset",
            E,
            "Expert supports uploading your own analysis-ready dataset, "
            "validated before any pipeline runs.",
            phase=3,
        ),
        _f(
            "parameters_extended",
            "Extended parameter ranges",
            E,
            "Expert opens extended parameter ranges for research-grade "
            "experimentation.",
            phase=3,
        ),
        _f(
            "custom_contrasts",
            "Custom statistical contrasts",
            E,
            "Expert lets you define your own design formula and contrasts.",
            phase=3,
        ),
        _f(
            "spatial_reference_mapping",
            "Reference mapping and deconvolution",
            E,
            "Expert lets you deconvolve a spatial section against a compatible "
            "single-cell reference. The guided spatial workflow runs without it.",
            phase=3,
        ),
        _f(
            "perturbation_extended",
            "Extended perturbations",
            E,
            "Expert allows multi-step and self-authored what-if perturbations.",
            phase=3,
        ),
        _f(
            "capstone_workspace",
            "Capstone workspace",
            E,
            "Expert unlocks the Week 8 capstone workspace, figure pack and "
            "slide deck builder.",
            phase=3,
        ),
    ]
}


@dataclass(frozen=True)
class Allowance:
    """Quantitative limits per tier (spec 3.1: depth and repetition)."""

    #: Runs a learner may start per module per week. ``None`` = unmetered.
    runs_per_module_per_week: Optional[int]
    #: Perturbations offered per run.
    perturbations_per_run: int
    #: Scope of the parameter registry the tier may address (spec 7).
    parameter_scope: str
    #: Report export formats.
    export_formats: List[str] = field(default_factory=list)
    max_upload_bytes: int = 0


ALLOWANCES: Dict[AccessTier, Allowance] = {
    AccessTier.BASIC: Allowance(
        runs_per_module_per_week=2,
        perturbations_per_run=1,
        parameter_scope="limited",
        export_formats=["pdf_summary"],
    ),
    AccessTier.MODERATE: Allowance(
        runs_per_module_per_week=15,
        perturbations_per_run=5,
        parameter_scope="full",
        export_formats=["pdf_summary", "pdf_full", "csv", "figure_pack"],
    ),
    AccessTier.EXPERT: Allowance(
        runs_per_module_per_week=None,
        perturbations_per_run=20,
        parameter_scope="extended",
        export_formats=["pdf_summary", "pdf_full", "csv", "figure_pack", "slides", "raw_objects"],
        # Admin-editable at runtime (spec 6); this is the seed value only.
        max_upload_bytes=2 * 1024 * 1024 * 1024,
    ),
}


class EntitlementError(PermissionError):
    """Raised when a tier does not carry a feature. Surfaced as HTTP 403."""

    def __init__(self, feature: Feature, tier: AccessTier):
        self.feature = feature
        self.tier = tier
        super().__init__(
            f"'{feature.label}' requires the {feature.min_tier.value} tier; "
            f"this account is {tier.value}."
        )


def has_feature(tier: AccessTier, key: str) -> bool:
    feature = get_feature(key)
    return tier.satisfies(feature.min_tier)


def get_feature(key: str) -> Feature:
    try:
        return FEATURES[key]
    except KeyError:
        raise KeyError(
            f"Unknown feature '{key}'. Features must be declared in the "
            f"entitlement matrix, never checked ad hoc."
        )


def assert_feature(tier: AccessTier, key: str) -> None:
    """Backend gate. Called independently of any front-end state (spec 2, 10)."""
    feature = get_feature(key)
    if not tier.satisfies(feature.min_tier):
        raise EntitlementError(feature, tier)


def allowance(tier: AccessTier) -> Allowance:
    return ALLOWANCES[tier]


def matrix_for(tier: AccessTier, active_phase: int) -> List[dict]:
    """Serialise the matrix for the client.

    Locked features are included with their explanation so the UI can render
    them visible-but-locked with an Upgrade CTA (spec 2).
    """
    rows = []
    for feature in FEATURES.values():
        unlocked = tier.satisfies(feature.min_tier)
        rows.append(
            {
                "key": feature.key,
                "label": feature.label,
                "minTier": feature.min_tier.value,
                "unlocked": unlocked,
                "available": feature.phase <= active_phase,
                "lockedExplanation": "" if unlocked else feature.locked_explanation,
                "phase": feature.phase,
            }
        )
    return rows
