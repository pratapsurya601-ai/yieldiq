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
from sqlalchemy.sql import func

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
    # Day-104b: AI summary cache. ai_summary populated lazily on first
    # list_concalls request that finds a row with pdf_url but no
    # summary. transcript_text caches the parsed PDF text so we don't
    # re-fetch + re-parse if Groq errors after extraction.
    ai_summary = Column(Text, nullable=True)
    ai_summary_model = Column(Text, nullable=True)
    ai_summary_generated_at = Column(DateTime(timezone=True), nullable=True)
    transcript_text = Column(Text, nullable=True)


# ─────────────────────────────────────────────────────────────────
# Day-103a: ticker-level concall library with AI-cached summaries.
# Migration: data_pipeline/migrations/051_concalls.sql
# Separate from ConcallTranscript above — that one carries raw NSE
# filings metadata; this one carries the curated, summarised library
# surface that the public /concalls/{ticker} endpoint reads.
# ─────────────────────────────────────────────────────────────────
class Concall(Base):
    """One row per ticker-quarter concall with cached AI summary."""
    __tablename__ = "concalls"
    __table_args__ = (
        UniqueConstraint("ticker", "period", name="uq_concalls_ticker_period"),
        Index("idx_concalls_ticker_date", "ticker", "concall_date"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticker = Column(Text, nullable=False)
    period = Column(Text, nullable=False)
    concall_date = Column(Date, nullable=True)
    source_url = Column(Text, nullable=False)
    transcript_text = Column(Text, nullable=True)
    ai_summary = Column(Text, nullable=True)
    ai_summary_model = Column(Text, nullable=True)
    ai_summary_generated_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
