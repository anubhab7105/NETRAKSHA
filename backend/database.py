
from __future__ import annotations

import os

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)





_APP_ENV = os.environ.get("APP_ENV", os.environ.get("ENVIRONMENT", "development")).lower()
_IS_PROD = _APP_ENV == "production"

_RAW_URL = os.environ.get("DATABASE_URL", "").strip()

IS_SQLITE = False

if not _RAW_URL or _RAW_URL.startswith("sqlite"):
    if _IS_PROD:
        raise RuntimeError(
            "DATABASE_URL is not set (or is SQLite) but APP_ENV=production. "
            "Production is Supabase-PostgreSQL-only — set DATABASE_URL to your "
            "Supabase connection string, e.g. "
            "postgresql://postgres.<ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres"
        )

    if _RAW_URL.startswith("sqlite://") and not _RAW_URL.startswith("sqlite+aiosqlite://"):
        _RAW_URL = _RAW_URL.replace("sqlite://", "sqlite+aiosqlite://", 1)
    if _RAW_URL.startswith("sqlite+aiosqlite://"):
        DATABASE_URL = _RAW_URL
    else:
        _local_path = os.environ.get("LOCAL_DB_PATH", "./local_dev.db")
        DATABASE_URL = f"sqlite+aiosqlite:///{_local_path}"
        if not _RAW_URL:
            print(f"[database] DATABASE_URL not set — using local dev DB {DATABASE_URL} (set DATABASE_URL for Supabase).")
    IS_SQLITE = True
else:
    DATABASE_URL = _RAW_URL
    if DATABASE_URL.startswith("postgresql://"):
        DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)
    if not DATABASE_URL.startswith("postgresql+asyncpg://"):
        raise RuntimeError(
            f"Unsupported DATABASE_URL scheme {DATABASE_URL.split('://', 1)[0]!r}. "
            "Use postgresql://... or postgresql+asyncpg://... (Supabase), "
            "or sqlite in non-production dev only."
        )





if IS_SQLITE:
    _engine_kwargs = {
        "echo": os.environ.get("DB_ECHO", "").lower() in ("1", "true"),
        "connect_args": {"check_same_thread": False},
    }
else:
    _engine_kwargs = {
        "echo": os.environ.get("DB_ECHO", "").lower() in ("1", "true"),
        "pool_size": int(os.environ.get("DB_POOL_SIZE", "5")),
        "max_overflow": int(os.environ.get("DB_MAX_OVERFLOW", "10")),
        "pool_pre_ping": True,
        "connect_args": {
            # Disable server-side statement cache: Supabase pooler (pgbouncer) rejects prepared statements.
            "statement_cache_size": 0
        },
    }

engine = create_async_engine(DATABASE_URL, **_engine_kwargs)

async_session = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_session() -> AsyncSession:
    async with async_session() as session:
        yield session


async def init_db() -> None:
    from .models import Base

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)




    try:
        await ensure_model_columns()
    except Exception as e:
        print(f"[init_db] model-column migration warning: {e}")



    try:
        await ensure_sequences()
    except Exception as e:
        print(f"[init_db] sequence repair warning: {e}")



    try:
        await ensure_registry_trust_columns()
    except Exception as e:
        print(f"[init_db] registry trust-column migration warning: {e}")
    try:
        await ensure_auth_columns()
    except Exception as e:
        print(f"[init_db] auth-column migration warning: {e}")


async def _sqlite_table_columns(conn, table_name: str) -> set:
    from sqlalchemy import text as _text

    try:
        res = await conn.execute(_text(f'PRAGMA table_info("{table_name}")'))
        return {row[1] for row in res.all()}
    except Exception:
        return set()


async def ensure_model_columns() -> dict:
    from .models import Base

    from sqlalchemy import text as _text

    if IS_SQLITE:
        from sqlalchemy.dialects import sqlite as _lite_dialect

        _dialect = _lite_dialect.dialect()
    else:
        from sqlalchemy.dialects import postgresql as _pg_dialect

        _dialect = _pg_dialect.dialect()

    added: dict[str, list[str]] = {}
    async with engine.begin() as conn:
        for table in Base.metadata.tables.values():
            if IS_SQLITE:
                existing = await _sqlite_table_columns(conn, table.name)
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
                if IS_SQLITE:


                    stmt = (f'ALTER TABLE "{table.name}" ADD COLUMN '
                            f'"{col.name}" {ddl_type}{default_sql}')
                else:
                    stmt = (f'ALTER TABLE {table.name} ADD COLUMN IF NOT EXISTS '
                            f'"{col.name}" {ddl_type}{default_sql}')
                try:
                    await conn.execute(_text(stmt))
                    added.setdefault(table.name, []).append(col.name)
                except Exception:
                    pass

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
    from sqlalchemy import text as _text

    added: list[str] = []
    async with engine.begin() as conn:
        existing = await _sqlite_table_columns(conn, "citizens_registry") if IS_SQLITE else set()
        for name, ddl in _REGISTRY_TRUST_COLUMNS:
            try:
                if IS_SQLITE:
                    if name in existing:
                        continue
                    await conn.execute(_text(
                        f'ALTER TABLE citizens_registry ADD COLUMN "{name}" {ddl}'
                    ))
                else:
                    await conn.execute(_text(
                        f"ALTER TABLE citizens_registry ADD COLUMN IF NOT EXISTS {name} {ddl}"
                    ))
                added.append(name)
            except Exception:
                pass
    if added:
        print(f"[init_db] citizens_registry trust columns added: {added}")
    return {"added": added}



_AUTH_COLUMNS: tuple[tuple[str, str], ...] = (
    ("must_change_password", "BOOLEAN DEFAULT FALSE"),
    ("totp_secret", "TEXT"),
    ("totp_enabled", "BOOLEAN DEFAULT FALSE"),
    ("password_changed_at", "TIMESTAMP"),
)


async def ensure_auth_columns() -> dict:
    from sqlalchemy import text as _text

    added: list[str] = []
    async with engine.begin() as conn:
        existing = await _sqlite_table_columns(conn, "officers") if IS_SQLITE else set()
        for name, ddl in _AUTH_COLUMNS:
            try:
                if IS_SQLITE:
                    if name in existing:
                        continue
                    await conn.execute(_text(
                        f'ALTER TABLE officers ADD COLUMN "{name}" {ddl}'
                    ))
                else:
                    await conn.execute(_text(
                        f"ALTER TABLE officers ADD COLUMN IF NOT EXISTS {name} {ddl}"
                    ))
                added.append(name)
            except Exception:
                pass

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
    if IS_SQLITE:
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
                    "(SELECT COALESCE(max(id), 0) FROM " + table.name + ") + 1, false"))
                row = res.fetchone()
                if row:
                    fixed[table.name] = int(row[0])
            except Exception:
                pass
    if fixed:
        print(f"[init_db] sequences re-anchored: {fixed}")
    return fixed


def get_engine_info() -> dict:
    if IS_SQLITE:
        return {
            "url": DATABASE_URL,
            "driver": "aiosqlite",
            "backend": "sqlite",
        }
    return {
        "url": DATABASE_URL.split("@")[-1] if "@" in DATABASE_URL else DATABASE_URL,
        "driver": "asyncpg",
        "backend": "postgresql",
    }
