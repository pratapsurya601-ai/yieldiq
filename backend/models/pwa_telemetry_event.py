# backend/models/pwa_telemetry_event.py
# SQLAlchemy model for the persistent PWA install funnel telemetry table.
# Schema defined in data_pipeline/migrations/050_pwa_telemetry_events.sql.
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, DateTime, Index, Integer, Text

from data_pipeline.models import Base


class PwaTelemetryEvent(Base):
    """One row per recorded PWA funnel event.

    `event` is one of: prompted, installed, dismissed, ios_hint_shown
    (validated upstream by the Pydantic Literal on the router).
    """

    __tablename__ = "pwa_telemetry_events"
    __table_args__ = (
        Index(
            "idx_pwa_telemetry_events_event_created",
            "event",
            "created_at",
        ),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    event = Column(Text, nullable=False)
    ua_truncated = Column(Text, nullable=True)
    ip_hash = Column(Text, nullable=True)
    created_at = Column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )
