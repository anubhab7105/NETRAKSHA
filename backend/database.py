"""Async database engine configuration.

Supports dual-engine setup:
  * Primary (Hackathon / Production): Supabase PostgreSQL via asyncpg
    (`postgresql+asyncpg://...`)
  * Offline Fallback: Local SQLite via aiosqlite
    (`sqlite+aiosqlite:///screening.db`)

Automatically selects the connection string via `DATABASE_URL` env var.
Falls back to SQLite if the env var is not set or empty.
"""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

# ---------------------------------------------------------------------------
# Database URL resolution
# ---------------------------------------------------------------------------

_DEFAULT_SQLITE = f"sqlite+aiosqlite:///{Path(__file__).resolve().parent.parent / 'screening.db'}"

DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
if not DATABASE_URL:
    DATABASE_URL = _DEFAULT_SQLITE
elif DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)

# Detect engine type for conditional configuration
_IS_SQLITE = DATABASE_URL.startswith("sqlite")

# ---------------------------------------------------------------------------
# Engine & session factory
# ---------------------------------------------------------------------------

_engine_kwargs = {
    "echo": os.environ.get("DB_ECHO", "").lower() in ("1", "true"),
}

if _IS_SQLITE:
    # SQLite-specific: allow check_same_thread=False for async
    _engine_kwargs["connect_args"] = {"check_same_thread": False}
else:
    # PostgreSQL asyncpg settings
    _engine_kwargs["pool_size"] = int(os.environ.get("DB_POOL_SIZE", "5"))
    _engine_kwargs["max_overflow"] = int(os.environ.get("DB_MAX_OVERFLOW", "10"))
    _engine_kwargs["pool_pre_ping"] = True
    _engine_kwargs["connect_args"] = {
        "statement_cache_size": 0
    }

engine = create_async_engine(DATABASE_URL, **_engine_kwargs)

async_session = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_session() -> AsyncSession:
    """Dependency for FastAPI — yields an async session."""
    async with async_session() as session:
        yield session


async def init_db() -> None:
    """Create all tables. Called once at application startup."""
    from .models import Base

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    # Post-fix columns on a pre-existing table are NOT added by create_all —
    # backfill them so deployed SQLite/Postgres DBs pick up trust metadata
    # with just a restart (no manual migration).
    try:
        await ensure_registry_trust_columns()
    except Exception as e:
        print(f"[init_db] registry trust-column migration warning: {e}")


# Trust columns added to citizens_registry after the enrollment audit.
# (name, DDL fragment used for ALTER TABLE on both SQLite and Postgres.)
_REGISTRY_TRUST_COLUMNS: tuple[tuple[str, str], ...] = (
    ("source", "VARCHAR(30)"),
    ("source_ref", "TEXT"),
    ("verification_method", "VARCHAR(80)"),
    ("photo_hash", "VARCHAR(64)"),
    ("enrolled_by", "VARCHAR(100)"),
    ("approved_by", "VARCHAR(100)"),
    ("last_reconciled_at", "TIMESTAMP"),
    ("reconciliation_status", "VARCHAR(30)"),
)


async def ensure_registry_trust_columns() -> dict:
    """Add missing controlled-enrollment columns to citizens_registry.

    Safe to run on every startup (idempotent). Returns {"added": [...]}.
    """
    added: list[str] = []
    if _IS_SQLITE:
        from sqlalchemy import text as _text
        async with engine.begin() as conn:
            res = await conn.execute(_text("PRAGMA table_info(citizens_registry)"))
            existing = {row[1] for row in res.all()}
            for name, ddl in _REGISTRY_TRUST_COLUMNS:
                if name not in existing:
                    await conn.execute(_text(f"ALTER TABLE citizens_registry ADD COLUMN {name} {ddl}"))
                    added.append(name)
    else:
        from sqlalchemy import text as _text
        async with engine.begin() as conn:
            for name, ddl in _REGISTRY_TRUST_COLUMNS:
                try:
                    await conn.execute(_text(
                        f"ALTER TABLE citizens_registry ADD COLUMN IF NOT EXISTS {name} {ddl}"
                    ))
                    added.append(name)
                except Exception:
                    pass
    if added:
        print(f"[init_db] citizens_registry trust columns added: {added}")
    return {"added": added}


async def drop_db() -> None:
    """Drop all tables. Used only in testing."""
    from .models import Base

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


def get_engine_info() -> dict:
    """Return diagnostic info about the current database engine."""
    return {
        "url": DATABASE_URL.split("@")[-1] if "@" in DATABASE_URL else DATABASE_URL,
        "is_sqlite": _IS_SQLITE,
        "driver": "aiosqlite" if _IS_SQLITE else "asyncpg",
    }
