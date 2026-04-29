"""
audit_data_completeness.py
==========================

Comprehensive per-ticker data completeness audit for the YieldIQ Neon DB.

Scope (read-only):
  - stocks (master)
  - financials (annual + quarterly)
  - market_metrics (latest snapshot)
  - ratio_history (latest snapshot — provides roe/roce/de_ratio/piotroski/etc.)
  - fair_value_history (FV time series)
  - daily_prices (price tail / staleness)
  - corporate_actions (dividends, splits, bonus)
  - analysis_cache (cached analysis payload)

Outputs:
  - reports/data_audit_<YYYY-MM-DD>.csv
        one row per active ticker, ~30 columns of populated/missing flags
  - reports/download_requirements_<YYYY-MM-DD>.json
        machine-readable summary that drives the next download pipeline
  - docs/ops/data_audit_<YYYY-MM-DD>.md
        human-readable summary report

Usage:
    DATABASE_URL="postgresql://..." python scripts/audit_data_completeness.py

Or read URL from an env file (line 2):
    python scripts/audit_data_completeness.py --env-file ../.env.local --env-line 2

Discipline:
  - READ-ONLY. No INSERT / UPDATE / DELETE statements anywhere.
  - No CACHE_VERSION change.
  - No DCF / scoring code touched.
  - Output runtime budget: 5-15 min. In practice: ~30-60s
    because we do per-table aggregations rather than per-ticker queries.

Coverage definitions:
  - "well-covered" annual financials: >=3 annual rows where revenue, pat,
     free_cash_flow, total_equity are ALL non-null.
  - "fresh" daily price: most-recent close within 5 trading days
     (i.e. 7 calendar days) of `today`.
  - "complete" ticker: passes ALL of:
        sector populated, industry populated, well-covered annual,
        latest market_metrics with pe_ratio AND market_cap_cr,
        latest ratio_history with roe AND piotroski_f_score,
        fresh daily price, analysis_cache present.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from dataclasses import dataclass, asdict, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine


# ---------- helpers ----------------------------------------------------------

def _read_env_file_line(path: str, line_no: int) -> str:
    p = Path(path)
    if not p.is_file():
        raise SystemExit(f"env file not found: {path}")
    lines = p.read_text(encoding="utf-8").splitlines()
    if len(lines) < line_no:
        raise SystemExit(f"env file has only {len(lines)} lines, asked for line {line_no}")
    raw = lines[line_no - 1].strip()
    # tolerate "DATABASE_URL=postgres://..." or bare url
    if "=" in raw and raw.split("=", 1)[0].isidentifier():
        raw = raw.split("=", 1)[1].strip().strip('"').strip("'")
    return raw


def _normalize_pg_url(url: str) -> str:
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    return url


def _today() -> date:
    return date.today()


# ---------- per-ticker fact ---------------------------------------------------

@dataclass
class TickerFacts:
    ticker: str
    company_name: str | None = None
    sector: str | None = None
    industry: str | None = None
    is_active: bool = True

    # market_metrics latest
    mm_market_cap_cr: float | None = None
    mm_pe_ratio: float | None = None
    mm_pb_ratio: float | None = None
    mm_dividend_yield: float | None = None
    mm_latest_trade_date: date | None = None

    # ratio_history latest (the place roe/roce/de/piotroski actually live)
    rh_roe: float | None = None
    rh_roce: float | None = None
    rh_de_ratio: float | None = None
    rh_piotroski: int | None = None
    rh_latest_period_end: date | None = None

    # financials
    fin_annual_rows: int = 0
    fin_quarterly_rows: int = 0
    fin_annual_with_revenue: int = 0
    fin_annual_with_pat: int = 0
    fin_annual_with_fcf: int = 0
    fin_annual_with_equity: int = 0
    fin_annual_inr: int = 0
    fin_annual_usd: int = 0
    fin_oldest_annual: date | None = None
    fin_latest_annual: date | None = None

    # FV history
    fv_total_rows: int = 0
    fv_rows_last_30d: int = 0
    fv_latest_date: date | None = None

    # daily prices
    dp_latest_date: date | None = None
    dp_rows: int = 0

    # corporate actions
    ca_dividend_count: int = 0
    ca_latest_dividend: date | None = None
    ca_split_or_bonus_count: int = 0

    # analysis cache
    ac_present: bool = False
    ac_cache_version: str | None = None
    ac_computed_at: datetime | None = None

    # ----- derived booleans -----
    @property
    def has_sector(self) -> bool: return bool(self.sector)
    @property
    def has_industry(self) -> bool: return bool(self.industry)
    @property
    def has_company_name(self) -> bool: return bool(self.company_name)
    @property
    def well_covered_annual(self) -> bool:
        # >=3 annual rows where ALL 4 critical fields are non-null
        # we approximate as: min(rev, pat, fcf, eq) >= 3
        return min(self.fin_annual_with_revenue,
                   self.fin_annual_with_pat,
                   self.fin_annual_with_fcf,
                   self.fin_annual_with_equity) >= 3
    @property
    def years_of_history(self) -> int:
        if not self.fin_oldest_annual or not self.fin_latest_annual:
            return 0
        return self.fin_latest_annual.year - self.fin_oldest_annual.year + 1
    @property
    def has_mm_pe(self) -> bool: return self.mm_pe_ratio is not None
    @property
    def has_mm_pb(self) -> bool: return self.mm_pb_ratio is not None
    @property
    def has_mm_mcap(self) -> bool: return self.mm_market_cap_cr is not None
    @property
    def has_rh_roe(self) -> bool: return self.rh_roe is not None
    @property
    def has_rh_roce(self) -> bool: return self.rh_roce is not None
    @property
    def has_rh_de(self) -> bool: return self.rh_de_ratio is not None
    @property
    def has_rh_piotroski(self) -> bool: return self.rh_piotroski is not None
    @property
    def fresh_price(self) -> bool:
        if not self.dp_latest_date:
            return False
        # 7 calendar days roughly == 5 trading days
        return (_today() - self.dp_latest_date).days <= 7

    def status(self) -> str:
        """Bucket: complete | partial | incomplete."""
        complete_criteria = [
            self.has_sector, self.has_industry,
            self.well_covered_annual,
            self.has_mm_pe, self.has_mm_mcap,
            self.has_rh_roe, self.has_rh_piotroski,
            self.fresh_price, self.ac_present,
        ]
        if all(complete_criteria):
            return "complete"
        # incomplete = missing core fundamentals (no annual financials or no sector)
        if not self.well_covered_annual or not self.has_sector:
            return "incomplete"
        return "partial"

    def missing_count(self) -> int:
        flags = [self.has_sector, self.has_industry,
                 self.well_covered_annual, self.has_mm_pe, self.has_mm_pb,
                 self.has_mm_mcap, self.has_rh_roe, self.has_rh_roce,
                 self.has_rh_de, self.has_rh_piotroski,
                 self.fresh_price, self.ac_present]
        return sum(1 for f in flags if not f)

    def to_csv_row(self) -> dict[str, Any]:
        d = asdict(self)
        # add booleans / derived
        d["status"] = self.status()
        d["missing_count"] = self.missing_count()
        d["has_sector"] = self.has_sector
        d["has_industry"] = self.has_industry
        d["well_covered_annual"] = self.well_covered_annual
        d["years_of_history"] = self.years_of_history
        d["has_mm_pe"] = self.has_mm_pe
        d["has_mm_pb"] = self.has_mm_pb
        d["has_mm_mcap"] = self.has_mm_mcap
        d["has_rh_roe"] = self.has_rh_roe
        d["has_rh_roce"] = self.has_rh_roce
        d["has_rh_de"] = self.has_rh_de
        d["has_rh_piotroski"] = self.has_rh_piotroski
        d["fresh_price"] = self.fresh_price
        return d


# ---------- bulk loaders -----------------------------------------------------

def load_stocks(engine: Engine) -> dict[str, TickerFacts]:
    sql = text("""
        SELECT ticker, company_name, sector, industry, is_active
          FROM stocks
         WHERE is_active = true
    """)
    out: dict[str, TickerFacts] = {}
    with engine.connect() as c:
        for row in c.execute(sql):
            t = row.ticker
            out[t] = TickerFacts(
                ticker=t,
                company_name=row.company_name,
                sector=row.sector,
                industry=row.industry,
                is_active=bool(row.is_active),
            )
    return out


def load_market_metrics(engine: Engine, facts: dict[str, TickerFacts]) -> None:
    sql = text("""
        SELECT DISTINCT ON (ticker)
               ticker, trade_date, market_cap_cr, pe_ratio, pb_ratio, dividend_yield
          FROM market_metrics
         ORDER BY ticker, trade_date DESC
    """)
    with engine.connect() as c:
        for row in c.execute(sql):
            f = facts.get(row.ticker)
            if not f:
                continue
            f.mm_latest_trade_date = row.trade_date
            f.mm_market_cap_cr = row.market_cap_cr
            f.mm_pe_ratio = row.pe_ratio
            f.mm_pb_ratio = row.pb_ratio
            f.mm_dividend_yield = row.dividend_yield


def load_ratio_history(engine: Engine, facts: dict[str, TickerFacts]) -> None:
    sql = text("""
        SELECT DISTINCT ON (ticker)
               ticker, period_end, roe, roce, de_ratio, piotroski_f_score
          FROM ratio_history
         WHERE period_type = 'annual'
         ORDER BY ticker, period_end DESC
    """)
    with engine.connect() as c:
        for row in c.execute(sql):
            f = facts.get(row.ticker)
            if not f:
                continue
            f.rh_latest_period_end = row.period_end
            f.rh_roe = row.roe
            f.rh_roce = row.roce
            f.rh_de_ratio = row.de_ratio
            f.rh_piotroski = row.piotroski_f_score


def load_financials(engine: Engine, facts: dict[str, TickerFacts]) -> None:
    sql = text("""
        SELECT
            ticker,
            SUM(CASE WHEN period_type='annual' THEN 1 ELSE 0 END) AS annual_rows,
            SUM(CASE WHEN period_type='quarterly' THEN 1 ELSE 0 END) AS q_rows,
            SUM(CASE WHEN period_type='annual' AND revenue IS NOT NULL THEN 1 ELSE 0 END) AS a_rev,
            SUM(CASE WHEN period_type='annual' AND pat IS NOT NULL THEN 1 ELSE 0 END) AS a_pat,
            SUM(CASE WHEN period_type='annual' AND free_cash_flow IS NOT NULL THEN 1 ELSE 0 END) AS a_fcf,
            SUM(CASE WHEN period_type='annual' AND total_equity IS NOT NULL THEN 1 ELSE 0 END) AS a_eq,
            SUM(CASE WHEN period_type='annual' AND currency='INR' THEN 1 ELSE 0 END) AS a_inr,
            SUM(CASE WHEN period_type='annual' AND currency='USD' THEN 1 ELSE 0 END) AS a_usd,
            MIN(CASE WHEN period_type='annual' THEN period_end END) AS oldest_annual,
            MAX(CASE WHEN period_type='annual' THEN period_end END) AS latest_annual
          FROM financials
         GROUP BY ticker
    """)
    with engine.connect() as c:
        for row in c.execute(sql):
            f = facts.get(row.ticker)
            if not f:
                continue
            f.fin_annual_rows = int(row.annual_rows or 0)
            f.fin_quarterly_rows = int(row.q_rows or 0)
            f.fin_annual_with_revenue = int(row.a_rev or 0)
            f.fin_annual_with_pat = int(row.a_pat or 0)
            f.fin_annual_with_fcf = int(row.a_fcf or 0)
            f.fin_annual_with_equity = int(row.a_eq or 0)
            f.fin_annual_inr = int(row.a_inr or 0)
            f.fin_annual_usd = int(row.a_usd or 0)
            f.fin_oldest_annual = row.oldest_annual
            f.fin_latest_annual = row.latest_annual


def load_fair_value_history(engine: Engine, facts: dict[str, TickerFacts]) -> None:
    cutoff = _today() - timedelta(days=30)
    sql = text("""
        SELECT
            ticker,
            COUNT(*) AS total,
            SUM(CASE WHEN date >= :cutoff THEN 1 ELSE 0 END) AS last30,
            MAX(date) AS latest
          FROM fair_value_history
         GROUP BY ticker
    """)
    with engine.connect() as c:
        for row in c.execute(sql, {"cutoff": cutoff}):
            f = facts.get(row.ticker)
            if not f:
                continue
            f.fv_total_rows = int(row.total or 0)
            f.fv_rows_last_30d = int(row.last30 or 0)
            f.fv_latest_date = row.latest


def load_daily_prices(engine: Engine, facts: dict[str, TickerFacts]) -> None:
    sql = text("""
        SELECT
            ticker,
            COUNT(*) AS rows,
            MAX(trade_date) AS latest
          FROM daily_prices
         GROUP BY ticker
    """)
    with engine.connect() as c:
        for row in c.execute(sql):
            f = facts.get(row.ticker)
            if not f:
                continue
            f.dp_rows = int(row.rows or 0)
            f.dp_latest_date = row.latest


def load_corporate_actions(engine: Engine, facts: dict[str, TickerFacts]) -> None:
    sql = text("""
        SELECT
            ticker,
            SUM(CASE WHEN action_type ILIKE '%DIVIDEND%' THEN 1 ELSE 0 END) AS div_count,
            MAX(CASE WHEN action_type ILIKE '%DIVIDEND%' THEN ex_date END) AS latest_div,
            SUM(CASE WHEN action_type ILIKE '%SPLIT%' OR action_type ILIKE '%BONUS%'
                     THEN 1 ELSE 0 END) AS sb_count
          FROM corporate_actions
         GROUP BY ticker
    """)
    with engine.connect() as c:
        for row in c.execute(sql):
            f = facts.get(row.ticker)
            if not f:
                continue
            f.ca_dividend_count = int(row.div_count or 0)
            f.ca_latest_dividend = row.latest_div
            f.ca_split_or_bonus_count = int(row.sb_count or 0)


def load_analysis_cache(engine: Engine, facts: dict[str, TickerFacts]) -> None:
    sql = text("""
        SELECT ticker, cache_version, computed_at
          FROM analysis_cache
    """)
    with engine.connect() as c:
        for row in c.execute(sql):
            f = facts.get(row.ticker)
            if not f:
                continue
            f.ac_present = True
            f.ac_cache_version = row.cache_version
            f.ac_computed_at = row.computed_at


# ---------- output -----------------------------------------------------------

CSV_FIELDS = [
    "ticker", "company_name", "sector", "industry", "is_active",
    "status", "missing_count",
    "has_sector", "has_industry",
    "well_covered_annual", "years_of_history",
    "fin_annual_rows", "fin_quarterly_rows",
    "fin_annual_with_revenue", "fin_annual_with_pat",
    "fin_annual_with_fcf", "fin_annual_with_equity",
    "fin_annual_inr", "fin_annual_usd",
    "fin_oldest_annual", "fin_latest_annual",
    "mm_latest_trade_date", "mm_market_cap_cr", "mm_pe_ratio", "mm_pb_ratio",
    "mm_dividend_yield",
    "has_mm_pe", "has_mm_pb", "has_mm_mcap",
    "rh_latest_period_end", "rh_roe", "rh_roce", "rh_de_ratio", "rh_piotroski",
    "has_rh_roe", "has_rh_roce", "has_rh_de", "has_rh_piotroski",
    "fv_total_rows", "fv_rows_last_30d", "fv_latest_date",
    "dp_rows", "dp_latest_date", "fresh_price",
    "ca_dividend_count", "ca_latest_dividend", "ca_split_or_bonus_count",
    "ac_present", "ac_cache_version", "ac_computed_at",
]


def write_csv(path: Path, facts: dict[str, TickerFacts]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=CSV_FIELDS, extrasaction="ignore")
        w.writeheader()
        for t in sorted(facts):
            w.writerow(facts[t].to_csv_row())


def _bucket_by_mcap(facts: dict[str, TickerFacts]) -> dict[str, list[TickerFacts]]:
    have_mcap = [f for f in facts.values() if f.mm_market_cap_cr is not None]
    have_mcap.sort(key=lambda f: f.mm_market_cap_cr or 0.0, reverse=True)

    no_mcap = [f for f in facts.values() if f.mm_market_cap_cr is None]

    buckets: dict[str, list[TickerFacts]] = {
        "top_100": have_mcap[:100],
        "top_500": have_mcap[:500],
        "mid_cap_100_to_1000_cr": [f for f in have_mcap
                                    if 100 <= (f.mm_market_cap_cr or 0) < 1000],
        "small_cap_under_100_cr": [f for f in have_mcap
                                    if (f.mm_market_cap_cr or 0) < 100],
        "no_mcap": no_mcap,
    }
    return buckets


def _segment_completeness(rows: list[TickerFacts]) -> dict[str, Any]:
    n = len(rows)
    if n == 0:
        return {"n": 0, "complete": 0, "partial": 0, "incomplete": 0}
    c = sum(1 for r in rows if r.status() == "complete")
    p = sum(1 for r in rows if r.status() == "partial")
    i = sum(1 for r in rows if r.status() == "incomplete")
    return {
        "n": n,
        "complete": c, "complete_pct": round(100 * c / n, 1),
        "partial": p, "partial_pct": round(100 * p / n, 1),
        "incomplete": i, "incomplete_pct": round(100 * i / n, 1),
    }


def build_download_requirements(facts: dict[str, TickerFacts]) -> dict[str, Any]:
    """Produce machine-readable summary that drives the next pipeline."""
    by_mcap = sorted(facts.values(),
                     key=lambda f: f.mm_market_cap_cr or 0.0,
                     reverse=True)
    sample_top = lambda preds, n=100: [
        f.ticker for f in by_mcap if preds(f)
    ][:n]

    fields_to_download: dict[str, dict[str, Any]] = {
        "sector": {
            "missing_count": sum(1 for f in facts.values() if not f.has_sector),
            "tickers_top_by_mcap": sample_top(lambda f: not f.has_sector),
        },
        "industry": {
            "missing_count": sum(1 for f in facts.values() if not f.has_industry),
            "tickers_top_by_mcap": sample_top(lambda f: not f.has_industry),
        },
        "annual_financials": {
            "missing_count": sum(1 for f in facts.values() if not f.well_covered_annual),
            "tickers_top_by_mcap": sample_top(lambda f: not f.well_covered_annual),
        },
        "market_metrics_pe_pb": {
            "missing_count": sum(1 for f in facts.values()
                                  if not f.has_mm_pe or not f.has_mm_pb),
            "tickers_top_by_mcap": sample_top(
                lambda f: not f.has_mm_pe or not f.has_mm_pb),
        },
        "ratio_history_roe_piotroski": {
            "missing_count": sum(1 for f in facts.values()
                                  if not f.has_rh_roe or not f.has_rh_piotroski),
            "tickers_top_by_mcap": sample_top(
                lambda f: not f.has_rh_roe or not f.has_rh_piotroski),
        },
        "fresh_daily_prices": {
            "missing_count": sum(1 for f in facts.values() if not f.fresh_price),
            "tickers_top_by_mcap": sample_top(lambda f: not f.fresh_price),
        },
        "analysis_cache": {
            "missing_count": sum(1 for f in facts.values() if not f.ac_present),
            "tickers_top_by_mcap": sample_top(lambda f: not f.ac_present),
        },
        "corporate_actions_dividends": {
            "missing_count": sum(1 for f in facts.values() if f.ca_dividend_count == 0),
            "tickers_top_by_mcap": sample_top(lambda f: f.ca_dividend_count == 0),
        },
    }

    # rough estimate of yfinance calls: one info() + one history() per ticker
    # that has any missing field, plus one financials() if annual gap.
    needs_info = set()
    needs_financials = set()
    needs_history = set()
    for f in facts.values():
        if not f.has_sector or not f.has_industry:
            needs_info.add(f.ticker)
        if not f.well_covered_annual:
            needs_financials.add(f.ticker)
        if not f.fresh_price:
            needs_history.add(f.ticker)
    estimated_calls = len(needs_info) + len(needs_financials) + len(needs_history)

    return {
        "total_tickers": len(facts),
        "fields_to_download": fields_to_download,
        "estimated_yfinance_calls": estimated_calls,
        "estimated_runtime_at_1rps": f"~{estimated_calls // 60} minutes",
        "estimated_runtime_at_5_workers_1rps_each": f"~{estimated_calls // 300} minutes",
        "needs_info_count": len(needs_info),
        "needs_financials_count": len(needs_financials),
        "needs_history_count": len(needs_history),
    }


def build_summary_md(facts: dict[str, TickerFacts],
                     dl: dict[str, Any],
                     audit_date: str) -> str:
    n = len(facts)
    statuses = [f.status() for f in facts.values()]
    n_complete = statuses.count("complete")
    n_partial = statuses.count("partial")
    n_incomplete = statuses.count("incomplete")

    # per-field gaps
    gaps = [
        ("sector",            sum(1 for f in facts.values() if not f.has_sector)),
        ("industry",          sum(1 for f in facts.values() if not f.has_industry)),
        ("company_name",      sum(1 for f in facts.values() if not f.has_company_name)),
        ("annual financials (>=3yr, all 4 fields)",
                              sum(1 for f in facts.values() if not f.well_covered_annual)),
        ("market_metrics pe_ratio",
                              sum(1 for f in facts.values() if not f.has_mm_pe)),
        ("market_metrics pb_ratio",
                              sum(1 for f in facts.values() if not f.has_mm_pb)),
        ("market_metrics market_cap_cr",
                              sum(1 for f in facts.values() if not f.has_mm_mcap)),
        ("ratio_history roe", sum(1 for f in facts.values() if not f.has_rh_roe)),
        ("ratio_history roce",sum(1 for f in facts.values() if not f.has_rh_roce)),
        ("ratio_history de_ratio",
                              sum(1 for f in facts.values() if not f.has_rh_de)),
        ("ratio_history piotroski_f_score",
                              sum(1 for f in facts.values() if not f.has_rh_piotroski)),
        ("daily_prices fresh (<=7d)",
                              sum(1 for f in facts.values() if not f.fresh_price)),
        ("analysis_cache present",
                              sum(1 for f in facts.values() if not f.ac_present)),
        ("corporate_actions dividends",
                              sum(1 for f in facts.values() if f.ca_dividend_count == 0)),
    ]

    buckets = _bucket_by_mcap(facts)

    # 20 worst-covered top-mcap names
    have_mcap = sorted([f for f in facts.values() if f.mm_market_cap_cr is not None],
                      key=lambda f: f.mm_market_cap_cr, reverse=True)
    top_500 = have_mcap[:500]
    top_500_sorted_by_gaps = sorted(top_500,
                                    key=lambda f: (-f.missing_count(),
                                                   -(f.mm_market_cap_cr or 0)))
    worst20 = top_500_sorted_by_gaps[:20]

    lines: list[str] = []
    lines.append(f"# YieldIQ — Data Completeness Audit ({audit_date})")
    lines.append("")
    lines.append(f"Read-only audit of **{n} active tickers** in Neon. "
                 f"Generated by `scripts/audit_data_completeness.py`.")
    lines.append("")
    lines.append("## Top-level coverage")
    lines.append("")
    lines.append(f"- Total active tickers: **{n}**")
    lines.append(f"- Complete (passes all coverage checks): "
                 f"**{n_complete} ({100*n_complete/n:.1f}%)**")
    lines.append(f"- Partial (>=1 field missing, has annual financials + sector): "
                 f"**{n_partial} ({100*n_partial/n:.1f}%)**")
    lines.append(f"- Incomplete (missing annual financials or sector — needs download): "
                 f"**{n_incomplete} ({100*n_incomplete/n:.1f}%)**")
    lines.append("")
    lines.append("## Per-field gaps")
    lines.append("")
    lines.append("| Field | Missing | % missing |")
    lines.append("|---|---:|---:|")
    for label, miss in gaps:
        lines.append(f"| {label} | {miss} | {100*miss/n:.1f}% |")
    lines.append("")
    lines.append("## Per-table gap summary")
    lines.append("")
    lines.append(f"- `stocks`: missing sector for {sum(1 for f in facts.values() if not f.has_sector)} tickers; "
                 f"missing industry for {sum(1 for f in facts.values() if not f.has_industry)} tickers.")
    lines.append(f"- `financials`: {sum(1 for f in facts.values() if f.fin_annual_rows == 0)} tickers have **zero** annual rows; "
                 f"{sum(1 for f in facts.values() if not f.well_covered_annual)} are not well-covered (<3 complete annual rows).")
    lines.append(f"- `market_metrics`: {sum(1 for f in facts.values() if not f.has_mm_mcap)} tickers have no market_cap_cr in latest snapshot; "
                 f"{sum(1 for f in facts.values() if not f.has_mm_pe)} have no PE in latest snapshot.")
    lines.append(f"- `ratio_history`: {sum(1 for f in facts.values() if not f.has_rh_roe)} have no ROE; "
                 f"{sum(1 for f in facts.values() if not f.has_rh_piotroski)} have no piotroski_f_score.")
    lines.append(f"- `fair_value_history`: {sum(1 for f in facts.values() if f.fv_total_rows == 0)} tickers have zero FV rows; "
                 f"{sum(1 for f in facts.values() if f.fv_rows_last_30d == 0)} have nothing in last 30 days.")
    lines.append(f"- `daily_prices`: {sum(1 for f in facts.values() if f.dp_rows == 0)} tickers have no price history; "
                 f"{sum(1 for f in facts.values() if not f.fresh_price)} are stale (>7d).")
    lines.append(f"- `corporate_actions`: {sum(1 for f in facts.values() if f.ca_dividend_count == 0)} tickers have no dividend records.")
    lines.append(f"- `analysis_cache`: {sum(1 for f in facts.values() if not f.ac_present)} tickers have no cached analysis.")
    lines.append("")
    lines.append("## By-segment breakdown")
    lines.append("")
    lines.append("| Segment | N | Complete | Partial | Incomplete |")
    lines.append("|---|---:|---:|---:|---:|")
    for name in ["top_100", "top_500", "mid_cap_100_to_1000_cr",
                 "small_cap_under_100_cr", "no_mcap"]:
        seg = _segment_completeness(buckets[name])
        if seg["n"] == 0:
            lines.append(f"| {name} | 0 | - | - | - |")
        else:
            lines.append(f"| {name} | {seg['n']} | "
                         f"{seg['complete']} ({seg['complete_pct']}%) | "
                         f"{seg['partial']} ({seg['partial_pct']}%) | "
                         f"{seg['incomplete']} ({seg['incomplete_pct']}%) |")
    lines.append("")
    lines.append("## Top 20 worst-covered names from the top-500 by market cap")
    lines.append("")
    lines.append("These names will be encountered first by users — they should be 100% complete.")
    lines.append("")
    lines.append("| Ticker | Company | MCap (Cr) | Status | Missing fields |")
    lines.append("|---|---|---:|---|---:|")
    for f in worst20:
        lines.append(f"| {f.ticker} | {f.company_name or ''} | "
                     f"{f.mm_market_cap_cr:.0f} | {f.status()} | "
                     f"{f.missing_count()} |")
    lines.append("")
    lines.append("## Download requirements summary")
    lines.append("")
    lines.append(f"- Estimated yfinance calls needed: **{dl['estimated_yfinance_calls']}**")
    lines.append(f"- At 1 rps single-worker: {dl['estimated_runtime_at_1rps']}")
    lines.append(f"- At 5 workers @ 1 rps each: {dl['estimated_runtime_at_5_workers_1rps_each']}")
    lines.append(f"- Tickers needing yfinance `.info` (sector/industry): {dl['needs_info_count']}")
    lines.append(f"- Tickers needing financials reload: {dl['needs_financials_count']}")
    lines.append(f"- Tickers needing fresh price history: {dl['needs_history_count']}")
    lines.append("")
    lines.append("Per-field detail (missing count + top-100 by mcap):")
    lines.append("")
    for k, v in dl["fields_to_download"].items():
        lines.append(f"- **{k}**: {v['missing_count']} missing")
    lines.append("")
    lines.append("## Files produced")
    lines.append("")
    lines.append(f"- `reports/data_audit_{audit_date}.csv` — per-ticker detail")
    lines.append(f"- `reports/download_requirements_{audit_date}.json` — drives next pipeline")
    lines.append(f"- `docs/ops/data_audit_{audit_date}.md` — this document")
    lines.append("")
    return "\n".join(lines)


# ---------- main -------------------------------------------------------------

def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--env-file", default=None,
                    help="Path to env file; reads URL from --env-line.")
    ap.add_argument("--env-line", type=int, default=2,
                    help="1-based line number containing the URL (default: 2).")
    ap.add_argument("--out-dir", default=".", help="Project root for reports/ and docs/ops/.")
    ap.add_argument("--date", default=None, help="Override audit date (YYYY-MM-DD).")
    args = ap.parse_args(argv)

    url = os.environ.get("DATABASE_URL", "")
    if not url and args.env_file:
        url = _read_env_file_line(args.env_file, args.env_line)
    if not url:
        print("ERROR: no DATABASE_URL (set env var or pass --env-file).", file=sys.stderr)
        return 2
    url = _normalize_pg_url(url)

    audit_date = args.date or _today().isoformat()
    root = Path(args.out_dir).resolve()
    csv_path = root / "reports" / f"data_audit_{audit_date}.csv"
    json_path = root / "reports" / f"download_requirements_{audit_date}.json"
    md_path = root / "docs" / "ops" / f"data_audit_{audit_date}.md"

    t0 = datetime.utcnow()
    print(f"[audit] connecting to Neon...", file=sys.stderr)
    engine = create_engine(url, pool_pre_ping=True)

    print(f"[audit] loading active stocks...", file=sys.stderr)
    facts = load_stocks(engine)
    print(f"[audit] {len(facts)} active tickers loaded.", file=sys.stderr)

    for label, fn in [
        ("market_metrics", load_market_metrics),
        ("ratio_history", load_ratio_history),
        ("financials", load_financials),
        ("fair_value_history", load_fair_value_history),
        ("daily_prices", load_daily_prices),
        ("corporate_actions", load_corporate_actions),
        ("analysis_cache", load_analysis_cache),
    ]:
        ts = datetime.utcnow()
        print(f"[audit] loading {label}...", file=sys.stderr)
        fn(engine, facts)
        print(f"[audit]  done in {(datetime.utcnow()-ts).total_seconds():.1f}s", file=sys.stderr)

    print(f"[audit] writing CSV -> {csv_path}", file=sys.stderr)
    write_csv(csv_path, facts)

    print(f"[audit] computing download requirements", file=sys.stderr)
    dl = build_download_requirements(facts)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    with json_path.open("w", encoding="utf-8") as fh:
        json.dump(dl, fh, indent=2, default=str)
    print(f"[audit] wrote -> {json_path}", file=sys.stderr)

    print(f"[audit] writing summary report -> {md_path}", file=sys.stderr)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(build_summary_md(facts, dl, audit_date), encoding="utf-8")

    elapsed = (datetime.utcnow() - t0).total_seconds()
    print(f"[audit] done in {elapsed:.1f}s", file=sys.stderr)

    # quick top-line to stdout for shell composability
    statuses = [f.status() for f in facts.values()]
    print(json.dumps({
        "total": len(facts),
        "complete": statuses.count("complete"),
        "partial": statuses.count("partial"),
        "incomplete": statuses.count("incomplete"),
        "csv": str(csv_path),
        "json": str(json_path),
        "md": str(md_path),
        "elapsed_sec": round(elapsed, 1),
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
