"""Capstone workspace, figure pack and defence deck (spec 3 week 8, 12 Phase 3).

The capstone assembles work the learner has already done: completed runs, their
recorded interpretations, the AI audit sheet and the perturbation record. It
does not generate findings. Every figure it offers points at an output the
validated pipeline actually produced, so a slide cannot show a result that was
never computed.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import current_user, require_feature
from app.constants import AnalysisTrack, RunStatus
from app.copilot import evidence
from app.db import get_db
from app.models import (
    AiInteraction,
    AuditRecord,
    Capstone,
    Dataset,
    DesignPlan,
    Interpretation,
    Perturbation,
    Run,
    User,
)

router = APIRouter(
    prefix="/api/capstone",
    tags=["capstone"],
    dependencies=[Depends(require_feature("capstone_workspace"))],
)

#: Figures the platform can offer, each bound to the output namespace and key a
#: pipeline publishes. A figure with no computed output behind it is not listed.
FIGURE_CATALOGUE: List[dict] = [
    {
        "id": "qc_summary",
        "label": "Quality control summary",
        "namespace": "qc",
        "kind": "summary",
        "caption": "Cells or spots retained and removed under the recorded thresholds.",
    },
    {
        "id": "variance_ratio",
        "label": "Principal component variance",
        "namespace": "pca",
        "key": "variance_ratio",
        "kind": "line",
        "caption": "Variance explained by each retained component.",
    },
    {
        "id": "cluster_sizes",
        "label": "Cluster sizes",
        "namespace": "cluster",
        "key": "cluster_sizes",
        "kind": "bar",
        "caption": "Cells per cluster at the recorded resolution.",
    },
    {
        "id": "composition",
        "label": "Cell type composition by sample",
        "namespace": "composition",
        "key": "proportions",
        "kind": "stacked_bar",
        "caption": "Population proportions per sample. Proportions are compositional.",
    },
    {
        "id": "de_volcano",
        "label": "Differential expression",
        "namespace": "de",
        "key": "table",
        "kind": "volcano",
        "caption": "Effect size against evidence for the recorded contrast.",
    },
    {
        "id": "pathway_table",
        "label": "Pathway enrichment",
        "namespace": "pathway",
        "key": "table",
        "kind": "table",
        "caption": "Enriched gene sets against the detected-gene background.",
    },
    {
        "id": "sample_structure",
        "label": "Sample structure",
        "namespace": "exploratory",
        "key": "coordinates",
        "kind": "scatter",
        "caption": "Samples in principal component space, coloured by annotation.",
    },
    {
        "id": "gene_maps",
        "label": "Tissue gene maps",
        "namespace": "svg",
        "key": "gene_maps",
        "kind": "spatial_map",
        "caption": "Expression of the most spatially structured genes across the section.",
    },
    {
        "id": "domain_map",
        "label": "Spatial domains",
        "namespace": "domains",
        "key": "assignments",
        "kind": "spatial_map",
        "caption": "Domain assignment per spot. A domain is a model output, not an annotated region.",
    },
    {
        "id": "neighborhood",
        "label": "Neighbourhood adjacency",
        "namespace": "neighborhood",
        "key": "table",
        "kind": "table",
        "caption": "Domain pairs adjacent more often than chance predicts.",
    },
    {
        "id": "interaction_network",
        "label": "Candidate communication network",
        "namespace": "interactions",
        "key": "table",
        "kind": "network",
        "caption": "Inferred candidate ligand-receptor interactions, not demonstrated signalling.",
    },
]


class CapstoneRequest(BaseModel):
    title: str = ""
    research_question: str = ""
    approach: str = ""
    run_ids: List[str] = Field(default_factory=list)
    figures: List[dict] = Field(default_factory=list)
    findings: List[dict] = Field(default_factory=list)
    limitations: List[str] = Field(default_factory=list)
    future_work: str = ""


def _capstone_for(db: Session, user: User) -> Capstone:
    existing = db.scalar(select(Capstone).where(Capstone.user_id == user.id))
    if existing:
        return existing
    created = Capstone(user_id=user.id)
    db.add(created)
    db.commit()
    return created


def _owned_runs(db: Session, user: User, run_ids: List[str]) -> List[Run]:
    runs = []
    for run_id in run_ids:
        run = db.get(Run, run_id)
        if run is None or run.user_id != user.id:
            raise HTTPException(404, f"Run {run_id} not found.")
        if run.status != RunStatus.COMPLETED:
            raise HTTPException(
                422,
                f"Run {run_id[:8]} did not complete, so it cannot support a "
                f"capstone claim.",
            )
        runs.append(run)
    return runs


def _serialise(capstone: Capstone) -> dict:
    return {
        "id": capstone.id,
        "title": capstone.title,
        "researchQuestion": capstone.research_question,
        "approach": capstone.approach,
        "runIds": capstone.run_ids,
        "figures": capstone.figures,
        "findings": capstone.findings,
        "limitations": capstone.limitations,
        "futureWork": capstone.future_work,
        "submittedAt": capstone.submitted_at.isoformat() if capstone.submitted_at else None,
        "updatedAt": capstone.updated_at.isoformat(),
    }


@router.get("")
def get_capstone(user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    return _serialise(_capstone_for(db, user))


@router.put("")
def save_capstone(
    payload: CapstoneRequest,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    capstone = _capstone_for(db, user)
    if capstone.submitted_at:
        raise HTTPException(
            409, "This capstone has been submitted and is no longer editable."
        )
    _owned_runs(db, user, payload.run_ids)

    capstone.title = payload.title
    capstone.research_question = payload.research_question
    capstone.approach = payload.approach
    capstone.run_ids = payload.run_ids
    capstone.figures = payload.figures
    capstone.findings = payload.findings
    capstone.limitations = payload.limitations
    capstone.future_work = payload.future_work
    db.add(capstone)
    db.commit()
    return _serialise(capstone)


@router.get("/available-figures")
def available_figures(
    user: User = Depends(current_user), db: Session = Depends(get_db)
) -> list:
    """Figures backed by an output the learner's completed runs actually hold."""
    capstone = _capstone_for(db, user)
    runs = _owned_runs(db, user, capstone.run_ids)
    offered = []
    for run in runs:
        for figure in FIGURE_CATALOGUE:
            namespace = run.outputs.get(figure["namespace"])
            if not namespace:
                continue
            key = figure.get("key")
            if key and key not in namespace:
                continue
            offered.append(
                {
                    **figure,
                    "runId": run.id,
                    "track": run.track,
                    "module": run.module,
                    "pipelineVersion": run.pipeline_version,
                }
            )
    return offered


@router.get("/figure-pack")
def figure_pack(user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    """Assemble the selected figures with their data and provenance."""
    capstone = _capstone_for(db, user)
    runs = {run.id: run for run in _owned_runs(db, user, capstone.run_ids)}
    catalogue = {figure["id"]: figure for figure in FIGURE_CATALOGUE}

    panels = []
    for index, selection in enumerate(capstone.figures, start=1):
        figure = catalogue.get(selection.get("figureId"))
        run = runs.get(selection.get("runId"))
        if figure is None or run is None:
            continue
        namespace = run.outputs.get(figure["namespace"], {})
        key = figure.get("key")
        data = namespace.get(key) if key else namespace
        if data is None:
            continue
        panels.append(
            {
                "panel": index,
                "figureId": figure["id"],
                "label": figure["label"],
                "kind": figure["kind"],
                "caption": selection.get("caption") or figure["caption"],
                "data": data,
                # Provenance travels with the figure so a panel lifted into a
                # slide still says which run and method version produced it.
                "provenance": {
                    "runId": run.id,
                    "datasetId": run.dataset_id,
                    "track": run.track,
                    "module": run.module,
                    "pipelineVersion": run.pipeline_version,
                    "methodVersions": run.method_versions,
                    "parameters": run.parameters,
                },
            }
        )
    return {"panels": panels, "count": len(panels)}


@router.get("/deck")
def deck(user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    """A defence deck assembled from recorded work only.

    Every slide is populated from the design plan, the run records, the
    interpretations the learner wrote and the audit sheet. Nothing on it is
    generated prose about results.
    """
    capstone = _capstone_for(db, user)
    runs = _owned_runs(db, user, capstone.run_ids)
    plan = db.scalar(select(DesignPlan).where(DesignPlan.user_id == user.id))
    pack = figure_pack(user=user, db=db)

    interpretations = []
    audit_rows = []
    source_ids: set = set()
    for run in runs:
        interpretations.extend(
            db.scalars(select(Interpretation).where(Interpretation.run_id == run.id)).all()
        )
        interactions = db.scalars(
            select(AiInteraction).where(AiInteraction.run_id == run.id)
        ).all()
        audits = {
            a.interaction_id: a
            for a in db.scalars(
                select(AuditRecord).where(AuditRecord.user_id == user.id)
            ).all()
        }
        for interaction in interactions:
            source_ids.update(interaction.evidence_source_ids)
            audit_rows.append(
                {
                    "step": interaction.step,
                    "function": interaction.function,
                    "label": interaction.interpretation_label,
                    "learnerAction": (
                        audits[interaction.id].action
                        if interaction.id in audits
                        else "not_reviewed"
                    ),
                }
            )

    perturbations = []
    for run in runs:
        perturbations.extend(
            db.scalars(select(Perturbation).where(Perturbation.run_id == run.id)).all()
        )

    datasets = [db.get(Dataset, run.dataset_id) for run in runs]
    limitations = set(capstone.limitations)
    for dataset in datasets:
        limitations.update(dataset.limitations or [])
    for run in runs:
        for namespace in run.outputs.values():
            if isinstance(namespace, dict) and namespace.get("caveat"):
                limitations.add(namespace["caveat"])

    unreviewed = [row for row in audit_rows if row["learnerAction"] == "not_reviewed"]

    slides = [
        {"slide": 1, "title": capstone.title or "Capstone", "type": "title",
         "body": {"researchQuestion": capstone.research_question}},
        {"slide": 2, "title": "Study design", "type": "design",
         "body": {
             "chosenAssay": plan.chosen_assay if plan else None,
             "justification": plan.assay_justification if plan else "",
             "designWarnings": plan.design_warnings if plan else [],
         }},
        {"slide": 3, "title": "Data and provenance", "type": "provenance",
         "body": [
             {
                 "name": dataset.name,
                 "accession": dataset.accession,
                 "source": dataset.source,
                 "license": dataset.license,
             }
             for dataset in datasets
             if dataset
         ]},
        {"slide": 4, "title": "Methods and versions", "type": "methods",
         "body": [
             {
                 "runId": run.id,
                 "track": run.track,
                 "module": run.module,
                 "pipelineVersion": run.pipeline_version,
                 "methodVersions": run.method_versions,
             }
             for run in runs
         ]},
        {"slide": 5, "title": "Results", "type": "figures", "body": pack["panels"]},
        {"slide": 6, "title": "Interpretation", "type": "interpretation",
         "body": [
             {
                 "step": row.step,
                 "observation": row.observation,
                 "statisticalEvidence": row.statistical_evidence,
                 "biologicalInterpretation": row.biological_interpretation,
                 "hypothesis": row.hypothesis,
                 "label": row.label,
             }
             for row in interpretations
         ]},
        {"slide": 7, "title": "Robustness", "type": "perturbations",
         "body": [
             {
                 "parameterKey": row.parameter_key,
                 "from": row.from_value.get("value"),
                 "to": row.to_value.get("value"),
                 "decision": row.decision,
                 "matchedExpectation": row.matched_expectation,
                 "explanation": row.divergence_explanation,
             }
             for row in perturbations
         ]},
        {"slide": 8, "title": "AI audit", "type": "audit",
         "body": {"rows": audit_rows, "unreviewed": len(unreviewed)}},
        {"slide": 9, "title": "Limitations", "type": "limitations",
         "body": sorted(limitations)},
        {"slide": 10, "title": "What I would do next", "type": "future",
         "body": capstone.future_work},
        {"slide": 11, "title": "References", "type": "references",
         "body": evidence.resolve(sorted(source_ids))},
    ]

    readiness = _readiness(capstone, runs, interpretations, unreviewed)
    return {"slides": slides, "readiness": readiness}


def _readiness(capstone, runs, interpretations, unreviewed) -> dict:
    """What is still missing before this is defensible. Not a grade."""
    gaps = []
    if not capstone.research_question.strip():
        gaps.append("The research question has not been stated.")
    if not runs:
        gaps.append("No completed run is attached to the capstone.")
    if not capstone.figures:
        gaps.append("No figure has been selected for the figure pack.")
    incomplete = [
        row.step
        for row in interpretations
        if not (row.observation.strip() and row.statistical_evidence.strip())
    ]
    if incomplete:
        gaps.append(
            "Observation and statistical evidence are not both recorded for: "
            + ", ".join(sorted(set(incomplete)))
        )
    if not interpretations:
        gaps.append("No interpretation has been recorded against any attached run.")
    if unreviewed:
        gaps.append(
            f"{len(unreviewed)} Copilot outputs have not been adjudicated in the "
            f"AI audit."
        )
    if not capstone.limitations:
        gaps.append("No limitations have been stated in your own words.")
    return {
        "ready": not gaps,
        "gaps": gaps,
        "note": (
            "This lists what is missing from the record. It is not an assessment "
            "of whether your science is right."
        ),
    }


@router.post("/submit")
def submit(user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    capstone = _capstone_for(db, user)
    if capstone.submitted_at:
        raise HTTPException(409, "This capstone has already been submitted.")
    runs = _owned_runs(db, user, capstone.run_ids)
    interpretations: List[Interpretation] = []
    for run in runs:
        interpretations.extend(
            db.scalars(select(Interpretation).where(Interpretation.run_id == run.id)).all()
        )
    readiness = _readiness(capstone, runs, interpretations, [])
    if not readiness["ready"]:
        raise HTTPException(422, {"error": "capstone_incomplete", **readiness})
    capstone.submitted_at = datetime.utcnow()
    db.commit()
    return _serialise(capstone)
