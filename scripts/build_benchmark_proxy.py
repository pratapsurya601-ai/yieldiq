"""Build the benchmark comparison data (Route A — total-return proxy).

Two steps, both idempotent, run against DATABASE_URL (via the
mf-benchmark-proxy.yml workflow_dispatch, so no local prod write):

  1. MAP: set funds.benchmark_index_code from the category -> default
     benchmark seed (fund_categories, migration 073). funds.category is
     ~100% populated, so this is a single deterministic UPDATE.

  2. PROXY: for each NIFTY TRI code we can source, synthesize a
     total-return proxy from nse_index_history (which carries the price
     close + dividend yield) and upsert into fund_benchmark_history:

         TRI_t = TRI_{t-1} * (close_t/close_{t-1} + div_yield_{t-1}/100/252)

     i.e. price return + reinvested dividend yield. The base level is
     arbitrary (anchored at the first close); only ratios feed the
     fund-vs-benchmark returns + risk metrics. Labeled a *proxy* in the
     UI — it is ~0.05-0.1%/yr off the official TRI from dividend-timing.

CRISIL_* benchmarks (debt + most hybrid) are NOT in the NSE feed, so they
are reported as deferred — those funds keep the honest "no benchmark"
state until a CRISIL source is added.

--dry-run writes nothing; it just reports the prereq + coverage state
(fund_categories present? nse_index_history populated? which index names
match?), so the first CI run is a safe diagnostic.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys

logger = logging.getLogger("build_benchmark_proxy")

# NIFTY TRI benchmark code -> the NSE `ind_close_all` "Index Name" string
# as stored in nse_index_history.index_name. Best-known names; the script
# logs any code that matches 0 source rows so a wrong name is obvious in
# the dry-run and easily corrected. CRISIL_* codes are intentionally
# absent (no NSE source) and reported as deferred.
TRI_CODE_TO_NSE_NAME = {
    "NIFTY_50_TRI": "Nifty 50",
    "NIFTY_100_TRI": "Nifty 100",
    "NIFTY_500_TRI": "Nifty 500",
    "NIFTY_NEXT_50_TRI": "Nifty Next 50",
    "NIFTY_MIDCAP_150_TRI": "Nifty Midcap 150",
    "NIFTY_SMALLCAP_250_TRI": "Nifty Smallcap 250",
    "NIFTY_LARGEMIDCAP_250_TRI": "Nifty LargeMidcap 250",
    "NIFTY_500_MULTICAP_5025_TRI": "Nifty500 Multicap 50:25:25",
    "NIFTY_500_VALUE_50_TRI": "Nifty500 Value 50",
    "NIFTY_DIVIDEND_OPPS_50_TRI": "Nifty Dividend Opportunities 50",
}

UPSERT_SQL = """
INSERT INTO fund_benchmark_history (benchmark_index_code, nav_date, tri_value)
VALUES %s
ON CONFLICT (benchmark_index_code, nav_date) DO UPDATE SET
    tri_value = EXCLUDED.tri_value
"""
UPSERT_TEMPLATE = "(%(code)s, %(nav_date)s, %(tri)s)"


def synth_proxy_tri(series):
    """series: list of (nav_date, close, div_yield_pct) sorted ascending.

    Returns list of {code-less} (nav_date, tri) with TRI anchored at the
    first valid close and grown daily by price return + reinvested yield.
    Pure function — unit-tested.
    """
    out = []
    tri = None
    prev_close = None
    prev_dy = 0.0
    for nav_date, close, dy in series:
        if close is None or close <= 0:
            continue
        if tri is None:
            tri = float(close)
        else:
            price_ratio = close / prev_close
            daily_div = (prev_dy or 0.0) / 100.0 / 252.0
            tri = tri * (price_ratio + daily_div)
        out.append((nav_date, tri))
        prev_close = close
        prev_dy = dy if dy is not None else prev_dy
    return out


def _connect(db_url):
    import psycopg2
    if db_url.startswith("postgres://"):
        db_url = "postgresql://" + db_url[len("postgres://"):]
    return psycopg2.connect(db_url)


def run(db_url: str, dry_run: bool) -> int:
    conn = _connect(db_url)
    cur = conn.cursor()

    def scalar(q, args=None):
        cur.execute(q, args or ())
        return cur.fetchone()[0]

    def regclass(t):
        return scalar("SELECT to_regclass(%s)", (t,))

    # ── prereq report ────────────────────────────────────────────────
    for t in ("fund_categories", "nse_index_history", "fund_benchmark_history", "funds"):
        logger.info("table %-22s present=%s", t, regclass(t) is not None)
    if regclass("fund_categories") is None:
        logger.error("fund_categories missing — apply migration 073 first.")
        return 2
    if regclass("nse_index_history") is None:
        logger.error("nse_index_history missing — the NSE index feed has never run.")
        return 2

    logger.info("fund_categories rows=%s with_benchmark=%s",
                scalar("SELECT COUNT(*) FROM fund_categories"),
                scalar("SELECT COUNT(*) FROM fund_categories WHERE default_benchmark IS NOT NULL"))
    logger.info("nse_index_history rows=%s indices=%s",
                scalar("SELECT COUNT(*) FROM nse_index_history"),
                scalar("SELECT COUNT(DISTINCT index_name) FROM nse_index_history"))

    # ── step 1: map funds.benchmark_index_code from the seed ─────────
    mappable = scalar("""
        SELECT COUNT(*) FROM funds f JOIN fund_categories c ON c.category=f.category
        WHERE f.is_active AND c.default_benchmark IS NOT NULL
          AND (f.benchmark_index_code IS NULL OR f.benchmark_index_code <> c.default_benchmark)
    """)
    logger.info("MAP: %s active funds need benchmark_index_code set", mappable)
    if not dry_run:
        cur.execute("""
            UPDATE funds f SET benchmark_index_code = c.default_benchmark
            FROM fund_categories c
            WHERE c.category = f.category AND c.default_benchmark IS NOT NULL
              AND f.is_active
              AND (f.benchmark_index_code IS NULL OR f.benchmark_index_code <> c.default_benchmark)
        """)
        conn.commit()
        logger.info("MAP: updated %s rows", cur.rowcount)

    # ── which mapped codes actually have funds, and are they sourceable?
    cur.execute("""
        SELECT c.default_benchmark, COUNT(*)
        FROM funds f JOIN fund_categories c ON c.category=f.category
        WHERE f.is_active AND c.default_benchmark IS NOT NULL
        GROUP BY c.default_benchmark ORDER BY 2 DESC
    """)
    demand = cur.fetchall()
    sourceable = [(code, n) for code, n in demand if code in TRI_CODE_TO_NSE_NAME]
    deferred = [(code, n) for code, n in demand if code not in TRI_CODE_TO_NSE_NAME]
    logger.info("DEMAND: %s distinct benchmarks across active funds", len(demand))
    logger.info("  sourceable (NSE/NIFTY): %s codes, %s funds",
                len(sourceable), sum(n for _, n in sourceable))
    logger.info("  deferred (CRISIL/none): %s codes, %s funds",
                len(deferred), sum(n for _, n in deferred))
    for code, n in deferred:
        logger.info("    deferred: %-32s %s funds", code, n)

    # ── step 2: synthesize proxy TRI for each sourceable code ────────
    total_written = 0
    from psycopg2.extras import execute_values
    for code, n_funds in sourceable:
        nse_name = TRI_CODE_TO_NSE_NAME[code]
        cur.execute(
            "SELECT trade_date, close, div_yield FROM nse_index_history "
            "WHERE index_name = %s AND close IS NOT NULL ORDER BY trade_date ASC",
            (nse_name,),
        )
        series = cur.fetchall()
        proxy = synth_proxy_tri(series)
        logger.info("PROXY %-32s nse=%-26s src_rows=%-5s proxy_pts=%-5s funds=%s",
                    code, nse_name, len(series), len(proxy), n_funds)
        if not proxy:
            logger.warning("  -> 0 source rows for '%s' — check the NSE index_name", nse_name)
            continue
        if not dry_run:
            rows = [{"code": code, "nav_date": d, "tri": v} for d, v in proxy]
            execute_values(cur, UPSERT_SQL, rows, template=UPSERT_TEMPLATE, page_size=1000)
            conn.commit()
            total_written += len(rows)

    logger.info("DONE dry_run=%s tri_rows_written=%s", dry_run, total_written)
    cur.close()
    conn.close()
    return 0


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--dry-run", action="store_true",
                   help="Report prereq + coverage only; write nothing.")
    args = p.parse_args(argv)
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        logger.error("DATABASE_URL not set")
        return 2
    return run(db_url, dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
