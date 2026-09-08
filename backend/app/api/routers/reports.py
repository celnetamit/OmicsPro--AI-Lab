"""Report and portfolio export, scoped to the tier that generated it (spec 9.12)."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import current_tier, current_user, require_feature
from app.constants import LOCKED_METHODS, AccessTier, AnalysisTrack
from app.copilot import evidence, knowledge
from app.core import entitlements as ent, parameters as params
from app.db import get_db
from app.models import (
    AiInteraction,
    AuditRecord,
    Dataset,
    DesignPlan,
    Interpretation,
    Perturbation,
    Report,
    Run,
    User,
)

router = APIRouter(prefix="/api/reports", tags=["reports"])


class ReportRequest(BaseModel):
    run_id: str
    export_format: str = "pdf_summary"


def _build(db: Session, run: Run, user: User, export_format: str) -> dict:
    dataset = db.get(Dataset, run.dataset_id)
    track = AnalysisTrack(run.track)
    interpretations = db.scalars(
        select(Interpretation).where(Interpretation.run_id == run.id)
    ).all()
    perturbations = db.scalars(
        select(Perturbation).where(Perturbation.run_id == run.id)
    ).all()
    interactions = db.scalars(
        select(AiInteraction).where(AiInteraction.run_id == run.id)
    ).all()
    audits = {
        a.interaction_id: a
        for a in db.scalars(select(AuditRecord).where(AuditRecord.user_id == user.id)).all()
    }
    plan = db.scalar(select(DesignPlan).where(DesignPlan.user_id == user.id))

    source_ids = sorted({sid for i in interactions for sid in i.evidence_source_ids})
    limitations = list(dataset.limitations or [])
    for entry in knowledge.steps_for(track):
        limitations.extend(entry.caveats)

    summary = {
        "runId": run.id,
        "generatedFor": user.email,
        "designPlan": (
            {
                "briefId": plan.brief_id,
                "biologicalQuestion": plan.biological_question,
                "chosenAssay": plan.chosen_assay,
                "designWarnings": plan.design_warnings,
            }
            if plan
            else None
        ),
        "dataset": {
            "name": dataset.name,
            "source": dataset.source,
            "accession": dataset.accession,
            "license": dataset.license,
            "kind": dataset.kind,
        },
        "methods": {
            "track": track.value,
            "pipelineVersion": run.pipeline_version,
            "methodVersions": run.method_versions,
            "lockedMethods": {
                k: {"method": v["method"], "version": v["version"]}
                for k, v in LOCKED_METHODS.items()
            },
        },
        # Parameters are reported with their registry rule, so a reader can see
        # why each setting exists rather than only what it was.
        "settings": [
            {
                "key": key,
                "value": value,
                "label": params.get(key).label,
                "methodRule": params.get(key).method_rule,
            }
            for key, value in sorted(run.parameters.items())
        ],
        "results": run.outputs,
        # The four fields stay separated in the report, as in the UI (spec 9.10).
        "interpretations": [
            {
                "step": i.step,
                "observation": i.observation,
                "statisticalEvidence": i.statistical_evidence,
                "biologicalInterpretation": i.biological_interpretation,
                "hypothesis": i.hypothesis,
                "label": i.label,
            }
            for i in interpretations
        ],
        "limitations": sorted(set(limitations)),
        "references": evidence.resolve(source_ids),
    }

    if export_format in ("csv", "raw_objects"):
        # Tabular and object exports carry the computed tables themselves, still
        # accompanied by the provenance needed to interpret them.
        summary["tables"] = {
            f"{namespace}.{key}": value
            for namespace, values in (run.outputs or {}).items()
            if isinstance(values, dict)
            for key, value in values.items()
            if isinstance(value, list)
        }
    if export_format in ("figure_pack", "slides"):
        summary["figurePackNote"] = (
            "Figure panels are assembled in the capstone workspace, where each "
            "panel is bound to the run and method version that produced it."
        )

    if export_format != "pdf_summary":
        summary["aiAudit"] = [
            {
                "function": i.function,
                "step": i.step,
                "aiOutput": i.output,
                "evidence": evidence.resolve(i.evidence_source_ids),
                "computedRefs": i.computed_refs,
                "label": i.interpretation_label,
                "labelRationale": i.label_rationale,
                "learnerAction": audits[i.id].action if i.id in audits else "not_reviewed",
                "learnerRationale": audits[i.id].learner_rationale if i.id in audits else "",
                "finalInterpretation": (
                    audits[i.id].final_interpretation if i.id in audits else ""
                ),
            }
            for i in interactions
        ]
        summary["perturbations"] = [
            {
                "parameterKey": p.parameter_key,
                "fromValue": p.from_value.get("value"),
                "toValue": p.to_value.get("value"),
                "decision": p.decision,
                "expected": p.expected_consequence,
                "actual": p.actual_outcome,
                "divergenceExplanation": p.divergence_explanation,
                "alternateRunId": p.alternate_run_id,
            }
            for p in perturbations
        ]
    else:
        summary["aiAuditNote"] = (
            "The full AI audit sheet and perturbation comparison are included in "
            "the Moderate full report export."
        )
    return summary


@router.post("", status_code=201, dependencies=[Depends(require_feature("report_summary"))])
def create_report(
    payload: ReportRequest,
    user: User = Depends(current_user),
    tier: AccessTier = Depends(current_tier),
    db: Session = Depends(get_db),
) -> dict:
    run = db.get(Run, payload.run_id)
    if run is None or run.user_id != user.id:
        raise HTTPException(404, "Run not found.")
    allowed = ent.allowance(tier).export_formats
    if payload.export_format not in allowed:
        raise HTTPException(
            403,
            {
                "error": "export_format_not_available",
                "message": ent.get_feature("report_full").locked_explanation,
                "availableFormats": allowed,
            },
        )
    content = _build(db, run, user, payload.export_format)
    report = Report(
        user_id=user.id,
        run_id=run.id,
        generated_tier=tier,
        export_format=payload.export_format,
        content=content,
    )
    db.add(report)
    db.commit()
    return {"id": report.id, "exportFormat": report.export_format, "content": content}


@router.get("")
def list_reports(user: User = Depends(current_user), db: Session = Depends(get_db)) -> list:
    """Historical reports stay readable after a tier expires (spec 2)."""
    rows = db.scalars(
        select(Report).where(Report.user_id == user.id).order_by(Report.created_at.desc())
    ).all()
    return [
        {
            "id": r.id,
            "runId": r.run_id,
            "exportFormat": r.export_format,
            "generatedTier": r.generated_tier,
            "createdAt": r.created_at.isoformat(),
        }
        for r in rows
    ]


@router.get("/{report_id}")
def get_report(
    report_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> dict:
    report = db.get(Report, report_id)
    if report is None or report.user_id != user.id:
        raise HTTPException(404, "Report not found.")
    return {
        "id": report.id,
        "runId": report.run_id,
        "exportFormat": report.export_format,
        "generatedTier": report.generated_tier,
        "content": report.content,
        "createdAt": report.created_at.isoformat(),
    }
