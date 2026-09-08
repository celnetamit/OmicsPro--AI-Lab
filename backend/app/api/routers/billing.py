"""Paid tier activation (spec 2, 12 Phase 2).

The platform records the order and activates the entitlement; it never handles
or stores card data. A provider integration replaces ``_charge`` — everything
else here, including the entitlement grant and its expiry, stays the same.

Basic is not sold. It is auto-granted on flagship enrollment, so it is absent
from the catalogue below by design.
"""

from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import current_tier, current_user
from app.constants import TIER_LABELS, AccessTier
from app.core import entitlements as ent
from app.db import get_db
from app.models import Entitlement, Purchase, Report, User

router = APIRouter(prefix="/api/billing", tags=["billing"])

#: Term and price per purchasable tier. Amounts are in minor currency units so
#: no floating point money reaches the database.
CATALOGUE = {
    AccessTier.MODERATE: {"term_days": 90, "amount_minor_units": 499000, "currency": "INR"},
    AccessTier.EXPERT: {"term_days": 90, "amount_minor_units": 1299000, "currency": "INR"},
}


class CheckoutRequest(BaseModel):
    tier: AccessTier


class ActivateRequest(BaseModel):
    purchase_id: str
    #: Reference returned by the payment provider. In this build the operator
    #: supplies it; a provider webhook supplies it in production.
    provider_reference: str


@router.get("/catalogue")
def catalogue(tier: AccessTier = Depends(current_tier)) -> dict:
    rows = []
    for candidate, terms in CATALOGUE.items():
        rows.append(
            {
                "tier": candidate.value,
                "label": TIER_LABELS[candidate],
                "termDays": terms["term_days"],
                "amountMinorUnits": terms["amount_minor_units"],
                "currency": terms["currency"],
                "purchasable": candidate.rank > tier.rank,
                "alreadyHeld": candidate.rank <= tier.rank,
                "adds": [f.label for f in ent.FEATURES.values() if f.min_tier is candidate],
            }
        )
    return {
        "currentTier": tier.value,
        "options": rows,
        "note": (
            "Basic is included with flagship enrollment and is never sold. Paid "
            "tiers add depth, repetition, independence and richer outputs; the "
            "teaching content of every week is included at every tier."
        ),
    }


@router.post("/checkout", status_code=201)
def checkout(
    payload: CheckoutRequest,
    user: User = Depends(current_user),
    tier: AccessTier = Depends(current_tier),
    db: Session = Depends(get_db),
) -> dict:
    if payload.tier not in CATALOGUE:
        raise HTTPException(422, f"{TIER_LABELS[payload.tier]} access is not purchasable.")
    if payload.tier.rank <= tier.rank:
        raise HTTPException(
            409,
            f"This account already holds {TIER_LABELS[tier]} access, which "
            f"includes everything in {TIER_LABELS[payload.tier]}.",
        )

    terms = CATALOGUE[payload.tier]
    purchase = Purchase(
        user_id=user.id,
        tier=payload.tier,
        term_days=terms["term_days"],
        amount_minor_units=terms["amount_minor_units"],
        currency=terms["currency"],
        provider="unconfigured",
        status="awaiting_payment",
    )
    db.add(purchase)
    db.commit()
    return {
        "id": purchase.id,
        "tier": purchase.tier,
        "status": purchase.status,
        "amountMinorUnits": purchase.amount_minor_units,
        "currency": purchase.currency,
        "termDays": purchase.term_days,
        "paymentUrl": None,
        "note": (
            "No payment provider is configured in this deployment, so the order "
            "is recorded as awaiting payment. An administrator can activate it "
            "once payment is confirmed out of band."
        ),
    }


@router.get("/purchases")
def purchases(user: User = Depends(current_user), db: Session = Depends(get_db)) -> list:
    rows = db.scalars(
        select(Purchase).where(Purchase.user_id == user.id).order_by(Purchase.created_at.desc())
    ).all()
    return [_serialise(row) for row in rows]


def _serialise(purchase: Purchase) -> dict:
    return {
        "id": purchase.id,
        "tier": purchase.tier,
        "status": purchase.status,
        "amountMinorUnits": purchase.amount_minor_units,
        "currency": purchase.currency,
        "termDays": purchase.term_days,
        "providerReference": purchase.provider_reference,
        "entitlementId": purchase.entitlement_id,
        "createdAt": purchase.created_at.isoformat(),
        "activatedAt": purchase.activated_at.isoformat() if purchase.activated_at else None,
    }


def activate_purchase(db: Session, purchase: Purchase, provider_reference: str) -> Entitlement:
    """Grant the entitlement a paid order bought.

    Idempotent: activating an already-activated order returns the entitlement it
    created rather than granting a second one.
    """
    if purchase.status == "activated" and purchase.entitlement_id:
        existing = db.get(Entitlement, purchase.entitlement_id)
        if existing is not None:
            return existing

    entitlement = Entitlement(
        user_id=purchase.user_id,
        tier=purchase.tier,
        source="purchase",
        expires_at=datetime.utcnow() + timedelta(days=purchase.term_days),
        note=f"purchase {purchase.id}",
    )
    db.add(entitlement)
    db.flush()
    purchase.entitlement_id = entitlement.id
    purchase.provider_reference = provider_reference
    purchase.status = "activated"
    purchase.activated_at = datetime.utcnow()
    db.commit()
    return entitlement


@router.get("/expiry")
def expiry(user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    """What a learner keeps when a paid tier lapses."""
    from app.core.access import active_entitlements

    paid = [
        e
        for e in active_entitlements(db, user.id)
        if AccessTier(e.tier) is not AccessTier.BASIC and e.expires_at
    ]
    retained = len(db.scalars(select(Report).where(Report.user_id == user.id)).all())
    return {
        "paidGrants": [
            {"tier": e.tier, "expiresAt": e.expires_at.isoformat()} for e in paid
        ],
        "reportsRetained": retained,
        "note": (
            "When a paid tier lapses, access returns to Basic. Reports, runs, "
            "interpretations and audit records you already produced stay "
            "readable; expiry never deletes prior work."
        ),
    }
