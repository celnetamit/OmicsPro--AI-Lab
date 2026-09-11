"""Admin / SME console (spec 11).

Entitlements, dataset provenance, module availability and runtime settings are
all editable here without a code deploy. Scientific *methods* are deliberately
not editable at runtime: changing a locked method is a versioned code change so
historical run provenance stays true.
"""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_admin
from app.constants import ACTIVE_PHASE, LOCKED_METHODS, AccessTier, AnalysisTrack, RunStatus
from app.api.routers.issues import serialise as issue_serialise
from app.core import commercial
from app.core import entitlements as ent, parameters as params
from app.copilot import evidence
from app.db import get_db
from app.models import (
    AdminSetting,
    AiInteraction,
    AssessmentResult,
    AuditRecord,
    Capstone,
    Dataset,
    Enrollment,
    Entitlement,
    Interpretation,
    IssueReport,
    ModuleFlag,
    Report,
    Run,
    User,
)

router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_admin)])


# ------------------------------------------------------------- datasets ----
class DatasetRequest(BaseModel):
    slug: str
    name: str
    track: AnalysisTrack
    kind: str = "guided"
    source: str = ""
    accession: str = ""
    citation: str = ""
    license: str = ""
    description: str = ""
    storage_path: str = ""
    file_format: str = ""
    supported_modules: list = Field(default_factory=list)
    limitations: list = Field(default_factory=list)
    enabled: bool = True
    retention_days: Optional[int] = None


@router.get("/datasets")
def list_datasets(db: Session = Depends(get_db)) -> list:
    return [
        {
            "id": d.id,
            "slug": d.slug,
            "name": d.name,
            "track": d.track,
            "kind": d.kind,
            "accession": d.accession,
            "source": d.source,
            "license": d.license,
            "validationStatus": d.validation_status,
            "supportedModules": d.supported_modules,
            "limitations": d.limitations,
            "enabled": d.enabled,
            "retentionDays": d.retention_days,
        }
        for d in db.scalars(select(Dataset)).all()
    ]


@router.post("/datasets", status_code=201)
def create_dataset(payload: DatasetRequest, db: Session = Depends(get_db)) -> dict:
    missing = [f for f in ("source", "accession", "license") if not getattr(payload, f)]
    if missing:
        raise HTTPException(
            422,
            f"Provenance is required before a dataset can be created: "
            f"{', '.join(missing)}.",
        )
    if db.scalar(select(Dataset).where(Dataset.slug == payload.slug)):
        raise HTTPException(409, "A dataset with that slug already exists.")
    dataset = Dataset(**payload.model_dump())
    db.add(dataset)
    db.commit()
    return {"id": dataset.id, "slug": dataset.slug}


@router.patch("/datasets/{dataset_id}")
def update_dataset(dataset_id: str, payload: dict, db: Session = Depends(get_db)) -> dict:
    dataset = db.get(Dataset, dataset_id)
    if dataset is None:
        raise HTTPException(404, "Dataset not found.")
    for key, value in payload.items():
        if hasattr(dataset, key) and key not in ("id", "imported_at"):
            setattr(dataset, key, value)
    db.commit()
    return {"id": dataset.id, "updated": sorted(payload)}


# --------------------------------------------------------- entitlements ----
class GrantRequest(BaseModel):
    user_id: str
    tier: AccessTier
    expires_at: Optional[datetime] = None
    note: str = ""


@router.post("/entitlements/grant", status_code=201)
def grant(
    payload: GrantRequest, admin: User = Depends(require_admin), db: Session = Depends(get_db)
) -> dict:
    if db.get(User, payload.user_id) is None:
        raise HTTPException(404, "User not found.")
    entitlement = Entitlement(
        user_id=payload.user_id,
        tier=payload.tier,
        source="admin_grant",
        expires_at=payload.expires_at,
        granted_by=admin.id,
        note=payload.note,
    )
    db.add(entitlement)
    db.commit()
    return {"id": entitlement.id, "tier": entitlement.tier}


@router.post("/entitlements/{entitlement_id}/revoke")
def revoke(
    entitlement_id: str, admin: User = Depends(require_admin), db: Session = Depends(get_db)
) -> dict:
    entitlement = db.get(Entitlement, entitlement_id)
    if entitlement is None:
        raise HTTPException(404, "Entitlement not found.")
    entitlement.revoked_at = datetime.utcnow()
    entitlement.granted_by = admin.id
    db.commit()
    # Revocation changes access only. Reports generated earlier stay readable.
    retained = len(
        db.scalars(select(Report).where(Report.user_id == entitlement.user_id)).all()
    )
    return {"id": entitlement.id, "revoked": True, "reportsRetained": retained}


class ExtendRequest(BaseModel):
    expires_at: Optional[datetime] = None


@router.post("/entitlements/{entitlement_id}/extend")
def extend(
    entitlement_id: str, payload: ExtendRequest, db: Session = Depends(get_db)
) -> dict:
    entitlement = db.get(Entitlement, entitlement_id)
    if entitlement is None:
        raise HTTPException(404, "Entitlement not found.")
    entitlement.expires_at = payload.expires_at
    db.commit()
    return {
        "id": entitlement.id,
        "expiresAt": entitlement.expires_at.isoformat() if entitlement.expires_at else None,
    }


class ActivatePurchaseRequest(BaseModel):
    provider_reference: str


@router.get("/purchases")
def list_purchases(db: Session = Depends(get_db)) -> list:
    from app.api.routers.billing import _serialise
    from app.models import Purchase

    return [
        {**_serialise(p), "userId": p.user_id}
        for p in db.scalars(select(Purchase).order_by(Purchase.created_at.desc())).all()
    ]


@router.post("/purchases/{purchase_id}/activate")
def activate_purchase(
    purchase_id: str, payload: ActivatePurchaseRequest, db: Session = Depends(get_db)
) -> dict:
    """Activate a paid order once payment is confirmed out of band."""
    from app.api.routers.billing import activate_purchase as activate
    from app.models import Purchase

    purchase = db.get(Purchase, purchase_id)
    if purchase is None:
        raise HTTPException(404, "Purchase not found.")
    entitlement = activate(db, purchase, payload.provider_reference)
    return {
        "purchaseId": purchase.id,
        "entitlementId": entitlement.id,
        "tier": entitlement.tier,
        "expiresAt": entitlement.expires_at.isoformat() if entitlement.expires_at else None,
    }


# ------------------------------------------------------------- modules -----
class ModuleFlagRequest(BaseModel):
    module_key: str
    cohort: str = ""
    enabled: bool = True
    note: str = ""


@router.get("/modules")
def list_modules(db: Session = Depends(get_db)) -> list:
    return [
        {"moduleKey": f.module_key, "cohort": f.cohort, "enabled": f.enabled, "note": f.note}
        for f in db.scalars(select(ModuleFlag)).all()
    ]


@router.put("/modules")
def set_module(payload: ModuleFlagRequest, db: Session = Depends(get_db)) -> dict:
    flag = db.scalar(
        select(ModuleFlag).where(
            ModuleFlag.module_key == payload.module_key, ModuleFlag.cohort == payload.cohort
        )
    ) or ModuleFlag(module_key=payload.module_key, cohort=payload.cohort)
    flag.enabled = payload.enabled
    flag.note = payload.note
    db.add(flag)
    db.commit()
    return {"moduleKey": flag.module_key, "cohort": flag.cohort, "enabled": flag.enabled}


# ------------------------------------------------------------ settings -----
class SettingRequest(BaseModel):
    key: str
    value: dict


@router.get("/settings")
def list_settings(db: Session = Depends(get_db)) -> list:
    return [
        {"key": s.key, "value": s.value, "updatedAt": s.updated_at.isoformat()}
        for s in db.scalars(select(AdminSetting)).all()
    ]


@router.put("/settings")
def set_setting(
    payload: SettingRequest, admin: User = Depends(require_admin), db: Session = Depends(get_db)
) -> dict:
    #: Commercial values have rules the generic setter cannot check — Basic is
    #: never sold, and a paid tier may not allow less than the one below it — so
    #: they go through their own validated endpoints below.
    if payload.key.startswith("commercial."):
        raise HTTPException(
            422,
            "Commercial terms are changed through /api/admin/commercial, which "
            "checks them before they apply.",
        )
    setting = db.get(AdminSetting, payload.key) or AdminSetting(key=payload.key)
    setting.value = payload.value
    setting.updated_by = admin.id
    db.add(setting)
    db.commit()
    return {"key": setting.key, "value": setting.value}


# ------------------------------------------------ scientific configuration --
@router.get("/parameters")
def parameter_registry() -> dict:
    """Read-only view of the registry, with the tier scope each range applies to."""
    return {
        "scopes": list(params.SCOPES),
        "parameters": [
            {
                "key": p.key,
                "label": p.label,
                "tracks": p.track_values,
                "step": p.step,
                "kind": p.kind,
                "default": p.default,
                "methodRule": p.method_rule,
                "validationMessage": p.validation_message,
                "caveat": p.caveat,
                "ranges": {k: list(v) for k, v in (p.ranges or {}).items()},
                "choices": {k: (list(v) if v else None) for k, v in (p.choices or {}).items()},
            }
            for p in params.REGISTRY.values()
        ],
    }


@router.get("/method-lock")
def method_lock() -> dict:
    """The frozen method choices and their SME sign-off state (spec 13)."""
    return {
        "activePhase": ACTIVE_PHASE,
        "methods": LOCKED_METHODS,
        "unsignedOff": [
            key for key, value in LOCKED_METHODS.items() if not value.get("sme_signoff")
        ],
        "note": (
            "Method changes are a versioned code change, not a runtime setting, so "
            "the version recorded against every historical run stays true."
        ),
    }


@router.get("/evidence-sources")
def evidence_sources() -> list:
    return evidence.resolve(list(evidence.REGISTRY))


# ----------------------------------------------------------- operations ----
@router.get("/runs/failures")
def failures(db: Session = Depends(get_db)) -> list:
    rows = db.scalars(
        select(Run).where(Run.status == RunStatus.FAILED).order_by(Run.created_at.desc()).limit(100)
    ).all()
    return [
        {
            "id": r.id,
            "userId": r.user_id,
            "track": r.track,
            "datasetId": r.dataset_id,
            "lastValidStep": r.last_valid_step,
            "errorMessage": r.error_message,
            "errorDetail": r.error_detail,
            "createdAt": r.created_at.isoformat(),
        }
        for r in rows
    ]


@router.get("/usage")
def usage(db: Session = Depends(get_db)) -> dict:
    runs = db.scalars(select(Run)).all()
    by_status, by_track, by_tier = {}, {}, {}
    for run in runs:
        by_status[run.status] = by_status.get(run.status, 0) + 1
        by_track[run.track] = by_track.get(run.track, 0) + 1
        by_tier[run.access_tier] = by_tier.get(run.access_tier, 0) + 1
    reports = db.scalars(select(Report)).all()
    exports: dict = {}
    for report in reports:
        exports[report.export_format] = exports.get(report.export_format, 0) + 1

    #: Dataset load (spec 14): how heavily each dataset is being run, so an
    #: operator can see which ones need caching or are going unused.
    load: dict = {}
    for run in runs:
        entry = load.setdefault(run.dataset_id, {"runs": 0, "lastRunAt": None})
        entry["runs"] += 1
        stamp = run.created_at.isoformat()
        if entry["lastRunAt"] is None or stamp > entry["lastRunAt"]:
            entry["lastRunAt"] = stamp
    dataset_load = []
    for dataset in db.scalars(select(Dataset)).all():
        entry = load.get(dataset.id, {"runs": 0, "lastRunAt": None})
        dataset_load.append(
            {
                "slug": dataset.slug,
                "name": dataset.name,
                "validationStatus": dataset.validation_status,
                "runs": entry["runs"],
                "lastRunAt": entry["lastRunAt"],
            }
        )
    dataset_load.sort(key=lambda row: row["runs"], reverse=True)

    return {
        "totalRuns": len(runs),
        "byStatus": by_status,
        "byTrack": by_track,
        "byAccessTier": by_tier,
        "totalReports": len(reports),
        "exportsByFormat": exports,
        "totalDatasets": len(dataset_load),
        "datasetLoad": dataset_load,
    }


@router.get("/completion")
def completion(db: Session = Depends(get_db)) -> list:
    """Learner completion status (spec 14), one row per enrolled learner.

    Built from the records the learner actually produced rather than a progress
    flag that could drift from them.
    """
    rows = []
    for enrollment in db.scalars(
        select(Enrollment).where(Enrollment.active.is_(True))
    ).all():
        user = db.get(User, enrollment.user_id)
        if user is None:
            continue
        runs = db.scalars(select(Run).where(Run.user_id == user.id)).all()
        completed = [r for r in runs if r.status == RunStatus.COMPLETED]
        weeks_run = sorted({r.week for r in completed if r.week})
        assessments = db.scalars(
            select(AssessmentResult).where(AssessmentResult.user_id == user.id)
        ).all()
        capstone = db.scalar(select(Capstone).where(Capstone.user_id == user.id))
        rows.append(
            {
                "userId": user.id,
                "email": user.email,
                "cohort": enrollment.cohort,
                "currentWeek": enrollment.current_week,
                "runsCompleted": len(completed),
                "weeksWithACompletedRun": weeks_run,
                "interpretations": len(
                    db.scalars(select(Interpretation).where(Interpretation.user_id == user.id)).all()
                ),
                "preLabTaken": any(a.assessment_id == "pre-lab" for a in assessments),
                "weekAssessments": sorted(
                    int(a.assessment_id.split("-", 1)[1])
                    for a in assessments
                    if a.assessment_id.startswith("week-")
                ),
                "capstoneSubmitted": bool(capstone and capstone.submitted_at),
                "defenceScore": capstone.defence_score if capstone else None,
            }
        )
    rows.sort(key=lambda row: (row["cohort"], row["email"]))
    return rows


@router.get("/ai-audit")
def ai_audit(db: Session = Depends(get_db)) -> list:
    audits = db.scalars(select(AuditRecord).order_by(AuditRecord.created_at.desc()).limit(200)).all()
    return [
        {
            "id": a.id,
            "userId": a.user_id,
            "action": a.action,
            "revisedLabel": a.revised_label,
            "learnerRationale": a.learner_rationale,
            "interaction": _interaction_summary(db.get(AiInteraction, a.interaction_id)),
            "createdAt": a.created_at.isoformat(),
        }
        for a in audits
    ]


def _interaction_summary(interaction: Optional[AiInteraction]) -> Optional[dict]:
    if interaction is None:
        return None
    return {
        "id": interaction.id,
        "function": interaction.function,
        "step": interaction.step,
        "label": interaction.interpretation_label,
        "evidenceSourceIds": interaction.evidence_source_ids,
        "computedRefs": interaction.computed_refs,
    }



# ------------------------------------------------------ commercial terms --
class CommercialRequest(BaseModel):
    value: dict


@router.get("/commercial")
def commercial_terms(db: Session = Depends(get_db)) -> dict:
    """The commercial values in force, with the defaults they override (spec 12)."""
    return {
        "catalogue": {tier.value: terms for tier, terms in commercial.catalogue(db).items()},
        "allowance": {
            tier.value: {
                "runs_per_module_per_week": commercial.allowance_for(db, tier).runs_per_module_per_week,
                "perturbations_per_run": commercial.allowance_for(db, tier).perturbations_per_run,
            }
            for tier in AccessTier
        },
        "defaults": {
            "catalogue": commercial.DEFAULT_CATALOGUE,
            "allowance": {
                tier.value: {
                    "runs_per_module_per_week": ent.allowance(tier).runs_per_module_per_week,
                    "perturbations_per_run": ent.allowance(tier).perturbations_per_run,
                }
                for tier in AccessTier
            },
        },
        "note": (
            "Prices are in minor currency units (499000 = INR 4,990.00). A price "
            "or term change applies to new orders only; entitlements already "
            "granted keep the term they were bought on."
        ),
    }


def _store(db: Session, key: str, value: dict, admin: User) -> None:
    setting = db.get(AdminSetting, key) or AdminSetting(key=key)
    setting.value = value
    setting.updated_by = admin.id
    db.add(setting)
    db.commit()


@router.put("/commercial/catalogue")
def set_catalogue(
    payload: CommercialRequest, admin: User = Depends(require_admin), db: Session = Depends(get_db)
) -> dict:
    try:
        clean = commercial.validate_catalogue(payload.value)
    except commercial.CommercialConfigError as exc:
        raise HTTPException(422, str(exc))
    _store(db, commercial.CATALOGUE_KEY, clean, admin)
    return commercial_terms(db)


@router.put("/commercial/allowance")
def set_allowance(
    payload: CommercialRequest, admin: User = Depends(require_admin), db: Session = Depends(get_db)
) -> dict:
    try:
        clean = commercial.validate_allowance(payload.value)
    except commercial.CommercialConfigError as exc:
        raise HTTPException(422, str(exc))
    _store(db, commercial.ALLOWANCE_KEY, clean, admin)
    return commercial_terms(db)


# ------------------------------------------------ progressive week unlock --
class WeekRequest(BaseModel):
    week: int = Field(ge=1, le=8)
    cohort: str = ""


@router.get("/cohorts")
def cohorts(db: Session = Depends(get_db)) -> list:
    """Each cohort, its learners and the week it is on (spec 17)."""
    grouped: dict = {}
    for enrollment in db.scalars(select(Enrollment).where(Enrollment.active.is_(True))).all():
        entry = grouped.setdefault(enrollment.cohort, {"learners": 0, "weeks": {}})
        entry["learners"] += 1
        entry["weeks"][enrollment.current_week] = entry["weeks"].get(enrollment.current_week, 0) + 1
    return [
        {
            "cohort": cohort,
            "learners": entry["learners"],
            #: Usually one week per cohort; more than one means a learner was
            #: moved individually, which the console should make visible.
            "currentWeeks": dict(sorted(entry["weeks"].items())),
        }
        for cohort, entry in sorted(grouped.items())
    ]


@router.post("/cohorts/week")
def set_cohort_week(payload: WeekRequest, db: Session = Depends(get_db)) -> dict:
    """Open a cohort's next week of the flagship pathway (spec 4, 17).

    The eight weeks unlock progressively; this is how a cohort moves forward.
    Moving back is allowed and never deletes work — it only changes which
    week's modules are presented as current.
    """
    enrollments = db.scalars(
        select(Enrollment).where(
            Enrollment.active.is_(True), Enrollment.cohort == payload.cohort
        )
    ).all()
    if not enrollments:
        raise HTTPException(404, f"No active learners in cohort '{payload.cohort}'.")
    for enrollment in enrollments:
        enrollment.current_week = payload.week
    db.commit()
    return {"cohort": payload.cohort, "week": payload.week, "learnersMoved": len(enrollments)}


@router.post("/learners/{user_id}/week")
def set_learner_week(user_id: str, payload: WeekRequest, db: Session = Depends(get_db)) -> dict:
    """Move one learner, for a late joiner or a deferral."""
    enrollment = db.scalar(
        select(Enrollment).where(Enrollment.user_id == user_id, Enrollment.active.is_(True))
    )
    if enrollment is None:
        raise HTTPException(404, "That learner has no active enrollment.")
    enrollment.current_week = payload.week
    db.commit()
    return {"userId": user_id, "week": payload.week}


# -------------------------------------------------- learner-reported issues --
class IssueUpdate(BaseModel):
    status: str
    admin_note: str = ""


@router.get("/issues")
def list_issues(status: Optional[str] = None, db: Session = Depends(get_db)) -> list:
    query = select(IssueReport).order_by(IssueReport.created_at.desc())
    if status:
        query = query.where(IssueReport.status == status)
    rows = []
    for issue in db.scalars(query).all():
        user = db.get(User, issue.user_id)
        rows.append({**issue_serialise(issue), "email": user.email if user else None})
    return rows


@router.patch("/issues/{issue_id}")
def update_issue(
    issue_id: str,
    payload: IssueUpdate,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    if payload.status not in ("open", "acknowledged", "resolved"):
        raise HTTPException(422, "Status must be open, acknowledged or resolved.")
    issue = db.get(IssueReport, issue_id)
    if issue is None:
        raise HTTPException(404, "Issue not found.")
    issue.status = payload.status
    issue.admin_note = payload.admin_note
    if payload.status == "resolved":
        issue.resolved_by = admin.id
        issue.resolved_at = datetime.utcnow()
    else:
        issue.resolved_by = None
        issue.resolved_at = None
    db.commit()
    return issue_serialise(issue)
