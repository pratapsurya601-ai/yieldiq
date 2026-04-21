# Bank data availability report

**Date**: 2026-04-21
**Goal**: Determine which bank-native Prism metrics we can ship today vs. later.
**Method**: Probe Neon prod DB for 7 flagship banks — SBIN, HDFCBANK, ICICIBANK,
BANKBARODA, KOTAKBANK, AXISBANK, INDUSINDBK.

---

## TL;DR

| Metric                | Coverage  | Source                                                 | Status                    |
|-----------------------|-----------|--------------------------------------------------------|---------------------------|
| ROA                   | 7/7       | `financials.roa`                                       | Ship now                  |
| ROE                   | 7/7       | `financials.roe` (already in enriched)                 | Already shipped           |
| Advances YoY (proxy)  | 7/7       | `company_financials.total_assets` (balance sheet)      | Ship now as Assets YoY    |
| Revenue YoY           | 7/7       | `company_financials.revenue` series                    | Ship now                  |
| PAT YoY               | 7/7       | `company_financials.net_income` series                 | Ship now                  |
| Cost-to-Income        | 5/7       | `company_financials.operating_expense / revenue`       | Ship now (best-effort)    |
| P/B                   | 5/7       | `ratio_history.pb_ratio` / `market_metrics.pb_ratio`   | Ship now                  |
| NIM                   | 0/7       | `interest_earned − interest_expended / total_assets`   | TODO: XBRL Sch A/B        |
| CAR (Tier-1)          | 0/7       | Not in DB                                              | TODO: NSE XBRL Sch XI     |
| Gross NPA %           | 0/7       | Not in DB                                              | TODO: NSE XBRL Sch XVIII  |
| Net NPA %             | 0/7       | Not in DB                                              | TODO: NSE XBRL Sch XVIII  |
| CASA %                | 0/7       | Not in DB                                              | TODO: NSE XBRL Sch V      |
| Deposits total        | 0/7       | Not broken out — lumped into `total_liabilities`       | TODO: Sch V breakdown     |
| Advances total        | 0/7       | Not broken out — lumped into `total_assets`            | TODO: Sch VII breakdown   |

---

## Detailed findings

### `company_financials` (54 cols, XBRL-sourced)

Per-bank row counts (annual, 2022-03-31 → 2025-03-31): 4 years each, both
`income` and `balance_sheet` statement types.

**Income statement fields, populated (all 7 banks)**:
- `revenue` (= interest earned + non-interest income, NOT split)
- `net_income` / `pat`
- `operating_expense` — populated on **5/7**: SBIN, BANKBARODA, KOTAKBANK,
  AXISBANK, INDUSINDBK. **Missing on HDFCBANK, ICICIBANK.**

**Income statement fields NULL across all 7 banks**:
- `total_income` (bank-specific composite)
- `interest_earned` (bank-specific)
- `interest_expended` (bank-specific)
- `interest_earned` (bank-specific)
- `depreciation`, `pretax_income`, `tax_provision`

**Balance sheet fields populated (all 7 banks)**:
- `total_assets`, `total_equity`, `total_debt`, `total_liabilities`, `cash`

**Balance sheet fields NULL across all 7 banks**:
- `current_liabilities` (not meaningful for banks — working-capital concept
  doesn't map to deposit-funded banks, so zero coverage is expected)

**Flags**:
- `is_bank` boolean is **False for all 7 banks**. The XBRL ingest never
  flipped it. We therefore cannot use this column as a reliable bank
  filter. Fallback: `stocks.sector` / ticker suffix. (Pipeline bug worth
  a separate follow-up, but not needed for this PR — our existing
  `_is_bank_like` heuristic in analysis_service covers it.)

### `financials` (38 cols, legacy table)

Pre-computed `roa`, `roe`, `debt_to_equity`, `net_margin`, `revenue`, `pat`,
`total_assets`, `total_equity`. Available for all 7 banks, 2+ years each.

- `revenue_growth_yoy`, `pat_growth_yoy`, `fcf_growth_yoy` — **all NULL
  across all 7 banks**. Pipeline doesn't populate these for banks.
  → Must compute YoY in-app from the `revenue` / `pat` series.

### `ratio_history` (42 cols)

`roe` (populated), `roa` (populated), `pb_ratio` (populated for HDFCBANK,
ICICIBANK, KOTAKBANK, AXISBANK, SBIN — NULL for BANKBARODA and INDUSINDBK),
`pe_ratio` similar pattern.

- `roce` is **NULL for all 7 banks** — correct, since ROCE doesn't apply
  to banks. This is what we expected.

### `market_metrics`

`pb_ratio`, `pe_ratio`, `ev_ebitda`, `market_cap_cr` — populated for all 7
at latest trade date.

### `shareholding_pattern`

Already wired into analysis_service for all tickers — promoter_pct,
fii_pct, dii_pct, public_pct, promoter_pledge_pct.

### `hex_pulse_inputs`

Populated for Pulse axis already — promoter_delta_qoq, insider_net_30d,
estimate_revision_30d, pledged_pct_delta. Works for banks without change.

---

## What we ship in this PR

### Bank-native QualityOutput fields (new)

1. **`roa`** — `financials.roa`, already pre-computed. 7/7 coverage.
2. **`advances_yoy`** — derived from `total_assets` YoY (loans dominate
   a bank's balance sheet so this is a directionally-correct proxy until
   we can extract `advances` from Schedule VII). 7/7 coverage.
3. **`deposits_yoy`** — derived from `total_liabilities` YoY (deposits
   dominate a bank's liabilities for the same reason). 7/7 coverage.
4. **`cost_to_income`** — `operating_expense / revenue × 100`, 5/7 coverage.
5. **`revenue_yoy_bank`**, **`pat_yoy_bank`** — reused existing series
   computation; surfaces the YoY number the frontend can render as a card.

### Bank-native Prism axes (hex_service)

- **Quality**: ROA + ROE composite (existing ROE weighting stays; ROA
  additive). Scored vs. absolute thresholds — ROA > 1% is good for Indian
  banks (cohort median is ~1.1-1.4).
- **Moat**: scale proxy — log(total_assets_cr) normalised to 0-10, PLUS
  margin-stability signal from existing `op_margin` series when present.
- **Safety**: already branches for banks (PR-D1 in hex_service). Currently
  falls back to P/BV proxy because CAR/NPA aren't in the DB. No change —
  the branch is correct, data is the bottleneck.
- **Growth**: average of (Revenue 3y CAGR, Assets 3y CAGR, PAT 3y CAGR).
  All derivable from the 4-year `company_financials` series we just
  verified. No longer dependent on `revenue_growth_yoy` column which is
  NULL for banks.
- **Value**: unchanged — uses P/BV, which is already bank-aware.
- **Pulse**: unchanged — sector-agnostic.

### Fields scoped out (TODO list, source required)

- **NIM** — need `interest_earned` + `interest_expended` populated on
  `company_financials.income`. Both are currently NULL for all banks.
  Source: NSE XBRL Schedule A/B (Interest Earned / Expended), or BSE
  filings. Requires a pipeline job.
- **CAR / Tier-1 capital ratio** — RBI-regulated disclosure, NOT in any
  table today. Source: NSE XBRL Schedule XI (Capital Adequacy). Requires
  a new extractor.
- **Gross NPA % / Net NPA %** — Source: NSE XBRL Schedule XVIII
  (Asset Classification). Requires a new extractor.
- **CASA %** — Source: NSE XBRL Schedule V (Deposits, broken down by
  type — current/savings/term). Requires a new extractor.
- **Advances / Deposits (absolute, not proxies)** — Source: NSE XBRL
  Schedules V (Deposits) and VII (Advances). Requires a new extractor.

Once any of these lands, the corresponding TODO comments in
`analysis_service.py` point at exactly where to wire the new field.
