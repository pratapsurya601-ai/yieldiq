# backend/services/coverage_tier_service.py
"""
Coverage Tier service — honest framing for which stocks YieldIQ models
well vs partially vs barely.

Background
----------
Until now the platform shipped a single `confidence_score` next to every
verdict. That single number flattens a real and large quality gap:

  * NIFTY 50 names with 20y of clean XBRL financials, deep peer cohorts,
    and large floats produce a DCF we genuinely trust.
  * Recently-listed mid-caps with 2 quarters of audited data, 3 sector
    peers, and validator warnings produce a number we are far less
    confident in.

A user reading "Confidence 62%" cannot tell those two cases apart. The
tier system makes the gap explicit and visible:

  * **Tier A** — full confidence. We have the inputs the model needs.
  * **Tier B** — partial. We have most inputs; one or two warnings.
  * **Tier C** — limited. Recent IPO / micro-cap / thin cohort / data
    gaps. The page should say so prominently.

This is a *labeling-only* feature. It does not change FV, MoS, score,
verdict, or anything else in the analysis pipeline. The tier is computed
from inputs the pipeline already gathered.

Rubric (7 criteria, all weighted equally)
----------------------------------------
For a given ticker we evaluate seven signals:

  1. annual_history_years   >= 10
  2. quarterly_ttm_periods  >= 4
  3. peer_cohort_size       >= 10
  4. market_cap_cr          >= 10000
  5. validator_warnings     == 0
  6. has_recent_xbrl        (latest annual within last 18 months)
  7. shares_data_clean      (shares_outstanding present & non-zero)

Tier A: 7/7 criteria met
Tier B: 5/7 or 6/7 criteria met
Tier C: <= 4/7 criteria met

Thresholds were chosen to match the rough universe distribution stated
in the planning doc:

  * ~200 stocks Tier A   (large-cap NIFTY-style names with deep history)
  * ~800 stocks Tier B   (the bulk of investable mid-caps)
  * ~1200 stocks Tier C  (small-caps, recent IPOs, thin coverage)

Numbers are eyeballed estimates from the canary-50 sample distribution
and may need tweaking after we eyeball the first cron-computed
distribution.

Caching
-------
Results are cached in-memory via the standard `cache` service for 6
hours. The inputs (history depth, peer count, market cap) move slowly,
so a 6h TTL is plenty. The endpoint at /api/v1/coverage/{ticker}
explicitly bypasses cache when called with `?refresh=1`.

This file is pure-additive — does NOT touch FV computation, scoring,
or anything that would require a CACHE_VERSION bump.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from backend.services.cache_service import cache

logger = logging.getLogger("yieldiq.coverage_tier")

# ── Rubric thresholds ──────────────────────────────────────────────
# Tier A — full confidence
TIER_A_MIN_ANNUAL_YEARS = 10
TIER_A_MIN_QUARTERS = 4
TIER_A_MIN_PEER_COHORT = 10
TIER_A_MIN_MCAP_CR = 10_000
TIER_A_MAX_WARNINGS = 0

# Tier B — partial. (Tier A failures with these floors still hit B.)
TIER_B_MIN_ANNUAL_YEARS = 5
TIER_B_MIN_QUARTERS = 3
TIER_B_MIN_PEER_COHORT = 5
TIER_B_MIN_MCAP_CR = 2_000

# Days since latest annual to count as "recent XBRL"
RECENT_XBRL_DAYS = 540  # ~18 months

# Cache TTL — 6 hours. Inputs move slowly.
CACHE_TTL_SEC = 6 * 3600


def _strip_ticker(t: str) -> str:
    return (t or "").upper().strip()


def _db_ticker(t: str) -> str:
    """Strip exchange suffix for DB lookups (matches stocks.ticker convention)."""
    return _strip_ticker(t).replace(".NS", "").replace(".BO", "")


def _get_session():
    """Open a pipeline DB session, returning None if unavailable.

    Mirrors the pattern used across endpoint_cache_service,
    bse_shareholding_service, etc. so coverage tier degrades gracefully
    when the DB is unreachable (we just return Tier C with a `db_unavailable`
    reason rather than 500ing).
    """
    try:
        from data_pipeline.db import Session  # type: ignore
    except Exception as exc:
        logger.warning("coverage_tier: db import failed: %s", exc)
        return None
    if Session is None:
        return None
    try:
        return Session()
    except Exception as exc:
        logger.warning("coverage_tier: Session() failed: %s", exc)
        return None


def _gather_signals(ticker: str) -> dict[str, Any]:
    """Pull the seven raw signals from the DB.

    Returns a dict with keys:
        annual_years, quarter_count, peer_cohort, market_cap_cr,
        validator_warnings, latest_annual_age_days, shares_outstanding,
        sector

    Any signal that cannot be resolved becomes None so the caller can
    treat "missing data" the same as "fails the threshold".
    """
    db_t = _db_ticker(ticker)
    sess = _get_session()
    out: dict[str, Any] = {
        "annual_years": None,
        "quarter_count": None,
        "peer_cohort": None,
        "market_cap_cr": None,
        "validator_warnings": None,
        "latest_annual_age_days": None,
        "shares_outstanding": None,
        "sector": None,
    }
    if sess is None:
        return out

    from sqlalchemy import text

    try:
        # ── financials: annual + quarterly counts + most recent annual age
        fin_row = sess.execute(text("""
            SELECT
                SUM(CASE WHEN period_type = 'annual' THEN 1 ELSE 0 END) AS n_ann,
                SUM(CASE WHEN period_type = 'quarterly' THEN 1 ELSE 0 END) AS n_q,
                MAX(CASE WHEN period_type = 'annual' THEN period_end END) AS last_ann,
                MAX(shares_outstanding) AS shares_max
            FROM financials
            WHERE ticker = :t
        """), {"t": db_t}).mappings().first()

        if fin_row:
            out["annual_years"] = int(fin_row.get("n_ann") or 0)
            out["quarter_count"] = int(fin_row.get("n_q") or 0)
            shares = fin_row.get("shares_max")
            try:
                out["shares_outstanding"] = float(shares) if shares else 0.0
            except (TypeError, ValueError):
                out["shares_outstanding"] = 0.0
            last_ann = fin_row.get("last_ann")
            if last_ann is not None:
                try:
                    from datetime import date as _date
                    today = _date.today()
                    age = (today - last_ann).days
                    out["latest_annual_age_days"] = int(age)
                except Exception:
                    pass
    except Exception as exc:
        logger.warning("coverage_tier: financials query failed for %s: %s", db_t, exc)

    try:
        # ── stocks.sector for peer cohort lookup
        sec_row = sess.execute(text("""
            SELECT sector FROM stocks WHERE ticker = :t LIMIT 1
        """), {"t": db_t}).mappings().first()
        if sec_row:
            out["sector"] = sec_row.get("sector")
    except Exception as exc:
        logger.warning("coverage_tier: sector lookup failed for %s: %s", db_t, exc)

    # ── peer cohort size (count of OTHER tickers in the same sector)
    if out["sector"]:
        try:
            peer_row = sess.execute(text("""
                SELECT COUNT(*) AS n
                FROM stocks
                WHERE sector = :s AND ticker != :t
            """), {"s": out["sector"], "t": db_t}).mappings().first()
            if peer_row:
                out["peer_cohort"] = int(peer_row.get("n") or 0)
        except Exception as exc:
            logger.warning("coverage_tier: peer count failed for %s: %s", db_t, exc)

    try:
        # ── market_cap_cr from market_metrics (latest row)
        mc_row = sess.execute(text("""
            SELECT market_cap_cr
            FROM market_metrics
            WHERE ticker = :t
            ORDER BY as_of_date DESC
            LIMIT 1
        """), {"t": db_t}).mappings().first()
        if mc_row and mc_row.get("market_cap_cr") is not None:
            try:
                out["market_cap_cr"] = float(mc_row["market_cap_cr"])
            except (TypeError, ValueError):
                pass
    except Exception as exc:
        logger.warning("coverage_tier: market_cap query failed for %s: %s", db_t, exc)

    # ── validator warnings: count from analysis_cache.payload.data_issues
    # if cached. Cheap proxy — doesn't fire validators live (would defeat the
    # 6h cache). If we have no cached analysis, treat as None (unknown).
    try:
        from backend.services import analysis_cache_service
        cached = analysis_cache_service.get_cached(_strip_ticker(ticker))
        if cached:
            issues = cached.get("data_issues") or []
            out["validator_warnings"] = len(issues)
    except Exception as exc:
        logger.debug("coverage_tier: analysis_cache lookup failed for %s: %s", db_t, exc)

    try:
        sess.close()
    except Exception:
        pass

    return out


def _evaluate_criteria(signals: dict[str, Any]) -> list[dict[str, Any]]:
    """Apply the 7-criteria rubric, returning a list of per-criterion dicts.

    Each entry has:
        key, label, value, threshold, passed (bool)

    "passed" uses the Tier A threshold — it's the strict bar. A criterion
    that fails Tier A might still meet Tier B's looser floor; that is
    handled in `_assign_tier` below by counting the strict-pass count.
    """
    criteria: list[dict[str, Any]] = []

    # 1. Annual history depth
    n_ann = signals.get("annual_years")
    criteria.append({
        "key": "annual_history",
        "label": "Annual financials >= 10 years",
        "value": n_ann,
        "threshold": TIER_A_MIN_ANNUAL_YEARS,
        "passed": (n_ann is not None and n_ann >= TIER_A_MIN_ANNUAL_YEARS),
    })

    # 2. Quarterly TTM
    n_q = signals.get("quarter_count")
    criteria.append({
        "key": "quarterly_ttm",
        "label": "Quarterly periods >= 4 (full TTM)",
        "value": n_q,
        "threshold": TIER_A_MIN_QUARTERS,
        "passed": (n_q is not None and n_q >= TIER_A_MIN_QUARTERS),
    })

    # 3. Peer cohort
    n_peers = signals.get("peer_cohort")
    criteria.append({
        "key": "peer_cohort",
        "label": "Sector peer cohort >= 10",
        "value": n_peers,
        "threshold": TIER_A_MIN_PEER_COHORT,
        "passed": (n_peers is not None and n_peers >= TIER_A_MIN_PEER_COHORT),
    })

    # 4. Market cap
    mcap = signals.get("market_cap_cr")
    criteria.append({
        "key": "market_cap",
        "label": "Market cap >= INR 10,000 cr",
        "value": mcap,
        "threshold": TIER_A_MIN_MCAP_CR,
        "passed": (mcap is not None and mcap >= TIER_A_MIN_MCAP_CR),
    })

    # 5. Validator warnings (zero is a pass)
    warns = signals.get("validator_warnings")
    criteria.append({
        "key": "validator_warnings",
        "label": "No validator warnings",
        "value": warns,
        "threshold": TIER_A_MAX_WARNINGS,
        "passed": (warns is not None and warns <= TIER_A_MAX_WARNINGS),
    })

    # 6. Recent XBRL (annual filing within ~18 months)
    age = signals.get("latest_annual_age_days")
    criteria.append({
        "key": "recent_xbrl",
        "label": "Latest annual filing within ~18 months",
        "value": age,
        "threshold": RECENT_XBRL_DAYS,
        "passed": (age is not None and age <= RECENT_XBRL_DAYS),
    })

    # 7. Shares outstanding present (the FIX e3a8c2b shares-data quality
    # gate that fires when a ticker reports zero shares — usually means
    # the data pipeline missed a unit conversion).
    shares = signals.get("shares_outstanding")
    criteria.append({
        "key": "shares_data",
        "label": "Shares outstanding present",
        "value": shares,
        "threshold": 0.0,
        "passed": (shares is not None and shares > 0.0),
    })

    return criteria


def _assign_tier(criteria: list[dict[str, Any]], signals: dict[str, Any]) -> tuple[str, list[str]]:
    """Combine the criteria into A/B/C and produce human reasons.

    Tier A: all 7 strict criteria pass.
    Tier B: 5-6 strict criteria pass, AND the looser Tier B floors hold
            for years/quarters/peers/mcap (so a ticker with literally 1
            year of data can't sneak into B by virtue of having 5 OK rows
            on other axes).
    Tier C: everything else.
    """
    n_passed = sum(1 for c in criteria if c["passed"])

    # Tier A — perfect score
    if n_passed == 7:
        return "A", ["Meets all 7 quality criteria for full-confidence modeling."]

    # Tier B floor checks — even with 5+ passes, fail to C if any of the
    # critical-mass floors is breached (e.g. literally 1y of data).
    n_ann = signals.get("annual_years") or 0
    n_q = signals.get("quarter_count") or 0
    n_peers = signals.get("peer_cohort") or 0
    mcap = signals.get("market_cap_cr") or 0

    floors_ok = (
        n_ann >= TIER_B_MIN_ANNUAL_YEARS
        and n_q >= TIER_B_MIN_QUARTERS
        and n_peers >= TIER_B_MIN_PEER_COHORT
        and mcap >= TIER_B_MIN_MCAP_CR
    )

    reasons: list[str] = []
    for c in criteria:
        if not c["passed"]:
            v = c["value"]
            v_str = f"{v}" if v is not None else "unknown"
            reasons.append(f"{c['label']} — actual: {v_str}")

    if n_passed >= 5 and floors_ok:
        return "B", reasons
    return "C", reasons


def compute_coverage_tier(ticker: str, *, refresh: bool = False) -> dict[str, Any]:
    """Compute the coverage tier for a ticker.

    Returns a dict with the shape consumed by:
      * /api/v1/analysis/{ticker}/og-data  (additive `coverage_tier` field)
      * /api/v1/coverage/{ticker}          (full breakdown, methodology page)
      * The CoverageTierBadge frontend component

    Shape:
        {
            "tier": "A" | "B" | "C",
            "criteria_met": "5/7",
            "reasons": ["..."],
            "rubric": [
                {"key": "...", "label": "...", "value": ..., "threshold": ..., "passed": bool},
                ...
            ],
        }

    `refresh=True` bypasses the in-memory cache (used by the methodology
    explorer and admin tooling). The default path hits a 6h cache.
    """
    ticker = _strip_ticker(ticker)
    cache_key = f"coverage_tier:{ticker}"
    if not refresh:
        cached = cache.get(cache_key)
        if cached:
            return cached

    try:
        signals = _gather_signals(ticker)
        criteria = _evaluate_criteria(signals)
        tier, reasons = _assign_tier(criteria, signals)
        n_passed = sum(1 for c in criteria if c["passed"])
        result = {
            "tier": tier,
            "criteria_met": f"{n_passed}/7",
            "criteria_passed": n_passed,
            "criteria_total": 7,
            "reasons": reasons,
            "rubric": criteria,
        }
        cache.set(cache_key, result, ttl=CACHE_TTL_SEC)
        return result
    except Exception as exc:
        # Defensive — coverage tier is decorative metadata. A failure here
        # must NEVER break the underlying analysis page. Log + return a
        # safe "C / unknown" so the badge can still render something.
        logger.warning(
            "coverage_tier: compute failed for %s (%s) — returning safe C",
            ticker, type(exc).__name__,
        )
        return {
            "tier": "C",
            "criteria_met": "0/7",
            "criteria_passed": 0,
            "criteria_total": 7,
            "reasons": ["Coverage tier could not be computed for this ticker."],
            "rubric": [],
        }


def summary_for_og(ticker: str) -> Optional[dict[str, Any]]:
    """Compact projection used by the og-data response.

    The og-data endpoint is hot and public. Don't ship the full rubric
    to every social-card preview — just the headline tier + count so the
    frontend can render the badge without an extra round-trip.
    """
    try:
        full = compute_coverage_tier(ticker)
        return {
            "tier": full["tier"],
            "criteria_met": full["criteria_met"],
        }
    except Exception:
        return None
