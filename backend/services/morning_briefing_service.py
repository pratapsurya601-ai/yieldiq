# backend/services/morning_briefing_service.py
# ═══════════════════════════════════════════════════════════════
# Morning Briefing — server-side composition of the /home hero
# tile data + 2-4 sentence observational briefing line.
#
# Wire shape (returned by build_morning_briefing):
#   {
#     "as_of":            ISO 8601 IST timestamp
#     "user_name":        str — display name OR derived-from-email token
#     "portfolio": {
#       "total_value":     float  (current_value sum)
#       "day_change":      float  (today's INR move on the basket)
#       "day_change_pct":  float  (today's % move on the basket)
#       "sparkline_7d":    list[float]  (last 7 daily totals)
#     } | None  (None when the user has zero holdings — frontend hides
#                the tile and shows a friendly "add your first stock"
#                line in the briefing copy)
#     "market": {
#       "nifty_value":         float
#       "nifty_change_pct":    float
#       "nifty_sparkline_7d":  list[float]
#     }
#     "briefing_text": str  (2-4 sentences, SEBI-clean observational)
#   }
#
# DISCIPLINE — SEBI vocabulary
# ─────────────────────────────
# The briefing text is composed from deterministic templates only — no
# LLM, no opinion verbs. Allowed words: drag, lift, moved, reported.
# Banned (enforced by scripts/check_sebi_words.py and the runtime
# sebi_filter): buy, sell, hold, recommend, should, attractive, etc.
#
# CACHING
# ───────
# 5-minute server-side cache pinned to user_id (NEVER email — emails
# can collide on dev fixtures and the user_id is the only stable PK).
# Cache key: `briefing:morning:<user_id>`. The TTL means the briefing
# refreshes naturally on every page view after 5 minutes, which is the
# same cadence as live_quotes ingestion.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import text

logger = logging.getLogger("yieldiq.morning_briefing")

# IST = UTC+5:30. No DST since 1947 — fixed offset is correct.
_IST = timezone(timedelta(hours=5, minutes=30))

# Server-side cache TTL — 5 min (same cadence as the live-quotes
# refresher). Pins the briefing to user_id so cross-user leakage is
# impossible.
_BRIEFING_TTL_SEC = 300

# Threshold for "stocks you watch moved more than 2% today". The brief
# spec said >2% — we honour the strict inequality.
_WATCH_MOVE_THRESHOLD_PCT = 2.0

# Earnings horizon — surface a holding's earnings date if within the
# next 7 days. Shorter window keeps the briefing focused.
_EARNINGS_WINDOW_DAYS = 7


# ─────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────

def _now_ist_iso() -> str:
    """Current IST timestamp in ISO 8601 with offset."""
    return datetime.now(_IST).isoformat(timespec="seconds")


def _display_name_from_email(email: Optional[str]) -> str:
    """Mirror frontend/components/home/PersonalHeader.tsx#nameFromEmail.

    The Server-side briefing inlines the same fallback so the prose
    can say "Welcome — add your first stock to start tracking" with
    no flicker on the client.
    """
    if not email:
        return "there"
    local = email.split("@", 1)[0]
    if not local:
        return "there"
    token = local.replace("_", ".").replace("-", ".").replace("+", ".").split(".")[0]
    if not token:
        return "there"
    return token[0].upper() + token[1:].lower()


def _display_ticker(ticker: str) -> str:
    """Strip the .NS / .BO suffix for human-readable prose."""
    return (ticker or "").replace(".NS", "").replace(".BO", "")


def _fmt_pct(value: Optional[float]) -> str:
    """Format a percent as `+1.1%` / `-0.4%`. Missing → '0.0%'.

    Single decimal place — matches the rest of the home dashboard.
    """
    if value is None:
        return "0.0%"
    sign = "+" if value >= 0 else ""
    return f"{sign}{value:.1f}%"


def _fmt_arrow_pct(value: Optional[float]) -> str:
    """Compose an `up/down arrow + abs %` glyph for the prose stream.

    The reference shape uses ↓1.1% / ↑0.8%. Sign-encoded arrow keeps
    the briefing readable mid-sentence ("NIFTY opened ↓1.1% on ...").
    """
    if value is None:
        return "flat"
    arrow = "down" if value < 0 else "up"
    return f"{arrow} {abs(value):.1f}%"


# ─────────────────────────────────────────────────────────────────
# Data fetch — all I/O isolated here so the composer is pure
# ─────────────────────────────────────────────────────────────────

def _fetch_portfolio_with_day_change(email: str) -> dict[str, Any]:
    """Return enriched holdings + summary for the user.

    Wraps `portfolio_service.get_holdings_with_live_data` so the
    briefing inherits the same canonical-price cascade + bulk
    valuation lookup the home `/holdings-live` endpoint uses.

    Returns the raw service payload (with keys `holdings`, `summary`).
    Empty when the user has no holdings or the email is missing.
    """
    if not email:
        return {"holdings": [], "summary": {}}
    try:
        from backend.services.portfolio_service import get_holdings_with_live_data
        return get_holdings_with_live_data(email) or {"holdings": [], "summary": {}}
    except Exception as exc:
        logger.warning("morning_briefing: portfolio fetch failed: %s", exc)
        return {"holdings": [], "summary": {}}


def _fetch_watchlist_tickers(email: str) -> list[str]:
    """Return the user's watchlisted tickers as a flat list (no metadata).

    The briefing only needs the ticker symbols — we compute the %
    moves separately from live_quotes.
    """
    if not email:
        return []
    try:
        from db.supabase_client import get_admin_client
        client = get_admin_client()
        if client is None:
            return []
        result = (
            client.table("watchlist")
            .select("ticker")
            .eq("user_email", email)
            .execute()
        )
        return [r.get("ticker", "") for r in (result.data or []) if r.get("ticker")]
    except Exception as exc:
        logger.warning("morning_briefing: watchlist fetch failed: %s", exc)
        return []


def _fetch_live_quotes(tickers: list[str]) -> dict[str, dict]:
    """Bulk live_quotes lookup. Returns {} on any failure (briefing
    degrades to "no watchlist movement to report" rather than 500-ing).
    """
    if not tickers:
        return {}
    try:
        from backend.services import market_data_service as _mds
        return _mds.get_live_quotes_bulk(tickers) or {}
    except Exception as exc:
        logger.warning("morning_briefing: live_quotes fetch failed: %s", exc)
        return {}


def _fetch_nifty_snapshot() -> dict[str, Any]:
    """Current NIFTY 50 snapshot. Empty dict on failure."""
    try:
        from backend.services import market_data_service as _mds
        snap = _mds.get_index_snapshot("NIFTY 50")
        return snap or {}
    except Exception as exc:
        logger.warning("morning_briefing: nifty snapshot fetch failed: %s", exc)
        return {}


def _fetch_index_sparkline_7d(symbol: str = "NIFTY 50") -> list[float]:
    """Last 7 daily closes for an index. Best-effort — returns [] on miss.

    Reads from `index_history` if available, otherwise falls back to
    the daily_prices table keyed by the well-known yfinance ticker
    (^NSEI for NIFTY 50). Both paths are defensive — the home page
    must render even when the historical store is empty.
    """
    try:
        from data_pipeline.db import Session
        if Session is None:
            return []
        sess = Session()
    except Exception:
        return []
    try:
        # Primary path: index_history (populated by the index-EOD
        # cron in market_data_refresher). Optional table — we tolerate
        # its absence on dev / brand-new Aiven instances.
        try:
            rows = sess.execute(
                text(
                    "SELECT close_price FROM index_history "
                    "WHERE symbol = :s ORDER BY trade_date DESC LIMIT 7"
                ),
                {"s": symbol},
            ).fetchall()
            if rows:
                values = [float(r[0]) for r in rows if r[0] is not None]
                values.reverse()  # oldest → newest, for a left-to-right sparkline
                return values
        except Exception:
            sess.rollback()
        # Fallback: daily_prices keyed by the canonical yfinance symbol.
        yf_key = {"NIFTY 50": "^NSEI", "NIFTY BANK": "^NSEBANK"}.get(symbol)
        if yf_key:
            try:
                rows = sess.execute(
                    text(
                        "SELECT close_price FROM daily_prices "
                        "WHERE ticker = :t ORDER BY trade_date DESC LIMIT 7"
                    ),
                    {"t": yf_key},
                ).fetchall()
                if rows:
                    values = [float(r[0]) for r in rows if r[0] is not None]
                    values.reverse()
                    return values
            except Exception:
                sess.rollback()
        return []
    finally:
        try:
            sess.close()
        except Exception:
            pass


def _fetch_upcoming_earnings(tickers: list[str]) -> Optional[dict]:
    """Return the earliest upcoming earnings event in the next
    7 days from the supplied tickers, or None.

    Picks the EARLIEST date so the briefing surfaces the most
    immediate event — earnings prep is time-sensitive.
    """
    if not tickers:
        return None
    try:
        from data_pipeline.db import Session
        if Session is None:
            return None
        sess = Session()
    except Exception:
        return None
    try:
        from backend.services.earnings_calendar_service import (
            get_next_earnings_dict,
        )
        soonest: Optional[dict] = None
        today = datetime.now(_IST).date()
        horizon = today + timedelta(days=_EARNINGS_WINDOW_DAYS)
        for t in tickers:
            try:
                ev = get_next_earnings_dict(t, sess)
            except Exception:
                continue
            if not ev:
                continue
            ev_date = ev.get("date")
            if ev_date is None:
                continue
            # Earnings events live as dates; horizon is also a date.
            try:
                if today <= ev_date <= horizon:
                    if soonest is None or ev_date < soonest["date"]:
                        soonest = {"ticker": t, "date": ev_date}
            except TypeError:
                continue
        return soonest
    except Exception as exc:
        logger.debug("morning_briefing: earnings lookup failed: %s", exc)
        return None
    finally:
        try:
            sess.close()
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────────
# Composer — pure functions on the fetched payloads
# ─────────────────────────────────────────────────────────────────

def _portfolio_block(
    holdings: list[dict],
    summary: dict,
) -> Optional[dict[str, Any]]:
    """Shape the portfolio tile payload. Returns None when the user
    has zero holdings — the frontend hides the tile in that case.
    """
    if not holdings:
        return None
    total_current = float(summary.get("total_current_value") or 0.0)
    # Sum the per-holding day_change_abs (set in
    # portfolio_service.get_holdings_with_live_data from live_quotes).
    day_change = 0.0
    for h in holdings:
        v = h.get("day_change_abs")
        if v is not None:
            try:
                day_change += float(v)
            except (TypeError, ValueError):
                continue
    # Yesterday's basket value ≈ today − day_change. Avoids storing a
    # second number; the % is derived once at the top.
    yesterday_value = total_current - day_change
    day_change_pct = (day_change / yesterday_value * 100.0) if yesterday_value > 0 else 0.0
    # The 7-day sparkline lives on the per-holding cache today, not
    # at the basket level. Emit an empty list rather than fabricating
    # values — the frontend handles `[]` by rendering nothing.
    return {
        "total_value": round(total_current, 2),
        "day_change": round(day_change, 2),
        "day_change_pct": round(day_change_pct, 2),
        "sparkline_7d": [],
    }


def _biggest_holding_mover(holdings: list[dict]) -> Optional[dict]:
    """Pick the holding with the largest absolute day_change_pct.

    Returns {"ticker", "display", "pct", "direction"} or None when no
    holding has a live day_change_pct yet (cold worker / pre-market).
    """
    best: Optional[dict] = None
    best_abs = 0.0
    for h in holdings:
        pct = h.get("day_change_pct")
        if pct is None:
            continue
        try:
            pct_f = float(pct)
        except (TypeError, ValueError):
            continue
        if abs(pct_f) >= best_abs:
            best_abs = abs(pct_f)
            best = {
                "ticker": h.get("ticker", ""),
                "display": _display_ticker(h.get("ticker", "")),
                "pct": pct_f,
                "direction": "drag" if pct_f < 0 else "lift",
            }
    return best


def _count_watch_movers(
    watch_tickers: list[str],
    quotes: dict[str, dict],
    threshold_pct: float = _WATCH_MOVE_THRESHOLD_PCT,
) -> int:
    """How many watchlisted tickers moved more than `threshold_pct`%
    today (in either direction)."""
    count = 0
    for t in watch_tickers:
        q = quotes.get(t) or {}
        pct = q.get("change_pct")
        if pct is None:
            continue
        try:
            if abs(float(pct)) > threshold_pct:
                count += 1
        except (TypeError, ValueError):
            continue
    return count


def _compose_briefing_text(
    *,
    has_portfolio: bool,
    nifty_change_pct: Optional[float],
    biggest_mover: Optional[dict],
    watch_movers_count: int,
    earnings_event: Optional[dict],
) -> str:
    """Deterministic 2-4 sentence briefing.

    SEBI-clean: observational only. Allowed verbs — moved, reported,
    is the biggest drag/lift. No should/recommend/buy/sell.
    """
    # Empty portfolio path — a single friendly line, no recommendations.
    if not has_portfolio:
        if nifty_change_pct is not None:
            return (
                f"NIFTY 50 is {_fmt_arrow_pct(nifty_change_pct)} today. "
                "Welcome — add your first stock to start tracking."
            )
        return "Welcome — add your first stock to start tracking."

    sentences: list[str] = []

    # Sentence 1: NIFTY direction. We don't fabricate macro reasons —
    # if no headline is cached, we keep it observational ("after global
    # cues" / "in early trade").
    if nifty_change_pct is not None:
        sentences.append(
            f"NIFTY 50 is {_fmt_arrow_pct(nifty_change_pct)} today after global cues."
        )
    else:
        sentences.append("NIFTY 50 is flat at the open after global cues.")

    # Sentence 2: biggest single-holding mover (drag or lift).
    if biggest_mover and abs(biggest_mover["pct"]) >= 0.1:
        sentences.append(
            f"{biggest_mover['display']} is your biggest "
            f"{biggest_mover['direction']} today "
            f"({_fmt_pct(biggest_mover['pct'])})."
        )

    # Sentence 3: watchlist movement count (only if >0).
    if watch_movers_count > 0:
        plural = "s" if watch_movers_count != 1 else ""
        verb = "moved" if watch_movers_count != 1 else "moved"
        sentences.append(
            f"{watch_movers_count} stock{plural} you watch {verb} "
            f"more than {_WATCH_MOVE_THRESHOLD_PCT:.0f}% today."
        )

    # Sentence 4: nearest upcoming earnings event from a holding.
    if earnings_event and earnings_event.get("date"):
        ev_disp = _display_ticker(earnings_event["ticker"])
        try:
            date_str = earnings_event["date"].strftime("%a %d %b")
        except Exception:
            date_str = str(earnings_event["date"])
        sentences.append(f"{ev_disp} reports earnings on {date_str}.")

    return " ".join(sentences)


# ─────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────

def build_morning_briefing(user: dict) -> dict[str, Any]:
    """Compose the full Morning Briefing payload for a user.

    Wraps fetch + compose + cache. Pins the cache key to user_id so
    cross-user leakage is structurally impossible.
    """
    user_id = (user or {}).get("user_id") or ""
    email = (user or {}).get("email") or ""
    # display_name is not on the JWT in v1 — the frontend has its own
    # store-backed displayName and will overlay it. Server-side we
    # use the email-derived token so the briefing prose is renderable
    # standalone (e.g. when streamed into the email morning digest).
    user_name = _display_name_from_email(email)

    cache_key = f"briefing:morning:{user_id}" if user_id else None

    # Cache hit — only when we have a user_id to pin. Anonymous /
    # dev-mode-impersonation requests bypass the cache entirely.
    if cache_key:
        try:
            from backend.services.cache_service import cache as _c
            cached = _c.get(cache_key)
            if isinstance(cached, dict):
                return cached
        except Exception:
            pass

    # ── Fetch ──
    portfolio_payload = _fetch_portfolio_with_day_change(email)
    holdings = portfolio_payload.get("holdings") or []
    summary = portfolio_payload.get("summary") or {}

    watch_tickers = _fetch_watchlist_tickers(email)
    watch_quotes = _fetch_live_quotes(watch_tickers)

    nifty_snap = _fetch_nifty_snapshot()
    nifty_value = nifty_snap.get("price")
    nifty_change_pct = nifty_snap.get("change_pct")
    nifty_sparkline = _fetch_index_sparkline_7d("NIFTY 50")

    # Earnings horizon — only ask for holdings, not the full universe.
    earnings_event = _fetch_upcoming_earnings(
        [h.get("ticker", "") for h in holdings if h.get("ticker")]
    )

    # ── Compose ──
    portfolio_block = _portfolio_block(holdings, summary)
    biggest_mover = _biggest_holding_mover(holdings)
    watch_movers_count = _count_watch_movers(watch_tickers, watch_quotes)

    briefing_text = _compose_briefing_text(
        has_portfolio=portfolio_block is not None,
        nifty_change_pct=nifty_change_pct,
        biggest_mover=biggest_mover,
        watch_movers_count=watch_movers_count,
        earnings_event=earnings_event,
    )

    payload: dict[str, Any] = {
        "as_of": _now_ist_iso(),
        "user_name": user_name,
        "portfolio": portfolio_block,
        "market": {
            "nifty_value": (
                round(float(nifty_value), 2) if nifty_value is not None else None
            ),
            "nifty_change_pct": (
                round(float(nifty_change_pct), 2)
                if nifty_change_pct is not None else None
            ),
            "nifty_sparkline_7d": nifty_sparkline,
        },
        "briefing_text": briefing_text,
    }

    # ── Cache ──
    if cache_key:
        try:
            from backend.services.cache_service import cache as _c
            _c.set(cache_key, payload, ttl=_BRIEFING_TTL_SEC)
        except Exception:
            pass

    return payload


__all__ = [
    "build_morning_briefing",
    # Exposed for tests — keeps the composer unit-testable without
    # any of the Supabase / Aiven / live_quotes plumbing.
    "_compose_briefing_text",
    "_biggest_holding_mover",
    "_count_watch_movers",
    "_portfolio_block",
    "_WATCH_MOVE_THRESHOLD_PCT",
    "_BRIEFING_TTL_SEC",
]
