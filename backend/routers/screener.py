# backend/routers/screener.py
from __future__ import annotations
from fastapi import APIRouter, Depends, Query
from backend.models.responses import ScreenerResponse, ScreenerStock
from backend.middleware.auth import get_current_user, require_tier

router = APIRouter(prefix="/api/v1/screener", tags=["screener"])


@router.get("/run", response_model=ScreenerResponse)
async def run_screener(
    min_score: int = Query(0, ge=0, le=100),
    min_mos: float = Query(-100),
    moat: str = Query(None),
    sector: str = Query(None),
    fcf_positive: bool = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: dict = Depends(require_tier("starter")),
):
    """Run custom screener with filters. Starter+ only."""
    try:
        import pandas as pd
        from pathlib import Path
        _path = Path(__file__).resolve().parent.parent.parent / "data" / "screener_results.csv"
        if not _path.exists():
            return ScreenerResponse(filter_applied={"min_score": min_score})

        df = pd.read_csv(_path)
        _score_col = next((c for c in df.columns if c.lower() in ("score", "yieldiq_score")), None)
        _mos_col = next((c for c in df.columns if c.lower() in ("mos", "mos_pct")), None)
        _ticker_col = next((c for c in df.columns if c.lower() in ("ticker", "symbol")), df.columns[0])

        if _score_col and min_score > 0:
            df = df[df[_score_col] >= min_score]
        if _mos_col and min_mos > -100:
            df = df[df[_mos_col] >= min_mos]

        total = len(df)
        start = (page - 1) * page_size
        df = df.iloc[start:start + page_size]

        stocks = []
        for _, row in df.iterrows():
            stocks.append(ScreenerStock(
                ticker=str(row.get(_ticker_col, "")),
                score=int(row.get(_score_col, 0)) if _score_col else 0,
                margin_of_safety=float(row.get(_mos_col, 0)) if _mos_col else 0,
            ))

        return ScreenerResponse(
            results=stocks, total=total, page=page, page_size=page_size,
            filter_applied={"min_score": min_score, "min_mos": min_mos},
        )
    except Exception:
        return ScreenerResponse()


@router.get("/preset/{preset_name}", response_model=ScreenerResponse)
async def run_preset(
    preset_name: str,
    user: dict = Depends(get_current_user),
):
    """Run a pre-built screener preset."""
    presets = {
        "buffett": {"min_score": 60, "min_mos": 20},
        "deep_value": {"min_score": 60, "min_mos": 30},
        "growth_quality": {"min_score": 80, "min_mos": 0},
    }
    filters = presets.get(preset_name, {"min_score": 50})
    return await run_screener(
        min_score=filters.get("min_score", 0),
        min_mos=filters.get("min_mos", -100),
        user=user,
    )
