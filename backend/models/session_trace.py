# backend/models/session_trace.py
# SQLAlchemy model for the Phase J session-observation harness.
# Schema defined in data_pipeline/migrations/062_session_traces.sql.
from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, BigInteger, Column, DateTime, Index, Integer, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func

# PG uses JSONB (defined in migration 062); other dialects (SQLite in
# tests) fall back to the generic JSON type so the table can be
# created in-memory without a Postgres compiler.
_JsonCol = JSON().with_variant(JSONB(), "postgresql")

from data_pipeline.models import Base


class SessionTrace(Base):
    """One row per UI event recorded by useSessionTrace on an auth'd session.

    `event_type` is one of: page_view, search_query, button_click
    (validated upstream by the Pydantic Literal on the router).
    `event_data` is a small JSON blob with ticker / query / button_id —
    NO PII, NO form contents.
    """

    __tablename__ = "session_traces"
    __table_args__ = (
        Index(
            "idx_session_traces_user_created",
            "user_id",
            "created_at",
        ),
    )

    # SQLite (used in tests) needs INTEGER PRIMARY KEY for autoincrement;
    # PG uses BIGSERIAL per migration 062.
    id = Column(
        BigInteger().with_variant(Integer(), "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    user_id = Column(Text, nullable=False)
    session_id = Column(Text, nullable=False)
    event_type = Column(Text, nullable=False)
    event_data = Column(_JsonCol, nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        default=datetime.utcnow,
    )
