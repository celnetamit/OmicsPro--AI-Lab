"""Omics Copilot endpoints and the AI Research Audit (spec 8, 5.3)."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import current_user, require_feature
from app.constants import AnalysisTrack, AuditAction, InterpretationLabel
from app.copilot import evidence, knowledge, service
from app.copilot.grounding import UngroundedOutputError
from app.db import get_db
from app.models import AiInteraction, AuditRecord, Run, User

router = APIRouter(prefix="/api/copilot", tags=["copilot"])


def _owned_run(run_id: str, user: User, db: Session) -> Run:
    run = db.get(Run, run_id)
    if run is None or run.user_id != user.id:
        raise HTTPException(404, "Run not found.")
    return run


def _guard(call):
    """Fail closed: an ungrounded response is an error, never a degraded answer."""
    try:
        return call()
    except UngroundedOutputError as exc:
        raise HTTPException(
            500,
            {
                "error": "ungrounded_output",
                "message": (
                    "The Copilot could not produce a response traceable to this "
                    "run's computed results, so nothing was returned. "
                    f"{exc}"
                ),
            },
        )
    except KeyError as exc:
        raise HTTPException(404, str(exc))


@router.get("/steps/{track}")
def steps(track: AnalysisTrack) -> list:
    return [
        {
            "step": entry.step,
            "title": entry.title,
            "purpose": entry.purpose,
            "whatToObserve": entry.what_to_observe,
            "caveats": entry.caveats,
            "references": evidence.resolve(entry.evidence_source_ids),
        }
        for entry in knowledge.steps_for(track)
    ]


@router.get("/explain", dependencies=[Depends(require_feature("copilot_explain"))])
def explain(
    run_id: str, step: str, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> dict:
    run = _owned_run(run_id, user, db)
    return _guard(lambda: service.explain(db, user.id, run, step))


@router.get("/evidence", dependencies=[Depends(require_feature("copilot_explain"))])
def cite(
    track: AnalysisTrack,
    step: str,
    run_id: Optional[str] = None,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    run = _owned_run(run_id, user, db) if run_id else None
    return _guard(lambda: service.cite(db, user.id, run, step, track))


@router.get("/recommend", dependencies=[Depends(require_feature("copilot_explain"))])
def recommend(
    run_id: str, step: str, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> dict:
    run = _owned_run(run_id, user, db)
    return _guard(lambda: service.recommend(db, user.id, run, step))


@router.get("/interpret", dependencies=[Depends(require_feature("copilot_interpret"))])
def interpret(
    run_id: str, step: str, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> dict:
    run = _owned_run(run_id, user, db)
    return _guard(lambda: service.interpret(db, user.id, run, step))


@router.get("/challenge", dependencies=[Depends(require_feature("copilot_interpret"))])
def challenge(
    run_id: str, step: str, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> dict:
    run = _owned_run(run_id, user, db)
    return _guard(lambda: service.challenge(db, user.id, run, step))


# ------------------------------------------------------------- AI audit ----
class AuditSubmission(BaseModel):
    interaction_id: str
    action: AuditAction
    learner_rationale: str = ""
    final_interpretation: str = ""
    revised_label: Optional[InterpretationLabel] = None


@router.get("/interactions", dependencies=[Depends(require_feature("ai_audit"))])
def interactions(
    run_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> list:
    run = _owned_run(run_id, user, db)
    rows = db.scalars(
        select(AiInteraction).where(AiInteraction.run_id == run.id).order_by(
            AiInteraction.created_at
        )
    ).all()
    audits = {
        a.interaction_id: a
        for a in db.scalars(
            select(AuditRecord).where(AuditRecord.user_id == user.id)
        ).all()
    }
    return [
        {
            "id": row.id,
            "function": row.function,
            "step": row.step,
            "output": row.output,
            "evidence": evidence.resolve(row.evidence_source_ids),
            "computedRefs": row.computed_refs,
            "label": row.interpretation_label,
            "labelRationale": row.label_rationale,
            "createdAt": row.created_at.isoformat(),
            "audit": _serialise_audit(audits[row.id]) if row.id in audits else None,
        }
        for row in rows
    ]


@router.post("/audit", status_code=201, dependencies=[Depends(require_feature("ai_audit"))])
def submit_audit(
    payload: AuditSubmission,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    interaction = db.get(AiInteraction, payload.interaction_id)
    if interaction is None or interaction.user_id != user.id:
        raise HTTPException(404, "AI interaction not found.")
    # Append-only: the AI's original output and evidence are never rewritten.
    record = AuditRecord(
        interaction_id=interaction.id,
        user_id=user.id,
        action=payload.action,
        learner_rationale=payload.learner_rationale,
        final_interpretation=payload.final_interpretation,
        revised_label=payload.revised_label,
    )
    db.add(record)
    db.commit()
    return _serialise_audit(record)


def _serialise_audit(record: AuditRecord) -> dict:
    return {
        "id": record.id,
        "interactionId": record.interaction_id,
        "action": record.action,
        "learnerRationale": record.learner_rationale,
        "finalInterpretation": record.final_interpretation,
        "revisedLabel": record.revised_label,
        "createdAt": record.created_at.isoformat(),
    }
