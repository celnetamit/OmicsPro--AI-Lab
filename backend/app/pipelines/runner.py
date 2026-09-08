"""Run execution.

Spec 10: status transitions are explicit, failures carry a readable scientific
message, the last valid step is preserved so a failed run leaves no corrupted
partial state, and the full provenance of the execution is written to the run
record.
"""

import copy
from datetime import datetime
from typing import Dict, Optional

from sqlalchemy.orm import Session

from app.constants import LOCKED_METHODS, AnalysisTrack, RunStatus
from app.models import Run
from app.pipelines import registry
from app.pipelines.base import BackendUnavailable, DataObject, StepContext, StepFailure


def method_versions_for(track: AnalysisTrack, module: Optional[str] = None) -> Dict[str, str]:
    """Method and version stamp written to every run record."""
    pipeline = registry.get(track, module)
    required = {s.requires_method for s in pipeline.steps if s.requires_method}
    stamp = {
        key: f"{LOCKED_METHODS[key]['method']} {LOCKED_METHODS[key]['version']}"
        for key in sorted(required)
    }
    stamp["pipeline"] = pipeline.version
    return stamp


def execute(db: Session, run: Run, data: DataObject) -> Run:
    """Run every step in order, committing status transitions as they happen."""
    pipeline = registry.get(AnalysisTrack(run.track), run.module or None)

    run.status = RunStatus.VALIDATING
    run.started_at = datetime.utcnow()
    run.method_versions = method_versions_for(AnalysisTrack(run.track), run.module or None)
    run.pipeline_version = pipeline.version
    db.commit()

    outputs: Dict[str, dict] = {}
    #: Snapshot so a failure cannot leave a half-mutated object behind.
    working = copy.deepcopy(data)
    working.meta.setdefault("obs_before", copy.deepcopy(working.obs))

    run.status = RunStatus.RUNNING
    db.commit()

    for index, step in enumerate(pipeline.steps):
        context = StepContext(
            data=working, parameters=run.parameters, outputs=outputs, backend=None
        )
        try:
            outputs[step.publishes] = step.run(context)
        except StepFailure as exc:
            return _fail(db, run, step.key, exc.message, exc.detail, outputs)
        except BackendUnavailable as exc:
            return _fail(db, run, step.key, str(exc), "locked runtime missing", outputs)
        except Exception as exc:  # unexpected: still leave a valid state behind
            return _fail(
                db,
                run,
                step.key,
                f"The '{step.label}' step could not complete. The analysis stopped "
                f"here and the results of the earlier steps are preserved.",
                f"{type(exc).__name__}: {exc}",
                outputs,
            )
        run.last_valid_step = step.key
        run.outputs = dict(outputs)
        db.commit()

    run.status = RunStatus.COMPLETED
    run.finished_at = datetime.utcnow()
    run.outputs = dict(outputs)
    db.commit()
    return run


def _fail(
    db: Session,
    run: Run,
    step_key: str,
    message: str,
    detail: str,
    outputs: Dict[str, dict],
) -> Run:
    run.status = RunStatus.FAILED
    run.finished_at = datetime.utcnow()
    run.error_message = message
    run.error_detail = f"step={step_key}; {detail}"
    #: Outputs of the steps that did succeed stay readable.
    run.outputs = dict(outputs)
    db.commit()
    return run


def cancel(db: Session, run: Run) -> Run:
    if run.status in (RunStatus.COMPLETED, RunStatus.FAILED):
        return run
    run.status = RunStatus.CANCELLED
    run.finished_at = datetime.utcnow()
    db.commit()
    return run


def next_step(run: Run) -> Optional[str]:
    pipeline = registry.get(AnalysisTrack(run.track), run.module or None)
    keys = pipeline.step_keys
    if run.last_valid_step is None:
        return keys[0]
    index = keys.index(run.last_valid_step)
    return keys[index + 1] if index + 1 < len(keys) else None
