"""Pipeline registry — one canonical pipeline per scientific track, plus the
versioned extension modules that run on a track's data (spec 10, 11).

A pipeline is never mutated after it is frozen: a method change is a new version
so historical run provenance stays true.
"""

from typing import Dict, List, Optional

from app.constants import ACTIVE_PHASE, AnalysisTrack
from app.pipelines import advanced, communication, core, foundation
from app.pipelines.base import Pipeline

PIPELINES: Dict[AnalysisTrack, Pipeline] = {
    AnalysisTrack.FOUNDATION: foundation.PIPELINE,
    AnalysisTrack.CORE: core.PIPELINE,
    AnalysisTrack.ADVANCED: advanced.PIPELINE,
}

TRACK_PHASE = {
    AnalysisTrack.FOUNDATION: 1,
    AnalysisTrack.CORE: 1,
    AnalysisTrack.ADVANCED: 2,
}

#: Extension modules, keyed by module id. Each declares the track whose data it
#: consumes, the entitlement feature that gates it, and its build phase.
MODULES: Dict[str, dict] = {
    "core_communication": {
        "pipeline": communication.PIPELINE,
        "track": AnalysisTrack.CORE,
        "label": "Cell-Cell Communication Explorer",
        "feature": "cell_communication",
        "phase": 2,
    },
}


def get(track: AnalysisTrack, module: Optional[str] = None) -> Pipeline:
    """The pipeline a run executes: an extension module, or the guided workflow."""
    if module:
        return get_module(module)["pipeline"]
    if TRACK_PHASE[track] > ACTIVE_PHASE:
        raise KeyError(f"The {track.value} pipeline is not available in this release.")
    return PIPELINES[track]


def get_module(module: str) -> dict:
    entry = MODULES.get(module)
    if entry is None:
        raise KeyError(f"'{module}' is not a registered analysis module.")
    if entry["phase"] > ACTIVE_PHASE:
        raise KeyError(f"'{entry['label']}' is not available in this release.")
    return entry


def available_tracks() -> List[AnalysisTrack]:
    return [t for t, phase in TRACK_PHASE.items() if phase <= ACTIVE_PHASE]


def available_modules(track: Optional[AnalysisTrack] = None) -> List[dict]:
    return [
        {"module": key, **{k: v for k, v in entry.items() if k != "pipeline"}}
        for key, entry in MODULES.items()
        if entry["phase"] <= ACTIVE_PHASE and (track is None or entry["track"] is track)
    ]
