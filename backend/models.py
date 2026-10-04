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
    CheckConstraint,
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






class Officer(Base):
    __tablename__ = "officers"
    __table_args__ = (
        CheckConstraint("role IN ('officer', 'supervisor', 'auditor')", name="ck_officer_role"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(100), unique=True, nullable=False)
    password_hash = Column(Text, nullable=False)
    role = Column(String(20), nullable=False, default="officer")
    unit = Column(String(50), nullable=False, default="BORDER_UNIT_1")
    created_at = Column(DateTime, server_default=func.now())


    must_change_password = Column(Boolean, nullable=False, default=False)
    # Audit C6: Fernet-encrypted ("enc:v1:…") via encrypt_totp_secret();
    # legacy plaintext rows are still accepted on read and upgraded on verify.
    totp_secret = Column(Text, nullable=True)
    totp_enabled = Column(Boolean, nullable=False, default=False)
    password_changed_at = Column(DateTime, nullable=True)


    screening_cases = relationship("ScreeningCase", back_populates="officer")
    officer_actions = relationship("OfficerAction", back_populates="officer")

    def __repr__(self) -> str:
        return f"<Officer(id={self.id}, username={self.username!r}, role={self.role!r})>"






class CitizenRegistry(Base):
    __tablename__ = "citizens_registry"
    __table_args__ = (
        UniqueConstraint("document_type", "document_number", name="uq_citizen_type_number"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    document_type = Column(String(20), nullable=False)
    document_number = Column(String(50), nullable=False)
    full_name = Column(Text, nullable=False)
    date_of_birth = Column(String(20), nullable=True)
    gender = Column(String(10), nullable=True)
    address = Column(Text, nullable=True)
    father_or_spouse_name = Column(Text, nullable=True)
    photo_uri = Column(Text, nullable=True)







    source = Column(String(30), nullable=True)
    source_ref = Column(Text, nullable=True)
    verification_method = Column(String(80), nullable=True)
    photo_hash = Column(String(64), nullable=True)
    enrolled_by = Column(String(100), nullable=True)
    approved_by = Column(String(100), nullable=True)
    last_reconciled_at = Column(DateTime, nullable=True)
    reconciliation_status = Column(String(30), nullable=True)


    screening_cases = relationship("ScreeningCase", back_populates="citizen")
    iris_templates = relationship("IrisTemplate", back_populates="citizen", cascade="all, delete-orphan")

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
    action = Column(String(10), nullable=False, default="create")
    status = Column(String(10), nullable=False, default="pending")

    document_type = Column(String(20), nullable=True)
    document_number = Column(String(50), nullable=True)
    full_name = Column(Text, nullable=True)
    date_of_birth = Column(String(20), nullable=True)
    gender = Column(String(10), nullable=True)
    address = Column(Text, nullable=True)
    father_or_spouse_name = Column(Text, nullable=True)
    photo_uri = Column(Text, nullable=True)
    photo_hash = Column(String(64), nullable=True)
    source = Column(String(30), nullable=True)
    source_ref = Column(Text, nullable=True)
    verification_method = Column(String(80), nullable=True)
    request_reason = Column(Text, nullable=True)
    review_note = Column(Text, nullable=True)
    requested_by_id = Column(Integer, ForeignKey("officers.id"), nullable=False)
    requested_by = Column(String(100), nullable=False)
    approved_by_id = Column(Integer, ForeignKey("officers.id"), nullable=True)
    approved_by = Column(String(100), nullable=True)
    target_citizen_id = Column(Integer, ForeignKey("citizens_registry.id"), nullable=True)
    resulting_citizen_id = Column(Integer, ForeignKey("citizens_registry.id"), nullable=True)
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






class ScreeningCase(Base):
    __tablename__ = "screening_cases"
    __table_args__ = (
        Index("ix_screening_cases_officer", "officer_id"),
        Index("ix_screening_cases_unit", "unit"),
        Index("ix_screening_cases_status", "status"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    officer_id = Column(Integer, ForeignKey("officers.id"), nullable=False)
    timestamp = Column(DateTime, server_default=func.now())
    document_type = Column(String(20), nullable=True)
    citizen_id = Column(Integer, ForeignKey("citizens_registry.id"), nullable=True)
    demographic_match = Column(Boolean, nullable=True)
    risk_score = Column(Float, nullable=True)
    verdict = Column(String(10), nullable=True)
    status = Column(String(20), default="pending_review")
    unit = Column(String(50), nullable=True)
    version = Column(Integer, default=0, nullable=False)
    provenance = Column(Text, nullable=True)
    provenance_signature = Column(Text, nullable=True)
    challenge_type = Column(String(20), nullable=True)


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






class ExtractedField(Base):
    __tablename__ = "extracted_fields"

    id = Column(Integer, primary_key=True, autoincrement=True)
    case_id = Column(Integer, ForeignKey("screening_cases.id"), nullable=False)
    field_name = Column(String(50), nullable=False)
    extracted_value = Column(Text, nullable=True)
    database_value = Column(Text, nullable=True)
    match_status = Column(String(20), nullable=False, default="unverified")
    confidence = Column(Float, nullable=True)


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






class IrisTemplate(Base):
    __tablename__ = "iris_templates"

    id = Column(Integer, primary_key=True, autoincrement=True)
    citizen_id = Column(Integer, ForeignKey("citizens_registry.id"), nullable=False)
    # Audit C5: Fernet-encrypted ("enc:v1:…") via _encrypt_template();
    # legacy "sig:b64" HMAC rows are still verified on read.
    template = Column(Text, nullable=False)
    mask = Column(Text, nullable=True)
    quality = Column(Float, nullable=True)
    eye = Column(String(10), nullable=False, default="left")
    created_at = Column(DateTime, server_default=func.now())
    enrolled_by = Column(Integer, ForeignKey("officers.id"), nullable=True)

    citizen = relationship("CitizenRegistry", back_populates="iris_templates")
    officer = relationship("Officer")

    def to_dict(self, include_template: bool = False) -> dict:
        d = {
            "id": self.id,
            "citizen_id": self.citizen_id,
            "quality": self.quality,
            "eye": self.eye,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "enrolled_by": self.enrolled_by,
        }
        if include_template:

            d["template"] = "***REDACTED***"
        return d






class ModuleResultDB(Base):
    __tablename__ = "module_results"
    __table_args__ = (
        Index("ix_module_results_case", "case_id"),
        Index("ix_module_results_evidence_uri", "evidence_uri"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    case_id = Column(Integer, ForeignKey("screening_cases.id"), nullable=False)
    module_name = Column(String(50), nullable=False)
    score = Column(Float, nullable=True)
    status = Column(String(20), nullable=False, default="ok")
    raw_output = Column(Text, nullable=True)
    evidence_uri = Column(Text, nullable=True)
    is_mocked = Column(Boolean, default=False)


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






class RevokedToken(Base):
    """Deny-list for logged-out / rotated JWT sessions (checked in _auth).

    jti = the JWT ID minted in _create_token. Rows are pruned once past
    expires_at so the table stays tiny. Created via create_all on startup
    (no manual migration).
    """

    __tablename__ = "revoked_tokens"

    jti = Column(String(64), primary_key=True)
    officer_id = Column(Integer, ForeignKey("officers.id"), nullable=True)
    reason = Column(String(40), nullable=True)
    revoked_at = Column(DateTime, server_default=func.now())
    expires_at = Column(DateTime, nullable=True)

    def __repr__(self) -> str:
        return f"<RevokedToken(jti={self.jti!r} reason={self.reason!r})>"


class OfficerAction(Base):
    __tablename__ = "officer_actions"
    id = Column(Integer, primary_key=True, autoincrement=True)
    case_id = Column(Integer, ForeignKey("screening_cases.id"), nullable=False)
    officer_id = Column(Integer, ForeignKey("officers.id"), nullable=False)
    action = Column(String(20), nullable=False)
    reason = Column(Text, nullable=False)
    timestamp = Column(DateTime, server_default=func.now())


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






class AuditLog(Base):
    __tablename__ = "audit_log"
    __table_args__ = (
        Index("ix_audit_log_actor", "actor"),
        Index("ix_audit_log_action", "action"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    # Audit C11: free-text audit columns are Text (never String(100)) so
    # overlong entity/session/request values cannot 500 the request.
    # create_with_chain() still clips writer-controlled values for
    # backward compatibility with legacy VARCHAR(100) databases.
    actor = Column(Text, nullable=False)
    action = Column(Text, nullable=False)
    entity = Column(Text, nullable=True)
    timestamp = Column(DateTime, server_default=func.now())
    immutable = Column(Boolean, default=True)

    officer_id = Column(Integer, nullable=True)
    session_id = Column(Text, nullable=True)
    request_id = Column(Text, nullable=True)
    device_info = Column(Text, nullable=True)
    file_hashes = Column(Text, nullable=True)
    prev_hash = Column(String(64), nullable=True)
    entry_hash = Column(String(64), nullable=True)

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
            "prev_hash": self.prev_hash,
            "entry_hash": self.entry_hash,
        }

    @staticmethod
    async def create_with_chain(session, **kwargs):
        """Create an audit log entry with hash chaining.

        All route writes must go through here (never bare ``AuditLog(...)``)
        so every row carries prev_hash/entry_hash. The tail-row read takes
        ``FOR UPDATE`` on PostgreSQL to serialize concurrent writers;
        SQLite has no row locks, so it falls back to a plain read (the
        single-process dev server never races). String fields are truncated
        to their column widths so overlong entities cannot 500 the request.
        """
        import hashlib, hmac

        def _clip(value, limit):
            if value is None:
                return None
            text = value if isinstance(value, str) else str(value)
            return text[:limit]

        kwargs["actor"] = _clip(kwargs.get("actor", "unknown") or "unknown", 100)
        kwargs["entity"] = _clip(kwargs.get("entity"), 100)
        kwargs["session_id"] = _clip(kwargs.get("session_id"), 100)
        kwargs["request_id"] = _clip(kwargs.get("request_id"), 100)

        try:
            from sqlalchemy import select as _select

            query = _select(AuditLog).order_by(AuditLog.id.desc()).limit(1)
            try:
                dialect = getattr(session.get_bind(), "dialect", None)
                if getattr(dialect, "name", "") == "postgresql":
                    query = query.with_for_update()
            except Exception:
                pass
            result = await session.execute(query)
            last = result.scalar_one_or_none()
            prev_hash = last.entry_hash if last and last.entry_hash else "0" * 64
        except Exception:
            prev_hash = "0" * 64

        try:
            from backend.auth_security import audit_secret as _audit_secret

            secret = _audit_secret()
            payload = f"{prev_hash}{kwargs.get('actor','')}{kwargs.get('action','')}{kwargs.get('entity','')}".encode()
            entry_hash = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
        except RuntimeError:
            raise
        except Exception:
            entry_hash = None
        kwargs["prev_hash"] = prev_hash
        kwargs["entry_hash"] = entry_hash
        entry = AuditLog(**kwargs)
        session.add(entry)
        return entry






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
    response_snapshot = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now())

    def __repr__(self) -> str:
        return (
            f"<IdempotencyRecord(officer={self.officer_id} "
            f"key={self.idempotency_key!r} case={self.case_id})>"
        )






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
