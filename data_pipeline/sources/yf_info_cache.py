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
    2. Subsequent call within ``ttl_minutes`` (default 30): DB
       lookup (~50ms), no yfinance hit.
    3. Subsequent call after TTL: return the stale row immediately
       AND fire a daemon thread to refresh in background (user
       doesn't wait).
    4. DB outage / missing table: fall back to live-fetch every
       time — we stay functional, just slow.

The table schema is created by ``scripts/migrate_yfinance_info_cache.py``
via the ``.github/workflows/migrate.yml`` manual workflow. If the
table is absent, this module no-ops gracefully; callers never see
a crash, only a live-fetch path.
"""
from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

log = logging.getLogger("yieldiq.yf_info_cache")


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
    db = _db_session()
    if db is None:
        log.warning("YF_INFO_CACHE: store failed for %s — DATABASE_URL not set", ticker)
        return
    try:
        from sqlalchemy import text
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


def get_info(ticker: str, ttl_minutes: int = 30) -> tuple[dict, bool]:
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
        _store(ticker, info)          # Postgres (if available)
        _file_write(ticker, info)     # File cache (always works)
    else:
        log.info("YF_INFO_CACHE: live fetch for %s returned invalid data — not caching", ticker)
    return info, False
