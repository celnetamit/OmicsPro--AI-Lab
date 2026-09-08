"""Ingestion gates (spec 6).

These are hard gates, not guidelines: a dataset that fails any check never
reaches a pipeline. Expert upload is a Phase 3 feature, but the validator ships
in Phase 1 because guided and trial datasets pass through the same gate.
"""

import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from app.constants import AnalysisTrack

#: Analysis-ready formats only. Raw sequencing is documented future architecture
#: and is deliberately absent (spec 6).
ALLOWED_FORMATS: Dict[AnalysisTrack, List[str]] = {
    AnalysisTrack.FOUNDATION: [".csv", ".tsv", ".npz", ".rds", ".rdata"],
    AnalysisTrack.CORE: [".h5ad", ".h5", ".mtx", ".npz", ".rds", ".rdata"],
    AnalysisTrack.ADVANCED: [".h5ad", ".npz", ".rds", ".rdata"],
}

REJECTED_FORMATS = {".fastq", ".fq", ".bam", ".cram", ".sam", ".gz"}

REQUIRED_METADATA: Dict[AnalysisTrack, List[str]] = {
    AnalysisTrack.FOUNDATION: ["sample_id", "condition"],
    AnalysisTrack.CORE: ["sample_id", "condition"],
    AnalysisTrack.ADVANCED: ["sample_id", "condition"],
}

REQUIRED_PROVENANCE = ["source", "accession", "license"]

#: Patterns that indicate identifiable patient information. A hit blocks the
#: upload outright rather than being reported as a warning.
PII_PATTERNS = [
    ("national_id", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    ("email", re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]{2,}\b")),
    ("date_of_birth", re.compile(r"\b(?:dob|date_of_birth|birth_date)\b", re.I)),
    ("patient_name", re.compile(r"\b(?:patient_name|full_name|surname|first_name)\b", re.I)),
    ("mrn", re.compile(r"\b(?:mrn|medical_record|nhs_number|health_id)\b", re.I)),
    ("address", re.compile(r"\b(?:street_address|postcode|zip_code|home_address)\b", re.I)),
    ("phone", re.compile(r"\b(?:phone|mobile_number|telephone)\b", re.I)),
]


@dataclass
class ValidationResult:
    ok: bool = True
    errors: List[dict] = field(default_factory=list)
    warnings: List[dict] = field(default_factory=list)
    summary: Dict[str, Any] = field(default_factory=dict)

    def fail(self, code: str, message: str) -> None:
        self.ok = False
        self.errors.append({"code": code, "message": message})

    def warn(self, code: str, message: str) -> None:
        self.warnings.append({"code": code, "message": message})

    def as_dict(self) -> dict:
        return {
            "ok": self.ok,
            "errors": self.errors,
            "warnings": self.warnings,
            "summary": self.summary,
        }


def validate_upload(
    *,
    filename: str,
    size_bytes: int,
    track: AnalysisTrack,
    max_bytes: int,
    metadata_rows: Optional[Sequence[dict]] = None,
    provenance: Optional[dict] = None,
    n_matrix_columns: Optional[int] = None,
) -> ValidationResult:
    """Full ingestion gate. Every check runs so the learner sees all problems."""
    result = ValidationResult()
    extension = os.path.splitext(filename.lower())[1]

    if extension in REJECTED_FORMATS:
        result.fail(
            "raw_sequencing_not_supported",
            "Raw sequencing files are not accepted. Upload an analysis-ready "
            "count matrix or expression object instead.",
        )
    elif extension not in ALLOWED_FORMATS[track]:
        result.fail(
            "unsupported_format",
            f"'{extension or filename}' is not a supported format for this "
            f"analysis track. Accepted: "
            f"{', '.join(ALLOWED_FORMATS[track])}.",
        )

    if size_bytes <= 0:
        result.fail("empty_file", "The uploaded file is empty.")
    elif size_bytes > max_bytes:
        result.fail(
            "file_too_large",
            f"The file is {size_bytes} bytes, above the configured limit of "
            f"{max_bytes} bytes.",
        )

    if metadata_rows is not None:
        _validate_metadata(result, track, metadata_rows, n_matrix_columns)

    if provenance is not None:
        missing = [k for k in REQUIRED_PROVENANCE if not provenance.get(k)]
        if missing:
            result.fail(
                "missing_provenance",
                f"Provenance is incomplete. Required: {', '.join(missing)}.",
            )

    return result


def _validate_metadata(
    result: ValidationResult,
    track: AnalysisTrack,
    rows: Sequence[dict],
    n_matrix_columns: Optional[int],
) -> None:
    if not rows:
        result.fail("missing_metadata", "No sample metadata was supplied.")
        return

    pii = scan_for_pii(rows)
    if pii:
        result.fail(
            "identifiable_information",
            "The metadata appears to contain identifiable personal information "
            f"({', '.join(sorted({hit['kind'] for hit in pii}))}). Only public, "
            "teaching or de-identified data may be used on this platform. Remove "
            "the identifying columns and upload again.",
        )

    missing_fields = [
        field for field in REQUIRED_METADATA[track] if not all(field in row for row in rows)
    ]
    if missing_fields:
        result.fail(
            "missing_required_fields",
            f"Every sample needs {', '.join(missing_fields)}.",
        )

    ids = [row.get("sample_id") for row in rows if row.get("sample_id")]
    if len(set(ids)) != len(ids):
        result.fail("duplicate_sample_ids", "Sample identifiers must be unique.")

    if n_matrix_columns is not None and n_matrix_columns != len(rows):
        result.fail(
            "matrix_metadata_mismatch",
            f"The matrix describes {n_matrix_columns} samples but the metadata "
            f"has {len(rows)} rows.",
        )

    result.summary["n_samples"] = len(rows)
    _check_design(result, rows)


def _check_design(result: ValidationResult, rows: Sequence[dict]) -> None:
    """Replication and confounding checks (spec 5.1)."""
    conditions = [row.get("condition") for row in rows if row.get("condition")]
    per_condition: Dict[str, int] = {}
    for condition in conditions:
        per_condition[condition] = per_condition.get(condition, 0) + 1
    result.summary["replicates_per_condition"] = per_condition

    if len(per_condition) < 2:
        result.warn(
            "single_condition",
            "Only one condition is present, so no contrast can be tested. This "
            "dataset supports description, not comparison.",
        )
    for condition, count in per_condition.items():
        if count < 2:
            result.warn(
                "insufficient_replication",
                f"Condition '{condition}' has {count} biological replicate. "
                f"Condition-level statistical claims are not supportable without "
                f"at least two.",
            )

    if all("batch" in row for row in rows) and len(per_condition) > 1:
        pairs = {(row["condition"], row["batch"]) for row in rows}
        batches_per_condition = {}
        for condition, batch in pairs:
            batches_per_condition.setdefault(condition, set()).add(batch)
        all_batches = {batch for _, batch in pairs}
        if len(all_batches) > 1 and all(
            len(batches) == 1 for batches in batches_per_condition.values()
        ):
            result.warn(
                "confounded_batch",
                "Each condition sits entirely within its own batch, so the "
                "condition effect and the batch effect cannot be separated by any "
                "statistical model.",
            )


def scan_for_pii(rows: Sequence[dict]) -> List[dict]:
    """Return every identifiable-information hit found in metadata."""
    hits: List[dict] = []
    for index, row in enumerate(rows):
        for key, value in row.items():
            text = f"{key} {value}"
            for kind, pattern in PII_PATTERNS:
                if pattern.search(text):
                    hits.append({"row": index, "field": key, "kind": kind})
    return hits
