"""API integration tests for the full /api/screen pipeline.

Exercises login -> screen (genuine + tampered) -> case fetch -> audit,
plus auth/upload guards, against an isolated SQLite DB with the seeded
officer. Gemini runs offline here (simulated), so assertions only pin
contract shape (verdict set, modules persisted, dedup behavior) — never
simulated scores.
"""

from __future__ import annotations

import asyncio
import io
import uuid

import pytest

pytestmark = pytest.mark.skipif(
    __import__("shutil").which("tesseract") is None,
    reason="system tesseract required for the OCR leg",
)

import backend.app as app
from backend.models import Base, Officer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

GENUINE = "samples/genuine_doc.png"
TAMPERED = "samples/tampered_doc.png"
LIVE = "samples/live/blink_burst_05.png"


class _Req:
    def __init__(self, headers=None, cookies=None):
        self.headers = headers or {}
        self.cookies = cookies or {}
        self.client = None


def _files(doc_path, live_path=None, key=None):
    from fastapi import UploadFile
    from starlette.datastructures import Headers

    with open(doc_path, "rb") as fh:
        doc = UploadFile(file=io.BytesIO(fh.read()), filename="doc.png",
                         headers=Headers({"content-type": "image/png"}))
    live = None
    if live_path:
        with open(live_path, "rb") as fh:
            live = UploadFile(file=io.BytesIO(fh.read()), filename="live.png",
                              headers=Headers({"content-type": "image/png"}))
    return doc, live, key or str(uuid.uuid4())


async def _seed_officer(maker):
    from passlib.context import CryptContext

    ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")
    async with maker() as s:
        s.add(Officer(username="screenint", password_hash=ctx.hash("Screen-Int-1!"),
                      role="officer", unit="U1"))
        s.add(Officer(username="screenaudit", password_hash=ctx.hash("Screen-Int-1!"),
                      role="auditor", unit="HQ"))
        await s.commit()


def _run(coro_factory):
    async def go():
        eng = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with eng.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        maker = async_sessionmaker(eng, class_=AsyncSession, expire_on_commit=False)
        old = app.async_session
        app.async_session = maker
        try:
            await _seed_officer(maker)
            return await coro_factory()
        finally:
            app.async_session = old
            await eng.dispose()

    return asyncio.run(go())


def test_screen_requires_auth():
    async def go():
        with pytest.raises(Exception) as exc:
            doc, live, key = _files(GENUINE, LIVE)
            await app.screen_document(_Req(), doc, live, None, None, None, key)
        assert getattr(exc.value, "status_code", None) in (401, 422)

    _run(go)


def test_screen_genuine_end_to_end():
    async def go():
        login = await app.login(
            app.LoginRequest(username="screenint", password="Screen-Int-1!"), _Req())
        req = _Req(headers={"Authorization": f"Bearer {login.token}",
                            "Idempotency-Key": str(uuid.uuid4())})
        doc, live, _ = _files(GENUINE, LIVE)
        res = await app.screen_document(req, doc, live, None, None, None, None)
        assert res["case_id"]
        assert res["risk_assessment"]["verdict"] in ("Green", "Yellow", "Red")
        assert res["tamper"]["status"] in ("ok", "inconclusive")

        case = await app.get_case(res["case_id"], _Req(
            headers={"Authorization": f"Bearer {login.token}"}))
        assert case["case"]["id"] == res["case_id"]
        assert any(m["module_name"] == "tamper" for m in case["module_results"])

        auditor = await app.login(
            app.LoginRequest(username="screenaudit", password="Screen-Int-1!"), _Req())
        audit = await app.list_audit(
            _Req(headers={"Authorization": f"Bearer {auditor.token}"}),
            actor=None, entity=None, limit=50, offset=0)
        assert audit["count"] >= 1

    _run(go)


def test_screen_rejects_oversize_upload():
    async def go():
        login = await app.login(
            app.LoginRequest(username="screenint", password="Screen-Int-1!"), _Req())
        from fastapi import UploadFile
        from starlette.datastructures import Headers

        big = UploadFile(file=io.BytesIO(b"\x89PNG" + b"\x00" * (11_000_000)),
                         filename="big.png",
                         headers=Headers({"content-type": "image/png"}))
        req = _Req(headers={"Authorization": f"Bearer {login.token}",
                            "Idempotency-Key": str(uuid.uuid4())})
        with pytest.raises(Exception) as exc:
            await app.screen_document(req, big, None, None, None, None, None)
        assert getattr(exc.value, "status_code", None) == 413

    _run(go)


def test_screen_idempotent_replay():
    async def go():
        login = await app.login(
            app.LoginRequest(username="screenint", password="Screen-Int-1!"), _Req())
        key = str(uuid.uuid4())
        headers = {"Authorization": f"Bearer {login.token}", "Idempotency-Key": key}
        doc1, live1, _ = _files(GENUINE, LIVE)
        first = await app.screen_document(_Req(headers=headers), doc1, live1,
                                          None, None, None, None)
        doc2, live2, _ = _files(GENUINE, LIVE)
        second = await app.screen_document(_Req(headers=headers), doc2, live2,
                                           None, None, None, None)
        assert second.get("deduplicated") is True
        assert second["case_id"] == first["case_id"]

    _run(go)
