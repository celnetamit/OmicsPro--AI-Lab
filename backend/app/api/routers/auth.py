"""The only way into this lab: a verified NanoSchool launch.

OmicsLab has no sign-in screen, no registration and no passwords. A learner
opens the lab from their NanoSchool dashboard, which appends a short-lived
launch token to the address; the front end hands that token to
``POST /api/auth/lab-session``; this server asks the hub who it belongs to and,
only if the hub says yes, issues the lab's own session token.

Why the exchange happens here rather than in the browser, and why the launch
token is spent exactly once, is set out in ``app/core/hub.py``. The short
version: a client-side gate decides what a screen renders, and this is an API
with a database behind it, so the gate that matters has to be on this side.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import current_tier, current_user
from app.constants import ACTIVE_PHASE, AccessTier
from app.core import hub, ratelimit
from app.core.lab_session import dev_account, provision
from app.core.security import create_access_token
from app.settings import settings
from app.db import get_db
from app.models import Enrollment, User

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LabSessionRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    #: The launch token NanoSchool put in the address bar. Not a JWT this lab
    #: can read, and it deliberately never tries: only the hub can verify it.
    token: str = Field(min_length=1, max_length=4096)
    #: Where the lab was opened. The hub resolves which lab is being launched
    #: from it, and falls back to the configured slug when it is absent.
    domain_url: str | None = Field(default=None, alias="domainUrl", max_length=500)


def _session_payload(user: User, authorization: hub.HubAuthorization | None) -> dict:
    """The session, and who the hub said it belongs to.

    ``identity`` is null when there is no authorization behind the session — a
    development session. That is the honest answer and it matters: the client
    stores this as the verified NanoSchool account, and a plausible-looking
    identity nobody verified is precisely how a lab ends up filing an expert's
    undertaking, or a learner's feedback, against an account that does not
    exist. The lab still opens; it simply cannot name anyone.
    """
    identity = authorization.identity if authorization else None
    return {
        "access_token": create_access_token(user.id),
        "token_type": "bearer",
        #: camelCase, because this is read straight into the browser's identity
        #: store, which the other Live Labs share the shape of.
        "identity": None
        if identity is None
        else {
            "userId": identity.user_id,
            "email": user.email,
            "name": user.full_name or identity.name or "",
            "role": identity.role,
            "labId": identity.lab_id,
            "labSlug": identity.lab_slug or settings.lab_slug,
            "isReviewer": user.is_reviewer,
        },
        #: The hub's own credential, relayed for the browser's later calls to
        #: NanoSchool: feedback, the reviewer agreement, the review form. This
        #: server holds no use for it.
        "hubSessionToken": authorization.session_token if authorization else None,
        "hubSessionExpiresAt": authorization.session_expires_at if authorization else None,
    }


@router.post("/lab-session")
def lab_session(
    payload: LabSessionRequest, request: Request, db: Session = Depends(get_db)
) -> dict:
    """Exchange a NanoSchool launch token for a session in this lab."""
    ratelimit.enforce(request, "lab-session", settings.lab_session_rate_limit)

    try:
        authorization = hub.authorize_launch(payload.token, payload.domain_url)
    except hub.HubRefused as exc:
        #: The hub answered, and the answer was no. Relaunching from the
        #: dashboard is what fixes this, so the address to do that is included.
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            {
                "error": "launch_refused",
                "message": exc.message,
                "loginUrl": settings.hub_login_url,
            },
        )
    except hub.HubUnreachable:
        #: Not a refusal, and it must not be dressed up as one: sending someone
        #: to sign in again cannot fix a hub that is not answering.
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            {
                "error": "hub_unreachable",
                "message": (
                    "Could not reach NanoSchool to check this launch. This is a "
                    "connection problem rather than a problem with your account. "
                    "Try again in a moment."
                ),
            },
        )

    user = provision(db, authorization.identity)
    return _session_payload(user, authorization)


@router.post("/dev-session")
def dev_session(request: Request, db: Session = Depends(get_db)) -> dict:
    """Open a lab session with no hub, for local development and smoke tests.

    Absent unless ``OMICSLAB_DEV_LAB_SESSION`` is set, and configuration
    refuses to start in production with it set. The 404 is the same one any
    unknown path gets, so a deployment does not advertise that this exists.
    """
    if not settings.dev_lab_session or settings.is_production:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not Found")
    ratelimit.enforce(request, "dev-session", settings.lab_session_rate_limit)
    user = dev_account(db)
    payload = _session_payload(user, None)
    #: Said plainly, so a screenshot of a development session can never be
    #: mistaken for a NanoSchool one. The front end shows a banner on it.
    payload["development"] = True
    return payload


@router.get("/me")
def me(
    user: User = Depends(current_user),
    tier: AccessTier = Depends(current_tier),
    db: Session = Depends(get_db),
) -> dict:
    enrollment = db.scalar(select(Enrollment).where(Enrollment.user_id == user.id))
    return {
        "id": user.id,
        "email": user.email,
        "fullName": user.full_name,
        "isAdmin": user.is_admin,
        "isReviewer": user.is_reviewer,
        "accessTier": tier.value,
        "programCode": enrollment.program_code if enrollment else None,
        "currentWeek": enrollment.current_week if enrollment else None,
        "cohort": enrollment.cohort if enrollment else None,
        "activePhase": ACTIVE_PHASE,
        #: Where this session came from. A row with no hub id was opened by the
        #: development endpoint or seeded by an operator, and the interface says
        #: so rather than implying NanoSchool vouched for it.
        "authSource": "nanoschool" if user.hub_user_id else "local",
        #: Where to send someone whose session has ended. The client should not
        #: have to hard-code the hub's address to offer a relaunch.
        "hubUrl": settings.hub_base_url.rstrip("/"),
    }
