"""Grounded dataset explanation for the Dataset Inspector (spec 9.6).

Before a learner runs anything, the inspector explains the dataset: where it
comes from, how the experiment was designed, what the object contains, and
which analyses its design can and cannot support. Every sentence is a reviewed
template whose variable content is a reference to a fact computed from the
loaded object or recorded on the dataset, and it passes the same fail-closed
grounding check as every other Copilot output. Which analyses a design supports
is decided by the rules below, in code, never by a model.
"""

import re
from typing import Any, Dict, List, Tuple

from sqlalchemy.orm import Session

from app.constants import ACTIVE_PHASE, AnalysisTrack
from app.copilot import evidence
from app.copilot.grounding import Grounded, render
from app.models import AiInteraction, Dataset
from app.pipelines import registry
from app.pipelines.base import DataObject

#: Output namespaces whose steps compare conditions, and so need a contrast
#: with independent replicates on both sides.
CONTRAST_NAMESPACES = ("de", "pathway")
#: Independent replicates each condition needs before a comparison is tested
#: at all. Two is the floor for estimating variance, not a recommendation.
MIN_REPLICATES = 2

_UNIT = {
    AnalysisTrack.FOUNDATION: ("sample", "samples"),
    AnalysisTrack.CORE: ("cell", "cells"),
    AnalysisTrack.ADVANCED: ("spot", "spots"),
}


def _blank(value: Any) -> bool:
    return value is None or value == ""


def _facts(dataset: Dataset, data: DataObject) -> Dict[str, Any]:
    """Every value the explanation may state, computed from the object itself."""
    track = AnalysisTrack(dataset.track)
    obs = data.obs
    fields = sorted({key for row in obs for key in row})
    conditions = sorted({str(row["condition"]) for row in obs if not _blank(row.get("condition"))})

    #: The replicate is the sample: a cell or a spot is never independent.
    samples_by_condition: Dict[str, set] = {}
    for row in obs:
        if not _blank(row.get("condition")):
            samples_by_condition.setdefault(str(row["condition"]), set()).add(str(row.get("sample_id", "")))
    replicates = {condition: len(ids) for condition, ids in samples_by_condition.items()}

    conditions_by_donor: Dict[str, set] = {}
    for row in obs:
        if not _blank(row.get("donor")):
            conditions_by_donor.setdefault(str(row["donor"]), set()).add(str(row.get("condition", "")))
    crossed = [len(c) > 1 for c in conditions_by_donor.values()]

    conditions_by_batch: Dict[str, set] = {}
    for row in obs:
        if not _blank(row.get("batch")):
            conditions_by_batch.setdefault(str(row["batch"]), set()).add(str(row.get("condition", "")))

    missing = [f for f in fields if any(_blank(row.get(f)) for row in obs)]
    singular, plural = _UNIT[track]
    return {
        "source": dataset.source or "",
        "accession": dataset.accession or "",
        "license": dataset.license or "",
        "citation": (dataset.citation or "").strip().rstrip("."),
        "validation_status": dataset.validation_status,
        "unit": plural,
        "unit_singular": singular,
        "n_observations": len(obs),
        "n_features": len(data.var),
        "metadata_fields": fields,
        "n_metadata_fields": len(fields),
        "conditions": conditions,
        "n_conditions": len(conditions),
        "replicates_per_condition": replicates,
        "min_replicates": min(replicates.values()) if replicates else 0,
        "min_replicates_required": MIN_REPLICATES,
        "n_samples": len({str(row.get("sample_id", "")) for row in obs}),
        "n_donors": len(conditions_by_donor),
        "fully_paired": len(conditions) > 1 and bool(crossed) and all(crossed),
        "partly_paired": len(conditions) > 1 and any(crossed) and not all(crossed),
        "n_batches": len(conditions_by_batch),
        "batch_confounded": (
            len(conditions_by_batch) > 1
            and len(conditions) > 1
            and all(len(c) == 1 for c in conditions_by_batch.values())
        ),
        "fields_with_missing": missing,
        "n_fields_with_missing": len(missing),
    }


# --------------------------------------------------------------- sections --
def _provenance(f: Dict[str, Any]) -> List[str]:
    #: Label and value, not a sentence built around the value: a recorded source
    #: can be a name ("NCBI Gene Expression Omnibus") or a statement ("Generated
    #: locally by scripts/seed.py"), and only this form reads right for both.
    parts = []
    if f["source"]:
        parts.append("Source: {{computed:dataset.source}}.")
    if f["accession"]:
        parts.append("Accession: {{computed:dataset.accession}}.")
    if f["license"]:
        parts.append("Licence or terms of use: {{computed:dataset.license}}.")
    if f["citation"]:
        parts.append("Citation: {{computed:dataset.citation}}.")
    parts.append("Validation status: {{computed:dataset.validation_status}}.")
    return parts


def _design(track: AnalysisTrack, f: Dict[str, Any]) -> List[str]:
    parts = []
    if f["n_conditions"] == 0:
        parts.append(
            "No condition is recorded for these {{computed:dataset.unit}}, so the object "
            "defines no comparison between groups."
        )
    elif f["n_conditions"] == 1:
        parts.append(
            "Every one of these {{computed:dataset.unit}} is recorded under one condition, "
            "{{computed:dataset.conditions}}, so the object defines no comparison between groups."
        )
    else:
        parts.append(
            "The {{computed:dataset.n_observations}} {{computed:dataset.unit}} are recorded under "
            "{{computed:dataset.n_conditions}} conditions: {{computed:dataset.conditions}}."
        )
        if track is AnalysisTrack.FOUNDATION:
            parts.append(
                "Each sample is an independent replicate, and the smallest condition has "
                "{{computed:dataset.min_replicates}} of them."
            )
        else:
            parts.append(
                "The independent replicate is the sample, not the {{computed:dataset.unit_singular}}: "
                "the smallest condition has {{computed:dataset.min_replicates}} samples, however many "
                "{{computed:dataset.unit}} each contributes."
            )

    if f["fully_paired"]:
        parts.append(
            "Every donor appears under more than one condition, so the design is paired and "
            "donor-to-donor differences can be separated from the condition effect."
        )
    elif f["partly_paired"]:
        parts.append(
            "Some donors appear under more than one condition and others only once, so the "
            "pairing is incomplete."
        )

    if f["n_batches"] == 1:
        parts.append(
            "All of them are recorded in a single batch, so a batch difference cannot "
            "masquerade as a condition difference."
        )
    elif f["batch_confounded"]:
        parts.append(
            "Each of the {{computed:dataset.n_batches}} recorded batches holds only one condition, "
            "so batch and condition cannot be separated: any difference between conditions may "
            "be a batch effect."
        )
    elif f["n_batches"] > 1:
        parts.append(
            "{{computed:dataset.n_batches}} batches are recorded and at least one holds more than "
            "one condition, so batch can be modelled alongside condition."
        )
    else:
        parts.append("No batch is recorded, so batch effects can be neither checked nor modelled.")

    if track is AnalysisTrack.ADVANCED:
        if f["n_samples"] == 1:
            parts.append(
                "The object is a single tissue section, so results describe this section; they "
                "do not generalise to a condition or a population."
            )
        else:
            parts.append("The object holds {{computed:dataset.n_samples}} tissue sections.")
    return parts


def _structure(track: AnalysisTrack, f: Dict[str, Any]) -> List[str]:
    if track is AnalysisTrack.FOUNDATION:
        parts = [
            "The count matrix measures {{computed:dataset.n_features}} genes in "
            "{{computed:dataset.n_observations}} samples."
        ]
    elif track is AnalysisTrack.CORE:
        parts = [
            "The count matrix holds {{computed:dataset.n_observations}} cells by "
            "{{computed:dataset.n_features}} genes, contributed by {{computed:dataset.n_samples}} samples."
        ]
    else:
        parts = [
            "The object holds {{computed:dataset.n_observations}} spots, each with tissue "
            "coordinates, measured across {{computed:dataset.n_features}} genes."
        ]
    if f["n_metadata_fields"]:
        parts.append(
            "Each {{computed:dataset.unit_singular}} carries {{computed:dataset.n_metadata_fields}} "
            "recorded annotations: {{computed:dataset.metadata_fields}}."
        )
    if f["n_fields_with_missing"]:
        parts.append(
            "{{computed:dataset.n_fields_with_missing}} of them have missing values: "
            "{{computed:dataset.fields_with_missing}}."
        )
    elif f["n_metadata_fields"]:
        parts.append("No annotation is missing a value.")
    return parts


# -------------------------------------------------------------- analyses --
def _contrast_reason(f: Dict[str, Any], computed: dict, refs: List[str]) -> Tuple[bool, str]:
    """Whether the design supports a comparison between conditions, and why."""
    if f["n_conditions"] < 2:
        template = (
            "Needs at least two recorded conditions to compare; this object records "
            "{{computed:dataset.n_conditions}}."
        )
        supported = False
    elif f["min_replicates"] < MIN_REPLICATES:
        template = (
            "Needs at least {{computed:dataset.min_replicates_required}} independent samples in "
            "every condition; the smallest condition here has {{computed:dataset.min_replicates}}."
        )
        supported = False
    elif f["batch_confounded"]:
        template = (
            "Runs, but batch and condition cannot be separated in this design, so a difference "
            "may be a batch effect."
        )
        supported = True
    else:
        template = (
            "{{computed:dataset.n_conditions}} conditions, with at least "
            "{{computed:dataset.min_replicates}} independent samples in each."
        )
        supported = True
    grounded = render(template, computed, {}, [])
    refs += grounded.computed_refs
    return supported, grounded.text


def _analyses(
    dataset: Dataset, f: Dict[str, Any], computed: dict, refs: List[str]
) -> Tuple[List[dict], List[dict]]:
    track = AnalysisTrack(dataset.track)
    supported: List[dict] = []
    unsupported: List[dict] = []
    try:
        pipeline = registry.get(track)
    except KeyError as exc:
        return [], [{"label": "The guided workflow", "reason": str(exc.args[0])}]

    contrast = None
    for step in pipeline.steps:
        if step.publishes == "validate":
            continue
        if step.publishes in CONTRAST_NAMESPACES:
            if contrast is None:
                contrast = _contrast_reason(f, computed, refs)
            ok, reason = contrast
            (supported if ok else unsupported).append({"label": step.label, "reason": reason})
        else:
            supported.append({"label": step.label, "reason": ""})

    for module in registry.MODULES.values():
        if module["track"] is not track:
            continue
        if module["phase"] > ACTIVE_PHASE:
            unsupported.append({"label": module["label"], "reason": "Not available in this release."})
        else:
            supported.append({"label": module["label"], "reason": "Extension module."})
    return supported, unsupported


def _sources(dataset: Dataset) -> List[str]:
    """Approved registry entries for this dataset, matched on its accession."""
    accession = (dataset.accession or "").strip()
    if not accession:
        return []
    pattern = re.compile(rf"(?<![A-Za-z0-9]){re.escape(accession)}(?![A-Za-z0-9])")
    return [source.id for source in evidence.SEED_SOURCES if pattern.search(source.reference)]


# ------------------------------------------------------------------ entry --
def brief_for(dataset: Dataset, data: DataObject) -> Tuple[dict, Grounded]:
    """The explanation and the provenance of everything in it."""
    track = AnalysisTrack(dataset.track)
    facts = _facts(dataset, data)
    computed = {"dataset": facts}
    sources = _sources(dataset)
    refs: List[str] = []

    sections = []
    for key, title, parts, ids in (
        ("provenance", "Where it comes from", _provenance(facts), sources),
        ("design", "How the experiment was designed", _design(track, facts), []),
        ("structure", "What the object contains", _structure(track, facts), []),
    ):
        grounded = render(" ".join(parts), computed, {}, ids)
        refs += grounded.computed_refs
        sections.append({"key": key, "title": title, "text": grounded.text})

    supported, unsupported = _analyses(dataset, facts, computed, refs)
    unique_refs = sorted(set(refs))
    payload = {
        "available": True,
        "sections": sections,
        "validAnalyses": supported,
        "notSupported": unsupported,
        #: Reviewed limitations recorded on the dataset, shown as written.
        "limitations": list(dataset.limitations or []),
        "evidence": evidence.resolve(sources),
        "computedRefs": unique_refs,
    }
    combined = Grounded(
        text="\n".join(section["text"] for section in sections),
        computed_refs=unique_refs,
        evidence_source_ids=sources,
    )
    return payload, combined


def compose(db: Session, user_id: str, dataset: Dataset, data: DataObject) -> dict:
    """Compose the explanation and record it, like every Copilot output (spec 5.3)."""
    payload, grounded = brief_for(dataset, data)
    interaction = AiInteraction(
        run_id=None,
        user_id=user_id,
        function="dataset_brief",
        step="dataset_inspector",
        prompt_context={"datasetId": dataset.id, "track": AnalysisTrack(dataset.track).value},
        output=payload,
        evidence_source_ids=grounded.evidence_source_ids,
        computed_refs=grounded.computed_refs,
    )
    db.add(interaction)
    db.commit()
    payload["interactionId"] = interaction.id
    return payload
