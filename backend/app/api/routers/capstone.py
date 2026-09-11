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
from app.core.figures import FIGURE_CATALOGUE
from app.db import get_db
from app.models import (
    AiInteraction,
    AssessmentResult,
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

#: The figure catalogue is shared with the analysis workspace, so a figure
#: means the same thing on both screens. See app.core.figures.


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
        "defenceScore": capstone.defence_score,
        "defenceBreakdown": capstone.defence_breakdown or {},
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
        {"slide": 2, "title": "Design and data", "type": "design",
         "body": {
             "chosenAssay": plan.chosen_assay if plan else None,
             "justification": plan.assay_justification if plan else "",
             "designWarnings": plan.design_warnings if plan else [],
             "datasets": [
                 {
                     "name": dataset.name,
                     "accession": dataset.accession,
                     "source": dataset.source,
                     "license": dataset.license,
                 }
                 for dataset in datasets
                 if dataset
             ],
         }},
        {"slide": 3, "title": "Methods and versions", "type": "methods",
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
        {"slide": 4, "title": "Results", "type": "figures", "body": pack["panels"]},
        {"slide": 5, "title": "Interpretation", "type": "interpretation",
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
        {"slide": 6, "title": "Robustness", "type": "perturbations",
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
        {"slide": 7, "title": "AI audit", "type": "audit",
         "body": {"rows": audit_rows, "unreviewed": len(unreviewed)}},
        {"slide": 8, "title": "Limitations, next steps and references", "type": "closing",
         "body": {
             "limitations": sorted(limitations),
             "nextSteps": capstone.future_work,
             "references": evidence.resolve(sorted(source_ids)),
         }},
    ]

    readiness = _readiness(capstone, runs, interpretations, unreviewed)
    #: Spec 13 asks for a five-to-eight slide defence deck; the count is
    #: asserted here so a future slide cannot quietly push it out of range.
    assert 5 <= len(slides) <= 8, f"deck must be 5-8 slides, built {len(slides)}"
    return {"slides": slides, "slideCount": len(slides), "readiness": readiness}


#: A printed page of this memo's layout holds roughly this many words. Used to
#: report length honestly rather than claiming "2 pages" without checking.
WORDS_PER_PAGE = 500


def _words(*parts) -> int:
    total = 0
    for part in parts:
        if isinstance(part, str):
            total += len(part.split())
        elif isinstance(part, (list, tuple)):
            total += _words(*part)
        elif isinstance(part, dict):
            total += _words(*part.values())
    return total


@router.get("/memo")
def memo(user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    """The two-page biotech/research memo (spec 13).

    Assembled from recorded work only, on the same rule as the deck: the
    findings are the learner's own biological interpretations, each carried with
    the label it was given and the run and step that produced it. The platform
    does not write the science; it lays out what was recorded and states what
    the record does not support.
    """
    capstone = _capstone_for(db, user)
    runs = _owned_runs(db, user, capstone.run_ids)
    plan = db.scalar(select(DesignPlan).where(DesignPlan.user_id == user.id))

    interpretations: List[Interpretation] = []
    for run in runs:
        interpretations.extend(
            db.scalars(select(Interpretation).where(Interpretation.run_id == run.id)).all()
        )

    perturbations: List[Perturbation] = []
    for run in runs:
        perturbations.extend(
            db.scalars(select(Perturbation).where(Perturbation.run_id == run.id)).all()
        )

    datasets = [db.get(Dataset, run.dataset_id) for run in runs]
    source_ids, limitations = set(), set()
    for dataset in datasets:
        if dataset:
            limitations.update(dataset.limitations or [])
    for run in runs:
        for namespace in (run.outputs or {}).values():
            if isinstance(namespace, dict) and namespace.get("caveat"):
                limitations.add(namespace["caveat"])
    for row in interpretations:
        interaction = db.scalar(
            select(AiInteraction).where(
                AiInteraction.run_id.in_([r.id for r in runs] or [""]),
                AiInteraction.step == row.step,
            )
        )
        if interaction and interaction.evidence_source_ids:
            source_ids.update(interaction.evidence_source_ids)

    findings = [
        {
            "step": row.step,
            "claim": row.biological_interpretation,
            "observation": row.observation,
            "statisticalEvidence": row.statistical_evidence,
            "hypothesis": row.hypothesis,
            "label": row.label,
        }
        for row in interpretations
        if row.biological_interpretation.strip()
    ]

    sections = {
        "question": capstone.research_question,
        "decision": plan.decision_goal if plan else "",
        "approach": {
            "narrative": capstone.approach,
            "chosenAssay": plan.chosen_assay if plan else None,
            "justification": plan.assay_justification if plan else "",
            "datasets": [
                {"name": d.name, "accession": d.accession, "source": d.source, "license": d.license}
                for d in datasets
                if d
            ],
            "methods": [
                {
                    "track": run.track,
                    "pipelineVersion": run.pipeline_version,
                    "methodVersions": run.method_versions,
                }
                for run in runs
            ],
        },
        "findings": findings,
        "robustness": [
            {
                "parameterKey": row.parameter_key,
                "from": row.from_value.get("value"),
                "to": row.to_value.get("value"),
                "decision": row.decision,
                "matchedExpectation": row.matched_expectation,
            }
            for row in perturbations
        ],
        "limitations": sorted(limitations) + list(capstone.limitations or []),
        "nextSteps": capstone.future_work,
        "references": evidence.resolve(sorted(source_ids)),
    }

    words = _words(sections)
    pages = max(1, round(words / WORDS_PER_PAGE)) if words else 0

    missing = []
    if not sections["question"].strip():
        missing.append("the research question")
    if not findings:
        missing.append("at least one biological interpretation")
    if not sections["limitations"]:
        missing.append("the limitations")

    return {
        "title": capstone.title or "Capstone memo",
        "sections": sections,
        "estimatedWords": words,
        "estimatedPages": pages,
        "withinTwoPages": pages <= 2,
        "missing": missing,
        "note": (
            "Every claim here is one you recorded against a run, carried with the "
            "label you gave it. The memo states length as measured, not as "
            "promised: a memo longer than two pages needs cutting by you, because "
            "the platform will not decide which of your findings to drop."
        ),
    }


def _defence_score(capstone, runs, interpretations, perturbations, audit_rows, week_scores) -> dict:
    """The final defence score (spec 13).

    Every part is read from the record and says what it counted. None of it
    judges whether the science is correct — the platform cannot know that — so
    the score measures whether the work is defensible: complete, adjudicated,
    tested for robustness and stated with its limits.
    """
    parts = []

    complete = [
        row
        for row in interpretations
        if all(
            getattr(row, name).strip()
            for name in ("observation", "statistical_evidence", "biological_interpretation", "hypothesis")
        )
    ]
    parts.append({
        "key": "interpretation",
        "label": "Interpretations complete",
        "measures": "Interpretations that separate all four fields.",
        "score": (len(complete) / len(interpretations)) if interpretations else None,
        "counted": len(complete),
        "total": len(interpretations),
    })

    adjudicated = [row for row in audit_rows if row["learnerAction"] != "not_reviewed"]
    parts.append({
        "key": "audit",
        "label": "Copilot output adjudicated",
        "measures": "AI outputs you accepted, modified, rejected or flagged.",
        "score": (len(adjudicated) / len(audit_rows)) if audit_rows else None,
        "counted": len(adjudicated),
        "total": len(audit_rows),
    })

    reconciled = [row for row in perturbations if row.actual_outcome]
    parts.append({
        "key": "robustness",
        "label": "Robustness tested",
        "measures": "What-if tests whose alternate run produced a comparison.",
        "score": (len(reconciled) / len(perturbations)) if perturbations else None,
        "counted": len(reconciled),
        "total": len(perturbations),
    })

    stated = len(capstone.limitations or [])
    parts.append({
        "key": "limits",
        "label": "Limitations stated",
        "measures": "Limitations you wrote in your own words.",
        "score": 1.0 if stated else 0.0,
        "counted": stated,
        "total": 1,
    })

    if week_scores:
        parts.append({
            "key": "weeks",
            "label": "Week assessments",
            "measures": "Mean of the week assessments you have taken.",
            "score": sum(week_scores) / len(week_scores),
            "counted": len(week_scores),
            "total": len(week_scores),
        })

    scored = [p for p in parts if p["score"] is not None]
    overall = sum(p["score"] for p in scored) / len(scored) if scored else None
    for part in parts:
        if part["score"] is not None:
            part["score"] = round(part["score"], 2)

    return {
        "score": round(overall, 2) if overall is not None else None,
        "parts": parts,
        "pending": [p["label"] for p in parts if p["score"] is None],
        "note": (
            "This measures whether the work is defensible — complete, "
            "adjudicated, tested and stated with its limits. It is not a "
            "judgement of whether your biology is right; the platform cannot "
            "know that, and an SME review is where that belongs."
        ),
    }


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

    #: The defence score is computed once, at submission, from the record as it
    #: stood — so it stays true to what was defended rather than drifting with
    #: later edits.
    perturbations: List[Perturbation] = []
    for run in runs:
        perturbations.extend(
            db.scalars(select(Perturbation).where(Perturbation.run_id == run.id)).all()
        )
    audit_rows = []
    audits = {
        a.interaction_id: a
        for a in db.scalars(select(AuditRecord).where(AuditRecord.user_id == user.id)).all()
    }
    for run in runs:
        for interaction in db.scalars(
            select(AiInteraction).where(AiInteraction.run_id == run.id)
        ).all():
            audit_rows.append(
                {
                    "step": interaction.step,
                    "learnerAction": (
                        audits[interaction.id].action
                        if interaction.id in audits
                        else "not_reviewed"
                    ),
                }
            )
    week_scores = [
        row.score
        for row in db.scalars(
            select(AssessmentResult).where(
                AssessmentResult.user_id == user.id,
                AssessmentResult.assessment_id.like("week-%"),
            )
        ).all()
    ]
    breakdown = _defence_score(
        capstone, runs, interpretations, perturbations, audit_rows, week_scores
    )

    capstone.submitted_at = datetime.utcnow()
    capstone.defence_score = breakdown["score"]
    capstone.defence_breakdown = breakdown
    db.commit()
    return {**_serialise(capstone), "defence": breakdown}
