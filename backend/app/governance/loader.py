"""Load a validated Dataset record into the internal DataObject.

Spec 10: runs execute against validated internal objects, never directly
against arbitrary user files. Everything a pipeline sees passes through here.
"""

import json
import os

import numpy as np

from app.constants import AnalysisTrack
from app.models import Dataset
from app.pipelines.base import DataObject, StepFailure
from app.settings import settings


class DatasetUnavailable(StepFailure):
    """The dataset record exists but its files are not present or not validated."""


def load(dataset: Dataset) -> DataObject:
    if dataset.validation_status != "validated":
        raise DatasetUnavailable(
            f"'{dataset.name}' has not passed validation ({dataset.validation_status}) "
            f"and cannot be analysed. Guided datasets become selectable once their "
            f"files are ingested and validated."
        )
    base = os.path.join(settings.data_dir, dataset.storage_path)
    matrix_path, meta_path = f"{base}.npz", f"{base}.meta.json"
    if not (os.path.exists(matrix_path) and os.path.exists(meta_path)):
        raise DatasetUnavailable(
            f"The files for '{dataset.name}' are not present in this environment. "
            f"Run scripts/fetch_guided_data.py to ingest them from {dataset.accession}."
        )
    with np.load(matrix_path) as archive:
        matrix = archive["matrix"]
    with open(meta_path) as handle:
        meta = json.load(handle)

    return DataObject(
        matrix=matrix,
        obs=meta["obs"],
        var=meta["var"],
        track=AnalysisTrack(dataset.track),
        provenance={
            "dataset_id": dataset.id,
            "name": dataset.name,
            "source": dataset.source,
            "accession": dataset.accession,
            "license": dataset.license,
            "imported_at": dataset.imported_at.isoformat(),
            "validation_status": dataset.validation_status,
        },
    )
