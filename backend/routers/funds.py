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
    FundBenchmarkPoint,
    FundCategoriesResponse,
    FundCategoryCount,
    FundDetailResponse,
    FundListItem,
    FundListResponse,
    FundNavPoint,
    FundReturnsCache,
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


def _fetch_nav_monthly(db, scheme_code: str, years: int = 5) -> list[FundNavPoint]:
    """Last `years` of monthly-bucketed NAV.

    One row per (scheme_code, calendar month) — the closing NAV of the
    last trading day of the month. Implemented with a DISTINCT ON over
    descending nav_date inside each month bucket; on Postgres this is
    significantly cheaper than window functions for a partitioned table.
    """
    from sqlalchemy import text

    cutoff = date.today() - timedelta(days=365 * years + 30)
    # Portable across Postgres + SQLite (used in tests). We compute the
    # month bucket via SUBSTR on the ISO date string ("YYYY-MM-DD" →
    # "YYYY-MM"), pick the maximum nav_date in each bucket, then join
    # the original rows to grab nav + aum_cr for those month-end dates.
    # Postgres' DISTINCT ON would be slightly faster but is dialect-
    # specific; the join approach is identical in plan shape on both.
    sql = text(
        """
        WITH month_maxima AS (
            SELECT SUBSTR(CAST(nav_date AS TEXT), 1, 7) AS ym,
                   MAX(nav_date) AS nd
            FROM fund_nav_history
            WHERE scheme_code = :sc
              AND nav_date >= :cutoff
            GROUP BY SUBSTR(CAST(nav_date AS TEXT), 1, 7)
        )
        SELECT h.nav_date, h.nav, h.aum_cr
        FROM fund_nav_history h
        JOIN month_maxima m
          ON h.scheme_code = :sc
         AND h.nav_date = m.nd
        ORDER BY h.nav_date ASC
        """
    )
    try:
        rows = db.execute(sql, {"sc": scheme_code, "cutoff": cutoff}).fetchall()
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

    sql = text(
        """
        WITH month_maxima AS (
            SELECT SUBSTR(CAST(nav_date AS TEXT), 1, 7) AS ym,
                   MAX(nav_date) AS nd
            FROM fund_benchmark_history
            WHERE benchmark_index_code = :bc
              AND nav_date >= :cutoff
            GROUP BY SUBSTR(CAST(nav_date AS TEXT), 1, 7)
        )
        SELECT h.nav_date, h.tri_value
        FROM fund_benchmark_history h
        JOIN month_maxima m
          ON h.benchmark_index_code = :bc
         AND h.nav_date = m.nd
        ORDER BY h.nav_date ASC
        """
    )
    try:
        rows = db.execute(
            sql, {"bc": benchmark_index_code, "cutoff": window_start}
        ).fetchall()
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


def _fetch_returns_cache(db, scheme_code: str) -> Optional[FundReturnsCache]:
    """Phase 2 cache lookup. Returns None when the table doesn't exist
    yet (Phase 2 not landed) or when there is no row for this scheme."""
    from sqlalchemy import text

    sql = text(
        """
        SELECT ret_1y, ret_3y, ret_5y, ret_10y, ret_si,
               cagr_3y, cagr_5y,
               ter_direct, ter_regular,
               yieldiq_fund_score
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

    return FundReturnsCache(
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


def _index_where(
    q: Optional[str],
    category: Optional[str],
    dedupe_plans: bool = True,
) -> tuple[str, dict]:
    """Shared WHERE clause + binds for the index list and its count.

    Search is a case-insensitive substring on scheme_name OR amc, using
    LOWER(...) LIKE (portable across Postgres + SQLite — we avoid ILIKE,
    which is Postgres-only). Category is an exact label match. All values
    are parameterised; the dynamic part is only fixed clause text.

    Plan dedupe (default ON): a single fund is sold as up to four
    plan/option permutations (Direct/Regular × Growth/IDCW). For a retail
    browse grid that is noise — we collapse to the Direct-Growth variant
    by keeping only `plan = 'Direct'` rows whose scheme_name is a Growth
    option (i.e. does NOT mention IDCW or Dividend). This roughly turns
    one row-per-permutation into one row-per-fund. The match uses the
    same LOWER(...) LIKE / NOT LIKE idiom as the search filter so it
    stays portable across Postgres + SQLite. Pass dedupe_plans=False to
    return every permutation (e.g. an "?all_plans=1" power-user view).
    """
    clauses = ["COALESCE(is_active, TRUE) = TRUE"]
    params: dict = {}
    if q and q.strip():
        clauses.append("(LOWER(scheme_name) LIKE :q OR LOWER(amc) LIKE :q)")
        params["q"] = f"%{q.strip().lower()}%"
    if category and category.strip():
        clauses.append("category = :category")
        params["category"] = category.strip()
    if dedupe_plans:
        # Direct plan only…
        clauses.append("LOWER(plan) = :plan_direct")
        params["plan_direct"] = "direct"
        # …and the Growth option (exclude income-distribution variants).
        clauses.append("LOWER(scheme_name) NOT LIKE :no_idcw")
        clauses.append("LOWER(scheme_name) NOT LIKE :no_dividend")
        params["no_idcw"] = "%idcw%"
        params["no_dividend"] = "%dividend%"
    return " AND ".join(clauses), params


def _row_to_list_item(r, with_metrics: bool) -> FundListItem:
    """Map a list-query row to FundListItem.

    The first seven columns are always the fund master projection; when
    `with_metrics` is True the row also carries the three LEFT-JOINed
    cache columns (ret_1y, yieldiq_fund_score, ter). Coercion is
    defensive so a stray text/NUMERIC value never 500s the grid.
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
        yieldiq_fund_score=_i(8) if with_metrics else None,
        ter=_f(9) if with_metrics else None,
    )


def _fetch_index_funds(
    db,
    limit: int,
    q: Optional[str] = None,
    category: Optional[str] = None,
    dedupe_plans: bool = True,
) -> list[FundListItem]:
    """Filtered card grid for /funds.

    Active funds matching the optional search + category filter. By
    default the list collapses to one Direct-Growth row per fund (see
    `_index_where`) and LEFT-JOINs `fund_returns_cache` so each card
    carries ret_1y / yieldiq_fund_score / ter (COALESCE(ter_direct,
    ter_regular)). Funds with no cache row keep null metrics rather than
    being dropped (LEFT JOIN). Ordering leads with the YieldIQ Fund Score
    (highest first, nulls last) so the hub surfaces quality funds, then
    falls back to alphabetical by scheme_name for a stable tiebreak.

    If `fund_returns_cache` does not exist yet (Phase 2 not merged in
    some orderings — the same condition the detail endpoint guards
    against), the JOIN query raises; we transparently fall back to the
    plain master query (null metrics, alphabetical order) so the grid
    never 500s and the Phase-3 contract still holds.
    """
    from sqlalchemy import text

    where, params = _index_where(q, category, dedupe_plans=dedupe_plans)
    params["lim"] = limit

    # Portable NULLS-LAST: "(col IS NULL)" is 0/1 on both Postgres and
    # SQLite, so ordering by it ascending pushes the nulls to the end
    # before the DESC score sort. Avoids the Postgres-only "NULLS LAST"
    # keyword. ret_1y is a secondary market-relevance tiebreak.
    joined_sql = text(
        f"""
        SELECT f.scheme_code, f.scheme_name, f.amc, f.category, f.sub_category,
               f.riskometer_level, f.plan,
               c.ret_1y,
               c.yieldiq_fund_score,
               COALESCE(c.ter_direct, c.ter_regular) AS ter
        FROM funds f
        LEFT JOIN fund_returns_cache c
          ON c.scheme_code = f.scheme_code
        WHERE {where}
        ORDER BY (c.yieldiq_fund_score IS NULL) ASC,
                 c.yieldiq_fund_score DESC,
                 (c.ret_1y IS NULL) ASC,
                 c.ret_1y DESC,
                 f.scheme_name ASC
        LIMIT :lim
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

    plain_sql = text(
        f"""
        SELECT scheme_code, scheme_name, amc, category, sub_category,
               riskometer_level, plan
        FROM funds
        WHERE {where}
        ORDER BY scheme_name ASC
        LIMIT :lim
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
    dedupe_plans: bool = True,
) -> int:
    from sqlalchemy import text

    where, params = _index_where(q, category, dedupe_plans=dedupe_plans)
    try:
        row = db.execute(
            text(f"SELECT COUNT(*) FROM funds WHERE {where}"), params
        ).fetchone()
        return int(row[0]) if row and row[0] is not None else 0
    except Exception as exc:
        logger.warning("funds: index count failed: %s", exc)
        return 0


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
    limit: int = Query(48, ge=1, le=60, description="Max cards to return."),
    q: Optional[str] = Query(None, description="Search scheme name or AMC (substring)."),
    category: Optional[str] = Query(None, description="Exact SEBI category filter."),
    all_plans: bool = Query(
        False,
        description=(
            "When false (default) the list collapses to one Direct-Growth "
            "row per fund. Set true to return every plan/option permutation "
            "(Direct/Regular × Growth/IDCW)."
        ),
    ),
) -> FundListResponse:
    """Browse grid for /funds.

    Returns active funds matching the optional search (`q`, substring on
    scheme name / AMC) and `category` filter. By default the grid is
    deduped to the Direct-Growth variant per fund and ordered by the
    YieldIQ Fund Score (highest first, nulls last) so quality funds lead;
    each card carries ret_1y / yieldiq_fund_score / ter LEFT-JOINed from
    the returns cache. Pass `all_plans=true` to see every permutation.
    `total` reflects the same filter so the page can show "N of M
    matching".
    """
    dedupe = not all_plans
    db = _open_session()
    if db is None:
        return FundListResponse(funds=[], total=0)
    try:
        funds = _fetch_index_funds(
            db, limit, q=q, category=category, dedupe_plans=dedupe
        )
        total = _fetch_index_total(
            db, q=q, category=category, dedupe_plans=dedupe
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
        metrics = _fetch_returns_cache(db, scheme_code)
    finally:
        _safe_close(db)

    return FundDetailResponse(
        fund=fund,
        nav_history=nav_history,
        benchmark_history=benchmark_history,
        metrics=metrics,
    )
