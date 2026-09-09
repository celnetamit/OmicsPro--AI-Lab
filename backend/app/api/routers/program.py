"""Lab Home, Knowledge Bank, Pre-Lab Assessment (spec 9.1, 9.2, 9.3, 9.11)."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import current_tier, current_user, require_feature
from app.constants import ACTIVE_PHASE, TRACK_LABELS, AccessTier, AnalysisTrack
from app.content import knowledge_bank, program as program_content
from app.copilot import evidence
from app.core import entitlements as ent
from app.db import get_db
from app.content import assessment as assessment_content
from app.core import assessment
from app.models import AssessmentResult, DesignPlan, Enrollment, Run, User
from app.pipelines import registry

router = APIRouter(prefix="/api/program", tags=["program"])


@router.get("/home")
def lab_home(
    user: User = Depends(current_user),
    tier: AccessTier = Depends(current_tier),
    db: Session = Depends(get_db),
) -> dict:
    enrollment = db.scalar(select(Enrollment).where(Enrollment.user_id == user.id))
    current_week = enrollment.current_week if enrollment else 1
    recent = db.scalars(
        select(Run).where(Run.user_id == user.id).order_by(Run.created_at.desc()).limit(10)
    ).all()

    weeks = []
    for week in program_content.WEEKS:
        available = week["phase"] <= ACTIVE_PHASE
        weeks.append(
            {
                **week,
                "unlocked": available and week["week"] <= current_week,
                "available": available,
                "status": (
                    "scheduled_for_later_release"
                    if not available
                    else "open"
                    if week["week"] <= current_week
                    else "locked_until_week"
                ),
            }
        )

    return {
        "currentWeek": current_week,
        "accessTier": tier.value,
        "weeks": weeks,
        "availableTracks": [
            {"track": t.value, "label": TRACK_LABELS[t]} for t in registry.available_tracks()
        ],
        "availableModules": [
            {
                "module": entry["module"],
                "label": entry["label"],
                "track": entry["track"].value,
                "unlocked": ent.has_feature(tier, entry["feature"]),
                "requiredTier": ent.get_feature(entry["feature"]).min_tier.value,
                "lockedExplanation": (
                    ""
                    if ent.has_feature(tier, entry["feature"])
                    else ent.get_feature(entry["feature"]).locked_explanation
                ),
            }
            for entry in registry.available_modules()
        ],
        "recentRuns": [
            {
                "id": r.id,
                "track": r.track,
                "status": r.status,
                "createdAt": r.created_at.isoformat(),
                "isOriginal": r.is_original,
            }
            for r in recent
        ],
        "hasDesignPlan": db.scalar(
            select(DesignPlan).where(DesignPlan.user_id == user.id)
        )
        is not None,
        "lockedFeatures": [
            row for row in ent.matrix_for(tier, ACTIVE_PHASE) if not row["unlocked"]
        ],
    }


@router.get("/knowledge-bank", dependencies=[Depends(require_feature("knowledge_bank"))])
def get_knowledge_bank() -> dict:
    cards = []
    for card in knowledge_bank.CARDS:
        cards.append({**card, "references": evidence.resolve(card["evidenceSourceIds"])})
    return {"cards": cards, "glossary": knowledge_bank.GLOSSARY}


PRE_LAB_QUESTIONS = [
    {
        "id": "replication",
        "prompt": (
            "A single-cell dataset holds 40,000 cells from two donors, one per "
            "condition. How many biological replicates does the condition "
            "comparison have?"
        ),
        "options": ["40,000", "2", "1 per condition", "It depends on the cell types"],
        "answer": 2,
        "reviewTopic": "replication-unit",
        "explanation": (
            "Each condition is represented by one donor, so there is one "
            "biological replicate per group and no way to separate the condition "
            "effect from donor-to-donor variation."
        ),
    },
    {
        "id": "zeros",
        "prompt": "In a single-cell count matrix, what does a zero most reliably mean?",
        "options": [
            "The gene is switched off in that cell",
            "The transcript was not detected in that cell",
            "The cell is dead",
            "The gene is not expressed in that tissue",
        ],
        "answer": 1,
        "reviewTopic": "how-scrna-data-is-generated",
        "explanation": (
            "Capture is incomplete, so a zero records non-detection rather than "
            "absence of expression."
        ),
    },
    {
        "id": "clusters",
        "prompt": "You raise the clustering resolution and get four more clusters. What follows?",
        "options": [
            "Four more cell types are present",
            "The earlier clustering was wrong",
            "The graph was partitioned more finely; whether the new clusters are "
            "real populations depends on their markers",
            "The data needs reprocessing",
        ],
        "answer": 2,
        "reviewTopic": "clustering-is-a-choice",
        "explanation": (
            "Cluster count follows from the resolution. Marker support is what "
            "distinguishes a population from a partition artefact."
        ),
    },
    {
        "id": "padj",
        "prompt": "A gene has an adjusted p-value of 0.03. What does that mean?",
        "options": [
            "There is a 3% chance this gene is a false positive",
            "The gene changed by 3%",
            "Among genes called at this threshold, roughly 3% are expected to be "
            "false discoveries",
            "The effect is small",
        ],
        "answer": 2,
        "reviewTopic": "multiple-testing",
        "explanation": (
            "The adjustment controls the false discovery proportion of the called "
            "set, not the status of an individual gene."
        ),
    },
    {
        "id": "enrichment",
        "prompt": "A pathway is enriched in your differentially expressed genes. What can you say?",
        "options": [
            "The pathway is activated",
            "Your gene list overlaps that curated set more than chance predicts",
            "The pathway is inhibited",
            "The pathway drives the phenotype",
        ],
        "answer": 1,
        "reviewTopic": "enrichment-vs-activity",
        "explanation": (
            "Over-representation is a statement about set membership, not about "
            "the direction or activity of the process."
        ),
    },
]


class WeekAssessmentSubmission(BaseModel):
    week: int = 1
    responses: dict


class AssessmentSubmission(BaseModel):
    assessment_id: str = "pre-lab"
    week: int = 1
    responses: dict


@router.get("/pre-lab", dependencies=[Depends(require_feature("pre_lab_assessment"))])
def pre_lab() -> dict:
    return {
        "assessmentId": "pre-lab",
        "questions": [
            {k: v for k, v in q.items() if k not in ("answer", "explanation")}
            for q in PRE_LAB_QUESTIONS
        ],
    }


@router.post("/pre-lab", dependencies=[Depends(require_feature("pre_lab_assessment"))])
def submit_pre_lab(
    payload: AssessmentSubmission,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    correct, review, feedback = 0, [], []
    for question in PRE_LAB_QUESTIONS:
        given = payload.responses.get(question["id"])
        is_correct = given == question["answer"]
        correct += int(is_correct)
        if not is_correct:
            review.append(question["reviewTopic"])
        feedback.append(
            {
                "id": question["id"],
                "correct": is_correct,
                "explanation": question["explanation"],
                "reviewTopic": question["reviewTopic"],
            }
        )
    score = correct / len(PRE_LAB_QUESTIONS)
    result = AssessmentResult(
        user_id=user.id,
        assessment_id=payload.assessment_id,
        week=payload.week,
        responses=payload.responses,
        score=score,
        recommended_topics=review,
    )
    db.add(result)
    db.commit()
    return {
        "score": round(score, 2),
        "correct": correct,
        "total": len(PRE_LAB_QUESTIONS),
        "feedback": feedback,
        "recommendedTopics": review,
    }


# ------------------------------------------------------- week assessment --
@router.get("/assessment", dependencies=[Depends(require_feature("assessment"))])
def week_assessment(
    week: int = 1,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    """The week's concept questions, plus what has already been measured.

    The measured components are returned before submission so the learner can
    see what the assessment reads from their work rather than being graded by
    something invisible.
    """
    state = assessment.assess(db, user.id, week, responses=None)
    previous = db.scalars(
        select(AssessmentResult)
        .where(
            AssessmentResult.user_id == user.id,
            AssessmentResult.assessment_id == f"week-{week}",
        )
        .order_by(AssessmentResult.created_at.desc())
    ).first()
    return {
        "assessmentId": f"week-{week}",
        "week": week,
        "questions": [
            {k: v for k, v in q.items() if k not in ("answer", "explanation")}
            for q in assessment_content.questions_for(week)
        ],
        "components": state["components"],
        "note": state["note"],
        "previousScore": round(previous.score, 2) if previous else None,
        "previousTakenAt": previous.created_at.isoformat() if previous else None,
    }


@router.post("/assessment", dependencies=[Depends(require_feature("assessment"))])
def submit_week_assessment(
    payload: WeekAssessmentSubmission,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Grade the week: concepts marked, decisions and interpretation measured."""
    result = assessment.assess(db, user.id, payload.week, responses=payload.responses)
    record = AssessmentResult(
        user_id=user.id,
        assessment_id=f"week-{payload.week}",
        week=payload.week,
        responses=payload.responses,
        #: Stored as 0.0 when nothing was assessable; the breakdown carries the
        #: distinction, and the column is not nullable.
        score=result["score"] or 0.0,
        recommended_topics=result["recommendedTopics"],
    )
    db.add(record)
    db.commit()
    return result
