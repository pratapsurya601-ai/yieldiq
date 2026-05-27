"""Snapshot NAV + returns + category for the top-50 MF canary set.

Mirrors scripts/snapshot_50_stocks.py for the mutual-fund pipeline.
Run BEFORE and AFTER any change to the MF ingest path (Phase 2+
will add returns/risk compute — this snapshot is the before/after
diff anchor for those changes).

Phase 1 captures the data-foundation primitives only:
    * latest NAV per scheme
    * NAV at T-1y, T-3y, T-5y (interpolated from the closest prior
      trading day if the exact anniversary is a holiday)
    * naive trailing-return %  (informational — the canonical
      returns compute lands in Phase 2; this snapshot stores the
      sanity baseline so Phase 2's numbers can be eyeballed against
      the trivially-derivable values here)
    * funds.category, funds.amc

Output: scripts/snapshots/funds_snapshot_<ts>.json

Read-only. Never mutates DB.

How to run::

    # Windows (PowerShell)
    $env:DATABASE_URL = "<neon uri>"
    py scripts/snapshot_50_funds.py

    # *nix
    DATABASE_URL="<neon uri>" python scripts/snapshot_50_funds.py
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import sys
from pathlib import Path

# Make the repo root importable.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text  # noqa: E402

from data_pipeline.db import Session  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
CANARY_FUNDS_JSON = REPO_ROOT / "scripts" / "canary_funds_50.json"
OUT_DIR = REPO_ROOT / "scripts" / "snapshots"

LOOKBACK_YEARS = (1, 3, 5)


def _load_canary_schemes() -> list[dict]:
    data = json.loads(CANARY_FUNDS_JSON.read_text(encoding="utf-8"))
    seen: set[str] = set()
    out: list[dict] = []
    for row in data["schemes"]:
        sc = row["scheme_code"]
        if sc in seen:
            continue
        seen.add(sc)
        out.append(row)
    return out


SCHEME_QUERY = text(
    """
    SELECT f.scheme_code, f.scheme_name, f.amc, f.category,
           f.plan, f.option, f.is_active
      FROM funds f
     WHERE f.scheme_code = :sc
    """
)

LATEST_NAV_QUERY = text(
    """
    SELECT nav_date, nav
      FROM fund_nav_history
     WHERE scheme_code = :sc
     ORDER BY nav_date DESC
     LIMIT 1
    """
)

NAV_AT_DATE_QUERY = text(
    """
    SELECT nav_date, nav
      FROM fund_nav_history
     WHERE scheme_code = :sc
       AND nav_date <= :target
     ORDER BY nav_date DESC
     LIMIT 1
    """
)


# Phase 2 — fund_returns_cache fields. The query is wrapped in a
# try/except at call-site so the snapshot still works on a DB where the
# migration has not been applied yet (e.g. fresh dev clone).
CACHE_QUERY = text(
    """
    SELECT cache_version, computed_at, nav_as_of, history_days,
           ret_1y, ret_3y, ret_5y, ret_10y, ret_si,
           cagr_3y, cagr_5y, cagr_10y,
           rolling_3y_mean, rolling_3y_median, rolling_3y_window_count,
           stdev_3y, sharpe_3y, sortino_3y, max_dd_3y, max_dd_5y,
           beta_3y, alpha_3y, info_ratio_3y, tracking_error_3y,
           upside_capture_3y, downside_capture_3y, benchmark_excess_3y,
           category_percentile_3y,
           yieldiq_fund_score,
           score_component_rolling, score_component_sharpe,
           score_component_drawdown, score_component_ter, score_component_tenure
      FROM fund_returns_cache
     WHERE scheme_code = :sc
    """
)


def _trailing_return_pct(nav_now: float | None, nav_then: float | None) -> float | None:
    if not nav_now or not nav_then or nav_then <= 0:
        return None
    return round((nav_now / nav_then - 1.0) * 100.0, 4)


def main() -> int:
    if not os.environ.get("DATABASE_URL"):
        print("ERROR: DATABASE_URL not set.", file=sys.stderr)
        return 2
    if Session is None:
        print("ERROR: SQLAlchemy Session not initialised (DATABASE_URL not set).",
              file=sys.stderr)
        return 2

    schemes = _load_canary_schemes()
    rows: list[dict] = []
    with Session() as s:
        for spec in schemes:
            sc = spec["scheme_code"]
            meta = s.execute(SCHEME_QUERY, {"sc": sc}).mappings().fetchone()
            latest = s.execute(LATEST_NAV_QUERY, {"sc": sc}).mappings().fetchone()
            nav_now = float(latest["nav"]) if latest else None
            nav_now_date = latest["nav_date"] if latest else None

            entry: dict = {
                "scheme_code": sc,
                "spec_name": spec["scheme_name"],
                "amc": (meta and meta["amc"]) or spec.get("amc"),
                "category": (meta and meta["category"]) or spec.get("category"),
                "plan": (meta and meta["plan"]) or spec.get("plan"),
                "option": (meta and meta["option"]) or spec.get("option"),
                "is_active": (meta and meta["is_active"]),
                "latest_nav": nav_now,
                "latest_nav_date": nav_now_date,
            }

            if nav_now and nav_now_date:
                for yrs in LOOKBACK_YEARS:
                    target = nav_now_date.replace(year=nav_now_date.year - yrs)
                    past = s.execute(
                        NAV_AT_DATE_QUERY, {"sc": sc, "target": target}
                    ).mappings().fetchone()
                    nav_then = float(past["nav"]) if past else None
                    entry[f"nav_{yrs}y_ago"] = nav_then
                    entry[f"return_{yrs}y_pct"] = _trailing_return_pct(nav_now, nav_then)
            else:
                for yrs in LOOKBACK_YEARS:
                    entry[f"nav_{yrs}y_ago"] = None
                    entry[f"return_{yrs}y_pct"] = None

            # Phase 2 — capture fund_returns_cache fields when available.
            try:
                cache = s.execute(CACHE_QUERY, {"sc": sc}).mappings().fetchone()
            except Exception:
                cache = None
            entry["cache"] = dict(cache) if cache else None

            rows.append(entry)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ts = _dt.datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    out_path = OUT_DIR / f"funds_snapshot_{ts}.json"
    out_path.write_text(
        json.dumps(
            {
                "snapshot_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
                "purpose": "mf_phase2_canary_baseline",
                "scheme_count": len(rows),
                "rows": rows,
            },
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )
    missing = sum(1 for r in rows if r.get("latest_nav") is None)
    print(f"Wrote {len(rows)} schemes ({missing} missing NAV) to {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
