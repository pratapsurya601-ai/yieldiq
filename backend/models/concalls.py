# backend/models/concalls.py
# SQLAlchemy model for concall_transcripts.
#
# Stores metadata about earnings-call / analyst-meet filings from NSE
# corporate-announcements. PDF parsing is deliberately NOT part of this
# model -- see TODO below. The /concall frontend page reads this table
# to surface links + subject lines; full transcript text extraction is
# a separate (expensive) pipeline.
#
# Migration: data_pipeline/migrations/009_concall_transcripts.sql
#
# TODO(concall-pdf-parse): add a `transcript_text` TEXT column and a
# separate worker that downloads pdf_url, runs pdfplumber / OCR
# fallback, and populates the text. Out-of-scope here.
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Column, Integer, String, Text, Date, DateTime, UniqueConstraint, Index,
)

from data_pipeline.models import Base


class ConcallTranscript(Base):
    """NSE earnings-call / analyst-meet filing metadata."""
    __tablename__ = "concall_transcripts"
    __table_args__ = (
        UniqueConstraint(
            "ticker", "filing_date", "subject",
            name="uq_concall_ticker_date_subject",
        ),
        Index("idx_concall_ticker_date", "ticker", "filing_date"),
        Index("idx_concall_filing_date", "filing_date"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticker = Column(String(20), nullable=False, index=True)
    filing_date = Column(Date, nullable=False)
    quarter_end = Column(Date, nullable=True)   # best-effort from subject
    pdf_url = Column(Text, nullable=True)
    subject = Column(Text, nullable=False)
    category = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
