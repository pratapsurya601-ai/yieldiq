# Day 3 data quality follow-ups (2026-05-19 evening dump)

These were uncovered during the Day 1+2 outlier sprint. Each is a real
issue, but each requires touching the data pipeline (collectors) rather
than the valuation engine. Parking them here so they don't get lost.

## 1. INFY annual financials — current_liabilities NULL + unit mixing

`financials` table for INFY (and likely many other large caps) has
inconsistent units across data_source:

| period_end | data_source | total_assets | ebit | CL |
|---|---|---:|---:|---:|
| 2026-03-31 | yfinance | 1,644.6 | NULL | NULL |
| 2025-03-31 | yfinance | 1,741.9 | 39,236 | NULL |
| 2024-03-31 | NSE_XBRL | 1,652.3 (?) | 36,458 | 38,794 |
| 2024-09-30 | NSE_XBRL (q) | 141,870 | 18,488 | 40,830 |

The yfinance rows look like they're in INR billions (1,644 B = ₹1.64L Cr
which matches INFY's actual scale). The NSE_XBRL quarterly row is
clearly in Cr (141,870 Cr = ₹14.2L Cr — but that's TOO big for INFY).

Two bugs:
1. **Current liabilities NULL** on yfinance annual rows — the collector
   isn't extracting it from balance sheet statements properly.
2. **Unit mixing** — yfinance numbers stored as bare millions/billions,
   NSE_XBRL stored as Cr. Downstream consumers (ratios_service.compute_roce,
   tier2 enrichment, etc.) assume a single unit.

**Effect**: INFY ROCE returns None for tier 2 cohort enrichment (Bug 2
identified during PR #380 work). Likely affects all tickers with
yfinance-only annual rows. Spot-check a sample of large caps to size
the problem.

**Fix sketch**:
- Standardise to **Cr** at collector ingest time
- For yfinance: detect currency (raw `Currency` field) and convert
  USD/INR → standard
- Backfill 2-3 years of historical data after the schema fix
- Add a data-quality column flagging unit-of-origin (debug only)

**Priority**: medium. Doesn't block any single PR but degrades quality
across the cohort.

## 2. LICHOUSFIN missing from market_metrics

LICHSGFIN's `traditional_hfc` peer median was being skewed during the
PR #382 / #383 work because LICHOUSFIN had no rows in
`market_metrics` (despite being in `FINANCIAL_PEER_GROUPS`). The
collector / nightly job that populates market_metrics is skipping it
for some reason — possibly a ticker-symbol mismatch (LICHOUSFIN
historically traded under `LIC` or other variants).

**Effect**: PR #383's traditional_hfc bucket runs with only 2 of the
intended 3 peers (LICHSGFIN, PNBHOUSING) — diluting peer-median signal.

**Fix sketch**:
- Run the market_metrics collector manually for LICHOUSFIN and check
  the failure reason
- Add LICHOUSFIN to a "must-have-data" canary check that fails the
  nightly job if any FINANCIAL_PEER_GROUPS member returns 0 rows

## 3. HUDCO consensus is single-analyst

HUDCO has only 1 analyst on yfinance (target ₹225). Our model produced
₹128 (PR #381 calibrated). Model is probably right — 1 analyst is not
a reliable anchor. But the reconciliation report still flags HUDCO as
"under" 44% from consensus.

**Fix sketch**:
- Add a `min_analysts` threshold (>= 3) for outlier flagging — single-
  analyst consensus shouldn't trigger an outlier alert
- Or pull additional sources (Reuters, AceEquity, Damodaran) when
  yfinance consensus has < 3 analysts

## 4. Daughter-task: general_insurance breakdown

PR (this branch, cc850ab) split general_insurance into psu_gi /
private_gi / health_insurance. Validate post-deploy that:
- NIACL drops from `+174% over` to within ±25% of consensus
- GICRE drops from `+144% over` to similar tolerance
- ICICIGI / GODIGIT FVs stay close to current values (their bucket
  median didn't materially change)
- STARHEALTH unchanged (it was already in the old general_insurance
  bucket; just gets a tighter peer set now)

## 5. CACHE_VERSION audit

CACHE_VERSION = 117 throughout today's sprint. None of the PRs
(#376-#382, plus today's local commits) bumped it because each was
configuration-affecting, not response-shape-changing. Worth a
deliberate audit at Day 3 start: have we accumulated subtle shape
changes that should trigger a bump? Spot-check by diff'ing two
analyses on the same ticker pre/post-deploy.

---

Generated 2026-05-19 evening during a network-degraded session. The
local commits (CANFINHOME reclassify + GI split) will be pushed once
GitHub is reachable.
