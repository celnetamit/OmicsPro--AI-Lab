"""Analysis Workspace: run execution, perturbation, interpretation (spec 9.7-9.10)."""

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import current_tier, current_user, require_feature
from app.constants import AccessTier, AnalysisTrack, InterpretationLabel, RunStatus
from app.copilot import perturbation as pert, service as copilot
from app.core import entitlements as ent, parameters as params
from app.db import get_db
from app.governance.loader import DatasetUnavailable, load
from app.models import Dataset, Interpretation, Perturbation, Run, User
from app.core import commercial, figures, jobs
from app.pipelines import registry, runner

router = APIRouter(prefix="/api/runs", tags=["runs"])


class CreateRunRequest(BaseModel):
    dataset_id: str
    track: AnalysisTrack
    #: An extension module such as "core_communication". Empty runs the track's
    #: guided workflow.
    module: Optional[str] = None
    week: Optional[int] = None
    parameters: Dict[str, Any] = Field(default_factory=dict)


def _quota_used(db: Session, user_id: str, track: AnalysisTrack) -> int:
    since = datetime.utcnow() - timedelta(days=7)
    return len(
        db.scalars(
            select(Run).where(
                Run.user_id == user_id, Run.track == track, Run.created_at >= since
            )
        ).all()
    )


def _enforce_quota(db: Session, user_id: str, track: AnalysisTrack, tier: AccessTier) -> None:
    limit = commercial.allowance_for(db, tier).runs_per_module_per_week
    if limit is None:
        return
    if _quota_used(db, user_id, track) >= limit:
        raise HTTPException(
            429,
            {
                "error": "run_allowance_exhausted",
                "message": (
                    f"Your tier includes {limit} runs per module per week. Moderate "
                    f"adds independent reruns with a wider allowance."
                ),
                "currentTier": tier.value,
            },
        )


def _serialise(run: Run) -> dict:
    return {
        "id": run.id,
        "datasetId": run.dataset_id,
        "track": run.track,
        "module": run.module,
        "week": run.week,
        "accessTier": run.access_tier,
        "status": run.status,
        "pipelineVersion": run.pipeline_version,
        "methodVersions": run.method_versions,
        "parameters": run.parameters,
        "outputs": run.outputs,
        "lastValidStep": run.last_valid_step,
        "nextStep": runner.next_step(run) if run.status != RunStatus.FAILED else None,
        "errorMessage": run.error_message,
        "isOriginal": run.is_original,
        "parentRunId": run.parent_run_id,
        "startedAt": run.started_at.isoformat() if run.started_at else None,
        "finishedAt": run.finished_at.isoformat() if run.finished_at else None,
    }


@router.get("/parameters/{track}")
def parameter_panel(
    track: AnalysisTrack, tier: AccessTier = Depends(current_tier)
) -> dict:
    """Registry view for the parameter panel, already constrained to the tier."""
    scope = params.scope_for(tier)
    wider = [s for s in params.SCOPES if params.SCOPES.index(s) > params.SCOPES.index(scope)]
    return {
        "track": track.value,
        "scope": scope,
        "parameters": params.describe_for(track, tier),
        "widerScopesAvailable": wider,
        "upgradeNote": (
            ent.get_feature("parameters_full").locked_explanation if wider else ""
        ),
    }


@router.post("", status_code=201, dependencies=[Depends(require_feature("run_guided_pipeline"))])
def create_run(
    payload: CreateRunRequest,
    user: User = Depends(current_user),
    tier: AccessTier = Depends(current_tier),
    db: Session = Depends(get_db),
) -> dict:
    from app.api.routers.datasets import KIND_FEATURE, visible_to

    dataset = db.get(Dataset, payload.dataset_id)
    #: Someone else's upload is reported as absent, never analysed (spec 6).
    if dataset is None or not dataset.enabled or not visible_to(dataset, user):
        raise HTTPException(404, "Dataset not found.")
    if dataset.track != payload.track.value:
        raise HTTPException(422, "That dataset does not belong to the selected analysis track.")

    try:
        ent.assert_feature(tier, KIND_FEATURE[dataset.kind])
    except ent.EntitlementError as exc:
        raise HTTPException(403, {"message": str(exc)})

    module_entry = None
    if payload.module:
        try:
            module_entry = registry.get_module(payload.module)
        except KeyError as exc:
            raise HTTPException(404, str(exc))
        if module_entry["track"] is not payload.track:
            raise HTTPException(
                422,
                f"'{module_entry['label']}' runs on the "
                f"{module_entry['track'].value} track.",
            )
        try:
            ent.assert_feature(tier, module_entry["feature"])
        except ent.EntitlementError:
            feature = ent.get_feature(module_entry["feature"])
            raise HTTPException(
                403,
                {
                    "error": "entitlement_required",
                    "feature": feature.key,
                    "requiredTier": feature.min_tier.value,
                    "message": feature.locked_explanation,
                    "currentTier": tier.value,
                },
            )

    # A rerun with learner-chosen parameters is a Moderate feature; the guided
    # run at registry defaults is Basic.
    if payload.parameters:
        try:
            ent.assert_feature(tier, "independent_rerun")
        except ent.EntitlementError as exc:
            raise HTTPException(
                403,
                {
                    "error": "entitlement_required",
                    "feature": "independent_rerun",
                    "message": ent.get_feature("independent_rerun").locked_explanation,
                    "currentTier": tier.value,
                },
            )

    _enforce_quota(db, user.id, payload.track, tier)

    try:
        resolved = params.validate_many(payload.parameters, payload.track, tier)
    except params.ParameterError as exc:
        raise HTTPException(422, {"error": "invalid_parameters", "fields": exc.args[0]})

    run = Run(
        user_id=user.id,
        dataset_id=dataset.id,
        track=payload.track,
        module=payload.module or "",
        week=payload.week,
        access_tier=tier,
        pipeline_version=registry.get(payload.track, payload.module or None).version,
        parameters=resolved,
        status=RunStatus.QUEUED,
    )
    db.add(run)
    db.commit()

    try:
        data = load(dataset)
        _attach_spatial_context(db, data, dataset, resolved, tier, user)
    except DatasetUnavailable as exc:
        run.status = RunStatus.FAILED
        run.error_message = exc.message
        db.commit()
        return _serialise(run)
    except HTTPException:
        db.delete(run)
        db.commit()
        raise

    #: The pipeline runs on the worker pool; the learner gets the run id now
    #: and the workspace polls it. Inline mode completes it before returning.
    jobs.submit(db, run, data)
    return _serialise(run)


def _attach_spatial_context(db, data, dataset, parameters, tier, user) -> None:
    """Resolve the optional single-cell reference for a spatial run.

    Reference selection is Expert-only, and an unresolvable or inaccessible
    reference is refused here rather than producing an estimate from nothing.
    """
    if dataset.track != AnalysisTrack.ADVANCED.value:
        return
    data.meta["spatial_dataset"] = dataset
    reference_id = parameters.get("spatial.mapping.reference_dataset") or ""
    if not reference_id:
        return
    try:
        ent.assert_feature(tier, "spatial_reference_mapping")
    except ent.EntitlementError:
        feature = ent.get_feature("spatial_reference_mapping")
        raise HTTPException(
            403,
            {
                "error": "entitlement_required",
                "feature": feature.key,
                "requiredTier": feature.min_tier.value,
                "message": feature.locked_explanation,
                "currentTier": tier.value,
            },
        )
    from app.api.routers.datasets import visible_to

    reference = db.get(Dataset, reference_id)
    #: A reference is a dataset like any other: another learner's upload is absent.
    if reference is None or not reference.enabled or not visible_to(reference, user):
        raise HTTPException(404, "The reference dataset named for mapping was not found.")
    data.meta["reference_dataset"] = reference


@router.get("")
def list_runs(user: User = Depends(current_user), db: Session = Depends(get_db)) -> list:
    runs = db.scalars(
        select(Run).where(Run.user_id == user.id).order_by(Run.created_at.desc())
    ).all()
    return [_serialise(r) for r in runs]


def _owned_run(run_id: str, user: User, db: Session) -> Run:
    run = db.get(Run, run_id)
    if run is None or run.user_id != user.id:
        raise HTTPException(404, "Run not found.")
    return run


@router.get("/{run_id}")
def get_run(
    run_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> dict:
    return _serialise(_owned_run(run_id, user, db))


@router.post("/{run_id}/cancel")
def cancel_run(
    run_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> dict:
    return _serialise(runner.cancel(db, _owned_run(run_id, user, db)))


# ------------------------------------------------------------ perturbation --
@router.get(
    "/{run_id}/perturbations",
    dependencies=[Depends(require_feature("perturbation_guided"))],
)
def offers(
    run_id: str,
    step: str,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    run = _owned_run(run_id, user, db)
    allowance = commercial.allowance_for(db, AccessTier(run.access_tier)).perturbations_per_run
    used = len(
        db.scalars(select(Perturbation).where(Perturbation.run_id == run.id)).all()
    )
    return {
        "offers": copilot.suggest_perturbation(db, user.id, run, step) if used < allowance else [],
        "used": used,
        "allowance": allowance,
        "exhausted": used >= allowance,
        "upgradeNote": (
            ent.get_feature("perturbation_extended").locked_explanation
            if used >= allowance
            else ""
        ),
    }


class PerturbationDecision(BaseModel):
    offer_key: str
    #: Binary by design: there is no silent-override path (spec 8.1).
    decision: str  # "test" | "skip"


@router.post(
    "/{run_id}/perturbations",
    dependencies=[Depends(require_feature("perturbation_guided"))],
)
def decide(
    run_id: str,
    payload: PerturbationDecision,
    user: User = Depends(current_user),
    tier: AccessTier = Depends(current_tier),
    db: Session = Depends(get_db),
) -> dict:
    run = _owned_run(run_id, user, db)
    if payload.decision not in ("test", "skip"):
        raise HTTPException(422, "The decision must be either 'test' or 'skip'.")
    try:
        offer = pert.get(payload.offer_key)
    except pert.PerturbationNotAllowed as exc:
        raise HTTPException(422, str(exc))

    allowance = commercial.allowance_for(db, AccessTier(run.access_tier)).perturbations_per_run
    if len(db.scalars(select(Perturbation).where(Perturbation.run_id == run.id)).all()) >= allowance:
        raise HTTPException(
            429,
            {
                "error": "perturbation_allowance_exhausted",
                "message": ent.get_feature("perturbation_extended").locked_explanation,
            },
        )

    current = run.parameters.get(offer.parameter_key)
    proposed = pert.proposed_value(offer, current)
    record = Perturbation(
        run_id=run.id,
        parameter_key=offer.parameter_key,
        from_value={"value": current},
        to_value={"value": proposed},
        scientific_reason=offer.scientific_reason,
        evidence_source_ids=offer.evidence_source_ids,
        expected_consequence={
            "expectations": [
                {"metric": e.metric, "direction": e.direction, "reason": e.reason}
                for e in offer.expectations
            ]
        },
        what_to_observe=offer.what_to_observe,
        limitation=offer.limitation,
        decision=payload.decision,
        decided_at=datetime.utcnow(),
    )
    db.add(record)
    db.commit()

    if payload.decision == "skip":
        return {"perturbation": _serialise_perturbation(record), "alternateRun": None}

    # The original run is never mutated: the alternate is a new run record.
    alternate_parameters = dict(run.parameters)
    try:
        alternate_parameters[offer.parameter_key] = params.validate(
            offer.parameter_key, proposed, tier
        )
    except params.ParameterError as exc:
        raise HTTPException(
            422,
            {
                "error": "perturbation_out_of_range",
                "message": (
                    f"The proposed value falls outside the range your tier can "
                    f"address. {exc}"
                ),
            },
        )

    alternate = Run(
        user_id=user.id,
        dataset_id=run.dataset_id,
        track=run.track,
        week=run.week,
        access_tier=tier,
        pipeline_version=run.pipeline_version,
        parameters=alternate_parameters,
        status=RunStatus.QUEUED,
        parent_run_id=run.id,
        is_original=False,
    )
    db.add(alternate)
    db.commit()

    dataset = db.get(Dataset, run.dataset_id)
    try:
        data = load(dataset)
    except DatasetUnavailable as exc:
        alternate.status = RunStatus.FAILED
        alternate.error_message = exc.message
        db.commit()
    else:
        #: Reconciliation needs the alternate's outputs, so it runs as the
        #: completion hook rather than holding the request open for a full
        #: second pipeline. The client polls the perturbation record.
        original_outputs = dict(run.outputs or {})
        record_id = record.id

        def _reconcile(session, completed) -> None:
            saved = session.get(Perturbation, record_id)
            if saved is None:
                return
            reconciliation = pert.reconcile(offer, original_outputs, completed.outputs)
            saved.actual_outcome = reconciliation
            saved.divergence_explanation = reconciliation["divergenceExplanation"]
            saved.matched_expectation = reconciliation["matchedExpectation"]
            session.commit()

        jobs.submit(db, alternate, data, on_complete=_reconcile)

    record.alternate_run_id = alternate.id
    db.commit()
    db.refresh(record)

    return {
        "perturbation": _serialise_perturbation(record),
        "alternateRun": _serialise(alternate),
        "originalRun": _serialise(run),
    }


def _serialise_perturbation(record: Perturbation) -> dict:
    return {
        "id": record.id,
        "runId": record.run_id,
        "parameterKey": record.parameter_key,
        "fromValue": record.from_value.get("value"),
        "toValue": record.to_value.get("value"),
        "scientificReason": record.scientific_reason,
        "expectedConsequence": record.expected_consequence,
        "whatToObserve": record.what_to_observe,
        "limitation": record.limitation,
        "decision": record.decision,
        "alternateRunId": record.alternate_run_id,
        "actualOutcome": record.actual_outcome,
        "divergenceExplanation": record.divergence_explanation,
        "matchedExpectation": record.matched_expectation,
    }


@router.get("/{run_id}/figures")
def run_figures(
    run_id: str, step: str, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> list:
    """The figures a step's computed output can be drawn as (spec 10.7).

    Plots are drawn from the run's own recorded outputs; nothing is recomputed
    and a figure with no output behind it is not returned.
    """
    return figures.figures_for_step(_owned_run(run_id, user, db), step)


@router.get("/{run_id}/perturbation-records")
def perturbation_records(
    run_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> list:
    run = _owned_run(run_id, user, db)
    rows = db.scalars(select(Perturbation).where(Perturbation.run_id == run.id)).all()
    return [_serialise_perturbation(r) for r in rows]


# ----------------------------------------------------------- interpretation --
class InterpretationRequest(BaseModel):
    step: str
    observation: str = ""
    statistical_evidence: str = ""
    biological_interpretation: str = ""
    hypothesis: str = ""
    label: Optional[InterpretationLabel] = None


@router.post(
    "/{run_id}/interpretation",
    dependencies=[Depends(require_feature("interpretation_panel"))],
)
def save_interpretation(
    run_id: str,
    payload: InterpretationRequest,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    run = _owned_run(run_id, user, db)
    record = db.scalar(
        select(Interpretation).where(
            Interpretation.run_id == run.id, Interpretation.step == payload.step
        )
    ) or Interpretation(run_id=run.id, user_id=user.id, step=payload.step)
    record.observation = payload.observation
    record.statistical_evidence = payload.statistical_evidence
    record.biological_interpretation = payload.biological_interpretation
    record.hypothesis = payload.hypothesis
    record.label = payload.label
    db.add(record)
    db.commit()
    return {
        "id": record.id,
        "step": record.step,
        "observation": record.observation,
        "statisticalEvidence": record.statistical_evidence,
        "biologicalInterpretation": record.biological_interpretation,
        "hypothesis": record.hypothesis,
        "label": record.label,
    }


@router.get("/{run_id}/interpretation")
def list_interpretations(
    run_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> list:
    run = _owned_run(run_id, user, db)
    rows = db.scalars(select(Interpretation).where(Interpretation.run_id == run.id)).all()
    return [
        {
            "id": r.id,
            "step": r.step,
            "observation": r.observation,
            "statisticalEvidence": r.statistical_evidence,
            "biologicalInterpretation": r.biological_interpretation,
            "hypothesis": r.hypothesis,
            "label": r.label,
        }
        for r in rows
    ]


# ------------------------------------------------- extended perturbation --
class CustomPerturbationRequest(BaseModel):
    parameter_key: str
    value: Any
    rationale: str = ""
    expected_direction: Optional[str] = None
    expected_metric: Optional[str] = None


@router.post(
    "/{run_id}/perturbations/custom",
    dependencies=[Depends(require_feature("perturbation_extended"))],
)
def custom_perturbation(
    run_id: str,
    payload: CustomPerturbationRequest,
    user: User = Depends(current_user),
    tier: AccessTier = Depends(current_tier),
    db: Session = Depends(get_db),
) -> dict:
    """A learner-authored what-if (spec 7, Phase 3).

    The change still passes the whitelist and the parameter registry, and the
    original run is still preserved. What is not invented is the expectation:
    the learner states it, and the platform compares against what they said.
    """
    run = _owned_run(run_id, user, db)
    try:
        pert.assert_perturbable(payload.parameter_key)
    except pert.PerturbationNotAllowed as exc:
        raise HTTPException(422, str(exc))

    parameter = params.get(payload.parameter_key)
    if not parameter.applies_to(AnalysisTrack(run.track)):
        raise HTTPException(
            422, f"'{parameter.label}' does not apply to this analysis track."
        )
    try:
        value = params.validate(payload.parameter_key, payload.value, tier)
    except params.ParameterError as exc:
        raise HTTPException(422, {"error": "invalid_parameters", "message": str(exc)})

    current = run.parameters.get(payload.parameter_key)
    if value == current:
        raise HTTPException(422, "That is the value the original run already used.")

    expectations = [
        {
            "metric": payload.expected_metric or "__unspecified__",
            "direction": payload.expected_direction or pert.UNCERTAIN,
            "reason": payload.rationale
            or "Learner-authored change; the expectation is the learner's own.",
        }
    ]
    record = Perturbation(
        run_id=run.id,
        parameter_key=payload.parameter_key,
        from_value={"value": current},
        to_value={"value": value},
        scientific_reason=payload.rationale or "Learner-authored what-if.",
        evidence_source_ids=[],
        expected_consequence={"expectations": expectations, "authoredBy": "learner"},
        what_to_observe=parameter.method_rule,
        limitation=(
            "You authored this change, so the platform offers no reviewed "
            "expectation for it and no evidence citation. Judge the result "
            "against what you wrote down before running it."
        ),
        decision="test",
        decided_at=datetime.utcnow(),
    )
    db.add(record)
    db.commit()

    alternate = Run(
        user_id=user.id,
        dataset_id=run.dataset_id,
        track=run.track,
        module=run.module,
        week=run.week,
        access_tier=tier,
        pipeline_version=run.pipeline_version,
        parameters={**run.parameters, payload.parameter_key: value},
        status=RunStatus.QUEUED,
        parent_run_id=run.id,
        is_original=False,
    )
    db.add(alternate)
    db.commit()

    dataset = db.get(Dataset, run.dataset_id)
    try:
        data = load(dataset)
        _attach_spatial_context(db, data, dataset, alternate.parameters, tier, user)
    except DatasetUnavailable as exc:
        alternate.status = RunStatus.FAILED
        alternate.error_message = exc.message
        db.commit()
    else:
        original_outputs = dict(run.outputs or {})
        record_id = record.id

        def _diff(session, completed) -> None:
            saved = session.get(Perturbation, record_id)
            if saved is None:
                return
            saved.actual_outcome = _numeric_diff(original_outputs, completed.outputs)
            session.commit()

        jobs.submit(db, alternate, data, on_complete=_diff)

    record.alternate_run_id = alternate.id
    record.divergence_explanation = (
        "The platform states what changed between the two runs. Because you "
        "authored the change, judging whether it matched your expectation is "
        "yours to record in the interpretation panel."
    )
    db.commit()
    return {
        "perturbation": _serialise_perturbation(record),
        "alternateRun": _serialise(alternate),
        "originalRun": _serialise(run),
    }


# ----------------------------------------------------------- compare runs --
def _flatten_numeric(outputs: dict) -> Dict[str, float]:
    flat: Dict[str, float] = {}
    for namespace, values in (outputs or {}).items():
        if not isinstance(values, dict):
            continue
        for key, value in values.items():
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                continue
            flat[f"{namespace}.{key}"] = float(value)
    return flat


def _numeric_diff(original: dict, alternate: dict) -> dict:
    before, after = _flatten_numeric(original), _flatten_numeric(alternate)
    rows = []
    for key in sorted(set(before) | set(after)):
        first, second = before.get(key), after.get(key)
        rows.append(
            {
                "metric": key,
                "before": first,
                "after": second,
                "changed": first != second,
                "direction": (
                    None
                    if first is None or second is None
                    else "increase"
                    if second > first
                    else "decrease"
                    if second < first
                    else "unchanged"
                ),
            }
        )
    return {"comparisons": rows}


@router.get("/compare/pair", dependencies=[Depends(require_feature("compare_runs"))])
def compare(
    original: str,
    alternate: str,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Original against alternate settings: what changed, and what it changed."""
    first = _owned_run(original, user, db)
    second = _owned_run(alternate, user, db)
    if first.dataset_id != second.dataset_id or first.track != second.track:
        raise HTTPException(
            422,
            "Only runs of the same analysis track on the same dataset are "
            "comparable. Comparing anything else would be comparing two "
            "different experiments.",
        )

    keys = sorted(set(first.parameters) | set(second.parameters))
    settings = [
        {
            "key": key,
            "label": params.get(key).label,
            "before": first.parameters.get(key),
            "after": second.parameters.get(key),
            "changed": first.parameters.get(key) != second.parameters.get(key),
            "methodRule": params.get(key).method_rule,
        }
        for key in keys
    ]

    labels = {}
    for run in (first, second):
        rows = db.scalars(
            select(Interpretation).where(Interpretation.run_id == run.id)
        ).all()
        labels[run.id] = {row.step: row.label for row in rows if row.label}
    changed_conclusions = [
        {
            "step": step,
            "before": labels[first.id].get(step),
            "after": labels[second.id].get(step),
        }
        for step in sorted(set(labels[first.id]) | set(labels[second.id]))
        if labels[first.id].get(step) != labels[second.id].get(step)
    ]

    return {
        "original": _serialise(first),
        "alternate": _serialise(second),
        "settings": settings,
        "changedSettings": [row for row in settings if row["changed"]],
        "metrics": _numeric_diff(first.outputs, second.outputs)["comparisons"],
        "changedConclusions": changed_conclusions,
        "note": (
            "A metric that moved tells you the analysis is sensitive to the "
            "setting. It does not tell you which run is closer to the truth."
        ),
    }
