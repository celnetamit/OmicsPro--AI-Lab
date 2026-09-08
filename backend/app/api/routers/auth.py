"""Registration, login, the open-access session, and the Basic auto-grant."""

import secrets

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import current_tier, current_user
from app.constants import ACTIVE_PHASE, AccessTier
from app.core.access import ensure_basic_auto_grant
from app.core import ratelimit
from app.core.security import (
    PasswordPolicyError,
    create_access_token,
    hash_password,
    validate_password,
    verify_password,
)
from app.settings import settings
from app.db import get_db
from app.models import Enrollment, User

router = APIRouter(prefix="/api/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)
    full_name: str = ""
    #: Standalone build: enrollment is asserted at registration. When the
    #: NanoSchool platform is integrated this comes from its enrollment API.
    program_code: str = "flagship-8w"
    cohort: str = ""


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=200)
    new_password: str = Field(min_length=1, max_length=200)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


@router.post("/register", response_model=TokenResponse, status_code=201)
def register(
    payload: RegisterRequest, request: Request, db: Session = Depends(get_db)
) -> TokenResponse:
    ratelimit.enforce(request, "register", settings.register_rate_limit)
    try:
        validate_password(payload.password, email=payload.email)
    except PasswordPolicyError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            {"error": "weak_password", "field": "password", "message": str(exc)},
        )
    if db.scalar(select(User).where(User.email == payload.email)):
        raise HTTPException(status.HTTP_409_CONFLICT, "That email is already registered.")
    user = User(
        email=payload.email,
        full_name=payload.full_name,
        password_hash=hash_password(payload.password),
    )
    db.add(user)
    db.flush()
    db.add(Enrollment(user_id=user.id, program_code=payload.program_code, cohort=payload.cohort))
    db.commit()
    # Basic is auto-granted off the enrollment, never sold (spec 2).
    ensure_basic_auto_grant(db, user.id)
    return TokenResponse(access_token=create_access_token(user.id))


@router.post("/login", response_model=TokenResponse)
def login(
    payload: LoginRequest, request: Request, db: Session = Depends(get_db)
) -> TokenResponse:
    #: Rate limited per client address: this is the endpoint credential
    #: stuffing aims at, and the limit is what makes a weak password survivable.
    ratelimit.enforce(request, "login", settings.login_rate_limit)
    user = db.scalar(select(User).where(User.email == payload.email))
    #: One message for both failures, so the response cannot be used to
    #: enumerate which addresses have accounts.
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect email or password.")
    ensure_basic_auto_grant(db, user.id)
    return TokenResponse(access_token=create_access_token(user.id))


@router.post("/guest", response_model=TokenResponse)
def guest(request: Request, db: Session = Depends(get_db)) -> TokenResponse:
    """Open the Live Lab without credentials.

    Every run, interpretation and report belongs to a user, so an open-access
    visitor is still a real account — one shared, enrolled, Basic-tier account
    rather than an anonymous request with no owner. The password is random and
    unusable: the account is reachable only through this endpoint.

    Disabled when ``OMICSLAB_OPEN_ACCESS`` is false, which is how the sign-in
    screen is put back in front of the app.
    """
    if not settings.open_access:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Open access is not enabled on this deployment."
        )
    ratelimit.enforce(request, "guest", settings.global_rate_limit)

    user = db.scalar(select(User).where(User.email == settings.guest_email))
    if user is None:
        user = User(
            email=settings.guest_email,
            full_name=settings.guest_name,
            #: Not a usable credential: no one can log in as this account.
            password_hash=hash_password(secrets.token_urlsafe(32)),
        )
        db.add(user)
        db.flush()
        db.add(Enrollment(user_id=user.id, program_code="flagship-8w", cohort="open-access"))
        db.commit()
    ensure_basic_auto_grant(db, user.id)
    return TokenResponse(access_token=create_access_token(user.id))


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
        "accessTier": tier.value,
        "programCode": enrollment.program_code if enrollment else None,
        "currentWeek": enrollment.current_week if enrollment else None,
        "cohort": enrollment.cohort if enrollment else None,
        "activePhase": ACTIVE_PHASE,
        #: The client hides the sign-out control on an open-access deployment;
        #: whether this session began without credentials is the server's fact
        #: to report, not something the client can infer from a stored token.
        "openAccess": settings.open_access,
    }


@router.post("/password", status_code=204)
def change_password(
    payload: ChangePasswordRequest,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> None:
    """Change the signed-in account's password.

    Issued tokens stay valid until they expire: this build has no revocation
    list, and claiming otherwise would be worse than saying so. Token lifetime
    is ``OMICSLAB_ACCESS_TOKEN_TTL_MINUTES``.
    """
    ratelimit.enforce(request, "password-change", settings.login_rate_limit)
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "That is not your current password.")
    try:
        validate_password(payload.new_password, email=user.email)
    except PasswordPolicyError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            {"error": "weak_password", "field": "new_password", "message": str(exc)},
        )
    user.password_hash = hash_password(payload.new_password)
    db.commit()
