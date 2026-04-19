# backend/services/prism_service.py
# ═══════════════════════════════════════════════════════════════
# The YieldIQ Prism — consolidated single-round-trip payload for
# the analysis page. Composes existing hex + analysis_cache +
# market_metrics + fair_value_history into ONE object.
#
# Performance budget: <150ms warm, <800ms cold. No new DB tables.
#
# SEBI compliance: no buy/sell/hold/accumulate language in verdict
# labels or anywhere else. Every return carries `disclaimer`.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import json
import logging
import math
import statistics
import time
from datetime import datetime, timezone, date, timedelta
from typing import Any, Optional

from sqlalchemy import text

from backend.services import hex_service
from backend.services.cache_service import cache

logger = logging.getLogger("yieldiq.prism")

_CACHE_TTL = 3600  # 1 hour
_SECTOR_RANK_TTL = 3600  # 1 hour
_SECTOR_RANK_CACHE: dict[str, tuple[float, dict[str, dict]]] = {}

DISCLAIMER = "Model estimate. Not investment advice."


# ── Verdict mapping (SEBI-safe phrasing) ─────────────────────────
# NEVER use buy/sell/hold/accumulate/recommend language here.
_VERDICT_BANDS = [
    # (min_mos, band_key, label)
    (40.0,   "deepValue",   "Deep value region"),
    (20.0,   "undervalued", "Below fair value region"),
    (-10.0,  "fair",        "Fair value region"),
    (-25.0,  "overvalued",  "Priced above fair value"),
    (-999.0, "expensive",   "Notably above fair value"),
]


def _verdict_from_mos(mos_pct: Optional[float]) -> tuple[str, str]:
    if mos_pct is None:
        return "fair", "Fair value region"
    try:
        m = float(mos_pct)
    except (TypeError, ValueError):
        return "fair", "Fair value region"
    if math.isnan(m) or math.isinf(m):
        return "fair", "Fair value region"
    for threshold, key, label in _VERDICT_BANDS:
        if m >= threshold:
            return key, label
    return "expensive", "Notably above fair value"


def _grade_from_score(score_100: Optional[float]) -> str:
    if score_100 is None:
        return "C"
    try:
        s = float(score_100)
    except (TypeError, ValueError):
        return "C"
    if s >= 85:
        return "A+"
    if s >= 75:
        return "A"
    if s >= 60:
        return "B"
    if s >= 45:
        return "C"
    return "D"


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _dig(d: Any, *path, default=None):
    cur = d
    for p in path:
        if cur is None:
            return default
        if isinstance(cur, dict):
            cur = cur.get(p)
        else:
            cur = getattr(cur, p, None)
    return cur if cur is not None else default


def _get_session():
    try:
        from data_pipeline.db import Session  # type: ignore
    except Exception:
        return None
    if Session is None:
        return None
    try:
        return Session()
    except Exception:
        return None


def _safe_close(sess) -> None:
    if sess is None:
        return
    try:
        sess.close()
    except Exception:
        pass


# ── Helpers: pulse velocity + score history + sector rank ───────
def _pulse_velocity_hz(ticker: str) -> float:
    """Map pulse inputs to a breathing rate in Hz, 0.2..1.0. Default 0.33."""
    sess = _get_session()
    if sess is None:
        return 0.33
    try:
        row = sess.execute(
            text(
                "SELECT promoter_delta_qoq, insider_net_30d, "
                "estimate_revision_30d, pledged_pct_delta "
                "FROM hex_pulse_inputs WHERE ticker = :t"
            ),
            {"t": ticker},
        ).fetchone()
    except Exception:
        row = None
    finally:
        _safe_close(sess)

    if not row:
        return 0.33
    raw = 0.0
    for v in row:
        try:
            if v is not None:
                raw += abs(float(v))
        except Exception:
            pass
    # Map raw absolute intensity → 0.2..1.0 Hz. Gentle curve.
    if raw <= 0:
        return 0.33
    hz = 0.2 + min(0.8, raw * 0.25)
    return round(_clamp(hz, 0.2, 1.0), 3)


def _score_history_12m(ticker: str) -> list[int]:
    """Last 12 monthly buckets of yieldiq score scaled 0..100. Empty on <3 rows."""
    sess = _get_session()
    if sess is None:
        return []
    try:
        cutoff = date.today() - timedelta(days=400)
        # fair_value_history has: ticker, date, fair_value, price, mos_pct, confidence
        # We don't have yieldiq_score here directly; derive a proxy from
        # mos_pct clamped [-50..+50] → [0..100].
        try:
            rows = sess.execute(
                text(
                    "SELECT date, mos_pct, confidence "
                    "FROM fair_value_history "
                    "WHERE ticker = :t AND date >= :c "
                    "ORDER BY date ASC"
                ),
                {"t": ticker, "c": cutoff},
            ).fetchall()
        except Exception:
            rows = []
    finally:
        _safe_close(sess)

    if not rows or len(rows) < 3:
        return []

    # Bucket by YYYY-MM keep the last value of the month
    buckets: dict[str, float] = {}
    for r in rows:
        d, mos, conf = r[0], r[1], r[2]
        if d is None:
            continue
        try:
            key = f"{d.year:04d}-{d.month:02d}"
        except Exception:
            continue
        # Score proxy: blend mos (60%) + confidence (40%).
        try:
            mos_f = float(mos) if mos is not None else 0.0
        except Exception:
            mos_f = 0.0
        try:
            conf_f = float(conf) if conf is not None else 50.0
        except Exception:
            conf_f = 50.0
        mos_score = _clamp(50.0 + mos_f, 0.0, 100.0)
        blended = 0.6 * mos_score + 0.4 * _clamp(conf_f, 0.0, 100.0)
        buckets[key] = round(blended)

    ordered = [buckets[k] for k in sorted(buckets.keys())]
    if len(ordered) < 3:
        return []
    return [int(v) for v in ordered[-12:]]


def _sector_rank(ticker: str, sector: Optional[str],
                 yieldiq_score_100: Optional[float]) -> Optional[dict]:
    """Rank ticker within its sector by score. Cached hourly. Returns None
    if sector unknown or computation fails."""
    if not sector or yieldiq_score_100 is None:
        return None
    cache_key = sector.strip().lower()
    if not cache_key:
        return None
    now = time.time()
    hit = _SECTOR_RANK_CACHE.get(cache_key)
    ranks: dict[str, dict]
    if hit and (now - hit[0]) < _SECTOR_RANK_TTL:
        ranks = hit[1]
    else:
        ranks = _compute_sector_rank_table(sector)
        _SECTOR_RANK_CACHE[cache_key] = (now, ranks)

    if not ranks:
        # Fall back: synthesize a single-member rank so UI has something
        return {"rank": 1, "total": 1}

    # Ticker we ranked might be bare or suffixed; try both.
    bare = ticker.replace(".NS", "").replace(".BO", "")
    return ranks.get(ticker) or ranks.get(bare)


def _compute_sector_rank_table(sector: str) -> dict[str, dict]:
    """
    Build a {ticker -> {rank, total}} map for the sector. Cheap query
    against analysis_cache payloads joined with stocks.sector. If
    analysis_cache is empty, returns {}.
    """
    sess = _get_session()
    if sess is None:
        return {}
    try:
        try:
            rows = sess.execute(
                text(
                    """
                    SELECT s.ticker, ac.payload
                    FROM stocks s
                    JOIN analysis_cache ac
                      ON (ac.ticker = s.ticker || '.NS' OR ac.ticker = s.ticker)
                    WHERE s.sector = :sec
                    LIMIT 500
                    """
                ),
                {"sec": sector},
            ).fetchall()
        except Exception:
            rows = []
    finally:
        _safe_close(sess)

    scored: list[tuple[str, float]] = []
    for r in rows:
        tk = r[0]
        payload = r[1]
        if isinstance(payload, (bytes, bytearray)):
            try:
                payload = payload.decode("utf-8")
            except Exception:
                continue
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except Exception:
                continue
        if not isinstance(payload, dict):
            continue
        mos = _dig(payload, "valuation", "margin_of_safety")
        try:
            mos_f = float(mos) if mos is not None else 0.0
        except Exception:
            mos_f = 0.0
        # Coarse score proxy (same scale as yieldiq_score_100 shape)
        score = _clamp(50.0 + mos_f, 0.0, 100.0)
        scored.append((tk, score))

    if not scored:
        return {}

    scored.sort(key=lambda x: x[1], reverse=True)
    total = len(scored)
    out: dict[str, dict] = {}
    for idx, (tk, _s) in enumerate(scored):
        rank_entry = {"rank": idx + 1, "total": total}
        out[tk] = rank_entry
        out[tk.replace(".NS", "").replace(".BO", "")] = rank_entry
        out[f"{tk.replace('.NS', '').replace('.BO', '')}.NS"] = rank_entry
    return out


# ── Analysis cache reader ────────────────────────────────────────
def _fetch_analysis_payload(ticker: str) -> Optional[dict]:
    sess = _get_session()
    if sess is None:
        return None
    try:
        try:
            row = sess.execute(
                text("SELECT payload FROM analysis_cache WHERE ticker = :t"),
                {"t": ticker},
            ).fetchone()
        except Exception:
            row = None
        if not row or not row[0]:
            return None
        payload = row[0]
        if isinstance(payload, (bytes, bytearray)):
            try:
                payload = payload.decode("utf-8")
            except Exception:
                return None
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except Exception:
                return None
        return payload if isinstance(payload, dict) else None
    finally:
        _safe_close(sess)


def _fetch_market_cap_cr(ticker: str) -> Optional[float]:
    sess = _get_session()
    if sess is None:
        return None
    try:
        try:
            row = sess.execute(
                text("SELECT market_cap_cr FROM market_metrics WHERE ticker = :t"),
                {"t": ticker},
            ).fetchone()
        except Exception:
            row = None
        if row and row[0] is not None:
            try:
                return float(row[0])
            except Exception:
                return None
        return None
    finally:
        _safe_close(sess)


def _fetch_company_sector(ticker: str) -> tuple[Optional[str], Optional[str]]:
    """Return (company_name, sector) from stocks table. Bare ticker key."""
    bare = ticker.replace(".NS", "").replace(".BO", "")
    sess = _get_session()
    if sess is None:
        return None, None
    try:
        try:
            row = sess.execute(
                text(
                    "SELECT company_name, sector FROM stocks "
                    "WHERE ticker = :t LIMIT 1"
                ),
                {"t": bare},
            ).fetchone()
        except Exception:
            row = None
        if row:
            return row[0], row[1]
        return None, None
    finally:
        _safe_close(sess)


def _extract_scenarios(analysis: Optional[dict]) -> dict:
    """Pull bear/base/bull scenario fair values from the analysis payload."""
    if not isinstance(analysis, dict):
        return {"bear": None, "base": None, "bull": None}
    scen = analysis.get("scenarios") or {}
    if not isinstance(scen, dict):
        return {"bear": None, "base": None, "bull": None}

    def _val(*keys: str):
        for k in keys:
            node = scen.get(k)
            if node is None:
                continue
            if isinstance(node, (int, float)):
                return float(node)
            if isinstance(node, dict):
                for fk in ("fair_value", "value", "fv", "price"):
                    if node.get(fk) is not None:
                        try:
                            return float(node[fk])
                        except Exception:
                            pass
        return None

    base_fallback = _dig(analysis, "valuation", "fair_value")
    try:
        base_fallback = float(base_fallback) if base_fallback is not None else None
    except Exception:
        base_fallback = None

    return {
        "bear": _val("bear", "pessimistic", "downside"),
        "base": _val("base", "baseline", "central") or base_fallback,
        "bull": _val("bull", "optimistic", "upside"),
    }


def _refraction_index(hex_payload: dict) -> float:
    axes = (hex_payload or {}).get("axes") or {}
    scores: list[float] = []
    for k in ("value", "quality", "growth", "moat", "safety", "pulse"):
        v = axes.get(k) or {}
        try:
            s = float(v.get("score"))
            if not (math.isnan(s) or math.isinf(s)):
                scores.append(s)
        except Exception:
            pass
    if len(scores) < 2:
        return 0.0
    try:
        sd = statistics.pstdev(scores)
    except Exception:
        return 0.0
    return round(_clamp(sd / 3.5, 0.0, 5.0), 3)


def _baseline_payload(ticker: str, compute_ms: float, error: str = "") -> dict:
    """Zeroed/neutral payload returned when nothing else works."""
    now = datetime.now(timezone.utc).isoformat()
    base = {
        "ticker": ticker,
        "company_name": None,
        "sector": None,
        "sector_category": "general",
        "price": None,
        "fair_value": None,
        "mos_pct": None,
        "verdict_band": "fair",
        "verdict_label": "Fair value region",
        "hex": None,
        "refraction_index": 0.0,
        "pulse_velocity_hz": 0.33,
        "yieldiq_score_100": None,
        "grade": "C",
        "sector_rank": None,
        "market_cap_cr": None,
        "scenarios": {"bear": None, "base": None, "bull": None},
        "score_history_12m": [],
        "computed_at": now,
        "compute_ms": round(compute_ms, 2),
        "data_limited": True,
        "disclaimer": DISCLAIMER,
    }
    if error:
        base["error"] = error
    return base


# ── Main consolidator ───────────────────────────────────────────
def get_prism(ticker: str) -> dict:
    """Return the consolidated Prism payload for a ticker. Never raises."""
    t0 = time.perf_counter()
    try:
        norm = hex_service._normalize_ticker(ticker) or ticker
    except Exception:
        norm = ticker

    cache_key = f"prism:{(norm or '').upper()}"
    try:
        cached = cache.get(cache_key)
    except Exception:
        cached = None
    if cached is not None:
        # Refresh compute_ms to reflect warm-read latency
        try:
            warm = (time.perf_counter() - t0) * 1000.0
            # Return a shallow copy so we don't mutate the cached object
            out = dict(cached)
            out["compute_ms"] = round(warm, 2)
            out["cached"] = True
            return out
        except Exception:
            return cached

    try:
        result = _build_prism(norm, t0)
        try:
            cache.set(cache_key, result, ttl=_CACHE_TTL)
        except Exception:
            pass
        return result
    except Exception as exc:
        logger.warning("prism: build failed for %s: %s", norm, exc)
        elapsed = (time.perf_counter() - t0) * 1000.0
        return _baseline_payload(norm, elapsed, error="compute_error")


def _build_prism(ticker: str, t0: float) -> dict:
    # 1. Hex (always safe — never raises)
    try:
        hex_payload = hex_service.compute_hex_safe(ticker)
    except Exception:
        hex_payload = None

    # 2. Analysis payload (may be None)
    try:
        analysis = _fetch_analysis_payload(ticker)
    except Exception:
        analysis = None

    # 3. Company + sector meta
    try:
        company_name, sector = _fetch_company_sector(ticker)
    except Exception:
        company_name, sector = None, None

    # analysis payload may carry company_info overrides
    if not company_name:
        company_name = (
            _dig(analysis, "company_info", "name")
            or _dig(analysis, "company_info", "company_name")
        )
    if not sector:
        sector = _dig(analysis, "company_info", "sector")

    sector_category = (hex_payload or {}).get("sector_category", "general")

    # 4. Price / fair_value / MoS
    price = _dig(analysis, "valuation", "current_price")
    fair_value = _dig(analysis, "valuation", "fair_value")
    mos_pct = _dig(analysis, "valuation", "margin_of_safety")

    # Derive mos if missing — use the CANONICAL formula (FV-CMP)/CMP that
    # matches analysis_service's mos_pct (post-FIX1, single source of truth).
    # Was previously (FV-CMP)/FV — caused verdict band to mis-classify
    # stocks (e.g. HCLTECH +27% MoS shown as "Expensive Region").
    if mos_pct is None and fair_value and price:
        try:
            fv_f = float(fair_value)
            px_f = float(price)
            if px_f > 0:
                mos_pct = (fv_f - px_f) / px_f * 100.0
        except Exception:
            mos_pct = None

    try:
        price = float(price) if price is not None else None
    except Exception:
        price = None
    try:
        fair_value = float(fair_value) if fair_value is not None else None
    except Exception:
        fair_value = None
    try:
        mos_pct = round(float(mos_pct), 2) if mos_pct is not None else None
    except Exception:
        mos_pct = None

    verdict_band, verdict_label = _verdict_from_mos(mos_pct)

    # 5. yieldiq_score_100 from hex overall
    overall = _dig(hex_payload, "overall")
    try:
        yieldiq_score_100 = int(round(float(overall) * 10)) if overall is not None else None
        if yieldiq_score_100 is not None:
            yieldiq_score_100 = int(_clamp(yieldiq_score_100, 0, 100))
    except Exception:
        yieldiq_score_100 = None
    grade = _grade_from_score(yieldiq_score_100)

    # 6. Refraction index + pulse velocity
    refraction_index = _refraction_index(hex_payload or {})
    try:
        pulse_hz = _pulse_velocity_hz(ticker)
    except Exception:
        pulse_hz = 0.33

    # 7. market cap
    market_cap_cr = _fetch_market_cap_cr(ticker)

    # 8. scenarios
    scenarios = _extract_scenarios(analysis)

    # 9. score history
    try:
        score_history_12m = _score_history_12m(ticker)
    except Exception:
        score_history_12m = []

    # 10. sector rank (optional, cached hourly)
    try:
        sector_rank = _sector_rank(ticker, sector, yieldiq_score_100)
    except Exception:
        sector_rank = None

    data_limited = (
        analysis is None
        or price is None
        or fair_value is None
        or mos_pct is None
    )

    elapsed = (time.perf_counter() - t0) * 1000.0

    return {
        "ticker": ticker,
        "company_name": company_name,
        "sector": sector,
        "sector_category": sector_category,
        "price": price,
        "fair_value": fair_value,
        "mos_pct": mos_pct,
        "verdict_band": verdict_band,
        "verdict_label": verdict_label,
        "hex": hex_payload,
        "refraction_index": refraction_index,
        "pulse_velocity_hz": pulse_hz,
        "yieldiq_score_100": yieldiq_score_100,
        "grade": grade,
        "sector_rank": sector_rank,
        "market_cap_cr": market_cap_cr,
        "scenarios": scenarios,
        "score_history_12m": score_history_12m,
        "computed_at": datetime.now(timezone.utc).isoformat(),
        "compute_ms": round(elapsed, 2),
        "data_limited": data_limited,
        "cached": False,
        "disclaimer": DISCLAIMER,
    }


def compare_prisms(t1: str, t2: str) -> dict:
    """Side-by-side comparison. Returns {stock1, stock2, overlap}."""
    p1 = get_prism(t1)
    p2 = get_prism(t2)
    overlap: dict = {"per_axis_delta": {}, "overall_delta": 0.0,
                     "score_delta": 0.0, "mos_delta": 0.0}
    try:
        axes1 = _dig(p1, "hex", "axes") or {}
        axes2 = _dig(p2, "hex", "axes") or {}
        for k in ("value", "quality", "growth", "moat", "safety", "pulse"):
            try:
                s1 = float((axes1.get(k) or {}).get("score", 5.0))
                s2 = float((axes2.get(k) or {}).get("score", 5.0))
                overlap["per_axis_delta"][k] = round(s1 - s2, 2)
            except Exception:
                overlap["per_axis_delta"][k] = 0.0
        try:
            overlap["overall_delta"] = round(
                float(_dig(p1, "hex", "overall") or 5.0)
                - float(_dig(p2, "hex", "overall") or 5.0),
                2,
            )
        except Exception:
            pass
        try:
            s1 = p1.get("yieldiq_score_100")
            s2 = p2.get("yieldiq_score_100")
            if s1 is not None and s2 is not None:
                overlap["score_delta"] = int(s1) - int(s2)
        except Exception:
            pass
        try:
            m1 = p1.get("mos_pct")
            m2 = p2.get("mos_pct")
            if m1 is not None and m2 is not None:
                overlap["mos_delta"] = round(float(m1) - float(m2), 2)
        except Exception:
            pass
    except Exception as exc:
        logger.warning("prism: compare overlap failed: %s", exc)

    return {
        "stock1": p1,
        "stock2": p2,
        "overlap": overlap,
        "disclaimer": DISCLAIMER,
    }


__all__ = ["get_prism", "compare_prisms", "DISCLAIMER"]
