# backend/services/hex_service.py
# ═══════════════════════════════════════════════════════════════
# The YieldIQ Hex — 6-axis hexagonal radar score (sector-adaptive).
#
# Six axes, each scored 0..10:
#   1. value    — margin of safety + P/E vs history (or P/BV for banks,
#                 revenue multiple for IT)
#   2. quality  — Piotroski + ROCE + operating margin stability
#   3. growth   — 3y revenue / EPS CAGR
#   4. moat     — moat grade + brand/margin stability proxies
#   5. safety   — D/E inverse + interest coverage + Altman Z (or CAR
#                 proxy for banks)
#   6. pulse    — insider + promoter + estimate revisions (Agent D
#                 populates `hex_pulse_inputs`; we fall back to a
#                 yfinance recommendations signal or a neutral 5.0)
#
# Output is schema-tolerant: any axis we can't compute returns 5.0
# with `data_limited: true`. No axis ever returns NaN.
#
# SEBI compliance: no "buy/sell/recommend" language in output or
# comments. The returned payload always carries a `disclaimer` field.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import json
import logging
import math
import statistics
import time
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import text

logger = logging.getLogger("yieldiq.hex")


# ── Sector ticker groups (mirrors screener/sector_relative.py) ─
_BANK_TICKERS = {
    "HDFCBANK", "ICICIBANK", "AXISBANK", "KOTAKBANK", "SBIN",
    "INDUSINDBK", "BANDHANBNK", "FEDERALBNK", "BANKBARODA", "PNB",
    "CANBK", "IDFCFIRSTB", "RBLBANK", "YESBANK",
}
_NBFC_TICKERS = {
    "BAJFINANCE", "BAJAJFINSV", "CHOLAFIN", "MUTHOOTFIN", "SHRIRAMFIN",
    "LICHSGFIN", "LICHOUSFIN", "MANAPPURAM", "M&MFIN", "POONAWALLA",
    "AAVAS", "HOMEFIRST",
}
_IT_TICKERS = {
    "TCS", "INFY", "WIPRO", "HCLTECH", "TECHM", "MPHASIS", "HEXAWARE",
    "LTIM", "LTIMINDTR", "PERSISTENT", "COFORGE", "KPITTECH", "TATAELXSI",
    "CYIENT", "ZENSAR", "MASTEK", "NIIT", "OFSS",
}


# ── Constants ────────────────────────────────────────────────────
DISCLAIMER = (
    "Model estimate. Fundamental + Market Profile. Not investment advice."
)

AXIS_WEIGHTS = {
    "value": 0.20,
    "quality": 0.20,
    "growth": 0.20,
    "moat": 0.15,
    "safety": 0.15,
    "pulse": 0.10,
}


# ── DB session helper ────────────────────────────────────────────
def _get_session():
    """Lazily acquire a pipeline SQLAlchemy session, or None."""
    try:
        from data_pipeline.db import Session  # type: ignore
    except Exception as exc:
        logger.warning("hex: pipeline db import failed: %s", exc)
        return None
    if Session is None:
        return None
    try:
        return Session()
    except Exception as exc:
        logger.warning("hex: Session() failed: %s", exc)
        return None


def _safe_close(sess) -> None:
    if sess is None:
        return
    try:
        sess.close()
    except Exception:
        pass


# ── Idempotent bootstrap of the pulse inputs table ───────────────
_PULSE_TABLE_CHECKED = False


def _ensure_pulse_table() -> None:
    """Create hex_pulse_inputs if missing. Runs at most once per process."""
    global _PULSE_TABLE_CHECKED
    if _PULSE_TABLE_CHECKED:
        return
    sess = _get_session()
    if sess is None:
        _PULSE_TABLE_CHECKED = True  # nothing we can do
        return
    try:
        sess.execute(text(
            """
            CREATE TABLE IF NOT EXISTS hex_pulse_inputs (
                ticker                  TEXT PRIMARY KEY,
                promoter_delta_qoq      NUMERIC,
                insider_net_30d         NUMERIC,
                estimate_revision_30d   NUMERIC,
                pledged_pct_delta       NUMERIC,
                computed_at             TIMESTAMPTZ DEFAULT now()
            )
            """
        ))
        sess.commit()
        _PULSE_TABLE_CHECKED = True
    except Exception as exc:
        logger.warning("hex: ensure_pulse_table failed: %s", exc)
        try:
            sess.rollback()
        except Exception:
            pass
    finally:
        _safe_close(sess)


# Fire once at import; harmless on cold starts where DB is missing.
try:
    _ensure_pulse_table()
except Exception:
    pass


# ── Small numeric helpers ────────────────────────────────────────
def _clamp(x: float, lo: float = 0.0, hi: float = 10.0) -> float:
    try:
        x = float(x)
    except (TypeError, ValueError):
        return 5.0
    if math.isnan(x) or math.isinf(x):
        return 5.0
    return max(lo, min(hi, x))


def _label_general(score: float) -> str:
    if score >= 7.5:
        return "Strong"
    if score >= 4.5:
        return "Moderate"
    return "Weak"


def _label_pulse(score: float) -> str:
    if score >= 6.5:
        return "Positive"
    if score >= 3.5:
        return "Neutral"
    return "Negative"


def _axis(score: float, why: str, data_limited: bool = False,
          labeler=_label_general) -> dict:
    s = round(_clamp(score), 2)
    return {
        "score": s,
        "label": labeler(s),
        "why": why,
        "data_limited": bool(data_limited),
    }


def _neutral_axis(why: str = "Insufficient data", labeler=_label_general) -> dict:
    return _axis(5.0, why, data_limited=True, labeler=labeler)


# ── Sector classification ────────────────────────────────────────
def _classify_sector(ticker_bare: str, sector_str: Optional[str]) -> str:
    """Return 'bank', 'it', or 'general'."""
    t = (ticker_bare or "").upper().replace(".NS", "").replace(".BO", "")
    if t in _BANK_TICKERS or t in _NBFC_TICKERS:
        return "bank"
    if t in _IT_TICKERS:
        return "it"
    s = (sector_str or "").lower()
    if any(k in s for k in ("bank", "financial services", "nbfc", "lending")):
        return "bank"
    if any(k in s for k in (
        "information technology", "technology", "software", "it services"
    )):
        return "it"
    return "general"


# ── Data fetch ───────────────────────────────────────────────────
def _normalize_ticker(ticker: str) -> str:
    t = (ticker or "").upper().strip()
    if not t:
        return t
    if not t.endswith(".NS") and not t.endswith(".BO"):
        t = f"{t}.NS"
    return t


def _fetch_core_data(ticker: str) -> dict:
    """
    Pull all data needed for axis computation in one round-trip.
    Returns a dict; fields missing when the DB is unavailable.
    """
    out: dict = {
        "ticker": ticker,
        "analysis": None,      # analysis_cache.payload
        "metrics": None,       # market_metrics row
        "financials": [],      # list of ttm/annual financials rows
        "sector": None,        # stocks.sector
    }
    sess = _get_session()
    if sess is None:
        return out
    try:
        bare = ticker.replace(".NS", "").replace(".BO", "")

        # 1. analysis_cache — full AnalysisResponse JSON
        try:
            row = sess.execute(
                text("SELECT payload FROM analysis_cache WHERE ticker = :t"),
                {"t": ticker},
            ).fetchone()
            if row and row[0]:
                payload = row[0]
                if isinstance(payload, (bytes, bytearray)):
                    payload = payload.decode("utf-8")
                if isinstance(payload, str):
                    try:
                        payload = json.loads(payload)
                    except Exception:
                        payload = None
                if isinstance(payload, dict):
                    out["analysis"] = payload
        except Exception as exc:
            logger.debug("hex: analysis_cache fetch failed for %s: %s", ticker, exc)

        # 2. market_metrics
        try:
            row = sess.execute(
                text(
                    "SELECT pe_ratio, pb_ratio, ev_ebitda, market_cap_cr "
                    "FROM market_metrics WHERE ticker = :t"
                ),
                {"t": ticker},
            ).fetchone()
            if row:
                out["metrics"] = {
                    "pe_ratio": row[0],
                    "pb_ratio": row[1],
                    "ev_ebitda": row[2],
                    "market_cap_cr": row[3],
                }
        except Exception as exc:
            logger.debug("hex: market_metrics fetch failed for %s: %s", ticker, exc)

        # 3. financials — last ~5y of annuals
        try:
            rows = sess.execute(
                text(
                    "SELECT period_end, revenue, fcf, op_margin, eps, "
                    "debt_to_equity, interest_coverage "
                    "FROM financials "
                    "WHERE ticker = :t AND period_type = 'annual' "
                    "ORDER BY period_end DESC LIMIT 6"
                ),
                {"t": bare},
            ).fetchall()
            out["financials"] = [
                {
                    "period_end": r[0],
                    "revenue": r[1],
                    "fcf": r[2],
                    "op_margin": r[3],
                    "eps": r[4],
                    "de": r[5],
                    "int_cov": r[6],
                }
                for r in rows
            ]
        except Exception as exc:
            # Schema may differ; fall back to SELECT * style introspection quietly
            logger.debug("hex: financials fetch failed for %s: %s", ticker, exc)

        # 4. stocks.sector
        try:
            row = sess.execute(
                text("SELECT sector FROM stocks WHERE ticker = :t LIMIT 1"),
                {"t": bare},
            ).fetchone()
            if row:
                out["sector"] = row[0]
        except Exception as exc:
            logger.debug("hex: stocks.sector fetch failed for %s: %s", ticker, exc)

    finally:
        _safe_close(sess)
    return out


def _fetch_pulse_inputs(ticker: str) -> Optional[dict]:
    sess = _get_session()
    if sess is None:
        return None
    try:
        row = sess.execute(
            text(
                "SELECT promoter_delta_qoq, insider_net_30d, "
                "estimate_revision_30d, pledged_pct_delta, computed_at "
                "FROM hex_pulse_inputs WHERE ticker = :t"
            ),
            {"t": ticker},
        ).fetchone()
        if not row:
            return None
        return {
            "promoter_delta_qoq": row[0],
            "insider_net_30d": row[1],
            "estimate_revision_30d": row[2],
            "pledged_pct_delta": row[3],
            "computed_at": row[4],
        }
    except Exception as exc:
        logger.debug("hex: pulse_inputs fetch failed for %s: %s", ticker, exc)
        return None
    finally:
        _safe_close(sess)


# ── Extraction helpers from analysis payload ─────────────────────
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


# ── Axis computations (general case) ────────────────────────────
def _axis_value_general(data: dict) -> dict:
    analysis = data.get("analysis") or {}
    metrics = data.get("metrics") or {}
    fv = _dig(analysis, "valuation", "fair_value")
    price = _dig(analysis, "valuation", "current_price")
    mos_pct = _dig(analysis, "valuation", "margin_of_safety")

    if mos_pct is None and fv and price:
        try:
            mos_pct = (float(fv) - float(price)) / float(fv) * 100.0
        except Exception:
            mos_pct = None

    pe = metrics.get("pe_ratio")

    if mos_pct is None and pe is None:
        return _neutral_axis("No valuation data available")

    # Anchor: MoS of 0 -> 5; each +10% MoS bumps ~1.5 points.
    score = 5.0
    reasons: list[str] = []
    if mos_pct is not None:
        try:
            score += 0.15 * float(mos_pct)
            reasons.append(f"MoS {float(mos_pct):.0f}%")
        except Exception:
            pass
    if pe is not None:
        try:
            pe_f = float(pe)
            # Below 15 cheap (+1.0), above 40 rich (-1.0); midpoint 22.
            pe_adj = (22.0 - pe_f) * 0.05
            pe_adj = max(-2.0, min(2.0, pe_adj))
            score += pe_adj
            reasons.append(f"P/E {pe_f:.1f}")
        except Exception:
            pass

    why = ", ".join(reasons) if reasons else "Partial valuation data"
    return _axis(score, why, data_limited=(mos_pct is None or pe is None))


def _axis_value_bank(data: dict) -> dict:
    analysis = data.get("analysis") or {}
    metrics = data.get("metrics") or {}
    pb = metrics.get("pb_ratio")
    mos_pct = _dig(analysis, "valuation", "margin_of_safety")
    if pb is None and mos_pct is None:
        return _neutral_axis("No P/BV or MoS available")
    score = 5.0
    reasons: list[str] = []
    if pb is not None:
        try:
            pb_f = float(pb)
            # Banking peer band centre ~2.5x; <1.5 cheap (+2), >4 rich (-2).
            adj = (2.5 - pb_f) * 1.5
            adj = max(-2.5, min(2.5, adj))
            score += adj
            reasons.append(f"P/BV {pb_f:.2f}")
        except Exception:
            pass
    if mos_pct is not None:
        try:
            score += 0.10 * float(mos_pct)
            reasons.append(f"MoS {float(mos_pct):.0f}%")
        except Exception:
            pass
    return _axis(
        score,
        ", ".join(reasons) if reasons else "Bank valuation partial",
        data_limited=(pb is None),
    )


def _axis_value_it(data: dict) -> dict:
    analysis = data.get("analysis") or {}
    metrics = data.get("metrics") or {}
    financials = data.get("financials") or []
    rev = None
    if financials:
        rev = financials[0].get("revenue")
    mcap_cr = metrics.get("market_cap_cr")
    if not (rev and mcap_cr):
        # Fall back to general P/E logic
        return _axis_value_general(data)
    try:
        # Convert cr to same unit as revenue (revenue typically in abs rupees
        # or cr depending on source). Use ratio rather than absolute.
        rev_multiple = float(mcap_cr) / max(1.0, float(rev) / 1e7)
        # IT cohort median EV/Rev ~4-5x; anchor 5.0 mid.
        score = 5.0 + (5.0 - rev_multiple) * 0.6
        return _axis(
            score,
            f"Revenue multiple {rev_multiple:.2f}x vs cohort ~5x",
        )
    except Exception:
        return _axis_value_general(data)


def _axis_quality(data: dict, sector: str) -> dict:
    analysis = data.get("analysis") or {}
    q = analysis.get("quality") or {}
    piotroski = q.get("piotroski_score") or q.get("piotroski")
    roce = q.get("roce")
    roe = q.get("roe")

    # Operating margin stability from annual financials
    fins = data.get("financials") or []
    op_margins = [f.get("op_margin") for f in fins if f.get("op_margin") is not None]
    margin_stability = None
    if len(op_margins) >= 3:
        try:
            stdev = statistics.pstdev([float(x) for x in op_margins])
            margin_stability = stdev
        except Exception:
            margin_stability = None

    if piotroski is None and roce is None and roe is None:
        return _neutral_axis("No quality metrics available")

    score = 5.0
    reasons: list[str] = []

    if piotroski is not None:
        try:
            p = float(piotroski)
            # Piotroski 0-9 -> contribute (p-4.5)*0.6 => span ~±2.7
            score += (p - 4.5) * 0.6
            reasons.append(f"Piotroski {int(p)}/9")
        except Exception:
            pass

    primary = roce if roce is not None else roe
    if primary is not None:
        try:
            v = float(primary)
            # ROCE/ROE anchor 15%; below 8 weak, above 22 strong.
            score += (v - 15.0) * 0.12
            label_name = "ROCE" if roce is not None else "ROE"
            reasons.append(f"{label_name} {v:.1f}%")
        except Exception:
            pass

    if margin_stability is not None and sector != "bank":
        # Lower stdev = more stable = small positive
        try:
            score += max(-1.0, min(1.0, (5.0 - margin_stability) * 0.1))
        except Exception:
            pass

    return _axis(
        score,
        ", ".join(reasons) if reasons else "Partial quality data",
        data_limited=(piotroski is None or primary is None),
    )


def _axis_growth(data: dict) -> dict:
    analysis = data.get("analysis") or {}
    q = analysis.get("quality") or {}
    rev_cagr = q.get("revenue_cagr_3y")
    if rev_cagr is None:
        rev_cagr = q.get("revenue_cagr_5y")

    # EPS CAGR from financials
    fins = data.get("financials") or []
    eps_series = [f.get("eps") for f in fins if f.get("eps") is not None]
    eps_cagr = None
    if len(eps_series) >= 3:
        try:
            # financials are DESC — oldest last
            old = float(eps_series[-1])
            new = float(eps_series[0])
            years = len(eps_series) - 1
            if old > 0 and new > 0 and years > 0:
                eps_cagr = ((new / old) ** (1.0 / years) - 1.0) * 100.0
        except Exception:
            eps_cagr = None

    if rev_cagr is None and eps_cagr is None:
        return _neutral_axis("No growth history available")

    score = 5.0
    reasons: list[str] = []
    if rev_cagr is not None:
        try:
            r = float(rev_cagr)
            # Anchor 10% -> 5.5; 20% -> 6.5
            score += r * 0.10
            reasons.append(f"Rev CAGR {r:.1f}%")
        except Exception:
            pass
    if eps_cagr is not None:
        try:
            score += eps_cagr * 0.08
            reasons.append(f"EPS CAGR {eps_cagr:.1f}%")
        except Exception:
            pass

    return _axis(
        score,
        ", ".join(reasons) if reasons else "Partial growth data",
        data_limited=(rev_cagr is None or eps_cagr is None),
    )


def _axis_moat(data: dict, sector: str) -> dict:
    analysis = data.get("analysis") or {}
    q = analysis.get("quality") or {}
    moat_grade = q.get("moat") or _dig(analysis, "moat", "grade")

    score = 5.0
    reasons: list[str] = []
    if isinstance(moat_grade, str):
        g = moat_grade.lower()
        if "wide" in g:
            score += 3.0
            reasons.append("Wide moat")
        elif "narrow" in g:
            score += 1.5
            reasons.append("Narrow moat")
        elif "none" in g or g == "no moat":
            score -= 1.5
            reasons.append("No moat")

    # Margin stability proxy (IT)
    fins = data.get("financials") or []
    op_margins = [f.get("op_margin") for f in fins if f.get("op_margin") is not None]
    if len(op_margins) >= 3:
        try:
            stdev = statistics.pstdev([float(x) for x in op_margins])
            # Very stable (<3 stdev) -> bonus
            score += max(-0.5, min(1.0, (5.0 - stdev) * 0.15))
            if stdev < 3.0:
                reasons.append("Stable margins")
        except Exception:
            pass

    if not reasons:
        return _neutral_axis("No moat classification available")
    return _axis(score, ", ".join(reasons))


def _axis_safety(data: dict, sector: str) -> dict:
    analysis = data.get("analysis") or {}
    q = analysis.get("quality") or {}
    de = q.get("de_ratio") or q.get("debt_to_equity")
    int_cov = q.get("interest_coverage")
    altman = q.get("altman_z")

    if sector == "bank":
        # CAR/book proxy — use pb_ratio inverse + quality.grade if present
        metrics = data.get("metrics") or {}
        pb = metrics.get("pb_ratio")
        if pb is None:
            return _neutral_axis("No CAR proxy data")
        try:
            pb_f = float(pb)
            # Higher P/BV often reflects franchise strength for quality banks
            score = 5.0 + max(-2.0, min(2.5, (pb_f - 1.5) * 0.8))
            return _axis(score, f"Book-value franchise proxy P/BV {pb_f:.2f}")
        except Exception:
            return _neutral_axis("Bank safety proxy failed")

    if de is None and int_cov is None and altman is None:
        return _neutral_axis("No leverage / coverage data")

    score = 5.0
    reasons: list[str] = []
    if de is not None:
        try:
            de_f = float(de)
            # D/E 0 -> +2, 1 -> 0, 2 -> -2
            score += max(-3.0, min(2.5, (1.0 - de_f) * 2.0))
            reasons.append(f"D/E {de_f:.2f}")
        except Exception:
            pass
    if int_cov is not None:
        try:
            ic = float(int_cov)
            # >8x safe (+1.5), 2-4 weak (-1)
            score += max(-2.0, min(2.0, (ic - 4.0) * 0.25))
            reasons.append(f"Int cov {ic:.1f}x")
        except Exception:
            pass
    if altman is not None:
        try:
            z = float(altman)
            # Altman Z: >3 safe, <1.8 distress
            score += max(-2.0, min(2.0, (z - 2.4) * 0.8))
            reasons.append(f"Altman Z {z:.2f}")
        except Exception:
            pass

    return _axis(
        score,
        ", ".join(reasons) if reasons else "Partial safety data",
        data_limited=(de is None or int_cov is None),
    )


def _axis_pulse(ticker: str) -> dict:
    row = _fetch_pulse_inputs(ticker)
    if row:
        # Combine signals into -10..+10 then normalize to 0..10.
        raw = 0.0
        reasons: list[str] = []
        er = row.get("estimate_revision_30d")
        if er is not None:
            try:
                raw += max(-5.0, min(5.0, float(er) * 5.0))
                reasons.append(f"Est rev {float(er):+.2f}")
            except Exception:
                pass
        ins = row.get("insider_net_30d")
        if ins is not None:
            try:
                raw += max(-3.0, min(3.0, float(ins)))
                reasons.append("Insider signal")
            except Exception:
                pass
        prom = row.get("promoter_delta_qoq")
        if prom is not None:
            try:
                raw += max(-2.0, min(2.0, float(prom) * 2.0))
                reasons.append(f"Promoter Δ {float(prom):+.2f}")
            except Exception:
                pass
        pledge = row.get("pledged_pct_delta")
        if pledge is not None:
            try:
                # A rise in pledged % is a negative signal.
                raw -= max(-2.0, min(2.0, float(pledge)))
            except Exception:
                pass
        score = 5.0 + raw * 0.5
        return _axis(
            score,
            ", ".join(reasons) if reasons else "Pulse inputs present",
            labeler=_label_pulse,
        )

    # Fallback: yfinance analyst recommendation trend
    try:
        import yfinance as yf  # type: ignore
        t = yf.Ticker(ticker)
        summary = None
        try:
            summary = t.recommendations_summary  # newer yfinance
        except Exception:
            summary = None
        if summary is None or (hasattr(summary, "empty") and summary.empty):
            try:
                summary = t.get_recommendations_summary()
            except Exception:
                summary = None

        if summary is not None and hasattr(summary, "iloc") and len(summary) > 0:
            # Expect columns: strongBuy, buy, hold, sell, strongSell
            row = summary.iloc[0]
            sb = float(row.get("strongBuy", 0) or 0)
            b = float(row.get("buy", 0) or 0)
            h = float(row.get("hold", 0) or 0)
            s = float(row.get("sell", 0) or 0)
            ss = float(row.get("strongSell", 0) or 0)
            total = sb + b + h + s + ss
            if total > 0:
                # Weighted positive share (-1..+1), then to 0..10
                net = (2 * sb + b - s - 2 * ss) / total
                score = 5.0 + net * 4.0
                return _axis(
                    score,
                    "Analyst revision trend (fallback)",
                    labeler=_label_pulse,
                )
    except Exception as exc:
        logger.debug("hex: yfinance pulse fallback failed for %s: %s", ticker, exc)

    return _axis(
        5.0,
        "Pulse data unavailable; neutral placeholder",
        data_limited=True,
        labeler=_label_pulse,
    )


# ── Sector medians (rolling) ─────────────────────────────────────
_SECTOR_MEDIAN_CACHE: dict[str, tuple[float, dict]] = {}
_SECTOR_MEDIAN_TTL = 900  # 15 min


def _sector_medians(category: str) -> dict:
    """
    Compute axis-wise medians over the last ~500 stored hex results for
    the given sector category. Results are cached in-process for 15 min.
    Returns neutral 5.0 per axis if the hex_results table is missing
    (Agent D populates it).
    """
    now = time.time()
    hit = _SECTOR_MEDIAN_CACHE.get(category)
    if hit and now - hit[0] < _SECTOR_MEDIAN_TTL:
        return hit[1]

    default = {k: 5.0 for k in AXIS_WEIGHTS.keys()}
    sess = _get_session()
    if sess is None:
        _SECTOR_MEDIAN_CACHE[category] = (now, default)
        return default
    try:
        # Optional table populated by future agents. We read defensively;
        # if it does not exist yet, fall back to neutral.
        rows = sess.execute(
            text(
                """
                SELECT axes
                FROM hex_results
                WHERE sector_category = :cat
                ORDER BY computed_at DESC
                LIMIT 500
                """
            ),
            {"cat": category},
        ).fetchall()
    except Exception:
        rows = []
    finally:
        _safe_close(sess)

    bucket: dict[str, list[float]] = {k: [] for k in AXIS_WEIGHTS.keys()}
    for r in rows:
        axes = r[0]
        if isinstance(axes, (bytes, bytearray)):
            try:
                axes = axes.decode("utf-8")
            except Exception:
                continue
        if isinstance(axes, str):
            try:
                axes = json.loads(axes)
            except Exception:
                continue
        if not isinstance(axes, dict):
            continue
        for k in AXIS_WEIGHTS.keys():
            v = axes.get(k)
            if isinstance(v, dict):
                v = v.get("score")
            try:
                if v is not None:
                    bucket[k].append(float(v))
            except Exception:
                pass

    result = {
        k: round(statistics.median(v), 2) if v else 5.0
        for k, v in bucket.items()
    }
    _SECTOR_MEDIAN_CACHE[category] = (now, result)
    return result


# ── Public API ───────────────────────────────────────────────────
def compute_hex(ticker: str) -> dict:
    """
    Compute the 6-axis Hex score for a ticker. Always returns a valid
    payload; missing data becomes `data_limited: true` on the affected
    axis. Never raises.
    """
    t = _normalize_ticker(ticker)
    if not t:
        return {
            "ticker": ticker,
            "error": "invalid ticker",
            "data_limited": True,
            "axes": {k: _neutral_axis("invalid ticker") for k in AXIS_WEIGHTS},
            "overall": 5.0,
            "sector_category": "general",
            "sector_medians": {k: 5.0 for k in AXIS_WEIGHTS},
            "computed_at": datetime.now(timezone.utc).isoformat(),
            "disclaimer": DISCLAIMER,
        }

    try:
        data = _fetch_core_data(t)
    except Exception as exc:
        logger.warning("hex: fetch_core_data failed for %s: %s", t, exc)
        data = {"ticker": t}

    sector = _classify_sector(t, data.get("sector"))

    # Axis dispatch
    try:
        if sector == "bank":
            value_axis = _axis_value_bank(data)
        elif sector == "it":
            value_axis = _axis_value_it(data)
        else:
            value_axis = _axis_value_general(data)
    except Exception as exc:
        logger.warning("hex: value axis failed for %s: %s", t, exc)
        value_axis = _neutral_axis("value axis error")

    try:
        quality_axis = _axis_quality(data, sector)
    except Exception:
        quality_axis = _neutral_axis("quality axis error")
    try:
        growth_axis = _axis_growth(data)
    except Exception:
        growth_axis = _neutral_axis("growth axis error")
    try:
        moat_axis = _axis_moat(data, sector)
    except Exception:
        moat_axis = _neutral_axis("moat axis error")
    try:
        safety_axis = _axis_safety(data, sector)
    except Exception:
        safety_axis = _neutral_axis("safety axis error")
    try:
        pulse_axis = _axis_pulse(t)
    except Exception:
        pulse_axis = _neutral_axis("pulse axis error", labeler=_label_pulse)

    axes = {
        "value":   value_axis,
        "quality": quality_axis,
        "growth":  growth_axis,
        "moat":    moat_axis,
        "safety":  safety_axis,
        "pulse":   pulse_axis,
    }

    overall = sum(axes[k]["score"] * w for k, w in AXIS_WEIGHTS.items())
    overall = round(_clamp(overall), 2)

    return {
        "ticker": t,
        "sector_category": sector,
        "axes": axes,
        "overall": overall,
        "sector_medians": _sector_medians(sector),
        "computed_at": datetime.now(timezone.utc).isoformat(),
        "disclaimer": DISCLAIMER,
    }


def compute_hex_safe(ticker: str) -> dict:
    """
    Public wrapper that NEVER raises. On any unhandled exception, returns
    a neutral payload with data_limited=True so the router can always
    serve HTTP 200.
    """
    try:
        return compute_hex(ticker)
    except Exception as exc:
        logger.warning("hex: compute_hex_safe fallback for %s: %s", ticker, exc)
        return {
            "ticker": _normalize_ticker(ticker) or ticker,
            "sector_category": "general",
            "axes": {k: _neutral_axis("compute error") for k in AXIS_WEIGHTS},
            "overall": 5.0,
            "sector_medians": {k: 5.0 for k in AXIS_WEIGHTS},
            "computed_at": datetime.now(timezone.utc).isoformat(),
            "error": "compute_error",
            "data_limited": True,
            "disclaimer": DISCLAIMER,
        }


def compute_portfolio_hex(holdings: list[dict]) -> dict:
    """
    Aggregate portfolio Hex: weighted mean per axis across tickers.
    `holdings` is a list of {ticker, weight}. Weights are renormalized.
    """
    if not holdings:
        return {
            "axes": {k: _neutral_axis("empty portfolio") for k in AXIS_WEIGHTS},
            "overall": 5.0,
            "holdings": [],
            "disclaimer": DISCLAIMER,
            "computed_at": datetime.now(timezone.utc).isoformat(),
        }

    # Normalize weights
    total_w = sum(max(0.0, float(h.get("weight", 0) or 0)) for h in holdings)
    if total_w <= 0:
        total_w = float(len(holdings))
        weights = [1.0 / total_w for _ in holdings]
    else:
        weights = [
            max(0.0, float(h.get("weight", 0) or 0)) / total_w for h in holdings
        ]

    per_ticker = []
    agg: dict[str, float] = {k: 0.0 for k in AXIS_WEIGHTS}
    any_limited = {k: False for k in AXIS_WEIGHTS}

    for h, w in zip(holdings, weights):
        hx = compute_hex_safe(h.get("ticker", ""))
        per_ticker.append({"ticker": hx.get("ticker"), "weight": round(w, 4),
                           "overall": hx.get("overall")})
        for k in AXIS_WEIGHTS:
            ax = hx["axes"].get(k, {})
            agg[k] += float(ax.get("score", 5.0)) * w
            if ax.get("data_limited"):
                any_limited[k] = True

    axes_out = {}
    for k, v in agg.items():
        labeler = _label_pulse if k == "pulse" else _label_general
        axes_out[k] = _axis(
            v, f"Weighted across {len(holdings)} holdings",
            data_limited=any_limited[k], labeler=labeler,
        )

    overall = round(
        _clamp(sum(axes_out[k]["score"] * w for k, w in AXIS_WEIGHTS.items())),
        2,
    )

    return {
        "axes": axes_out,
        "overall": overall,
        "holdings": per_ticker,
        "computed_at": datetime.now(timezone.utc).isoformat(),
        "disclaimer": DISCLAIMER,
    }


__all__ = [
    "compute_hex",
    "compute_hex_safe",
    "compute_portfolio_hex",
    "DISCLAIMER",
    "AXIS_WEIGHTS",
]
