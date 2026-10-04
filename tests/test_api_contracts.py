"""API contract tests (H2) — /screen idempotency, RBAC overrides, audit chain,
HMAC registry import, signed evidence bounds, Aadhaar masking.

Isolated `:memory:` SQLite per test (monkeypatched ``app.async_session``,
same pattern as ``tests/test_auth_security.py``). The heavy screening
pipeline (OCR / CV / Gemini) is mocked — these tests pin API contracts
(status codes, replay shapes, RBAC matrix), never forensic scores.
Fast and deterministic: no network, no model downloads, tiny fake uploads.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import io
import json
import uuid

import pytest

import backend.app as app
from backend.models import (
    AuditLog,
    Base,
    CitizenRegistry,
    ExtractedField,
    IdempotencyRecord,
    ModuleResultDB,
    Officer,
    ScreeningCase,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

DOC_A = b"\x89PNG\r\n\x1a\n" + b"A" * 128
DOC_B = b"\x89PNG\r\n\x1a\n" + b"B" * 128

_FAKE_RESULT = {
    "case_id": 777001,
    "document_type": "passport",
    "risk_assessment": {"verdict": "Green", "risk_score": 0.1},
    "module_results": [],
    "extracted_fields": [],
}

from passlib.context import CryptContext as _Ctx

_PWD_HASH = _Ctx(schemes=["bcrypt"], deprecated="auto").hash("Test-Pass-123!")


class _Req:
    def __init__(self, headers=None, cookies=None):
        self.headers = headers or {}
        self.cookies = cookies or {}
        self.client = None


class _ImportReq(_Req):
    def __init__(self, body: bytes, headers):
        super().__init__(headers=headers)
        self._body = body

    async def body(self):  # FastAPI Request.body()
        return self._body


def _upload(data: bytes, filename: str = "doc.png"):
    from fastapi import UploadFile
    from starlette.datastructures import Headers

    return UploadFile(
        file=io.BytesIO(bytes(data)),
        filename=filename,
        headers=Headers({"content-type": "image/png"}),
    )


def _bearer(token: str, extra: dict | None = None) -> dict:
    headers = {"Authorization": f"Bearer {token}"}
    if extra:
        headers.update(extra)
    return headers


async def _seed_officers(maker) -> dict:
    async with maker() as s:
        s.add(Officer(username="off1", password_hash=_PWD_HASH,
                      role="officer", unit="BORDER_UNIT_1",
                      must_change_password=False, totp_enabled=False))
        s.add(Officer(username="sup1", password_hash=_PWD_HASH,
                      role="supervisor", unit="BORDER_UNIT_1",
                      must_change_password=False, totp_enabled=True))
        s.add(Officer(username="aud1", password_hash=_PWD_HASH,
                      role="auditor", unit="HQ",
                      must_change_password=False, totp_enabled=False))
        await s.commit()
        rows = (await s.execute(select(Officer))).scalars().all()
        return {o.username: o for o in rows}


def _token(officer: Officer) -> str:
    return app._create_token(officer.id, officer.username, officer.role,
                             officer.unit or "BORDER_UNIT_1")


def _run(coro_factory):
    async def go():
        eng = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with eng.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        maker = async_sessionmaker(eng, class_=AsyncSession, expire_on_commit=False)
        old_session = app.async_session
        old_pipeline = app._run_screening_pipeline

        async def _fake_pipeline(*args, **kwargs):
            return dict(_FAKE_RESULT)

        app.async_session = maker
        app._run_screening_pipeline = _fake_pipeline
        try:
            officers = await _seed_officers(maker)
            return await coro_factory(maker, officers)
        finally:
            app.async_session = old_session
            app._run_screening_pipeline = old_pipeline
            await eng.dispose()

    return asyncio.run(go())


async def _make_case(maker, officer: Officer, verdict: str = "Green",
                     status: str = "pending_review", version: int = 0,
                     unit: str | None = None) -> int:
    async with maker() as s:
        case = ScreeningCase(
            officer_id=officer.id,
            document_type="passport",
            verdict=verdict,
            status=status,
            risk_score=0.1,
            unit=unit if unit is not None else (officer.unit or "BORDER_UNIT_1"),
            version=version,
        )
        s.add(case)
        await s.commit()
        await s.refresh(case)
        return case.id


# ---------------------------------------------------------------------------
# /screen idempotency matrix
# ---------------------------------------------------------------------------

def test_screen_same_key_same_input_replay():
    async def go(maker, officers):
        tok = _token(officers["off1"])
        key = str(uuid.uuid4())
        headers = _bearer(tok, {"Idempotency-Key": key})
        first = await app.screen_document(_Req(headers=dict(headers)), _upload(DOC_A),
                                          None, None, None, None, None)
        assert first["case_id"] == 777001
        assert first.get("deduplicated") is False
        second = await app.screen_document(_Req(headers=dict(headers)), _upload(DOC_A),
                                           None, None, None, None, None)
        assert second.get("deduplicated") is True
        assert second["case_id"] == first["case_id"]

    _run(go)


def test_screen_same_key_different_input_422():
    async def go(maker, officers):
        tok = _token(officers["off1"])
        key = str(uuid.uuid4())
        headers = _bearer(tok, {"Idempotency-Key": key})
        first = await app.screen_document(_Req(headers=dict(headers)), _upload(DOC_A),
                                          None, None, None, None, None)
        assert first["case_id"] == 777001
        with pytest.raises(Exception) as exc:
            await app.screen_document(_Req(headers=dict(headers)), _upload(DOC_B),
                                      None, None, None, None, None)
        assert getattr(exc.value, "status_code", None) == 422

    _run(go)


def test_screen_inflight_409():
    async def go(maker, officers):
        off = officers["off1"]
        tok = _token(off)
        payload = app._decode_token(tok)
        session_id = payload.get("jti") or ""
        key = str(uuid.uuid4())
        file_hashes = {"document": hashlib.sha256(DOC_A).hexdigest()}
        input_hash = app._compute_input_hash(file_hashes)
        async with maker() as s:
            s.add(IdempotencyRecord(
                idempotency_key=key, officer_id=off.id,
                session_id=session_id or "", input_hash=input_hash,
                case_id=None,
            ))
            await s.commit()
        with pytest.raises(Exception) as exc:
            await app.screen_document(
                _Req(headers=_bearer(tok, {"Idempotency-Key": key})),
                _upload(DOC_A), None, None, None, None, None)
        assert getattr(exc.value, "status_code", None) == 409

    _run(go)


def test_screen_same_input_different_key_duplicate_of_key():
    async def go(maker, officers):
        tok = _token(officers["off1"])
        key1, key2 = str(uuid.uuid4()), str(uuid.uuid4())
        first = await app.screen_document(
            _Req(headers=_bearer(tok, {"Idempotency-Key": key1})),
            _upload(DOC_A), None, None, None, None, None)
        assert first.get("deduplicated") is False
        second = await app.screen_document(
            _Req(headers=_bearer(tok, {"Idempotency-Key": key2})),
            _upload(DOC_A), None, None, None, None, None)
        assert second.get("deduplicated") is True
        assert second.get("duplicate_of_key") == key1
        assert second["case_id"] == first["case_id"]

    _run(go)


def test_screen_missing_key_422():
    async def go(maker, officers):
        tok = _token(officers["off1"])
        with pytest.raises(Exception) as exc:
            await app.screen_document(_Req(headers=_bearer(tok)), _upload(DOC_A),
                                      None, None, None, None, None)
        assert getattr(exc.value, "status_code", None) == 422

    _run(go)


# ---------------------------------------------------------------------------
# RBAC override matrix
# ---------------------------------------------------------------------------

def test_override_officer_cannot_deny():
    async def go(maker, officers):
        case_id = await _make_case(maker, officers["off1"], verdict="Green")
        with pytest.raises(Exception) as exc:
            await app.override_case(
                case_id, app.OverrideRequest(action="deny", reason="nope officer deny"),
                _Req(headers=_bearer(_token(officers["off1"]))))
        assert getattr(exc.value, "status_code", None) == 403

    _run(go)


def test_override_officer_cannot_clear_red_but_supervisor_can():
    async def go(maker, officers):
        red_id = await _make_case(maker, officers["off1"], verdict="Red")
        with pytest.raises(Exception) as exc:
            await app.override_case(
                red_id, app.OverrideRequest(action="clear", reason="officer clear red"),
                _Req(headers=_bearer(_token(officers["off1"]))))
        assert getattr(exc.value, "status_code", None) == 403
        # Supervisor clears the same Red case.
        out = await app.override_case(
            red_id, app.OverrideRequest(action="clear", reason="supervisor reviewed, genuine"),
            _Req(headers=_bearer(_token(officers["sup1"]))))
        assert out["status"] == "ok" and out["action"] == "clear"

    _run(go)


def test_override_supervisor_can_deny():
    async def go(maker, officers):
        case_id = await _make_case(maker, officers["off1"], verdict="Yellow")
        out = await app.override_case(
            case_id, app.OverrideRequest(action="deny", reason="supervisor denial, forgery confirmed"),
            _Req(headers=_bearer(_token(officers["sup1"]))))
        assert out["status"] == "ok" and out["action"] == "deny"

    _run(go)


def test_override_auditor_read_only():
    async def go(maker, officers):
        case_id = await _make_case(maker, officers["off1"], verdict="Green")
        with pytest.raises(Exception) as exc:
            await app.override_case(
                case_id, app.OverrideRequest(action="escalate", reason="auditor try"),
                _Req(headers=_bearer(_token(officers["aud1"]))))
        assert getattr(exc.value, "status_code", None) == 403

    _run(go)


def test_override_version_mismatch_409():
    async def go(maker, officers):
        case_id = await _make_case(maker, officers["off1"], verdict="Green", version=0)
        with pytest.raises(Exception) as exc:
            await app.override_case(
                case_id, app.OverrideRequest(action="clear", reason="stale version", version=999),
                _Req(headers=_bearer(_token(officers["off1"]))))
        assert getattr(exc.value, "status_code", None) == 409

    _run(go)


def test_override_if_match_mismatch_409():
    async def go(maker, officers):
        case_id = await _make_case(maker, officers["off1"], verdict="Green", version=0)
        with pytest.raises(Exception) as exc:
            await app.override_case(
                case_id, app.OverrideRequest(action="clear", reason="stale if-match"),
                _Req(headers=_bearer(_token(officers["off1"]), {"If-Match": '"999"'})))
        assert getattr(exc.value, "status_code", None) == 409

    _run(go)


def test_override_decided_409():
    async def go(maker, officers):
        case_id = await _make_case(maker, officers["off1"], verdict="Green", status="decided")
        with pytest.raises(Exception) as exc:
            await app.override_case(
                case_id, app.OverrideRequest(action="clear", reason="after decision"),
                _Req(headers=_bearer(_token(officers["sup1"]))))
        assert getattr(exc.value, "status_code", None) == 409

    _run(go)


def test_override_officer_can_clear_green_and_escalate():
    async def go(maker, officers):
        green_id = await _make_case(maker, officers["off1"], verdict="Green")
        out = await app.override_case(
            green_id, app.OverrideRequest(action="clear", reason="verified genuine"),
            _Req(headers=_bearer(_token(officers["off1"]))))
        assert out["status"] == "ok"
        esc_id = await _make_case(maker, officers["off1"], verdict="Yellow")
        out = await app.override_case(
            esc_id, app.OverrideRequest(action="escalate", reason="needs supervisor eyes"),
            _Req(headers=_bearer(_token(officers["off1"]))))
        assert out["status"] == "ok" and out["action"] == "escalate"

    _run(go)


# ---------------------------------------------------------------------------
# /audit/verify chain
# ---------------------------------------------------------------------------

def test_audit_verify_valid_flag():
    async def go(maker, officers):
        async with maker() as s:
            await AuditLog.create_with_chain(s, actor="off1", action="login", entity="officer:1")
            await AuditLog.create_with_chain(s, actor="sup1", action="officer_override:clear", entity="case:1")
            await s.commit()
        out = await app.verify_audit_chain(_Req(headers=_bearer(_token(officers["aud1"]))))
        assert out["valid"] is True
        assert out["total_entries"] >= 2
        assert out["first_broken_id"] is None

    _run(go)


def test_audit_verify_detects_tamper():
    async def go(maker, officers):
        async with maker() as s:
            await AuditLog.create_with_chain(s, actor="off1", action="login", entity="officer:1")
            await AuditLog.create_with_chain(s, actor="off1", action="login", entity="officer:1")
            await s.commit()
            rows = (await s.execute(select(AuditLog).order_by(AuditLog.id.asc()))).scalars().all()
            rows[1].prev_hash = "f" * 64  # tamper with the chain link
            await s.commit()
        out = await app.verify_audit_chain(_Req(headers=_bearer(_token(officers["aud1"]))))
        assert out["valid"] is False
        assert out["first_broken_id"] is not None

    _run(go)


def test_audit_verify_officer_forbidden():
    async def go(maker, officers):
        with pytest.raises(Exception) as exc:
            await app.verify_audit_chain(_Req(headers=_bearer(_token(officers["off1"]))))
        assert getattr(exc.value, "status_code", None) == 403

    _run(go)


# ---------------------------------------------------------------------------
# HMAC registry import
# ---------------------------------------------------------------------------

def _import_body(batch_ref="TEST-2026-001", number="X1234567"):
    return {
        "batch_ref": batch_ref,
        "records": [{
            "document_type": "passport",
            "document_number": number,
            "full_name": "Import Test Person",
            "date_of_birth": "1990-01-01",
            "gender": "M",
        }],
    }


def _sign(body: bytes) -> str:
    return hmac.new(app._REGISTRY_IMPORT_SECRET.encode(), body, hashlib.sha256).hexdigest()


def test_registry_import_valid_signature():
    async def go(maker, officers):
        payload = _import_body(number="P1111111")
        raw = json.dumps(payload).encode()
        req = _ImportReq(raw, {**_bearer(_token(officers["sup1"])),
                               "X-Import-Signature": _sign(raw)})
        out = await app.import_authority_citizens(req)
        assert out["status"] == "ok"
        assert out["created"] == 1
        async with maker() as s:
            row = (await s.execute(
                select(CitizenRegistry).where(CitizenRegistry.document_number == "P1111111")
            )).scalar_one_or_none()
            assert row is not None
            assert row.source == "authority_import"

    _run(go)


def test_registry_import_invalid_signature_401():
    async def go(maker, officers):
        payload = _import_body(number="P2222222")
        raw = json.dumps(payload).encode()
        req = _ImportReq(raw, {**_bearer(_token(officers["sup1"])),
                               "X-Import-Signature": "0" * 64})
        with pytest.raises(Exception) as exc:
            await app.import_authority_citizens(req)
        assert getattr(exc.value, "status_code", None) == 401

    _run(go)


def test_registry_import_missing_signature_401():
    async def go(maker, officers):
        payload = _import_body(number="P3333333")
        raw = json.dumps(payload).encode()
        req = _ImportReq(raw, _bearer(_token(officers["sup1"])))
        with pytest.raises(Exception) as exc:
            await app.import_authority_citizens(req)
        assert getattr(exc.value, "status_code", None) == 401

    _run(go)


def test_registry_import_officer_forbidden():
    async def go(maker, officers):
        payload = _import_body(number="P4444444")
        raw = json.dumps(payload).encode()
        req = _ImportReq(raw, {**_bearer(_token(officers["off1"])),
                               "X-Import-Signature": _sign(raw)})
        with pytest.raises(Exception) as exc:
            await app.import_authority_citizens(req)
        assert getattr(exc.value, "status_code", None) == 403

    _run(go)


# ---------------------------------------------------------------------------
# Signed evidence bounds + /evidence/* 404
# ---------------------------------------------------------------------------

async def _make_evidence_case(maker, officers, filename="test_evidence.png") -> int:
    async with maker() as s:
        off = (await s.execute(select(Officer).where(Officer.username == "off1"))).scalar_one()
        case = ScreeningCase(officer_id=off.id, document_type="passport",
                             verdict="Green", status="pending_review",
                             risk_score=0.1, unit=off.unit or "BORDER_UNIT_1", version=0)
        s.add(case)
        await s.flush()
        s.add(ModuleResultDB(case_id=case.id, module_name="tamper", score=0.1,
                             status="ok", raw_output="{}", evidence_uri=filename,
                             is_mocked=False))
        await s.commit()
        return case.id


def test_evidence_token_bounds_and_roundtrip():
    async def go(maker, officers):
        await _make_evidence_case(maker, officers)
        tok = _token(officers["off1"])
        # Lower bound: 30s ok, 29 → 422.
        ok30 = await app.get_evidence_token(
            "test_evidence.png", _Req(headers=_bearer(tok)), expires_in=30)
        assert ok30["expires_in"] == 30 and ok30["token"]
        with pytest.raises(Exception) as exc:
            await app.get_evidence_token(
                "test_evidence.png", _Req(headers=_bearer(tok)), expires_in=29)
        assert getattr(exc.value, "status_code", None) == 422
        # Upper bound: default max 3600 ok, above → 422.
        ok3600 = await app.get_evidence_token(
            "test_evidence.png", _Req(headers=_bearer(tok)), expires_in=3600)
        assert ok3600["expires_in"] == 3600
        with pytest.raises(Exception) as exc2:
            await app.get_evidence_token(
                "test_evidence.png", _Req(headers=_bearer(tok)), expires_in=3601)
        assert getattr(exc2.value, "status_code", None) == 422
        # Token verifies and carries the filename.
        payload = app._verify_evidence_token(ok30["token"])
        assert payload["filename"] == "test_evidence.png"

    _run(go)


def test_evidence_token_route_declares_ge30():
    import inspect

    param = inspect.signature(app.get_evidence_token).parameters["expires_in"]
    ge_values = [getattr(m, "ge", None) for m in getattr(param.default, "metadata", [])]
    assert 30 in ge_values


def test_public_evidence_is_404():
    async def go(maker, officers):
        with pytest.raises(Exception) as exc:
            await app.block_public_evidence("test_evidence.png")
        assert getattr(exc.value, "status_code", None) == 404

    _run(go)


# ---------------------------------------------------------------------------
# Aadhaar masking (document_type == aadhaar OR field-name)
# ---------------------------------------------------------------------------

def test_mask_by_document_type():
    assert app.mask_document_number("aadhaar", "document_number", "2345 6789 0123") == "XXXX-XXXX-0123"
    assert app.mask_document_number("Aadhaar", "document_number", "234567890123") == "XXXX-XXXX-0123"
    # Non-Aadhaar type with a generic field name passes through.
    assert app.mask_document_number("passport", "document_number", "L898902C3") == "L898902C3"
    assert app.mask_document_number("pan", "document_number", "ABCPD1234E") == "ABCPD1234E"


def test_mask_by_field_name():
    # Aadhaar-like field names mask even when the case type is not aadhaar.
    assert app.mask_document_number("passport", "aadhaar_number", "234567890123") == "XXXX-XXXX-0123"
    assert app.mask_document_number(None, "uid_number", "2345-6789-0123") == "XXXX-XXXX-0123"
    assert app.mask_document_number("passport", "document_number", "234567890123") == "234567890123"


def test_mask_passthrough_and_none():
    assert app.mask_document_number("aadhaar", "document_number", None) is None
    assert app.mask_document_number("aadhaar", "document_number", "") == ""
    assert app.mask_document_number("aadhaar", "document_number", "not-a-number") == "not-a-number"


def test_get_case_masks_aadhaar():
    async def go(maker, officers):
        async with maker() as s:
            off = (await s.execute(select(Officer).where(Officer.username == "off1"))).scalar_one()
            s.add(CitizenRegistry(document_type="aadhaar", document_number="2345 6789 0123",
                                 full_name="Mask Test", date_of_birth="1990-01-01"))
            await s.flush()
            citizen = (await s.execute(
                select(CitizenRegistry).where(CitizenRegistry.document_number == "2345 6789 0123")
            )).scalar_one()
            case = ScreeningCase(officer_id=off.id, citizen_id=citizen.id,
                                 document_type="aadhaar", verdict="Green",
                                 status="pending_review", risk_score=0.1,
                                 unit=off.unit or "BORDER_UNIT_1", version=0)
            s.add(case)
            await s.flush()
            s.add(ExtractedField(case_id=case.id, field_name="Document Number",
                                 extracted_value="2345 6789 0123",
                                 database_value="2345 6789 0123",
                                 match_status="match", confidence=1.0))
            await s.commit()
            case_id = case.id
        out = await app.get_case(case_id, _Req(headers=_bearer(_token(off))))
        assert out["citizen"]["document_number"] == "XXXX-XXXX-0123"
        fields = {f["field_name"]: f for f in out["extracted_fields"]}
        assert fields["Document Number"]["extracted_value"] == "XXXX-XXXX-0123"
        assert fields["Document Number"]["database_value"] == "XXXX-XXXX-0123"

    _run(go)
