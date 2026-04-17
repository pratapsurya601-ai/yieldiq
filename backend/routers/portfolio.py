# backend/routers/portfolio.py
from __future__ import annotations
import sys, os
import csv
import io
import logging
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)
_DASHBOARD_ROOT = os.path.join(_PROJECT_ROOT, "dashboard")
if _DASHBOARD_ROOT not in sys.path:
    sys.path.insert(0, _DASHBOARD_ROOT)

from backend.models.requests import AddHoldingRequest
from backend.models.responses import (
    HoldingResponse, PortfolioHealthResponse, SuccessResponse,
)
from backend.middleware.auth import get_current_user

logger = logging.getLogger("yieldiq.portfolio")

router = APIRouter(prefix="/api/v1/portfolio", tags=["portfolio"])


class ImportCSVRequest(BaseModel):
    csv_text: str
    broker: str = "zerodha"  # zerodha, groww, upstox, icici, custom


@router.get("/holdings", response_model=list[HoldingResponse])
async def get_holdings(user: dict = Depends(get_current_user)):
    """Get all portfolio holdings."""
    from portfolio import get_portfolio
    holdings = get_portfolio()
    return [
        HoldingResponse(
            ticker=h.get("ticker", ""),
            company_name=h.get("company_name", ""),
            entry_price=h.get("entry_price", 0),
            iv=h.get("iv", 0),
            mos_pct=h.get("mos_pct", 0),
            signal=h.get("signal", ""),
            sector=h.get("sector", ""),
            notes=h.get("notes", ""),
            saved_at=str(h.get("saved_at", "")),
        )
        for h in holdings
    ]


@router.post("/holdings", response_model=SuccessResponse)
async def add_holding(req: AddHoldingRequest, user: dict = Depends(get_current_user)):
    """Add stock to portfolio."""
    from portfolio import save_to_portfolio
    ok = save_to_portfolio(
        ticker=req.ticker, entry_price=req.entry_price,
        iv=req.iv, mos_pct=req.mos_pct, signal=req.signal,
        wacc=req.wacc, sector=req.sector, notes=req.notes,
        sym="₹", to_code="INR",
    )
    if not ok:
        raise HTTPException(status_code=400, detail="Failed to add holding")
    return SuccessResponse(message=f"{req.ticker} added to portfolio")


@router.delete("/holdings/{ticker}", response_model=SuccessResponse)
async def remove_holding(ticker: str, user: dict = Depends(get_current_user)):
    """Remove stock from portfolio."""
    from portfolio import remove_from_portfolio
    ok = remove_from_portfolio(ticker.upper())
    if not ok:
        raise HTTPException(status_code=404, detail=f"{ticker} not found in portfolio")
    return SuccessResponse(message=f"{ticker} removed from portfolio")


@router.post("/import")
async def import_holdings(req: ImportCSVRequest, user: dict = Depends(get_current_user)):
    """
    Bulk import holdings from a broker CSV.
    Supports: Zerodha Console, Groww, Upstox, ICICI Direct.

    Returns: { imported: int, skipped: int, errors: [] }
    """
    from portfolio import save_to_portfolio
    from backend.services import analysis_service as svc

    try:
        parsed = _parse_broker_csv(req.csv_text, req.broker)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not parse CSV: {e}")

    if not parsed:
        raise HTTPException(status_code=400, detail="No valid holdings found in CSV")

    # Free tier: 5 holdings limit; Pro/Analyst: unlimited
    tier = user.get("tier", "free")
    if tier == "free" and len(parsed) > 5:
        raise HTTPException(
            status_code=402,
            detail=f"Free tier limited to 5 holdings. Upgrade to Pro for unlimited import ({len(parsed)} holdings detected).",
        )

    imported = 0
    skipped = 0
    errors: list[str] = []

    for row in parsed:
        raw_ticker = row["ticker"]
        qty = row.get("quantity", 0)
        avg_cost = row.get("avg_cost", 0)
        if not raw_ticker or qty <= 0 or avg_cost <= 0:
            skipped += 1
            continue

        # Normalize: add .NS suffix for NSE tickers
        clean = raw_ticker.replace(".NS", "").replace(".BO", "").upper()
        full_ticker = f"{clean}.NS"

        # Try to get IV from cache (fast path — no analysis re-run)
        try:
            from backend.services.cache_service import cache as _c
            cached = _c.get(f"analysis:{full_ticker}")
            if cached and hasattr(cached, "valuation"):
                iv = cached.valuation.fair_value
                wacc_val = cached.valuation.wacc
                sector = cached.company.sector
                verdict = cached.valuation.verdict
                company_name = cached.company.company_name
            else:
                # Run analysis (will be cached for next time)
                result = svc.AnalysisService().get_full_analysis(full_ticker)
                iv = result.valuation.fair_value
                wacc_val = result.valuation.wacc
                sector = result.company.sector
                verdict = result.valuation.verdict
                company_name = result.company.company_name
            mos = (iv - avg_cost) / avg_cost * 100 if avg_cost > 0 else 0.0
        except Exception as e:
            logger.warning(f"Import: analysis failed for {full_ticker}: {e}")
            iv = 0
            wacc_val = 0.12
            sector = ""
            verdict = ""
            company_name = clean
            mos = 0

        try:
            ok = save_to_portfolio(
                ticker=full_ticker,
                entry_price=avg_cost,
                iv=iv,
                mos_pct=mos,
                signal=verdict,
                wacc=wacc_val,
                sym="\u20B9",
                to_code="INR",
                company_name=company_name,
                sector=sector,
                notes=f"Imported from {req.broker} ({qty} shares)",
            )
            if ok:
                imported += 1
            else:
                skipped += 1
                errors.append(f"{clean}: save failed")
        except Exception as e:
            skipped += 1
            errors.append(f"{clean}: {type(e).__name__}")

    return {
        "imported": imported,
        "skipped": skipped,
        "total_parsed": len(parsed),
        "errors": errors[:10],
        "tier": tier,
    }


def _parse_broker_csv(csv_text: str, broker: str) -> list[dict]:
    """
    Parse broker-specific CSV format. Returns list of dicts with:
        ticker (str), quantity (float), avg_cost (float)

    Supported brokers:
    - zerodha: Symbol,ISIN,Instrument,Qty,Avg.cost,LTP,...
    - groww:   Stock Name,ISIN,Quantity,Average buy price,...
    - upstox:  Company Name,Exchange,ISIN,Quantity,Avg Price,...
    - icici:   Stock,Qty,Avg Price,Current Price,...
    - custom:  ticker,quantity,avg_price (any header)
    """
    csv_text = csv_text.strip()
    if not csv_text:
        return []

    # Auto-detect delimiter
    first_line = csv_text.split("\n")[0]
    delim = "\t" if "\t" in first_line else ","

    reader = csv.DictReader(io.StringIO(csv_text), delimiter=delim)
    if not reader.fieldnames:
        return []

    # Normalize headers to lowercase for matching
    headers_lower = {h.lower().strip(): h for h in reader.fieldnames}

    # Broker-specific field maps (lowercase key → list of possible header names)
    broker_maps = {
        "zerodha": {
            "ticker": ["symbol", "tradingsymbol", "stock"],
            "quantity": ["qty", "quantity", "qty."],
            "avg_cost": ["avg.cost", "avg cost", "avgcost", "avg. cost", "avg price", "average price"],
        },
        "groww": {
            "ticker": ["stock name", "symbol", "ticker"],
            "quantity": ["quantity", "qty"],
            "avg_cost": ["average buy price", "avg buy price", "avg price", "avg. cost"],
        },
        "upstox": {
            "ticker": ["company name", "tradingsymbol", "symbol"],
            "quantity": ["quantity", "qty"],
            "avg_cost": ["avg price", "average price", "avg. cost"],
        },
        "icici": {
            "ticker": ["stock", "symbol", "company"],
            "quantity": ["qty", "quantity"],
            "avg_cost": ["avg price", "average price", "avg. cost"],
        },
        "custom": {
            "ticker": ["ticker", "symbol", "stock", "company"],
            "quantity": ["quantity", "qty", "shares", "units"],
            "avg_cost": ["avg_price", "avg_cost", "price", "average price", "avg price", "buy price"],
        },
    }

    field_map = broker_maps.get(broker, broker_maps["custom"])

    # Resolve to actual header names
    def _find_header(candidates: list[str]) -> str | None:
        for c in candidates:
            if c.lower() in headers_lower:
                return headers_lower[c.lower()]
        return None

    ticker_h = _find_header(field_map["ticker"])
    qty_h = _find_header(field_map["quantity"])
    cost_h = _find_header(field_map["avg_cost"])

    if not ticker_h or not qty_h or not cost_h:
        raise ValueError(
            f"Required columns not found for {broker}. "
            f"Need ticker, quantity, and average cost columns."
        )

    parsed: list[dict] = []
    for row in reader:
        try:
            raw_ticker = (row.get(ticker_h) or "").strip().upper()
            if not raw_ticker:
                continue
            # Strip exchange prefixes (e.g. "NSE:RELIANCE" → "RELIANCE")
            if ":" in raw_ticker:
                raw_ticker = raw_ticker.split(":")[-1]
            # Strip whitespace and non-printable chars
            raw_ticker = raw_ticker.strip()

            qty_str = str(row.get(qty_h, "")).replace(",", "").strip()
            cost_str = str(row.get(cost_h, "")).replace(",", "").replace("\u20B9", "").strip()

            qty = float(qty_str) if qty_str else 0
            cost = float(cost_str) if cost_str else 0

            if qty > 0 and cost > 0:
                parsed.append({
                    "ticker": raw_ticker,
                    "quantity": qty,
                    "avg_cost": cost,
                })
        except (ValueError, KeyError):
            continue

    return parsed


@router.get("/health", response_model=PortfolioHealthResponse)
async def get_portfolio_health(user: dict = Depends(get_current_user)):
    """Portfolio health score (0-100)."""
    from portfolio import get_portfolio
    from dashboard.utils.portfolio_health import calculate_portfolio_health
    holdings = get_portfolio()
    health = calculate_portfolio_health(holdings)
    return PortfolioHealthResponse(**health)
