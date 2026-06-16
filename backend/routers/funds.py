# backend/routers/funds.py
# ═══════════════════════════════════════════════════════════════
# Mutual Funds — Phase 3-slim read-only API surface.
#
# Endpoints
#   GET /api/v1/funds                       — index landing (top 20)
#   GET /api/v1/funds/{scheme_code}         — fund detail page payload
#
# This router is intentionally read-only and intentionally isolated
# from the existing equity FV / DCF engines. It composes:
#
#   - funds (Phase 1, populated by 067 + AMFI scheme-master ingest)
#   - fund_nav_history (Phase 1, partitioned, populated by 068 + AMFI
#     daily NAV cron) — bucketed monthly for the chart payload.
#   - fund_benchmark_history (Phase 1, 069) — matching TRI window.
#   - fund_returns_cache (Phase 2, OPTIONAL) — Phase 3 ships before
#     Phase 2 lands in some merge orderings, so the entire metrics
#     block returns `null` when the table or row is missing. The
#     frontend renders an em-dash placeholder per field.
#
# No SEBI-banned vocabulary is generated here — only raw numbers,
# AMC-published category labels, and the official Riskometer level
# (read verbatim from `funds.riskometer_level`, never recomputed).
#
# Canary discipline: this is a NEW router that does not touch any
# existing FV / DCF math or shared services. The canary diff harness
# protects backend/routers/ as a surface but the per-PR canary run
# compares cached analysis_cache payloads, which this code does not
# read or write. Safe to ship without canary-diff bump.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from backend.models.fund import (
    Fund,
    FundAllocationSlice,
    FundAmcCount,
    FundAmcsResponse,
    FundBenchmarkPoint,
    FundCategoriesResponse,
    FundCategoryCount,
    FundCategoryStats,
    FundDetailResponse,
    FundListItem,
    FundListResponse,
    FundNavPoint,
    FundPeer,
    FundPeersResponse,
    FundPortfolio,
    FundPortfolioHolding,
    FundReturnsCache,
    FundRiskBlock,
)

logger = logging.getLogger("yieldiq.funds.router")

router = APIRouter(prefix="/api/v1/funds", tags=["funds"])


# ── DB helper ──────────────────────────────────────────────────────────
#
# data_pipeline.db.Session is the project-wide session factory. We
# import lazily inside each handler so the FastAPI cold-start does
# not pay the SQLAlchemy import cost when the funds surface is not
# being hit.


def _open_session():
    """Open a project session, or None if data_pipeline is unavailable.

    Mirrors the defensive pattern used by routers/sectors.py — surfaces
    NEVER 500 on a missing data layer; they degrade to "no data yet".
    """
    try:
        from data_pipeline.db import Session  # type: ignore
    except Exception as exc:  # pragma: no cover — only on misconfigured envs
        logger.warning("funds: data_pipeline.db unavailable: %s", exc)
        return None
    if Session is None:
        return None
    try:
        return Session()
    except Exception as exc:  # pragma: no cover
        logger.warning("funds: Session() failed: %s", exc)
        return None


def _safe_close(db) -> None:
    if db is None:
        return
    try:
        db.close()
    except Exception:  # pragma: no cover
        pass


# ── Fetchers ───────────────────────────────────────────────────────────


_FUND_COLUMNS = (
    "scheme_code, isin_growth, isin_div, scheme_name, amc, plan, option, "
    "category, sub_category, benchmark_index_code, inception_date, "
    "riskometer_level, is_active"
)


def _row_to_fund(row) -> Fund:
    return Fund(
        scheme_code=row[0],
        isin_growth=row[1],
        isin_div=row[2],
        scheme_name=row[3],
        amc=row[4],
        plan=row[5],
        option=row[6],
        category=row[7],
        sub_category=row[8],
        benchmark_index_code=row[9],
        inception_date=row[10],
        riskometer_level=row[11],
        is_active=bool(row[12]) if row[12] is not None else True,
    )


def _fetch_fund(db, scheme_code: str) -> Optional[Fund]:
    from sqlalchemy import text

    sql = text(
        f"SELECT {_FUND_COLUMNS} FROM funds WHERE scheme_code = :sc LIMIT 1"
    )
    try:
        row = db.execute(sql, {"sc": scheme_code}).fetchone()
    except Exception as exc:
        logger.warning("funds: master lookup failed for %s: %s", scheme_code, exc)
        return None
    if row is None:
        return None
    return _row_to_fund(row)


def _stride_cap(rows: list, cap: int = 1000) -> list:
    """Down-sample a chronologically-sorted row list to <= cap points,
    always keeping the first and last. Returns the list unchanged when
    it already fits. Portable (plain Python — no SQL window functions),
    so the same path runs on Postgres + SQLite tests.

    This lets the chart endpoints return DAILY NAV within the window
    (dense line) while bounding payload for long 5y/10y windows: ~daily
    up to `cap` trading days, then lightly strided beyond.
    """
    n = len(rows)
    if n <= cap:
        return rows
    step = (n + cap - 1) // cap  # ceil
    sampled = rows[::step]
    if not sampled or sampled[-1] is not rows[-1]:
        sampled.append(rows[-1])
    return sampled


def _fetch_nav_monthly(db, scheme_code: str, years: int = 5) -> list[FundNavPoint]:
    """Last `years` of DAILY NAV (down-sampled to <=1000 points).

    Previously returned one month-end point per calendar month, which
    made the detail-page chart look sparse/jumpy even when daily data
    existed. Now a plain daily range scan (cheaper than the old CTE+join
    on the partitioned table) + `_stride_cap` for payload safety.
    """
    from sqlalchemy import text

    cutoff = date.today() - timedelta(days=365 * years + 30)
    # Plain daily range scan over the (scheme_code, nav_date) PK — dense
    # line for the chart; _stride_cap bounds the payload for long windows.
    sql = text(
        """
        SELECT nav_date, nav, aum_cr
        FROM fund_nav_history
        WHERE scheme_code = :sc
          AND nav_date >= :cutoff
        ORDER BY nav_date ASC
        """
    )
    try:
        rows = _stride_cap(
            db.execute(sql, {"sc": scheme_code, "cutoff": cutoff}).fetchall()
        )
    except Exception as exc:
        logger.info("funds: nav history empty/failed for %s: %s", scheme_code, exc)
        return []
    out: list[FundNavPoint] = []
    for r in rows:
        try:
            out.append(
                FundNavPoint(
                    nav_date=r[0],
                    nav=float(r[1]),
                    aum_cr=float(r[2]) if r[2] is not None else None,
                )
            )
        except Exception:
            continue
    return out


def _fetch_benchmark_monthly(
    db, benchmark_index_code: Optional[str], window_start: Optional[date]
) -> list[FundBenchmarkPoint]:
    """Matching monthly TRI series. Empty when no benchmark or no data."""
    if not benchmark_index_code or window_start is None:
        return []
    from sqlalchemy import text

    # Daily TRI within the window (matches the now-daily NAV series so the
    # NAV-vs-benchmark overlay lines up); _stride_cap bounds the payload.
    sql = text(
        """
        SELECT nav_date, tri_value
        FROM fund_benchmark_history
        WHERE benchmark_index_code = :bc
          AND nav_date >= :cutoff
        ORDER BY nav_date ASC
        """
    )
    try:
        rows = _stride_cap(
            db.execute(
                sql, {"bc": benchmark_index_code, "cutoff": window_start}
            ).fetchall()
        )
    except Exception as exc:
        logger.info(
            "funds: benchmark history empty/failed for %s: %s",
            benchmark_index_code,
            exc,
        )
        return []
    out: list[FundBenchmarkPoint] = []
    for r in rows:
        try:
            out.append(
                FundBenchmarkPoint(
                    benchmark_index_code=benchmark_index_code,
                    nav_date=r[0],
                    tri_value=float(r[1]),
                )
            )
        except Exception:
            continue
    return out


def _fetch_returns_cache(
    db, scheme_code: str
) -> tuple[Optional[FundReturnsCache], Optional[FundRiskBlock]]:
    """Phase 2 cache lookup → (flat metrics block, risk block).

    Returns ``(None, None)`` when the table doesn't exist yet (Phase 2 not
    landed) or there is no row for this scheme. The flat ``metrics`` block
    is UNCHANGED from the original Phase-3 contract (backwards compat); the
    additional ``risk`` block re-keys the 075 risk columns to the frontend
    contract names.

    Column-name reality (075 migration), since the contract uses slightly
    different names:
      * 075 has ``max_dd_3y`` / ``max_dd_5y`` → contract ``max_drawdown_3y``
        / ``max_drawdown_5y``.
      * 075 has ``upside_capture_3y`` / ``downside_capture_3y`` → contract
        ``up_capture_3y`` / ``down_capture_3y``.
      * 075 has NO ``stdev_5y`` / ``sharpe_5y`` / ``sortino_5y`` column, so
        those contract fields are always null.
      * 075 ``category_percentile_3y`` is 0..1; the contract wants 0..100,
        so we multiply by 100 on the way out.
    """
    from sqlalchemy import text

    sql = text(
        """
        SELECT ret_1y, ret_3y, ret_5y, ret_10y, ret_si,
               cagr_3y, cagr_5y,
               ter_direct, ter_regular,
               yieldiq_fund_score,
               stdev_3y, sharpe_3y, sortino_3y,
               max_dd_3y, max_dd_5y,
               beta_3y, alpha_3y, info_ratio_3y, tracking_error_3y,
               upside_capture_3y, downside_capture_3y, benchmark_excess_3y,
               category_percentile_3y, nav_as_of
        FROM fund_returns_cache
        WHERE scheme_code = :sc
        LIMIT 1
        """
    )
    try:
        row = db.execute(sql, {"sc": scheme_code}).fetchone()
    except Exception as exc:
        # Table not yet created (Phase 2 not merged) is the most common
        # path here. Log at INFO not WARNING — this is expected.
        logger.info(
            "funds: returns cache lookup soft-failed for %s "
            "(Phase 2 may not be live yet): %s",
            scheme_code,
            exc,
        )
        return None, None
    if row is None:
        return None, None

    def _f(idx: int) -> Optional[float]:
        v = row[idx]
        if v is None:
            return None
        try:
            return float(v)
        except Exception:
            return None

    def _i(idx: int) -> Optional[int]:
        v = row[idx]
        if v is None:
            return None
        try:
            return int(v)
        except Exception:
            return None

    metrics = FundReturnsCache(
        ret_1y=_f(0),
        ret_3y=_f(1),
        ret_5y=_f(2),
        ret_10y=_f(3),
        ret_si=_f(4),
        cagr_3y=_f(5),
        cagr_5y=_f(6),
        ter_direct=_f(7),
        ter_regular=_f(8),
        yieldiq_fund_score=_i(9),
    )

    cat_pct_frac = _f(22)  # 075 stores 0..1; contract wants 0..100
    risk = FundRiskBlock(
        lookback="3y",
        as_of=row[23],  # nav_as_of (date) — passed through, not coerced
        stdev_3y=_f(10),
        stdev_5y=None,
        sharpe_3y=_f(11),
        sharpe_5y=None,
        sortino_3y=_f(12),
        sortino_5y=None,
        max_drawdown_3y=_f(13),
        max_drawdown_5y=_f(14),
        beta_3y=_f(15),
        alpha_3y=_f(16),
        info_ratio_3y=_f(17),
        tracking_error_3y=_f(18),
        up_capture_3y=_f(19),
        down_capture_3y=_f(20),
        benchmark_excess_3y=_f(21),
        category_percentile_3y=(cat_pct_frac * 100.0)
        if cat_pct_frac is not None
        else None,
    )
    return metrics, risk


def _fetch_category_stats(
    db, group_key: Optional[str]
) -> Optional[FundCategoryStats]:
    """Per-group aggregate stats from fund_category_stats.

    `group_key` is the effective SEBI peer grouping key — i.e. the caller's
    COALESCE(sub_category, category). funds.sub_category is unpopulated
    (NULL) universe-wide, so `category` is the effective grouping key; the
    fund_category_stats `sub_category` PK column now stores that COALESCE
    key (recompute.py pass-3 writes it that way).

    Returns None when the table doesn't exist yet (migration not applied),
    when the fund has no grouping key, or when there's no row for it. CAGR
    columns are decimal fractions; category_percentile is not part of this
    block (it lives on the risk block per-scheme).
    """
    if not group_key:
        return None
    from sqlalchemy import text

    # The `sub_category` PK column stores the COALESCE(sub_category, category)
    # grouping key; sub_category is unpopulated in the funds table, so we
    # match on the category-derived key recompute pass-3 wrote.
    sql = text(
        """
        SELECT sub_category, n_funds,
               median_cagr_1y, median_cagr_3y, median_cagr_5y,
               avg_cagr_1y, avg_cagr_3y, avg_cagr_5y,
               avg_ter, avg_sharpe_3y, avg_stdev_3y, avg_max_drawdown_3y
        FROM fund_category_stats
        WHERE sub_category = :key
        LIMIT 1
        """
    )
    try:
        row = db.execute(sql, {"key": group_key}).fetchone()
    except Exception as exc:
        logger.info(
            "funds: category_stats lookup soft-failed for %r "
            "(table may not be migrated yet): %s",
            group_key,
            exc,
        )
        return None
    if row is None:
        return None

    def _f(idx: int) -> Optional[float]:
        v = row[idx]
        if v is None:
            return None
        try:
            return float(v)
        except Exception:
            return None

    def _i(idx: int) -> Optional[int]:
        v = row[idx]
        if v is None:
            return None
        try:
            return int(v)
        except Exception:
            return None

    return FundCategoryStats(
        sub_category=row[0],
        n_funds=_i(1),
        median_cagr_1y=_f(2),
        median_cagr_3y=_f(3),
        median_cagr_5y=_f(4),
        avg_cagr_1y=_f(5),
        avg_cagr_3y=_f(6),
        avg_cagr_5y=_f(7),
        avg_ter=_f(8),
        avg_sharpe_3y=_f(9),
        avg_stdev_3y=_f(10),
        avg_max_drawdown_3y=_f(11),
    )


def _fetch_peers(
    db, scheme_code: str, group_key: Optional[str], limit: int = 3
) -> list[FundPeer]:
    """Up to `limit` same-group peer rows (excluding self) plus a trailing
    category-average pseudo-row.

    `group_key` is the subject fund's effective SEBI peer grouping key —
    COALESCE(sub_category, category). funds.sub_category is unpopulated
    (NULL) universe-wide, so `category` is the effective grouping key and
    we match peers on COALESCE(f.sub_category, f.category) = :key (keying
    on raw sub_category would return zero peers for every fund).

    Peers are ordered by fund_score DESC (nulls last) purely as a STABLE,
    deterministic display ordering — NOT a ranking verdict. The query
    LEFT-JOINs fund_returns_cache for ret_1y / ret_3y / fund_score /
    ter_direct; a fund with no cache row still appears (with null metrics).
    Returns an empty list when the grouping key is missing. Soft-fails to
    the peers it can build (and still appends the category-average row when
    fund_category_stats is available).
    """
    if not group_key:
        return []
    from sqlalchemy import text

    # Portable NULLS-LAST (see _fetch_index_funds): "(col IS NULL) ASC"
    # pushes nulls to the end before the DESC sort. Self is excluded.
    # Match on COALESCE(sub_category, category): sub_category is unpopulated
    # in the funds table, so category is the effective SEBI peer grouping.
    peers_sql = text(
        """
        SELECT f.scheme_code, f.scheme_name, f.amc, f.riskometer_level,
               c.yieldiq_fund_score, c.ret_1y, c.ret_3y, c.ter_direct
        FROM funds f
        LEFT JOIN fund_returns_cache c
          ON c.scheme_code = f.scheme_code
        WHERE COALESCE(f.sub_category, f.category) = :key
          AND f.scheme_code <> :sc
          AND COALESCE(f.is_active, TRUE) = TRUE
        ORDER BY (c.yieldiq_fund_score IS NULL) ASC,
                 c.yieldiq_fund_score DESC,
                 f.scheme_name ASC
        LIMIT :lim
        """
    )

    def _f(v) -> Optional[float]:
        if v is None:
            return None
        try:
            return float(v)
        except Exception:
            return None

    def _i(v) -> Optional[int]:
        if v is None:
            return None
        try:
            return int(v)
        except Exception:
            return None

    out: list[FundPeer] = []
    try:
        rows = db.execute(
            peers_sql, {"key": group_key, "sc": scheme_code, "lim": limit}
        ).fetchall()
        for r in rows:
            out.append(
                FundPeer(
                    scheme_code=r[0],
                    scheme_name=r[1],
                    amc=r[2],
                    riskometer_level=r[3],
                    fund_score=_i(r[4]),
                    ret_1y=_f(r[5]),
                    ret_3y=_f(r[6]),
                    ter_direct=_f(r[7]),
                    is_category_average=False,
                )
            )
    except Exception as exc:
        logger.info(
            "funds: peers query soft-failed for %s (returns cache may be "
            "absent); returning what we have: %s",
            scheme_code,
            exc,
        )

    # Append the category-average pseudo-row when the stats table is live.
    # Keyed by the same COALESCE(sub_category, category) grouping key —
    # sub_category is unpopulated, so category is the effective SEBI group.
    stats = _fetch_category_stats(db, group_key)
    if stats is not None:
        out.append(
            FundPeer(
                scheme_code=None,
                scheme_name=f"{group_key} category average",
                amc=None,
                fund_score=None,
                # category stats hold CAGR (decimal fractions); the peer
                # contract surfaces ret_1y / ret_3y. avg_cagr_1y is the
                # 1y CAGR (== trailing 1y return) so it maps cleanly.
                ret_1y=stats.avg_cagr_1y,
                ret_3y=stats.avg_cagr_3y,
                ter_direct=stats.avg_ter,
                riskometer_level=None,
                is_category_average=True,
            )
        )
    return out


def _fetch_portfolio(db, scheme_code: str) -> FundPortfolio:
    """Holdings block. Forward-compatible: returns the explicit empty
    "updating" state when fund_holdings has no rows (or isn't migrated
    yet), and surfaces top holdings + asset / sector / mcap roll-ups once
    rows exist.

    Uses the latest as_of_month present for the scheme. weight_pct /
    change_3m_pct are PERCENTS (stored verbatim from the disclosure).
    """
    empty = FundPortfolio(
        updating=True,
        as_of_month=None,
        holdings_count=0,
        holdings=[],
        asset_allocation=[],
        sector_allocation=[],
        mcap_allocation=[],
    )
    from sqlalchemy import text

    # Latest as_of_month for this scheme (None when table empty/absent).
    try:
        mrow = db.execute(
            text(
                "SELECT MAX(as_of_month) FROM fund_holdings "
                "WHERE scheme_code = :sc"
            ),
            {"sc": scheme_code},
        ).fetchone()
    except Exception as exc:
        logger.info(
            "funds: holdings lookup soft-failed for %s (table may not be "
            "migrated yet): %s",
            scheme_code,
            exc,
        )
        return empty
    as_of = mrow[0] if mrow else None
    if as_of is None:
        return empty

    def _f(v) -> Optional[float]:
        if v is None:
            return None
        try:
            return float(v)
        except Exception:
            return None

    # Top holdings for the latest month, heaviest weight first.
    holdings: list[FundPortfolioHolding] = []
    try:
        hrows = db.execute(
            text(
                """
                SELECT isin, instrument, weight_pct, asset_class, sector,
                       mcap_bucket, change_3m_pct
                FROM fund_holdings
                WHERE scheme_code = :sc AND as_of_month = :m
                ORDER BY (weight_pct IS NULL) ASC, weight_pct DESC
                """
            ),
            {"sc": scheme_code, "m": as_of},
        ).fetchall()
    except Exception as exc:
        logger.info("funds: holdings rows fetch failed for %s: %s", scheme_code, exc)
        return empty
    if not hrows:
        return empty
    for r in hrows:
        holdings.append(
            FundPortfolioHolding(
                isin=r[0],
                instrument=r[1],
                weight_pct=_f(r[2]),
                asset_class=r[3],
                sector=r[4],
                mcap_bucket=r[5],
                change_3m_pct=_f(r[6]),
            )
        )

    # Roll up allocations by asset_class / sector / mcap_bucket.
    def _rollup(key_attr: str) -> list[FundAllocationSlice]:
        agg: dict[str, float] = {}
        for h in holdings:
            label = getattr(h, key_attr)
            if not label:
                continue
            agg[label] = agg.get(label, 0.0) + (h.weight_pct or 0.0)
        return [
            FundAllocationSlice(label=k, weight_pct=round(v, 4))
            for k, v in sorted(agg.items(), key=lambda kv: kv[1], reverse=True)
        ]

    return FundPortfolio(
        updating=False,
        as_of_month=as_of,
        holdings_count=len(holdings),
        holdings=holdings[:25],  # surface the top 25; full set behind ingester
        asset_allocation=_rollup("asset_class"),
        sector_allocation=_rollup("sector"),
        mcap_allocation=_rollup("mcap_bucket"),
    )


def _index_where(
    q: Optional[str],
    category: Optional[str],
    risk: Optional[str] = None,
    amc: Optional[str] = None,
    dedupe_plans: bool = True,
) -> tuple[str, dict]:
    """Shared WHERE clause + binds for the index list and its count.

    Search is a case-insensitive substring on scheme_name OR amc, using
    LOWER(...) LIKE (portable across Postgres + SQLite — we avoid ILIKE,
    which is Postgres-only). Category is an exact label match. `risk` is
    an exact riskometer_level match; `amc` is a case-insensitive
    substring match on the AMC name (so "HDFC" matches "HDFC Mutual
    Fund"). All four filters AND-combine. All values are parameterised;
    the dynamic part is only fixed clause text.

    Plan dedupe (default ON): a single fund is sold as several
    plan/option permutations (Direct/Regular × Growth/IDCW/Bonus/…). For
    a retail browse grid that is noise — we collapse to the Direct-Growth
    variant by keeping only `plan = 'Direct'` rows whose scheme_name is a
    plain Growth option, i.e. does NOT mention any income-distribution or
    alternate-payout token. Empirically (AMFI scheme master) the same
    fund shows up as both a "Growth Option" AND a "Bonus Option" Direct
    row, so excluding Growth-vs-IDCW alone still left two rows per fund
    (e.g. "Nippon India Large Cap Fund … Growth Option" and "… Bonus
    Option"). We therefore also exclude bonus / reinvest / payout /
    income-distribution variants. This turns one-row-per-permutation into
    (close to) one-row-per-fund. The match uses the same LOWER(...) LIKE
    / NOT LIKE idiom as the search filter so it stays portable across
    Postgres + SQLite. Pass dedupe_plans=False to return every
    permutation (e.g. an "?all_plans=1" power-user view).
    """
    clauses = ["COALESCE(is_active, TRUE) = TRUE"]
    params: dict = {}
    if q and q.strip():
        clauses.append("(LOWER(scheme_name) LIKE :q OR LOWER(amc) LIKE :q)")
        params["q"] = f"%{q.strip().lower()}%"
    if category and category.strip():
        clauses.append("category = :category")
        params["category"] = category.strip()
    if risk and risk.strip():
        # Exact match on the official Riskometer level (read verbatim from
        # funds.riskometer_level — never recomputed). Case-sensitive on
        # the stored canonical casing (e.g. "VeryHigh").
        clauses.append("riskometer_level = :risk")
        params["risk"] = risk.strip()
    if amc and amc.strip():
        # Case-insensitive substring on the AMC name so "HDFC" matches
        # "HDFC Mutual Fund". Same portable LOWER(...) LIKE idiom as q.
        clauses.append("LOWER(amc) LIKE :amc")
        params["amc"] = f"%{amc.strip().lower()}%"
    if dedupe_plans:
        # Direct plan only…
        clauses.append("LOWER(plan) = :plan_direct")
        params["plan_direct"] = "direct"
        # …and the plain Growth option only — exclude every non-Growth
        # payout/option token so a fund collapses to a single row. Each
        # token maps to a NOT LIKE clause with its own bind.
        _excluded_option_tokens = {
            "no_idcw": "%idcw%",
            "no_dividend": "%dividend%",
            "no_bonus": "%bonus%",
            "no_payout": "%payout%",
            "no_reinvest": "%reinvest%",
            # AMFI sometimes spells the IDCW option out in full.
            "no_idcw_long": "%income distribution%",
        }
        for bind, pattern in _excluded_option_tokens.items():
            clauses.append(f"LOWER(scheme_name) NOT LIKE :{bind}")
            params[bind] = pattern
    return " AND ".join(clauses), params


def _row_to_list_item(r, with_metrics: bool) -> FundListItem:
    """Map a list-query row to FundListItem.

    The first seven columns are always the fund master projection; when
    `with_metrics` is True the row also carries the LEFT-JOINed cache
    columns in this fixed order:

        7: ret_1y   8: ret_3y   9: ret_5y   10: ret_10y
        11: yieldiq_fund_score   12: ter_direct
        13: ter  (COALESCE(ter_direct, ter_regular))

    Returns are surfaced RAW (cumulative decimal fractions) — no
    server-side annualization. Coercion is defensive so a stray
    text/NUMERIC value never 500s the grid.
    """
    def _f(idx: int) -> Optional[float]:
        if idx >= len(r) or r[idx] is None:
            return None
        try:
            return float(r[idx])
        except Exception:
            return None

    def _i(idx: int) -> Optional[int]:
        if idx >= len(r) or r[idx] is None:
            return None
        try:
            return int(r[idx])
        except Exception:
            return None

    return FundListItem(
        scheme_code=r[0],
        scheme_name=r[1],
        amc=r[2],
        category=r[3],
        sub_category=r[4],
        riskometer_level=r[5],
        plan=r[6],
        ret_1y=_f(7) if with_metrics else None,
        ret_3y=_f(8) if with_metrics else None,
        ret_5y=_f(9) if with_metrics else None,
        ret_10y=_f(10) if with_metrics else None,
        yieldiq_fund_score=_i(11) if with_metrics else None,
        ter_direct=_f(12) if with_metrics else None,
        ter=_f(13) if with_metrics else None,
    )


# ── Screener sort handling ─────────────────────────────────────────────
#
# `sort` selects the ORDER BY column; `order` is asc/desc. Every sort is
# rendered NULLS LAST via the portable "(col IS NULL) ASC" idiom (0/1 on
# both Postgres + SQLite — avoids the Postgres-only "NULLS LAST" keyword)
# and always tie-breaks on scheme_name ASC for a stable, deterministic
# page boundary under offset pagination.
#
# Each sort key maps to its qualified column. `name` sorts on the fund
# master column; the rest sort on the LEFT-JOINed cache columns, so a
# fund with no cache row sorts to the end regardless of `order`. `ter`
# sorts on the raw ter_direct column (the screener's TER column).

SORT_KEYS = ("name", "score", "ret_1y", "ret_3y", "ret_5y", "ret_10y", "ter")
DEFAULT_SORT = "score"

_SORT_COLUMN = {
    "name": "f.scheme_name",
    "score": "c.yieldiq_fund_score",
    "ret_1y": "c.ret_1y",
    "ret_3y": "c.ret_3y",
    "ret_5y": "c.ret_5y",
    "ret_10y": "c.ret_10y",
    "ter": "c.ter_direct",
}


def _order_by_clause(sort: str, order: Optional[str]) -> str:
    """Build the ORDER BY body for the screener.

    Always NULLS LAST, always tie-broken on scheme_name ASC. `name`
    defaults to ascending; every numeric column defaults to descending
    (highest score / return first, cheapest TER... — note TER default is
    still desc per the contract's uniform desc default, the frontend can
    request asc). Returns the clause WITHOUT the leading "ORDER BY".
    """
    sort = sort if sort in _SORT_COLUMN else DEFAULT_SORT
    col = _SORT_COLUMN[sort]
    if order in ("asc", "desc"):
        direction = order.upper()
    else:
        # Per-column default: name ascending, everything else descending.
        direction = "ASC" if sort == "name" else "DESC"

    if sort == "name":
        # scheme_name is NOT NULL; no null-guard needed, no extra tiebreak.
        return f"{col} {direction}"
    # NULLS LAST via "(col IS NULL) ASC", then the chosen direction, then
    # the stable scheme_name ASC tiebreak so pagination boundaries are
    # deterministic across pages.
    return f"({col} IS NULL) ASC, {col} {direction}, f.scheme_name ASC"


def _fetch_index_funds(
    db,
    limit: int,
    offset: int = 0,
    q: Optional[str] = None,
    category: Optional[str] = None,
    risk: Optional[str] = None,
    amc: Optional[str] = None,
    sort: str = DEFAULT_SORT,
    order: Optional[str] = None,
    dedupe_plans: bool = True,
) -> list[FundListItem]:
    """Sortable, paginated, filtered screener rows for /funds.

    Active funds matching the optional q / category / risk / amc filters
    (AND-combined). By default the list collapses to one Direct-Growth
    row per fund (see `_index_where`) and LEFT-JOINs `fund_returns_cache`
    so each row carries the metrics-in-row payload (score + ret_1y /
    ret_3y / ret_5y / ret_10y + ter_direct). Funds with no cache row keep
    null metrics rather than being dropped (LEFT JOIN).

    Ordering is driven by `sort` + `order` (see `_order_by_clause`):
    always NULLS LAST, always tie-broken on scheme_name ASC for a
    deterministic page boundary under `offset` pagination.

    If `fund_returns_cache` does not exist yet (Phase 2 not merged in
    some orderings — the same condition the detail endpoint guards
    against), the JOIN query raises; we transparently fall back to the
    plain master query (null metrics, alphabetical order, still
    offset-paginated) so the grid never 500s.
    """
    from sqlalchemy import text

    where, params = _index_where(
        q, category, risk=risk, amc=amc, dedupe_plans=dedupe_plans
    )
    params["lim"] = limit
    params["off"] = offset
    order_by = _order_by_clause(sort, order)

    joined_sql = text(
        f"""
        SELECT f.scheme_code, f.scheme_name, f.amc, f.category, f.sub_category,
               f.riskometer_level, f.plan,
               c.ret_1y, c.ret_3y, c.ret_5y, c.ret_10y,
               c.yieldiq_fund_score,
               c.ter_direct,
               COALESCE(c.ter_direct, c.ter_regular) AS ter
        FROM funds f
        LEFT JOIN fund_returns_cache c
          ON c.scheme_code = f.scheme_code
        WHERE {where}
        ORDER BY {order_by}
        LIMIT :lim OFFSET :off
        """
    )
    try:
        rows = db.execute(joined_sql, params).fetchall()
        return [
            _row_to_list_item(r, with_metrics=True)
            for r in rows
        ]
    except Exception as exc:
        # Most common cause: fund_returns_cache not created yet. Log at
        # INFO (expected pre-Phase-2) and fall through to the plain query.
        logger.info(
            "funds: index JOIN query soft-failed (returns cache may be "
            "absent); falling back to master-only list: %s",
            exc,
        )

    # Fallback path: no cache table. Only `name` ordering is meaningful
    # (all metric columns are absent), so order on scheme_name regardless
    # of the requested metric sort, honoring asc/desc when `name` was asked.
    plain_dir = "DESC" if (sort == "name" and order == "desc") else "ASC"
    plain_sql = text(
        f"""
        SELECT scheme_code, scheme_name, amc, category, sub_category,
               riskometer_level, plan
        FROM funds
        WHERE {where}
        ORDER BY scheme_name {plain_dir}
        LIMIT :lim OFFSET :off
        """
    )
    try:
        rows = db.execute(plain_sql, params).fetchall()
    except Exception as exc:
        logger.warning("funds: index landing query failed: %s", exc)
        return []
    out: list[FundListItem] = []
    for r in rows:
        try:
            out.append(_row_to_list_item(r, with_metrics=False))
        except Exception:
            continue
    return out


def _fetch_index_total(
    db,
    q: Optional[str] = None,
    category: Optional[str] = None,
    risk: Optional[str] = None,
    amc: Optional[str] = None,
    dedupe_plans: bool = True,
) -> int:
    """FILTERED total (matches the same q/category/risk/amc + dedupe as
    the list query) so the screener can show "N of M matching"."""
    from sqlalchemy import text

    where, params = _index_where(
        q, category, risk=risk, amc=amc, dedupe_plans=dedupe_plans
    )
    try:
        row = db.execute(
            text(f"SELECT COUNT(*) FROM funds WHERE {where}"), params
        ).fetchone()
        return int(row[0]) if row and row[0] is not None else 0
    except Exception as exc:
        logger.warning("funds: index count failed: %s", exc)
        return 0


def _fetch_amcs(db) -> list[FundAmcCount]:
    """Distinct AMC names + active, plan-deduped scheme counts, ordered by
    count desc (then amc asc for a stable tiebreak).

    Plan-deduped via the same `_index_where(dedupe_plans=True)` predicate
    the list endpoint uses, so the counts line up with what the screener
    shows when an AMC filter is applied. Empty list on any failure — the
    surface degrades gracefully (the dropdown just shows no facets).
    """
    from sqlalchemy import text

    where, params = _index_where(None, None, dedupe_plans=True)
    sql = text(
        f"""
        SELECT amc, COUNT(*) AS n
        FROM funds
        WHERE {where}
          AND amc IS NOT NULL
          AND amc <> ''
        GROUP BY amc
        ORDER BY n DESC, amc ASC
        """
    )
    try:
        rows = db.execute(sql, params).fetchall()
    except Exception as exc:
        logger.warning("funds: amcs query failed: %s", exc)
        return []
    out: list[FundAmcCount] = []
    for r in rows:
        try:
            out.append(FundAmcCount(amc=r[0], count=int(r[1])))
        except Exception:
            continue
    return out


def _fetch_categories(db) -> list[FundCategoryCount]:
    """Distinct categories + active-scheme counts, for the hub filter
    chips. Empty list on any failure — the surface degrades gracefully."""
    from sqlalchemy import text

    sql = text(
        """
        SELECT category, COUNT(*) AS n
        FROM funds
        WHERE COALESCE(is_active, TRUE) = TRUE
          AND category IS NOT NULL
          AND category <> ''
        GROUP BY category
        ORDER BY n DESC, category ASC
        """
    )
    try:
        rows = db.execute(sql).fetchall()
    except Exception as exc:
        logger.warning("funds: categories query failed: %s", exc)
        return []
    out: list[FundCategoryCount] = []
    for r in rows:
        try:
            out.append(FundCategoryCount(category=r[0], count=int(r[1])))
        except Exception:
            continue
    return out


# ── Routes ─────────────────────────────────────────────────────────────


@router.get("", response_model=FundListResponse)
def list_funds(
    limit: int = Query(
        25, ge=1, le=50, description="Page size (max 50)."
    ),
    offset: int = Query(0, ge=0, description="Pagination offset."),
    q: Optional[str] = Query(None, description="Search scheme name or AMC (substring)."),
    category: Optional[str] = Query(None, description="Exact SEBI category filter."),
    risk: Optional[str] = Query(
        None, description="Exact riskometer_level filter (e.g. VeryHigh)."
    ),
    amc: Optional[str] = Query(
        None, description="AMC-name substring filter (e.g. HDFC)."
    ),
    sort: str = Query(
        DEFAULT_SORT,
        description=(
            "Sort column: name | score | ret_1y | ret_3y | ret_5y | "
            "ret_10y | ter. Defaults to score."
        ),
    ),
    order: Optional[str] = Query(
        None,
        description=(
            "Sort direction: asc | desc. Default desc (name defaults asc). "
            "Always NULLS LAST."
        ),
    ),
    all_plans: bool = Query(
        False,
        description=(
            "When false (default) the list collapses to one Direct-Growth "
            "row per fund. Set true to return every plan/option permutation "
            "(Direct/Regular × Growth/IDCW)."
        ),
    ),
) -> FundListResponse:
    """Sortable, paginated, filtered screener for /funds.

    Returns active funds matching the optional q / category / risk / amc
    filters (AND-combined). By default the grid is deduped to the
    Direct-Growth variant per fund and ordered by the YieldIQ Fund Score
    (highest first, NULLS LAST). `sort` + `order` drive the ORDER BY —
    every sort is NULLS LAST and tie-broken on scheme_name ASC so
    `offset` pagination has deterministic page boundaries. Each row
    carries the metrics-in-row payload (score + ret_1y/3y/5y/10y +
    ter_direct) LEFT-JOINed from the returns cache; returns are RAW
    stored cumulative fractions (no server-side annualization). `total`
    is the FILTERED count so the page can show "N of M matching". Pass
    `all_plans=true` to see every plan/option permutation.
    """
    dedupe = not all_plans
    # Defensive enum guards — out-of-range values fall back to defaults
    # rather than 422, so a frontend bug never blanks the screener.
    sort_key = sort if sort in SORT_KEYS else DEFAULT_SORT
    order_key = order if order in ("asc", "desc") else None
    db = _open_session()
    if db is None:
        return FundListResponse(funds=[], total=0)
    try:
        funds = _fetch_index_funds(
            db,
            limit,
            offset=offset,
            q=q,
            category=category,
            risk=risk,
            amc=amc,
            sort=sort_key,
            order=order_key,
            dedupe_plans=dedupe,
        )
        total = _fetch_index_total(
            db, q=q, category=category, risk=risk, amc=amc, dedupe_plans=dedupe
        )
    finally:
        _safe_close(db)
    return FundListResponse(funds=funds, total=total)


# NOTE: registered BEFORE the /{scheme_code} route below so "categories"
# is not captured as a scheme_code path param.
@router.get("/categories", response_model=FundCategoriesResponse)
def list_fund_categories() -> FundCategoriesResponse:
    """Distinct fund categories + active-scheme counts, for the hub's
    filter chips."""
    db = _open_session()
    if db is None:
        return FundCategoriesResponse(categories=[])
    try:
        cats = _fetch_categories(db)
    finally:
        _safe_close(db)
    return FundCategoriesResponse(categories=cats)


# NOTE: registered BEFORE the /{scheme_code} route below so "amcs" is not
# captured as a scheme_code path param.
@router.get("/amcs", response_model=FundAmcsResponse)
def list_fund_amcs() -> FundAmcsResponse:
    """Distinct AMC names + active, plan-deduped scheme counts (count
    desc), for the screener's AMC filter dropdown."""
    db = _open_session()
    if db is None:
        return FundAmcsResponse(amcs=[])
    try:
        amcs = _fetch_amcs(db)
    finally:
        _safe_close(db)
    return FundAmcsResponse(amcs=amcs)


@router.get("/{scheme_code}", response_model=FundDetailResponse)
def get_fund(scheme_code: str) -> FundDetailResponse:
    """Composite payload for /funds/[scheme_code].

    Returns 404 only when the scheme_code is not in the `funds` master
    table. All other downstream lookups (NAV history, benchmark TRI,
    Phase 2 cache) degrade to empty / null on failure — the consumer
    page is required to render every field with a graceful fallback.
    """
    # Whitelist: AMFI codes are numeric strings, typically 5-6 digits.
    # We accept up to 8 to leave room for future code changes but reject
    # anything containing characters that have no business in a key —
    # cheap defense against ?scheme_code='; DROP TABLE-style probing in
    # logs even though the underlying query is parameterised.
    if not scheme_code or not scheme_code.isalnum() or len(scheme_code) > 16:
        raise HTTPException(status_code=400, detail="Invalid scheme_code.")

    db = _open_session()
    if db is None:
        raise HTTPException(status_code=503, detail="Data layer unavailable.")
    try:
        fund = _fetch_fund(db, scheme_code)
        if fund is None:
            raise HTTPException(
                status_code=404,
                detail=f"No fund with scheme_code '{scheme_code}'.",
            )
        nav_history = _fetch_nav_monthly(db, scheme_code, years=5)
        window_start = nav_history[0].nav_date if nav_history else None
        benchmark_history = _fetch_benchmark_monthly(
            db, fund.benchmark_index_code, window_start
        )
        metrics, risk = _fetch_returns_cache(db, scheme_code)
        # sub_category is unpopulated in the funds table; category is the
        # effective SEBI peer grouping key the stats row is keyed by.
        group_key = fund.sub_category or fund.category
        category_stats = _fetch_category_stats(db, group_key)
        portfolio = _fetch_portfolio(db, scheme_code)
    finally:
        _safe_close(db)

    return FundDetailResponse(
        fund=fund,
        nav_history=nav_history,
        benchmark_history=benchmark_history,
        metrics=metrics,
        risk=risk,
        category_stats=category_stats,
        portfolio=portfolio,
    )


@router.get("/{scheme_code}/peers", response_model=FundPeersResponse)
def get_fund_peers(scheme_code: str) -> FundPeersResponse:
    """Same-group peers + a category-average row for /funds/[code].

    Returns up to 3 peer funds in the same SEBI group (self excluded),
    ordered by fund_score DESC as a STABLE display ordering only (NOT a
    ranking verdict), followed by a category-average pseudo-row. Strictly
    comparative context — no recommendation language. The grouping key is
    COALESCE(sub_category, category): sub_category is unpopulated in the
    funds table, so category is the effective SEBI peer grouping. 404 only
    when the scheme_code is unknown; an empty peer list (no grouping key,
    or no peers) returns 200 with peers=[].
    """
    if not scheme_code or not scheme_code.isalnum() or len(scheme_code) > 16:
        raise HTTPException(status_code=400, detail="Invalid scheme_code.")

    db = _open_session()
    if db is None:
        raise HTTPException(status_code=503, detail="Data layer unavailable.")
    try:
        fund = _fetch_fund(db, scheme_code)
        if fund is None:
            raise HTTPException(
                status_code=404,
                detail=f"No fund with scheme_code '{scheme_code}'.",
            )
        # sub_category is unpopulated in the funds table; category is the
        # effective SEBI peer grouping key. Group peers + the category-stats
        # row by COALESCE(sub_category, category) so peers actually resolve.
        group_key = fund.sub_category or fund.category
        peers = _fetch_peers(db, scheme_code, group_key, limit=3)
    finally:
        _safe_close(db)

    # Surface the effective grouping key so the UI caption reads the real
    # SEBI group (e.g. "Equity Scheme - Flexi Cap Fund").
    return FundPeersResponse(sub_category=group_key, peers=peers)
