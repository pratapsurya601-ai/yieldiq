# backend/services/funds/recompute.py
# Orchestrator: iterate funds, compute returns + risk + score, upsert
# into fund_returns_cache.
#
# Idempotent. CACHE_VERSION discipline mirrors the stock side — the
# active version_id from the manifest (or the env override) is stamped
# onto every row so we can re-key the cache by bumping the manifest.
#
# Operator usage (local-only — do NOT run in the Railway worker per
# project memory; the long-running backfill belongs on a dev laptop):
#
#     DATABASE_URL=... python -m backend.services.funds.recompute
#     DATABASE_URL=... python -m backend.services.funds.recompute --scheme 120503
#     DATABASE_URL=... python -m backend.services.funds.recompute --limit 50
#
# CI usage: the daily cron (.github/workflows/cron-mf-returns-recompute.yml)
# invokes the same entrypoint with no args.
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from collections import defaultdict
from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy import text

logger = logging.getLogger("yieldiq.funds.recompute")

# Active cache_version for this compute pass. Mirrors the v_238 pattern
# from the equity side — a stable string that identifies the schema/logic
# revision the cached rows were produced under. Bumped by editing this
# constant + adding a matching manifest entry in
# backend/services/cache_invalidation_manifest.py.
ACTIVE_CACHE_VERSION = "v_phase2_mf_returns_compute_2026_05_27"

# Default risk-free rate (annual, decimal). Overridden per-run by the
# latest value from rbi_rate / RiskFreeRate when available.
DEFAULT_RISK_FREE_ANNUAL = 0.071


def _load_risk_free(session) -> float:
    """Best-effort fetch of the latest 10y G-Sec rate. Falls back to default."""
    try:
        row = session.execute(
            text(
                "SELECT gsec_10yr_yield FROM risk_free_rates "
                "ORDER BY trade_date DESC LIMIT 1"
            )
        ).fetchone()
        if row and row[0] is not None:
            r = float(row[0])
            # rbi_rate stores percent (e.g. 7.10); convert to decimal.
            return r / 100.0 if r > 1.0 else r
    except Exception as exc:
        logger.warning("risk_free fetch failed: %s — using default", exc)
        # Roll back the failed query so subsequent statements in this
        # session are not blocked by an aborted transaction.
        try:
            session.rollback()
        except Exception:
            pass
    return DEFAULT_RISK_FREE_ANNUAL


def _fetch_scheme_list(session, limit: Optional[int], scheme: Optional[str]) -> list[dict]:
    if scheme:
        q = text(
            "SELECT scheme_code, category, sub_category, benchmark_index_code, inception_date "
            "FROM funds WHERE scheme_code = :sc"
        )
        rows = session.execute(q, {"sc": scheme}).mappings().fetchall()
    else:
        # Only iterate schemes that actually have NAV history. Filtering
        # at the SQL layer avoids wasting a round-trip per empty scheme
        # (the funds table has ~14k rows; only a small subset has been
        # ingested into fund_nav_history so far).
        q = text(
            "SELECT f.scheme_code, f.category, f.sub_category, f.benchmark_index_code, f.inception_date "
            "FROM funds f "
            "WHERE f.is_active = TRUE "
            "  AND EXISTS (SELECT 1 FROM fund_nav_history n "
            "              WHERE n.scheme_code = f.scheme_code) "
            "ORDER BY f.scheme_code "
            + ("LIMIT :lim" if limit else "")
        )
        params = {"lim": limit} if limit else {}
        rows = session.execute(q, params).mappings().fetchall()
    return [dict(r) for r in rows]


def _fetch_nav_series(session, scheme_code: str) -> tuple[list[date], list[float]]:
    rows = session.execute(
        text(
            "SELECT nav_date, nav FROM fund_nav_history "
            "WHERE scheme_code = :sc ORDER BY nav_date"
        ),
        {"sc": scheme_code},
    ).fetchall()
    return [r[0] for r in rows], [float(r[1]) for r in rows]


def _fetch_bench_series(session, code: Optional[str]) -> tuple[list[date], list[float]]:
    if not code:
        return [], []
    rows = session.execute(
        text(
            "SELECT nav_date, tri_value FROM fund_benchmark_history "
            "WHERE benchmark_index_code = :c ORDER BY nav_date"
        ),
        {"c": code},
    ).fetchall()
    return [r[0] for r in rows], [float(r[1]) for r in rows]


_UPSERT_SQL = text(
    """
    INSERT INTO fund_returns_cache (
        scheme_code, computed_at, cache_version, nav_as_of, history_days,
        ret_1y, ret_3y, ret_5y, ret_10y, ret_si,
        cagr_3y, cagr_5y, cagr_10y,
        rolling_3y_mean, rolling_3y_median, rolling_3y_min, rolling_3y_max, rolling_3y_window_count,
        stdev_3y, sharpe_3y, sortino_3y, max_dd_3y, max_dd_5y,
        beta_3y, alpha_3y, info_ratio_3y, tracking_error_3y,
        upside_capture_3y, downside_capture_3y, benchmark_excess_3y,
        category_percentile_3y,
        yieldiq_fund_score,
        score_component_rolling, score_component_sharpe, score_component_drawdown,
        score_component_ter, score_component_tenure,
        notes
    ) VALUES (
        :scheme_code, now(), :cache_version, :nav_as_of, :history_days,
        :ret_1y, :ret_3y, :ret_5y, :ret_10y, :ret_si,
        :cagr_3y, :cagr_5y, :cagr_10y,
        :rolling_3y_mean, :rolling_3y_median, :rolling_3y_min, :rolling_3y_max, :rolling_3y_window_count,
        :stdev_3y, :sharpe_3y, :sortino_3y, :max_dd_3y, :max_dd_5y,
        :beta_3y, :alpha_3y, :info_ratio_3y, :tracking_error_3y,
        :upside_capture_3y, :downside_capture_3y, :benchmark_excess_3y,
        :category_percentile_3y,
        :yieldiq_fund_score,
        :score_component_rolling, :score_component_sharpe, :score_component_drawdown,
        :score_component_ter, :score_component_tenure,
        :notes
    )
    ON CONFLICT (scheme_code) DO UPDATE SET
        computed_at = EXCLUDED.computed_at,
        cache_version = EXCLUDED.cache_version,
        nav_as_of = EXCLUDED.nav_as_of,
        history_days = EXCLUDED.history_days,
        ret_1y = EXCLUDED.ret_1y, ret_3y = EXCLUDED.ret_3y,
        ret_5y = EXCLUDED.ret_5y, ret_10y = EXCLUDED.ret_10y, ret_si = EXCLUDED.ret_si,
        cagr_3y = EXCLUDED.cagr_3y, cagr_5y = EXCLUDED.cagr_5y, cagr_10y = EXCLUDED.cagr_10y,
        rolling_3y_mean = EXCLUDED.rolling_3y_mean,
        rolling_3y_median = EXCLUDED.rolling_3y_median,
        rolling_3y_min = EXCLUDED.rolling_3y_min,
        rolling_3y_max = EXCLUDED.rolling_3y_max,
        rolling_3y_window_count = EXCLUDED.rolling_3y_window_count,
        stdev_3y = EXCLUDED.stdev_3y, sharpe_3y = EXCLUDED.sharpe_3y,
        sortino_3y = EXCLUDED.sortino_3y,
        max_dd_3y = EXCLUDED.max_dd_3y, max_dd_5y = EXCLUDED.max_dd_5y,
        beta_3y = EXCLUDED.beta_3y, alpha_3y = EXCLUDED.alpha_3y,
        info_ratio_3y = EXCLUDED.info_ratio_3y,
        tracking_error_3y = EXCLUDED.tracking_error_3y,
        upside_capture_3y = EXCLUDED.upside_capture_3y,
        downside_capture_3y = EXCLUDED.downside_capture_3y,
        benchmark_excess_3y = EXCLUDED.benchmark_excess_3y,
        category_percentile_3y = EXCLUDED.category_percentile_3y,
        yieldiq_fund_score = EXCLUDED.yieldiq_fund_score,
        score_component_rolling = EXCLUDED.score_component_rolling,
        score_component_sharpe = EXCLUDED.score_component_sharpe,
        score_component_drawdown = EXCLUDED.score_component_drawdown,
        score_component_ter = EXCLUDED.score_component_ter,
        score_component_tenure = EXCLUDED.score_component_tenure,
        notes = EXCLUDED.notes
    """
)


_CATEGORY_STATS_UPSERT_SQL = text(
    """
    INSERT INTO fund_category_stats (
        sub_category, updated_at, cache_version,
        median_cagr_1y, median_cagr_3y, median_cagr_5y,
        avg_cagr_1y, avg_cagr_3y, avg_cagr_5y,
        avg_ter, avg_sharpe_3y, avg_stdev_3y, avg_max_drawdown_3y,
        n_funds
    ) VALUES (
        :sub_category, :updated_at, :cache_version,
        :median_cagr_1y, :median_cagr_3y, :median_cagr_5y,
        :avg_cagr_1y, :avg_cagr_3y, :avg_cagr_5y,
        :avg_ter, :avg_sharpe_3y, :avg_stdev_3y, :avg_max_drawdown_3y,
        :n_funds
    )
    ON CONFLICT (sub_category) DO UPDATE SET
        updated_at = EXCLUDED.updated_at,
        cache_version = EXCLUDED.cache_version,
        median_cagr_1y = EXCLUDED.median_cagr_1y,
        median_cagr_3y = EXCLUDED.median_cagr_3y,
        median_cagr_5y = EXCLUDED.median_cagr_5y,
        avg_cagr_1y = EXCLUDED.avg_cagr_1y,
        avg_cagr_3y = EXCLUDED.avg_cagr_3y,
        avg_cagr_5y = EXCLUDED.avg_cagr_5y,
        avg_ter = EXCLUDED.avg_ter,
        avg_sharpe_3y = EXCLUDED.avg_sharpe_3y,
        avg_stdev_3y = EXCLUDED.avg_stdev_3y,
        avg_max_drawdown_3y = EXCLUDED.avg_max_drawdown_3y,
        n_funds = EXCLUDED.n_funds
    """
)


def _nanaware(values: list) -> "Optional[list]":
    """Filter a metric list down to finite floats; return None if empty."""
    import math

    out = []
    for v in values:
        if v is None:
            continue
        try:
            fv = float(v)
        except (TypeError, ValueError):
            continue
        if math.isnan(fv) or math.isinf(fv):
            continue
        out.append(fv)
    return out or None


def recompute_category_stats(
    session,
    per_scheme: dict[str, dict],
    *,
    cache_version: str = ACTIVE_CACHE_VERSION,
) -> dict:
    """Pass-3: aggregate the already-computed per-scheme metrics by the
    effective SEBI peer grouping key COALESCE(sub_category, category) and
    UPSERT one row per group into fund_category_stats (the table's
    `sub_category` PK column stores this COALESCE key).

    funds.sub_category is unpopulated (NULL) universe-wide, so `category`
    is the effective grouping key. Grouping on raw sub_category here would
    produce zero category_stats rows (and the router's peers/stats lookups
    keyed by COALESCE would then find nothing) — so we COALESCE to category.

    Groups the in-memory pass-1/2 results (no extra NAV reads), computes
    median/avg via numpy for cagr_1y (== ret_1y) / cagr_3y / cagr_5y and
    avg sharpe_3y / stdev_3y / max_dd_3y. ``avg_ter`` is left NULL (TER is
    not in the compute objects — never fabricated). n_funds counts schemes
    contributing at least one non-null metric.

    SOFT-FAILS: if fund_category_stats isn't migrated yet (or any UPSERT
    raises), the exception is logged and swallowed so the daily cron's
    primary fund_returns_cache write is never jeopardised.
    """
    import numpy as np

    # Bucket per-scheme metric lists by the effective grouping key.
    buckets: dict[str, dict[str, list]] = defaultdict(
        lambda: {
            "cagr_1y": [], "cagr_3y": [], "cagr_5y": [],
            "sharpe_3y": [], "stdev_3y": [], "max_dd_3y": [],
            "schemes": set(),
        }
    )
    for sc, rec in per_scheme.items():
        if rec.get("skip"):
            continue
        # sub_category is unpopulated in the funds table; category is the
        # effective SEBI peer grouping. Group on COALESCE(sub_category,
        # category) so the per-group stats row keys off category.
        sub = rec.get("sub_category") or rec.get("category")
        if not sub:
            continue
        ret = rec["returns"]
        risk = rec["risk"]
        b = buckets[sub]
        # cagr_1y == trailing 1y return by definition (compute objects have
        # ret_1y but no separate cagr_1y).
        for key, val in (
            ("cagr_1y", ret.ret_1y),
            ("cagr_3y", ret.cagr_3y),
            ("cagr_5y", ret.cagr_5y),
            ("sharpe_3y", risk.sharpe_3y),
            ("stdev_3y", risk.stdev_3y),
            ("max_dd_3y", risk.max_dd_3y),
        ):
            if val is not None:
                b[key].append(val)
                b["schemes"].add(sc)

    written = skipped = 0
    for sub, b in buckets.items():
        try:
            def _median(key: str):
                vals = _nanaware(b[key])
                return float(np.median(np.asarray(vals))) if vals else None

            def _avg(key: str):
                vals = _nanaware(b[key])
                return float(np.mean(np.asarray(vals))) if vals else None

            n_funds = len(b["schemes"])
            if n_funds == 0:
                continue
            params = {
                # `sub` is the COALESCE(sub_category, category) grouping key;
                # sub_category is unpopulated, so this PK column holds the
                # category-derived effective SEBI peer grouping key.
                "sub_category": sub,
                # Bound (not SQL now()) so the same statement runs on
                # Postgres (prod) and SQLite (tests). UTC, tz-aware.
                "updated_at": datetime.now(timezone.utc),
                "cache_version": cache_version,
                "median_cagr_1y": _median("cagr_1y"),
                "median_cagr_3y": _median("cagr_3y"),
                "median_cagr_5y": _median("cagr_5y"),
                "avg_cagr_1y": _avg("cagr_1y"),
                "avg_cagr_3y": _avg("cagr_3y"),
                "avg_cagr_5y": _avg("cagr_5y"),
                # TER not in compute objects — NEVER fabricated. Leave NULL.
                "avg_ter": None,
                "avg_sharpe_3y": _avg("sharpe_3y"),
                "avg_stdev_3y": _avg("stdev_3y"),
                "avg_max_drawdown_3y": _avg("max_dd_3y"),
                "n_funds": n_funds,
            }
            session.execute(_CATEGORY_STATS_UPSERT_SQL, params)
            session.commit()
            written += 1
        except Exception as exc:
            # Most common cause: fund_category_stats not migrated yet. Log
            # and carry on — pass-3 must never poison the primary cache write.
            logger.warning(
                "category_stats_upsert_failed",
                extra={
                    "sub_category": sub,
                    "exception_type": type(exc).__name__,
                },
            )
            try:
                session.rollback()
            except Exception:
                pass
            skipped += 1
    logger.info(
        "recompute_category_stats done: written=%d skipped=%d", written, skipped
    )
    return {"written": written, "skipped": skipped}


def recompute_all(
    session,
    *,
    limit: Optional[int] = None,
    scheme: Optional[str] = None,
    cache_version: str = ACTIVE_CACHE_VERSION,
) -> dict:
    """Run the full Phase 2 compute pipeline against the funds universe.

    Two-pass design: pass 1 computes the per-scheme returns + risk,
    holds them in memory keyed by category. Pass 2 derives the peer
    percentiles + composite score and upserts to fund_returns_cache.
    The two-pass split is needed because the score needs the full
    category cohort to rank.
    """
    from backend.services.funds import compute_returns, compute_risk, compute_score

    schemes = _fetch_scheme_list(session, limit=limit, scheme=scheme)
    if not schemes:
        logger.warning("no schemes selected — nothing to compute")
        return {"processed": 0, "written": 0, "skipped": 0}

    rf = _load_risk_free(session)
    logger.info("recompute_all: %d schemes, rf=%.4f, cache_version=%s",
                len(schemes), rf, cache_version)

    # Pass 1 — per-scheme compute, hold in memory.
    per_scheme: dict[str, dict] = {}
    by_category: dict[str, list[str]] = defaultdict(list)
    t0 = time.time()
    for i, s in enumerate(schemes):
        sc = s["scheme_code"]
        try:
            nav_d, nav_v = _fetch_nav_series(session, sc)
            bench_d, bench_v = _fetch_bench_series(session, s.get("benchmark_index_code"))
            if not nav_d:
                logger.info("skip %s: no NAV history", sc)
                per_scheme[sc] = {"skip": True, "reason": "no NAV history"}
                continue
            ret = compute_returns.compute_returns_for_scheme(nav_d, nav_v)
            risk = compute_risk.compute_risk_for_scheme(
                nav_d, nav_v,
                bench_dates=bench_d if bench_d else None,
                bench_values=bench_v if bench_v else None,
                risk_free_annual=rf,
            )
            per_scheme[sc] = {
                "skip": False,
                "category": s.get("category"),
                "sub_category": s.get("sub_category"),
                "returns": ret,
                "risk": risk,
            }
            if s.get("category"):
                by_category[s["category"]].append(sc)
        except Exception as exc:
            # One bad scheme must not poison the whole batch. Roll back
            # the failed statement so the session is usable for the
            # next iteration, then carry on.
            logger.warning(
                "recompute_scheme_failed",
                extra={
                    "scheme_code": sc,
                    "exception_type": type(exc).__name__,
                },
            )
            try:
                session.rollback()
            except Exception:
                pass
            per_scheme[sc] = {"skip": True, "reason": f"error: {type(exc).__name__}"}
        if (i + 1) % 50 == 0:
            logger.info("pass1: %d/%d (%.1fs)", i + 1, len(schemes), time.time() - t0)

    # Build per-category peer arrays for score percentile.
    cat_rolling: dict[str, list] = defaultdict(list)
    cat_sharpe: dict[str, list] = defaultdict(list)
    cat_dd: dict[str, list] = defaultdict(list)
    cat_cagr3y: dict[str, list] = defaultdict(list)
    for cat, codes in by_category.items():
        for sc in codes:
            rec = per_scheme[sc]
            if rec.get("skip"):
                continue
            cat_rolling[cat].append(rec["returns"].rolling_3y_mean)
            cat_sharpe[cat].append(rec["risk"].sharpe_3y)
            cat_dd[cat].append(rec["risk"].max_dd_3y)
            cat_cagr3y[cat].append(rec["returns"].cagr_3y)

    # Pass 2 — score + upsert.
    written = skipped = 0
    for sc, rec in per_scheme.items():
        if rec.get("skip"):
            skipped += 1
            continue
        ret = rec["returns"]
        risk = rec["risk"]
        cat = rec.get("category")

        # Category percentile of cagr_3y vs peers (higher = better).
        cat_pct = None
        if cat and ret.cagr_3y is not None:
            peers = [v for v in cat_cagr3y.get(cat, []) if v is not None]
            if len(peers) >= 5:
                import numpy as _np
                cat_pct = float(_np.sum(_np.asarray(peers) <= ret.cagr_3y) / len(peers))

        # Score (peer-percentile composite). TER + tenure not yet ingested
        # in Phase 1 — pass None; the tenure cap then sets tenure component
        # to 50 ("unknown"), and TER percentile is omitted from the score.
        score_inp = compute_score.ScoreInputs(
            rolling_3y_mean=ret.rolling_3y_mean,
            sharpe_3y=risk.sharpe_3y,
            max_dd_3y=risk.max_dd_3y,
            ter=None,
            manager_tenure_years=None,
        )
        score = compute_score.compute_score_for_scheme(
            score_inp,
            peer_rolling_3y=cat_rolling.get(cat, []) if cat else [],
            peer_sharpe_3y=cat_sharpe.get(cat, []) if cat else [],
            peer_max_dd_3y=cat_dd.get(cat, []) if cat else [],
            peer_ter=[],
        )

        notes_combined = "; ".join(
            (ret.notes or []) + (risk.notes or []) + (score.notes or [])
        ) or None

        params = {
            "scheme_code": sc,
            "cache_version": cache_version,
            "nav_as_of": ret.nav_as_of,
            "history_days": ret.history_days,
            "ret_1y": ret.ret_1y, "ret_3y": ret.ret_3y, "ret_5y": ret.ret_5y,
            "ret_10y": ret.ret_10y, "ret_si": ret.ret_si,
            "cagr_3y": ret.cagr_3y, "cagr_5y": ret.cagr_5y, "cagr_10y": ret.cagr_10y,
            "rolling_3y_mean": ret.rolling_3y_mean,
            "rolling_3y_median": ret.rolling_3y_median,
            "rolling_3y_min": ret.rolling_3y_min,
            "rolling_3y_max": ret.rolling_3y_max,
            "rolling_3y_window_count": ret.rolling_3y_window_count,
            "stdev_3y": risk.stdev_3y, "sharpe_3y": risk.sharpe_3y,
            "sortino_3y": risk.sortino_3y,
            "max_dd_3y": risk.max_dd_3y, "max_dd_5y": risk.max_dd_5y,
            "beta_3y": risk.beta_3y, "alpha_3y": risk.alpha_3y,
            "info_ratio_3y": risk.info_ratio_3y,
            "tracking_error_3y": risk.tracking_error_3y,
            "upside_capture_3y": risk.upside_capture_3y,
            "downside_capture_3y": risk.downside_capture_3y,
            "benchmark_excess_3y": risk.benchmark_excess_3y,
            "category_percentile_3y": cat_pct,
            "yieldiq_fund_score": score.score,
            "score_component_rolling": score.component_rolling,
            "score_component_sharpe": score.component_sharpe,
            "score_component_drawdown": score.component_drawdown,
            "score_component_ter": score.component_ter,
            "score_component_tenure": score.component_tenure,
            "notes": notes_combined,
        }
        try:
            session.execute(_UPSERT_SQL, params)
            session.commit()
            written += 1
        except Exception as exc:
            logger.warning(
                "recompute_upsert_failed",
                extra={
                    "scheme_code": sc,
                    "exception_type": type(exc).__name__,
                },
            )
            try:
                session.rollback()
            except Exception:
                pass
            skipped += 1
    logger.info("recompute_all done: written=%d skipped=%d (%.1fs)",
                written, skipped, time.time() - t0)

    # Pass 3 — per-sub_category category stats. Rides the existing cron.
    # Skipped in --scheme mode (a single scheme can't form a meaningful
    # category aggregate, and we must not overwrite a full-cohort row with
    # a one-scheme one). Soft-fails so a missing fund_category_stats table
    # (migration not yet applied) never breaks the primary cache write.
    cat_stats = {"written": 0, "skipped": 0}
    if scheme is None:
        try:
            cat_stats = recompute_category_stats(
                session, per_scheme, cache_version=cache_version
            )
        except Exception as exc:
            logger.warning(
                "recompute_category_stats pass soft-failed: %s "
                "(table may not be migrated yet)",
                exc,
            )
            try:
                session.rollback()
            except Exception:
                pass

    return {
        "processed": len(schemes),
        "written": written,
        "skipped": skipped,
        "category_stats_written": cat_stats.get("written", 0),
        "category_stats_skipped": cat_stats.get("skipped", 0),
    }


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    p = argparse.ArgumentParser(description="Recompute fund_returns_cache (Phase 2).")
    p.add_argument("--scheme", help="Process a single scheme_code only.")
    p.add_argument("--limit", type=int, help="Limit to first N schemes (debug aid).")
    p.add_argument("--cache-version", default=ACTIVE_CACHE_VERSION,
                   help="Override cache_version stamped on rows. Default: ACTIVE_CACHE_VERSION.")
    args = p.parse_args(argv)

    if not os.environ.get("DATABASE_URL"):
        print("ERROR: DATABASE_URL not set.", file=sys.stderr)
        return 2

    from data_pipeline.db import Session
    if Session is None:
        print("ERROR: SQLAlchemy Session not initialised.", file=sys.stderr)
        return 2

    with Session() as s:
        result = recompute_all(
            s,
            limit=args.limit,
            scheme=args.scheme,
            cache_version=args.cache_version,
        )
    print(f"processed={result['processed']} written={result['written']} skipped={result['skipped']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
