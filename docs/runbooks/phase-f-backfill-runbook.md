# Runbook — Phase F combined: 10-year historical depth backfill

**Audit:** `docs/diagnostics/phase-f-historical-depth-audit-2026-05-25.md`
**Block:** Block II, Phase F
**Expected total wall-clock:** ~70 min (one weekend evening; block 2 hours).
**Sub-phases:** F.2 → F.3 → F.4, **strict order**.

## TL;DR

Three scripts in sequence, each gated by its own pre-flight, all
writing to the financials DB pointed at by `DATABASE_URL`:

| # | Phase | Script | Sub-runbook |
|---|---|---|---|
| 1 | F.2 | `scripts/backfill_adj_close_10y.py` | [backfill_adj_close_10y.md](./backfill_adj_close_10y.md) |
| 2 | F.3 | `scripts/backfill_financials_10y.py` | [backfill_financials_10y.md](./backfill_financials_10y.md) |
| 3 | F.4 | `scripts/regenerate_ratio_history_10y.py` | [regenerate_ratio_history_10y.md](./regenerate_ratio_history_10y.md) |

## Why this order matters

- **F.2 first.** ratio_history (F.4) consumes price series for market-
  metrics anchoring. Running F.4 before F.2 caches ratios off shallow
  price history.
- **F.3 second.** ratio_history derives from `financials`; running
  F.4 before F.3 caches off shallow financial history.
- **F.4 last** ships the manifest entry `v_phase_f_historical_depth_
  2026_05_25` covering `cagr_3y`, `cagr_5y`, `cagr_10y`,
  `ratio_history`, `compounded_growth`. The manifest entry is the
  signal to the read path that cached rows are now stale. If it
  ships before F.2/F.3 finish, the first warming read uses pre-
  backfill data and "fixes" the cache at the wrong value until the
  next invalidation.

## Pre-flight (operator, before sub-phase 1)

1. Pick the universe. `top-500` is the default; `canary-333` is
   smaller and safer for first run.
2. Confirm a fresh logical backup of `daily_prices`, `financials`,
   and `ratio_history` exists. Scripts are idempotent + audited
   (`price_adjustment_log`, source-precedence guards in
   `store_financials`) but a backup is cheap insurance.
3. Set `DATABASE_URL` to the financials DB.
4. Hardware: developer box or a long-lived GH Actions runner. NOT
   Railway (multi-tens-of-minutes job; Railway worker tier OOMs
   per `memory/feedback_yieldiq_discipline.md`).
5. For F.3 browser fallback (optional but recommended):
   ```bash
   pip install playwright playwright-stealth
   playwright install chromium
   ```

## Step 1 — F.2 (adj_close, ~20 min @ 5 workers)

```bash
# Smoke test
python scripts/backfill_adj_close_10y.py \
    --tickers RELIANCE,TCS,HDFCBANK --dry-run

# Real
python scripts/backfill_adj_close_10y.py --tickers top-500 --workers 5
```

Pre-flight gates the script enforces:
- >=4 of 5 sample tickers must yield >=10y from yfinance.
- <=30 % of input universe may have `daily_prices.n_rows < 100`.

See [backfill_adj_close_10y.md](./backfill_adj_close_10y.md) for
validation SQL + rollback.

## Step 2 — F.3 (financials, ~40 min)

```bash
# Smoke test
python scripts/backfill_financials_10y.py \
    --tickers RELIANCE,TCS,HDFCBANK --dry-run

# Real
python scripts/backfill_financials_10y.py --tickers top-500
```

Pre-flight gate the script enforces:
- <=20 % of input universe may have NULL `stocks.bse_code`.
- Circuit-breaker: aborts if >50 % of attempted tickers return 0
  rows on the direct API path.

Browser fallback (`BSEBrowserClient`) runs automatically for
tickers that returned 0 rows on the direct path.

See [backfill_financials_10y.md](./backfill_financials_10y.md).

## Step 3 — F.4 (ratio_history, ~5 min)

```bash
# Real
python scripts/regenerate_ratio_history_10y.py --tickers top-500
```

Post-regen validator warns when `ratio_history.pe_ratio` null-rate
exceeds 10 % per ticker (Phase A issue #546 watchlist).

The manifest entry `v_phase_f_historical_depth_2026_05_25` is shipped
in code with this PR. Once the deploy reaches prod, cached
`cagr_*` / `ratio_history` / `compounded_growth` are invalidated and
warmed on first read.

See [regenerate_ratio_history_10y.md](./regenerate_ratio_history_10y.md).

## Post-run validation

```sql
-- 1. adj_close depth histogram (expected to skew '10y+' post-F.2).
WITH u AS (SELECT unnest($1::text[]) AS ticker)
SELECT
  CASE WHEN n_rows = 0 THEN 'none'
       WHEN n_rows < 1250 THEN '<5y'
       WHEN n_rows < 1750 THEN '5-7y'
       WHEN n_rows < 2500 THEN '7-10y'
       ELSE '10y+' END AS bucket,
  COUNT(*) AS n_tickers
FROM (SELECT u.ticker, COUNT(dp.trade_date) AS n_rows
      FROM   u LEFT JOIN daily_prices dp ON dp.ticker = u.ticker
      GROUP BY u.ticker) t
GROUP BY bucket ORDER BY 1;

-- 2. financials annual depth (expected to skew '10y+' post-F.3).
WITH u AS (SELECT unnest($1::text[]) AS ticker)
SELECT u.ticker,
       SUM(CASE WHEN f.period_type='annual' THEN 1 ELSE 0 END) AS n_annual
FROM   u LEFT JOIN financials f ON f.ticker = u.ticker
GROUP BY u.ticker ORDER BY n_annual ASC LIMIT 25;

-- 3. ratio_history coverage post-F.4.
WITH u AS (SELECT unnest($1::text[]) AS ticker)
SELECT u.ticker, COUNT(*) AS n_rows
FROM   u LEFT JOIN ratio_history r ON r.ticker = u.ticker
                                   AND r.period_type='annual'
GROUP BY u.ticker ORDER BY n_rows ASC LIMIT 25;

-- 4. Canary-diff (the merge-blocking gate).
-- Run from a clean checkout against staging or prod replica.
python scripts/canary_diff.py
```

## Rollback

- **F.2:** restore from `price_adjustment_log` — see
  [backfill_adj_close_10y.md](./backfill_adj_close_10y.md).
- **F.3:** `financials` writes are UPSERTs guarded by source rank;
  there's no automatic undo. Restore from the logical backup taken
  pre-flight, or delete-by-source-and-window:
  ```sql
  DELETE FROM financials
   WHERE data_source IN ('BSE_PEERCOMP', 'BSE_PEERCOMP_BROWSER')
     AND inserted_at > $window_start;
  ```
- **F.4:** `ratio_history` is fully derived — rerun
  `build_ratio_history.py` against the previous-known-good
  `financials` snapshot.
- **Manifest entry:** revert the F.4 PR. The granular matcher will
  drop the entry; cached rows from before the entry's applied_at
  become valid again.

## Discipline reminders

- No CACHE_VERSION bump — F.4 manifest entry is the read-path signal.
- canary-diff GH Actions workflow blocks any FV swing > 15 % on the
  50 snapshot stocks. If a swing is expected (it isn't — F.2/F.3
  add data, they don't change formulas), document the rationale in
  the F.4 PR description.
- F.2 + F.3 are append-only data backfills; they are not expected to move
  any score / FV that wasn't already starved for inputs. Any
  movement on the canary panel is signal, not noise.
