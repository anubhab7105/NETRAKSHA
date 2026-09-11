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
