"""ORM models for the AI Document Screening System.

All 7 entities from Schema.md:
  1. Officer        — authenticated security personnel
  2. CitizenRegistry — official reference identity records
  3. ScreeningCase  — a single document screening event
  4. ExtractedField — per-field OCR extraction with DB reconciliation
  5. ModuleResult   — per-pipeline-module output with evidence
  6. OfficerAction  — human override decisions (clear/deny/escalate)
  7. AuditLog       — append-only immutable event ledger
  + WatchlistEntry  — mocked watchlist records
"""

from __future__ import annotations

import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""
    pass


# ---------------------------------------------------------------------------
# 1. Officer
# ---------------------------------------------------------------------------

class Officer(Base):
    __tablename__ = "officers"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(100), unique=True, nullable=False)
    password_hash = Column(Text, nullable=False)
    role = Column(String(20), nullable=False, default="officer")  # officer | supervisor | auditor
    unit = Column(String(50), nullable=False, default="BORDER_UNIT_1")  # location/unit for least-privilege scoping
    created_at = Column(DateTime, server_default=func.now())
    # --- Auth hardening (password rotation + supervisor MFA) ---
    # Pre-existing databases gain these via database.ensure_auth_columns().
    must_change_password = Column(Boolean, nullable=False, default=False)
    totp_secret = Column(Text, nullable=True)  # base32 secret; set at enrollment
    totp_enabled = Column(Boolean, nullable=False, default=False)
    password_changed_at = Column(DateTime, nullable=True)

    # Relationships
    screening_cases = relationship("ScreeningCase", back_populates="officer")
    officer_actions = relationship("OfficerAction", back_populates="officer")

    def __repr__(self) -> str:
        return f"<Officer(id={self.id}, username={self.username!r}, role={self.role!r})>"


# ---------------------------------------------------------------------------
# 2. CitizenRegistry
# ---------------------------------------------------------------------------

class CitizenRegistry(Base):
    __tablename__ = "citizens_registry"
    __table_args__ = (
        UniqueConstraint("document_type", "document_number", name="uq_citizen_type_number"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    document_type = Column(String(20), nullable=False)  # aadhaar | pan | voter_id | passport
    document_number = Column(String(50), nullable=False)
    full_name = Column(Text, nullable=False)
    date_of_birth = Column(String(20), nullable=True)  # YYYY-MM-DD or DD/MM/YYYY
    gender = Column(String(10), nullable=True)  # M | F | Other
    address = Column(Text, nullable=True)
    father_or_spouse_name = Column(Text, nullable=True)
    photo_uri = Column(Text, nullable=True)  # path/URI to reference photo

    # --- Controlled-enrollment trust metadata (added post-audit) ---
    # Pre-fix rows have NULLs here and are treated as `legacy` (grandfathered
    # but flagged for authority re-verification). All post-fix rows are written
    # only via dual approval or a signed authority import, so these are set.
    # A runtime migration (database.ensure_registry_trust_columns) adds these
    # columns to already-deployed databases on startup.
    source = Column(String(30), nullable=True)  # authority_import | verified_enrollment | legacy_seed
    source_ref = Column(Text, nullable=True)  # authority batch / enrollment reference
    verification_method = Column(String(80), nullable=True)  # e.g. authority_signed_import
    photo_hash = Column(String(64), nullable=True)  # SHA-256 of the enrolled face photo
    enrolled_by = Column(String(100), nullable=True)  # requesting supervisor username
    approved_by = Column(String(100), nullable=True)  # second supervisor (must differ)
    last_reconciled_at = Column(DateTime, nullable=True)
    reconciliation_status = Column(String(30), nullable=True)  # ok | needs_review | ...

    # Relationships
    screening_cases = relationship("ScreeningCase", back_populates="citizen")

    def __repr__(self) -> str:
        return f"<CitizenRegistry(id={self.id}, type={self.document_type!r}, name={self.full_name!r})>"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "document_type": self.document_type,
            "document_number": self.document_number,
            "full_name": self.full_name,
            "date_of_birth": self.date_of_birth,
            "gender": self.gender,
            "address": self.address,
            "father_or_spouse_name": self.father_or_spouse_name,
            "photo_uri": self.photo_uri,
            "source": self.source,
            "source_ref": self.source_ref,
            "verification_method": self.verification_method,
            "photo_hash": self.photo_hash,
            "enrolled_by": self.enrolled_by,
            "approved_by": self.approved_by,
            "last_reconciled_at": self.last_reconciled_at.isoformat() if self.last_reconciled_at else None,
            "reconciliation_status": self.reconciliation_status,
        }


# ---------------------------------------------------------------------------
# 2b. RegistryEnrollment — dual-approval workflow for the master registry
# ---------------------------------------------------------------------------

class RegistryEnrollment(Base):
    """Controlled-enrollment request for the master citizen registry.

    Single-supervisor direct writes to ``citizens_registry`` are closed.
    A supervisor REQUESTS (create or delete); a DIFFERENT supervisor must
    APPROVE (or reject) before anything touches the authoritative table.
    Signed authority imports bypass this queue (the HMAC signature from the
    issuing authority is the second factor) and are recorded as such.
    """

    __tablename__ = "registry_enrollments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    action = Column(String(10), nullable=False, default="create")  # create | delete
    status = Column(String(10), nullable=False, default="pending")  # pending | approved | rejected
    # Proposed payload (for action=create)
    document_type = Column(String(20), nullable=True)
    document_number = Column(String(50), nullable=True)
    full_name = Column(Text, nullable=True)
    date_of_birth = Column(String(20), nullable=True)
    gender = Column(String(10), nullable=True)
    address = Column(Text, nullable=True)
    father_or_spouse_name = Column(Text, nullable=True)
    photo_uri = Column(Text, nullable=True)  # staged pending photo (approved → linked)
    photo_hash = Column(String(64), nullable=True)
    source = Column(String(30), nullable=True)
    source_ref = Column(Text, nullable=True)
    verification_method = Column(String(80), nullable=True)
    request_reason = Column(Text, nullable=True)  # why this enrollment is needed
    review_note = Column(Text, nullable=True)  # approver/rejecter note
    requested_by_id = Column(Integer, ForeignKey("officers.id"), nullable=False)
    requested_by = Column(String(100), nullable=False)
    approved_by_id = Column(Integer, ForeignKey("officers.id"), nullable=True)
    approved_by = Column(String(100), nullable=True)
    target_citizen_id = Column(Integer, ForeignKey("citizens_registry.id"), nullable=True)  # for delete
    resulting_citizen_id = Column(Integer, ForeignKey("citizens_registry.id"), nullable=True)  # for create
    created_at = Column(DateTime, server_default=func.now())
    decided_at = Column(DateTime, nullable=True)

    def __repr__(self) -> str:
        return (
            f"<RegistryEnrollment(id={self.id} action={self.action!r} "
            f"status={self.status!r} doc={self.document_number!r})>"
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "action": self.action,
            "status": self.status,
            "document_type": self.document_type,
            "document_number": self.document_number,
            "full_name": self.full_name,
            "date_of_birth": self.date_of_birth,
            "gender": self.gender,
            "address": self.address,
            "father_or_spouse_name": self.father_or_spouse_name,
            "photo_uri": self.photo_uri,
            "photo_hash": self.photo_hash,
            "source": self.source,
            "source_ref": self.source_ref,
            "verification_method": self.verification_method,
            "request_reason": self.request_reason,
            "review_note": self.review_note,
            "requested_by_id": self.requested_by_id,
            "requested_by": self.requested_by,
            "approved_by_id": self.approved_by_id,
            "approved_by": self.approved_by,
            "target_citizen_id": self.target_citizen_id,
            "resulting_citizen_id": self.resulting_citizen_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "decided_at": self.decided_at.isoformat() if self.decided_at else None,
        }


# ---------------------------------------------------------------------------
# 3. ScreeningCase
# ---------------------------------------------------------------------------

class ScreeningCase(Base):
    __tablename__ = "screening_cases"

    id = Column(Integer, primary_key=True, autoincrement=True)
    officer_id = Column(Integer, ForeignKey("officers.id"), nullable=False)
    timestamp = Column(DateTime, server_default=func.now())
    document_type = Column(String(20), nullable=True)
    citizen_id = Column(Integer, ForeignKey("citizens_registry.id"), nullable=True)
    demographic_match = Column(Boolean, nullable=True)
    risk_score = Column(Float, nullable=True)
    verdict = Column(String(10), nullable=True)  # Green | Yellow | Red
    status = Column(String(20), default="pending_review")  # pending_review | escalated | decided
    unit = Column(String(50), nullable=True)  # officer's unit at screening time for location scoping
    version = Column(Integer, default=0, nullable=False)  # optimistic locking version
    provenance = Column(Text, nullable=True)  # JSON of model/config/input hashes for reproducibility
    provenance_signature = Column(Text, nullable=True)  # HMAC signature of provenance
    challenge_type = Column(String(20), nullable=True)  # active liveness challenge: blink | head_turn | mouth_open | smile

    # Relationships
    officer = relationship("Officer", back_populates="screening_cases")
    citizen = relationship("CitizenRegistry", back_populates="screening_cases")
    extracted_fields = relationship("ExtractedField", back_populates="case", cascade="all, delete-orphan")
    module_results = relationship("ModuleResultDB", back_populates="case", cascade="all, delete-orphan")
    officer_actions = relationship("OfficerAction", back_populates="case", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<ScreeningCase(id={self.id}, verdict={self.verdict!r}, status={self.status!r})>"

    def to_dict(self) -> dict:
        import json as _json
        prov = None
        if self.provenance:
            try:
                prov = _json.loads(self.provenance)
            except Exception:
                prov = self.provenance
        return {
            "id": self.id,
            "officer_id": self.officer_id,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "document_type": self.document_type,
            "citizen_id": self.citizen_id,
            "demographic_match": self.demographic_match,
            "risk_score": self.risk_score,
            "verdict": self.verdict,
            "status": self.status,
            "unit": self.unit,
            "version": self.version or 0,
            "provenance": prov,
            "provenance_signature": self.provenance_signature,
            "challenge_type": self.challenge_type,
        }


# ---------------------------------------------------------------------------
# 4. ExtractedField
# ---------------------------------------------------------------------------

class ExtractedField(Base):
    __tablename__ = "extracted_fields"

    id = Column(Integer, primary_key=True, autoincrement=True)
    case_id = Column(Integer, ForeignKey("screening_cases.id"), nullable=False)
    field_name = Column(String(50), nullable=False)
    extracted_value = Column(Text, nullable=True)
    database_value = Column(Text, nullable=True)
    match_status = Column(String(20), nullable=False, default="unverified")  # match | mismatch | unverified
    confidence = Column(Float, nullable=True)

    # Relationships
    case = relationship("ScreeningCase", back_populates="extracted_fields")

    def __repr__(self) -> str:
        return f"<ExtractedField(id={self.id}, field={self.field_name!r}, status={self.match_status!r})>"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "case_id": self.case_id,
            "field_name": self.field_name,
            "extracted_value": self.extracted_value,
            "database_value": self.database_value,
            "match_status": self.match_status,
            "confidence": self.confidence,
        }


# ---------------------------------------------------------------------------
# 5. ModuleResult (DB model — distinct from pipeline.common.ModuleResult)
# ---------------------------------------------------------------------------

class ModuleResultDB(Base):
    __tablename__ = "module_results"

    id = Column(Integer, primary_key=True, autoincrement=True)
    case_id = Column(Integer, ForeignKey("screening_cases.id"), nullable=False)
    module_name = Column(String(50), nullable=False)
    score = Column(Float, nullable=True)
    status = Column(String(20), nullable=False, default="ok")  # ok | inconclusive
    raw_output = Column(Text, nullable=True)  # JSON string
    evidence_uri = Column(Text, nullable=True)
    is_mocked = Column(Boolean, default=False)

    # Relationships
    case = relationship("ScreeningCase", back_populates="module_results")

    def __repr__(self) -> str:
        return f"<ModuleResultDB(id={self.id}, module={self.module_name!r}, status={self.status!r})>"

    def to_dict(self) -> dict:
        import json
        raw = None
        if self.raw_output:
            try:
                raw = json.loads(self.raw_output)
            except (json.JSONDecodeError, TypeError):
                raw = self.raw_output
        return {
            "id": self.id,
            "case_id": self.case_id,
            "module_name": self.module_name,
            "score": self.score,
            "status": self.status,
            "raw_output": raw,
            "evidence_uri": self.evidence_uri,
            "is_mocked": self.is_mocked,
        }


# ---------------------------------------------------------------------------
# 6. OfficerAction
# ---------------------------------------------------------------------------

class OfficerAction(Base):
    __tablename__ = "officer_actions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    case_id = Column(Integer, ForeignKey("screening_cases.id"), nullable=False)
    officer_id = Column(Integer, ForeignKey("officers.id"), nullable=False)
    action = Column(String(20), nullable=False)  # clear | deny | escalate
    reason = Column(Text, nullable=False)
    timestamp = Column(DateTime, server_default=func.now())

    # Relationships
    case = relationship("ScreeningCase", back_populates="officer_actions")
    officer = relationship("Officer", back_populates="officer_actions")

    def __repr__(self) -> str:
        return f"<OfficerAction(id={self.id}, action={self.action!r})>"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "case_id": self.case_id,
            "officer_id": self.officer_id,
            "action": self.action,
            "reason": self.reason,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
        }


# ---------------------------------------------------------------------------
# 7. AuditLog
# ---------------------------------------------------------------------------

class AuditLog(Base):
    __tablename__ = "audit_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    actor = Column(String(100), nullable=False)  # officer username or "system"
    action = Column(Text, nullable=False)
    entity = Column(String(100), nullable=True)  # e.g. "case:42"
    timestamp = Column(DateTime, server_default=func.now())
    immutable = Column(Boolean, default=True)
    # Enriched attribution for screening events
    officer_id = Column(Integer, nullable=True)  # FK to officers.id when actor is an officer
    session_id = Column(String(100), nullable=True)  # JWT jti or session token ID
    request_id = Column(String(100), nullable=True)  # per-request UUID for tracing
    device_info = Column(Text, nullable=True)  # User-Agent + IP + location context
    file_hashes = Column(Text, nullable=True)  # JSON of input file hashes (doc/live)
    prev_hash = Column(String(64), nullable=True)  # hash chain: previous entry_hash
    entry_hash = Column(String(64), nullable=True)  # HMAC of this entry

    def __repr__(self) -> str:
        return f"<AuditLog(id={self.id}, actor={self.actor!r}, action={self.action!r})>"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "actor": self.actor,
            "action": self.action,
            "entity": self.entity,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "immutable": self.immutable,
            "officer_id": self.officer_id,
            "session_id": self.session_id,
            "request_id": self.request_id,
            "device_info": self.device_info,
            "file_hashes": self.file_hashes,
        }


# ---------------------------------------------------------------------------
# 8. IdempotencyRecord — duplicate-submission guard for POST /api/screen
# ---------------------------------------------------------------------------

class IdempotencyRecord(Base):
    """Deduplicates screening requests across network retries.

    Scope (per fix spec): authenticated officer + capture session (JWT jti)
    + input hash (SHA-256 over input file hashes) + client idempotency key.

    * (officer_id, idempotency_key) is UNIQUE — same key replayed with a
      different payload/session is rejected with 422.
    * Same officer + session + input hash within a short window suppresses
      double-click duplicates even when the client generated a fresh key.
    * New table (not a column addition) so deployed DBs pick it up via
      ``create_all`` on next restart with no manual migration.
    """

    __tablename__ = "screening_idempotency"
    __table_args__ = (
        UniqueConstraint("officer_id", "idempotency_key", name="uq_idempotency_officer_key"),
        Index("ix_idempotency_officer_session_hash", "officer_id", "session_id", "input_hash"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    idempotency_key = Column(String(128), nullable=False)
    officer_id = Column(Integer, ForeignKey("officers.id"), nullable=False)
    session_id = Column(String(100), nullable=True, default="")
    input_hash = Column(String(64), nullable=False)
    case_id = Column(Integer, ForeignKey("screening_cases.id"), nullable=True)
    response_snapshot = Column(Text, nullable=True)  # JSON of the original screening result
    created_at = Column(DateTime, server_default=func.now())

    def __repr__(self) -> str:
        return (
            f"<IdempotencyRecord(officer={self.officer_id} "
            f"key={self.idempotency_key!r} case={self.case_id})>"
        )


# ---------------------------------------------------------------------------
# WatchlistEntry (mocked — per Schema.md)
# ---------------------------------------------------------------------------

class WatchlistEntry(Base):
    __tablename__ = "watchlist_entries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(Text, nullable=False)
    id_number = Column(String(50), nullable=True)
    flag_reason = Column(Text, nullable=True)

    def __repr__(self) -> str:
        return f"<WatchlistEntry(id={self.id}, name={self.name!r})>"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "id_number": self.id_number,
            "flag_reason": self.flag_reason,
        }
