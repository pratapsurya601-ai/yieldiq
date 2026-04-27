# backend/routers/screener.py
# Stock screener — queries Aiven pipeline DB for real-time ranked stocks.
#
# ─── market_metrics dedupe discipline (2026-04-21) ────────────────────
# The ``market_metrics`` table stores ONE ROW PER LISTING, not per
# ticker. Dual-listed tickers (NSE+BSE) therefore have TWO rows each,
# and ~70% of the table (2,652/3,780) is effectively duplicate when
# viewed through the stocks-master "one ticker, one company" lens.
# Any query that JOINs market_metrics directly against stocks (or does
# ``SELECT ... FROM market_metrics``) will inflate:
#   • COUNT(*) by up to 2×
#   • result lists (same ticker twice — BPCL regressed this way in prod)
#   • aggregate ORDER BY mm.market_cap_cr (same ticker appears twice)
# The cure is ALWAYS either (a) ``DISTINCT ON (ticker) ... ORDER BY
# ticker, trade_date DESC`` inside a CTE/subquery, or (b) ``GROUP BY
# ticker`` before JOINing. We do NOT add a unique constraint on
# market_metrics(ticker) because the duplicates have semantic meaning
# (NSE-listing row vs BSE-listing row carry different close_price,
# volume, etc.). Deduplicate at READ TIME.  See docs/ticker_format_audit.md.
# ─────────────────────────────────────────────────────────────────────
from __future__ import annotations
import logging
from fastapi import APIRouter, Depends, Query
from backend.models.responses import ScreenerResponse, ScreenerStock
from backend.middleware.auth import get_current_user, require_tier

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/screener", tags=["screener"])


def _query_stocks_from_db(min_score: int = 0, min_mos: float = -100,
                          page: int = 1, page_size: int = 25) -> tuple[list[ScreenerStock], int]:
    """Query stocks from Aiven pipeline database."""
    try:
        from data_pipeline.db import Session
        if Session is None:
            return [], 0

        from sqlalchemy import text
        db = Session()
        try:
            # Get stocks with market metrics — rank by PE (lower = more undervalued)
            # Only show quality stocks: market cap > 2000 Cr, PE between 3-50
            #
            # DISTINCT ON (mm.ticker) dedupes cross-listing rows in
            # market_metrics (NSE+BSE). See the module-level design note
            # at the top of this file. Without it, "2,907 stocks" in the
            # UI was ~1,700 real tickers counted twice.
            query = text("""
                WITH mm_dedup AS (
                    SELECT DISTINCT ON (ticker)
                        ticker, pe_ratio, pb_ratio, beta_1yr,
                        market_cap_cr, dividend_yield
                    FROM market_metrics
                    ORDER BY ticker, trade_date DESC
                )
                SELECT
                    s.ticker,
                    s.company_name,
                    mm.pe_ratio,
                    mm.pb_ratio,
                    mm.beta_1yr,
                    mm.market_cap_cr,
                    mm.dividend_yield
                FROM stocks s
                JOIN mm_dedup mm ON mm.ticker = s.ticker
                WHERE s.is_active = true
                  AND mm.pe_ratio BETWEEN 3 AND 50
                  AND mm.market_cap_cr > 2000
                ORDER BY mm.pe_ratio ASC
                LIMIT :lim OFFSET :off
            """)
            offset = (page - 1) * page_size
            rows = db.execute(query, {"lim": page_size, "off": offset}).fetchall()

            # Count must ALSO dedupe — pre-fix this was returning ~2,900
            # for a true universe of ~1,700.
            count_q = text("""
                WITH mm_dedup AS (
                    SELECT DISTINCT ON (ticker) ticker, pe_ratio, market_cap_cr
                    FROM market_metrics
                    ORDER BY ticker, trade_date DESC
                )
                SELECT COUNT(*) FROM stocks s
                JOIN mm_dedup mm ON mm.ticker = s.ticker
                WHERE s.is_active = true
                  AND mm.pe_ratio BETWEEN 3 AND 50
                  AND mm.market_cap_cr > 2000
            """)
            total = db.execute(count_q).scalar() or 0

            # PR-SCREENER-DEDUP: market_metrics can have duplicate ticker
            # rows (multi-listing on NSE+BSE, or pipeline write conflicts).
            # The JOIN above multiplies them. Dedupe in Python so the
            # output has exactly one row per ticker (first hit wins —
            # already ordered by pe_ratio so that's the cheapest).
            stocks = []
            seen: set[str] = set()
            for row in rows:
                ticker = row[0]
                if not ticker or ticker in seen:
                    continue
                seen.add(ticker)
                name = row[1] or ticker
                pe = row[2] or 0
                pb = row[3] or 0
                beta = row[4] or 1.0
                mcap = row[5] or 0

                # Simple score: lower PE + lower PB = higher score
                pe_score = max(0, min(40, int((30 - pe) / 30 * 40))) if pe > 0 else 0
                pb_score = max(0, min(30, int((5 - pb) / 5 * 30))) if pb > 0 else 0
                simple_score = pe_score + pb_score + 20  # base 20

                # Simple MoS estimate from PE (sector median ~20)
                mos = round((20 - pe) / 20 * 100, 1) if pe > 0 else 0

                stocks.append(ScreenerStock(
                    ticker=f"{ticker}.NS" if "." not in ticker else ticker,
                    score=max(0, min(100, simple_score)),
                    margin_of_safety=mos,
                ))

            return stocks, total
        finally:
            db.close()
    except Exception as e:
        logger.warning(f"Screener DB query failed: {e}")
        return [], 0


def _query_preset_from_db(preset: str, page: int = 1,
                          page_size: int = 25) -> tuple[list[ScreenerStock], int]:
    """
    Run preset screener against the in-memory analysis cache.

    Replaces the previous market_metrics DB query (which returned empty
    because that table isn't populated yet). The analysis cache has
    hundreds of stocks with real DCF data — much more useful.
    """
    try:
        from backend.services.cache_service import cache as _c

        # Filter functions per preset
        def _is_buffett(score, mos, moat, pe):
            # Quality + reasonable price + wide moat
            return score >= 60 and mos >= 0 and moat == "Wide"

        def _is_deep_value(score, mos, moat, pe):
            # Big margin of safety + decent quality
            return mos >= 30 and score >= 50

        def _is_growth_quality(score, mos, moat, pe):
            # High score (good fundamentals) + non-negative MoS
            return score >= 75

        def _is_custom(score, mos, moat, pe):
            return score >= 30  # almost everything

        filter_fn = {
            "buffett": _is_buffett,
            "deep_value": _is_deep_value,
            "growth_quality": _is_growth_quality,
            "custom": _is_custom,
        }.get(preset, _is_custom)

        # Three opinionated presets exclude clamped rows; see block
        # comment lower in this function for full reasoning.
        _PRESET_EXCLUDE_CLAMPED = {"buffett", "deep_value", "growth_quality"}
        _exclude_clamped = preset in _PRESET_EXCLUDE_CLAMPED

        candidates = []
        seen_tickers: set[str] = set()

        # Tier 1 — persistent analysis_cache DB table. This survives
        # Railway redeploys, which wipe the in-memory cache below.
        # Before this was wired, the screener always returned "No stocks
        # match" for a few minutes after every deploy because the
        # in-memory cache hadn't rehydrated yet.
        try:
            from data_pipeline.db import Session as _Session
            from sqlalchemy import text as _sql_text
            _sess = _Session()
            try:
                # PERF (egress): pull only the 5 JSON fields we need via
                # JSONB path operators instead of the whole payload (which
                # can be 100KB+ per row x ~500-3000 rows = tens of MB on a
                # cold scan). Same field semantics as the prior dict-walk.
                # FIX-SCREENER-CLAMPED (2026-04-27): exclude rows where
                # the router clamped FV/MoS to its sanity bounds (FV outside
                # [0.1×price, 3×price] OR |MoS| >= 95%) for the three named
                # presets. Pre-fix, buffett/deep-value/growth-quality were
                # full of micro-caps where MoS got pinned at the ~±95-200%
                # boundary because of FCF/EPS data-quality issues
                # (AMJLAND +215%, NILAINFRA +198%, CAPITALSFB +289%, etc.).
                # The custom screener intentionally still includes these so
                # power users can see everything.
                #
                # Primary signal: payload->valuation->data_limited = true
                # (router sets this whenever it clamps; see
                # backend/routers/analysis.py around the FV-clamp block and
                # backend/models/responses.py ValuationOutput.data_limited).
                # Fallback: |mos| < 95 — this catches any pre-flag legacy
                # cache rows that were clamped before the data_limited flag
                # was wired but still carry the boundary-pinned MoS value.
                # `_exclude_clamped` itself is hoisted to function scope so
                # the tier-2 in-memory path below sees the same gate.
                _rows = _sess.execute(_sql_text(
                    """
                    SELECT
                      ticker,
                      (payload->'quality'->>'yieldiq_score')::float    AS score,
                      (payload->'valuation'->>'margin_of_safety')::float AS mos,
                      (payload->'quality'->>'moat')                    AS moat,
                      (payload->'valuation'->>'eps_ttm')::float        AS eps_ttm,
                      (payload->'valuation'->>'current_price')::float  AS current_price,
                      COALESCE((payload->'valuation'->>'data_limited')::boolean, false) AS data_limited
                    FROM analysis_cache
                    WHERE computed_at > now() - interval '48 hours'
                    """
                )).fetchall()
            finally:
                _sess.close()
            for _r in _rows:
                _ticker = _r[0]
                score = _r[1] or 0
                mos = _r[2] or 0
                moat = _r[3] or "None"
                pe = None
                try:
                    eps = _r[4] or 0
                    cp = _r[5] or 0
                    if eps > 0 and cp > 0:
                        pe = cp / eps
                except Exception:
                    pass
                _data_limited = bool(_r[6]) if len(_r) > 6 else False
                # Skip rows where MoS got clamped (data-quality issues)
                # for the three opinionated presets. See block comment above.
                if _exclude_clamped and (_data_limited or abs(mos) >= 95):
                    continue
                full_ticker = _ticker if "." in _ticker else f"{_ticker}.NS"
                # Dedup by bare ticker (strip .NS/.BO) so NSE+BSE listings
                # of the same company and raw-vs-suffixed cache entries
                # can't both be counted. Pre-fix this was producing
                # 899 > 550-Nifty-500-universe in prod.
                _dedup_key = full_ticker.split(".")[0]
                if filter_fn(score, mos, moat, pe) and _dedup_key not in seen_tickers:
                    candidates.append((full_ticker, score, mos))
                    seen_tickers.add(_dedup_key)
        except Exception as _exc:
            logger.info("analysis_cache scan skipped: %s", _exc)

        # Tier 2 — in-memory cache. Catches anything freshly computed
        # on this worker but not yet in the persistent table.
        for key in list(_c._store.keys()):
            if not key.startswith("analysis:") or ".NS" not in key:
                continue
            val = _c.get(key)
            if not val or not hasattr(val, "valuation"):
                continue
            v = val.valuation
            q = val.quality
            score = q.yieldiq_score or 0
            mos = v.margin_of_safety or 0
            moat = q.moat or "None"
            pe = None
            try:
                eps = getattr(v, "eps_ttm", None)
                if eps and eps > 0 and v.current_price > 0:
                    pe = v.current_price / eps
            except Exception:
                pe = None

            # Mirror the tier-1 clamp-exclusion for the named presets.
            # See block comment in the analysis_cache scan above.
            _dl = bool(getattr(v, "data_limited", False))
            if _exclude_clamped and (_dl or abs(mos) >= 95):
                continue

            _dedup_key2 = val.ticker.split(".")[0]
            if filter_fn(score, mos, moat, pe) and _dedup_key2 not in seen_tickers:
                candidates.append((val.ticker, score, mos))
                seen_tickers.add(_dedup_key2)

        # Sort by score (descending) then MoS
        candidates.sort(key=lambda x: (x[1], x[2]), reverse=True)

        # Pagination
        total = len(candidates)
        start = (page - 1) * page_size
        end = start + page_size
        page_items = candidates[start:end]

        stocks = [
            ScreenerStock(
                ticker=ticker,
                score=int(round(score)),
                margin_of_safety=round(mos, 1),
            )
            for ticker, score, mos in page_items
        ]
        return stocks, total
    except Exception as e:
        logger.warning(f"Screener preset query failed: {e}", exc_info=True)
        return [], 0


@router.get("/run", response_model=ScreenerResponse)
async def run_screener(
    min_score: int = Query(0, ge=0, le=100),
    min_mos: float = Query(-100),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    user: dict = Depends(get_current_user),
):
    """Run custom screener. Available to all users."""
    stocks, total = _query_stocks_from_db(min_score, min_mos, page, page_size)

    # Filter by min_score and min_mos
    if min_score > 0:
        stocks = [s for s in stocks if s.score >= min_score]
    if min_mos > -100:
        stocks = [s for s in stocks if s.margin_of_safety >= min_mos]

    return ScreenerResponse(
        results=stocks, total=total, page=page, page_size=page_size,
        filter_applied={"min_score": min_score, "min_mos": min_mos},
    )


@router.get("/preset/{preset_name}", response_model=ScreenerResponse)
async def run_preset(
    preset_name: str,
    user: dict = Depends(get_current_user),
):
    """Run a pre-built screener preset. Available to all users.

    Frontend sends slug-style preset names with dashes
    (``deep-value``, ``growth-quality``) — the in-memory filter dispatch
    below keys on underscores (``deep_value``, ``growth_quality``).
    Without this normalisation, BOTH slugs fell through to ``_is_custom``
    (``score >= 30``) and returned an identical, over-inflated count
    (899/899 in prod on 2026-04-22). Fixes P0-#5 on the Day-1 audit.
    """
    api_preset = preset_name.replace("-", "_")
    stocks, total = _query_preset_from_db(api_preset)

    return ScreenerResponse(
        results=stocks, total=total, page=1, page_size=25,
        filter_applied={"preset": preset_name},
    )


@router.get("/export", response_model=ScreenerResponse)
async def export_screener(
    preset: str = Query("custom"),
    min_score: int = Query(0, ge=0, le=100),
    min_mos: float = Query(-100),
    user: dict = Depends(require_tier("starter")),
):
    """Export screener results (up to 500 stocks). Starter+ only."""
    if preset != "custom":
        api_preset = preset.replace("-", "_")
        stocks, total = _query_preset_from_db(api_preset, page=1, page_size=500)
    else:
        stocks, total = _query_stocks_from_db(min_score, min_mos, page=1, page_size=500)

    # Apply filters
    if min_score > 0:
        stocks = [s for s in stocks if s.score >= min_score]
    if min_mos > -100:
        stocks = [s for s in stocks if s.margin_of_safety >= min_mos]

    return ScreenerResponse(
        results=stocks[:500], total=len(stocks), page=1, page_size=500,
        filter_applied={"preset": preset, "min_score": min_score, "min_mos": min_mos, "export": True},
    )
