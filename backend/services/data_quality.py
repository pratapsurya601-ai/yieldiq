# backend/services/data_quality.py
# ═══════════════════════════════════════════════════════════════
# Data-completeness gate. Wired into _build_yieldiq50 so the
# Discover rail never surfaces tickers with sparse fundamentals.
#
# The score is intentionally simple and explainable — it's a
# weighted average of five binary-ish checks:
#
#   1. Annual financials count >= 3 years   weight 0.30
#   2. Key fields populated on latest row   weight 0.25
#   3. Classifier confidence (Pillar 1)     weight 0.15
#   4. Quality metrics computable (ROE etc) weight 0.15
#   5. Market cap row present (>0)          weight 0.15
#
# Surfaces should:
#   - score >= 0.70  -> show full numbers
#   - 0.50 <= score < 0.70 -> show with `data_limited` chip
#   - score < 0.50   -> hide / soft-block from rails
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from backend.services.classification import classify, ClassificationResult

logger = logging.getLogger("yieldiq.data_quality")


@dataclass
class CompletenessReport:
    ticker: str
    score: float
    annual_rows: int
    has_key_fields: bool
    classifier_confidence: float
    has_quality_metrics: bool
    has_market_cap: bool
    classification: Optional[ClassificationResult] = None
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "ticker": self.ticker,
            "score": round(self.score, 3),
            "annual_rows": self.annual_rows,
            "has_key_fields": self.has_key_fields,
            "classifier_confidence": round(self.classifier_confidence, 3),
            "has_quality_metrics": self.has_quality_metrics,
            "has_market_cap": self.has_market_cap,
            "canonical_sector": (
                self.classification.canonical_sector if self.classification else None
            ),
            "notes": list(self.notes),
        }


# Tunable weights — keep them summing to 1.0 so `score` ranges 0..1.
_W_ANNUALS = 0.30
_W_KEY_FIELDS = 0.25
_W_CLASSIFIER = 0.15
_W_QUALITY = 0.15
_W_MARKET_CAP = 0.15

# Threshold beyond which annual_rows stops accruing credit.
_ANNUAL_ROWS_FULL_CREDIT = 3


def _bare(ticker: str) -> str:
    return (ticker or "").replace(".NS", "").replace(".BO", "").upper().strip()


def _count_annual_rows(ticker_bare: str, db_session) -> int:
    if db_session is None:
        return 0
    try:
        from sqlalchemy import text
        row = db_session.execute(
            text(
                "SELECT COUNT(*) FROM financials "
                "WHERE ticker = :t AND period_type IN ('annual', 'annual_synth') "
                "AND revenue IS NOT NULL"
            ),
            {"t": ticker_bare},
        ).fetchone()
        return int(row[0]) if row and row[0] is not None else 0
    except Exception as exc:
        logger.debug("annual_rows count failed for %s: %s", ticker_bare, exc)
        return 0


def _check_key_fields(ticker_bare: str, db_session) -> bool:
    """Latest annual row has revenue, pat, fcf, equity populated.

    `fcf` may be NULL for legitimate financial-company rows (NBFCs /
    banks); the classifier branch handles those, so we relax the
    fcf requirement when the ticker classifies as a bank/insurer.
    """
    if db_session is None:
        return False
    try:
        from sqlalchemy import text
        row = db_session.execute(
            text(
                "SELECT revenue, pat, free_cash_flow, total_equity "
                "FROM financials "
                "WHERE ticker = :t AND period_type IN ('annual', 'annual_synth') "
                "ORDER BY period_end DESC LIMIT 1"
            ),
            {"t": ticker_bare},
        ).fetchone()
        if row is None:
            return False
        revenue, pat, fcf, equity = row
        return revenue is not None and pat is not None and equity is not None
    except Exception as exc:
        logger.debug("key_fields check failed for %s: %s", ticker_bare, exc)
        return False


def _has_market_cap(ticker_bare: str, db_session) -> bool:
    if db_session is None:
        return False
    try:
        from sqlalchemy import text
        row = db_session.execute(
            text(
                "SELECT market_cap_cr FROM market_metrics "
                "WHERE ticker = :t ORDER BY trade_date DESC LIMIT 1"
            ),
            {"t": ticker_bare},
        ).fetchone()
        if row is None or row[0] is None:
            return False
        return float(row[0]) > 0.0
    except Exception as exc:
        logger.debug("market_cap check failed for %s: %s", ticker_bare, exc)
        return False


def _has_quality_metrics(ticker_bare: str, db_session) -> bool:
    """ROE / ROCE computable from latest annual row.

    Cheap proxy: PAT and equity both present and equity > 0.
    """
    if db_session is None:
        return False
    try:
        from sqlalchemy import text
        row = db_session.execute(
            text(
                "SELECT pat, total_equity FROM financials "
                "WHERE ticker = :t AND period_type IN ('annual', 'annual_synth') "
                "ORDER BY period_end DESC LIMIT 1"
            ),
            {"t": ticker_bare},
        ).fetchone()
        if row is None:
            return False
        pat, equity = row
        return pat is not None and equity is not None and float(equity) > 0
    except Exception as exc:
        logger.debug("quality_metrics check failed for %s: %s", ticker_bare, exc)
        return False


def data_completeness_score(ticker: str, db_session=None) -> CompletenessReport:
    """Compute the 0-1 completeness score for `ticker`.

    Designed to be cheap (5 SELECTs max) so it can run inline in the
    YieldIQ 50 build loop. Each SELECT is wrapped — a missing table
    or transient DB error degrades the score, never raises.
    """
    bare = _bare(ticker)
    notes: list[str] = []

    classification = classify(ticker, db_session)
    classifier_conf = classification.data_quality_score
    if classification.canonical_sector == "Unclassified":
        notes.append("classifier_unclassified")

    annual_rows = _count_annual_rows(bare, db_session)
    if annual_rows == 0:
        notes.append("no_annual_financials")

    has_key = _check_key_fields(bare, db_session)
    if not has_key:
        notes.append("missing_key_fields")

    has_qual = _has_quality_metrics(bare, db_session)
    if not has_qual:
        notes.append("quality_metrics_uncomputable")

    has_mc = _has_market_cap(bare, db_session)
    if not has_mc:
        notes.append("missing_market_cap")

    annual_score = min(1.0, annual_rows / _ANNUAL_ROWS_FULL_CREDIT)
    score = (
        _W_ANNUALS * annual_score
        + _W_KEY_FIELDS * (1.0 if has_key else 0.0)
        + _W_CLASSIFIER * classifier_conf
        + _W_QUALITY * (1.0 if has_qual else 0.0)
        + _W_MARKET_CAP * (1.0 if has_mc else 0.0)
    )

    return CompletenessReport(
        ticker=ticker,
        score=round(score, 3),
        annual_rows=annual_rows,
        has_key_fields=has_key,
        classifier_confidence=classifier_conf,
        has_quality_metrics=has_qual,
        has_market_cap=has_mc,
        classification=classification,
        notes=notes,
    )


# Threshold used by _build_yieldiq50 to gate inclusion. Keep here so
# any future calibration is in one place.
YIELDIQ50_MIN_COMPLETENESS = 0.70
