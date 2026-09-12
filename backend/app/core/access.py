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


#: The source recorded on grants the configured-tier switch makes, so it can
#: find and take back its own grants without ever touching a purchase.
#:
#: The literal string is deliberately unchanged from when this setting was
#: called OMICSLAB_OPEN_ACCESS_TIER: it is written into rows that exist in
#: deployed databases, and a new spelling would leave those grants orphaned —
#: never revoked, because nothing would recognise them as ours.
OPEN_ACCESS_SOURCE = "open_access_configuration"


def ensure_granted_tier(db: Session, user_id: str, tier: AccessTier) -> Optional[Entitlement]:
    """Hold an account at exactly the tier this deployment grants on arrival.

    Applied to every account the hub provisions, so an evaluation deployment can
    exercise the paid features without a purchase. It grants rather than
    bypasses: every entitlement check still runs, the account simply holds the
    grant. It also takes back what it gave: lowering the setting revokes the
    earlier grant, so returning to "basic" really closes the paid features
    again. Only grants made here are touched, never a purchase.
    """
    now = datetime.utcnow()
    held: Optional[Entitlement] = None
    for entitlement in active_entitlements(db, user_id):
        if entitlement.source != OPEN_ACCESS_SOURCE:
            continue
        if held is None and tier is not AccessTier.BASIC and AccessTier(entitlement.tier) is tier:
            held = entitlement
        else:
            entitlement.revoked_at = now
    if held is None and tier is not AccessTier.BASIC:
        held = Entitlement(
            user_id=user_id,
            tier=tier,
            source=OPEN_ACCESS_SOURCE,
            expires_at=None,
            note="Granted by OMICSLAB_GRANTED_TIER for evaluation.",
        )
        db.add(held)
    db.commit()
    return held


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
