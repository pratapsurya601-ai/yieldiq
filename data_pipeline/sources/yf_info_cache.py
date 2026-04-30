"""
Stale-while-revalidate cache for yfinance ``.info`` dicts.

yfinance's ``Ticker.info`` is the hottest and slowest call in the
analysis path — it hits Yahoo's quoteSummary endpoint and blocks for
15-30 seconds on Indian tickers. The collector reads ~20 fields from
that dict (price, PE, sector, shortName, ratios, etc.) so we can't
easily eliminate the call, but we CAN cache the whole response.

Strategy:
    1. First call for a ticker: live-fetch + write through to
       ``yfinance_info_cache`` table (slow, one-time).
    2. Subsequent call within ``ttl_minutes`` (default 30 days):
       DB/file lookup (~50ms), no yfinance hit.
    3. Subsequent call after TTL: return the stale row immediately
       AND fire a daemon thread to refresh in background (user
       doesn't wait).
    4. DB outage / missing table: fall back to file cache or
       live-fetch — we stay functional, just slow.

The table schema is created by ``scripts/migrate_yfinance_info_cache.py``
via the ``.github/workflows/migrate.yml`` manual workflow. If the
table is absent, this module no-ops gracefully; callers never see
a crash, only a live-fetch path.

TTL rationale (2026-04-21, yfinance-quick-wins-week1):
    ``.info`` returns sector, industry, shortName, longName,
    description, 52-week high/low, beta, forward PE, trailingPE,
    dividendYield, marketCap, and ~30 other fields. Of these, only
    price-derived values (regularMarketPrice, marketCap, trailingPE)
    change intra-day. Everything else (sector/industry/description/
    shortName/beta) changes annually or less. The analysis pipeline
    no longer depends on ``.info`` for live price — that comes from
    the daily_prices table. So a 30-day TTL is safe: stale price is
    replaced by the DB lookup, everything else is correct for 30+
    days. 43200 minutes == 30 days.
"""
from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

log = logging.getLogger("yieldiq.yf_info_cache")

# 30 days. See module docstring for rationale.
DEFAULT_TTL_MINUTES = 30 * 24 * 60  # 43_200


def _db_session():
    """Return a pipeline DB session, or None if DATABASE_URL isn't set."""
    try:
        from data_pipeline.db import Session as PipelineSession
        if PipelineSession is not None:
            return PipelineSession()
    except Exception:
        pass
    return None


# ── File-based fallback cache ────────────────────────────────────────
# When no Postgres is available (Railway DB deleted, Aiven down, etc.),
# cache info dicts as individual JSON files in a local directory.
# This works everywhere — dev, Railway, CI — with zero dependencies.

_FILE_CACHE_DIR = Path(__file__).parent.parent.parent / "data" / "yf_cache"


def _file_read(ticker: str, ttl_minutes: int) -> dict | None:
    """Read a cached info dict from a JSON file. Returns None if missing/stale."""
    path = _FILE_CACHE_DIR / f"{ticker.replace('/', '_')}.json"
    if not path.exists():
        return None
    try:
        age = datetime.utcnow().timestamp() - path.stat().st_mtime
        if age > ttl_minutes * 60:
            return None  # stale
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _file_write(ticker: str, info: dict) -> None:
    """Write an info dict to a JSON file."""
    try:
        _FILE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        path = _FILE_CACHE_DIR / f"{ticker.replace('/', '_')}.json"
        path.write_text(_serialize(info), encoding="utf-8")
    except Exception as exc:
        log.debug("file cache write failed for %s: %s", ticker, exc)


def _is_valid_info(info: dict | None) -> bool:
    """Only cache info dicts with real data — skip caching 404 shells."""
    if not info:
        return False
    return bool(
        info.get("regularMarketPrice") is not None
        or info.get("currentPrice") is not None
        or info.get("shortName")
        or info.get("longName")
    )


# ── Write-time validation guards (added 2026-04-30, mirrors PR #208) ───
# The 2026-04-29 INFY ADR currency-mistag incident (fixed in
# scripts/data_pipelines/fix_adr_indian_currency_mistag.py) showed that
# yfinance occasionally returns financialCurrency='USD' for Indian-primary
# tickers (it pulls the wrong filing from the ADR side). Caching that
# blob means every downstream read is poisoned until the row expires.
# Reject obviously-corrupt info dicts at write time.

# Explicit US-primary ADRs we must NOT confuse with Indian primaries.
# These legitimately report USD on yfinance and are NOT in our universe.
_US_PRIMARY_ADRS: frozenset[str] = frozenset({
    "SIFY", "MMYT", "WIT", "HDB", "IBN", "TTM", "RDY", "INFY-ADR",
})


def _is_indian_primary_ticker(ticker: str) -> bool:
    """Return True if the ticker is in our Indian-primary universe.

    Conservative: check the `stocks` table. If the table or DB is
    unreachable, fall back to "not in the explicit ADR allow-list" —
    YieldIQ's universe is Indian-only by construction.
    """
    if not ticker:
        return False
    bare = ticker.replace(".NS", "").replace(".BO", "").upper()
    if bare in _US_PRIMARY_ADRS:
        return False
    db = _db_session()
    if db is None:
        return True  # universe is Indian-only; assume yes
    try:
        from sqlalchemy import text
        row = db.execute(
            text("SELECT 1 FROM stocks WHERE ticker = :t LIMIT 1"),
            {"t": bare},
        ).first()
        return row is not None
    except Exception:
        return True
    finally:
        try:
            db.close()
        except Exception:
            pass


def _validate_info_for_write(ticker: str, info: dict) -> tuple[bool, str | None]:
    """Inspect a freshly-fetched info dict before caching it.

    Returns (ok, reason). When ok is False, the caller must NOT write
    the row to either the DB cache or the file cache, and should log
    a WARNING (no `data_anomalies` table exists today).

    Rejection rules (mirrors fix_adr_indian_currency_mistag.py guards):
      1. financialCurrency='USD' on an Indian-primary ticker — the
         classic ADR mistag pattern. Block.
      2. marketCap < 0 or > 1e15 — overflow / unit bug.
      3. trailingPE > 1000 — almost always a unit bug.
      4. currentPrice disagrees with live_quotes by >50% — catches
         the 2026-04-30 INFY 92x unit bug where ratios were
         internally consistent but the absolute price was poisoned.
      5. enterpriseToEbitda > 200 — unit bug (real-world cap ~150).
    """
    try:
        # Rule 1: ADR currency mistag
        fin_ccy = str(info.get("financialCurrency") or "").upper()
        if fin_ccy == "USD" and _is_indian_primary_ticker(ticker):
            return False, (
                f"financialCurrency=USD on Indian-primary ticker {ticker} "
                "(suspected ADR mistag — see PR #208 lineage)"
            )

        # Rule 2: marketCap range
        mc = info.get("marketCap")
        if isinstance(mc, (int, float)):
            if mc < 0 or mc > 1e15:
                return False, (
                    f"marketCap out of plausible range: {mc} "
                    f"(must be 0 <= x <= 1e15)"
                )

        # Rule 3: trailingPE sanity
        pe = info.get("trailingPE")
        if isinstance(pe, (int, float)) and pe > 1000:
            return False, f"trailingPE={pe} > 1000 (suspected unit bug)"

        # Rule 4: cross-check currentPrice vs live_quotes table (within 50%).
        # Catches the 2026-04-30 INFY incident where yfinance returned
        # 109652 but live_quotes had 1188 — 92x divergence. Per-ratio
        # guards (PE 18.4, PB 6.16) passed because the bad blob was
        # internally consistent, so we need an external anchor.
        px = info.get("currentPrice") or info.get("regularMarketPrice")
        if px is not None:
            db = _db_session()
            if db is not None:
                try:
                    from sqlalchemy import text
                    row = db.execute(
                        text(
                            "SELECT price FROM live_quotes "
                            "WHERE ticker = :t "
                            "ORDER BY trade_date DESC LIMIT 1"
                        ),
                        {"t": ticker},
                    ).first()
                    if row and row[0]:
                        lq = float(row[0])
                        if lq > 0 and abs(float(px) - lq) / lq > 0.5:
                            return False, (
                                f"currentPrice={px} disagrees with "
                                f"live_quotes={lq} by >50% (suspected unit bug)"
                            )
                except Exception:
                    # Don't block writes if live_quotes is unreachable.
                    pass
                finally:
                    try:
                        db.close()
                    except Exception:
                        pass

        # Rule 5: enterpriseToEbitda sanity (real-world cap ~150).
        ev_ebitda = info.get("enterpriseToEbitda")
        if isinstance(ev_ebitda, (int, float)) and ev_ebitda > 200:
            return False, f"enterpriseToEbitda={ev_ebitda} > 200 (suspected unit bug)"

        return True, None
    except Exception as exc:
        # Defensive: never crash the writer over a guard failure.
        log.debug("validate_info_for_write raised for %s: %s", ticker, exc)
        return True, None


def _serialize(info: dict) -> str:
    """JSON-encode with fallback to str() for non-JSON values (Timestamps etc)."""
    def _fallback(o: Any) -> str:
        try:
            return str(o)
        except Exception:
            return ""
    return json.dumps(info, default=_fallback, ensure_ascii=False)


def _fetch_live(ticker: str) -> dict:
    """Do the actual yfinance call. Returns {} on any failure."""
    try:
        import yfinance as yf
        return yf.Ticker(ticker).info or {}
    except Exception as exc:
        log.debug("yfinance .info fetch failed for %s: %s", ticker, exc)
        return {}


def _store(ticker: str, info: dict) -> None:
    """Upsert into yfinance_info_cache. Logs at INFO level so failures
    surface in Railway logs — silent failures here mean users stay slow."""
    if not _is_valid_info(info):
        log.info("YF_INFO_CACHE: skip-store %s (invalid info)", ticker)
        return
    ok, reason = _validate_info_for_write(ticker, info)
    if not ok:
        # No data_anomalies table exists today — surface at WARNING so
        # the rejection lands in Railway logs and is grep-able.
        log.warning(
            "YF_INFO_CACHE: REJECT write for %s — %s", ticker, reason,
        )
        return
    db = _db_session()
    if db is None:
        log.warning("YF_INFO_CACHE: store failed for %s — DATABASE_URL not set", ticker)
        return
    try:
        from sqlalchemy import text
        # data_quality_rank=50 (yfinance) — column added in migration 009/024
        # for schema consistency with the wider source-precedence pattern
        # (PR #208). Wrapped in try/except path: pre-migration the column
        # is absent and we fall back to the 3-column INSERT.
        try:
            db.execute(text("""
                INSERT INTO yfinance_info_cache
                    (ticker, info_json, updated_at, data_quality_rank)
                VALUES (:t, :j, NOW(), 50)
                ON CONFLICT (ticker) DO UPDATE
                    SET info_json = EXCLUDED.info_json,
                        updated_at = NOW(),
                        data_quality_rank = LEAST(
                            COALESCE(yfinance_info_cache.data_quality_rank, 50),
                            EXCLUDED.data_quality_rank
                        )
            """), {"t": ticker, "j": _serialize(info)})
        except Exception:
            # Pre-migration fallback — column may not exist yet.
            db.rollback()
            db.execute(text("""
                INSERT INTO yfinance_info_cache (ticker, info_json, updated_at)
                VALUES (:t, :j, NOW())
                ON CONFLICT (ticker) DO UPDATE
                    SET info_json = EXCLUDED.info_json,
                        updated_at = NOW()
            """), {"t": ticker, "j": _serialize(info)})
        db.commit()
        log.info("YF_INFO_CACHE: stored %s (%d bytes)", ticker, len(_serialize(info)))
    except Exception as exc:
        log.warning("YF_INFO_CACHE: store failed for %s: %s", ticker, exc)
        try:
            db.rollback()
        except Exception:
            pass
    finally:
        try:
            db.close()
        except Exception:
            pass


def _refresh_async(ticker: str) -> None:
    """Fire-and-forget refresh in a daemon thread."""
    def _go():
        try:
            info = _fetch_live(ticker)
            _store(ticker, info)
        except Exception as exc:
            log.debug("async refresh failed for %s: %s", ticker, exc)
    threading.Thread(target=_go, daemon=True, name=f"yfinfo-refresh-{ticker}").start()


def get_info(ticker: str, ttl_minutes: int = DEFAULT_TTL_MINUTES) -> tuple[dict, bool]:
    """
    Return ``(info, from_cache)``. Never raises.

    Priority:
      1. Fresh DB row (age < ttl_minutes) → return + ``True``.
      2. Stale DB row → return stale data + ``True`` AND spawn a
         background refresh thread. User gets instant response.
      3. No DB row / table missing / DB down → live-fetch
         synchronously, write through, return + ``False``.
    """
    if not ticker:
        return {}, False

    # ── File cache (works without any DB) ────────────────────
    file_cached = _file_read(ticker, ttl_minutes)
    if file_cached:
        log.info("YF_INFO_CACHE: FILE HIT %s", ticker)
        return file_cached, True

    # ── DB lookup (if Postgres is available) ──────────────────
    db = _db_session()
    if db is None:
        log.debug("YF_INFO_CACHE: no DB session for %s", ticker)
    else:
        try:
            from sqlalchemy import text
            row = db.execute(text("""
                SELECT info_json, updated_at
                FROM yfinance_info_cache
                WHERE ticker = :t
            """), {"t": ticker}).mappings().first()
            if row:
                try:
                    info = json.loads(row["info_json"])
                except Exception:
                    info = None
                if info:
                    updated = row["updated_at"]
                    age = datetime.utcnow() - (
                        updated.replace(tzinfo=None) if hasattr(updated, "tzinfo") and updated.tzinfo else updated
                    )
                    if age < timedelta(minutes=ttl_minutes):
                        log.info("YF_INFO_CACHE: HIT %s (age=%ds)", ticker, int(age.total_seconds()))
                        return info, True
                    log.info("YF_INFO_CACHE: STALE %s (age=%ds) → bg refresh", ticker, int(age.total_seconds()))
                    _refresh_async(ticker)
                    return info, True
                else:
                    log.warning("YF_INFO_CACHE: row for %s had unparseable JSON", ticker)
            else:
                log.info("YF_INFO_CACHE: MISS %s (no row)", ticker)
        except Exception as exc:
            log.warning("YF_INFO_CACHE: read failed for %s: %s", ticker, exc)
        finally:
            try:
                db.close()
            except Exception:
                pass

    # ── Live fetch + write-through ───────────────────────────
    info = _fetch_live(ticker)
    if _is_valid_info(info):
        ok, reason = _validate_info_for_write(ticker, info)
        if not ok:
            # Reject from BOTH DB and file cache — see _validate_info_for_write
            # for rationale (PR #208 ADR currency-mistag guard).
            log.warning(
                "YF_INFO_CACHE: REJECT write-through for %s — %s",
                ticker, reason,
            )
            return info, False
        _store(ticker, info)          # Postgres (if available)
        _file_write(ticker, info)     # File cache (always works)
    else:
        log.info("YF_INFO_CACHE: live fetch for %s returned invalid data — not caching", ticker)
    return info, False
