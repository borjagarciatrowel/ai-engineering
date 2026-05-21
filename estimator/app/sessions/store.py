"""Postgres-backed session store.

This is the project-specific deviation from the Session 5 brief. The exercise
says "a process-memory dict is enough — persistence is module-3 territory".
We already run Postgres for the persisted estimations, so we persist the
conversational memory there too: a restart (or a second uvicorn worker) no
longer wipes the conversation.

The store wraps a request-scoped SQLAlchemy ``Session`` (from ``get_db``). It
maps between the relational row (``ChatSession``) and the storage-agnostic
Pydantic ``Session``:

- ``create``      → INSERT a fresh row, return the Pydantic model.
- ``get`` / ``get_or_404`` → load a row and rebuild the Pydantic model.
- ``save``        → write the (mutated) ``history`` + ``metadata`` back.

The service mutates the Pydantic ``Session`` in place (appends a turn, refreshes
metadata); the router then calls ``save`` to flush those changes. Keeping the
service storage-agnostic means the conversational pipeline never imports the ORM.
"""

from __future__ import annotations

from sqlalchemy.orm import Session as SaSession

from app.db_models import ChatSession
from app.sessions.models import ConversationHistory, ProjectMetadata, Session


class SessionNotFoundError(KeyError):
    """Raised by ``DbSessionStore.get_or_404`` when the id is unknown."""


class DbSessionStore:
    def __init__(self, db: SaSession, *, max_turns: int = 6) -> None:
        self._db = db
        self._max_turns = max_turns

    def create(self) -> Session:
        history = ConversationHistory(max_turns=self._max_turns)
        metadata = ProjectMetadata()
        row = ChatSession(
            max_turns=self._max_turns,
            history=history.model_dump(mode="json"),
            project_metadata=metadata.model_dump(mode="json"),
        )
        self._db.add(row)
        self._db.commit()
        self._db.refresh(row)
        return self._to_session(row)

    def get(self, session_id: str) -> Session | None:
        row = self._db.get(ChatSession, session_id)
        return self._to_session(row) if row is not None else None

    def get_or_404(self, session_id: str) -> Session:
        session = self.get(session_id)
        if session is None:
            raise SessionNotFoundError(session_id)
        return session

    def save(self, session: Session) -> None:
        """Persist the mutated history + metadata back onto the row.

        We assign fresh dicts (not in-place edits) so SQLAlchemy's change
        detection flags the JSON columns as dirty without needing MutableDict.
        """
        row = self._db.get(ChatSession, session.session_id)
        if row is None:
            raise SessionNotFoundError(session.session_id)
        row.history = session.history.model_dump(mode="json")
        row.project_metadata = session.metadata.model_dump(mode="json")
        self._db.commit()

    @staticmethod
    def _to_session(row: ChatSession) -> Session:
        return Session(
            session_id=row.id,
            history=ConversationHistory.model_validate(row.history),
            metadata=ProjectMetadata.model_validate(row.project_metadata),
            created_at=row.created_at,
        )
