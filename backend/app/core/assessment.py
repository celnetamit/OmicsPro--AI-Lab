"""Week assessment scoring (spec 9.11, 13).

The assessment has three components and only the first is asked as questions:

  concept understanding    answers to the week's concept questions
  analytical decisions     measured from the decisions the learner recorded
  interpretation quality   measured from the interpretations they wrote

The second and third are deliberately not self-reported. Asking a learner to
rate their own reasoning would produce a number with nothing behind it; the
platform already stores what they actually did, so the assessment reads that.

A component with no work behind it is reported as *not yet assessable* rather
than scored zero, and the overall score is the mean of the components that
could be assessed. A zero would claim the learner reasoned badly when the truth
is that they have not reached that part of the week.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.constants import AuditAction
from app.content.assessment import questions_for
from app.models import AiInteraction, AuditRecord, Interpretation, Perturbation, Run

#: The four fields an interpretation must separate (spec 9.10).
INTERPRETATION_FIELDS = (
    "observation",
    "statistical_evidence",
    "biological_interpretation",
    "hypothesis",
)


@dataclass
class Component:
    key: str
    label: str
    #: What this component measures, shown to the learner.
    measures: str
    #: None when there is nothing recorded to assess yet.
    score: Optional[float] = None
    counted: int = 0
    total: int = 0
    notes: List[str] = field(default_factory=list)

    @property
    def assessable(self) -> bool:
        return self.score is not None

    def as_dict(self) -> dict:
        return {
            "key": self.key,
            "label": self.label,
            "measures": self.measures,
            "assessable": self.assessable,
            "score": round(self.score, 2) if self.score is not None else None,
            "counted": self.counted,
            "total": self.total,
            "notes": self.notes,
        }


def _week_runs(db: Session, user_id: str, week: int) -> List[Run]:
    return list(
        db.scalars(select(Run).where(Run.user_id == user_id, Run.week == week)).all()
    )


def score_concepts(week: int, responses: Dict[str, str]) -> tuple:
    """Objective marking of the week's concept questions."""
    questions = questions_for(week)
    feedback, review, correct = [], [], 0
    for question in questions:
        given = responses.get(question["id"])
        is_correct = given == question["answer"]
        correct += int(is_correct)
        if not is_correct:
            review.append(question["reviewTopic"])
        feedback.append(
            {
                "id": question["id"],
                "correct": is_correct,
                "given": given,
                "answer": question["answer"],
                "explanation": question["explanation"],
                "reviewTopic": question["reviewTopic"],
            }
        )
    component = Component(
        key="concepts",
        label="Concept understanding",
        measures="Answers to this week's concept questions.",
        score=(correct / len(questions)) if questions else None,
        counted=correct,
        total=len(questions),
    )
    return component, feedback, review


def measure_decisions(db: Session, user_id: str, week: int) -> Component:
    """Analytical decisions, read from the perturbation record.

    A decision counts as sound when the learner engaged the what-if at all —
    TEST or SKIP are both defensible — and, when they tested it, the alternate
    run actually completed so the comparison exists.
    """
    component = Component(
        key="decisions",
        label="Analytical decisions",
        measures=(
            "What-if decisions you recorded this week, and whether the alternate "
            "run that a TEST produced completed so the comparison exists."
        ),
    )
    runs = _week_runs(db, user_id, week)
    if not runs:
        component.notes.append("No runs recorded for this week yet.")
        return component

    run_ids = [r.id for r in runs]
    records = list(
        db.scalars(select(Perturbation).where(Perturbation.run_id.in_(run_ids))).all()
    )
    if not records:
        component.notes.append(
            "No what-if decision recorded yet. The Copilot offers one on a completed step."
        )
        return component

    sound = 0
    for record in records:
        if record.decision == "skip":
            sound += 1
        elif record.decision == "test" and record.actual_outcome:
            sound += 1
    component.counted, component.total = sound, len(records)
    component.score = sound / len(records)
    tested = sum(1 for r in records if r.decision == "test")
    component.notes.append(
        f"{tested} tested, {len(records) - tested} skipped, out of {len(records)} offered."
    )
    return component


def measure_interpretation(db: Session, user_id: str, week: int) -> Component:
    """Interpretation quality, read from what the learner wrote.

    Quality here means the four fields were kept separate and filled — the
    distinction the spec asks the UI and the report to preserve — and that the
    Copilot's output was adjudicated rather than accepted silently.
    """
    component = Component(
        key="interpretation",
        label="Interpretation quality",
        measures=(
            "Whether your interpretations separate observation, statistical "
            "evidence, biological interpretation and hypothesis, and whether you "
            "adjudicated the Copilot's output."
        ),
    )
    runs = _week_runs(db, user_id, week)
    if not runs:
        component.notes.append("No runs recorded for this week yet.")
        return component

    run_ids = [r.id for r in runs]
    written = list(
        db.scalars(select(Interpretation).where(Interpretation.run_id.in_(run_ids))).all()
    )
    if not written:
        component.notes.append("No interpretation saved yet.")
        return component

    complete = sum(
        1
        for entry in written
        if all(getattr(entry, field_name, "").strip() for field_name in INTERPRETATION_FIELDS)
    )
    component.counted, component.total = complete, len(written)
    field_score = complete / len(written)

    #: Adjudication: did the learner act on the Copilot output for these runs?
    interactions = list(
        db.scalars(select(AiInteraction).where(AiInteraction.run_id.in_(run_ids))).all()
    )
    audited = 0
    if interactions:
        interaction_ids = [i.id for i in interactions]
        actions = list(
            db.scalars(
                select(AuditRecord).where(AuditRecord.interaction_id.in_(interaction_ids))
            ).all()
        )
        audited = len({a.interaction_id for a in actions})
        considered = sum(
            1 for a in actions if AuditAction(a.action) is not AuditAction.ACCEPT
        )
        component.notes.append(
            f"{audited} of {len(interactions)} Copilot outputs adjudicated"
            + (f", {considered} modified, rejected or flagged." if considered else ".")
        )
        adjudication = audited / len(interactions)
    else:
        adjudication = None
        component.notes.append("No Copilot output to adjudicate yet.")

    if complete < len(written):
        component.notes.append(
            f"{len(written) - complete} interpretation(s) left a field empty."
        )

    component.score = field_score if adjudication is None else (field_score + adjudication) / 2
    return component


def assess(db: Session, user_id: str, week: int, responses: Optional[Dict[str, str]] = None) -> dict:
    """The full week assessment. Without responses, the measured components only."""
    components: List[Component] = []
    feedback: List[dict] = []
    review: List[str] = []

    if responses is not None:
        concepts, feedback, review = score_concepts(week, responses)
        components.append(concepts)

    components.append(measure_decisions(db, user_id, week))
    components.append(measure_interpretation(db, user_id, week))

    assessed = [c for c in components if c.assessable]
    overall = sum(c.score for c in assessed) / len(assessed) if assessed else None
    pending = [c.label for c in components if not c.assessable]

    return {
        "week": week,
        "components": [c.as_dict() for c in components],
        "score": round(overall, 2) if overall is not None else None,
        "assessedComponents": [c.key for c in assessed],
        "pendingComponents": pending,
        "feedback": feedback,
        "recommendedTopics": review,
        "note": (
            "Components with no recorded work are not scored. The overall figure "
            "is the mean of the components that could be assessed, so finishing "
            "the week's analysis changes what is measured, not only the score."
        ),
    }
