"""Learner-reported issues (spec 14).

Spec 14 asks the admin console to "review AI audit records and learner-reported
issues". This is the learner's side: a way to report a problem from wherever it
happened, with the screen and run captured so it can be reproduced.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import current_user
from app.core import ratelimit
from app.db import get_db
from app.models import IssueReport, Run, User
from app.settings import settings

router = APIRouter(prefix="/api/issues", tags=["issues"])

CATEGORIES = ("scientific", "technical", "content", "access", "other")


class IssueRequest(BaseModel):
    category: str = "other"
    message: str = Field(min_length=10, max_length=4000)
    screen: str = Field(default="", max_length=128)
    run_id: Optional[str] = None


def serialise(issue: IssueReport) -> dict:
    return {
        "id": issue.id,
        "userId": issue.user_id,
        "runId": issue.run_id,
        "screen": issue.screen,
        "category": issue.category,
        "message": issue.message,
        "status": issue.status,
        "adminNote": issue.admin_note,
        "createdAt": issue.created_at.isoformat(),
        "resolvedAt": issue.resolved_at.isoformat() if issue.resolved_at else None,
    }


@router.post("", status_code=201)
def report_issue(
    payload: IssueRequest,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    #: Reporting must stay open to every tier — a problem is a problem — so it
    #: is rate limited rather than entitlement gated.
    ratelimit.enforce(request, "issue-report", "20/3600")
    if payload.category not in CATEGORIES:
        raise HTTPException(
            422, f"Choose one of: {', '.join(CATEGORIES)}."
        )
    if payload.run_id:
        run = db.get(Run, payload.run_id)
        #: A learner may attach only their own run; anything else is dropped
        #: rather than leaked into another person's record.
        if run is None or run.user_id != user.id:
            raise HTTPException(404, "That run is not one of yours.")
    issue = IssueReport(
        user_id=user.id,
        run_id=payload.run_id or None,
        screen=payload.screen,
        category=payload.category,
        message=payload.message.strip(),
    )
    db.add(issue)
    db.commit()
    return serialise(issue)


@router.get("")
def my_issues(user: User = Depends(current_user), db: Session = Depends(get_db)) -> list:
    rows = db.scalars(
        select(IssueReport)
        .where(IssueReport.user_id == user.id)
        .order_by(IssueReport.created_at.desc())
    ).all()
    return [serialise(row) for row in rows]
