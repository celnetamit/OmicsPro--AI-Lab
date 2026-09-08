"""Pipeline framework: versioned step graphs over validated internal objects.

Spec 10. A pipeline is an ordered list of steps; each step declares the
parameters it reads and the computed outputs it publishes. The Copilot's
knowledge entries reference those output keys, so a step that stops publishing a
key breaks its explanation loudly rather than silently describing nothing.

Runs never execute against arbitrary user files: the runner is handed a
validated ``DataObject`` produced by the governance layer.
"""

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from app.constants import AnalysisTrack


class BackendUnavailable(RuntimeError):
    """A locked scientific runtime is not provisioned in this environment.

    Raised instead of substituting a different method. Silent substitution would
    invalidate the method provenance stamped onto every run.
    """


class StepFailure(RuntimeError):
    """A step failed for a scientific or technical reason the learner can read."""

    def __init__(self, message: str, detail: str = ""):
        super().__init__(message)
        self.message = message
        self.detail = detail


@dataclass
class DataObject:
    """Validated internal representation handed to every step.

    ``matrix`` is genes-by-samples (Foundation) or cells-by-genes (Core);
    ``obs`` and ``var`` hold the corresponding annotations.
    """

    matrix: Any
    obs: Any
    var: Any
    track: AnalysisTrack
    provenance: Dict[str, Any] = field(default_factory=dict)
    layers: Dict[str, Any] = field(default_factory=dict)
    meta: Dict[str, Any] = field(default_factory=dict)


@dataclass
class StepContext:
    data: DataObject
    parameters: Dict[str, Any]
    #: Outputs published by earlier steps in this run.
    outputs: Dict[str, Any]
    backend: Any


@dataclass(frozen=True)
class Step:
    key: str
    label: str
    #: Parameter registry keys this step reads.
    reads_parameters: List[str]
    #: Output namespace this step publishes, e.g. ``"de"``.
    publishes: str
    run: Callable[[StepContext], Dict[str, Any]]
    #: Locked method whose runtime this step requires, if any.
    requires_method: Optional[str] = None


@dataclass(frozen=True)
class Pipeline:
    track: AnalysisTrack
    version: str
    steps: List[Step]

    def step(self, key: str) -> Step:
        for step in self.steps:
            if step.key == key:
                return step
        raise KeyError(f"Step '{key}' is not part of pipeline {self.version}.")

    @property
    def step_keys(self) -> List[str]:
        return [s.key for s in self.steps]
