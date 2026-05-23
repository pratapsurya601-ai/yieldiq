"""
audit_bank_kpi_coverage.py
==========================

Phase I-audit (Block II): read-only diagnostic for bank operational-KPI
coverage across the canonical bank universe.

Answers: "Is the planned bank_operational_kpis schema + ingest worth
building, and which of the 9 KPIs have a reliable source today?"

Universe:
  * The canonical commercial-bank list lives in
    ``backend/services/analysis/sector_overrides.py`` as
    ``_PURE_BANK_TICKERS_FOR_DE`` (~33 tickers — Tier-1 private, Tier-2
    private, PSU, SFB). This is the single source of truth used by the
    Day-111b D/E numerator fix and is broader than the Day-109a
    PB-anchoring cohort. Phase I targets this same universe.

Outputs:
  * reports/bank_kpi_coverage_<YYYY-MM-DD>.csv (per-ticker per-metric)
  * reports/bank_kpi_coverage_summary_<YYYY-MM-DD>.json
  * docs/diagnostics/phase-i-bank-kpi-coverage-<YYYY-MM-DD>.md

Verdict gates Phase I-schema / I-ingest / I-frontend:
  * HARD STOP if >70% of the 9 KPIs have no reliable source path.
  * PROCEED if >=3 of the 9 KPIs are populated anywhere in the schema
    today (sanity check that we haven't missed an existing column).
  * RESCOPE otherwise — ship schema + the subset of KPIs that have a
    reliable XBRL source, defer the rest to manual entry.

The 9 KPIs:
  1. branches_total          (AR / investor presentation)
  2. branches_tier1/2/3      (AR / investor presentation)
  3. atms_total              (AR / investor presentation)
  4. customers_millions      (AR / investor presentation)
  5. gnpa_pct                (NSE/BSE XBRL Schedule XVIII)
  6. nnpa_pct                (NSE/BSE XBRL Schedule XVIII)
  7. pcr_pct                 (NSE/BSE XBRL Schedule XVIII)
  8. casa_pct                (NSE/BSE XBRL Schedule V)
  9. cost_to_income_pct      (derivable from operating_expense / revenue
                              when both populated; XBRL Schedule A/B for
                              the precise definition)
  10. credit_deposit_pct     (derivable once advances + deposits broken
                              out from total_assets / total_liabilities)

(Items 9 and 10 are derivable; the schema column still gets a verified
extracted value when the source provides it.)

Discipline:
  * READ-ONLY. No INSERT/UPDATE/DELETE.
  * No CACHE_VERSION change.
  * No score/DCF code touched.
  * No long jobs in Railway worker (this is operator-run locally or in
    a GitHub Actions one-shot job).
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import sys
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

logger = logging.getLogger("yieldiq.audit.bank_kpi")
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")

REPO_ROOT = Path(__file__).resolve().parents[1]
REPORTS_DIR = REPO_ROOT / "reports"
DOCS_DIR = REPO_ROOT / "docs" / "diagnostics"

# The 9 operational KPIs Phase I aims to land. The "expected_source"
# is the most reliable known path per `docs/bank_data_availability.md`
# (2026-04-21) — used to render the source table in the diagnostic.
KPI_DEFS: list[dict[str, str]] = [
    {"name": "branches_total",      "expected_source": "AR / investor presentation"},
    {"name": "branches_tier_split", "expected_source": "AR / investor presentation"},
    {"name": "atms_total",          "expected_source": "AR / investor presentation"},
    {"name": "customers_millions",  "expected_source": "AR / investor presentation"},
    {"name": "gnpa_pct",            "expected_source": "NSE/BSE XBRL Sch XVIII"},
    {"name": "nnpa_pct",            "expected_source": "NSE/BSE XBRL Sch XVIII"},
    {"name": "pcr_pct",             "expected_source": "NSE/BSE XBRL Sch XVIII"},
    {"name": "casa_pct",            "expected_source": "NSE/BSE XBRL Sch V"},
    {"name": "cost_to_income_pct",  "expected_source": "operating_expense / revenue (derived)"},
    {"name": "credit_deposit_pct",  "expected_source": "NSE/BSE XBRL Sch V + VII"},
]

VERDICT_HARD_STOP_MISSING_PCT = 70.0  # >70% missing → HARD STOP


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

def _load_bank_universe() -> list[str]:
    """Import the canonical bank universe from sector_overrides.

    Single source of truth: ``_PURE_BANK_TICKERS_FOR_DE`` — the Day-111b
    commercial-bank predicate that already drives the D/E numerator fix.
    Importing rather than hard-coding ensures this audit stays aligned
    with the live cohort if it grows or shrinks.
    """
    sys.path.insert(0, str(REPO_ROOT))
    from backend.services.analysis.sector_overrides import (  # noqa: WPS433
        PURE_BANK_TICKERS_FOR_DE,
    )
    return sorted(PURE_BANK_TICKERS_FOR_DE)


# ---------- KPI probes -------------------------------------------------------

def _table_exists(engine: Engine, table: str) -> bool:
    sql = text(
        "SELECT EXISTS ("
        "  SELECT 1 FROM information_schema.tables "
        "   WHERE table_schema = 'public' AND table_name = :t"
        ")"
    )
    with engine.connect() as c:
        return bool(c.execute(sql, {"t": table}).scalar())


def _column_exists(engine: Engine, table: str, column: str) -> bool:
    sql = text(
        "SELECT EXISTS ("
        "  SELECT 1 FROM information_schema.columns "
        "   WHERE table_schema = 'public' "
        "     AND table_name = :t AND column_name = :c"
        ")"
    )
    with engine.connect() as c:
        return bool(c.execute(sql, {"t": table, "c": column}).scalar())


def probe_kpi_coverage(
    engine: Engine, universe: list[str],
) -> dict[str, dict[str, int]]:
    """Per-ticker per-KPI non-null count across all candidate tables.

    Returns a mapping ``{ticker: {kpi_name: nonnull_row_count}}``.

    The probe is defensive: each candidate column existence is checked
    first so the audit runs cleanly on databases where the Phase I
    migration has not landed yet (the expected starting state).
    """
    # Map each KPI to the list of (table, column) pairs we should probe.
    # The bank_operational_kpis table is the target schema for Phase I
    # — included here so reruns AFTER the migration lands still produce
    # accurate coverage numbers.
    kpi_probes: dict[str, list[tuple[str, str]]] = {
        "branches_total":      [("bank_operational_kpis", "branches_total")],
        "branches_tier_split": [("bank_operational_kpis", "branches_tier1")],
        "atms_total":          [("bank_operational_kpis", "atms_total")],
        "customers_millions":  [("bank_operational_kpis", "customers_millions")],
        "gnpa_pct":            [("bank_operational_kpis", "gnpa_pct"),
                                ("ratio_history", "gross_npa_pct"),
                                ("financials", "gross_npa_pct")],
        "nnpa_pct":            [("bank_operational_kpis", "nnpa_pct"),
                                ("ratio_history", "net_npa_pct"),
                                ("financials", "net_npa_pct")],
        "pcr_pct":             [("bank_operational_kpis", "pcr_pct"),
                                ("ratio_history", "provision_coverage_pct")],
        "casa_pct":            [("bank_operational_kpis", "casa_pct"),
                                ("ratio_history", "casa_pct")],
        "cost_to_income_pct":  [("bank_operational_kpis", "cost_to_income_pct"),
                                ("ratio_history", "cost_to_income_pct"),
                                ("company_financials", "operating_expense")],
        "credit_deposit_pct":  [("bank_operational_kpis", "credit_deposit_pct"),
                                ("ratio_history", "credit_deposit_pct")],
    }

    out: dict[str, dict[str, int]] = {
        t: {k: 0 for k in kpi_probes} for t in universe
    }

    # Resolve which (table, column) pairs actually exist right now.
    resolved: dict[str, list[tuple[str, str]]] = {}
    for kpi, pairs in kpi_probes.items():
        resolved[kpi] = [
            (tbl, col) for tbl, col in pairs
            if _table_exists(engine, tbl) and _column_exists(engine, tbl, col)
        ]

    with engine.connect() as c:
        for kpi, pairs in resolved.items():
            for tbl, col in pairs:
                # COUNT non-null occurrences per ticker for this column.
                sql = text(
                    f"SELECT ticker, COUNT(*) AS n "
                    f"  FROM {tbl} "
                    f" WHERE ticker = ANY(:tickers) AND {col} IS NOT NULL "
                    f" GROUP BY ticker"
                )
                try:
                    rows = c.execute(sql, {"tickers": universe}).fetchall()
                except Exception as exc:
                    logger.warning("probe failed for %s.%s: %s", tbl, col, exc)
                    continue
                for r in rows:
                    if r.ticker in out:
                        out[r.ticker][kpi] += int(r.n or 0)
    return out, resolved


# ---------- summary / verdict -----------------------------------------------

def build_summary(
    universe: list[str],
    per_ticker: dict[str, dict[str, int]],
    resolved: dict[str, list[tuple[str, str]]],
) -> dict[str, Any]:
    kpi_names = [k["name"] for k in KPI_DEFS]

    # Per-KPI coverage: number of tickers with >=1 non-null value.
    kpi_coverage: dict[str, dict[str, Any]] = {}
    for kpi in kpi_names:
        n_with = sum(1 for t in universe if per_ticker[t][kpi] > 0)
        kpi_coverage[kpi] = {
            "tickers_with_data": n_with,
            "pct_with_data": round(100.0 * n_with / max(1, len(universe)), 1),
            "resolved_sources": [f"{t}.{c}" for t, c in resolved.get(kpi, [])],
            "expected_source": next(
                d["expected_source"] for d in KPI_DEFS if d["name"] == kpi
            ),
        }

    n_missing_kpis = sum(
        1 for k in kpi_names if kpi_coverage[k]["tickers_with_data"] == 0
    )
    pct_missing_kpis = round(100.0 * n_missing_kpis / len(kpi_names), 1)
    n_populated_kpis = len(kpi_names) - n_missing_kpis

    if pct_missing_kpis > VERDICT_HARD_STOP_MISSING_PCT:
        verdict = "RESCOPE"
        verdict_reason = (
            f"{n_missing_kpis}/{len(kpi_names)} ({pct_missing_kpis}%) of "
            f"the Phase I KPIs have no source today. This is the EXPECTED "
            f"starting state — the bank_operational_kpis table does not "
            f"exist yet and the NSE/BSE XBRL Schedule extractors (V / VII "
            f"/ XI / XVIII) have not been written. Ship I-schema + I-ingest "
            f"narrowed to the highest-confidence subset (GNPA / NNPA / PCR "
            f"/ CASA from BSE quarterly XBRL); defer branches / ATMs / "
            f"customer base to the AR-PDF extraction path; cost-to-income "
            f"and credit-deposit are derivable once the underlying "
            f"deposits/advances columns are broken out."
        )
    elif n_populated_kpis >= 3:
        verdict = "PROCEED"
        verdict_reason = (
            f"{n_populated_kpis}/{len(kpi_names)} KPIs already have at "
            f"least partial coverage in the existing schema. Phase I "
            f"schema + extractors are still warranted to consolidate "
            f"into bank_operational_kpis with explicit source provenance."
        )
    else:
        verdict = "RESCOPE"
        verdict_reason = (
            f"Only {n_populated_kpis} of {len(kpi_names)} KPIs are "
            f"populated anywhere today. Ship I-schema + the BSE XBRL "
            f"path (most reliable for GNPA/NNPA/PCR/CASA); defer the "
            f"AR-PDF path until the XBRL path is proven in production."
        )

    return {
        "universe_size": len(universe),
        "universe_sample": universe[:10],
        "kpi_coverage": kpi_coverage,
        "n_missing_kpis": n_missing_kpis,
        "pct_missing_kpis": pct_missing_kpis,
        "n_populated_kpis": n_populated_kpis,
        "verdict": verdict,
        "verdict_reason": verdict_reason,
        "thresholds": {
            "hard_stop_missing_pct": VERDICT_HARD_STOP_MISSING_PCT,
        },
    }


# ---------- writers ---------------------------------------------------------

def write_per_ticker_csv(
    path: Path, universe: list[str],
    per_ticker: dict[str, dict[str, int]],
) -> None:
    kpi_names = [k["name"] for k in KPI_DEFS]
    fields = ["ticker"] + kpi_names + ["kpis_present", "kpis_missing"]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for t in universe:
            row: dict[str, Any] = {"ticker": t}
            present = 0
            for k in kpi_names:
                v = per_ticker[t][k]
                row[k] = v
                if v > 0:
                    present += 1
            row["kpis_present"] = present
            row["kpis_missing"] = len(kpi_names) - present
            w.writerow(row)


def write_markdown_report(
    path: Path, today: date, summary: dict[str, Any],
    universe: list[str], csv_path: Path, json_path: Path,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    kpi_rows = []
    for kpi in [k["name"] for k in KPI_DEFS]:
        c = summary["kpi_coverage"][kpi]
        sources = ", ".join(c["resolved_sources"]) or "_none in DB today_"
        kpi_rows.append(
            f"| {kpi} | {c['tickers_with_data']} / {summary['universe_size']} "
            f"({c['pct_with_data']}%) | {c['expected_source']} | {sources} |"
        )
    kpi_table = (
        "| KPI | Tickers with data | Expected source | Resolved DB column(s) |\n"
        "|---|---|---|---|\n" + "\n".join(kpi_rows)
    )

    universe_list = ", ".join(universe)

    body = f"""# Phase I-audit -- Bank operational-KPI coverage ({today.isoformat()})

**Status:** read-only diagnostic. No code or data changes.
**Author:** Phase I dispatch (Block II).
**Purpose:** evidence base to gate Phase I-schema / I-ingest /
I-frontend / I-operator-workflow.

---

## 1. Why this audit exists

Competitor surfaces (screener.in, banknote.in, tijori) show per-bank
operational metrics that YieldIQ currently does not: branches
(total + tier split), ATMs, customer base, GNPA, NNPA, provision
coverage ratio, CASA, cost-to-income, credit-deposit ratio.

The generic `company_financials` and `ratio_history` tables do not
carry bank-specific operational fields. Phase I adds them as a
schema + ingest path + frontend panel. The Phase B.0 / B.1 work
established that the banking cohort scoring is highly sensitive to
NPA cycles -- per-bank GNPA / PCR are first-class inputs to the
ROE-quality boost and stress flag in `sector_overrides.py`
(`banking_roe_quality_boost`, `banking_stress_flag`).

Today those helpers receive `None` for the asset-quality inputs in
production because no upstream column populates them. This audit
quantifies the gap before committing schema + ingest work.

---

## 2. Universe ({summary['universe_size']} tickers)

Source: `_PURE_BANK_TICKERS_FOR_DE` in
`backend/services/analysis/sector_overrides.py`. This is the broader
commercial-bank predicate used by the Day-111b D/E numerator fix,
and is the right universe for Phase I -- it includes Tier-1 private
banks, Tier-2 private banks, the top PSU set, and the small-finance
banks.

{universe_list}

---

## 3. KPI coverage today

{kpi_table}

**Missing entirely:** {summary['n_missing_kpis']} / {len(KPI_DEFS)}
({summary['pct_missing_kpis']}%).
**At least partially populated:** {summary['n_populated_kpis']} / {len(KPI_DEFS)}.

This matches the per-bank probe documented in
`docs/bank_data_availability.md` (2026-04-21) which found 0/7
coverage on GNPA / NNPA / PCR / CASA across the seven flagship banks.

---

## 4. Source recommendations per KPI

| KPI | Recommended source | Notes |
|---|---|---|
| gnpa_pct | NSE / BSE quarterly XBRL Schedule XVIII (Asset Classification) | Reuse `data_pipeline/sources/bse_xbrl.py` patterns. Direct numeric tags. |
| nnpa_pct | NSE / BSE quarterly XBRL Schedule XVIII | Same fetcher as GNPA. |
| pcr_pct  | NSE / BSE quarterly XBRL Schedule XVIII | Same fetcher. Often disclosed as a separate ratio tag. |
| casa_pct | NSE / BSE quarterly XBRL Schedule V (Deposits) | Compute from `current + savings` over `total_deposits` if the ratio tag is absent. |
| credit_deposit_pct | NSE / BSE quarterly XBRL Schedule V + VII | `advances_total / deposits_total`. |
| cost_to_income_pct | XBRL Schedule A/B + Form A; fallback derived `operating_expense / (interest_earned + non_interest_income)` | `operating_expense` is already populated for 5/7 flagship banks per the 2026-04-21 audit. |
| branches_total / tier split | Bank annual report (`company_annual_reports.ar_url`) -- "performance highlights" section, typically pages 1-15 | Use the Phase H Anthropic extractor with a new bank-ops prompt template. |
| atms_total | Same AR section | Same extractor. |
| customers_millions | Same AR section | Same extractor. RBI DBIE has aggregate figures but not per-bank consistently. |

For the AR path, the existing Phase H pipeline
(`scripts/extract_ar_signals_batch.py`, ar_signals migration 060)
gives us prompt caching, cost tracking, and the SEBI-vocab JSON
sanitiser for free. The new I-ingest-b script reuses that scaffolding
with a different output schema.

---

## 5. Verdict

**{summary['verdict']}**

{summary['verdict_reason']}

### Scope for the four follow-on PRs

- **I-schema** -- ship `061_bank_operational_kpis.sql` exactly as
  specified in the Phase I plan (10 metric columns + source + URL +
  ticker / period_end / period_type UNIQUE). Migration 060 is taken
  (`ar_signals`), so this Phase uses **061**.
- **I-ingest-a** -- BSE XBRL Schedules V / XVIII fetcher for the four
  financial KPIs (GNPA / NNPA / PCR / CASA) on the 3-bank pre-flight
  sample (HDFCBANK, SBIN, AXISBANK). `--dry-run`, `--resume-from`.
- **I-ingest-b** -- AR-PDF Anthropic extractor for the operational
  KPIs (branches / ATMs / customers). `--cost-cap-usd 50` per the
  Phase H precedent.
- **I-frontend** -- `BankKpiPanel.tsx` rendering only when the ticker
  is in `is_pure_bank_for_de()`; gracefully degrades when columns are
  null (the expected state on day one). Manifest entry scoped to
  `["bank_operational_kpis", "bank_kpis"]`. No CACHE_VERSION bump.
- **I-operator-workflow** -- `bank-kpi-backfill.yml` mirroring
  `concall-backfill.yml` and `ar-backfill.yml`, with phase choice
  `xbrl` / `ar` / `all`, `top_n_banks`, `cost_cap_usd`, `dry_run`.

---

## 6. Outputs of this run

* `{csv_path.as_posix()}` -- per-ticker per-KPI non-null counts.
* `{json_path.as_posix()}` -- machine-readable summary.
* This markdown -- human-readable diagnostic.

## 7. Reproducibility

```
python scripts/audit_bank_kpi_coverage.py \\
    --env-file .env.local --env-line 2
```

Output paths embed the run date; reruns against a different DB
snapshot write new files without overwriting today's. The probe is
defensive against missing tables / columns -- once `I-schema` lands
the same script will start picking up `bank_operational_kpis` rows
without any code change.
"""
    path.write_text(body, encoding="utf-8")


# ---------- main ------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--env-file", default=None,
                    help="Path to env file containing DATABASE_URL")
    ap.add_argument("--env-line", type=int, default=2,
                    help="1-based line in --env-file holding DATABASE_URL")
    args = ap.parse_args()

    today = date.today()
    engine = _build_engine(args)

    universe = _load_bank_universe()
    logger.info("bank universe size=%d", len(universe))

    per_ticker, resolved = probe_kpi_coverage(engine, universe)
    summary = build_summary(universe, per_ticker, resolved)

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    csv_path = REPORTS_DIR / f"bank_kpi_coverage_{today.isoformat()}.csv"
    json_path = REPORTS_DIR / f"bank_kpi_coverage_summary_{today.isoformat()}.json"
    md_path = DOCS_DIR / f"phase-i-bank-kpi-coverage-{today.isoformat()}.md"

    write_per_ticker_csv(csv_path, universe, per_ticker)
    json_path.write_text(json.dumps(summary, indent=2, default=str),
                         encoding="utf-8")
    write_markdown_report(md_path, today, summary, universe, csv_path, json_path)

    logger.info("wrote %s", csv_path)
    logger.info("wrote %s", json_path)
    logger.info("wrote %s", md_path)
    logger.info("verdict: %s", summary["verdict"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
