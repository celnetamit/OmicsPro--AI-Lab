"""Resolution of a user's effective access tier, plus the auto-grant rule.

Kept separate from the entitlement *matrix* (which says what a tier may do) so
there is one place that answers "which tier is this user, right now".
"""

from datetime import datetime
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.constants import AccessTier
from app.models import Enrollment, Entitlement


def active_entitlements(db: Session, user_id: str, at: Optional[datetime] = None) -> List[Entitlement]:
    rows = db.scalars(select(Entitlement).where(Entitlement.user_id == user_id)).all()
    return [e for e in rows if e.is_active(at)]


def effective_tier(db: Session, user_id: str, at: Optional[datetime] = None) -> AccessTier:
    """Highest active grant. Expiry silently downgrades; it never deletes data."""
    tiers = [AccessTier(e.tier) for e in active_entitlements(db, user_id, at)]
    if not tiers:
        return AccessTier.BASIC if _has_active_enrollment(db, user_id) else AccessTier.BASIC
    return max(tiers, key=lambda t: t.rank)


def _has_active_enrollment(db: Session, user_id: str) -> bool:
    return (
        db.scalar(
            select(Enrollment).where(Enrollment.user_id == user_id, Enrollment.active.is_(True))
        )
        is not None
    )


def ensure_open_access_tier(db: Session, user_id: str, tier: AccessTier) -> Optional[Entitlement]:
    """Hold the open-access session at a configured tier.

    Used only by the shared open-access account, so an evaluation deployment can
    exercise the paid features without a purchase. Idempotent, and it grants
    rather than bypasses: every entitlement check still runs, the account simply
    holds the grant. Basic needs nothing beyond the enrollment auto-grant.
    """
    if tier is AccessTier.BASIC:
        return None
    for entitlement in active_entitlements(db, user_id):
        if AccessTier(entitlement.tier) is tier:
            return entitlement
    granted = Entitlement(
        user_id=user_id,
        tier=tier,
        source="open_access_configuration",
        expires_at=None,
        note="Granted by OMICSLAB_OPEN_ACCESS_TIER for evaluation.",
    )
    db.add(granted)
    db.commit()
    return granted


def ensure_basic_auto_grant(db: Session, user_id: str) -> Optional[Entitlement]:
    """Auto-grant Basic on flagship enrollment (spec 2, 13).

    Idempotent: repeated calls do not stack duplicate grants.
    """
    if not _has_active_enrollment(db, user_id):
        return None
    for entitlement in active_entitlements(db, user_id):
        if AccessTier(entitlement.tier) is AccessTier.BASIC:
            return entitlement
    granted = Entitlement(
        user_id=user_id,
        tier=AccessTier.BASIC,
        source="enrollment_auto_grant",
        expires_at=None,
    )
    db.add(granted)
    db.commit()
    return granted
