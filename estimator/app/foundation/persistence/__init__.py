"""Persistence layer for the Session 6 ingestion subsystem.

Holds the SQLAlchemy engine, the declarative ``Base`` and the row models that
back the pseudonymization mapping table and the ingestion job tracker. Higher
layers consume narrow repositories from ``app.foundation.persistence.repositories``; they
never see SQLAlchemy types directly.

This layer shares the project's single Postgres (``Settings.DATABASE_URL``,
psycopg v3 sync driver). The two tables here are managed by Alembic
(``alembic upgrade head``); the older ``estimations`` / ``chat_sessions`` tables
keep using ``app.foundation.persistence.db.create_all`` + ``_ensure_columns``. One database, two
creation mechanisms — deliberate, documented in ``docs/session-06.md``.
"""
from app.foundation.persistence.database import (
    SessionLocal,
    create_engine_from_settings,
    get_session,
)
from app.foundation.persistence.models import Base, IngestionJobRow, PseudonymMappingRow

__all__ = [
    "Base",
    "IngestionJobRow",
    "PseudonymMappingRow",
    "SessionLocal",
    "create_engine_from_settings",
    "get_session",
]
