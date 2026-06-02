"""SQLAlchemy engine, session factory and FastAPI dependency.

The engine is built lazily from ``settings.DATABASE_URL`` so importing the app
never opens a connection (tests can override ``get_db`` or point at sqlite).
``create_all`` runs at startup; for a real deployment swap it for Alembic.
"""

from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def _init() -> tuple[Engine, sessionmaker[Session]]:
    global _engine, _SessionLocal
    if _engine is None:
        url = get_settings().DATABASE_URL
        connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
        _engine = create_engine(url, pool_pre_ping=True, connect_args=connect_args)
        _SessionLocal = sessionmaker(bind=_engine, autoflush=False, autocommit=False)
    assert _SessionLocal is not None
    return _engine, _SessionLocal


def get_engine() -> Engine:
    return _init()[0]


def create_all() -> None:
    # Import models so they register on Base.metadata before create_all.
    from app import db_models  # noqa: F401

    engine, _ = _init()
    Base.metadata.create_all(engine)
    _ensure_columns(engine)


# Columns added after a table first shipped. ``create_all`` does NOT alter an
# existing table, so we add them idempotently. Postgres-only (ADD COLUMN IF NOT
# EXISTS); on a fresh sqlite test DB create_all already includes them. Keyed by
# table name so newer tables (chat_sessions) can evolve the same way.
_ADDED_COLUMNS: dict[str, dict[str, str]] = {
    "estimations": {
        "input_tokens": "INTEGER",
        "output_tokens": "INTEGER",
        "total_tokens": "INTEGER",
        "cost_usd": "DOUBLE PRECISION",
        "finish_reason": "VARCHAR(40)",
        "session_id": "VARCHAR(36)",
    },
    "chat_sessions": {
        "last_resolved_tier": "VARCHAR(20)",
        "last_tier_rule": "VARCHAR(40)",
    },
}


def _ensure_columns(engine: Engine) -> None:
    if engine.dialect.name != "postgresql":
        return
    from sqlalchemy import text

    with engine.begin() as conn:
        for table, columns in _ADDED_COLUMNS.items():
            for name, ddl in columns.items():
                conn.execute(
                    text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {name} {ddl}")
                )


def get_db() -> Generator[Session, None, None]:
    _, SessionLocal = _init()
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
