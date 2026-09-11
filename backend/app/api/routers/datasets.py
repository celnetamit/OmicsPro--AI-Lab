"""Dataset Selector and Dataset Inspector (spec 9.5, 9.6)."""

import os
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import current_tier, current_user, require_feature
from app.constants import ACTIVE_PHASE, AccessTier, AnalysisTrack
from app.copilot import dataset_brief
from app.core import entitlements as ent
from app.db import get_db
from app.governance import ingest
from app.governance.loader import DatasetUnavailable, load
from app.governance.validation import validate_metadata, validate_upload
from app.models import AdminSetting, Dataset, User
from app.pipelines import registry
from app.settings import settings

router = APIRouter(prefix="/api/datasets", tags=["datasets"])

#: Which entitlement feature each dataset kind sits behind.
KIND_FEATURE = {"guided": "guided_dataset", "trial": "trial_dataset", "upload": "dataset_upload"}


def visible_to(dataset: Dataset, user: User) -> bool:
    """An upload is private to the learner who uploaded it (spec 6).

    The upload response promises the data is never shared with other users;
    this is where that promise is kept for listing, inspection and runs.
    """
    return dataset.kind != "upload" or dataset.owner_id == user.id


def _serialise(dataset: Dataset, tier: AccessTier) -> dict:
    feature_key = KIND_FEATURE[dataset.kind]
    feature = ent.get_feature(feature_key)
    unlocked = tier.satisfies(feature.min_tier)
    return {
        "id": dataset.id,
        "slug": dataset.slug,
        "name": dataset.name,
        "track": dataset.track,
        "kind": dataset.kind,
        "description": dataset.description,
        # Provenance is always visible, including on locked datasets (spec 9.5).
        "provenance": {
            "source": dataset.source,
            "accession": dataset.accession,
            "citation": dataset.citation,
            "license": dataset.license,
            "importedAt": dataset.imported_at.isoformat(),
            "validationStatus": dataset.validation_status,
        },
        "supportedModules": dataset.supported_modules,
        "limitations": dataset.limitations,
        "selectable": unlocked and dataset.enabled and dataset.validation_status == "validated",
        "unlocked": unlocked,
        "lockedExplanation": "" if unlocked else feature.locked_explanation,
        "requiredTier": feature.min_tier.value,
    }


@router.get("")
def list_datasets(
    track: str = None,
    user: User = Depends(current_user),
    tier: AccessTier = Depends(current_tier),
    db: Session = Depends(get_db),
) -> list:
    query = select(Dataset).where(Dataset.enabled.is_(True))
    if track:
        query = query.where(Dataset.track == track)
    available = {t.value for t in registry.available_tracks()}
    rows = [
        d for d in db.scalars(query).all() if d.track in available and visible_to(d, user)
    ]
    return [_serialise(d, tier) for d in rows]


def _inspectable(dataset_id: str, user: User, tier: AccessTier, db: Session) -> Dataset:
    dataset = db.get(Dataset, dataset_id)
    #: Someone else's upload is reported as absent, not as forbidden, so its
    #: existence is not disclosed either.
    if dataset is None or not dataset.enabled or not visible_to(dataset, user):
        raise HTTPException(404, "Dataset not found.")
    # Server-side gate: inspection of a locked dataset is refused here, not
    # merely hidden in the client.
    ent_feature = KIND_FEATURE[dataset.kind]
    try:
        ent.assert_feature(tier, ent_feature)
    except ent.EntitlementError as exc:
        raise HTTPException(403, {"message": str(exc), "feature": ent_feature})
    return dataset


@router.get("/{dataset_id}")
def inspect(
    dataset_id: str,
    user: User = Depends(current_user),
    tier: AccessTier = Depends(current_tier),
    db: Session = Depends(get_db),
) -> dict:
    dataset = _inspectable(dataset_id, user, tier, db)
    payload = _serialise(dataset, tier)

    try:
        data = load(dataset)
    except DatasetUnavailable as exc:
        payload["inspection"] = None
        payload["unavailableReason"] = exc.message
        return payload

    obs = data.obs
    fields = sorted({key for row in obs for key in row})
    payload["inspection"] = {
        "shape": list(data.matrix.shape),
        "nFeatures": len(data.var),
        "metadataFields": fields,
        "groups": {
            field: _counts(obs, field)
            for field in fields
            if field in ("condition", "batch", "donor", "sample_id")
        },
        "missingness": {
            field: sum(1 for row in obs if row.get(field) in (None, "")) for field in fields
        },
        "preview": obs[:10],
    }
    return payload


def _counts(rows, field) -> dict:
    out = {}
    for row in rows:
        value = str(row.get(field, ""))
        out[value] = out.get(value, 0) + 1
    return out


@router.get("/{dataset_id}/brief")
def brief(
    dataset_id: str,
    user: User = Depends(current_user),
    tier: AccessTier = Depends(current_tier),
    db: Session = Depends(get_db),
) -> dict:
    """The Copilot's grounded explanation of a dataset, before any run (spec 9.6)."""
    dataset = _inspectable(dataset_id, user, tier, db)
    try:
        data = load(dataset)
    except DatasetUnavailable as exc:
        return {"available": False, "reason": exc.message}
    return dataset_brief.compose(db, user.id, dataset, data)


# ------------------------------------------------------- Expert upload ----
def _admin_setting(db: Session, key: str, default: dict) -> dict:
    setting = db.get(AdminSetting, key)
    return setting.value if setting and isinstance(setting.value, dict) else default


def _max_upload_bytes(db: Session, tier: AccessTier) -> int:
    """Admin-editable cap, falling back to the tier allowance (spec 6)."""
    configured = _admin_setting(db, "upload.max_bytes", {})
    value = configured.get(tier.value)
    return int(value) if value else ent.allowance(tier).max_upload_bytes


@router.post(
    "/upload",
    status_code=201,
    dependencies=[Depends(require_feature("dataset_upload"))],
)
async def upload(
    track: AnalysisTrack = Form(...),
    name: str = Form(...),
    source: str = Form(...),
    accession: str = Form(...),
    license: str = Form(...),
    citation: str = Form(""),
    description: str = Form(""),
    matrix: UploadFile = File(...),
    metadata: Optional[UploadFile] = File(None),
    features: Optional[UploadFile] = File(None),
    barcodes: Optional[UploadFile] = File(None),
    positions: Optional[UploadFile] = File(None),
    user: User = Depends(current_user),
    tier: AccessTier = Depends(current_tier),
    db: Session = Depends(get_db),
) -> dict:
    """Ingest an analysis-ready dataset (spec 6, Phase 3).

    Nothing is stored and no pipeline can reach the data until every governance
    gate passes: format, size, structure, identifiers, required metadata,
    provenance, and the block on identifiable personal information. Files are
    read by the same readers the operator uses for the guided datasets, so a
    format means the same thing on both routes.
    """
    matrix_source = ingest.Source(matrix.filename or "matrix", data=await matrix.read())
    companions = {}
    for key, part in (
        ("metadata", metadata), ("features", features),
        ("barcodes", barcodes), ("positions", positions),
    ):
        if part is not None and part.filename:
            companions[key] = ingest.Source(part.filename, data=await part.read())

    # Format, size and provenance are judged before anything is parsed.
    gate = validate_upload(
        filename=matrix_source.name,
        size_bytes=matrix_source.size + sum(s.size for s in companions.values()),
        track=track,
        max_bytes=_max_upload_bytes(db, tier),
        provenance={"source": source, "accession": accession, "license": license},
    )
    if not gate.ok:
        raise HTTPException(422, {"error": "validation_failed", **gate.as_dict()})

    try:
        ingested = ingest.ingest(
            track,
            matrix_source,
            companions.get("metadata"),
            features=companions.get("features"),
            barcodes=companions.get("barcodes"),
            positions=companions.get("positions"),
        )
    except ingest.IngestError as exc:
        raise HTTPException(
            422,
            {
                "error": exc.code,
                "message": exc.message,
                "ok": False,
                "errors": [{"code": exc.code, "message": exc.message}],
                "warnings": [],
                "summary": {},
            },
        )

    result = validate_metadata(track, ingested.obs, n_observations=len(ingested.obs))
    result.warnings = [*gate.warnings, *ingested.warnings, *result.warnings]
    result.summary["ingestion"] = ingested.notes
    if not result.ok:
        # Nothing is written when validation fails, so a rejected upload leaves
        # no trace on disk to clean up.
        raise HTTPException(422, {"error": "validation_failed", **result.as_dict()})

    retention = _admin_setting(db, "retention.uploaded_dataset_days", {"days": 180})
    dataset = Dataset(
        slug=f"upload-{uuid.uuid4().hex[:12]}",
        name=name,
        track=track,
        kind="upload",
        source=source,
        accession=accession,
        citation=citation,
        license=license,
        description=description,
        storage_path=f"uploads/{user.id}/{uuid.uuid4().hex}",
        file_format=matrix_source.extension.lstrip("."),
        owner_id=user.id,
        validation_status="validated",
        validation_report=result.as_dict(),
        supported_modules=[f"{track.value}_guided"],
        limitations=[
            "Uploaded by you. Its provenance and suitability are your "
            "responsibility, and the platform has not reviewed it.",
        ],
        retention_days=retention.get("days"),
    )

    # Stored as a validated internal object, never as the raw upload, so no
    # pipeline ever reads the user's file directly (spec 10).
    ingested.write(os.path.join(settings.data_dir, dataset.storage_path))

    db.add(dataset)
    db.commit()
    return {
        **_serialise(dataset, tier),
        "validation": result.as_dict(),
        "governance": {
            "retentionDays": dataset.retention_days,
            "usedForTraining": False,
            "sharedWithOtherUsers": False,
            "note": (
                "Your data is never used to train models and is never shared "
                "with other users. It is stored for the retention period above."
            ),
        },
    }


@router.delete("/{dataset_id}")
def delete_upload(
    dataset_id: str,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Delete a dataset you uploaded, and the stored object with it."""
    dataset = db.get(Dataset, dataset_id)
    if dataset is None or dataset.kind != "upload" or dataset.owner_id != user.id:
        raise HTTPException(404, "Uploaded dataset not found.")

    base = os.path.join(settings.data_dir, dataset.storage_path)
    for suffix in (".npz", ".meta.json"):
        path = f"{base}{suffix}"
        if os.path.exists(path):
            os.remove(path)
    db.delete(dataset)
    db.commit()
    # Runs keep their dataset id so their provenance record stays complete, and
    # report content already generated is untouched.
    return {"deleted": dataset_id, "note": "Prior runs and reports are retained."}
