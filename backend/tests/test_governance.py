"""Definition of Done: ingestion validates format, structure, identifiers and
governance restrictions before anything executes (spec 6, 13)."""

import pytest

from app.constants import AccessTier, AnalysisTrack
from app.governance.loader import DatasetUnavailable, load
from app.governance.validation import scan_for_pii, validate_upload
from app.models import Dataset

ONE_MB = 1024 * 1024
CLEAN_ROWS = [
    {"sample_id": "S1", "condition": "treated", "batch": "b1"},
    {"sample_id": "S2", "condition": "treated", "batch": "b1"},
    {"sample_id": "S3", "condition": "untreated", "batch": "b1"},
    {"sample_id": "S4", "condition": "untreated", "batch": "b1"},
]


def _validate(**overrides):
    kwargs = dict(
        filename="counts.csv",
        size_bytes=ONE_MB,
        track=AnalysisTrack.FOUNDATION,
        max_bytes=10 * ONE_MB,
        metadata_rows=CLEAN_ROWS,
        provenance={"source": "GEO", "accession": "GSE1", "license": "public"},
        n_matrix_columns=4,
    )
    kwargs.update(overrides)
    return validate_upload(**kwargs)


def test_a_clean_analysis_ready_upload_passes():
    assert _validate().ok


def test_raw_sequencing_is_refused():
    result = _validate(filename="reads.fastq")
    assert not result.ok
    assert result.errors[0]["code"] == "raw_sequencing_not_supported"


def test_unsupported_format_is_refused():
    assert not _validate(filename="notes.docx").ok


def test_oversized_upload_is_refused():
    result = _validate(size_bytes=20 * ONE_MB)
    assert not result.ok
    assert any(e["code"] == "file_too_large" for e in result.errors)


def test_identifiable_information_blocks_ingestion():
    """Spec 6: this is a hard gate, not a warning."""
    rows = [{**CLEAN_ROWS[0], "patient_name": "Jane Doe"}] + CLEAN_ROWS[1:]
    result = _validate(metadata_rows=rows)
    assert not result.ok
    assert any(e["code"] == "identifiable_information" for e in result.errors)


@pytest.mark.parametrize(
    "row",
    [
        {"sample_id": "S1", "condition": "t", "email": "a@b.com"},
        {"sample_id": "S1", "condition": "t", "dob": "1980-01-01"},
        {"sample_id": "S1", "condition": "t", "mrn": "884"},
    ],
)
def test_pii_scanner_catches_common_identifier_shapes(row):
    assert scan_for_pii([row])


def test_matrix_and_metadata_must_agree():
    result = _validate(n_matrix_columns=6)
    assert not result.ok
    assert any(e["code"] == "matrix_metadata_mismatch" for e in result.errors)


def test_duplicate_sample_ids_are_refused():
    rows = [dict(CLEAN_ROWS[0]) for _ in range(4)]
    assert not _validate(metadata_rows=rows).ok


def test_missing_provenance_is_refused():
    result = _validate(provenance={"source": "GEO", "accession": "", "license": ""})
    assert not result.ok
    assert any(e["code"] == "missing_provenance" for e in result.errors)


def test_missing_replication_is_warned_not_silently_accepted():
    rows = [
        {"sample_id": "S1", "condition": "treated"},
        {"sample_id": "S2", "condition": "untreated"},
    ]
    result = _validate(metadata_rows=rows, n_matrix_columns=2)
    assert result.ok  # structurally valid
    assert any(w["code"] == "insufficient_replication" for w in result.warnings)


def test_batch_confounded_with_condition_is_warned():
    rows = [
        {"sample_id": "S1", "condition": "treated", "batch": "b1"},
        {"sample_id": "S2", "condition": "treated", "batch": "b1"},
        {"sample_id": "S3", "condition": "untreated", "batch": "b2"},
        {"sample_id": "S4", "condition": "untreated", "batch": "b2"},
    ]
    result = _validate(metadata_rows=rows)
    assert any(w["code"] == "confounded_batch" for w in result.warnings)


def test_an_unvalidated_dataset_cannot_be_loaded():
    dataset = Dataset(
        slug="x",
        name="Pending guided dataset",
        track=AnalysisTrack.FOUNDATION,
        validation_status="pending_data_ingest",
        storage_path="guided/x",
    )
    with pytest.raises(DatasetUnavailable, match="not passed validation"):
        load(dataset)
