# backend/routers/tax.py
# ═══════════════════════════════════════════════════════════════
# Capital Gains Tax endpoints — Analyst tier gated.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import logging
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from backend.middleware.auth import get_current_user
from backend.services.tax_service import (
    compute_tax_summary,
    parse_zerodha_tax_pnl_csv,
    export_itr_csv,
)

logger = logging.getLogger("yieldiq.tax")

router = APIRouter(prefix="/api/v1/tax", tags=["tax"])


class TaxComputeRequest(BaseModel):
    trades: list[dict]


class TaxImportRequest(BaseModel):
    csv_text: str
    broker: str = "zerodha"


def _require_paid_tier(user: dict) -> None:
    """Tax reports require Analyst tier (Rs 799/mo). Pro tier (Rs 299) gets computation but no CSV export."""
    tier = user.get("tier", "free")
    if tier == "free":
        raise HTTPException(
            status_code=402,
            detail="Capital gains tax reports require a paid plan. Upgrade to Pro (Rs 299/mo) or Analyst (Rs 799/mo).",
        )


def _require_analyst_tier(user: dict) -> None:
    tier = user.get("tier", "free")
    if tier not in ("analyst",):
        raise HTTPException(
            status_code=402,
            detail="ITR-ready CSV export requires Analyst tier (Rs 799/mo).",
        )


@router.post("/compute")
async def compute_tax(req: TaxComputeRequest, user: dict = Depends(get_current_user)):
    """
    Compute STCG/LTCG tax summary for a list of trades.

    Each trade must have: ticker, quantity, buy_date, buy_price, sell_date, sell_price.

    Available to Pro and Analyst tiers (free tier locked out).
    """
    _require_paid_tier(user)

    if not req.trades:
        raise HTTPException(status_code=400, detail="No trades provided")

    try:
        summary = compute_tax_summary(req.trades)
        return summary
    except Exception as e:
        logger.warning(f"tax compute failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Tax computation failed")


@router.post("/import")
async def import_broker_csv(req: TaxImportRequest, user: dict = Depends(get_current_user)):
    """
    Parse broker tax P&L CSV (Zerodha format) and compute tax summary.
    """
    _require_paid_tier(user)

    try:
        if req.broker == "zerodha":
            trades = parse_zerodha_tax_pnl_csv(req.csv_text)
        else:
            # Other brokers use same parser for now (flexible column matching)
            trades = parse_zerodha_tax_pnl_csv(req.csv_text)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.warning(f"tax import parse failed: {e}")
        raise HTTPException(status_code=400, detail="Could not parse CSV")

    if not trades:
        raise HTTPException(status_code=400, detail="No valid trades found in CSV")

    try:
        summary = compute_tax_summary(trades)
        return summary
    except Exception as e:
        logger.warning(f"tax import compute failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Tax computation failed")


@router.post("/export-csv", response_class=PlainTextResponse)
async def export_csv(req: TaxComputeRequest, user: dict = Depends(get_current_user)):
    """
    Export enriched trades as ITR-ready CSV.
    Analyst tier only.
    """
    _require_analyst_tier(user)

    try:
        summary = compute_tax_summary(req.trades)
        csv_text = export_itr_csv(summary["trades"])
        return PlainTextResponse(
            content=csv_text,
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=yieldiq_capital_gains.csv"},
        )
    except Exception as e:
        logger.warning(f"tax export failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Export failed")
