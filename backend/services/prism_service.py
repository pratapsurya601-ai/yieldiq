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

from sqlalchemy import bindparam, text

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
    # P0 null-pillar gate (2026-05-02): when mos_pct is missing the
    # caller (or `assign_verdict`) is expected to surface "Under
    # Review" — never silently default to "Fair value region". The
    # methodology page promises an explicit "Under Review" verdict
    # for insufficient data; the previous `"fair" / "Fair value
    # region"` fallback violated that promise (audit hits on
    # /prism/HEALTHCARE, /prism/SHAQUAK, /prism/TRL).
    if mos_pct is None:
        return "data_limited", "Under Review"
    try:
        m = float(mos_pct)
    except (TypeError, ValueError):
        return "data_limited", "Under Review"
    if math.isnan(m) or math.isinf(m):
        return "data_limited", "Under Review"
    for threshold, key, label in _VERDICT_BANDS:
        if m >= threshold:
            return key, label
    return "expensive", "Notably above fair value"


def _count_null_pillars(hex_payload: Optional[dict]) -> int:
    """Count pillars (axes) that lack a real score.

    A pillar is "null" if its dict is missing, its `score` key is
    None, OR `data_limited` is True (the latter is how
    `hex_service._neutral_axis` flags placeholder 5.0 fills).
    """
    axes = (hex_payload or {}).get("axes") or {}
    if not isinstance(axes, dict) or not axes:
        # No axes at all = every pillar is null.
        return 6
    null_count = 0
    for _key, node in axes.items():
        if not isinstance(node, dict):
            null_count += 1
            continue
        if node.get("score") is None:
            null_count += 1
            continue
        if node.get("data_limited") is True:
            null_count += 1
    return null_count


def assign_verdict(
    hex_payload: Optional[dict],
    mos_pct: Optional[float],
) -> tuple[str, str, Optional[float], Optional[str]]:
    """Return (verdict_band, verdict_label, composite_score, reason).

    P0 null-pillar gate: when 3 or more of the 6 pillars have no
    real score, force "Under Review" instead of letting MoS drive a
    misleading "Fair value region · 5.0/10" composite.
    """
    null_count = _count_null_pillars(hex_payload)
    if null_count >= 3:
        return (
            "data_limited",
            "Under Review",
            None,
            f"Insufficient data — {6 - null_count} of 6 pillars scored",
        )
    band, label = _verdict_from_mos(mos_pct)
    return band, label, None, None


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
    """Last 12 monthly buckets of yieldiq score scaled 0..100.

    Empty on <2 monthly buckets — matches the frontend Sparkline gate
    (``points.length < 2``) so backend and UI agree on what "insufficient
    history" means. Earlier this was <3 which produced "Insufficient
    history" for tickers with only 2 months of fair_value_history data
    even though the sparkline would happily draw a 2-point line.

    Queries ``fair_value_history`` under both the canonical ``TITAN.NS``
    form and the bare ``TITAN`` form. Historical rows were written via
    two code paths that disagreed on suffix handling (store_today_fair_value
    persists whatever ticker it's given, typically canonical; some
    backfill/admin paths stripped .NS/.BO first). Matching both forms
    ensures the sparkline renders regardless of which writer touched
    the row most recently. See fix/score-history-12m-pipeline (2026-04-23).
    """
    sess = _get_session()
    if sess is None:
        return []
    try:
        cutoff = date.today() - timedelta(days=400)
        # Accept both canonical (TICKER.NS) and bare (TICKER) forms.
        bare = ticker.replace(".NS", "").replace(".BO", "")
        candidates = {ticker, bare}
        # fair_value_history has: ticker, date, fair_value, price, mos_pct, confidence
        # We don't have yieldiq_score here directly; derive a proxy from
        # mos_pct clamped [-50..+50] → [0..100].
        try:
            rows = sess.execute(
                text(
                    "SELECT date, mos_pct, confidence "
                    "FROM fair_value_history "
                    "WHERE ticker IN :tickers AND date >= :c "
                    "ORDER BY date ASC"
                ).bindparams(bindparam("tickers", expanding=True)),
                {"tickers": list(candidates), "c": cutoff},
            ).fetchall()
        except Exception:
            rows = []
    finally:
        _safe_close(sess)

    if not rows:
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
    if len(ordered) < 2:
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
        # Accept canonical (TICKER.NS) and bare forms — market_metrics
        # rows are written by two code paths that disagree on suffix
        # handling (same class of bug as fair_value_history, see PR #34).
        # HDFCBANK is the canary: canonical ticker lookup returned None
        # even though market_metrics had a bare-ticker row → bank-branch
        # moat axis lost its scale signal → rendered "n/a" on prod
        # 2026-04-23.
        bare = ticker.replace(".NS", "").replace(".BO", "")
        candidates = [ticker, bare] if ticker != bare else [ticker]
        for cand in candidates:
            try:
                # ORDER BY trade_date DESC LIMIT 1 - dual-listed tickers
                # (NSE+BSE) have two rows in market_metrics; pick the
                # freshest. See design note in backend/routers/screener.py.
                # PR #218 read-path fallback: skip NULL-mcap rows + prefer high-trust source.
                # Prevents 2026-04-30 yfinance-NULL incident class.
                row = sess.execute(
                    text(
                        "SELECT market_cap_cr FROM market_metrics "
                        "WHERE ticker = :t "
                        "AND market_cap_cr IS NOT NULL AND market_cap_cr > 0 "
                        "ORDER BY COALESCE(data_quality_rank, 50) ASC, trade_date DESC LIMIT 1"
                    ),
                    {"t": cand},
                ).fetchone()
            except Exception:
                row = None
            if row and row[0] is not None:
                try:
                    return float(row[0])
                except Exception:
                    continue
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
    """Pull bear/base/bull scenario fair values from the analysis payload.

    `base_unclamped` is the base-case scenario IV taken straight from the
    pre-clamp scenarios dict (not the post-clamp valuation.fair_value).
    Used by the public Prism payload + visitor analysis hero to recover
    the meaningful base-case FV when the headline has been clamped to a
    plausible bound (see backend/routers/analysis.py FV clamp + the
    NOIDATOLL +200% MoS bug fixed in PR #108 / its visitor follow-up).
    """
    out = {"bear": None, "base": None, "bull": None, "base_unclamped": None}
    if not isinstance(analysis, dict):
        return out
    scen = analysis.get("scenarios") or {}
    if not isinstance(scen, dict):
        return out

    def _val(*keys: str):
        for k in keys:
            node = scen.get(k)
            if node is None:
                continue
            if isinstance(node, (int, float)):
                return float(node)
            if isinstance(node, dict):
                for fk in ("iv", "fair_value", "value", "fv", "price"):
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

    base_real = _val("base", "baseline", "central")
    out["bear"] = _val("bear", "pessimistic", "downside")
    out["base"] = base_real if base_real is not None else base_fallback
    out["bull"] = _val("bull", "optimistic", "upside")
    # base_unclamped: only set when the scenarios dict carried a real
    # base value — never the post-clamp valuation.fair_value fallback.
    out["base_unclamped"] = base_real
    return out


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
        # P0 null-pillar gate: the baseline payload is returned when
        # the entire compute path errors out — by definition we have
        # zero pillar scores, so the verdict is "Under Review", not
        # "Fair value region". (Previous default silently shipped a
        # 5.0/10 composite for tickers like /prism/HEALTHCARE.)
        "verdict_band": "data_limited",
        "verdict_label": "Under Review",
        "composite_score": None,
        "verdict_reason": "Insufficient data — fewer than 4 pillars scored",
        "hex": None,
        "refraction_index": 0.0,
        "pulse_velocity_hz": 0.33,
        "yieldiq_score_100": None,
        "grade": "C",
        "sector_rank": None,
        "market_cap_cr": None,
        "scenarios": {"bear": None, "base": None, "bull": None, "base_unclamped": None},
        "fv_clamped": False,
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

    # PR INFY-PRICE-CASCADE (2026-04-30): authoritative price comes
    # from live_quotes → daily_prices → yfinance cascade, NOT from
    # the analysis_cache snapshot which may have been computed when
    # yfinance was returning poison values (INFY ₹0 / ₹1,09,652).
    # Recomputing MoS here is intentional — the analysis snapshot's
    # MoS would compound the bad price; using a fresh, trusted price
    # against the cached fair_value gives the right verdict band.
    try:
        from backend.services.market_data_service import get_canonical_price
        _canonical_px = get_canonical_price(ticker, yf_fallback=price)
        if _canonical_px is not None and _canonical_px > 0:
            try:
                _stale = float(price) if price is not None else None
            except Exception:
                _stale = None
            if _stale is None or abs(_stale - _canonical_px) > 0.01:
                logger.info(
                    "prism: %s price overridden by canonical cascade: "
                    "cache=%s → canonical=%.2f",
                    ticker, _stale, _canonical_px,
                )
                # Recompute MoS against the trusted price so the
                # verdict band reflects reality, not the poisoned
                # snapshot. Same canonical (FV-CMP)/CMP formula
                # used elsewhere in this file.
                if fair_value is not None and _canonical_px > 0:
                    try:
                        mos_pct = (float(fair_value) - _canonical_px) / _canonical_px * 100.0
                    except Exception:
                        pass
            price = _canonical_px
    except Exception as exc:
        logger.warning("prism: canonical price cascade failed for %s: %s", ticker, exc)

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

    # P0 MoS standardization (2026-05-02): clamp the displayed MoS to
    # [-100, +200]. Raw value is preserved in `mos_pct_raw`; clamped
    # value replaces `mos_pct`; `mos_clamped` flags whether the clamp
    # actually changed the number.
    mos_pct_raw = mos_pct
    mos_clamped = False
    if mos_pct is not None:
        from backend.services.analysis.utils import display_mos as _display_mos
        _d, _c = _display_mos(mos_pct)
        if _d is not None:
            mos_pct = round(_d, 2)
            mos_clamped = _c

    # P0 null-pillar gate: when ≥3 pillars are unscored, surface
    # "Under Review" instead of the misleading MoS-based default.
    verdict_band, verdict_label, _composite_override, verdict_reason = (
        assign_verdict(hex_payload, mos_pct)
    )

    # 5. yieldiq_score_100 from hex overall
    overall = _dig(hex_payload, "overall")
    try:
        yieldiq_score_100 = int(round(float(overall) * 10)) if overall is not None else None
        if yieldiq_score_100 is not None:
            yieldiq_score_100 = int(_clamp(yieldiq_score_100, 0, 100))
    except Exception:
        yieldiq_score_100 = None
    grade = _grade_from_score(yieldiq_score_100)

    # P0 null-pillar gate: if the verdict is "Under Review" the
    # composite score is meaningless (it would have averaged to ~5.0
    # via the neutral-axis fallback). Null it out so the UI shows
    # "—" instead of a confident-looking 5.0/10.
    if verdict_band == "data_limited" and verdict_label == "Under Review":
        yieldiq_score_100 = None
        grade = None  # downstream renderers must handle None grade

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

    # 8b. FV-clamp flag — surfaced to the visitor analysis hero so it can
    # render the unclamped base-case scenario instead of the misleading
    # clamped headline (NOIDATOLL +200% bug, follow-up to PR #108).
    # Single source of truth: analysis_cache.payload.data_issues string
    # emitted by the same code path that performs the clamp
    # (backend/routers/analysis.py).
    fv_clamped = False
    try:
        _issues = (analysis or {}).get("data_issues") or []
        if isinstance(_issues, list):
            fv_clamped = any(
                isinstance(s, str) and "Fair value clamped" in s for s in _issues
            )
    except Exception:
        fv_clamped = False

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
        or verdict_band == "data_limited"
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
        "mos_pct_raw": mos_pct_raw,
        "mos_clamped": mos_clamped,
        "verdict_band": verdict_band,
        "verdict_label": verdict_label,
        # P0 null-pillar gate: composite_score mirrors yieldiq_score_100
        # but is None when the gate fires — surfaced separately so any
        # downstream caller looking for "the headline number" gets a
        # null instead of falling back to the score field.
        "composite_score": yieldiq_score_100,
        "verdict_reason": verdict_reason,
        "hex": hex_payload,
        "refraction_index": refraction_index,
        "pulse_velocity_hz": pulse_hz,
        "yieldiq_score_100": yieldiq_score_100,
        "grade": grade,
        "sector_rank": sector_rank,
        "market_cap_cr": market_cap_cr,
        "scenarios": scenarios,
        "fv_clamped": fv_clamped,
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
