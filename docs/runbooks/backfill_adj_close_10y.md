# Runbook — Phase F.2: 10-year adj_close backfill

**Script:** `scripts/backfill_adj_close_10y.py`
**Owner-on-call:** data-pipeline owner
**Expected wall-clock:** ~20 min for top-500 @ 5 workers (per F.1 audit §8)
**Audit:** `docs/diagnostics/phase-f-historical-depth-audit-2026-05-25.md`

## What this does

Backfills `daily_prices.adj_close` to 10y+ depth across the top-500
(or canary-333) universe by:

1. Fetching `yf.Ticker("SYM.NS").history(period="max", auto_adjust=False)`.
2. Reconciling against split/bonus events from `corporate_actions`.
3. **INSERT**-ing missing OHLC rows (Day-112's rebuilder only UPDATEd
   existing rows; F.2 extends with INSERT for tickers whose bhavcopy
   ingest started after 2021).
4. Appending each write to `price_adjustment_log` (audit trail).

## Pre-flight gates (script-enforced, audit §7)

The script will refuse to run if any gate fails:

| Gate | Threshold | What it catches |
|---|---|---|
| Sample-ticker yfinance depth | >=4 of 5 (`RELIANCE`, `TCS`, `INFY`, `HDFCBANK`, `NESTLEIND`) must return >=10y | yfinance regional cap on Indian symbols |
| Universe shallowness | <=30% of input universe may have `daily_prices.n_rows < 100` | NSE-bhavcopy ingest gap wider than expected |

If a gate fails the script exits with code 1, **logs the offending
tickers**, and recommends a follow-up (inflate runtime budget 4x, or
investigate the bhavcopy populator) before launching the full backfill.

## Operator commands

```bash
# 0. Set DB env. Whichever of Neon / Aiven currently owns financials.
export DATABASE_URL='postgres://...'

# 1. Smoke test (no writes). Confirms pre-flight gates and adjustment
#    math on 3 tickers in ~1 min.
python scripts/backfill_adj_close_10y.py \
    --tickers RELIANCE,TCS,HDFCBANK --dry-run

# 2. Real run, top-500.
python scripts/backfill_adj_close_10y.py \
    --tickers top-500 --workers 5

# 3. If interrupted, resume past the last-completed ticker (alpha-sorted).
python scripts/backfill_adj_close_10y.py \
    --tickers top-500 --workers 5 --resume-from MARUTI

# 4. Canary-only path (333 tickers, ~12 min).
python scripts/backfill_adj_close_10y.py --tickers canary-333

# 5. Custom list from a file (one ticker per line, # comments OK).
python scripts/backfill_adj_close_10y.py --tickers scripts/phase_f_top500.txt
```

## Post-backfill validation

```sql
-- Coverage histogram — expected to be heavy in `10y+` after F.2.
WITH u AS (SELECT unnest($1::text[]) AS ticker)
SELECT
  CASE
    WHEN n_rows = 0       THEN 'none'
    WHEN n_rows < 1250    THEN '<5y'
    WHEN n_rows < 1750    THEN '5-7y'
    WHEN n_rows < 2500    THEN '7-10y'
    ELSE '10y+'
  END AS bucket,
  COUNT(*) AS n_tickers
FROM (
  SELECT u.ticker, COUNT(dp.trade_date) AS n_rows
  FROM   u LEFT JOIN daily_prices dp ON dp.ticker = u.ticker
  GROUP BY u.ticker
) t
GROUP BY bucket
ORDER BY 1;

-- Adjustment-log activity for the run window.
SELECT source, COUNT(*) AS n_rows
FROM   price_adjustment_log
WHERE  inserted_at > now() - INTERVAL '4 hours'
GROUP BY source;
```

## Rollback

Each write is logged in `price_adjustment_log` with `adj_close_before`
+ `adj_close_after`. To roll back a window:

```sql
UPDATE daily_prices dp
SET    adj_close = log.adj_close_before
FROM   price_adjustment_log log
WHERE  log.ticker = dp.ticker
  AND  log.trade_date = dp.trade_date
  AND  log.inserted_at BETWEEN $1 AND $2;
```

(There is no automatic rollback for INSERTed rows — those are new
rows with no `_before` value. Operator must DELETE by
`(ticker, trade_date)` where the log row's `source` ends in
`+insert`.)

## Discipline reminders

- **Not Railway.** This is a 20-min job; Railway worker tier OOMs on
  multi-hour pipelines per `memory/feedback_yieldiq_discipline.md`.
  Run locally or on a long-lived GH Actions runner.
- **No CACHE_VERSION bump.** F.4 ships the manifest entry
  `v_phase_f_historical_depth_2026_05_25` covering this change.
- **Backup first.** Confirm a fresh `daily_prices` logical backup
  exists before launch. The script is idempotent + audited but a
  backup costs nothing.
