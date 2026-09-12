"""Turning a verified NanoSchool launch into a session in this lab.

The hub says who someone is; this decides what that means locally. Every run,
interpretation, capstone and report in OmicsLab belongs to a row in ``users``,
so a launch has to resolve to exactly one such row — the same one every time,
for years, across browsers and devices.

Matching is by the hub's user id, which is the only identifier that holds still.
Email is used to *find* a row exactly once: to adopt one an operator created
ahead of someone's first launch, which is how an administrator is appointed (see
scripts/seed.py). After that the row carries the hub id and is never looked up
by address again, so a person who changes their email on the platform keeps
their work instead of silently starting a second, empty account — the address is
merely kept up to date from then on.
"""

from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.constants import AccessTier
from app.core.access import ensure_basic_auto_grant, ensure_granted_tier
from app.core.hub import HubIdentity
from app.models import Enrollment, User
from app.settings import settings

#: Recorded on the enrollment of an account the hub provisioned, so a cohort
#: report can tell a platform launch from a locally seeded row.
HUB_COHORT = "nanoschool"


def _usable_email(db: Session, identity: HubIdentity, current: Optional[User]) -> Optional[str]:
    """The hub's address for this person, unless another row already holds it.

    Emails are unique here, and the hub's are not this table's to arrange: two
    accounts can end up pointing at one address — an operator seeds
    `ops@example.org`, person A adopts that row, and person B later changes
    their platform address to the same thing. Writing it anyway raises an
    integrity error, which would turn a routine launch into a 500 and lock
    someone out of a lab for a reason that has nothing to do with them. So the
    collision is simply left alone: the row keeps the address it has, which is
    stale at worst, and the account is still identified by its hub id.
    """
    email = (identity.email or "").strip().lower()
    if not email:
        return None
    if current is not None and (current.email or "").lower() == email:
        return email
    clash = db.scalar(select(User).where(func.lower(User.email) == email))
    if clash is not None and (current is None or clash.id != current.id):
        return None
    return email


def provision(db: Session, identity: HubIdentity) -> User:
    """Find or create the lab account for a verified hub identity."""
    user = db.scalar(select(User).where(User.hub_user_id == identity.user_id))

    if user is None and identity.email:
        #: Adopt a row seeded by email before this person's first launch. The
        #: comparison is case-insensitive because an address typed into a seed
        #: script and one stored by the hub routinely differ in case only.
        user = db.scalar(
            select(User).where(
                func.lower(User.email) == identity.email.lower(),
                User.hub_user_id.is_(None),
            )
        )
        if user is not None:
            user.hub_user_id = identity.user_id

    if user is None:
        user = User(
            hub_user_id=identity.user_id,
            #: The hub guarantees an id, not an address. A synthetic local
            #: address keeps the column's uniqueness meaningful without
            #: pretending to know an email nobody supplied.
            email=_usable_email(db, identity, current=None)
            or f"{identity.user_id}@hub.invalid",
            full_name=identity.name or "",
        )
        db.add(user)
        db.flush()
        db.add(
            Enrollment(
                user_id=user.id, program_code="flagship-8w", cohort=HUB_COHORT
            )
        )
    else:
        #: Keep the details the hub owns fresh, so a corrected name or address
        #: on the platform shows up here on the next launch.
        fresh_email = _usable_email(db, identity, current=user)
        if fresh_email:
            user.email = fresh_email
        if identity.name:
            user.full_name = identity.name

    #: The reviewer flag follows the hub exactly, including being taken away.
    user.is_reviewer = identity.is_reviewer

    #: Admin, however, only ever goes up here. The hub's ADMIN and SUPER_ADMIN
    #: roles grant this lab's admin console; a lab admin appointed directly in
    #: the database — someone with no hub admin role who runs the ingestion and
    #: sign-off screens — is not demoted by launching the lab. Taking lab admin
    #: away is a deliberate act in the lab's own database, not a side effect.
    if identity.is_admin:
        user.is_admin = True

    db.commit()

    ensure_basic_auto_grant(db, user.id)
    ensure_granted_tier(db, user.id, AccessTier(settings.granted_tier))
    db.refresh(user)
    return user


def dev_account(db: Session) -> User:
    """The account behind ``POST /api/auth/dev-session``.

    Local development and smoke tests only: the endpoint that calls this is
    refused in production and off unless ``OMICSLAB_DEV_LAB_SESSION`` is set.
    It is an administrator because the screens a developer most needs to reach
    without a hub are the ones behind the admin console, and because this
    account cannot exist on a deployment where that would matter.
    """
    email = "dev-session@omicslab.local"
    user: Optional[User] = db.scalar(select(User).where(User.email == email))
    if user is None:
        user = User(
            email=email,
            full_name="Local development session",
            is_admin=True,
        )
        db.add(user)
        db.flush()
        db.add(
            Enrollment(user_id=user.id, program_code="flagship-8w", cohort="development")
        )
        db.commit()

    ensure_basic_auto_grant(db, user.id)
    ensure_granted_tier(db, user.id, AccessTier(settings.granted_tier))
    db.refresh(user)
    return user
