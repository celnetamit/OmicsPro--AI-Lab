"""Entitlement matrix and upgrade screen data (spec 9.13)."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import current_tier, current_user
from app.constants import ACTIVE_PHASE, TIER_LABELS, AccessTier
from app.core import entitlements as ent
from app.core.access import active_entitlements
from app.db import get_db
from app.models import User

router = APIRouter(prefix="/api/entitlements", tags=["entitlements"])


@router.get("/matrix")
def matrix(tier: AccessTier = Depends(current_tier)) -> dict:
    """The full matrix, including locked rows so the UI can show them locked."""
    allowance = ent.allowance(tier)
    return {
        "currentTier": tier.value,
        "currentTierLabel": TIER_LABELS[tier],
        "activePhase": ACTIVE_PHASE,
        "features": ent.matrix_for(tier, ACTIVE_PHASE),
        "allowance": {
            "runsPerModulePerWeek": allowance.runs_per_module_per_week,
            "perturbationsPerRun": allowance.perturbations_per_run,
            "parameterScope": allowance.parameter_scope,
            "exportFormats": allowance.export_formats,
            "maxUploadBytes": allowance.max_upload_bytes,
        },
    }


@router.get("/grants")
def grants(
    user: User = Depends(current_user), db: Session = Depends(get_db)
) -> list:
    return [
        {
            "id": e.id,
            "tier": e.tier,
            "source": e.source,
            "grantedAt": e.granted_at.isoformat(),
            "expiresAt": e.expires_at.isoformat() if e.expires_at else None,
        }
        for e in active_entitlements(db, user.id)
    ]


@router.get("/upgrade-options")
def upgrade_options(tier: AccessTier = Depends(current_tier)) -> dict:
    """Comparison shown on the Upgrade screen."""
    columns = []
    for candidate in (AccessTier.BASIC, AccessTier.MODERATE, AccessTier.EXPERT):
        allowance = ent.allowance(candidate)
        columns.append(
            {
                "tier": candidate.value,
                "label": TIER_LABELS[candidate],
                "current": candidate is tier,
                "purchasable": candidate.rank > tier.rank,
                "features": [
                    f.label for f in ent.FEATURES.values() if f.min_tier is candidate
                ],
                "runsPerModulePerWeek": allowance.runs_per_module_per_week,
                "perturbationsPerRun": allowance.perturbations_per_run,
                "parameterScope": allowance.parameter_scope,
                "exportFormats": allowance.export_formats,
            }
        )
    return {
        "columns": columns,
        "note": (
            "Paid tiers add depth, repetition, independence and richer outputs. "
            "The teaching content of every week is included at every tier."
        ),
    }
