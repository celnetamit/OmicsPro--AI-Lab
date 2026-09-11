"""Persistence layer.

Every run record here is designed to be fully reconstructable after the fact —
dataset, method version, parameters, learner decisions and the AI interaction
log (spec 10, 14.6).
"""

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.constants import (
    AccessTier,
    AnalysisTrack,
    AuditAction,
    InterpretationLabel,
    RunStatus,
)


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.utcnow()


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(200), default="")
    password_hash: Mapped[str] = mapped_column(String(255))
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    entitlements: Mapped[list["Entitlement"]] = relationship(back_populates="user")
    enrollments: Mapped[list["Enrollment"]] = relationship(back_populates="user")


class Enrollment(Base):
    """Flagship-program enrollment. Basic is auto-granted off this record."""

    __tablename__ = "enrollments"
    __table_args__ = (UniqueConstraint("user_id", "program_code"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    program_code: Mapped[str] = mapped_column(String(64), default="flagship-8w")
    cohort: Mapped[str] = mapped_column(String(64), default="")
    current_week: Mapped[int] = mapped_column(Integer, default=1)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    enrolled_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    user: Mapped[User] = relationship(back_populates="enrollments")


class Entitlement(Base):
    """A commercial access grant. Expiry never deletes prior reports (spec 2)."""

    __tablename__ = "entitlements"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    tier: Mapped[AccessTier] = mapped_column(String(16))
    source: Mapped[str] = mapped_column(String(32), default="enrollment_auto_grant")
    granted_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    granted_by: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    note: Mapped[str] = mapped_column(Text, default="")

    user: Mapped[User] = relationship(back_populates="entitlements")

    def is_active(self, at: Optional[datetime] = None) -> bool:
        at = at or _now()
        if self.revoked_at is not None and self.revoked_at <= at:
            return False
        if self.expires_at is not None and self.expires_at <= at:
            return False
        return self.granted_at <= at


class Dataset(Base):
    """Guided / trial / uploaded dataset with mandatory provenance (spec 6)."""

    __tablename__ = "datasets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    slug: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    track: Mapped[AnalysisTrack] = mapped_column(String(16), index=True)
    kind: Mapped[str] = mapped_column(String(16), default="guided")  # guided|trial|upload
    #: Provenance (spec 6): all four are required before a dataset is selectable.
    source: Mapped[str] = mapped_column(String(200), default="")
    accession: Mapped[str] = mapped_column(String(64), default="")
    citation: Mapped[str] = mapped_column(Text, default="")
    license: Mapped[str] = mapped_column(String(120), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    storage_path: Mapped[str] = mapped_column(String(500), default="")
    file_format: Mapped[str] = mapped_column(String(32), default="")
    owner_id: Mapped[Optional[str]] = mapped_column(ForeignKey("users.id"), nullable=True)
    imported_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    validation_status: Mapped[str] = mapped_column(String(24), default="pending")
    validation_report: Mapped[dict] = mapped_column(JSON, default=dict)
    supported_modules: Mapped[list] = mapped_column(JSON, default=list)
    #: Scientific limitations the UI must surface with every result from it,
    #: e.g. single-section spatial data being descriptive only (spec 4.3).
    limitations: Mapped[list] = mapped_column(JSON, default=list)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    retention_days: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)


class DesignPlan(Base):
    """Week 1 Experimental Design Studio output artifact (spec 5.1)."""

    __tablename__ = "design_plans"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    brief_id: Mapped[str] = mapped_column(String(64))
    biological_question: Mapped[str] = mapped_column(Text, default="")
    condition_structure: Mapped[str] = mapped_column(Text, default="")
    sample_structure: Mapped[str] = mapped_column(Text, default="")
    decision_goal: Mapped[str] = mapped_column(Text, default="")
    chosen_assay: Mapped[str] = mapped_column(String(64), default="")
    assay_justification: Mapped[str] = mapped_column(Text, default="")
    #: Sample rows from the Metadata Builder.
    samples: Mapped[list] = mapped_column(JSON, default=list)
    #: Replication / confounding warnings raised at analysis-entry selection.
    design_warnings: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)


class Run(Base):
    """One pipeline execution. Immutable once completed."""

    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    dataset_id: Mapped[str] = mapped_column(ForeignKey("datasets.id"), index=True)
    track: Mapped[AnalysisTrack] = mapped_column(String(16))
    #: Extension pipeline this run executed, if it was not the track's guided
    #: workflow (for example "core_communication"). Empty means the guided one.
    module: Mapped[str] = mapped_column(String(64), default="")
    program_code: Mapped[str] = mapped_column(String(64), default="flagship-8w")
    week: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    #: Tier at execution time — entitlement changes must not rewrite history.
    access_tier: Mapped[AccessTier] = mapped_column(String(16))
    pipeline_version: Mapped[str] = mapped_column(String(64))
    method_versions: Mapped[dict] = mapped_column(JSON, default=dict)
    parameters: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[RunStatus] = mapped_column(String(16), default=RunStatus.QUEUED, index=True)
    #: Perturbation lineage: the original run is always recoverable (spec 10).
    parent_run_id: Mapped[Optional[str]] = mapped_column(ForeignKey("runs.id"), nullable=True)
    is_original: Mapped[bool] = mapped_column(Boolean, default=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    outputs: Mapped[dict] = mapped_column(JSON, default=dict)
    #: Last successfully completed step, preserved when a later step fails.
    last_valid_step: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str] = mapped_column(Text, default="")
    error_detail: Mapped[str] = mapped_column(Text, default="")
    #: The most recent report generated from this run (spec 11). A plain
    #: column rather than a foreign key: reports already reference their run,
    #: and a key in both directions makes the two tables impossible to create
    #: or drop in either order.
    report_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class Perturbation(Base):
    """A TEST/SKIP offer and its EXPECTED-vs-ACTUAL reconciliation (spec 8.1)."""

    __tablename__ = "perturbations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), index=True)
    parameter_key: Mapped[str] = mapped_column(String(64))
    from_value: Mapped[dict] = mapped_column(JSON, default=dict)
    to_value: Mapped[dict] = mapped_column(JSON, default=dict)
    scientific_reason: Mapped[str] = mapped_column(Text)
    evidence_source_ids: Mapped[list] = mapped_column(JSON, default=list)
    #: Direction/effect only — never a promised numeric result (spec 8.1).
    expected_consequence: Mapped[dict] = mapped_column(JSON, default=dict)
    what_to_observe: Mapped[str] = mapped_column(Text, default="")
    limitation: Mapped[str] = mapped_column(Text, default="")
    decision: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)  # test|skip
    decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    alternate_run_id: Mapped[Optional[str]] = mapped_column(ForeignKey("runs.id"), nullable=True)
    #: Persisted comparison artifact, generated after the alternate run ends.
    actual_outcome: Mapped[dict] = mapped_column(JSON, default=dict)
    divergence_explanation: Mapped[str] = mapped_column(Text, default="")
    matched_expectation: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class EvidenceSource(Base):
    """Approved evidence registry. The Copilot may cite nothing outside it."""

    __tablename__ = "evidence_sources"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source_type: Mapped[str] = mapped_column(String(32))  # dataset|publication|method|docs|database
    title: Mapped[str] = mapped_column(Text)
    reference: Mapped[str] = mapped_column(Text)  # accession, DOI or URL
    summary: Mapped[str] = mapped_column(Text, default="")
    approved: Mapped[bool] = mapped_column(Boolean, default=True)
    added_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class AiInteraction(Base):
    """Every Copilot output, with the evidence it was traceable to."""

    __tablename__ = "ai_interactions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    run_id: Mapped[Optional[str]] = mapped_column(ForeignKey("runs.id"), nullable=True, index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    function: Mapped[str] = mapped_column(String(32))  # explain|recommend|interpret|challenge...
    step: Mapped[str] = mapped_column(String(64), default="")
    prompt_context: Mapped[dict] = mapped_column(JSON, default=dict)
    output: Mapped[dict] = mapped_column(JSON, default=dict)
    evidence_source_ids: Mapped[list] = mapped_column(JSON, default=list)
    #: Keys of computed pipeline outputs this response was grounded in.
    computed_refs: Mapped[list] = mapped_column(JSON, default=list)
    interpretation_label: Mapped[Optional[InterpretationLabel]] = mapped_column(
        String(24), nullable=True
    )
    label_rationale: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class AuditRecord(Base):
    """Learner adjudication of one AI output (spec 5.3). Append-only."""

    __tablename__ = "audit_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    interaction_id: Mapped[str] = mapped_column(ForeignKey("ai_interactions.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    action: Mapped[AuditAction] = mapped_column(String(24))
    learner_rationale: Mapped[str] = mapped_column(Text, default="")
    final_interpretation: Mapped[str] = mapped_column(Text, default="")
    #: Learner may revise the label; the AI's original record stays immutable.
    revised_label: Mapped[Optional[InterpretationLabel]] = mapped_column(String(24), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class Interpretation(Base):
    """Four-field interpretation record, separated in UI and report (spec 9.10)."""

    __tablename__ = "interpretations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    step: Mapped[str] = mapped_column(String(64), default="")
    observation: Mapped[str] = mapped_column(Text, default="")
    statistical_evidence: Mapped[str] = mapped_column(Text, default="")
    biological_interpretation: Mapped[str] = mapped_column(Text, default="")
    hypothesis: Mapped[str] = mapped_column(Text, default="")
    label: Mapped[Optional[InterpretationLabel]] = mapped_column(String(24), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), index=True)
    #: Tier the report was generated under; retained after expiry (spec 2).
    generated_tier: Mapped[AccessTier] = mapped_column(String(16))
    export_format: Mapped[str] = mapped_column(String(32))
    content: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class Purchase(Base):
    """A paid tier activation (spec 12 Phase 2).

    The platform records the order and activates the entitlement; it does not
    hold card data. ``provider_reference`` is the identifier returned by the
    payment provider, which is the only thing worth storing here.
    """

    __tablename__ = "purchases"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    tier: Mapped[AccessTier] = mapped_column(String(16))
    term_days: Mapped[int] = mapped_column(Integer, default=90)
    amount_minor_units: Mapped[int] = mapped_column(Integer, default=0)
    currency: Mapped[str] = mapped_column(String(8), default="INR")
    provider: Mapped[str] = mapped_column(String(32), default="manual")
    provider_reference: Mapped[str] = mapped_column(String(120), default="")
    status: Mapped[str] = mapped_column(String(24), default="pending")
    entitlement_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("entitlements.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    activated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class Capstone(Base):
    """Week 8 capstone workspace (spec 3, 9.12, 12 Phase 3)."""

    __tablename__ = "capstones"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(300), default="")
    research_question: Mapped[str] = mapped_column(Text, default="")
    approach: Mapped[str] = mapped_column(Text, default="")
    #: Run ids the capstone draws on, in the order they should be presented.
    run_ids: Mapped[list] = mapped_column(JSON, default=list)
    #: Figures selected for the figure pack: run id, output key, caption.
    figures: Mapped[list] = mapped_column(JSON, default=list)
    findings: Mapped[list] = mapped_column(JSON, default=list)
    limitations: Mapped[list] = mapped_column(JSON, default=list)
    future_work: Mapped[str] = mapped_column(Text, default="")
    submitted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    #: Final defence score, computed from the record at submission (spec 13).
    #: Null until submitted; the breakdown states what each part measured.
    defence_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    defence_breakdown: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)


class AssessmentResult(Base):
    __tablename__ = "assessment_results"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    assessment_id: Mapped[str] = mapped_column(String(64))
    week: Mapped[int] = mapped_column(Integer, default=1)
    responses: Mapped[dict] = mapped_column(JSON, default=dict)
    score: Mapped[float] = mapped_column(Float, default=0.0)
    recommended_topics: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class ModuleFlag(Base):
    """Admin enable/disable of a module per cohort or phase (spec 11)."""

    __tablename__ = "module_flags"
    __table_args__ = (UniqueConstraint("module_key", "cohort"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    module_key: Mapped[str] = mapped_column(String(64), index=True)
    cohort: Mapped[str] = mapped_column(String(64), default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    note: Mapped[str] = mapped_column(Text, default="")


class AdminSetting(Base):
    """Runtime-editable settings (retention, upload caps) — spec 6, 11."""

    __tablename__ = "admin_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)
    updated_by: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)


class IssueReport(Base):
    """A problem a learner reported from inside the lab (spec 14).

    The admin console reviews these alongside the AI audit records. The screen
    and, where there is one, the run are captured so a report can be reproduced
    rather than only read.
    """

    __tablename__ = "issue_reports"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    run_id: Mapped[Optional[str]] = mapped_column(ForeignKey("runs.id"), nullable=True, index=True)
    screen: Mapped[str] = mapped_column(String(128), default="")
    #: scientific | technical | content | access | other
    category: Mapped[str] = mapped_column(String(32), default="other")
    message: Mapped[str] = mapped_column(Text)
    #: open | acknowledged | resolved
    status: Mapped[str] = mapped_column(String(16), default="open", index=True)
    admin_note: Mapped[str] = mapped_column(Text, default="")
    resolved_by: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
