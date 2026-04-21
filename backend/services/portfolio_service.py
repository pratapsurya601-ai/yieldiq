# backend/services/portfolio_service.py
# ═══════════════════════════════════════════════════════════════
# Portfolio CRUD — Supabase-backed with per-user isolation.
# Table: holdings (user_email PK composite)
#
# SQL to create the table (run once in Supabase SQL editor):
# CREATE TABLE IF NOT EXISTS holdings (
#     id            BIGSERIAL PRIMARY KEY,
#     user_email    TEXT NOT NULL,
#     ticker        TEXT NOT NULL,
#     company_name  TEXT DEFAULT '',
#     entry_price   DOUBLE PRECISION NOT NULL,
#     iv            DOUBLE PRECISION DEFAULT 0,
#     mos_pct       DOUBLE PRECISION DEFAULT 0,
#     signal        TEXT DEFAULT '',
#     wacc          DOUBLE PRECISION DEFAULT 0,
#     sector        TEXT DEFAULT '',
#     notes         TEXT DEFAULT '',
#     saved_at      TIMESTAMPTZ DEFAULT NOW(),
#     UNIQUE(user_email, ticker)
# );
# CREATE INDEX IF NOT EXISTS idx_holdings_email ON holdings(user_email);
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import logging
from datetime import datetime, timezone

logger = logging.getLogger("yieldiq.portfolio")


def _get_supabase():
    try:
        from db.supabase_client import get_admin_client
        return get_admin_client()
    except Exception as e:
        logger.warning(f"Supabase client unavailable: {e}")
        return None


def save_holding(
    user_email: str,
    ticker: str,
    entry_price: float,
    iv: float = 0,
    mos_pct: float = 0,
    signal: str = "",
    wacc: float = 0.12,
    sector: str = "",
    notes: str = "",
    company_name: str = "",
    account_label: str = "default",
    quantity: float | None = None,
) -> tuple[bool, str]:
    """
    Upsert a holding for a user. Returns (ok, error_message).

    ``account_label``: lets the same ticker exist multiple times under
    different demat accounts (e.g. 'zerodha', 'icici'). Unique key is
    (user_email, ticker, account_label). Defaults to "default" so all
    pre-2026-04-21 single-account rows continue to upsert correctly.

    ``quantity``: optional. If provided, persisted to the holdings row.
    Old callers that only stored entry_price still work.
    """
    if not user_email:
        return False, "user_email required"
    if not ticker:
        return False, "ticker required"

    client = _get_supabase()
    if client is None:
        return False, "Supabase unavailable"

    ticker_up = ticker.upper()
    label = (account_label or "default").lower().strip() or "default"
    now_iso = datetime.now(timezone.utc).isoformat()

    try:
        row = {
            "user_email": user_email,
            "ticker": ticker_up,
            "account_label": label,
            "company_name": company_name,
            "entry_price": float(entry_price),
            "iv": float(iv) if iv else 0,
            "mos_pct": float(mos_pct) if mos_pct else 0,
            "signal": signal or "",
            "wacc": float(wacc) if wacc else 0.12,
            "sector": sector or "",
            "notes": notes or "",
            "saved_at": now_iso,
        }
        if quantity is not None:
            row["quantity"] = float(quantity)
        # New conflict target: (user_email, ticker, account_label).
        # If the Supabase table doesn't yet have account_label + the new
        # composite unique constraint, fall back to the legacy single-
        # column conflict so this code keeps working until migration runs.
        try:
            client.table("holdings").upsert(
                row, on_conflict="user_email,ticker,account_label",
            ).execute()
        except Exception as upsert_exc:
            msg = str(upsert_exc).lower()
            if "account_label" in msg or "no unique" in msg or "constraint" in msg:
                logger.info(
                    "holdings table missing account_label constraint; "
                    "falling back to (user_email,ticker) upsert. Apply "
                    "migration 010_holdings_account_label.sql to enable "
                    "multi-account separation."
                )
                row.pop("account_label", None)
                client.table("holdings").upsert(
                    row, on_conflict="user_email,ticker",
                ).execute()
            else:
                raise
        return True, ""
    except Exception as e:
        err_msg = f"{type(e).__name__}: {e}"
        logger.warning(
            "save_holding failed for %s/%s/%s: %s",
            user_email, ticker_up, label, err_msg,
        )
        return False, err_msg


def get_holdings(user_email: str) -> list[dict]:
    """Return all holdings for a user."""
    if not user_email:
        return []
    client = _get_supabase()
    if client is None:
        return []
    try:
        result = (
            client.table("holdings")
            .select("*")
            .eq("user_email", user_email)
            .order("saved_at", desc=True)
            .execute()
        )
        return result.data or []
    except Exception as e:
        logger.warning(f"get_holdings failed for {user_email}: {e}")
        return []


def remove_holding(
    user_email: str,
    ticker: str,
    account_label: str | None = None,
) -> bool:
    """Delete a holding by ticker (and optionally account_label) for a user.

    If ``account_label`` is omitted, removes ALL rows for the ticker —
    matches the pre-multi-account behaviour. Pass it explicitly to
    target a single account's row.
    """
    if not user_email or not ticker:
        return False
    client = _get_supabase()
    if client is None:
        return False
    try:
        q = (
            client.table("holdings")
            .delete()
            .eq("user_email", user_email)
            .eq("ticker", ticker.upper())
        )
        if account_label:
            q = q.eq("account_label", account_label.lower().strip())
        result = q.execute()
        return bool(result.data)
    except Exception as e:
        logger.warning(f"remove_holding failed for {user_email}/{ticker}: {e}")
        return False


def get_holdings_with_live_data(user_email: str) -> dict:
    """
    Get holdings enriched with live prices + P&L computation.

    Returns:
        {
            "holdings": [
                {
                    ticker, company_name, sector, entry_price, quantity,
                    current_price, invested_value, current_value,
                    pnl_abs, pnl_pct, fair_value, mos_pct, verdict, score,
                }
            ],
            "summary": {
                "total_invested", "total_current_value",
                "total_pnl_abs", "total_pnl_pct",
                "winners", "losers", "count",
            }
        }
    """
    holdings = get_holdings(user_email)
    if not holdings:
        return {"holdings": [], "summary": _empty_summary()}

    # First pass: try fast sources (cache + Parquet) for all tickers
    # Identify which ones need yfinance fallback
    missing_tickers: list[str] = []
    fast_prices: dict[str, float] = {}
    for h in holdings:
        ticker = h.get("ticker", "")
        if not ticker:
            continue
        price = _get_current_price(ticker, allow_yfinance=False)
        if price is not None and price > 0:
            fast_prices[ticker] = price
        else:
            missing_tickers.append(ticker)

    # Parallel yfinance fetch for missing ones (ETFs, small caps not in Parquet)
    yf_prices: dict[str, float] = {}
    if missing_tickers:
        try:
            yf_prices = fetch_live_prices_parallel(missing_tickers, max_workers=8)
        except Exception as e:
            logger.warning(f"Parallel yfinance fetch failed: {e}")

    enriched = []
    total_invested = 0.0
    total_current = 0.0
    winners = 0
    losers = 0

    for h in holdings:
        ticker = h.get("ticker", "")
        entry_price = float(h.get("entry_price", 0) or 0)
        # Extract quantity from notes if available (e.g. "Imported from zerodha (80 shares)")
        quantity = _extract_quantity(h.get("notes", "")) or 1
        invested = entry_price * quantity

        # Get current price from the fastest available source
        current_price = fast_prices.get(ticker) or yf_prices.get(ticker)
        if current_price is None or current_price <= 0:
            current_price = entry_price  # final fallback

        current_value = current_price * quantity
        pnl_abs = current_value - invested
        pnl_pct = ((current_price - entry_price) / entry_price * 100) if entry_price > 0 else 0

        if pnl_pct > 0:
            winners += 1
        elif pnl_pct < 0:
            losers += 1

        # Get fair value from cache (don't refetch)
        from backend.services.cache_service import cache as _c
        cached = _c.get(f"analysis:{ticker}")
        fair_value = None
        verdict = ""
        score = None
        mos_pct = None
        if cached and hasattr(cached, "valuation"):
            fair_value = cached.valuation.fair_value
            verdict = cached.valuation.verdict
            score = cached.quality.yieldiq_score
            # MoS = (fair_value - current_price) / current_price (forward-looking)
            mos_pct = ((fair_value - current_price) / current_price * 100) if current_price > 0 else None

        enriched.append({
            "ticker": ticker,
            "display_ticker": ticker.replace(".NS", "").replace(".BO", ""),
            "company_name": h.get("company_name", ""),
            "sector": h.get("sector", "") or "—",
            "entry_price": round(entry_price, 2),
            "quantity": quantity,
            "current_price": round(current_price, 2),
            "invested_value": round(invested, 2),
            "current_value": round(current_value, 2),
            "pnl_abs": round(pnl_abs, 2),
            "pnl_pct": round(pnl_pct, 2),
            "fair_value": round(fair_value, 2) if fair_value else None,
            "mos_pct": round(mos_pct, 2) if mos_pct is not None else None,
            "verdict": verdict,
            "score": score,
            "saved_at": h.get("saved_at", ""),
            "notes": h.get("notes", ""),
        })

        total_invested += invested
        total_current += current_value

    total_pnl = total_current - total_invested
    total_pnl_pct = (total_pnl / total_invested * 100) if total_invested > 0 else 0

    # Sort by current value descending
    enriched.sort(key=lambda x: x["current_value"], reverse=True)

    return {
        "holdings": enriched,
        "summary": {
            "total_invested": round(total_invested, 2),
            "total_current_value": round(total_current, 2),
            "total_pnl_abs": round(total_pnl, 2),
            "total_pnl_pct": round(total_pnl_pct, 2),
            "winners": winners,
            "losers": losers,
            "count": len(enriched),
        },
    }


def _empty_summary() -> dict:
    return {
        "total_invested": 0, "total_current_value": 0,
        "total_pnl_abs": 0, "total_pnl_pct": 0,
        "winners": 0, "losers": 0, "count": 0,
    }


def _extract_quantity(notes: str) -> int | None:
    """Extract quantity from notes like 'Imported from zerodha (80 shares)'."""
    if not notes:
        return None
    import re
    m = re.search(r"\((\d+(?:\.\d+)?)\s*shares?\)", notes)
    if m:
        try:
            return int(float(m.group(1)))
        except ValueError:
            return None
    return None


def _get_current_price(ticker: str, allow_yfinance: bool = False) -> float | None:
    """Get the most recent price — analysis cache → Parquet → (optional) yfinance live.

    yfinance is slow (1-3s), so only called when explicitly requested.
    Use fetch_live_prices_parallel() for bulk fetches.
    """
    # Try analysis cache (fastest, has live price)
    try:
        from backend.services.cache_service import cache as _c
        cached = _c.get(f"analysis:{ticker}")
        if cached and hasattr(cached, "valuation"):
            return float(cached.valuation.current_price)
    except Exception:
        pass

    # Try short-lived price cache (15 min)
    try:
        from backend.services.cache_service import cache as _c
        cached_price = _c.get(f"live_price:{ticker}")
        if cached_price is not None:
            return float(cached_price)
    except Exception:
        pass

    # Try DB-backed live_quotes (populated every 5m during market hrs)
    try:
        from backend.services import market_data_service as _mds
        row = _mds.get_live_quote(ticker)
        if row and row.get("price"):
            return float(row["price"])
    except Exception:
        pass

    # Fallback to Parquet (latest close)
    try:
        from data_pipeline.nse_prices.db_integration import get_latest_price
        clean = ticker.replace(".NS", "").replace(".BO", "")
        price = get_latest_price(clean)
        if price:
            return float(price)
    except Exception:
        pass

    # Last resort: yfinance fast_info (only when explicitly allowed)
    if allow_yfinance:
        logger.warning("live_quote fallback to yfinance for %s", ticker)
        price = _fetch_yfinance_price(ticker)
        if price is not None:
            try:
                from backend.services.cache_service import cache as _c
                _c.set(f"live_price:{ticker}", price, ttl=900)
            except Exception:
                pass
            return price

    return None


def _fetch_yfinance_price(ticker: str) -> float | None:
    """Fetch live price from yfinance fast_info.

    Tries .NS first (NSE), then .BO (BSE) as fallback for BSE-only
    stocks (e.g. PREMCO-X which is BSE-listed).
    """
    import yfinance as yf
    # Silence yfinance errors for failed fetches
    import logging as _yf_log
    _yf_log.getLogger("yfinance").setLevel(_yf_log.CRITICAL)

    # Build candidate ticker list based on current suffix
    candidates: list[str] = []
    base = ticker.replace(".NS", "").replace(".BO", "")

    # Strip Zerodha hyphen suffixes (e.g. "PREMCO-X" -> "PREMCO")
    # Common suffixes: -X (BSE), -EQ, -BE, -BL, -BT, -BZ
    base_no_suffix = base
    for suffix in ("-X", "-EQ", "-BE", "-BL", "-BT", "-BZ"):
        if base.upper().endswith(suffix):
            base_no_suffix = base[: -len(suffix)]
            break

    # Build candidates in priority order
    if ticker.endswith(".BO"):
        candidates = [f"{base}.BO", f"{base}.NS"]
        if base_no_suffix != base:
            candidates += [f"{base_no_suffix}.BO", f"{base_no_suffix}.NS"]
    elif ticker.endswith(".NS"):
        candidates = [f"{base}.NS", f"{base}.BO"]
        if base_no_suffix != base:
            candidates += [f"{base_no_suffix}.NS", f"{base_no_suffix}.BO"]
    else:
        candidates = [f"{base}.NS", f"{base}.BO"]
        if base_no_suffix != base:
            candidates += [f"{base_no_suffix}.NS", f"{base_no_suffix}.BO"]

    for t in candidates:
        try:
            tk = yf.Ticker(t)
            # fast_info (no network if already cached by yf)
            try:
                lp = tk.fast_info.last_price
                if lp and 0 < float(lp) < 1e7:
                    return float(lp)
            except Exception:
                pass
            # Fallback: short history query
            try:
                hist = tk.history(period="5d", auto_adjust=False, progress=False)
                if not hist.empty:
                    last = float(hist["Close"].dropna().iloc[-1])
                    if 0 < last < 1e7:
                        return last
            except Exception:
                pass
        except Exception:
            continue
    return None


def fetch_live_prices_parallel(tickers: list[str], max_workers: int = 8) -> dict[str, float]:
    """
    Fetch live prices for multiple tickers.

    Tier 1: bulk-read live_quotes (DB, populated every 5m by the
            market_data_refresher APScheduler job). One SQL call.
    Tier 2: short-lived in-memory cache (15 min, for anything already
            fetched from yfinance in the current container).
    Tier 3: parallel yfinance fallback — only for tickers missing from
            both DB and cache. Logs a warning per miss.
    """
    if not tickers:
        return {}

    from concurrent.futures import ThreadPoolExecutor, as_completed
    from backend.services.cache_service import cache as _c
    from backend.services import market_data_service as _mds

    results: dict[str, float] = {}

    # Tier 1 — DB bulk
    try:
        db_rows = _mds.get_live_quotes_bulk(tickers)
        for t, row in db_rows.items():
            price = row.get("price")
            if price is not None and price > 0:
                results[t] = float(price)
    except Exception as exc:
        logger.warning("live_quotes bulk read failed: %s", exc)

    # Tier 2 — local cache (fills any remaining)
    to_fetch: list[str] = []
    for t in tickers:
        if t in results:
            continue
        cached = _c.get(f"live_price:{t}")
        if cached is not None:
            results[t] = float(cached)
        else:
            to_fetch.append(t)

    if not to_fetch:
        return results

    # Tier 3 — yfinance fallback (warn: production gap)
    logger.warning(
        "live_quotes fallback to yfinance for %d ticker(s): %s",
        len(to_fetch), to_fetch[:10],
    )
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(_fetch_yfinance_price, t): t for t in to_fetch}
        for fut in as_completed(futures, timeout=15):
            t = futures[fut]
            try:
                price = fut.result()
                if price is not None:
                    results[t] = price
                    _c.set(f"live_price:{t}", price, ttl=900)
            except Exception:
                pass

    return results


def count_holdings(user_email: str) -> int:
    """Count holdings for tier-limit checks."""
    if not user_email:
        return 0
    client = _get_supabase()
    if client is None:
        return 0
    try:
        result = (
            client.table("holdings")
            .select("id", count="exact")
            .eq("user_email", user_email)
            .execute()
        )
        return result.count or 0
    except Exception:
        return 0
