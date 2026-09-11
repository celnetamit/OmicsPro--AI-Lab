#!/usr/bin/env python3
"""Ingest a guided teaching dataset into the internal object format.

Guided datasets are seeded as ``pending_data_ingest`` and are not selectable
until this script has produced their files and the ingestion validator has
passed. Nothing stands in for missing teaching data: the platform reports the
dataset as unavailable rather than computing anything from a placeholder.

The download itself is a deliberate operator step, because the accessions carry
terms of use that must be accepted by a person. Once the files are on disk:

    Foundation  GSE52778  airway smooth muscle, glucocorticoid treated
                A count matrix (genes as rows, samples as columns) and a sample
                sheet with sample_id and condition, for example exported from
                the Bioconductor 'airway' package, which packages this accession:
                    python scripts/fetch_guided_data.py airway-dexamethasone \\
                        counts.csv --metadata samples.csv

    Core        GSE96583  PBMC, control and interferon-beta stimulated
                A 10x matrix directory (matrix.mtx.gz, features.tsv.gz or
                genes.tsv, barcodes.tsv.gz), a 10x .h5, or an .h5ad; plus a cell
                table naming each barcode with its sample_id and condition:
                    python scripts/fetch_guided_data.py pbmc-interferon-beta \\
                        filtered_matrix/ --metadata cells.csv \\
                        --min-cells-per-gene 3 --max-cells 12000 --seed 0

    Advanced    a Visium section: the Space Ranger outs directory (the filtered
                matrix and spatial/tissue_positions.csv) or an .h5ad carrying
                coordinates in obsm['spatial']:
                    python scripts/fetch_guided_data.py <slug> outs/ \\
                        --set sample_id=section1 --set condition=reference

Formats: CSV/TSV (optionally .gz), 10x Matrix Market directory or .mtx,
10x HDF5 (.h5), AnnData (.h5ad). Metadata is matched to the matrix by
identifier (sample_id; cell_id or barcode; spot_id or barcode).

The analysis object is dense in memory, so a large single-cell matrix must be
reduced on the way in. --max-cells takes a seeded subsample and
--min-cells-per-gene drops rarely detected genes; both are recorded on the
dataset, and a subsample is added to its limitations so every result says so.

Each ingestion writes ``<storage_path>.npz`` and ``<storage_path>.meta.json``
under the data directory, runs the governance validator, and flips the dataset
to ``validated`` only when it passes.
"""

import argparse
import glob
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from app.constants import AnalysisTrack  # noqa: E402
from app.db import SessionLocal, init_db  # noqa: E402
from app.governance import ingest  # noqa: E402
from app.governance.validation import validate_metadata, validate_upload  # noqa: E402
from app.models import Dataset  # noqa: E402
from app.settings import settings  # noqa: E402


def _first(directory: str, *patterns: str):
    for pattern in patterns:
        hits = sorted(glob.glob(os.path.join(directory, pattern)))
        if hits:
            return hits[0]
    return None


def _resolve(matrix_path: str, args) -> dict:
    """Turn a file or a 10x / Space Ranger directory into the sources to read."""
    sources = {"features": args.features, "barcodes": args.barcodes, "positions": args.positions}
    if os.path.isdir(matrix_path):
        directory = matrix_path
        h5 = _first(directory, "filtered_feature_bc_matrix.h5", "*.h5")
        mtx_dir = _first(directory, "filtered_feature_bc_matrix") or directory
        mtx = _first(mtx_dir, "matrix.mtx.gz", "matrix.mtx")
        if mtx:
            matrix_path = mtx
            sources["features"] = sources["features"] or _first(
                mtx_dir, "features.tsv.gz", "features.tsv", "genes.tsv.gz", "genes.tsv"
            )
            sources["barcodes"] = sources["barcodes"] or _first(
                mtx_dir, "barcodes.tsv.gz", "barcodes.tsv"
            )
        elif h5:
            matrix_path = h5
        else:
            raise SystemExit(f"No matrix.mtx or .h5 found in {directory}.")
        sources["positions"] = sources["positions"] or _first(
            directory, "spatial/tissue_positions.csv", "spatial/tissue_positions_list.csv"
        )
    sources["matrix"] = matrix_path
    return {k: ingest.Source.from_path(v) for k, v in sources.items() if v}


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("slug", help="The seeded dataset to ingest into.")
    parser.add_argument("matrix", help="Matrix file, or a 10x / Space Ranger directory.")
    parser.add_argument("--metadata", help="Sample, cell or spot table (CSV or TSV).")
    parser.add_argument("--features", help="features.tsv for a bare .mtx file.")
    parser.add_argument("--barcodes", help="barcodes.tsv for a bare .mtx file.")
    parser.add_argument("--positions", help="Visium tissue_positions.csv.")
    parser.add_argument(
        "--set", action="append", default=[], metavar="FIELD=VALUE",
        help="Give every observation this annotation where it has none (repeatable).",
    )
    parser.add_argument("--max-cells", type=int, help="Seeded subsample to this many observations.")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--min-cells-per-gene", type=int, default=0)
    parser.add_argument("--max-values", type=int, default=ingest.DEFAULT_MAX_VALUES)
    args = parser.parse_args()

    defaults = {}
    for pair in args.set:
        key, _, value = pair.partition("=")
        if not key or not value:
            parser.error(f"--set expects FIELD=VALUE, not '{pair}'.")
        defaults[key] = value

    init_db()
    db = SessionLocal()
    dataset = db.query(Dataset).filter(Dataset.slug == args.slug).first()
    if dataset is None:
        print(f"No dataset seeded with slug '{args.slug}'. Run scripts/seed.py first.")
        return 1
    track = AnalysisTrack(dataset.track)

    sources = _resolve(args.matrix, args)
    metadata = ingest.Source.from_path(args.metadata) if args.metadata else None
    gate = validate_upload(
        filename=sources["matrix"].name,
        size_bytes=sum(s.size for s in sources.values()),
        track=track,
        max_bytes=8 * 1024 ** 3,
        provenance={
            "source": dataset.source,
            "accession": dataset.accession,
            "license": dataset.license,
        },
    )
    if not gate.ok:
        return _refuse(db, dataset, gate.as_dict())

    try:
        ingested = ingest.ingest(
            track,
            sources["matrix"],
            metadata,
            features=sources.get("features"),
            barcodes=sources.get("barcodes"),
            positions=sources.get("positions"),
            defaults=defaults,
            max_observations=args.max_cells,
            seed=args.seed,
            min_cells_per_gene=args.min_cells_per_gene,
            max_values=args.max_values,
        )
    except ingest.IngestError as exc:
        return _refuse(db, dataset, {
            "ok": False, "errors": [{"code": exc.code, "message": exc.message}],
            "warnings": [], "summary": {},
        })

    result = validate_metadata(track, ingested.obs, n_observations=len(ingested.obs))
    result.warnings = [*gate.warnings, *ingested.warnings, *result.warnings]
    result.summary["ingestion"] = ingested.notes
    if not result.ok:
        return _refuse(db, dataset, result.as_dict())

    ingested.write(os.path.join(settings.data_dir, dataset.storage_path))
    dataset.validation_report = result.as_dict()
    dataset.file_format = sources["matrix"].extension.lstrip(".")
    subsampled = [note for note in ingested.notes if "subsample" in note]
    if subsampled:
        dataset.limitations = [*(dataset.limitations or []), *subsampled]
    dataset.validation_status = "validated"
    db.commit()

    shape = " × ".join(str(n) for n in ingested.matrix.shape)
    print(f"Ingested {args.slug}: stored matrix {shape} ({len(ingested.obs)} observations).")
    for note in ingested.notes:
        print(f"  note: {note}")
    for warning in result.warnings:
        print(f"  warning [{warning['code']}] {warning['message']}")
    return 0


def _refuse(db, dataset, report: dict) -> int:
    dataset.validation_report = report
    dataset.validation_status = "failed_validation"
    db.commit()
    print(f"Refused {dataset.slug}; nothing was written:")
    for error in report["errors"]:
        print(f"  [{error['code']}] {error['message']}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
