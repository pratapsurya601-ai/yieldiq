# backend/models/web_vital_event.py
# SQLAlchemy model for real-user Core Web Vitals (RUM) events.
# Schema: data_pipeline/migrations/202606141735_web_vitals_events.sql.
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, DateTime, Float, Index, Integer, Text

from data_pipeline.models import Base


class WebVitalEvent(Base):
    """One row per Core Web Vital sample beaconed from a real browser.

    `metric` is one of LCP / CLS / INP / TTFB / FCP (validated upstream
    by the Pydantic Literal on the router). `value` is in milliseconds
    except CLS, which is the unitless layout-shift score stored as-is.
    """

    __tablename__ = "web_vitals_events"
    __table_args__ = (
        Index("idx_web_vitals_metric_created", "metric", "created_at"),
        Index("idx_web_vitals_path_created", "path", "created_at"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    metric = Column(Text, nullable=False)
    value = Column(Float, nullable=False)
    rating = Column(Text, nullable=True)
    path = Column(Text, nullable=True)
    nav_type = Column(Text, nullable=True)
    conn_type = Column(Text, nullable=True)
    device = Column(Text, nullable=True)
    ip_hash = Column(Text, nullable=True)
    created_at = Column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )
