"""Omics Copilot service layer.

Spec 8. The Copilot is the mentor and interpretation layer; it is never the
statistical engine. Every function here takes the *actual* computed outputs of a
validated run and composes a response from reviewed knowledge, resolving all
variable content through ``grounding.render``. Nothing it returns can contain a
number, gene or citation that did not come from the run or the evidence registry.

Every response is persisted as an ``AiInteraction`` so it can be audited by the
learner (spec 5.3) and reconstructed later (spec 14.6).
"""

from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.constants import AnalysisTrack, InterpretationLabel
from app.copilot import evidence, knowledge, labels, perturbation
from app.copilot.grounding import Grounded, render
from app.models import AiInteraction, Run


def _persist(
    db: Session,
    *,
    user_id: str,
    run: Optional[Run],
    function: str,
    step: str,
    output: dict,
    grounded: Optional[Grounded] = None,
    label: Optional[str] = None,
    label_rationale: str = "",
) -> AiInteraction:
    interaction = AiInteraction(
        run_id=run.id if run else None,
        user_id=user_id,
        function=function,
        step=step,
        prompt_context={"track": run.track if run else None, "step": step},
        output=output,
        evidence_source_ids=list(grounded.evidence_source_ids) if grounded else [],
        computed_refs=list(grounded.computed_refs) if grounded else [],
        interpretation_label=InterpretationLabel(label) if label else None,
        label_rationale=label_rationale,
    )
    db.add(interaction)
    db.commit()
    return interaction


def _payload(grounded: Grounded, **extra) -> dict:
    payload = {
        "text": grounded.text,
        "evidence": evidence.resolve(grounded.evidence_source_ids),
        "computedRefs": grounded.computed_refs,
        "parameterRefs": grounded.parameter_refs,
    }
    payload.update(extra)
    return payload


# ---------------------------------------------------------------- explain --
def explain(db: Session, user_id: str, run: Run, step: str) -> dict:
    """Explain the current step: what it does, why, and what to look at."""
    entry = knowledge.get(AnalysisTrack(run.track), step)
    grounded = render(
        entry.explain_template,
        run.outputs,
        run.parameters,
        entry.evidence_source_ids,
    )
    payload = _payload(
        grounded,
        title=entry.title,
        purpose=entry.purpose,
        whatToObserve=entry.what_to_observe,
        caveats=entry.caveats,
    )
    interaction = _persist(
        db, user_id=user_id, run=run, function="explain", step=step,
        output=payload, grounded=grounded,
    )
    payload["interactionId"] = interaction.id
    return payload


# --------------------------------------------------------------- evidence --
def cite(db: Session, user_id: str, run: Optional[Run], step: str, track: AnalysisTrack) -> dict:
    """Return the approved sources behind a step. Never fetches at runtime."""
    entry = knowledge.get(track, step)
    payload = {"step": step, "evidence": evidence.resolve(entry.evidence_source_ids)}
    interaction = _persist(
        db, user_id=user_id, run=run, function="evidence", step=step, output=payload
    )
    payload["interactionId"] = interaction.id
    return payload


# -------------------------------------------------------------- recommend --
def recommend(db: Session, user_id: str, run: Run, step: str) -> dict:
    """Method-derived guidance, separating a required rule from a heuristic.

    A recommendation is emitted only when the locked method or the registry's
    method rule justifies it; there is no path that produces advice from nothing.
    """
    track = AnalysisTrack(run.track)
    entry = knowledge.get(track, step)
    from app.core import parameters as params

    items: List[dict] = []
    for descriptor in params.describe_for(track, run.access_tier):
        if descriptor["step"] != step:
            continue
        required = descriptor["choices"] is not None and len(descriptor["choices"] or []) == 1
        items.append(
            {
                "parameter": descriptor["key"],
                "label": descriptor["label"],
                "currentValue": run.parameters.get(descriptor["key"]),
                "kind": "required_rule" if required else "heuristic",
                "basis": descriptor["methodRule"],
                "caveat": descriptor["caveat"],
            }
        )

    payload = {
        "step": step,
        "title": entry.title,
        "recommendations": items,
        "evidence": evidence.resolve(entry.evidence_source_ids),
        "note": (
            "A required rule follows from the locked method and cannot be traded "
            "away. A heuristic is a defensible default that your data may argue "
            "against."
        ),
    }
    interaction = _persist(
        db, user_id=user_id, run=run, function="recommend", step=step, output=payload
    )
    payload["interactionId"] = interaction.id
    return payload


# --------------------------------------------------- suggest perturbation --
def suggest_perturbation(db: Session, user_id: str, run: Run, step: str) -> List[dict]:
    """Build the TEST/SKIP offers for a step (spec 8.1).

    The offer carries direction-and-effect expectations only. No numeric result
    is promised, because none has been computed.
    """
    track = AnalysisTrack(run.track)
    offers = []
    for offer in perturbation.available_for(track, step):
        current = run.parameters.get(offer.parameter_key)
        if current is None:
            continue
        proposed = perturbation.proposed_value(offer, current)
        payload = {
            "key": offer.key,
            "label": offer.label,
            "parameterKey": offer.parameter_key,
            "currentValue": current,
            "proposedValue": proposed,
            "scientificReason": offer.scientific_reason,
            "expectedConsequence": [
                {
                    "metric": e.metric,
                    "metricLabel": e.metric_label,
                    "direction": e.direction,
                    "reason": e.reason,
                }
                for e in offer.expectations
            ],
            "whatToObserve": offer.what_to_observe,
            "limitation": offer.limitation,
            "evidence": evidence.resolve(offer.evidence_source_ids),
        }
        offers.append(payload)
        _persist(
            db, user_id=user_id, run=run, function="suggest_perturbation",
            step=step, output=payload,
        )
    return offers


# -------------------------------------------------------------- interpret --
def interpret(db: Session, user_id: str, run: Run, step: str, context: Optional[dict] = None) -> dict:
    """Interpret the actual computed output in four separated fields (spec 9.10)."""
    track = AnalysisTrack(run.track)
    entry = knowledge.get(track, step)
    grounded = render(
        entry.explain_template, run.outputs, run.parameters, entry.evidence_source_ids
    )

    context = dict(context or {})
    context.setdefault("grouping", run.parameters.get("sc.de.grouping"))
    triggered = labels.evaluate(run.outputs, context)
    assignment = labels.assign(triggered)

    payload = {
        "step": step,
        # Observation: the computed numbers, nothing added.
        "observation": grounded.text,
        # Statistical evidence: what the numbers do and do not establish.
        "statisticalEvidence": _statistical_note(entry, triggered),
        # Biological interpretation: reviewed content, explicitly conditional.
        "biologicalInterpretation": entry.purpose,
        # Hypothesis: what to test next, never asserted as a finding.
        "hypothesis": entry.what_to_observe,
        "label": assignment["label"],
        "labelRationale": assignment["rationale"],
        "triggeredRules": triggered,
        "caveats": entry.caveats,
        "evidence": evidence.resolve(entry.evidence_source_ids),
        "computedRefs": grounded.computed_refs,
    }
    interaction = _persist(
        db, user_id=user_id, run=run, function="interpret", step=step,
        output=payload, grounded=grounded, label=assignment["label"],
        label_rationale=assignment["rationale"],
    )
    payload["interactionId"] = interaction.id
    return payload


def _statistical_note(entry: knowledge.StepKnowledge, triggered: List[str]) -> str:
    if not triggered:
        return (
            "The computed values above are the statistical evidence. They describe "
            "this dataset under the settings recorded for this run and no other."
        )
    reasons = [labels.RULES_BY_KEY[key].rationale for key in triggered if key in labels.RULES_BY_KEY]
    return " ".join(reasons)


# -------------------------------------------------------------- challenge --
def challenge(db: Session, user_id: str, run: Run, step: str, context: Optional[dict] = None) -> dict:
    """Warn about confounding, replication, overclustering and overclaiming."""
    triggered = labels.evaluate(run.outputs, context or {})
    warnings = [
        {
            "rule": key,
            "severity": _severity(labels.RULES_BY_KEY[key].label),
            "message": labels.RULES_BY_KEY[key].rationale,
        }
        for key in triggered
        if key in labels.RULES_BY_KEY
    ]
    entry = knowledge.get(AnalysisTrack(run.track), step)
    payload = {
        "step": step,
        "warnings": warnings,
        "caveats": entry.caveats,
        "clear": not warnings,
        "note": (
            "No warning fired for the checks this platform runs. That is not the "
            "same as the analysis being free of problems."
        )
        if not warnings
        else "",
    }
    interaction = _persist(
        db, user_id=user_id, run=run, function="challenge", step=step, output=payload
    )
    payload["interactionId"] = interaction.id
    return payload


def _severity(label: InterpretationLabel) -> str:
    return {
        InterpretationLabel.SPECULATIVE: "blocking",
        InterpretationLabel.NEEDS_VALIDATION: "high",
        InterpretationLabel.PARTIALLY_SUPPORTED: "moderate",
        InterpretationLabel.SUPPORTED: "info",
    }[label]
