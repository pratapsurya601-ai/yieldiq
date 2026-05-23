"""
audit_ar_coverage.py
====================

Phase H-audit (Block II): read-only diagnostic for annual-report
ingestion coverage.

Answers: "Is the planned 2000-AR (top-200 × 10y) LLM-extract backfill
worth running, and what's the per-AR token + USD cost?"

Universe:
  * Canary v3 (333 tickers from scripts/canary_universe_180.json,
    legacy filename) ∪ top-200 by market cap.

Outputs:
  * reports/ar_coverage_<YYYY-MM-DD>.csv (per-ticker counts)
  * reports/ar_coverage_summary_<YYYY-MM-DD>.json
  * docs/diagnostics/phase-h-ar-coverage-<YYYY-MM-DD>.md
  * reports/ar_sample_extraction_<YYYY-MM-DD>.json (10-AR PDF probe)

Verdict gates Phase H-schema / H-extract:
  * HARD STOP if <30% of top-200 have ANY AR row in
    company_annual_reports (universe is too sparse to bother).
  * HARD STOP if mean estimated cost/AR exceeds $0.50
    (2000-AR backfill would cost ≥$1000 — re-scope).
  * PROCEED WITH CAUTION if either signal is in the warning band.
  * PROCEED otherwise.

Discipline:
  * READ-ONLY. No INSERT/UPDATE/DELETE.
  * No CACHE_VERSION change.
  * No score/DCF code touched.
  * The 10-AR PDF probe downloads bytes into memory only; nothing
    written to disk other than the report files above.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import logging
import os
import random
import sys
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any, Optional

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

logger = logging.getLogger("yieldiq.audit.ar")
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")

REPO_ROOT = Path(__file__).resolve().parents[1]
CANARY_PATH = REPO_ROOT / "scripts" / "canary_universe_180.json"
REPORTS_DIR = REPO_ROOT / "reports"
DOCS_DIR = REPO_ROOT / "docs" / "diagnostics"

# Pricing assumption mirrors concall_intel_service: Sonnet 4.5
# at $3/Mtoken input + $15/Mtoken output. Chunked AR extraction
# is dominated by input tokens (PDFs are large, JSON output is
# moderate ~1000 tokens), so this is the right back-of-envelope.
SONNET_INPUT_USD_PER_MTOKEN = 3.0
SONNET_OUTPUT_USD_PER_MTOKEN = 15.0
ASSUMED_OUTPUT_TOKENS_PER_AR = 1500  # conservative for chunked merge

# Coverage thresholds for the verdict block.
TOP200_MIN_COVERAGE_PCT = 30.0   # hard stop
TOP200_WARN_COVERAGE_PCT = 50.0  # caution band
COST_PER_AR_HARD_STOP_USD = 0.50
COST_PER_AR_WARN_USD = 0.30

PDF_SAMPLE_SIZE = 10
PDF_MAX_BYTES = 8 * 1024 * 1024  # AR PDFs are bigger than concalls
PDF_DOWNLOAD_TIMEOUT_S = 60


# ---------- env / engine helpers --------------------------------------------

def _read_env_line(path: str, line_no: int) -> str:
    p = Path(path)
    if not p.is_file():
        raise SystemExit(f"env file not found: {path}")
    lines = p.read_text(encoding="utf-8").splitlines()
    if len(lines) < line_no:
        raise SystemExit(f"env file has only {len(lines)} lines; asked for {line_no}")
    raw = lines[line_no - 1].strip()
    if "=" in raw and raw.split("=", 1)[0].isidentifier():
        raw = raw.split("=", 1)[1].strip().strip('"').strip("'")
    return raw


def _normalize_pg_url(url: str) -> str:
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    return url


def _build_engine(args) -> Engine:
    url = os.environ.get("DATABASE_URL")
    if not url and args.env_file:
        url = _read_env_line(args.env_file, args.env_line)
    if not url:
        raise SystemExit("DATABASE_URL not set and no --env-file given")
    return create_engine(_normalize_pg_url(url), pool_pre_ping=True)


# ---------- universe ---------------------------------------------------------

def _load_canary_tickers() -> list[str]:
    raw = json.loads(CANARY_PATH.read_text(encoding="utf-8"))
    out: list[str] = []
    stocks_v3 = raw.get("stocks")
    if isinstance(stocks_v3, list):
        for s in stocks_v3:
            sym = s.get("symbol") if isinstance(s, dict) else None
            if sym:
                out.append(sym)
    else:
        for k, v in raw.items():
            if k.startswith("_"):
                continue
            if isinstance(v, list):
                out.extend([x for x in v if isinstance(x, str)])
    seen: set[str] = set()
    deduped: list[str] = []
    for t in out:
        if t not in seen:
            seen.add(t)
            deduped.append(t)
    return deduped


def _load_top_n_by_mcap(engine: Engine, n: int) -> list[str]:
    sql = text(
        "SELECT s.ticker "
        "FROM stocks s "
        "LEFT JOIN market_metrics mm ON mm.ticker = s.ticker "
        "WHERE s.is_active = TRUE "
        "GROUP BY s.ticker "
        "ORDER BY COALESCE(MAX(mm.market_cap_cr), 0) DESC "
        "LIMIT :n"
    )
    with engine.connect() as c:
        return [r[0] for r in c.execute(sql, {"n": n}).fetchall() if r and r[0]]


# ---------- bulk loaders -----------------------------------------------------

def load_per_ticker_counts(
    engine: Engine, universe: list[str]
) -> dict[str, dict[str, Any]]:
    """Per-ticker AR counts + source breakdown + FY range.

    Counts rows in `company_annual_reports` (the rich extraction
    table — migration 027). We bucket by source to feed the source
    breakdown table in the markdown report.
    """
    sql = text("""
        SELECT
          ticker,
          COUNT(*)                                                  AS total,
          SUM(CASE WHEN fiscal_year >= EXTRACT(YEAR FROM CURRENT_DATE) - 1
                   THEN 1 ELSE 0 END)                               AS last_1y,
          SUM(CASE WHEN fiscal_year >= EXTRACT(YEAR FROM CURRENT_DATE) - 5
                   THEN 1 ELSE 0 END)                               AS last_5y,
          SUM(CASE WHEN fiscal_year >= EXTRACT(YEAR FROM CURRENT_DATE) - 10
                   THEN 1 ELSE 0 END)                               AS last_10y,
          SUM(CASE WHEN source = 'bse' THEN 1 ELSE 0 END)           AS src_bse,
          SUM(CASE WHEN source = 'nse' THEN 1 ELSE 0 END)           AS src_nse,
          SUM(CASE WHEN source = 'manual' THEN 1 ELSE 0 END)        AS src_manual,
          SUM(CASE WHEN source = 'company_website' THEN 1 ELSE 0 END) AS src_cw,
          SUM(CASE WHEN ar_url IS NOT NULL AND ar_url <> '' THEN 1 ELSE 0 END) AS with_url,
          MIN(fiscal_year)                                          AS oldest_fy,
          MAX(fiscal_year)                                          AS newest_fy
        FROM company_annual_reports
        WHERE ticker = ANY(:tickers)
        GROUP BY ticker
    """)

    out: dict[str, dict[str, Any]] = {}
    with engine.connect() as c:
        rows = c.execute(sql, {"tickers": universe}).fetchall()

    for r in rows:
        out[r.ticker] = {
            "total": int(r.total or 0),
            "last_1y": int(r.last_1y or 0),
            "last_5y": int(r.last_5y or 0),
            "last_10y": int(r.last_10y or 0),
            "src_bse": int(r.src_bse or 0),
            "src_nse": int(r.src_nse or 0),
            "src_manual": int(r.src_manual or 0),
            "src_cw": int(r.src_cw or 0),
            "with_url": int(r.with_url or 0),
            "oldest_fy": int(r.oldest_fy) if r.oldest_fy else None,
            "newest_fy": int(r.newest_fy) if r.newest_fy else None,
        }

    for t in universe:
        out.setdefault(t, {
            "total": 0, "last_1y": 0, "last_5y": 0, "last_10y": 0,
            "src_bse": 0, "src_nse": 0, "src_manual": 0, "src_cw": 0,
            "with_url": 0, "oldest_fy": None, "newest_fy": None,
        })
    return out


def load_ticker_meta(engine: Engine, universe: list[str]) -> dict[str, dict[str, Any]]:
    sql = text("""
        SELECT s.ticker, s.company_name, s.sector,
               COALESCE(MAX(mm.market_cap_cr), 0) AS mcap_cr
          FROM stocks s
          LEFT JOIN market_metrics mm ON mm.ticker = s.ticker
         WHERE s.ticker = ANY(:tickers)
         GROUP BY s.ticker, s.company_name, s.sector
    """)
    out: dict[str, dict[str, Any]] = {}
    with engine.connect() as c:
        for r in c.execute(sql, {"tickers": universe}).fetchall():
            out[r.ticker] = {
                "company_name": r.company_name,
                "sector": r.sector,
                "mcap_cr": float(r.mcap_cr or 0),
            }
    for t in universe:
        out.setdefault(t, {"company_name": None, "sector": None, "mcap_cr": 0.0})
    return out


def load_url_samples(
    engine: Engine, universe: list[str], k: int = PDF_SAMPLE_SIZE,
) -> list[dict[str, Any]]:
    """Pick k random ARs that have a non-null ar_url for the PDF probe.

    Deterministic seed for reproducibility across reruns on the same
    DB snapshot.
    """
    sql = text("""
        SELECT id, ticker, fiscal_year, source, ar_url
          FROM company_annual_reports
         WHERE ticker = ANY(:tickers)
           AND ar_url IS NOT NULL
           AND ar_url <> ''
    """)
    with engine.connect() as c:
        rows = c.execute(sql, {"tickers": universe}).fetchall()
    candidates = [
        {"id": int(r.id), "ticker": r.ticker, "fiscal_year": int(r.fiscal_year),
         "source": r.source, "ar_url": r.ar_url}
        for r in rows
    ]
    if not candidates:
        return []
    random.seed(20260526)
    return random.sample(candidates, min(k, len(candidates)))


# ---------- PDF probe -------------------------------------------------------

def probe_ar_pdf(sample: dict[str, Any]) -> dict[str, Any]:
    """Download a single AR PDF and estimate its token count + USD cost.

    Returns a result dict with status ('ok' | 'fetch_failed' |
    'parse_failed' | 'oversize') and (if ok) extracted_chars,
    estimated_tokens, estimated_input_cost_usd, estimated_total_cost_usd.

    Best-effort: any network or parse failure is captured in the
    result dict — the script keeps going for the remaining samples.
    """
    result: dict[str, Any] = {
        "id": sample["id"],
        "ticker": sample["ticker"],
        "fiscal_year": sample["fiscal_year"],
        "source": sample["source"],
        "ar_url": sample["ar_url"],
        "status": "ok",
        "byte_size": None,
        "extracted_chars": None,
        "estimated_tokens": None,
        "estimated_input_cost_usd": None,
        "estimated_total_cost_usd": None,
        "error": None,
    }

    try:
        import httpx  # noqa: WPS433 (deferred import — only needed for probe)
    except ImportError as exc:
        result["status"] = "fetch_failed"
        result["error"] = f"httpx not installed: {exc}"
        return result

    try:
        with httpx.Client(
            timeout=PDF_DOWNLOAD_TIMEOUT_S,
            follow_redirects=True,
            headers={"User-Agent": "YieldIQ-AR-Audit/1.0"},
        ) as client:
            resp = client.get(sample["ar_url"])
            resp.raise_for_status()
            content = resp.content
    except Exception as exc:
        result["status"] = "fetch_failed"
        result["error"] = str(exc)[:200]
        return result

    result["byte_size"] = len(content)
    if len(content) > PDF_MAX_BYTES:
        result["status"] = "oversize"
        result["error"] = (
            f"PDF is {len(content)} bytes (cap {PDF_MAX_BYTES})"
        )
        return result

    try:
        import pypdf  # noqa: WPS433
        reader = pypdf.PdfReader(io.BytesIO(content))
        pages = []
        for page in reader.pages:
            try:
                pages.append(page.extract_text() or "")
            except Exception:
                pages.append("")
        text_blob = "\n".join(pages)
    except Exception as exc:
        result["status"] = "parse_failed"
        result["error"] = str(exc)[:200]
        return result

    extracted_chars = len(text_blob)
    # Anthropic tokenisation: rough rule-of-thumb is 4 chars / token
    # for English. Slightly pessimistic for Indian-English filings
    # which include numeric tables (more tokens per char) — round up.
    est_tokens = max(1, int(extracted_chars / 3.5))
    input_cost = est_tokens / 1_000_000.0 * SONNET_INPUT_USD_PER_MTOKEN
    output_cost = (
        ASSUMED_OUTPUT_TOKENS_PER_AR / 1_000_000.0
        * SONNET_OUTPUT_USD_PER_MTOKEN
    )
    total_cost = input_cost + output_cost

    result["extracted_chars"] = extracted_chars
    result["estimated_tokens"] = est_tokens
    result["estimated_input_cost_usd"] = round(input_cost, 4)
    result["estimated_total_cost_usd"] = round(total_cost, 4)
    return result


# ---------- summary / verdict -----------------------------------------------

def _hist(values: list[int], buckets: list[tuple[int, Optional[int], str]]) -> dict[str, int]:
    out: dict[str, int] = {label: 0 for _, _, label in buckets}
    for v in values:
        for lo, hi, label in buckets:
            if v >= lo and (hi is None or v < hi):
                out[label] += 1
                break
    return out


def build_summary(
    top200: list[str], canary: list[str], union_universe: list[str],
    counts: dict[str, dict[str, Any]],
    probe_results: list[dict[str, Any]],
) -> dict[str, Any]:
    def stats_for(group: list[str]) -> dict[str, Any]:
        totals = [counts[t]["total"] for t in group]
        in_5y = [counts[t]["last_5y"] for t in group]
        in_10y = [counts[t]["last_10y"] for t in group]
        any_1y = sum(1 for t in group if counts[t]["last_1y"] > 0)
        any_5y = sum(1 for t in group if counts[t]["last_5y"] > 0)
        any_10y = sum(1 for t in group if counts[t]["last_10y"] > 0)
        any_total = sum(1 for v in totals if v > 0)
        meets_5y = sum(1 for v in in_5y if v >= 5)
        meets_10y = sum(1 for v in in_10y if v >= 10)
        return {
            "size": len(group),
            "any_row": any_total,
            "any_row_pct": round(100.0 * any_total / max(1, len(group)), 1),
            "any_in_1y": any_1y,
            "any_in_5y": any_5y,
            "any_in_10y": any_10y,
            "any_in_1y_pct": round(100.0 * any_1y / max(1, len(group)), 1),
            "any_in_5y_pct": round(100.0 * any_5y / max(1, len(group)), 1),
            "any_in_10y_pct": round(100.0 * any_10y / max(1, len(group)), 1),
            "meets_5y_threshold": meets_5y,
            "meets_10y_threshold": meets_10y,
            "meets_5y_pct": round(100.0 * meets_5y / max(1, len(group)), 1),
            "meets_10y_pct": round(100.0 * meets_10y / max(1, len(group)), 1),
            "hist_10y": _hist(in_10y, [
                (0, 1, "0"),
                (1, 3, "1-2"),
                (3, 6, "3-5"),
                (6, 9, "6-8"),
                (9, 11, "9-10"),
                (11, None, "11+"),
            ]),
        }

    # Source breakdown across the union universe.
    src_totals = Counter()
    for t in union_universe:
        src_totals["bse"] += counts[t]["src_bse"]
        src_totals["nse"] += counts[t]["src_nse"]
        src_totals["manual"] += counts[t]["src_manual"]
        src_totals["company_website"] += counts[t]["src_cw"]
    total_rows = sum(src_totals.values())

    sources = {
        k: {"count": v,
            "pct": round(100.0 * v / max(1, total_rows), 1)}
        for k, v in src_totals.items()
    }

    # Probe roll-up.
    ok_probes = [p for p in probe_results if p["status"] == "ok"]
    fail_probes = [p for p in probe_results if p["status"] != "ok"]
    if ok_probes:
        mean_cost = sum(p["estimated_total_cost_usd"] for p in ok_probes) / len(ok_probes)
        max_cost = max(p["estimated_total_cost_usd"] for p in ok_probes)
        min_cost = min(p["estimated_total_cost_usd"] for p in ok_probes)
        mean_tokens = sum(p["estimated_tokens"] for p in ok_probes) / len(ok_probes)
        mean_chars = sum(p["extracted_chars"] for p in ok_probes) / len(ok_probes)
        mean_bytes = sum(p["byte_size"] for p in ok_probes) / len(ok_probes)
    else:
        mean_cost = max_cost = min_cost = 0.0
        mean_tokens = mean_chars = mean_bytes = 0.0

    probe_summary = {
        "sample_size": len(probe_results),
        "n_ok": len(ok_probes),
        "n_failed": len(fail_probes),
        "mean_cost_per_ar_usd": round(mean_cost, 4),
        "max_cost_per_ar_usd": round(max_cost, 4),
        "min_cost_per_ar_usd": round(min_cost, 4),
        "mean_tokens_per_ar": int(mean_tokens),
        "mean_extracted_chars": int(mean_chars),
        "mean_pdf_bytes": int(mean_bytes),
        "projected_2000_ar_cost_usd": round(mean_cost * 2000, 2),
        "failure_modes": Counter(p["status"] for p in fail_probes),
    }

    # Verdict
    top200_stats = stats_for(top200)
    coverage_pct = top200_stats["any_row_pct"]

    if coverage_pct < TOP200_MIN_COVERAGE_PCT:
        verdict = "HARD STOP"
        verdict_reason = (
            f"Only {top200_stats['any_row']} / {top200_stats['size']} "
            f"({coverage_pct}%) of top-200 have ANY AR row in "
            f"company_annual_reports. Below the {TOP200_MIN_COVERAGE_PCT}% "
            f"bar — the universe is too sparse to justify the LLM-extract "
            f"backfill. A separate phase must populate AR URLs first."
        )
    elif mean_cost > COST_PER_AR_HARD_STOP_USD:
        verdict = "HARD STOP"
        verdict_reason = (
            f"Mean estimated cost per AR is ${mean_cost:.4f} — exceeds "
            f"the ${COST_PER_AR_HARD_STOP_USD:.2f} hard-stop. A 2000-AR "
            f"backfill would cost ~${mean_cost * 2000:.0f}. Re-scope to "
            f"a smaller universe, switch to Haiku, or rework the chunk "
            f"strategy before proceeding."
        )
    elif (
        coverage_pct < TOP200_WARN_COVERAGE_PCT
        or mean_cost > COST_PER_AR_WARN_USD
    ):
        verdict = "PROCEED WITH CAUTION"
        verdict_reason = (
            f"Top-200 coverage at {coverage_pct}% (warn <{TOP200_WARN_COVERAGE_PCT}%); "
            f"mean cost/AR ${mean_cost:.4f} (warn >${COST_PER_AR_WARN_USD:.2f}). "
            f"Ship schema + extractor but narrow the initial batch to the "
            f"densest tickers and watch the cost meter closely."
        )
    else:
        verdict = "PROCEED"
        verdict_reason = (
            f"{coverage_pct}% of top-200 have AR rows; mean cost per AR "
            f"is ${mean_cost:.4f}; 2000-AR projection ${mean_cost * 2000:.0f}. "
            f"Backfill is economically justified — proceed to H-schema."
        )

    return {
        "canary": stats_for(canary),
        "top200": top200_stats,
        "union": stats_for(union_universe),
        "sources": sources,
        "probe": probe_summary,
        "verdict": verdict,
        "verdict_reason": verdict_reason,
        "thresholds": {
            "top200_min_coverage_pct": TOP200_MIN_COVERAGE_PCT,
            "top200_warn_coverage_pct": TOP200_WARN_COVERAGE_PCT,
            "cost_per_ar_hard_stop_usd": COST_PER_AR_HARD_STOP_USD,
            "cost_per_ar_warn_usd": COST_PER_AR_WARN_USD,
        },
    }


# ---------- writers ---------------------------------------------------------

def write_per_ticker_csv(
    path: Path, universe: list[str],
    counts: dict[str, dict[str, Any]],
    meta: dict[str, dict[str, Any]],
    canary_set: set[str], top200_set: set[str],
) -> None:
    fields = [
        "ticker", "company_name", "sector", "mcap_cr",
        "in_canary", "in_top200",
        "total", "last_1y", "last_5y", "last_10y",
        "with_url", "src_bse", "src_nse", "src_manual", "src_cw",
        "oldest_fy", "newest_fy",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for t in sorted(universe):
            c = counts[t]
            m = meta[t]
            w.writerow({
                "ticker": t,
                "company_name": m["company_name"],
                "sector": m["sector"],
                "mcap_cr": round(m["mcap_cr"], 2),
                "in_canary": t in canary_set,
                "in_top200": t in top200_set,
                "total": c["total"],
                "last_1y": c["last_1y"],
                "last_5y": c["last_5y"],
                "last_10y": c["last_10y"],
                "with_url": c["with_url"],
                "src_bse": c["src_bse"],
                "src_nse": c["src_nse"],
                "src_manual": c["src_manual"],
                "src_cw": c["src_cw"],
                "oldest_fy": c["oldest_fy"],
                "newest_fy": c["newest_fy"],
            })


def write_markdown_report(
    path: Path, today: date, summary: dict[str, Any],
    csv_path: Path, json_path: Path, probe_path: Path,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    canary = summary["canary"]
    top200 = summary["top200"]
    union = summary["union"]
    sources = summary["sources"]
    probe = summary["probe"]

    def render_hist(h: dict[str, int]) -> str:
        lines = ["| Bucket (10y AR count) | Tickers |", "|---|---|"]
        for k, v in h.items():
            lines.append(f"| {k} | {v} |")
        return "\n".join(lines)

    src_table_rows = [
        f"| {k} | {v['count']} | {v['pct']}% |"
        for k, v in sources.items()
    ]
    src_table = (
        "| Source | Rows | Share |\n|---|---|---|\n"
        + "\n".join(src_table_rows)
    )

    fail_modes = probe.get("failure_modes") or {}
    fail_modes_str = (
        ", ".join(f"{k}={v}" for k, v in fail_modes.items())
        if fail_modes else "_none_"
    )

    body = f"""# Phase H-audit -- Annual Report Coverage Diagnostic ({today.isoformat()})

**Status:** read-only diagnostic. No code or data changes.
**Author:** Phase H dispatch (Block II)
**Purpose:** evidence base to gate Phase H-schema / H-extract /
H-frontend / H-operator-workflow.

---

## 1. Why this audit exists

Phase H mirrors the Phase G concall pattern but for ANNUAL REPORTS:
prompt-cached Anthropic extraction of structured signals (segment
revenue/EBIT, capex commitments, related-party transactions,
auditor flags, contingent liabilities, management outlook) from the
AR PDFs already indexed by `data_pipeline/sources/nse_annual_reports.py`.

AR PDFs are 5-50x larger than concall PDFs (100-300 pages vs
15-30). Before committing budget to a top-200 x 10y (~2000 AR)
backfill, we need to know:

1. How many tickers in top-200 / canary-333 already have AR rows
   in `company_annual_reports` (migration 027)?
2. What's the source mix (BSE / NSE / manual seed)?
3. What does a typical AR PDF cost to extract end-to-end via
   Anthropic Sonnet 4.5 with prompt caching?

---

## 2. Universe

| Bucket | Count |
|---|---|
| Canary v3 (333) | {canary['size']} |
| Top 200 by market cap | {top200['size']} |
| Union (deduped) | {union['size']} |

---

## 3. Coverage headline

| Group | Any row | Any in 1y | Any in 5y | Any in 10y | Meets 5y >= 5 | Meets 10y >= 10 |
|---|---|---|---|---|---|---|
| Canary v3 | {canary['any_row']} ({canary['any_row_pct']}%) | {canary['any_in_1y']} ({canary['any_in_1y_pct']}%) | {canary['any_in_5y']} ({canary['any_in_5y_pct']}%) | {canary['any_in_10y']} ({canary['any_in_10y_pct']}%) | {canary['meets_5y_threshold']} ({canary['meets_5y_pct']}%) | {canary['meets_10y_threshold']} ({canary['meets_10y_pct']}%) |
| Top-200 | {top200['any_row']} ({top200['any_row_pct']}%) | {top200['any_in_1y']} ({top200['any_in_1y_pct']}%) | {top200['any_in_5y']} ({top200['any_in_5y_pct']}%) | {top200['any_in_10y']} ({top200['any_in_10y_pct']}%) | {top200['meets_5y_threshold']} ({top200['meets_5y_pct']}%) | {top200['meets_10y_threshold']} ({top200['meets_10y_pct']}%) |
| Union | {union['any_row']} ({union['any_row_pct']}%) | {union['any_in_1y']} ({union['any_in_1y_pct']}%) | {union['any_in_5y']} ({union['any_in_5y_pct']}%) | {union['any_in_10y']} ({union['any_in_10y_pct']}%) | {union['meets_5y_threshold']} ({union['meets_5y_pct']}%) | {union['meets_10y_threshold']} ({union['meets_10y_pct']}%) |

### 10-year AR-count distribution (top-200)

{render_hist(top200['hist_10y'])}

---

## 4. Source breakdown (union universe)

{src_table}

If BSE rows dominate but the planned extractor only knows how to
fetch from NSE (per `data_pipeline/sources/nse_annual_reports.py`),
that gap is fine for H-extract -- the URLs are already stored in
`company_annual_reports.ar_url` and the extractor downloads
whichever URL is present.

---

## 5. PDF probe -- {probe['n_ok']} / {probe['sample_size']} samples extracted end-to-end

| Metric | Value |
|---|---|
| Sample size | {probe['sample_size']} |
| Successful end-to-end | {probe['n_ok']} |
| Failed | {probe['n_failed']} ({fail_modes_str}) |
| Mean PDF size | {probe['mean_pdf_bytes']:,} bytes |
| Mean extracted chars | {probe['mean_extracted_chars']:,} |
| Mean estimated input tokens | {probe['mean_tokens_per_ar']:,} |
| Min cost per AR (USD) | ${probe['min_cost_per_ar_usd']} |
| Mean cost per AR (USD) | ${probe['mean_cost_per_ar_usd']} |
| Max cost per AR (USD) | ${probe['max_cost_per_ar_usd']} |
| Projected 2000-AR cost (USD) | ${probe['projected_2000_ar_cost_usd']} |

Pricing assumption: Sonnet 4.5 @ ${SONNET_INPUT_USD_PER_MTOKEN}/Mtoken input,
${SONNET_OUTPUT_USD_PER_MTOKEN}/Mtoken output. Assumed output tokens per
AR: {ASSUMED_OUTPUT_TOKENS_PER_AR} (chunked merge of segment / capex / RPT
/ auditor sections). Prompt caching is NOT modelled in this projection
-- real spend will be lower once the cache warms up.

Raw probe JSON: `{probe_path.as_posix()}`.

---

## 6. Verdict

**{summary['verdict']}**

{summary['verdict_reason']}

### Decision matrix

| Verdict | Action |
|---|---|
| PROCEED | Ship H-schema, H-extract, H-frontend, H-operator-workflow as planned. |
| PROCEED WITH CAUTION | Ship all four, but narrow the initial batch (operator default `--max-rows`) to the densest tickers and run the cost meter aggressively. |
| HARD STOP | Open a separate phase to either backfill AR URLs (if coverage is the blocker) or switch model / chunking strategy (if cost is the blocker). Pause H-schema. |

Thresholds: hard-stop coverage <{TOP200_MIN_COVERAGE_PCT}%, warn <{TOP200_WARN_COVERAGE_PCT}%;
hard-stop cost/AR >${COST_PER_AR_HARD_STOP_USD:.2f}, warn >${COST_PER_AR_WARN_USD:.2f}.

---

## 7. Outputs of this run

* `{csv_path.as_posix()}` -- per-ticker counts ({union['size']} rows).
* `{json_path.as_posix()}` -- machine-readable summary.
* `{probe_path.as_posix()}` -- 10-AR PDF probe raw results.
* This markdown -- human-readable diagnostic.

## 8. Reproducibility

```
python scripts/audit_ar_coverage.py \\
    --env-file .env.local --env-line 2
```

Output paths embed the run date; reruns against a different DB
snapshot write new files without overwriting today's. The PDF probe
uses a fixed random seed (20260526) so the same DB snapshot picks
the same {PDF_SAMPLE_SIZE} URLs across runs.
"""
    path.write_text(body, encoding="utf-8")


# ---------- main ------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--env-file", default=None,
                    help="Path to env file containing DATABASE_URL")
    ap.add_argument("--env-line", type=int, default=2,
                    help="1-based line in --env-file holding DATABASE_URL")
    ap.add_argument("--top-n", type=int, default=200,
                    help="Top-N by market cap (default 200)")
    ap.add_argument("--skip-pdf-probe", action="store_true",
                    help="Skip the 10-AR PDF download probe (faster)")
    args = ap.parse_args()

    today = date.today()
    engine = _build_engine(args)

    canary = _load_canary_tickers()
    top_n = _load_top_n_by_mcap(engine, args.top_n)
    union = sorted(set(canary) | set(top_n))

    logger.info("canary=%d top%d=%d union=%d",
                len(canary), args.top_n, len(top_n), len(union))

    counts = load_per_ticker_counts(engine, union)
    meta = load_ticker_meta(engine, union)

    probe_results: list[dict[str, Any]] = []
    if not args.skip_pdf_probe:
        samples = load_url_samples(engine, union, k=PDF_SAMPLE_SIZE)
        logger.info("probing %d AR PDFs (best-effort, network-dependent)",
                    len(samples))
        for s in samples:
            r = probe_ar_pdf(s)
            logger.info(
                "probe %s FY%s status=%s cost=$%s",
                r["ticker"], r["fiscal_year"], r["status"],
                r.get("estimated_total_cost_usd"),
            )
            probe_results.append(r)

    summary = build_summary(top_n, canary, union, counts, probe_results)
    # JSON-serialise Counters
    if "failure_modes" in summary["probe"]:
        summary["probe"]["failure_modes"] = dict(summary["probe"]["failure_modes"])

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    csv_path = REPORTS_DIR / f"ar_coverage_{today.isoformat()}.csv"
    json_path = REPORTS_DIR / f"ar_coverage_summary_{today.isoformat()}.json"
    probe_path = REPORTS_DIR / f"ar_sample_extraction_{today.isoformat()}.json"
    md_path = DOCS_DIR / f"phase-h-ar-coverage-{today.isoformat()}.md"

    write_per_ticker_csv(csv_path, union, counts, meta,
                         set(canary), set(top_n))
    json_path.write_text(json.dumps(summary, indent=2, default=str),
                         encoding="utf-8")
    probe_path.write_text(json.dumps(probe_results, indent=2, default=str),
                          encoding="utf-8")
    write_markdown_report(md_path, today, summary, csv_path, json_path, probe_path)

    logger.info("wrote %s", csv_path)
    logger.info("wrote %s", json_path)
    logger.info("wrote %s", probe_path)
    logger.info("wrote %s", md_path)
    logger.info("verdict: %s", summary["verdict"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
