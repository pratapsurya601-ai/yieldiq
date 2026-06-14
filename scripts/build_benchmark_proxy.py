"""Build the benchmark comparison data (Route A — total-return proxy).

Two steps, both idempotent, run against DATABASE_URL (via the
mf-benchmark-proxy.yml workflow_dispatch, so no local prod write):

  1. MAP: set funds.benchmark_index_code from the category -> default
     benchmark seed (fund_categories, migration 073). funds.category holds
     the AMFI *verbose* label ("Equity Scheme - Large Cap Fund") while the
     seed uses the SEBI *short* label ("Large Cap"), so we match on a
     normalized token (_canon) rather than equality — a plain join matched
     only ~97 of ~14k funds.

  2. PROXY: for each NIFTY TRI code we can source, synthesize a
     total-return proxy from nse_index_history (price close + dividend
     yield) and upsert into fund_benchmark_history:

         TRI_t = TRI_{t-1} * (close_t/close_{t-1} + div_yield_{t-1}/100/252)

     i.e. price return + reinvested dividend yield. Base level arbitrary
     (anchored at first close); only ratios feed the fund-vs-benchmark
     metrics. Labeled a *proxy* in the UI (~0.05-0.1%/yr off official TRI).

The PRI-name <-> TRI-code mapping is reused from nse_indices_history
(TRI_BENCHMARK_MAP) so there's one source of truth. CRISIL_* benchmarks
(debt + most hybrid) are not in the NSE feed -> reported as deferred.

--dry-run writes nothing; it reports the prereq + coverage state so the
first CI run is a safe diagnostic.
"""
from __future__ import annotations

import argparse
import logging
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# One source of truth for PRI index name <-> TRI benchmark code.
from data_pipeline.sources.nse_indices_history import TRI_BENCHMARK_MAP  # noqa: E402

logger = logging.getLogger("build_benchmark_proxy")

CODE_TO_NSE_NAME = {code: name for name, code in TRI_BENCHMARK_MAP.items()}

# Tokens dropped when normalizing a category label so the AMFI verbose
# string and the SEBI short label collapse to the same key.
_NOISE = {
    "scheme", "schemes", "fund", "funds", "open", "ended",
    "equity", "debt", "hybrid", "other", "others", "solution", "oriented",
}


def _canon(s: str) -> str:
    s = (s or "").lower().replace("&", " and ")
    toks = [t for t in re.split(r"[^a-z0-9]+", s) if t and t not in _NOISE]
    return "".join(toks)


UPSERT_SQL = """
INSERT INTO fund_benchmark_history (benchmark_index_code, nav_date, tri_value)
VALUES %s
ON CONFLICT (benchmark_index_code, nav_date) DO UPDATE SET
    tri_value = EXCLUDED.tri_value
"""
UPSERT_TEMPLATE = "(%(code)s, %(nav_date)s, %(tri)s)"


def synth_proxy_tri(series):
    """series: list of (nav_date, close, div_yield_pct) sorted ascending.

    Returns [(nav_date, tri)] with TRI anchored at the first valid close
    and grown daily by price return + reinvested yield. Pure / unit-tested.
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

    for t in ("fund_categories", "nse_index_history", "fund_benchmark_history", "funds"):
        logger.info("table %-22s present=%s", t, regclass(t) is not None)
    if regclass("fund_categories") is None or regclass("nse_index_history") is None:
        logger.error("prerequisite table missing — apply migrations / run NSE feed first.")
        return 2

    logger.info("nse_index_history rows=%s indices=%s date_range=%s",
                scalar("SELECT COUNT(*) FROM nse_index_history"),
                scalar("SELECT COUNT(DISTINCT index_name) FROM nse_index_history"),
                scalar("SELECT CONCAT(MIN(trade_date),' .. ',MAX(trade_date)) FROM nse_index_history"))

    # ── step 1: map funds.benchmark_index_code via normalized category ──
    cur.execute("SELECT category, default_benchmark FROM fund_categories WHERE default_benchmark IS NOT NULL")
    canon_to_bench = {_canon(label): bench for label, bench in cur.fetchall()}

    cur.execute("SELECT category, COUNT(*) FROM funds WHERE is_active AND category IS NOT NULL GROUP BY category")
    bench_to_amfi: dict[str, list[str]] = defaultdict(list)
    bench_fund_count: dict[str, int] = defaultdict(int)
    unmatched = []
    for amfi_cat, n in cur.fetchall():
        bench = canon_to_bench.get(_canon(amfi_cat))
        if bench:
            bench_to_amfi[bench].append(amfi_cat)
            bench_fund_count[bench] += n
        else:
            unmatched.append((amfi_cat, n))

    mapped_funds = sum(bench_fund_count.values())
    logger.info("MAP: %s active funds -> %s benchmarks; %s category-labels unmatched",
                mapped_funds, len(bench_to_amfi), len(unmatched))
    for cat, n in sorted(unmatched, key=lambda x: -x[1])[:15]:
        logger.info("  unmatched category: %-45s %s funds", cat[:45], n)

    if not dry_run:
        for bench, amfi_list in bench_to_amfi.items():
            cur.execute(
                "UPDATE funds SET benchmark_index_code=%s "
                "WHERE is_active AND category = ANY(%s) "
                "AND (benchmark_index_code IS NULL OR benchmark_index_code <> %s)",
                (bench, amfi_list, bench),
            )
        conn.commit()
        logger.info("MAP: applied; funds with benchmark_index_code now=%s",
                    scalar("SELECT COUNT(*) FROM funds WHERE is_active AND benchmark_index_code IS NOT NULL"))

    # ── step 2: synthesize proxy TRI for each sourceable benchmark ─────
    sourceable = [(b, n) for b, n in sorted(bench_fund_count.items(), key=lambda x: -x[1]) if b in CODE_TO_NSE_NAME]
    deferred = [(b, n) for b, n in sorted(bench_fund_count.items(), key=lambda x: -x[1]) if b not in CODE_TO_NSE_NAME]
    logger.info("COVERAGE: %s funds sourceable (NSE/NIFTY), %s funds deferred (CRISIL/none)",
                sum(n for _, n in sourceable), sum(n for _, n in deferred))
    for b, n in deferred:
        logger.info("  deferred: %-32s %s funds", b, n)

    total_written = 0
    from psycopg2.extras import execute_values
    for code, n_funds in sourceable:
        nse_name = CODE_TO_NSE_NAME[code]
        cur.execute(
            "SELECT trade_date, close::float8, div_yield::float8 FROM nse_index_history "
            "WHERE index_name = %s AND close IS NOT NULL ORDER BY trade_date ASC",
            (nse_name,),
        )
        series = cur.fetchall()
        proxy = synth_proxy_tri(series)
        span = (f"{proxy[0][0]}..{proxy[-1][0]}" if proxy else "-")
        logger.info("PROXY %-30s nse=%-26s src=%-5s pts=%-5s span=%s funds=%s",
                    code, nse_name, len(series), len(proxy), span, n_funds)
        if not proxy:
            logger.warning("  -> 0 source rows for '%s' (check NSE index_name / backfill)", nse_name)
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
