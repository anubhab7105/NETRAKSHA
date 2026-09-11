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
    # create_all() never adds columns to PRE-EXISTING tables, so long-lived
    # databases (e.g. production Supabase) silently miss columns added by
    # later code changes (officers.unit, screening_cases.version, ...).
    # The generic pass below self-heals any such drift on every startup.
    try:
        await ensure_model_columns()
    except Exception as e:
        print(f"[init_db] model-column migration warning: {e}")
    # Legacy tables built with explicit IDs leave their SERIAL sequences
    # behind max(id) → every autoincrement INSERT explodes with a duplicate
    # pkey. Re-anchor sequences past max(id) on every startup (Postgres).
    try:
        await ensure_sequences()
    except Exception as e:
        print(f"[init_db] sequence repair warning: {e}")
    # Post-fix columns on a pre-existing table are NOT added by create_all —
    # backfill them so deployed SQLite/Postgres DBs pick up trust metadata
    # with just a restart (no manual migration).
    try:
        await ensure_registry_trust_columns()
    except Exception as e:
        print(f"[init_db] registry trust-column migration warning: {e}")
    try:
        await ensure_auth_columns()
    except Exception as e:
        print(f"[init_db] auth-column migration warning: {e}")


async def ensure_model_columns() -> dict:
    """Add every ORM-mapped column missing from the live database.

    Generic drift repair: compares each model's columns against the actual
    table (information_schema on Postgres, PRAGMA on SQLite) and ALTERs in
    whatever is absent — e.g. officers.unit on databases created before
    unit scoping shipped. Idempotent, race-safe (per-column try/except),
    runs on every startup. Returns {"table": [added, ...]}.
    """
    from .models import Base

    if _IS_SQLITE:
        from sqlalchemy.dialects import sqlite as _sqlite_dialect
        _dialect = _sqlite_dialect.dialect()
    else:
        from sqlalchemy.dialects import postgresql as _pg_dialect
        _dialect = _pg_dialect.dialect()

    from sqlalchemy import text as _text

    added: dict[str, list[str]] = {}
    async with engine.begin() as conn:
        for table in Base.metadata.tables.values():
            if _IS_SQLITE:
                res = await conn.execute(_text(f"PRAGMA table_info({table.name})"))
                existing = {row[1] for row in res.all()}
            else:
                res = await conn.execute(
                    _text("SELECT column_name FROM information_schema.columns "
                          "WHERE table_name = :t"),
                    {"t": table.name},
                )
                existing = {row[0] for row in res.all()}
            for col in table.columns:
                if col.primary_key or col.name in existing:
                    continue
                try:
                    ddl_type = col.type.compile(dialect=_dialect)
                except Exception:
                    continue
                default_sql = ""
                try:
                    if col.server_default is not None:
                        default_sql = f" DEFAULT {col.server_default._compiler_dispatch(_dialect, None)}"
                except Exception:
                    default_sql = ""
                if _IS_SQLITE:
                    stmt = f'ALTER TABLE {table.name} ADD COLUMN "{col.name}" {ddl_type}{default_sql}'
                else:
                    stmt = (f'ALTER TABLE {table.name} ADD COLUMN IF NOT EXISTS '
                            f'"{col.name}" {ddl_type}{default_sql}')
                try:
                    await conn.execute(_text(stmt))
                    added.setdefault(table.name, []).append(col.name)
                except Exception:
                    pass  # concurrent startup already added it
    # Backfill NULLs on flag/counter columns so old rows behave sanely.
    _backfills = (
        ("officers", "must_change_password", "FALSE"),
        ("officers", "totp_enabled", "FALSE"),
        ("screening_cases", "version", "0"),
    )
    if added:
        from sqlalchemy import text as _text
        try:
            async with engine.begin() as conn:
                for table, column, value in _backfills:
                    if column in added.get(table, []):
                        await conn.execute(_text(
                            f'UPDATE {table} SET "{column}" = {value} WHERE "{column}" IS NULL'))
        except Exception as e:
            print(f"[init_db] model-column backfill warning: {e}")
        print(f"[init_db] model columns added: {added}")
    return added


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


# Auth-hardening columns added to officers after the secrets audit.
_AUTH_COLUMNS: tuple[tuple[str, str], ...] = (
    ("must_change_password", "BOOLEAN DEFAULT FALSE"),
    ("totp_secret", "TEXT"),
    ("totp_enabled", "BOOLEAN DEFAULT FALSE"),
    ("password_changed_at", "TIMESTAMP"),
)


async def ensure_auth_columns() -> dict:
    """Add missing auth columns to officers. Idempotent; runs every startup."""
    added: list[str] = []
    if _IS_SQLITE:
        from sqlalchemy import text as _text
        async with engine.begin() as conn:
            res = await conn.execute(_text("PRAGMA table_info(officers)"))
            existing = {row[1] for row in res.all()}
            for name, ddl in _AUTH_COLUMNS:
                if name not in existing:
                    await conn.execute(_text(f"ALTER TABLE officers ADD COLUMN {name} {ddl}"))
                    added.append(name)
    else:
        from sqlalchemy import text as _text
        async with engine.begin() as conn:
            for name, ddl in _AUTH_COLUMNS:
                try:
                    await conn.execute(_text(
                        f"ALTER TABLE officers ADD COLUMN IF NOT EXISTS {name} {ddl}"
                    ))
                    added.append(name)
                except Exception:
                    pass
    # Backfill NULLs left by ADD COLUMN on rows predating the default.
    if added:
        from sqlalchemy import text as _text
        try:
            async with engine.begin() as conn:
                if "must_change_password" in added:
                    await conn.execute(_text(
                        "UPDATE officers SET must_change_password = FALSE "
                        "WHERE must_change_password IS NULL"))
                if "totp_enabled" in added:
                    await conn.execute(_text(
                        "UPDATE officers SET totp_enabled = FALSE WHERE totp_enabled IS NULL"))
        except Exception as e:
            print(f"[init_db] auth-column backfill warning: {e}")
        print(f"[init_db] officers auth columns added: {added}")
    return {"added": added}


async def ensure_sequences() -> dict:
    """Re-anchor SERIAL sequences past max(id) on every table (Postgres).

    Legacy databases (rows inserted with explicit IDs, restores, dashboard
    edits) leave e.g. officers_id_seq behind max(officers.id), so the next
    autoincrement INSERT dies with a duplicate-pkey IntegrityError and —
    in production — crash-loops the backend at seed time. pg_get_serial_-
    sequence() resolves the real sequence regardless of naming. No-op on
    SQLite (rowid tables self-heal). Returns {"table": next_id}.
    """
    if _IS_SQLITE:
        return {}
    from sqlalchemy import text as _text

    from .models import Base

    fixed: dict[str, int] = {}
    async with engine.begin() as conn:
        for table in Base.metadata.tables.values():
            pk = [c for c in table.columns if c.primary_key]
            if len(pk) != 1 or pk[0].name != "id":
                continue
            try:
                res = await conn.execute(_text(
                    "SELECT setval(pg_get_serial_sequence(:t, 'id'), "
                    "(SELECT COALESCE(max(id), 0) FROM " + table.name + "))"))
                row = res.fetchone()
                if row:
                    fixed[table.name] = int(row[0])
            except Exception:
                pass  # non-serial PK or missing table — nothing to repair
    if fixed:
        print(f"[init_db] sequences re-anchored: {fixed}")
    return fixed


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
