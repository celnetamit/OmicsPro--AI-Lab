"""Request dependencies — authentication and the server-side entitlement gate.

Spec 2/10/14.2: the checks here run on every protected endpoint regardless of
what the front end believes. ``require_feature`` is the only sanctioned way to
gate an endpoint; do not hand-roll a tier comparison in a router.
"""

from typing import Callable

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.constants import ACTIVE_PHASE, AccessTier
from app.core import entitlements as ent
from app.core.access import effective_tier
from app.core.security import decode_access_token
from app.db import get_db
from app.models import User


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing bearer token")
    user_id = decode_access_token(header.split(" ", 1)[1].strip())
    if not user_id:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token")
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Unknown user")
    return user


def current_tier(
    user: User = Depends(current_user), db: Session = Depends(get_db)
) -> AccessTier:
    return effective_tier(db, user.id)


def require_admin(user: User = Depends(current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin access required")
    return user


def require_feature(feature_key: str) -> Callable:
    """Server-side entitlement gate for one endpoint.

    Returns 403 with the matrix's own upgrade copy so the client can render the
    same explanation it would have shown on the locked control.
    """
    feature = ent.get_feature(feature_key)

    def _dependency(tier: AccessTier = Depends(current_tier)) -> AccessTier:
        if feature.phase > ACTIVE_PHASE:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND,
                f"'{feature.label}' is not available in this release.",
            )
        try:
            ent.assert_feature(tier, feature_key)
        except ent.EntitlementError as exc:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                {
                    "error": "entitlement_required",
                    "feature": feature.key,
                    "requiredTier": feature.min_tier.value,
                    "currentTier": tier.value,
                    "message": feature.locked_explanation or str(exc),
                },
            )
        return tier

    return _dependency
