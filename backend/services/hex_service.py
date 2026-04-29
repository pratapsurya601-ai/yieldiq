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

# Canonical axis weights live in the pure hex_axes module so the
# hex_history seeder can import them without pulling in this module's
# streamlit/pydantic chain. Re-exported here for back-compat with
# existing callers that do `from backend.services.hex_service import AXIS_WEIGHTS`.
from backend.services.analysis.hex_axes import AXIS_WEIGHTS  # noqa: E402, F401


# ── DB session helper ────────────────────────────────────────────
# Module-level flags so we log WHY the DB is unreachable exactly once per
# process instead of spamming the log on every per-holding hex compute.
# When a Portfolio Prism request fans out to 18 holdings, we DO NOT want
# 18 identical stacktraces — just one, loud, at WARNING, on first failure.
_SESSION_IMPORT_WARNED = False
_SESSION_NONE_WARNED = False
_SESSION_CONSTRUCT_WARNED = False


def _get_session():
    """Lazily acquire a pipeline SQLAlchemy session, or None."""
    global _SESSION_IMPORT_WARNED, _SESSION_NONE_WARNED, _SESSION_CONSTRUCT_WARNED
    try:
        from data_pipeline.db import Session  # type: ignore
    except Exception as exc:
        if not _SESSION_IMPORT_WARNED:
            logger.warning(
                "hex: data_pipeline.db import failed (%s: %s) — all per-ticker "
                "hex fetches will return empty data for this process",
                type(exc).__name__, exc,
            )
            _SESSION_IMPORT_WARNED = True
        return None
    if Session is None:
        if not _SESSION_NONE_WARNED:
            logger.warning(
                "hex: data_pipeline.db.Session is None — DATABASE_URL probably "
                "unset or engine init failed. Hex will run in data_limited mode."
            )
            _SESSION_NONE_WARNED = True
        return None
    try:
        return Session()
    except Exception as exc:
        if not _SESSION_CONSTRUCT_WARNED:
            logger.warning(
                "hex: Session() constructor failed (%s: %s) — hex will run "
                "in data_limited mode",
                type(exc).__name__, exc,
            )
            _SESSION_CONSTRUCT_WARNED = True
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
        "industry": None,      # stocks.industry (cohort disambiguator)
    }
    sess = _get_session()
    if sess is None:
        # _get_session() already logged the root cause once at WARNING.
        # We return an empty `out`; the caller will fall back to
        # _neutral_axis() on every axis and the UI renders "n/a".
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

        # 2. market_metrics — try canonical THEN bare (writers disagree
        # on suffix handling; HDFCBANK had rows under bare form only,
        # which starved the bank-branch moat axis of its scale signal).
        try:
            row = None
            for cand in (ticker, bare) if ticker != bare else (ticker,):
                # ORDER BY trade_date DESC LIMIT 1 - dual-listed tickers
                # (NSE+BSE) have two rows in market_metrics; pick the
                # freshest. See design note in backend/routers/screener.py.
                row = sess.execute(
                    text(
                        "SELECT pe_ratio, pb_ratio, ev_ebitda, market_cap_cr "
                        "FROM market_metrics WHERE ticker = :t "
                        "ORDER BY trade_date DESC LIMIT 1"
                    ),
                    {"t": cand},
                ).fetchone()
                if row:
                    break
            if row:
                out["metrics"] = {
                    "pe_ratio": row[0],
                    "pb_ratio": row[1],
                    "ev_ebitda": row[2],
                    "market_cap_cr": row[3],
                }
        except Exception as exc:
            logger.debug("hex: market_metrics fetch failed for %s: %s", ticker, exc)

        # 3. financials — last ~6y of annuals.
        # Column names MUST match data_pipeline.models.Financials:
        #   operating_margin (NOT op_margin), free_cash_flow (NOT fcf),
        #   eps_diluted (NOT eps). There is no `interest_coverage` column
        #   on this table — it lives on the analysis QualityOutput only.
        # The previous query used the short aliases and raised
        # `UndefinedColumn` for every ticker → the exception was
        # swallowed, out["financials"] stayed []. That neutralised the
        # op-margin-stability signal in _axis_moat and the revenue-CAGR
        # fallback in _axis_growth for ANY ticker whose cached
        # analysis_cache.payload lacked quality.moat /
        # quality.revenue_cagr_*y (the TCS symptom set
        # 2026-04-23).
        try:
            rows = sess.execute(
                text(
                    "SELECT period_end, revenue, free_cash_flow, "
                    "operating_margin, eps_diluted, debt_to_equity "
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
                }
                for r in rows
            ]
        except Exception as exc:
            # Log at INFO (not debug) so the next regression of this
            # class is visible in Railway logs without a log-level bump.
            logger.info("hex: financials fetch failed for %s: %s", ticker, exc)

        # 4. stocks.sector + stocks.industry
        # `industry` is needed by sector_percentile.compute_sector_cohort
        # to disambiguate banks from NBFCs/AMCs in the Financial
        # Services bucket — without it HDFCBANK ends up in the same
        # cohort as an asset manager.
        try:
            row = sess.execute(
                text("SELECT sector, industry FROM stocks WHERE ticker = :t LIMIT 1"),
                {"t": bare},
            ).fetchone()
            if row:
                out["sector"] = row[0]
                out["industry"] = row[1]
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
# Stage 2/3 (sector-percentile Value): every Value axis branch now
# delegates to `_axis_value_percentile`, which ranks the ticker's
# cohort metric (MoS for general, P/BV for bank, revenue multiple
# for IT) against its sector peers and maps the resulting percentile
# to a 0-10 score plus a band/label/why bundle. Old sigmoid-based
# scoring + NBFC anchor branch are removed; cohort context replaces
# the static anchors.
#
# Response shape per axis (additive over the legacy {score,label,why,
# data_limited} envelope; downstream consumers ignore unknown keys):
#   score              float | None  — 0..10 derived from percentile
#                                       (None when data_limited; the
#                                        UI renders "—")
#   percentile         int   | None  — 0..100 rank within cohort
#   band               str            — one of 6 band keys
#   label              str            — human-readable band label
#   why                str            — reason text incl. cohort context
#   data_limited       bool
#   sector_peers       int            — cohort size (post-filter)
#   sector_label       str            — canonical sector key (or "")
#   sector_median_mos  float | None
#   sector_median_pe   float | None
#   sector_median_pb   float | None


def _percentile_to_score(percentile: Optional[int]) -> Optional[float]:
    """Map cohort percentile to a 0..10 legacy `score`.

    Inverted: low percentile (cheapest in cohort) → high score; high
    percentile (richest) → low score. Returns None when percentile is
    None (data_limited) so callers can render "—" instead of fabricating
    a neutral 5.0 anchor.
    """
    if percentile is None:
        return None
    try:
        p = float(percentile)
    except (TypeError, ValueError):
        return None
    if p != p:
        return None
    p = max(0.0, min(100.0, p))
    return round(10.0 - (p / 10.0), 2)


def _median_or_none(values: list[float]) -> Optional[float]:
    clean = [float(v) for v in values if v is not None]
    if not clean:
        return None
    try:
        return round(statistics.median(clean), 4)
    except statistics.StatisticsError:
        return None


def _empty_value_axis(why: str, sector_label: str = "",
                      sector_peers: int = 0) -> dict:
    """data_limited Value axis envelope (score=None, no percentile)."""
    return {
        "score": None,
        "label": "Insufficient peer data",
        "why": why,
        "data_limited": True,
        "percentile": None,
        "band": "data_limited",
        "sector_peers": sector_peers,
        "sector_label": sector_label,
        "sector_median_mos": None,
        "sector_median_pe": None,
        "sector_median_pb": None,
    }


def _resolve_mos_pct(data: dict) -> Optional[float]:
    """Pull MoS% off the analysis payload, computing from FV/price if absent."""
    analysis = data.get("analysis") or {}
    mos_pct = _dig(analysis, "valuation", "margin_of_safety")
    if mos_pct is None:
        fv = _dig(analysis, "valuation", "fair_value")
        price = _dig(analysis, "valuation", "current_price")
        if fv and price:
            try:
                mos_pct = (float(fv) - float(price)) / float(price) * 100.0
            except Exception:
                mos_pct = None
    if mos_pct is None:
        return None
    try:
        v = float(mos_pct)
    except (TypeError, ValueError):
        return None
    return None if v != v else v


def _resolve_revenue_multiple(data: dict) -> Optional[float]:
    """Compute MCAP / revenue (crores) for IT cohort comparison."""
    metrics = data.get("metrics") or {}
    financials = data.get("financials") or []
    if not financials:
        return None
    rev = financials[0].get("revenue")
    mcap_cr = metrics.get("market_cap_cr")
    if rev is None or mcap_cr is None:
        return None
    try:
        rev_f = float(rev)
        # Same unit-detect heuristic used pre-Stage-2: raw-rupees when
        # revenue exceeds 1e9 (smallest listed IT-services co. >100 Cr
        # ≈ 1e9 raw INR), already-in-crores otherwise.
        rev_cr = rev_f / 1e7 if rev_f > 1e9 else rev_f
        if rev_cr <= 0:
            return None
        return float(mcap_cr) / rev_cr
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def _build_cohort_session():
    """Acquire a session for the sector cohort query. Returns (sess, owns)."""
    sess = _get_session()
    return sess


def _axis_value_percentile(data: dict, metric_kind: str) -> dict:
    """Generic sector-percentile Value axis.

    `metric_kind` ∈ {"mos", "pb", "rev_multiple"}.

    Each metric's directional convention:
      - mos:           higher = cheaper. Score ∝ percentile (rank rises
                       with bigger MoS, mapped via 100-rank inversion
                       inside _percentile_to_score so cheap = high score).
      - pb:            lower = cheaper. We compute percentile of the raw
                       value (low PB → low rank) then invert via 100-rank
                       so cheap → high score.
      - rev_multiple:  lower = cheaper. Same inversion as PB.
    """
    from backend.services import sector_percentile as sp

    sector_label_raw = data.get("sector") or ""
    industry_label_raw = data.get("industry") or ""
    cohort: list[dict] = []
    sess = _build_cohort_session()
    sector_label = ""
    if sess is not None and sector_label_raw:
        try:
            cohort = sp.compute_sector_cohort(
                sector_label_raw, sess, industry_label=industry_label_raw,
            )
        except Exception as exc:
            logger.info("hex value: cohort fetch failed for %s: %s",
                        sector_label_raw, exc)
            cohort = []
        finally:
            _safe_close(sess)
        # Best-effort canonical label (may resolve via alias / industry).
        try:
            sector_label = sp._canonical_sector(
                sector_label_raw, industry_label_raw,
            ) or ""
        except Exception:
            sector_label = ""

    sector_peers = len(cohort)
    median_mos = _median_or_none([c.get("mos_pct") for c in cohort])
    median_pe = _median_or_none([c.get("pe_ratio") for c in cohort])
    median_pb = _median_or_none([c.get("pb_ratio") for c in cohort])

    def _pack(percentile: Optional[int], why: str,
              data_limited: bool = False) -> dict:
        band = sp.value_band_for_percentile(percentile)
        score = _percentile_to_score(percentile)
        if data_limited or percentile is None:
            return {
                "score": None,
                "label": band["label"],
                "why": why,
                "data_limited": True,
                "percentile": None,
                "band": "data_limited",
                "sector_peers": sector_peers,
                "sector_label": sector_label,
                "sector_median_mos": median_mos,
                "sector_median_pe": median_pe,
                "sector_median_pb": median_pb,
            }
        return {
            "score": score,
            "label": band["label"],
            "why": why,
            "data_limited": False,
            "percentile": int(percentile),
            "band": band["band"],
            "sector_peers": sector_peers,
            "sector_label": sector_label,
            "sector_median_mos": median_mos,
            "sector_median_pe": median_pe,
            "sector_median_pb": median_pb,
        }

    if sector_peers < 10:
        return _pack(
            None,
            f"Cohort too small ({sector_peers} peers) for percentile rank",
            data_limited=True,
        )

    # Resolve this ticker's metric value.
    if metric_kind == "mos":
        my_value = _resolve_mos_pct(data)
        if my_value is None:
            return _pack(None, "No MoS available for ticker",
                         data_limited=True)
        cohort_values = [c["mos_pct"] for c in cohort
                         if c.get("mos_pct") is not None]
        if len(cohort_values) < 10:
            return _pack(None,
                         f"Only {len(cohort_values)} MoS peers in cohort",
                         data_limited=True)
        # Higher MoS = cheaper = should map to high score.
        # percentile_rank gives % below; for MoS we want it directly so
        # that cheap (high MoS) ranks near 100 → invert via 100-rank
        # so the legacy score formula (10 - p/10) still rewards cheap.
        raw_rank = sp.percentile_rank(my_value, cohort_values)
        percentile = 100 - raw_rank
        why = (
            f"MoS {my_value:.0f}% vs sector median "
            f"{median_mos:.0f}%" if median_mos is not None else
            f"MoS {my_value:.0f}% vs sector cohort"
        ) + f" ({sector_peers} peers)"
        # Cyclical-trough anchor context: PR #168 sets fcf_data_source
        # to a string containing "trough_anchor" when the cyclical
        # fallback fired. Surface that in the reason text so the
        # anchor's effect is auditable.
        analysis = data.get("analysis") or {}
        _fcf_src = _dig(analysis, "valuation", "fcf_data_source") or ""
        if isinstance(_fcf_src, str) and "trough_anchor" in _fcf_src:
            why += " (cyclical-trough anchor)"
        return _pack(percentile, why)

    if metric_kind == "pb":
        metrics = data.get("metrics") or {}
        my_value = metrics.get("pb_ratio")
        if my_value is None:
            return _pack(None, "No P/BV available for ticker",
                         data_limited=True)
        try:
            my_value = float(my_value)
        except (TypeError, ValueError):
            return _pack(None, "Non-numeric P/BV", data_limited=True)
        cohort_values = [c["pb_ratio"] for c in cohort
                         if c.get("pb_ratio") is not None]
        if len(cohort_values) < 10:
            return _pack(None,
                         f"Only {len(cohort_values)} P/BV peers in cohort",
                         data_limited=True)
        # Low P/BV = cheaper. percentile_rank gives % below; invert so
        # cheap → low percentile → high score.
        raw_rank = sp.percentile_rank(my_value, cohort_values)
        percentile = raw_rank  # low PB → low rank → high score via 10 - p/10
        why = (
            f"P/BV {my_value:.2f}x vs sector median "
            f"{median_pb:.2f}x" if median_pb is not None else
            f"P/BV {my_value:.2f}x vs sector cohort"
        ) + f" ({sector_peers} peers)"
        return _pack(percentile, why)

    if metric_kind == "rev_multiple":
        my_value = _resolve_revenue_multiple(data)
        if my_value is None:
            # No revenue/mcap → fall through to MoS-percentile so IT
            # tickers without financials still get a sector-relative read.
            return _axis_value_percentile(data, "mos")
        cohort_rev_multiples: list[float] = []
        # The cohort table has pe_ratio + pb_ratio + mos_pct only —
        # rev_multiple isn't materialised. Use P/E as a proxy for IT
        # cohort richness when comparing rev-multiples isn't possible
        # within the Stage-2 cohort schema. (Stage-3 candidate: extend
        # sector_percentile to surface ev_revenue.)
        cohort_values = [c["pe_ratio"] for c in cohort
                         if c.get("pe_ratio") is not None]
        if len(cohort_values) < 10:
            return _pack(None,
                         f"Only {len(cohort_values)} P/E peers in IT cohort",
                         data_limited=True)
        # Use ticker's own P/E (from market_metrics) for the rank;
        # rev_multiple feeds into the why string only.
        metrics = data.get("metrics") or {}
        my_pe = metrics.get("pe_ratio")
        if my_pe is None:
            return _pack(None, "No P/E for ticker", data_limited=True)
        try:
            my_pe_f = float(my_pe)
        except (TypeError, ValueError):
            return _pack(None, "Non-numeric P/E", data_limited=True)
        raw_rank = sp.percentile_rank(my_pe_f, cohort_values)
        percentile = raw_rank  # low PE → low rank → high score
        why = (
            f"P/E {my_pe_f:.1f}x (rev mult {my_value:.2f}x) vs "
            f"sector median P/E "
            + (f"{median_pe:.1f}x" if median_pe is not None else "—")
            + f" ({sector_peers} peers)"
        )
        return _pack(percentile, why)

    return _pack(None, f"Unknown metric_kind {metric_kind}",
                 data_limited=True)


def _axis_value_general(data: dict) -> dict:
    return _axis_value_percentile(data, "mos")


def _axis_value_bank(data: dict) -> dict:
    return _axis_value_percentile(data, "pb")


def _axis_value_it(data: dict) -> dict:
    return _axis_value_percentile(data, "rev_multiple")


def _axis_quality(data: dict, sector: str) -> dict:
    analysis = data.get("analysis") or {}
    q = analysis.get("quality") or {}
    piotroski = q.get("piotroski_score") or q.get("piotroski")
    roce = q.get("roce")
    roe = q.get("roe")

    # ── Bank branch (feat/bank-prism-metrics 2026-04-21) ──────────
    # For banks, ROCE is None by design (capital-employed doesn't apply
    # to deposit-funded businesses). We blend ROA + ROE against
    # bank-appropriate thresholds so the Quality axis actually lights
    # up. Anchors are the Indian banking cohort:
    #   ROA:   >1.4% strong, ~1.0% average, <0.6% weak
    #   ROE:   >16% strong, ~12% average, <8% weak
    # Piotroski is de-emphasised — most of its 9 signals (inventory
    # turnover, gross margin, asset turnover) don't map to banks.
    if sector == "bank":
        roa = q.get("roa")
        if roa is None and roe is None:
            return _neutral_axis("No bank quality data (ROA/ROE)")
        score = 5.0
        reasons: list[str] = []
        if roa is not None:
            try:
                r = float(roa)
                # ROA anchor 1.0% = neutral. 1.4% -> ~6.0, 1.8% -> ~7.0,
                # 0.6% -> ~4.0. Bounded so a single metric can't pin the
                # axis to a floor/ceiling.
                score += max(-2.0, min(3.0, (r - 1.0) * 2.5))
                reasons.append(f"ROA {r:.2f}%")
            except Exception:
                pass
        if roe is not None:
            try:
                v = float(roe)
                # ROE anchor 12% = neutral. Each +4% ROE = +1 axis pt.
                # 16% -> 6.0, 20% -> 7.0, 8% -> 4.0. Bounded both sides.
                score += max(-2.0, min(2.5, (v - 12.0) * 0.25))
                reasons.append(f"ROE {v:.1f}%")
            except Exception:
                pass
        # Cost-to-Income sharpens Quality — low c2i = operating leverage.
        c2i = q.get("cost_to_income")
        if c2i is not None:
            try:
                c = float(c2i)
                # Indian bank cohort: top private ~40-45%, PSU ~55-65%.
                # Anchor 55% (cohort median) so PSU banks aren't punished
                # for running normal-for-PSU cost ratios; a private bank
                # at 42% gets a +0.6 uplift, a weak bank at 75% gets
                # -1.0. Bounded tightly — c/i is a tiebreaker, not the
                # dominant driver.
                score += max(-1.2, min(0.8, (55.0 - c) * 0.05))
                reasons.append(f"C/I {c:.0f}%")
            except Exception:
                pass
        return _axis(
            score,
            ", ".join(reasons) if reasons else "Bank quality partial",
            data_limited=(roa is None and roe is None),
        )

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

    # data_limited triggers ONLY when ALL three quality scores
    # (Piotroski, ROCE, ROE) are missing. Margin stability alone is
    # not strong enough to light Quality without one return metric.
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
        # data_limited only when no quality signal could be read at all.
        data_limited=(piotroski is None and primary is None),
    )


def _axis_growth(data: dict, sector: str = "general") -> dict:
    analysis = data.get("analysis") or {}
    q = analysis.get("quality") or {}

    # ── Bank branch (feat/bank-prism-metrics 2026-04-21) ──────────
    # Banks' growth is better measured as advances + deposits + PAT
    # YoY than revenue CAGR (revenue here is interest-income-heavy
    # and swings with the rate cycle). The analysis_service populates
    # `advances_yoy` / `deposits_yoy` / `pat_yoy_bank` via
    # _fetch_bank_metrics_inputs.
    #
    # UNIT CONTRACT (verified 2026-04-22): these three fields are all
    # produced by ratios_service.compute_yoy_growth which returns
    # PERCENT (12.5 means 12.5%). Do NOT apply the decimal→percent
    # normalisation that _axis_growth's non-bank path does below —
    # that would silently 100× the score. The non-bank path uses
    # compute_revenue_cagr which returns DECIMAL, hence the asymmetry.
    if sector == "bank":
        adv_yoy = q.get("advances_yoy")
        dep_yoy = q.get("deposits_yoy")
        pat_yoy = q.get("pat_yoy_bank")
        parts = [v for v in (adv_yoy, dep_yoy, pat_yoy) if v is not None]
        if parts:
            score = 5.0
            reasons: list[str] = []
            # Each +10% composite growth ≈ +1.0 axis point.
            # Advances / deposits get equal weight; PAT is quality-of-growth.
            # Inputs are in PERCENT units (see UNIT CONTRACT above), so
            # `avg * 0.10` yields the correct score contribution.
            try:
                comps = [float(v) for v in parts]
                avg = sum(comps) / len(comps)
                score += avg * 0.10
            except Exception:
                return _neutral_axis("Bank growth parse error")
            if adv_yoy is not None:
                reasons.append(f"Adv YoY {float(adv_yoy):.1f}%")
            if dep_yoy is not None:
                reasons.append(f"Dep YoY {float(dep_yoy):.1f}%")
            if pat_yoy is not None:
                reasons.append(f"PAT YoY {float(pat_yoy):.1f}%")
            return _axis(
                score,
                ", ".join(reasons) if reasons else "Bank growth partial",
                data_limited=False,
            )
        # ── BUG FIX #3 Part B (HEX_AXIS_SOURCE_MAP.md §9 Bug #4) ─────
        # Bank-specific YoY fields (advances_yoy, deposits_yoy,
        # pat_yoy_bank) were added in feat/bank-prism-metrics on
        # 2026-04-21. Any `analysis_cache.payload` written before
        # that date — or any bank ticker whose `_is_bank_like`
        # detection in analysis/service.py missed (e.g. SBIN when
        # sector string is NULL and the BANK.NS suffix check fails) —
        # has all three fields = None, which previously made the
        # Growth axis return neutral 5.0 and crushed composite scores
        # (HDFCBANK=17 pre-fix).
        #
        # Defensive fallback: when bank YoY fields are missing, fall
        # through to the general-branch revenue/EPS CAGR logic below,
        # computed on the fly from `data.financials`. This keeps Growth
        # lit with a real signal until the cache refreshes under a
        # bumped CACHE_VERSION.
        # Affected tickers: HDFCBANK, ICICIBANK, KOTAKBANK, SBIN,
        # AXISBANK, BAJFINANCE, BAJAJFINSV.
        # Expected recovery: HDFCBANK Growth 5.0 -> 6-7 using
        # revenue/EPS CAGR from financials; composite 17 -> ~55+.
        logger.info(
            "hex: bank YoY growth fields missing for %s, falling back "
            "to revenue/EPS CAGR from financials",
            data.get("ticker") or "?",
        )
        # Flow continues into the general-branch CAGR code path below.

    # Revenue CAGR — from analysis payload first, financials as fallback.
    #
    # FIX (prism-nonbank-regression): previously we only read
    # `analysis.quality.revenue_cagr_3y|_5y`. For tickers whose cached
    # analysis payload doesn't carry those fields (stale cache, or
    # yfinance income_df was too short at compute time) the whole Growth
    # axis degraded to data_limited=true → UI renders "n/a". TCS.NS
    # was the canary: analysis_cache.quality had neither CAGR field even
    # though the financials table has 5+ years of revenue. Fall back to
    # computing CAGR from the financials series so Growth stays lit
    # whenever we can derive it from EITHER source.
    rev_cagr = q.get("revenue_cagr_3y")
    if rev_cagr is None:
        rev_cagr = q.get("revenue_cagr_5y")

    # Unit normalisation: analysis_service emits CAGR as DECIMAL
    # (0.124 = 12.4%, see ratios_service.compute_revenue_cagr docstring
    # and responses.QualityOutput.revenue_cagr_3y). Internally this
    # function scores in PERCENT units (anchor 10% -> 5.5). Convert
    # now so the score contribution & the displayed reason both use
    # the same unit. Values already in percent (>= 1.0) are left alone.
    if rev_cagr is not None:
        try:
            rv = float(rev_cagr)
            if -1.5 < rv < 1.5:
                rev_cagr = rv * 100.0
            else:
                rev_cagr = rv
        except (TypeError, ValueError):
            rev_cagr = None

    # EPS CAGR from financials — already in percent units.
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

    # Revenue CAGR fallback — derive from the financials series (same
    # source as EPS CAGR above) when analysis payload lacked CAGR.
    if rev_cagr is None:
        rev_series = [f.get("revenue") for f in fins if f.get("revenue") is not None]
        if len(rev_series) >= 3:
            try:
                old = float(rev_series[-1])
                new = float(rev_series[0])
                years = len(rev_series) - 1
                if old > 0 and new > 0 and years > 0:
                    rev_cagr = ((new / old) ** (1.0 / years) - 1.0) * 100.0
            except Exception:
                rev_cagr = None

    # data_limited triggers ONLY when BOTH revenue CAGR and EPS CAGR
    # are absent. Either one alone is enough to light the axis — many
    # SMEs report only one of the two consistently.
    if rev_cagr is None and eps_cagr is None:
        return _neutral_axis("No growth history available")

    score = 5.0
    reasons: list[str] = []
    # PR #168: cap each component contribution to ±2.5 axis points so a
    # single deeply-negative cycle-bottom CAGR can't single-handedly
    # floor the whole axis to 0. Cyclicals at trough routinely produce
    # EPS CAGR < -50% (TATASTEEL EPS collapsed from ~₹70 peak to ~₹3
    # at trough -> 3y CAGR ≈ -60%). The honest score for "growth was
    # cyclical and we're at the bottom" is ~3-4, not 0.
    if rev_cagr is not None:
        try:
            r = float(rev_cagr)
            # Anchor 10% -> 5.5; 20% -> 6.5. r is in PERCENT.
            contrib = max(-2.5, min(2.5, r * 0.10))
            score += contrib
            reasons.append(f"Rev CAGR {r:.1f}%")
        except Exception:
            pass
    if eps_cagr is not None:
        try:
            contrib = max(-2.5, min(2.5, eps_cagr * 0.08))
            score += contrib
            reasons.append(f"EPS CAGR {eps_cagr:.1f}%")
        except Exception:
            pass

    return _axis(
        score,
        ", ".join(reasons) if reasons else "Partial growth data",
        # data_limited only when neither revenue nor EPS growth could be read.
        # One of the two is enough of a signal to render a lit axis.
        data_limited=(rev_cagr is None and eps_cagr is None),
    )


def _axis_moat(data: dict, sector: str) -> dict:
    analysis = data.get("analysis") or {}
    q = analysis.get("quality") or {}
    moat_grade = q.get("moat") or _dig(analysis, "moat", "grade")

    score = 5.0
    reasons: list[str] = []
    moat_signal = False
    margin_signal = False

    # ── Bank branch: moat = scale + distribution ───────────────────
    # For banks, the traditional "Wide/Narrow" moat call is misleading
    # — our analysis pipeline returns "N/A (Financial)". Scale (measured
    # by market cap / total assets) is the single biggest durable
    # advantage in Indian banking: distribution network, CASA base,
    # regulatory relationships, and low-cost-funds all scale. This
    # matches how the Street values franchise strength (look at SBIN
    # vs. RBLBANK P/B gap for the intuition).
    if sector == "bank":
        metrics = data.get("metrics") or {}
        mcap_cr = metrics.get("market_cap_cr")
        # Scale anchor: 50,000 Cr = 5.0 (neutral), each 10x market cap
        # ≈ +2 axis points. SBIN / HDFCBANK / ICICIBANK land near 8-9;
        # microcap banks near 3-4.
        if mcap_cr is not None:
            try:
                mc = float(mcap_cr)
                if mc > 0:
                    score = 5.0 + max(-3.0, min(3.5, math.log10(mc / 50000.0) * 2.0))
                    reasons.append(f"Scale (mcap {mc:,.0f} Cr)")
                    moat_signal = True
            except Exception:
                pass
        # Cost-to-Income as a franchise-quality signal: a bank with
        # structurally lower c2i has pricing power in deposits +
        # operating leverage — both franchise proxies.
        c2i = q.get("cost_to_income")
        if c2i is not None:
            try:
                c = float(c2i)
                # 45% = +0.5, 65% = -0.5. Cap tightly so this never
                # dominates the scale signal.
                score += max(-0.8, min(0.8, (50.0 - c) * 0.04))
                reasons.append(f"C/I {c:.0f}%")
                margin_signal = True
            except Exception:
                pass
        if not (moat_signal or margin_signal):
            return _neutral_axis("No bank scale/efficiency signal")
        return _axis(
            score,
            ", ".join(reasons) if reasons else "Bank franchise partial",
            data_limited=False,
        )

    if isinstance(moat_grade, str):
        g = moat_grade.lower()
        if "wide" in g:
            score += 3.0
            reasons.append("Wide moat")
            moat_signal = True
        elif "moderate" in g:
            # PR #36 introduced the "Moderate" band via the
            # STRONG_BRAND_ALLOWLIST floor. Map it between Narrow and
            # Wide so bellwethers (TITAN, RELIANCE) don't collapse to
            # neutral when the allowlist fires.
            score += 2.0
            reasons.append("Moderate moat")
            moat_signal = True
        elif "narrow" in g:
            score += 1.5
            reasons.append("Narrow moat")
            moat_signal = True
        elif "none" in g or g == "no moat":
            score -= 1.5
            reasons.append("No moat")
            moat_signal = True

    # Numeric moat_score fallback — when `quality.moat` is null in a
    # stale cached payload, the analysis pipeline still persists
    # `quality.moat_score` (0-100 scale, see QualityOutput). Map it
    # onto the same band contributions so a null-label row still lights
    # the axis. This mirrors the STRONG_BRAND_ALLOWLIST floor logic
    # applied in analysis/service.py (>=60 ≈ Moderate, >=75 ≈ Wide).
    if not moat_signal:
        try:
            ms = q.get("moat_score")
            if ms is not None:
                ms_f = float(ms)
                if ms_f >= 75.0:
                    score += 3.0
                    reasons.append(f"Moat score {ms_f:.0f}/100")
                    moat_signal = True
                elif ms_f >= 60.0:
                    score += 2.0
                    reasons.append(f"Moat score {ms_f:.0f}/100")
                    moat_signal = True
                elif ms_f >= 40.0:
                    score += 1.5
                    reasons.append(f"Moat score {ms_f:.0f}/100")
                    moat_signal = True
                elif ms_f > 0.0:
                    score -= 1.0
                    reasons.append(f"Moat score {ms_f:.0f}/100")
                    moat_signal = True
        except (TypeError, ValueError):
            pass

    # Margin stability proxy — works as a brand/pricing-power signal
    # for any sector, not just IT. A small-cap with stable op margins
    # over 3+ years exhibits real pricing power even without a formal
    # moat classification.
    fins = data.get("financials") or []
    op_margins = [f.get("op_margin") for f in fins if f.get("op_margin") is not None]
    if len(op_margins) >= 3:
        try:
            stdev = statistics.pstdev([float(x) for x in op_margins])
            # Very stable (<3 stdev) -> bonus
            score += max(-0.5, min(1.0, (5.0 - stdev) * 0.15))
            if stdev < 3.0:
                reasons.append("Stable margins")
                margin_signal = True
            else:
                # Even noisier margins still count as a real (if weak)
                # signal — we read 3+ years of op-margin history.
                margin_signal = True
                reasons.append(f"Op-margin σ {stdev:.1f}")
        except Exception:
            pass

    # data_limited only when we have NO moat classification AND no
    # multi-year op-margin history. Either alone lights the axis.
    if not (moat_signal or margin_signal):
        return _neutral_axis("No moat classification or margin history")
    return _axis(score, ", ".join(reasons) if reasons else "Partial moat data",
                 data_limited=False)


def _axis_safety(data: dict, sector: str) -> dict:
    analysis = data.get("analysis") or {}
    q = analysis.get("quality") or {}
    de = q.get("de_ratio") or q.get("debt_to_equity")
    int_cov = q.get("interest_coverage")
    altman = q.get("altman_z")

    # ── BUG FIX #1 (HEX_AXIS_SOURCE_MAP.md §9 Bug #1) ─────────────
    # D/E unit normalisation. yfinance's `info.debtToEquity` returns
    # the ratio as PERCENT (e.g. 45.0 means 45% i.e. 0.45), but the
    # downstream arithmetic in the general + IT Safety branches
    # expects DECIMAL (0.45). Feeding raw 45.0 into `(1.0 - de)*2.0`
    # clips the score to -3.0 and collapses Safety to ~2.0/10 for
    # every non-IT general stock with real debt — RELIANCE, ASIANPAINT,
    # POWERGRID, NTPC, L&T all showed Safety 2-4 pre-fix.
    #
    # Heuristic: any reported D/E > 5.0 is almost certainly in
    # percent units. A real decimal D/E of 5+ would itself be a
    # distress signal and the rest of the Safety formula (interest
    # coverage + Altman Z) would still flag it.
    #
    # Banks route to the bank branch above and never reach here, so
    # their structural 10-15x D/E is not affected by this guard.
    # Expected recovery: RELIANCE Safety ~3/10 -> ~6/10; composite
    # lift ~1 point on dozens of general-branch Nifty names.
    if de is not None:
        try:
            de_raw = float(de)
            if de_raw > 5.0:
                de = de_raw / 100.0
        except (TypeError, ValueError):
            pass

    # PR-D1: bank-aware Safety branch.
    # Banks should NOT be scored on D/E / interest coverage / Altman Z —
    # those metrics are designed for non-financial corporates. Tier-1
    # capital ratio, gross NPA% and net NPA% are the right safety proxies
    # for banks.
    #
    # FIX (prism-nonbank-regression): previously this branch ALSO matched
    # any raw sector string containing "bank" or ("financial services"
    # + sub_sector "bank"). That double-gating could mis-route a non-bank
    # into the bank Safety branch if `stocks.sector` carried an unusual
    # string (e.g. "Banking Equipment Manufacturer"). The internal
    # `_classify_sector` above is the authoritative classifier — it
    # already consults both the hand-maintained bank/NBFC ticker sets
    # AND the raw `sector` string via the same "bank/financial services"
    # heuristics. Trusting its output is both strictly correct and
    # cheaper — we only fall into the bank Safety branch when the
    # classifier explicitly returned "bank".
    is_bank_branch = (sector == "bank")
    if is_bank_branch:
        # Look for bank-specific inputs on the data envelope. These fields
        # are NOT currently populated by the analysis pipeline; if/when
        # they are added (likely sources: BSE XBRL filings, RBI Form A),
        # this branch will start producing real bank-Safety scores.
        # Until then we fall back to the existing P/BV franchise proxy.
        q_in = data.get("quality") or analysis.get("quality") or {}
        metrics_in = data.get("metrics") or {}
        gnpa_pct = (
            q_in.get("gnpa_pct")
            or metrics_in.get("gnpa_pct")
            or data.get("gnpa_pct")
        )
        nnpa_pct = (
            q_in.get("nnpa_pct")
            or metrics_in.get("nnpa_pct")
            or data.get("nnpa_pct")
        )
        tier1_ratio = (
            q_in.get("tier1_ratio")
            or metrics_in.get("tier1_ratio")
            or data.get("tier1_ratio")
        )

        bank_inputs_available = any(
            v is not None for v in (gnpa_pct, nnpa_pct, tier1_ratio)
        )

        if bank_inputs_available:
            score = 5.0
            reasons_b: list[str] = []
            try:
                if tier1_ratio is not None:
                    t1 = float(tier1_ratio)
                    # RBI minimum Tier-1 (incl. CCB) is ~9.5%. 13%+ comfortable,
                    # 16%+ strong. Map linearly with caps.
                    score += max(-2.5, min(2.5, (t1 - 12.0) * 0.5))
                    reasons_b.append(f"Tier-1 {t1:.1f}%")
                if gnpa_pct is not None:
                    g = float(gnpa_pct)
                    # GNPA: <2% strong (+1.5), 4% neutral, >8% distressed (-2.5)
                    score += max(-2.5, min(1.5, (4.0 - g) * 0.4))
                    reasons_b.append(f"GNPA {g:.2f}%")
                if nnpa_pct is not None:
                    n = float(nnpa_pct)
                    # NNPA: <0.5% strong (+1.0), 1.5% neutral, >3% bad (-2.0)
                    score += max(-2.0, min(1.0, (1.5 - n) * 0.7))
                    reasons_b.append(f"NNPA {n:.2f}%")
                return _axis(
                    score,
                    ", ".join(reasons_b) if reasons_b else "Bank capital/asset-quality proxy",
                )
            except Exception:
                logger.info(
                    "PR-D1 bank Safety inputs present but unparseable for %s, "
                    "using generic P/BV proxy",
                    data.get("ticker") or "?",
                )
        else:
            # Documented fallback: until the pipeline plumbs gnpa_pct/
            # nnpa_pct/tier1_ratio into the hex data envelope, this is the
            # only path. Logged at INFO so we can grep prod for bank
            # tickers that would benefit from real CAR data.
            logger.info(
                "PR-D1 bank Safety inputs missing for %s, using generic formula",
                data.get("ticker") or "?",
            )

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

    if sector == "it":
        # IT firms are usually net-cash; D/E ~0 and interest_coverage is
        # meaningless (no debt to cover). Altman Z for asset-light services
        # tends to be unstable. Use a simpler proxy: low D/E is good,
        # and margin stability is a capital-preservation signal.
        fins_it = data.get("financials") or []
        op_margins_it = [
            f.get("op_margin") for f in fins_it if f.get("op_margin") is not None
        ]
        reasons_it: list[str] = []
        score_it = 5.0
        signal_it = False
        if de is not None:
            try:
                de_f = float(de)
                # Net-cash / low-debt IT firms earn a strong safety uplift.
                score_it += max(-1.0, min(2.5, (0.3 - de_f) * 4.0))
                reasons_it.append(f"D/E {de_f:.2f}")
                signal_it = True
            except Exception:
                pass
        else:
            # Absent D/E usually means debt is immaterial; assume safe-ish.
            score_it += 1.5
            reasons_it.append("Low/no reported debt")
            signal_it = True
        if len(op_margins_it) >= 2:
            try:
                stdev = statistics.pstdev([float(x) for x in op_margins_it])
                score_it += max(-1.0, min(1.5, (4.0 - stdev) * 0.25))
                if stdev < 3.0:
                    reasons_it.append("Stable margins")
                signal_it = True
            except Exception:
                pass
        if not signal_it:
            return _neutral_axis("No IT-safety signal")
        return _axis(score_it, ", ".join(reasons_it) if reasons_it else "IT safety proxy")

    # data_limited triggers ONLY when ALL of D/E, interest coverage and
    # Altman Z are absent. A microcap with just D/E (and no Altman) is
    # still a real safety signal and lights the axis.
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
        # data_limited only when all three leverage/coverage metrics are absent.
        data_limited=(de is None and int_cov is None and altman is None),
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
        growth_axis = _axis_growth(data, sector)
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

    # Stage 2 (sector-percentile Value): an axis whose score is None
    # (data_limited) substitutes the neutral 5.0 anchor for the overall
    # weighted mean so we don't poison the composite.
    overall = sum(
        ((axes[k].get("score") if axes[k].get("score") is not None else 5.0)) * w
        for k, w in AXIS_WEIGHTS.items()
    )
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

    When this falls through to the neutral payload, we log LOUD (WARNING,
    with exception class name) so ops can spot silent hex regressions in
    production logs. Without this, a broken DB connection would manifest
    to users as "n/a on all 6 axes" with zero signal in the logs.
    """
    try:
        return compute_hex(ticker)
    except Exception as exc:
        logger.warning(
            "hex: compute_hex_safe fallback for %s — %s: %s",
            ticker, type(exc).__name__, exc,
            exc_info=True,
        )
        return {
            "ticker": _normalize_ticker(ticker) or ticker,
            "sector_category": "general",
            "axes": {k: _neutral_axis("compute error") for k in AXIS_WEIGHTS},
            "overall": 5.0,
            "sector_medians": {k: 5.0 for k in AXIS_WEIGHTS},
            "computed_at": datetime.now(timezone.utc).isoformat(),
            "error": "compute_error",
            "error_class": type(exc).__name__,
            "data_limited": True,
            "disclaimer": DISCLAIMER,
        }


def compute_portfolio_hex(holdings: list[dict]) -> dict:
    """
    Aggregate portfolio Hex: weighted mean per axis across tickers.
    `holdings` is a list of {ticker, weight}. Weights are renormalized.

    BUG #14 fix (2026-04-21):
    Previous behaviour: if ANY single holding returned data_limited=True
    for an axis, the entire portfolio axis was poisoned to data_limited
    and the UI rendered "n/a" on all 6 axes. A single Sri-Lanka-listed
    or illiquid ticker could break the whole Prism.

    New behaviour: an axis is flagged data_limited ONLY when every
    contributing holding is data_limited for that axis. Otherwise we
    compute the weighted mean over the SUBSET of holdings with real
    scores, renormalize the subset weights to 1.0, and set
    `partial_data=True` so the UI can still show a number with a hint
    that not every holding contributed.
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
    # Per-axis accumulators: weighted score sum + weight sum OVER
    # non-data_limited holdings only.
    agg_score: dict[str, float] = {k: 0.0 for k in AXIS_WEIGHTS}
    agg_weight: dict[str, float] = {k: 0.0 for k in AXIS_WEIGHTS}
    limited_count: dict[str, int] = {k: 0 for k in AXIS_WEIGHTS}

    for h, w in zip(holdings, weights):
        hx = compute_hex_safe(h.get("ticker", ""))
        per_ticker.append({"ticker": hx.get("ticker"), "weight": round(w, 4),
                           "overall": hx.get("overall")})
        for k in AXIS_WEIGHTS:
            ax = hx["axes"].get(k, {})
            if ax.get("data_limited"):
                limited_count[k] += 1
                continue
            try:
                score = float(ax.get("score", 5.0))
            except (TypeError, ValueError):
                limited_count[k] += 1
                continue
            agg_score[k] += score * w
            agg_weight[k] += w

    axes_out = {}
    total_holdings = len(holdings)
    for k in AXIS_WEIGHTS:
        labeler = _label_pulse if k == "pulse" else _label_general
        contributing = total_holdings - limited_count[k]
        if agg_weight[k] <= 0 or contributing == 0:
            # Every holding is data_limited on this axis — genuinely n/a.
            axes_out[k] = _neutral_axis(
                f"No data on any of {total_holdings} holdings", labeler=labeler,
            )
        else:
            mean = agg_score[k] / agg_weight[k]
            if limited_count[k] > 0:
                why = (
                    f"Weighted across {contributing}/{total_holdings} "
                    f"holdings ({limited_count[k]} had limited data)"
                )
            else:
                why = f"Weighted across {total_holdings} holdings"
            out = _axis(mean, why, data_limited=False, labeler=labeler)
            # Extra flag so the UI can render a soft "partial" hint
            # without downgrading the whole axis to n/a.
            out["partial_data"] = limited_count[k] > 0
            out["contributing_count"] = contributing
            out["total_count"] = total_holdings
            axes_out[k] = out

    overall = round(
        _clamp(sum(
            ((axes_out[k].get("score") if axes_out[k].get("score") is not None else 5.0)) * w
            for k, w in AXIS_WEIGHTS.items()
        )),
        2,
    )

    return {
        "axes": axes_out,
        "overall": overall,
        "holdings": per_ticker,
        "computed_at": datetime.now(timezone.utc).isoformat(),
        "disclaimer": DISCLAIMER,
    }


# ── Single source of truth bridge ───────────────────────────────
# `compute_hex` IS the canonical 6-axis derivation in this codebase.
# Every other call site (live analysis render, hex_history seeder,
# prism timeline, OG card) routes through
# `backend.services.analysis.hex_axes.compute_axes_for_ticker`,
# which delegates HERE. There is no parallel axis-derivation path.
#
# When you need just the {pulse, quality, moat, safety, growth, value}
# floats (e.g. for the hex_history table inserts), call
# `get_hex_axes(ticker)` below to get a typed `HexAxes` dataclass —
# it is a thin projection over `compute_hex_safe(ticker)["axes"]`
# that guarantees the same six floats are produced from the same
# inputs at every call site. See docs/FORMULA_SOURCE_OF_TRUTH.md
# for the broader pattern (introduced in PR #89 for ratio formulas).
def get_hex_axes(ticker: str):
    """Typed projection of the live-render axes onto a HexAxes dataclass.

    Byte-identical to `compute_hex_safe(ticker)["axes"]` modulo the
    discarded per-axis metadata (label, why, data_limited). Use this
    from any call site that needs only the six floats; use
    `compute_hex_safe` directly if you also need the metadata.
    """
    from backend.services.analysis.hex_axes import compute_axes_for_ticker
    return compute_axes_for_ticker(ticker)


__all__ = [
    "compute_hex",
    "compute_hex_safe",
    "compute_portfolio_hex",
    "get_hex_axes",
    "DISCLAIMER",
    "AXIS_WEIGHTS",
]
