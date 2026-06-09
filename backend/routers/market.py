# backend/routers/market.py
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy import text

from backend.models.responses import MarketPulseResponse, SectorOverviewItem
from backend.services.data_service import DataService
from backend.services.cache_service import cache
from backend.middleware.auth import get_current_user

router = APIRouter(prefix="/api/v1/market", tags=["market"])
data_service = DataService()
log = logging.getLogger("yieldiq.market")

# IST tzinfo for the as_of timestamp and the stale-data threshold check.
# Using a fixed offset is fine: India never observes DST and the offset
# has been stable since 1947.
_IST = timezone(timedelta(hours=5, minutes=30))


def _pipeline_session():
    try:
        from data_pipeline.db import Session as PipelineSession
        if PipelineSession is not None:
            return PipelineSession()
    except Exception:
        pass
    return None


# ── Sparkline enrichment for /pulse (2026-06-09) ───────────────
# Tiny 7-day close-price series per MarketsStrip tile, populated from
# `nse_index_history` (broad + sectoral indices). Each MarketIndex on
# the response carries its own `sparkline_7d` list so the frontend tile
# can render the inline trend without a second fetch round-trip.
#
# Mapping is name-based (case-insensitive substring match against the
# canonical NSE index name). The `data_service.get_market_pulse()`
# tiles use the human-friendly names "NIFTY 50" / "SENSEX" / "NIFTY
# Bank"; the `nse_index_history` table stores e.g. "Nifty 50" / "Nifty
# Bank". A small alias map handles the SENSEX hop (BSE index, not in
# the NSE history table — leaves the series empty rather than faking
# data).

# Tile-name → nse_index_history.index_name. Keys are uppercase-stripped
# substrings; the lookup walks the keyspace and stops at the first hit.
# Values are the EXACT case stored in the table.
_INDEX_NAME_MAP: Dict[str, str] = {
    "NIFTY 50": "Nifty 50",
    "NIFTY BANK": "Nifty Bank",
    "NIFTY IT": "Nifty IT",
    "NIFTY AUTO": "Nifty Auto",
    "NIFTY PHARMA": "Nifty Pharma",
    "NIFTY FMCG": "Nifty FMCG",
    "NIFTY METAL": "Nifty Metal",
    "NIFTY ENERGY": "Nifty Energy",
    "NIFTY MIDCAP 100": "Nifty Midcap 100",
}


def _canonical_index_name(label: str) -> str | None:
    """Map a tile label (e.g. "NIFTY 50", "NIFTY Bank") to the case the
    nse_index_history table uses. None for tiles not in the index map
    (SENSEX — BSE; USD/INR / GOLD — macro feeds)."""
    if not label:
        return None
    upper = label.upper().strip()
    # Exact uppercase-key match first (cheap path for the common case).
    if upper in _INDEX_NAME_MAP:
        return _INDEX_NAME_MAP[upper]
    # Substring match — catches "NIFTY 50 INDEX" or any future suffix.
    for key, canonical in _INDEX_NAME_MAP.items():
        if key in upper:
            return canonical
    return None


def _fetch_index_sparklines(canonical_names: List[str]) -> Dict[str, List[float]]:
    """Pull last 7 daily closes per canonical index name (oldest→newest).

    Returns {} on any database/import failure — the /pulse endpoint
    treats a missing sparkline as "no trend available" and renders the
    tile as it did pre-PR. Never raises.
    """
    if not canonical_names:
        return {}
    sess = _pipeline_session()
    if sess is None:
        return {}
    try:
        rows = sess.execute(
            text(
                """
                SELECT index_name, trade_date, close
                FROM nse_index_history
                WHERE index_name = ANY(:names)
                  AND close IS NOT NULL
                  AND trade_date >= :since
                ORDER BY index_name, trade_date
                """
            ),
            {
                "names": canonical_names,
                # 14-day lookback so weekends + a holiday still leave
                # ≥ 7 trading days in the slice.
                "since": (datetime.now(_IST).date() - timedelta(days=14)),
            },
        ).fetchall()

        buckets: Dict[str, List[float]] = {n: [] for n in canonical_names}
        for name, _trade_date, close_val in rows:
            if name in buckets:
                try:
                    buckets[name].append(float(close_val))
                except (TypeError, ValueError):
                    continue

        # Keep the trailing 7 entries per index (oldest→newest). Drop
        # series shorter than 2 — Sparkline component renders null for
        # those anyway.
        return {
            name: vals[-7:]
            for name, vals in buckets.items()
            if len(vals) >= 2
        }
    except Exception as exc:  # pragma: no cover — DB outage path
        log.debug("index sparkline fetch failed: %s", exc)
        return {}
    finally:
        try:
            sess.close()
        except Exception:
            pass


def _enrich_pulse_with_sparklines(
    pulse: MarketPulseResponse,
) -> MarketPulseResponse:
    """Attach `sparkline_7d` arrays to each index tile in-place.

    Macro tiles (USD/INR, GOLD, SILVER, CRUDE, India 10Y) lack a
    persisted daily-history table — they're sourced from yfinance
    directly via :func:`_macro_sparkline_yf` and surfaced through the
    response's `macro_sparklines` dict. SENSEX (BSE index) is also
    routed through the yfinance helper because the NSE bhavcopy that
    feeds `nse_index_history` does not include the BSE composite.
    """
    if not pulse or not pulse.indices:
        return pulse
    # Build lookup: tile-name → canonical history-table name.
    lookups: Dict[str, str] = {}
    for idx in pulse.indices:
        canonical = _canonical_index_name(idx.name)
        if canonical:
            lookups[idx.name] = canonical
    if not lookups:
        return pulse
    series_by_canonical = _fetch_index_sparklines(list(set(lookups.values())))
    for idx in pulse.indices:
        canonical = lookups.get(idx.name)
        if not canonical:
            continue
        series = series_by_canonical.get(canonical)
        if series:
            idx.sparkline_7d = series
    return pulse


# ── Macro sparkline fetch (USD/INR, India 10Y, Gold, Silver, Crude, SENSEX) ──
# `nse_index_history` only carries NSE-listed indices, so the macro
# tiles + the BSE SENSEX tile sit outside its coverage. We pull a short
# (≤ 10 trading day) close-price series from yfinance per symbol and
# cache the result for 24h in the shared CacheService. The cache key is
# per-symbol so a partial fetch (one yfinance call rate-limited, four
# OK) still surfaces what it can on the next /pulse hit.
#
# yfinance symbol map — exposed module-level so tests can patch the
# fetch path without touching the (private) helper.
_MACRO_YF_SYMBOLS: Dict[str, str] = {
    "USDINR":   "USDINR=X",
    "INDIA10Y": "^TNX",      # US 10Y proxy — see comment in usage site
    "GOLD":     "GC=F",
    "SILVER":   "SI=F",
    "CRUDE":    "BZ=F",      # Brent — matches MacroService crude_usd
    "SENSEX":   "^BSESN",
}


def _macro_sparkline_yf(symbol: str, days: int = 7) -> Optional[List[float]]:
    """Return last `days` daily closes (oldest→newest) for a yfinance
    symbol, or None on failure / insufficient data.

    Cached 24h per symbol. yfinance rate limits aggressively when called
    in a tight loop, so we serve the cache aggressively; the data only
    changes once per trading day anyway.
    """
    cache_key = f"macro_spark:{symbol}:{days}"
    try:
        cached = cache.get(cache_key)
    except Exception:
        cached = None
    if cached is not None:
        return cached if cached else None  # cached [] sentinel → no data
    try:
        import yfinance as yf
        # Pull `days * 2` calendar days of history so weekends + 1 IST
        # holiday still leave ≥ `days` valid closes.
        hist = yf.Ticker(symbol).history(
            period=f"{max(days * 2, 14)}d",
            interval="1d",
            auto_adjust=False,
        )
        if hist is None or hist.empty or "Close" not in hist:
            try:
                cache.set(cache_key, [], ttl=24 * 3600)
            except Exception:
                pass
            return None
        closes = [float(v) for v in hist["Close"].dropna().tolist() if v is not None]
        if len(closes) < 2:
            try:
                cache.set(cache_key, [], ttl=24 * 3600)
            except Exception:
                pass
            return None
        series = closes[-days:]
        try:
            cache.set(cache_key, series, ttl=24 * 3600)
        except Exception:
            pass
        return series
    except Exception as exc:
        log.debug("_macro_sparkline_yf(%s) failed: %s", symbol, exc)
        return None


def _change_pct_from_series(series: Optional[List[float]]) -> Optional[float]:
    """Last-vs-previous percent change from a `_macro_sparkline_yf`-style
    series. Returns None when the series is too short or the previous
    close is non-positive (division would be undefined / misleading)."""
    if not series or len(series) < 2:
        return None
    prev = series[-2]
    if not prev or prev <= 0:
        return None
    try:
        return round((series[-1] - prev) / prev * 100, 2)
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def _build_macro_sparklines() -> Tuple[Dict[str, List[float]], Dict[str, Optional[float]]]:
    """Fetch all macro sparkline series + derived change_pct values.

    Returns ``(sparklines_dict, change_pcts_dict)`` where:
    - sparklines_dict is the compact mapping (only keys with usable
      data) suitable for direct assignment to ``MarketPulseResponse
      .macro_sparklines``.
    - change_pcts_dict carries derived 24h % moves for USD/INR and
      INDIA10Y so the same yfinance fetch backs both the inline
      sparkline AND the pct badge — single source of truth, no second
      round-trip.

    Never raises. Either dict can be empty when yfinance is unavailable
    (the response degrades to its pre-PR shape — tiles render values
    without sparklines).
    """
    sparklines: Dict[str, List[float]] = {}
    derived: Dict[str, Optional[float]] = {
        "usd_inr_change_pct": None,
        "risk_free_change_pct": None,
    }
    for tile_key, yf_sym in _MACRO_YF_SYMBOLS.items():
        series = _macro_sparkline_yf(yf_sym)
        if series:
            sparklines[tile_key] = series
        # Derive the change_pct for the two tiles the frontend was
        # hardcoding to null pre-PR. Commodity change_pct already comes
        # from MacroService (fast_info-derived), so we don't override.
        if tile_key == "USDINR":
            derived["usd_inr_change_pct"] = _change_pct_from_series(series)
        elif tile_key == "INDIA10Y":
            derived["risk_free_change_pct"] = _change_pct_from_series(series)
    return sparklines, derived


@router.get("/pulse", response_model=MarketPulseResponse)
async def get_market_pulse(
    user: dict = Depends(get_current_user),
    include_macro: bool = Query(default=False),
):
    """
    Market indices + fear/greed.

    Pass ``?include_macro=true`` to additionally fetch FII/DII
    flows, FX, commodities and the risk-free rate. Macro fields
    are optional and default to ``null`` — clients unaware of
    them continue to work.
    """
    # Tier-0 RAW dict cache. Data is identical for all users
    # (market indices, not user-specific) so a single shared cache
    # entry is safe. Auth is still enforced — the cache check
    # runs AFTER get_current_user via Depends.
    _raw_key = f"market:pulse:raw:{int(bool(include_macro))}"
    try:
        _raw = cache.get(_raw_key)
    except Exception:
        _raw = None
    if _raw is not None:
        return JSONResponse(
            content=_raw,
            headers={
                "X-Cache": "HIT-MEM-RAW",
                # Auth-gated endpoint — use private so Vercel's
                # shared edge cache does not cache responses
                # across authenticated users. 60s max-age still
                # lets the browser avoid repeat calls during
                # page navigation.
                "Cache-Control": "private, max-age=60",
            },
        )

    base = data_service.get_market_pulse()

    # Enrich tile-by-tile with 7d sparkline series from
    # nse_index_history. Safe to run on every miss — the helper bails
    # silently when the DB is unavailable (offline tests) and skips
    # tiles with no matching canonical name (SENSEX, USD/INR, etc.).
    try:
        base = _enrich_pulse_with_sparklines(base)
    except Exception as _exc:  # pragma: no cover — defensive only
        log.debug("sparkline enrichment skipped: %s", _exc)

    if not include_macro:
        try:
            _dump = base.model_dump(mode="json") if hasattr(base, "model_dump") else base
            cache.set(_raw_key, _dump, ttl=60)
        except Exception:
            pass
        return base

    try:
        from backend.services.macro_service import MacroService
        svc = MacroService()
        db = _pipeline_session()
        try:
            snapshot = svc.get_snapshot(cache, db)
        finally:
            if db is not None:
                try:
                    db.close()
                except Exception:
                    pass

        base_dict = base.model_dump()
        allowed = set(MarketPulseResponse.model_fields.keys())
        for k, v in (snapshot or {}).items():
            if k in allowed:
                base_dict[k] = v
        # Attach AI summary if already cached (24h) — avoid
        # blocking the /pulse call on a live LLM roundtrip.
        cached_summary = cache.get("macro:ai_summary")
        if cached_summary:
            base_dict["ai_summary"] = cached_summary

        # ── Macro sparklines + derived change_pct (2026-06-09) ────────
        # Populates the 5 non-index MarketsStrip tiles (USD/INR, India
        # 10Y, GOLD, SILVER, CRUDE) with 7-day inline-trend series, plus
        # the SENSEX index tile (BSE composite, not in nse_index_history).
        # Also derives 24h % change for USD/INR and India 10Y so those
        # tiles get a delta badge — the rest of the strip already has
        # one via the MacroService snapshot.
        try:
            macro_sparks, derived_pcts = _build_macro_sparklines()
            if macro_sparks:
                # Promote SENSEX series onto the matching index tile
                # (frontend reads `idx.sparkline_7d` for indices and
                # only looks at `macro_sparklines` for the non-index
                # tiles). Strip SENSEX out of the dict afterwards so
                # the wire payload stays compact.
                sensex_series = macro_sparks.pop("SENSEX", None)
                if sensex_series:
                    # base.indices was just turned into base_dict via
                    # model_dump — patch the dict form so the final
                    # MarketPulseResponse(**base_dict) below picks it up.
                    for idx_dict in base_dict.get("indices", []) or []:
                        name = (idx_dict.get("name") or "").upper()
                        if "SENSEX" in name and not idx_dict.get("sparkline_7d"):
                            idx_dict["sparkline_7d"] = sensex_series
                            break
                if macro_sparks:
                    base_dict["macro_sparklines"] = macro_sparks
            # Only overwrite the derived pct fields when the helper
            # returned a number — never clobber an already-populated
            # value with None.
            if derived_pcts.get("usd_inr_change_pct") is not None:
                base_dict["usd_inr_change_pct"] = derived_pcts["usd_inr_change_pct"]
            if derived_pcts.get("risk_free_change_pct") is not None:
                base_dict["risk_free_change_pct"] = derived_pcts["risk_free_change_pct"]
        except Exception as _spark_exc:  # pragma: no cover — defensive
            log.debug("macro sparkline build skipped: %s", _spark_exc)

        # ── INR-conversion for Gold/Silver tile display (2026-06-09) ─
        # MarketsStrip shows commodities as ₹X/10g for the Indian
        # retail audience. Gold/silver come in USD/troy-ounce; one
        # troy ounce is 31.1035 grams. Render value = USD price ×
        # USD/INR × (10 / 31.1035). Skip silently when either input
        # is missing — the tile then degrades to USD or to "—".
        try:
            _usd_inr = base_dict.get("usd_inr")
            if _usd_inr:
                _gold_usd = base_dict.get("gold_usd")
                if _gold_usd:
                    base_dict["gold_inr_per_10g"] = round(
                        float(_gold_usd) * float(_usd_inr) * (10.0 / 31.1035), 0
                    )
                _silver_usd = base_dict.get("silver_usd")
                if _silver_usd:
                    base_dict["silver_inr_per_10g"] = round(
                        float(_silver_usd) * float(_usd_inr) * (10.0 / 31.1035), 0
                    )
        except (TypeError, ValueError) as _conv_exc:
            log.debug("commodity INR-conv skipped: %s", _conv_exc)

        out = MarketPulseResponse(**base_dict)
        try:
            cache.set(_raw_key, out.model_dump(mode="json"), ttl=60)
        except Exception:
            pass
        return out
    except Exception as exc:
        log.debug("Macro merge failed: %s", exc)
        return base


@router.get("/macro-summary")
async def get_macro_summary(user: dict = Depends(get_current_user)):
    """
    AI-generated 2-sentence market commentary. Cached 24 hours.
    Separate from ``/pulse`` so the main market strip never waits
    on an LLM roundtrip.
    """
    try:
        from backend.services.macro_service import MacroService
        svc = MacroService()
        snapshot = cache.get("macro:snapshot") or {}
        summary = svc.get_ai_summary(snapshot, cache)
        return {"summary": summary}
    except Exception as exc:
        log.debug("macro-summary failed: %s", exc)
        return {"summary": None}


@router.get("/sectors", response_model=list[SectorOverviewItem])
async def get_sector_overview(user: dict = Depends(get_current_user)):
    """Sector valuation summary."""
    return data_service.get_sector_overview()


# ── Today's Movers (2026-06-09) ────────────────────────────────
# Daily-engagement widget for /home — top N gainers + losers from the
# selected cohort (default NIFTY 500). Powered by the most-recent two
# trading days in `daily_prices`. NEUTRAL framing: this is a market-data
# surface, not a recommendation engine. The router copy never uses
# "buy"/"sell"/"pick" verbs — only "% change".

def _compute_today_movers(cohort: str, limit: int) -> dict:
    """Query the two most recent trading days and rank by % change.

    Returns the JSON dict the endpoint streams. Pure function so the
    cache layer in `get_today_movers` can dump it directly.
    """
    cohort_norm = (cohort or "nifty500").lower()
    # Only NIFTY 500 is wired for v1. Other cohorts fall back to the
    # NIFTY 500 universe rather than 500-erroring on the frontend; the
    # cohort param is forward-compat for nifty50 / nifty100.
    nifty_index = "NIFTY 500"
    if cohort_norm == "nifty50":
        nifty_index = "NIFTY 50"
    elif cohort_norm == "nifty100":
        nifty_index = "NIFTY 100"

    try:
        from data_pipeline.db import Session as PipelineSession
    except Exception as exc:
        log.warning("today-movers: pipeline session import failed: %s", exc)
        return {"as_of": None, "gainers": [], "losers": [], "stale": True}

    if PipelineSession is None:
        return {"as_of": None, "gainers": [], "losers": [], "stale": True}

    sess = PipelineSession()
    try:
        # Pull the two most-recent distinct trade dates that intersect
        # the cohort. Selecting from the cohort-filtered subquery means
        # we ignore data-load lag on stocks outside the cohort.
        row = sess.execute(
            text(
                """
                SELECT DISTINCT dp.trade_date
                FROM daily_prices dp
                JOIN nse_sector_constituents nc
                  ON UPPER(nc.ticker) = UPPER(dp.ticker)
                WHERE nc.nifty_index = :idx
                ORDER BY dp.trade_date DESC
                LIMIT 2
                """
            ),
            {"idx": nifty_index},
        ).fetchall()
        if len(row) < 2:
            return {"as_of": None, "gainers": [], "losers": [], "stale": True}

        latest_date, prev_date = row[0][0], row[1][0]

        # Stale-data check: if the latest trading day is more than 24h
        # behind today's IST date during market hours, the bhavcopy
        # ingest is lagging and we surface an empty list with a hint.
        now_ist = datetime.now(_IST)
        age_days = (now_ist.date() - latest_date).days
        # Threshold: 4 calendar days handles weekends + 1 public
        # holiday tolerantly; beyond that the pipeline really is stale.
        is_stale = age_days > 4

        # Pull both days for every cohort ticker in a single query.
        # Pivoting via FILTER aggregates avoids two round-trips and any
        # python-side join. `s.is_active` filters delisted tickers.
        rows = sess.execute(
            text(
                """
                SELECT
                    dp.ticker,
                    s.company_name,
                    MAX(CASE WHEN dp.trade_date = :latest THEN dp.close_price END)  AS close_latest,
                    MAX(CASE WHEN dp.trade_date = :prev   THEN dp.close_price END)  AS close_prev
                FROM daily_prices dp
                JOIN nse_sector_constituents nc
                  ON UPPER(nc.ticker) = UPPER(dp.ticker)
                LEFT JOIN stocks s
                  ON UPPER(s.ticker) = UPPER(dp.ticker)
                WHERE nc.nifty_index = :idx
                  AND dp.trade_date IN (:latest, :prev)
                  AND COALESCE(s.is_active, TRUE) = TRUE
                GROUP BY dp.ticker, s.company_name
                """
            ),
            {"idx": nifty_index, "latest": latest_date, "prev": prev_date},
        ).fetchall()

        movers: list[dict] = []
        for tk, name, close_l, close_p in rows:
            # Drop tickers with a null day (suspended / fresh listing).
            # Drop non-positive prev_close (would explode the ratio).
            if close_l is None or close_p is None:
                continue
            try:
                cl, cp = float(close_l), float(close_p)
            except (TypeError, ValueError):
                continue
            if cp <= 0:
                continue
            change_pct = (cl - cp) / cp * 100
            # Clip clearly-broken data points (>50% single-day moves are
            # almost always corporate-action splits that the bhavcopy
            # adjustment lagged on). Surfacing them as #1 mover misleads.
            if abs(change_pct) > 50:
                continue
            movers.append(
                {
                    "ticker": (tk or "").replace(".NS", ""),
                    "company_name": name or tk or "",
                    "change_pct": round(change_pct, 2),
                    "close": round(cl, 2),
                    "prev_close": round(cp, 2),
                }
            )

        gainers = sorted(movers, key=lambda m: m["change_pct"], reverse=True)[:limit]
        losers = sorted(movers, key=lambda m: m["change_pct"])[:limit]

        as_of_iso = datetime.combine(latest_date, datetime.min.time()).replace(
            hour=15, minute=30, tzinfo=_IST
        ).isoformat()

        return {
            "as_of": as_of_iso,
            "gainers": gainers if not is_stale else [],
            "losers": losers if not is_stale else [],
            "stale": is_stale,
            "cohort": cohort_norm,
        }
    finally:
        try:
            sess.close()
        except Exception:
            pass


@router.get("/today-movers")
async def get_today_movers(
    user: dict = Depends(get_current_user),
    cohort: str = Query(default="nifty500"),
    limit: int = Query(default=5, ge=1, le=20),
):
    """Top gainers / losers from the cohort, computed off the two most-
    recent trading days in `daily_prices`.

    Cached 60s at the router level — this is the home-page hot path and
    the underlying data only refreshes once a day post-close. Cohort +
    limit are part of the cache key so distinct calls stay isolated.
    """
    cache_key = f"market:today_movers:{cohort.lower()}:{int(limit)}"
    try:
        cached = cache.get(cache_key)
    except Exception:
        cached = None
    if cached is not None:
        return JSONResponse(
            content=cached,
            headers={
                "X-Cache": "HIT-MEM-MOVERS",
                "Cache-Control": "private, max-age=60",
            },
        )

    payload = _compute_today_movers(cohort, limit)
    try:
        cache.set(cache_key, payload, ttl=60)
    except Exception:
        pass
    return JSONResponse(
        content=payload,
        headers={"Cache-Control": "private, max-age=60"},
    )
