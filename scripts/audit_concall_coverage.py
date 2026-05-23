"""
audit_concall_coverage.py
=========================

Read-only diagnostic for Phase G-audit. Answers a single question:

    "Is a 5-year concall backfill worth running?"

Scope:
  - Universe: canary v3 (333 tickers in scripts/canary_universe_180.json,
    despite the legacy filename) UNION top-200 by market cap.
  - Per-ticker counts of rows in `concall_transcripts` over 1y / 5y windows.
  - Coverage histograms (how many tickers cross the 1y >=4 and 5y >=20
    "sufficient cadence" thresholds).
  - AI-summary cache stats: % rows with non-null `ai_summary`,
    % withheld by the SEBI sanitizer (sentinel
    `(summary withheld pending review)`).
  - Source feasibility: NSE-only blind spot check. Picks 10 random
    BSE-only listings (i.e. `bse_code IS NOT NULL` AND no NSE rows in
    concall_transcripts) and reports the gap.

Outputs:
  - reports/concall_coverage_<YYYY-MM-DD>.csv (one row per ticker)
  - reports/concall_coverage_summary_<YYYY-MM-DD>.json
  - docs/diagnostics/phase-g-concall-coverage-<YYYY-MM-DD>.md

Verdict block at the end of the .md gates Phase G-cost. If <20% of
top-200 have *any* transcript in the last 5y, the verdict is HARD STOP
and operator is asked to re-scope.

Usage:
    DATABASE_URL="postgresql://..." python scripts/audit_concall_coverage.py
    python scripts/audit_concall_coverage.py --env-file ../yieldiq_v7/.env.local --env-line 2

Discipline:
  - READ-ONLY. No INSERT/UPDATE/DELETE.
  - No CACHE_VERSION change.
  - No score/DCF code touched.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import random
import sys
from collections import Counter
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine


REPO_ROOT = Path(__file__).resolve().parents[1]
CANARY_PATH = REPO_ROOT / "scripts" / "canary_universe_180.json"
REPORTS_DIR = REPO_ROOT / "reports"
DOCS_DIR = REPO_ROOT / "docs" / "diagnostics"

WITHHELD_SENTINEL = "(summary withheld pending review)"

# "Sufficient cadence" thresholds — we treat ≥4 transcripts in the last
# 1y (quarterly cadence with some leeway) and ≥20 in 5y as the bar a
# ticker must clear for the Phase 1 signal extractor to be useful.
ONE_YEAR_MIN = 4
FIVE_YEAR_MIN = 20


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
    """Read scripts/canary_universe_180.json (v3_333 schema).

    The v3 file shape is:
        {"_meta": {...},
         "buckets": {"top100_diversified": [...rules...], ...},
         "stocks": [{"symbol": "RELIANCE", "bucket": "...", ...}, ...]}
    Older v2 keyed lists directly off bucket names. We support both.
    """
    raw = json.loads(CANARY_PATH.read_text(encoding="utf-8"))
    out: list[str] = []
    stocks_v3 = raw.get("stocks")
    if isinstance(stocks_v3, list):
        for s in stocks_v3:
            sym = s.get("symbol") if isinstance(s, dict) else None
            if sym:
                out.append(sym)
    else:
        # legacy v2: bucket -> list of tickers
        for k, v in raw.items():
            if k.startswith("_"):
                continue
            if isinstance(v, list):
                out.extend([x for x in v if isinstance(x, str)])
    # dedupe preserve-order
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
    engine: Engine, universe: list[str], today: date
) -> dict[str, dict[str, Any]]:
    """Return {ticker: {total, last_1y, last_5y, with_summary, withheld, oldest, newest}}."""
    cutoff_1y = today - timedelta(days=365)
    cutoff_5y = today - timedelta(days=365 * 5)

    sql = text("""
        SELECT
          ticker,
          COUNT(*)                                                AS total,
          SUM(CASE WHEN filing_date >= :c1 THEN 1 ELSE 0 END)     AS in_1y,
          SUM(CASE WHEN filing_date >= :c5 THEN 1 ELSE 0 END)     AS in_5y,
          SUM(CASE WHEN ai_summary IS NOT NULL THEN 1 ELSE 0 END) AS with_summary,
          SUM(CASE WHEN ai_summary = :sentinel THEN 1 ELSE 0 END) AS withheld,
          MIN(filing_date)                                        AS oldest,
          MAX(filing_date)                                        AS newest,
          SUM(CASE WHEN transcript_text IS NOT NULL THEN 1 ELSE 0 END) AS with_text
        FROM concall_transcripts
        WHERE ticker = ANY(:tickers)
        GROUP BY ticker
    """)

    out: dict[str, dict[str, Any]] = {}
    with engine.connect() as c:
        rows = c.execute(sql, {
            "c1": cutoff_1y, "c5": cutoff_5y,
            "sentinel": WITHHELD_SENTINEL,
            "tickers": universe,
        }).fetchall()

    for r in rows:
        out[r.ticker] = {
            "total": int(r.total or 0),
            "in_1y": int(r.in_1y or 0),
            "in_5y": int(r.in_5y or 0),
            "with_summary": int(r.with_summary or 0),
            "withheld": int(r.withheld or 0),
            "with_text": int(r.with_text or 0),
            "oldest": r.oldest.isoformat() if r.oldest else None,
            "newest": r.newest.isoformat() if r.newest else None,
        }

    # zero-fill for tickers with no concall rows at all
    for t in universe:
        out.setdefault(t, {
            "total": 0, "in_1y": 0, "in_5y": 0,
            "with_summary": 0, "withheld": 0, "with_text": 0,
            "oldest": None, "newest": None,
        })
    return out


def load_ticker_meta(engine: Engine, universe: list[str]) -> dict[str, dict[str, Any]]:
    sql = text("""
        SELECT s.ticker, s.company_name, s.sector, s.industry,
               s.bse_code, COALESCE(MAX(mm.market_cap_cr), 0) AS mcap_cr
          FROM stocks s
          LEFT JOIN market_metrics mm ON mm.ticker = s.ticker
         WHERE s.ticker = ANY(:tickers)
         GROUP BY s.ticker, s.company_name, s.sector, s.industry, s.bse_code
    """)
    out: dict[str, dict[str, Any]] = {}
    with engine.connect() as c:
        for r in c.execute(sql, {"tickers": universe}).fetchall():
            out[r.ticker] = {
                "company_name": r.company_name,
                "sector": r.sector,
                "industry": r.industry,
                "bse_code": r.bse_code,
                "mcap_cr": float(r.mcap_cr or 0),
            }
    for t in universe:
        out.setdefault(t, {"company_name": None, "sector": None,
                           "industry": None, "bse_code": None, "mcap_cr": 0.0})
    return out


def sample_bse_only_blindspots(
    engine: Engine, ticker_meta: dict[str, dict[str, Any]],
    counts: dict[str, dict[str, Any]], k: int = 10,
) -> list[dict[str, Any]]:
    """Tickers that have a bse_code AND zero concall_transcripts rows.

    These are the candidates for the "NSE-only source has a blind spot"
    argument — they're BSE-listed names where the existing NSE-only
    fetcher returned nothing.
    """
    candidates = [
        t for t in ticker_meta
        if ticker_meta[t]["bse_code"]
        and counts.get(t, {}).get("total", 0) == 0
    ]
    if not candidates:
        return []
    random.seed(20260526)  # deterministic for reproducibility
    sample = random.sample(candidates, min(k, len(candidates)))
    return [
        {
            "ticker": t,
            "company_name": ticker_meta[t]["company_name"],
            "sector": ticker_meta[t]["sector"],
            "bse_code": ticker_meta[t]["bse_code"],
            "mcap_cr": ticker_meta[t]["mcap_cr"],
        }
        for t in sample
    ]


# ---------- histograms / verdict --------------------------------------------

def _hist(values: list[int], buckets: list[tuple[int, int | None, str]]) -> dict[str, int]:
    out: dict[str, int] = {label: 0 for _, _, label in buckets}
    for v in values:
        for lo, hi, label in buckets:
            if v >= lo and (hi is None or v < hi):
                out[label] += 1
                break
    return out


def build_summary(
    top200: list[str],
    canary: list[str],
    union_universe: list[str],
    counts: dict[str, dict[str, Any]],
    blindspots: list[dict[str, Any]],
) -> dict[str, Any]:
    def stats_for(group: list[str]) -> dict[str, Any]:
        in_1y = [counts[t]["in_1y"] for t in group]
        in_5y = [counts[t]["in_5y"] for t in group]
        any_1y = sum(1 for v in in_1y if v > 0)
        any_5y = sum(1 for v in in_5y if v > 0)
        meets_1y = sum(1 for v in in_1y if v >= ONE_YEAR_MIN)
        meets_5y = sum(1 for v in in_5y if v >= FIVE_YEAR_MIN)
        return {
            "size": len(group),
            "any_in_1y": any_1y,
            "any_in_5y": any_5y,
            "any_in_1y_pct": round(100.0 * any_1y / max(1, len(group)), 1),
            "any_in_5y_pct": round(100.0 * any_5y / max(1, len(group)), 1),
            "meets_1y_threshold": meets_1y,
            "meets_5y_threshold": meets_5y,
            "meets_1y_pct": round(100.0 * meets_1y / max(1, len(group)), 1),
            "meets_5y_pct": round(100.0 * meets_5y / max(1, len(group)), 1),
            "hist_5y": _hist(in_5y, [
                (0, 1, "0"),
                (1, 5, "1-4"),
                (5, 10, "5-9"),
                (10, 20, "10-19"),
                (20, 40, "20-39"),
                (40, None, "40+"),
            ]),
        }

    # AI summary stats across the whole concall_transcripts table for
    # union_universe (re-derived from counts)
    total_rows = sum(counts[t]["total"] for t in union_universe)
    rows_with_summary = sum(counts[t]["with_summary"] for t in union_universe)
    rows_withheld = sum(counts[t]["withheld"] for t in union_universe)
    rows_with_text = sum(counts[t]["with_text"] for t in union_universe)

    ai = {
        "total_rows_in_universe": total_rows,
        "rows_with_summary": rows_with_summary,
        "rows_with_summary_pct": round(100.0 * rows_with_summary / max(1, total_rows), 1),
        "rows_withheld": rows_withheld,
        "rows_withheld_pct": round(100.0 * rows_withheld / max(1, total_rows), 1),
        "rows_with_transcript_text": rows_with_text,
        "rows_with_text_pct": round(100.0 * rows_with_text / max(1, total_rows), 1),
    }

    # verdict
    top200_stats = stats_for(top200)
    if top200_stats["any_in_5y_pct"] < 20.0:
        verdict = "HARD STOP"
        verdict_reason = (
            f"Only {top200_stats['any_in_5y']} / {top200_stats['size']} "
            f"({top200_stats['any_in_5y_pct']}%) of top-200 have any "
            f"concall transcript in the last 5y. Below the 20% bar — "
            f"NSE source is too sparse to justify Phase G-cost. Operator "
            f"must add a BSE source (or another fetcher) before backfill."
        )
    elif top200_stats["meets_5y_pct"] < 25.0:
        verdict = "PROCEED WITH CAUTION"
        verdict_reason = (
            f"{top200_stats['any_in_5y_pct']}% of top-200 have *some* "
            f"5y coverage but only {top200_stats['meets_5y_pct']}% clear "
            f"the ≥20-call cadence threshold. Phase G-cost is worth "
            f"shipping (cost tracking is needed regardless), but G-intel "
            f"signal extraction will have a small effective universe."
        )
    else:
        verdict = "PROCEED"
        verdict_reason = (
            f"{top200_stats['any_in_5y_pct']}% of top-200 have 5y "
            f"coverage; {top200_stats['meets_5y_pct']}% clear the cadence "
            f"bar. Backfill is justified — proceed to G-cost."
        )

    return {
        "canary": stats_for(canary),
        "top200": top200_stats,
        "union": stats_for(union_universe),
        "ai_summary_cache": ai,
        "bse_only_blindspots_sample": blindspots,
        "thresholds": {"one_year_min": ONE_YEAR_MIN,
                       "five_year_min": FIVE_YEAR_MIN},
        "verdict": verdict,
        "verdict_reason": verdict_reason,
    }


# ---------- writers ---------------------------------------------------------

def write_per_ticker_csv(
    path: Path, universe: list[str],
    counts: dict[str, dict[str, Any]],
    meta: dict[str, dict[str, Any]],
    canary_set: set[str], top200_set: set[str],
) -> None:
    fields = [
        "ticker", "company_name", "sector", "industry",
        "mcap_cr", "bse_code",
        "in_canary", "in_top200",
        "total", "in_1y", "in_5y",
        "with_summary", "withheld", "with_text",
        "oldest", "newest",
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
                "industry": m["industry"],
                "mcap_cr": round(m["mcap_cr"], 2),
                "bse_code": m["bse_code"],
                "in_canary": t in canary_set,
                "in_top200": t in top200_set,
                "total": c["total"],
                "in_1y": c["in_1y"],
                "in_5y": c["in_5y"],
                "with_summary": c["with_summary"],
                "withheld": c["withheld"],
                "with_text": c["with_text"],
                "oldest": c["oldest"],
                "newest": c["newest"],
            })


def write_markdown_report(
    path: Path, today: date, summary: dict[str, Any],
    csv_path: Path, json_path: Path,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    canary = summary["canary"]
    top200 = summary["top200"]
    union = summary["union"]
    ai = summary["ai_summary_cache"]
    bs = summary["bse_only_blindspots_sample"]

    def render_hist(h: dict[str, int]) -> str:
        lines = ["| Bucket (5y count) | Tickers |", "|---|---|"]
        for k, v in h.items():
            lines.append(f"| {k} | {v} |")
        return "\n".join(lines)

    bs_table = "_No bse_code-only tickers found in universe._"
    if bs:
        bs_lines = ["| Ticker | Company | Sector | BSE Code | M-cap (Cr) |",
                    "|---|---|---|---|---|"]
        for r in bs:
            bs_lines.append(
                f"| {r['ticker']} | {r['company_name'] or ''} | "
                f"{r['sector'] or ''} | {r['bse_code']} | "
                f"{r['mcap_cr']:.0f} |"
            )
        bs_table = "\n".join(bs_lines)

    body = f"""# Phase G-audit — Concall Coverage Diagnostic ({today.isoformat()})

**Status:** read-only diagnostic. No code or data changes.
**Author:** Phase G dispatch
**Purpose:** evidence base to gate Phase G-cost / G-intel-phase1 /
G-operator-workflow.

---

## 1. Why this audit exists

Phase G's re-scoped plan promotes the Phase 0 `concall_intel_service`
scaffold to Phase 1 production with Anthropic-powered structured signal
extraction (guidance, capex, margin, tone, quotes). Before spending
LLM budget on a wide backfill, we need to know whether the underlying
transcript inventory is dense enough to be worth extracting from — and
whether the existing NSE-only fetcher leaves big BSE blind spots.

This audit answers:

1. How many tickers in our top-200 / canary-333 union actually have
   transcripts in `concall_transcripts` over the last 1y and 5y?
2. What fraction of those transcripts already have an `ai_summary`,
   and what fraction were withheld by the SEBI sanitizer?
3. Is the NSE-only fetcher missing BSE-only listings in a systemic way?

---

## 2. Universe

| Bucket | Count |
|---|---|
| Canary v3 (333) | {canary['size']} |
| Top 200 by market cap | {top200['size']} |
| Union (deduped) | {union['size']} |

---

## 3. Coverage headline

| Group | Any in 1y | Any in 5y | Meets 1y ≥ {ONE_YEAR_MIN} | Meets 5y ≥ {FIVE_YEAR_MIN} |
|---|---|---|---|---|
| Canary v3 | {canary['any_in_1y']} ({canary['any_in_1y_pct']}%) | {canary['any_in_5y']} ({canary['any_in_5y_pct']}%) | {canary['meets_1y_threshold']} ({canary['meets_1y_pct']}%) | {canary['meets_5y_threshold']} ({canary['meets_5y_pct']}%) |
| Top-200 | {top200['any_in_1y']} ({top200['any_in_1y_pct']}%) | {top200['any_in_5y']} ({top200['any_in_5y_pct']}%) | {top200['meets_1y_threshold']} ({top200['meets_1y_pct']}%) | {top200['meets_5y_threshold']} ({top200['meets_5y_pct']}%) |
| Union | {union['any_in_1y']} ({union['any_in_1y_pct']}%) | {union['any_in_5y']} ({union['any_in_5y_pct']}%) | {union['meets_1y_threshold']} ({union['meets_1y_pct']}%) | {union['meets_5y_threshold']} ({union['meets_5y_pct']}%) |

### 5-year transcript-count distribution (top-200)

{render_hist(top200['hist_5y'])}

---

## 4. AI-summary cache state

Across the entire `concall_transcripts` table filtered to the union universe:

| Field | Value |
|---|---|
| Total rows | {ai['total_rows_in_universe']} |
| Rows with `ai_summary` populated | {ai['rows_with_summary']} ({ai['rows_with_summary_pct']}%) |
| Rows withheld by SEBI sanitizer | {ai['rows_withheld']} ({ai['rows_withheld_pct']}%) |
| Rows with cached `transcript_text` | {ai['rows_with_transcript_text']} ({ai['rows_with_text_pct']}%) |

`Rows withheld` are rows where `ai_summary` equals the sentinel
`(summary withheld pending review)` — the Groq summary contained a
SEBI-banned word (`buy/sell/strong/recommend/target/...`) and the
sanitizer in `backend/services/concall_service.py` swapped it out.

---

## 5. NSE-only blind-spot probe

The existing fetcher (`data_pipeline/sources/nse_concall_transcripts.py`)
only hits NSE. Sample of 10 random tickers that have a `bse_code` in
the `stocks` table but **zero** rows in `concall_transcripts`:

{bs_table}

If the operator manually spot-checks a couple of these against the BSE
corporate-announcements portal and finds concall PDFs, that's evidence
for adding a BSE fetcher in a follow-up phase (not in current scope).

---

## 6. Verdict

**{summary['verdict']}**

{summary['verdict_reason']}

### Decision matrix

| Verdict | Action |
|---|---|
| PROCEED | Ship G-cost, G-intel-phase1, G-operator-workflow as planned. |
| PROCEED WITH CAUTION | Ship G-cost (cost tracking valuable regardless). For G-intel-phase1, narrow the initial universe to only tickers that clear the 5y ≥ {FIVE_YEAR_MIN} bar. |
| HARD STOP | Open a separate phase to add a BSE source before any LLM spend. Pause G-cost. |

---

## 7. Outputs of this run

* `{csv_path.as_posix()}` — per-ticker counts ({union['size']} rows).
* `{json_path.as_posix()}` — machine-readable summary.
* This markdown — human-readable diagnostic.

## 8. Reproducibility

```
python scripts/audit_concall_coverage.py \\
    --env-file .env.local --env-line 2
```

Output paths embed the run date; re-runs against a different DB
snapshot will write new files without overwriting today's.
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
    args = ap.parse_args()

    today = date.today()
    engine = _build_engine(args)

    canary = _load_canary_tickers()
    top_n = _load_top_n_by_mcap(engine, args.top_n)
    union = sorted(set(canary) | set(top_n))

    print(f"[audit] canary={len(canary)} top{args.top_n}={len(top_n)} "
          f"union={len(union)}", file=sys.stderr)

    counts = load_per_ticker_counts(engine, union, today)
    meta = load_ticker_meta(engine, union)
    blindspots = sample_bse_only_blindspots(engine, meta, counts, k=10)

    summary = build_summary(top_n, canary, union, counts, blindspots)

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    csv_path = REPORTS_DIR / f"concall_coverage_{today.isoformat()}.csv"
    json_path = REPORTS_DIR / f"concall_coverage_summary_{today.isoformat()}.json"
    md_path = DOCS_DIR / f"phase-g-concall-coverage-{today.isoformat()}.md"

    write_per_ticker_csv(csv_path, union, counts, meta,
                         set(canary), set(top_n))
    json_path.write_text(json.dumps(summary, indent=2, default=str),
                         encoding="utf-8")
    write_markdown_report(md_path, today, summary, csv_path, json_path)

    print(f"[audit] wrote {csv_path}", file=sys.stderr)
    print(f"[audit] wrote {json_path}", file=sys.stderr)
    print(f"[audit] wrote {md_path}", file=sys.stderr)
    print(f"[audit] verdict: {summary['verdict']}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
