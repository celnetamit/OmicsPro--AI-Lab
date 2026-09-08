"""Experimental Design Studio (spec 5.1, 9.4)."""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import current_user, require_feature
from app.constants import AnalysisTrack
from app.content import program as program_content
from app.db import get_db
from app.governance.validation import _check_design, ValidationResult, scan_for_pii
from app.models import DesignPlan, User

router = APIRouter(
    prefix="/api/design",
    tags=["design"],
    dependencies=[Depends(require_feature("design_studio"))],
)


class SampleRow(BaseModel):
    sample_id: str
    donor: str = ""
    condition: str
    batch: str = ""
    replicate: str = ""
    tissue: str = ""
    covariates: dict = Field(default_factory=dict)


class DesignPlanRequest(BaseModel):
    brief_id: str
    biological_question: str
    condition_structure: str = ""
    sample_structure: str = ""
    decision_goal: str = ""
    chosen_assay: str
    assay_justification: str = ""
    samples: List[SampleRow] = Field(default_factory=list)


@router.get("/briefs")
def briefs() -> dict:
    return {"briefs": program_content.RESEARCH_BRIEFS, "assays": program_content.ASSAY_TRADEOFFS}


@router.post("/check")
def check_design(payload: DesignPlanRequest) -> dict:
    """Replication and confounding checks, run before analysis entry (spec 5.1)."""
    return _evaluate(payload).as_dict()


def _evaluate(payload: DesignPlanRequest) -> ValidationResult:
    result = ValidationResult()
    rows = [row.model_dump() for row in payload.samples]

    if payload.chosen_assay not in program_content.ASSAY_TRADEOFFS:
        result.fail(
            "unknown_assay",
            "Choose one of the available assay types, or a justified combination "
            "of them.",
        )
    if not rows:
        result.fail(
            "no_samples",
            "Add at least one sample to the metadata builder before saving the plan.",
        )
        return result

    if scan_for_pii(rows):
        result.fail(
            "identifiable_information",
            "Sample metadata must not contain identifiable personal information. "
            "Use coded donor identifiers.",
        )

    ids = [row["sample_id"] for row in rows]
    if len(set(ids)) != len(ids):
        result.fail("duplicate_sample_ids", "Sample identifiers must be unique.")

    _check_design(result, rows)

    tradeoffs = program_content.ASSAY_TRADEOFFS.get(payload.chosen_assay)
    if tradeoffs:
        result.summary["assayLimitations"] = tradeoffs["limitations"]
    return result


@router.post("/plan", status_code=201)
def save_plan(
    payload: DesignPlanRequest,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Save the one-page Design and Metadata Plan to the program portfolio."""
    result = _evaluate(payload)
    if not result.ok:
        raise HTTPException(422, result.as_dict())

    plan = db.scalar(
        select(DesignPlan).where(
            DesignPlan.user_id == user.id, DesignPlan.brief_id == payload.brief_id
        )
    ) or DesignPlan(user_id=user.id, brief_id=payload.brief_id)

    plan.biological_question = payload.biological_question
    plan.condition_structure = payload.condition_structure
    plan.sample_structure = payload.sample_structure
    plan.decision_goal = payload.decision_goal
    plan.chosen_assay = payload.chosen_assay
    plan.assay_justification = payload.assay_justification
    plan.samples = [row.model_dump() for row in payload.samples]
    #: Warnings are stored with the plan so the artifact records the design's
    #: known weaknesses rather than presenting it as sound.
    plan.design_warnings = result.warnings
    db.add(plan)
    db.commit()
    return _serialise(plan, result)


@router.get("/plan")
def list_plans(user: User = Depends(current_user), db: Session = Depends(get_db)) -> list:
    plans = db.scalars(select(DesignPlan).where(DesignPlan.user_id == user.id)).all()
    return [_serialise(p) for p in plans]


def _serialise(plan: DesignPlan, result: Optional[ValidationResult] = None) -> dict:
    return {
        "id": plan.id,
        "briefId": plan.brief_id,
        "biologicalQuestion": plan.biological_question,
        "conditionStructure": plan.condition_structure,
        "sampleStructure": plan.sample_structure,
        "decisionGoal": plan.decision_goal,
        "chosenAssay": plan.chosen_assay,
        "assayJustification": plan.assay_justification,
        "samples": plan.samples,
        "designWarnings": plan.design_warnings,
        "assayTradeoffs": program_content.ASSAY_TRADEOFFS.get(plan.chosen_assay),
        "updatedAt": plan.updated_at.isoformat(),
        "validation": result.as_dict() if result else None,
    }
