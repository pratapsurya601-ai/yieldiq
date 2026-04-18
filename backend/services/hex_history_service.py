# backend/services/hex_history_service.py
# ═══════════════════════════════════════════════════════════════
# The YieldIQ Prism — Time Machine backend.
#
# Reads (or computes + stores) the last N quarterly snapshots of the
# 6-axis Hex for a ticker. The "historical" snapshot is an
# approximation synthesized from point-in-time quarterly financials
# (company_financials table) plus the current fair value scaled by
# revenue ratio. This is NOT a perfect backtest — it's a directional
# visualisation of how the shape breathes through time.
#
# Approximation caveats (documented honestly in the payload):
#   - Quality / Moat / Safety / Growth — reconstruct faithfully from
#     point-in-time quarterly financials via the same formulas as
#     hex_service.
#   - Value — reconstructs MoS by scaling today's fair_value by the
#     revenue ratio (quarter_revenue / current_revenue). Price taken
#     from fair_value_history / live_quotes when available, else None.
#     Approximate, but directionally right.
#   - Pulse — we do NOT have historical hex_pulse_inputs. Current
#     quarter uses the real pulse; past quarters return None (UI
#     renders as a grey lens). Honest.
#
# SEBI: every response carries a disclaimer; no buy/sell language.
# Never raises: uncomputable quarters are omitted.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import logging
import math
import statistics
from datetime import date, datetime, timezone
from typing import Any, Optional

from sqlalchemy import text

from backend.services import hex_service
from backend.services.hex_service import AXIS_WEIGHTS, _classify_sector, _normalize_ticker

logger = logging.getLogger("yieldiq.hex_history")

DISCLAIMER = (
    "Model estimate. Historical snapshots reconstructed from quarterly "
    "financials. Not investment advice."
)


# ── DB helpers ────────────────────────────────────────────────────
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


_HISTORY_TABLE_CHECKED = False


def _ensure_history_table() -> None:
    """Idempotently create hex_history if missing. Runs once per process."""
    global _HISTORY_TABLE_CHECKED
    if _HISTORY_TABLE_CHECKED:
        return
    sess = _get_session()
    if sess is None:
        _HISTORY_TABLE_CHECKED = True
        return
    try:
        sess.execute(text(
            """
            CREATE TABLE IF NOT EXISTS hex_history (
              ticker            TEXT NOT NULL,
              quarter_end       DATE NOT NULL,
              value_score       NUMERIC,
              quality_score     NUMERIC,
              growth_score      NUMERIC,
              moat_score        NUMERIC,
              safety_score      NUMERIC,
              pulse_score       NUMERIC,
              overall           NUMERIC,
              refraction_index  NUMERIC,
              verdict_band      TEXT,
              computed_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
              PRIMARY KEY (ticker, quarter_end)
            )
            """
        ))
        sess.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_hex_history_ticker "
            "ON hex_history(ticker)"
        ))
        sess.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_hex_history_quarter "
            "ON hex_history(quarter_end DESC)"
        ))
        sess.commit()
        _HISTORY_TABLE_CHECKED = True
    except Exception as exc:
        logger.warning("hex_history: ensure table failed: %s", exc)
        try:
            sess.rollback()
        except Exception:
            pass
    finally:
        _safe_close(sess)


try:
    _ensure_history_table()
except Exception:
    pass


# ── Quarter utilities ─────────────────────────────────────────────
def _last_closed_quarter_end(today: Optional[date] = None) -> date:
    """Return the most recent closed quarter-end date (Mar/Jun/Sep/Dec)."""
    today = today or date.today()
    y = today.year
    m = today.month
    # Closed quarters: quarter ends at least 1 day ago
    if m <= 3:
        return date(y - 1, 12, 31)
    if m <= 6:
        return date(y, 3, 31)
    if m <= 9:
        return date(y, 6, 30)
    if m <= 12:
        return date(y, 9, 30)
    return date(y, 12, 31)


def _prev_quarter_end(q: date) -> date:
    """Step back one quarter."""
    y, m = q.year, q.month
    if m == 3:
        return date(y - 1, 12, 31)
    if m == 6:
        return date(y, 3, 31)
    if m == 9:
        return date(y, 6, 30)
    if m == 12:
        return date(y, 9, 30)
    # fallback — shouldn't happen for a valid quarter_end
    return date(y, max(1, m - 3), 1)


def _recent_quarters(n: int) -> list[date]:
    """Return N most-recent closed quarter-ends, oldest first."""
    q = _last_closed_quarter_end()
    out = [q]
    for _ in range(n - 1):
        q = _prev_quarter_end(q)
        out.append(q)
    return list(reversed(out))


# ── Axis reconstruction helpers ───────────────────────────────────
def _clamp(x: float, lo: float = 0.0, hi: float = 10.0) -> float:
    try:
        x = float(x)
    except (TypeError, ValueError):
        return 5.0
    if math.isnan(x) or math.isinf(x):
        return 5.0
    return max(lo, min(hi, x))


def _verdict_band_from_mos(mos_pct: Optional[float]) -> str:
    if mos_pct is None:
        return "fair"
    try:
        m = float(mos_pct)
    except (TypeError, ValueError):
        return "fair"
    if math.isnan(m) or math.isinf(m):
        return "fair"
    if m >= 40.0:
        return "deepValue"
    if m >= 20.0:
        return "undervalued"
    if m >= -10.0:
        return "fair"
    if m >= -25.0:
        return "overvalued"
    return "expensive"


def _fetch_financials_asof(sess, bare_ticker: str, quarter_end: date,
                           lookback_rows: int = 8) -> list[dict]:
    """Return up to `lookback_rows` of company_financials rows whose
    period_end_date <= quarter_end, newest first. Used both for point-in-time
    TTM synthesis and for N-year CAGR windows."""
    try:
        rows = sess.execute(
            text(
                """
                SELECT period_end_date, period_type, statement_type,
                       revenue, ebitda, ebit, net_income, operating_cf,
                       free_cash_flow, eps_basic, eps_diluted,
                       total_debt, total_equity, interest_expense,
                       current_assets, current_liabilities, retained_earnings,
                       total_assets
                FROM company_financials
                WHERE ticker_nse = :t
                  AND period_end_date IS NOT NULL
                  AND period_end_date <= :q
                ORDER BY period_end_date DESC
                LIMIT :lim
                """
            ),
            {"t": bare_ticker, "q": quarter_end, "lim": lookback_rows},
        ).fetchall()
    except Exception as exc:
        logger.debug("hex_history: financials fetch failed %s @ %s: %s",
                     bare_ticker, quarter_end, exc)
        return []

    out: list[dict] = []
    for r in rows:
        out.append({
            "period_end": r[0],
            "period_type": r[1],
            "statement_type": r[2],
            "revenue": r[3],
            "ebitda": r[4],
            "ebit": r[5],
            "net_income": r[6],
            "operating_cf": r[7],
            "fcf": r[8],
            "eps_basic": r[9],
            "eps_diluted": r[10],
            "total_debt": r[11],
            "total_equity": r[12],
            "interest_expense": r[13],
            "current_assets": r[14],
            "current_liabilities": r[15],
            "retained_earnings": r[16],
            "total_assets": r[17],
        })
    return out


def _annual_like_series(rows: list[dict]) -> list[dict]:
    """Collapse to one revenue/eps/etc row per fiscal year, newest first.
    We prefer annual rows; if only quarterly available, pick the Mar-end
    (fiscal-year-end) quarter rows. Rough but OK for CAGR anchors."""
    by_year: dict[int, dict] = {}
    for r in rows:
        pe = r.get("period_end")
        if pe is None:
            continue
        try:
            yr = pe.year
        except Exception:
            continue
        ptype = (r.get("period_type") or "").lower()
        is_annual = "ann" in ptype
        # Prefer annual rows; otherwise accept Mar-end quarter as FY proxy
        if is_annual:
            by_year[yr] = r
        elif yr not in by_year and getattr(pe, "month", 0) == 3:
            by_year[yr] = r
    # Newest first
    return [by_year[y] for y in sorted(by_year.keys(), reverse=True)]


def _safe_float(x) -> Optional[float]:
    if x is None:
        return None
    try:
        f = float(x)
        if math.isnan(f) or math.isinf(f):
            return None
        return f
    except (TypeError, ValueError):
        return None


def _compute_quality_axis(annuals: list[dict]) -> Optional[float]:
    """ROCE proxy + margin stability. Score 0..10. None if insufficient."""
    if not annuals:
        return None
    latest = annuals[0]
    reasons_count = 0
    score = 5.0
    # ROCE proxy: EBIT / (total_assets - current_liabilities) ~ capital employed
    ebit = _safe_float(latest.get("ebit"))
    ta = _safe_float(latest.get("total_assets"))
    cl = _safe_float(latest.get("current_liabilities"))
    if ebit is not None and ta is not None and cl is not None:
        ce = ta - cl
        if ce and ce > 0:
            roce = ebit / ce * 100.0
            # same scaling as hex_service: anchor 15%, delta 0.12/pct
            score += (roce - 15.0) * 0.12
            reasons_count += 1
    # Operating margin stability (via ebit/revenue sequence)
    margins = []
    for r in annuals[:5]:
        rev = _safe_float(r.get("revenue"))
        eb = _safe_float(r.get("ebit"))
        if rev and rev > 0 and eb is not None:
            margins.append(eb / rev * 100.0)
    if len(margins) >= 3:
        try:
            sd = statistics.pstdev(margins)
            score += max(-1.0, min(1.0, (5.0 - sd) * 0.1))
            reasons_count += 1
        except Exception:
            pass
    # Net-income positivity gives a small bonus (sanity)
    ni = _safe_float(latest.get("net_income"))
    if ni is not None:
        score += 0.5 if ni > 0 else -0.5
        reasons_count += 1
    if reasons_count == 0:
        return None
    return round(_clamp(score), 2)


def _compute_growth_axis(annuals: list[dict]) -> Optional[float]:
    """Revenue + EPS CAGR over available window, up to 3y."""
    if len(annuals) < 3:
        return None
    # annuals are newest-first
    revs = [_safe_float(r.get("revenue")) for r in annuals]
    revs = [v for v in revs if v is not None and v > 0]
    eps = [_safe_float(r.get("eps_diluted")) or _safe_float(r.get("eps_basic"))
           for r in annuals]
    eps = [v for v in eps if v is not None and v > 0]

    score = 5.0
    got = 0
    if len(revs) >= 3:
        new, old = revs[0], revs[-1]
        years = len(revs) - 1
        try:
            cagr = ((new / old) ** (1.0 / years) - 1.0) * 100.0
            score += cagr * 0.10
            got += 1
        except Exception:
            pass
    if len(eps) >= 3:
        new, old = eps[0], eps[-1]
        years = len(eps) - 1
        try:
            cagr = ((new / old) ** (1.0 / years) - 1.0) * 100.0
            score += cagr * 0.08
            got += 1
        except Exception:
            pass
    if got == 0:
        return None
    return round(_clamp(score), 2)


def _compute_moat_axis(annuals: list[dict], current_moat_grade: Optional[str]) -> Optional[float]:
    """Moat is mostly structural; we anchor on today's grade (moat doesn't
    swing quarter to quarter) and modulate by historical margin stability."""
    score = 5.0
    reasons_count = 0
    if isinstance(current_moat_grade, str):
        g = current_moat_grade.lower()
        if "wide" in g:
            score += 3.0
            reasons_count += 1
        elif "narrow" in g:
            score += 1.5
            reasons_count += 1
        elif "none" in g or g == "no moat":
            score -= 1.5
            reasons_count += 1
    # Historical margin stability
    margins = []
    for r in annuals[:5]:
        rev = _safe_float(r.get("revenue"))
        eb = _safe_float(r.get("ebit"))
        if rev and rev > 0 and eb is not None:
            margins.append(eb / rev * 100.0)
    if len(margins) >= 3:
        try:
            sd = statistics.pstdev(margins)
            score += max(-0.5, min(1.0, (5.0 - sd) * 0.15))
            reasons_count += 1
        except Exception:
            pass
    if reasons_count == 0:
        return None
    return round(_clamp(score), 2)


def _compute_safety_axis(annuals: list[dict]) -> Optional[float]:
    """D/E + interest coverage from the latest annual-equivalent snapshot."""
    if not annuals:
        return None
    r = annuals[0]
    score = 5.0
    reasons_count = 0
    # D/E
    td = _safe_float(r.get("total_debt"))
    te = _safe_float(r.get("total_equity"))
    if td is not None and te and te > 0:
        de = td / te
        score += max(-3.0, min(2.5, (1.0 - de) * 2.0))
        reasons_count += 1
    # Interest coverage
    eb = _safe_float(r.get("ebit"))
    ie = _safe_float(r.get("interest_expense"))
    if eb is not None and ie and abs(ie) > 0:
        ic = eb / abs(ie)
        score += max(-2.0, min(2.0, (ic - 4.0) * 0.25))
        reasons_count += 1
    # Altman-Z-ish proxy: retained_earnings / total_assets
    re = _safe_float(r.get("retained_earnings"))
    ta = _safe_float(r.get("total_assets"))
    if re is not None and ta and ta > 0:
        z_proxy = re / ta
        score += max(-1.0, min(1.0, z_proxy * 3.0))
        reasons_count += 1
    if reasons_count == 0:
        return None
    return round(_clamp(score), 2)


def _compute_value_axis(quarter_revenue: Optional[float],
                        current_revenue: Optional[float],
                        current_fair_value: Optional[float],
                        price_at_quarter: Optional[float]
                        ) -> tuple[Optional[float], Optional[float]]:
    """Reconstruct MoS by scaling today's fair value by the revenue ratio.
    Returns (value_score_0_to_10, mos_pct). None if insufficient data.

    APPROXIMATION: fair_value_at_quarter ≈ fair_value_today * (rev_q / rev_now).
    This is a rough surrogate — it assumes the multiple stayed constant and
    that revenue is the dominant driver of fair value. Good enough to make
    the shape breathe directionally; not a backtest."""
    if (quarter_revenue is None or current_revenue is None or
            current_fair_value is None or price_at_quarter is None):
        return None, None
    try:
        if current_revenue <= 0 or current_fair_value <= 0:
            return None, None
        fv_q = current_fair_value * (quarter_revenue / current_revenue)
        if fv_q <= 0:
            return None, None
        mos_pct = (fv_q - price_at_quarter) / fv_q * 100.0
        # Same anchor as hex_service general value
        score = 5.0 + 0.15 * mos_pct
        return round(_clamp(score), 2), round(mos_pct, 2)
    except Exception:
        return None, None


def _fetch_current_fv_and_revenue(sess, ticker_nse: str, bare: str
                                  ) -> tuple[Optional[float], Optional[float]]:
    """Today's fair_value (from analysis_cache) and latest revenue."""
    fv = None
    try:
        row = sess.execute(
            text("SELECT payload FROM analysis_cache WHERE ticker = :t"),
            {"t": ticker_nse},
        ).fetchone()
        if row and row[0]:
            payload = row[0]
            if isinstance(payload, (bytes, bytearray)):
                payload = payload.decode("utf-8")
            if isinstance(payload, str):
                import json as _json
                try:
                    payload = _json.loads(payload)
                except Exception:
                    payload = None
            if isinstance(payload, dict):
                v = (((payload.get("valuation") or {})).get("fair_value")
                     if isinstance(payload.get("valuation"), dict) else None)
                fv = _safe_float(v)
    except Exception:
        fv = None

    rev = None
    try:
        row = sess.execute(
            text(
                """
                SELECT revenue FROM company_financials
                WHERE ticker_nse = :t AND revenue IS NOT NULL
                ORDER BY period_end_date DESC LIMIT 1
                """
            ),
            {"t": bare},
        ).fetchone()
        if row:
            rev = _safe_float(row[0])
    except Exception:
        rev = None
    return fv, rev


def _fetch_price_at_quarter(sess, ticker_nse: str,
                            quarter_end: date) -> Optional[float]:
    """Pull a point-in-time price near quarter_end. Tries fair_value_history
    first (has price), then falls back to None."""
    try:
        row = sess.execute(
            text(
                """
                SELECT price FROM fair_value_history
                WHERE ticker = :t AND date <= :q AND price IS NOT NULL
                ORDER BY date DESC LIMIT 1
                """
            ),
            {"t": ticker_nse, "q": quarter_end},
        ).fetchone()
        if row and row[0] is not None:
            return _safe_float(row[0])
    except Exception:
        pass
    return None


def _fetch_current_moat_grade(sess, ticker_nse: str) -> Optional[str]:
    try:
        row = sess.execute(
            text("SELECT payload FROM analysis_cache WHERE ticker = :t"),
            {"t": ticker_nse},
        ).fetchone()
        if row and row[0]:
            payload = row[0]
            if isinstance(payload, (bytes, bytearray)):
                payload = payload.decode("utf-8")
            if isinstance(payload, str):
                import json as _json
                try:
                    payload = _json.loads(payload)
                except Exception:
                    payload = None
            if isinstance(payload, dict):
                q = payload.get("quality") or {}
                if isinstance(q, dict):
                    return q.get("moat")
    except Exception:
        pass
    return None


def _refraction(scores: list[Optional[float]]) -> float:
    vals = [s for s in scores if s is not None]
    if len(vals) < 2:
        return 0.0
    try:
        sd = statistics.pstdev(vals)
    except Exception:
        return 0.0
    return round(max(0.0, min(5.0, sd / 3.5)), 3)


def _weighted_overall(axes: dict[str, Optional[float]]) -> Optional[float]:
    """Compute overall using only the axes that are non-null, renormalizing
    weights. Returns None if too few axes available."""
    present = {k: v for k, v in axes.items() if v is not None}
    if len(present) < 4:
        return None
    total_w = sum(AXIS_WEIGHTS[k] for k in present)
    if total_w <= 0:
        return None
    s = sum(AXIS_WEIGHTS[k] * present[k] for k in present) / total_w
    return round(max(0.0, min(10.0, s)), 2)


# ── Per-quarter snapshot synthesis ───────────────────────────────
def _compute_snapshot(sess, ticker_nse: str, bare: str, quarter_end: date,
                      is_current_quarter: bool,
                      current_fair_value: Optional[float],
                      current_revenue: Optional[float],
                      current_moat_grade: Optional[str]) -> Optional[dict]:
    """Build ONE quarter's snapshot. Returns None if < 4 axes computable."""
    rows = _fetch_financials_asof(sess, bare, quarter_end, lookback_rows=8)
    if not rows:
        return None
    annuals = _annual_like_series(rows)

    # Quarter-anchor revenue: latest row with revenue, as-of quarter_end.
    quarter_revenue = None
    for r in rows:
        v = _safe_float(r.get("revenue"))
        if v is not None:
            quarter_revenue = v
            break

    quality = _compute_quality_axis(annuals)
    growth = _compute_growth_axis(annuals)
    moat = _compute_moat_axis(annuals, current_moat_grade)
    safety = _compute_safety_axis(annuals)

    price_at_q = _fetch_price_at_quarter(sess, ticker_nse, quarter_end)
    value, mos_pct = _compute_value_axis(
        quarter_revenue, current_revenue, current_fair_value, price_at_q
    )

    # Pulse: only the most recent quarter gets today's real pulse. Past
    # quarters honestly return None — we don't fabricate.
    pulse: Optional[float] = None
    if is_current_quarter:
        try:
            hx = hex_service.compute_hex_safe(ticker_nse)
            p = ((hx or {}).get("axes") or {}).get("pulse") or {}
            pv = _safe_float(p.get("score"))
            if pv is not None and not p.get("data_limited"):
                pulse = round(pv, 2)
        except Exception:
            pulse = None

    axes = {
        "value": value,
        "quality": quality,
        "growth": growth,
        "moat": moat,
        "safety": safety,
        "pulse": pulse,
    }

    # Require at least 4 of 6 axes
    present = sum(1 for v in axes.values() if v is not None)
    if present < 4:
        return None

    overall = _weighted_overall(axes)
    refraction = _refraction(list(axes.values()))
    verdict = _verdict_band_from_mos(mos_pct)

    return {
        "quarter_end": quarter_end,
        "axes": axes,
        "overall": overall,
        "refraction_index": refraction,
        "verdict_band": verdict,
    }


def _upsert_snapshot(sess, ticker_nse: str, snap: dict) -> None:
    axes = snap["axes"]
    try:
        sess.execute(
            text(
                """
                INSERT INTO hex_history (
                  ticker, quarter_end,
                  value_score, quality_score, growth_score,
                  moat_score, safety_score, pulse_score,
                  overall, refraction_index, verdict_band, computed_at
                ) VALUES (
                  :ticker, :quarter_end,
                  :value, :quality, :growth,
                  :moat, :safety, :pulse,
                  :overall, :refraction, :verdict, now()
                )
                ON CONFLICT (ticker, quarter_end) DO UPDATE SET
                  value_score      = EXCLUDED.value_score,
                  quality_score    = EXCLUDED.quality_score,
                  growth_score     = EXCLUDED.growth_score,
                  moat_score       = EXCLUDED.moat_score,
                  safety_score     = EXCLUDED.safety_score,
                  pulse_score      = EXCLUDED.pulse_score,
                  overall          = EXCLUDED.overall,
                  refraction_index = EXCLUDED.refraction_index,
                  verdict_band     = EXCLUDED.verdict_band,
                  computed_at      = now()
                """
            ),
            {
                "ticker": ticker_nse,
                "quarter_end": snap["quarter_end"],
                "value": axes.get("value"),
                "quality": axes.get("quality"),
                "growth": axes.get("growth"),
                "moat": axes.get("moat"),
                "safety": axes.get("safety"),
                "pulse": axes.get("pulse"),
                "overall": snap.get("overall"),
                "refraction": snap.get("refraction_index"),
                "verdict": snap.get("verdict_band"),
            },
        )
    except Exception as exc:
        logger.warning("hex_history: upsert failed for %s @ %s: %s",
                       ticker_nse, snap.get("quarter_end"), exc)
        try:
            sess.rollback()
        except Exception:
            pass


def _row_to_snapshot(row) -> dict:
    def _f(x):
        return _safe_float(x)
    qe = row[1]
    if isinstance(qe, datetime):
        qe = qe.date()
    return {
        "quarter_end": qe.isoformat() if hasattr(qe, "isoformat") else str(qe),
        "axes": {
            "value":   _f(row[2]),
            "quality": _f(row[3]),
            "growth":  _f(row[4]),
            "moat":    _f(row[5]),
            "safety":  _f(row[6]),
            "pulse":   _f(row[7]),
        },
        "overall":          _f(row[8]),
        "refraction_index": _f(row[9]),
        "verdict_band":     row[10] or "fair",
    }


# ── Public API ────────────────────────────────────────────────────
def get_hex_history(ticker: str, quarters: int = 12) -> list[dict]:
    """Return last N quarters of hex snapshots for this ticker, oldest first.

    Checks hex_history table first; rows older than their quarter are
    considered immutable and served from DB. If a tail of recent quarters
    is missing, falls back to on-the-fly compute for up to 4 quarters
    (more is too slow for an API call) then returns what we have.

    Never raises: returns [] on failure.
    """
    try:
        ticker_nse = _normalize_ticker(ticker) or ticker
    except Exception:
        ticker_nse = ticker
    bare = ticker_nse.replace(".NS", "").replace(".BO", "")

    quarters = max(2, min(20, int(quarters)))
    want = _recent_quarters(quarters)
    want_set = {q for q in want}

    sess = _get_session()
    if sess is None:
        return []
    try:
        try:
            rows = sess.execute(
                text(
                    """
                    SELECT ticker, quarter_end,
                           value_score, quality_score, growth_score,
                           moat_score, safety_score, pulse_score,
                           overall, refraction_index, verdict_band
                    FROM hex_history
                    WHERE ticker = :t
                      AND quarter_end >= :min_q
                    ORDER BY quarter_end ASC
                    """
                ),
                {"t": ticker_nse, "min_q": want[0]},
            ).fetchall()
        except Exception as exc:
            logger.debug("hex_history: read failed for %s: %s", ticker_nse, exc)
            rows = []

        by_q: dict[date, dict] = {}
        for r in rows:
            qe = r[1]
            if isinstance(qe, datetime):
                qe = qe.date()
            if qe in want_set:
                by_q[qe] = _row_to_snapshot(r)

        # Find missing quarters
        missing = [q for q in want if q not in by_q]
        if missing:
            # Only compute up to 4 on-the-fly to stay inside the API budget
            to_compute = missing[-4:] if len(missing) > 4 else missing
            current_fv, current_rev = _fetch_current_fv_and_revenue(
                sess, ticker_nse, bare
            )
            current_moat = _fetch_current_moat_grade(sess, ticker_nse)
            latest_q = want[-1]
            for q in to_compute:
                try:
                    snap = _compute_snapshot(
                        sess, ticker_nse, bare, q,
                        is_current_quarter=(q == latest_q),
                        current_fair_value=current_fv,
                        current_revenue=current_rev,
                        current_moat_grade=current_moat,
                    )
                except Exception as exc:
                    logger.debug("hex_history: compute failed %s @ %s: %s",
                                 ticker_nse, q, exc)
                    snap = None
                if snap is not None:
                    by_q[q] = {
                        "quarter_end": q.isoformat(),
                        "axes": snap["axes"],
                        "overall": snap["overall"],
                        "refraction_index": snap["refraction_index"],
                        "verdict_band": snap["verdict_band"],
                    }
                    try:
                        _upsert_snapshot(sess, ticker_nse, snap)
                    except Exception:
                        pass
            try:
                sess.commit()
            except Exception:
                try:
                    sess.rollback()
                except Exception:
                    pass

        out = []
        for q in want:
            snap = by_q.get(q)
            if snap is not None:
                out.append(snap)
        return out
    finally:
        _safe_close(sess)


def compute_and_store_all_history(ticker: str, quarters: int = 12) -> int:
    """Full 12-quarter compute + UPSERT. Used by the backfill script.

    Returns number of quarters successfully stored. Never raises."""
    try:
        ticker_nse = _normalize_ticker(ticker) or ticker
    except Exception:
        ticker_nse = ticker
    bare = ticker_nse.replace(".NS", "").replace(".BO", "")

    sess = _get_session()
    if sess is None:
        return 0
    stored = 0
    try:
        current_fv, current_rev = _fetch_current_fv_and_revenue(
            sess, ticker_nse, bare
        )
        current_moat = _fetch_current_moat_grade(sess, ticker_nse)

        want = _recent_quarters(quarters)
        latest_q = want[-1]
        for q in want:
            try:
                snap = _compute_snapshot(
                    sess, ticker_nse, bare, q,
                    is_current_quarter=(q == latest_q),
                    current_fair_value=current_fv,
                    current_revenue=current_rev,
                    current_moat_grade=current_moat,
                )
            except Exception as exc:
                logger.debug("hex_history: backfill compute failed %s @ %s: %s",
                             ticker_nse, q, exc)
                snap = None
            if snap is None:
                continue
            try:
                _upsert_snapshot(sess, ticker_nse, snap)
                stored += 1
            except Exception:
                pass
        try:
            sess.commit()
        except Exception:
            try:
                sess.rollback()
            except Exception:
                pass
        return stored
    finally:
        _safe_close(sess)


__all__ = [
    "get_hex_history",
    "compute_and_store_all_history",
    "DISCLAIMER",
]
