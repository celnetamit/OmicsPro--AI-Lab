#!/usr/bin/env python3
"""Ingest the guided teaching datasets into the internal object format.

Guided datasets are seeded as ``pending_data_ingest`` and are not selectable
until this script has produced their files and the ingestion validator has
passed. Nothing stands in for missing teaching data: the platform reports the
dataset as unavailable rather than computing anything from a placeholder.

The download itself is a deliberate operator step, because both accessions carry
terms of use that must be accepted by a person:

    Foundation  GSE52778  airway smooth muscle, glucocorticoid treated
                Obtain the analysis-ready count matrix and sample sheet (for
                example via the Bioconductor 'airway' package, which packages
                this accession), then run:
                    python scripts/fetch_guided_data.py airway-dexamethasone \\
                        counts.csv metadata.csv

    Core        GSE96583  PBMC, control and interferon-beta stimulated
                Obtain the filtered matrix and cell annotations, then run:
                    python scripts/fetch_guided_data.py pbmc-interferon-beta \\
                        matrix.mtx barcodes_with_metadata.csv

Each ingestion writes ``<storage_path>.npz`` and ``<storage_path>.meta.json``
under the data directory, runs the governance validator, and flips the dataset
to ``validated`` only when it passes.
"""

import json
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from app.constants import AnalysisTrack  # noqa: E402
from app.db import SessionLocal, init_db  # noqa: E402
from app.governance.validation import validate_upload  # noqa: E402
from app.models import Dataset  # noqa: E402
from app.settings import settings  # noqa: E402


def main() -> int:
    if len(sys.argv) != 4:
        print(__doc__)
        return 2

    slug, matrix_path, metadata_path = sys.argv[1:4]
    init_db()
    db = SessionLocal()
    dataset = db.query(Dataset).filter(Dataset.slug == slug).first()
    if dataset is None:
        print(f"No dataset seeded with slug '{slug}'. Run scripts/seed.py first.")
        return 1

    matrix = pd.read_csv(matrix_path, index_col=0)
    metadata = pd.read_csv(metadata_path)
    rows = metadata.to_dict("records")

    result = validate_upload(
        filename=os.path.basename(matrix_path),
        size_bytes=os.path.getsize(matrix_path),
        track=AnalysisTrack(dataset.track),
        max_bytes=8 * 1024 ** 3,
        metadata_rows=rows,
        provenance={
            "source": dataset.source,
            "accession": dataset.accession,
            "license": dataset.license,
        },
        n_matrix_columns=matrix.shape[1],
    )

    dataset.validation_report = result.as_dict()
    if not result.ok:
        dataset.validation_status = "failed_validation"
        db.commit()
        for error in result.errors:
            print(f"  [{error['code']}] {error['message']}")
        return 1

    base = os.path.join(settings.data_dir, dataset.storage_path)
    os.makedirs(os.path.dirname(base), exist_ok=True)
    np.savez_compressed(f"{base}.npz", matrix=matrix.to_numpy())
    with open(f"{base}.meta.json", "w") as handle:
        json.dump({"obs": rows, "var": list(matrix.index)}, handle)

    dataset.validation_status = "validated"
    db.commit()
    print(f"Ingested {slug}: {matrix.shape[0]} features × {matrix.shape[1]} samples")
    for warning in result.warnings:
        print(f"  warning [{warning['code']}] {warning['message']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
