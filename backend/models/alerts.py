# backend/models/alerts.py
# SQLAlchemy model for the backend-driven user_alerts table.
# Schema defined in data_pipeline/migrations/009_alerts.sql.
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)

# Reuse the declarative Base from data_pipeline.models so the table gets
# picked up by Base.metadata.create_all() in backend/main.py's startup
# lifecycle alongside the other pipeline tables.
from data_pipeline.models import Base


# ── Allowed values ────────────────────────────────────────────
ALERT_KINDS: tuple[str, ...] = (
    "mos_above",
    "mos_below",
    "price_above",
    "price_below",
    "verdict_change",
)

ALERT_STATUSES: tuple[str, ...] = ("active", "paused", "triggered")


class UserAlert(Base):
    """One row per user-configured alert.

    The evaluator (scripts/alerts_evaluator.py) scans rows where
    ``status = 'active'`` hourly, checks each alert's condition against
    the latest market_metrics + fair_value_history snapshot, and fires
    an email via backend.services.email_service._send_email when the
    condition is met AND the alert hasn't fired in the last 24h.
    """

    __tablename__ = "user_alerts"
    __table_args__ = (
        UniqueConstraint("user_id", "ticker", "kind", name="uq_user_alert"),
        CheckConstraint(
            "kind IN ('mos_above','mos_below','price_above',"
            "'price_below','verdict_change')",
            name="ck_user_alert_kind",
        ),
        CheckConstraint(
            "status IN ('active','paused','triggered')",
            name="ck_user_alert_status",
        ),
        Index("idx_user_alerts_status_ticker", "status", "ticker"),
        Index("idx_user_alerts_user", "user_id", "created_at"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Text, nullable=False)
    ticker = Column(Text, nullable=False)
    kind = Column(Text, nullable=False)
    # NUMERIC — nullable for verdict_change which has no numeric target.
    threshold = Column(Numeric, nullable=True)
    last_checked_at = Column(DateTime(timezone=True), nullable=True)
    last_triggered_at = Column(DateTime(timezone=True), nullable=True)
    status = Column(Text, nullable=False, default="active")
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=datetime.utcnow,
    )
    notify_email = Column(Boolean, nullable=False, default=True)
    notify_push = Column(Boolean, nullable=False, default=False)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "ticker": self.ticker,
            "kind": self.kind,
            "threshold": float(self.threshold) if self.threshold is not None else None,
            "last_checked_at": (
                self.last_checked_at.isoformat() if self.last_checked_at else None
            ),
            "last_triggered_at": (
                self.last_triggered_at.isoformat() if self.last_triggered_at else None
            ),
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "notify_email": bool(self.notify_email),
            "notify_push": bool(self.notify_push),
        }
