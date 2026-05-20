"""Day-22: Profile the analyze pipeline.

Strategy: hit the live API for 20 representative tickers, measure
wall-clock latency PLUS read the existing compute_ms field from
analysis_cache (which already records server-side compute time).

The mix of tickers covers each Tier-1 engine path PLUS the safety-
net rescue path PLUS a few problematic recent IPOs.
"""
from __future__ import annotations

import json
import os
import statistics
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


TICKERS = [
    # Tier-1 dedicated engines
    ("POWERGRID", "rate_base"),
    ("HDFCBANK", "p_bv_peer"),
    ("HDFCLIFE", "appraisal_value"),
    ("DLF", "pb_plus_land_bank"),
    ("LICI", "appraisal_value"),

    # Generic DCF (large)
    ("RELIANCE", "dcf_large"),
    ("TCS", "dcf_large"),
    ("ITC", "dcf_large"),

    # Pharma generic + CDMO + hospital (Day-13/16/19 sub-buckets)
    ("DRREDDY", "pharma_generic"),
    ("NATCOPHARM", "pharma_generic_v3"),
    ("MAXHEALTH", "hospital"),
    ("APOLLOHOSP", "hospital"),
    ("SYNGENE", "cdmo"),
    ("ANTHEM", "cdmo"),

    # Story-DCF + safety-net rescue
    ("PAYTM", "story_dcf"),
    ("DELHIVERY", "story_dcf_after_dcf_collapse"),
    ("FIVESTAR", "lending_nbfc"),

    # Recent IPO / edge cases
    ("WESTLIFE", "retail_recent_ipo"),
    ("CANHLIFE", "life_insurance_recent"),
    ("ZOMATO", "internet_platform"),
]


def _fetch(ticker: str, timeout: int = 90) -> tuple[float, Optional[dict], Optional[str]]:
    """Hit public stock-summary endpoint, return (elapsed_seconds, payload, error_or_none)."""
    url = f"https://api.yieldiq.in/api/v1/public/stock-summary/{ticker}.NS"
    req = urllib.request.Request(
        url, headers={"User-Agent": "yieldiq-profile-day22/1.0"}
    )
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            elapsed = time.perf_counter() - t0
            return elapsed, body, None
    except urllib.error.HTTPError as e:
        return time.perf_counter() - t0, None, f"http_{e.code}"
    except urllib.error.URLError as e:
        return time.perf_counter() - t0, None, f"url_err: {e.reason}"
    except Exception as e:  # noqa: BLE001
        return time.perf_counter() - t0, None, f"err: {e.__class__.__name__}"


def _fetch_cache_ms(ticker: str) -> Optional[int]:
    """Read compute_ms from analysis_cache for this ticker."""
    from sqlalchemy import create_engine, text
    db = os.environ.get("DATABASE_URL")
    if not db:
        return None
    if db.startswith("postgres://"):
        db = "postgresql://" + db[len("postgres://"):]
    eng = create_engine(db, pool_pre_ping=True)
    with eng.connect() as cn:
        r = cn.execute(text(
            "SELECT compute_ms FROM analysis_cache "
            "WHERE replace(replace(ticker, '.NS', ''), '.BO', '') = :t "
            "ORDER BY computed_at DESC LIMIT 1"
        ), {"t": ticker}).first()
        return int(r[0]) if r and r[0] is not None else None


def main() -> int:
    print(f"{'ticker':<14} {'engine_path':<30} {'wall_s':>8} {'compute_ms':>11} "
          f"{'cached?':<8} {'cache_v':<7} {'engine':<32}")
    print("-" * 120)

    rows: list[dict] = []
    for ticker, expected_path in TICKERS:
        elapsed, payload, err = _fetch(ticker)
        compute_ms = _fetch_cache_ms(ticker)

        engine = "?"
        cache_v = "?"
        cached_flag = "?"
        if payload:
            v = payload.get("valuation") or {}
            engine = v.get("valuation_engine_used") or "?"
            cache_v = str(payload.get("cache_version") or "?")
            # Heuristic: wall time < 1.5s with a payload = cache hit
            cached_flag = "HIT" if elapsed < 1.5 else "MISS"
        elif err:
            engine = err

        rows.append({
            "ticker": ticker, "expected_path": expected_path,
            "wall_s": elapsed, "compute_ms": compute_ms,
            "cached_flag": cached_flag, "cache_v": cache_v, "engine": engine,
        })

        print(
            f"{ticker:<14} "
            f"{expected_path:<30} "
            f"{elapsed:>7.2f}s "
            f"{(str(compute_ms) if compute_ms is not None else '-'):>11} "
            f"{cached_flag:<8} "
            f"{cache_v:<7} "
            f"{engine[:32]:<32}"
        )

    # ── Summary stats ────────────────────────────────────────
    print()
    wall_times = [r["wall_s"] for r in rows if r["wall_s"] is not None]
    compute_ms = [r["compute_ms"] for r in rows if r["compute_ms"] is not None]
    cold_wall = [r["wall_s"] for r in rows if r["cached_flag"] == "MISS"]

    def _p(lst: list[float], q: float) -> float:
        if not lst:
            return 0.0
        s = sorted(lst)
        idx = min(int(q * len(s)), len(s) - 1)
        return s[idx]

    print(f"SUMMARY (n={len(rows)}):")
    print(f"  wall-clock all  p50={_p(wall_times, 0.5):.2f}s  p95={_p(wall_times, 0.95):.2f}s  max={max(wall_times):.2f}s")
    if cold_wall:
        print(f"  wall-clock COLD p50={_p(cold_wall, 0.5):.2f}s  p95={_p(cold_wall, 0.95):.2f}s  max={max(cold_wall):.2f}s  n={len(cold_wall)}")
    if compute_ms:
        print(f"  compute_ms      p50={_p([float(x) for x in compute_ms], 0.5):.0f}ms  p95={_p([float(x) for x in compute_ms], 0.95):.0f}ms")
    print(f"  cache hit rate  {sum(1 for r in rows if r['cached_flag']=='HIT')}/{len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
