# Runbook — Phase F.3: 10-year financials backfill

**Script:** `scripts/backfill_financials_10y.py`
**Owner-on-call:** data-pipeline owner
**Expected wall-clock:** ~25 min API path + ~16 min browser fallback
for the top-500 universe (per F.1 audit §8).
**Audit:** `docs/diagnostics/phase-f-historical-depth-audit-2026-05-25.md`

## What this does

Wraps `data_pipeline.sources.bse_xbrl.fetch_historical_financials`
(direct BSE Peercomp JSON API) and falls back to
`bse_peercomp_browser.BSEBrowserClient` (Playwright through Akamai
cookies) for tickers where the direct path returns zero rows.

Writes are UPSERTed into the single `financials` table; the
`period_type` column distinguishes annual vs quarterly. Source
precedence is `BSE_PEERCOMP` rank 30 (per
`db/migrations/006_data_quality_rank.sql`) — a previously-stored
`NSE_XBRL` row (rank 10) cannot be displaced.

## Pre-flight gate (script-enforced, audit §7)

| Gate | Threshold | What it catches |
|---|---|---|
| `stocks.bse_code` coverage | <=20% of input universe may have NULL/empty `bse_code` | Insufficient BSE↔NSE mapping; would silently leave 20%+ of universe at 5y depth |

If the gate fails, the script exits with code 1 and **logs the
offending tickers**. Operator action: populate `stocks.bse_code`
via `data_pipeline/sources/bse_securities_master.py` or
`scripts/backfill_bse_codes.py`, then re-launch.

## Direct-path failure circuit-breaker

If more than 50 % of attempted tickers return 0 rows on the direct
API (before fallback), the script exits with code 1 rather than
silently leaning on the browser fallback at scale — this catches a
sudden Akamai-block widening that operator must investigate.

## Operator commands

```bash
export DATABASE_URL='postgres://...'

# 1. Smoke test — 3 tickers, no writes, ~1 min.
python scripts/backfill_financials_10y.py \
    --tickers RELIANCE,TCS,HDFCBANK --dry-run

# 2. Real run, top-500 with browser fallback enabled (default).
python scripts/backfill_financials_10y.py --tickers top-500

# 3. Canary-333 only.
python scripts/backfill_financials_10y.py --tickers canary-333

# 4. Resume past a checkpoint.
python scripts/backfill_financials_10y.py \
    --tickers top-500 --resume-from MARUTI

# 5. Disable browser fallback (use only the direct API path).
python scripts/backfill_financials_10y.py \
    --tickers top-500 --no-browser-fallback

# 6. Polite-mode (1s between tickers if BSE rate-limits).
python scripts/backfill_financials_10y.py \
    --tickers top-500 --sleep 1.0
```

## Browser-fallback prerequisites

If `--no-browser-fallback` is NOT set, ensure Playwright is installed:

```bash
pip install playwright playwright-stealth
playwright install chromium
```

The browser fallback uses a single warm context across all queued
tickers (~3-4 s/ticker including Akamai cookie warmup).

## Row-count overlap validation

For each ticker, the script compares the new fetch against existing
`financials` rows and warns when:

- Revenue 3y rolling window has `stddev / mean > 0.5` (suggests a
  unit-scale shift or single-period spike).

Aggregate counter `rev_warnings` is printed at end of run. Investigate
any ticker that's flagged.

## Post-backfill validation

```sql
-- Annual depth histogram for the input universe.
WITH u AS (SELECT unnest($1::text[]) AS ticker)
SELECT
  CASE
    WHEN n_annual = 0  THEN 'none'
    WHEN n_annual < 5  THEN '<5y'
    WHEN n_annual < 7  THEN '5-7y'
    WHEN n_annual < 10 THEN '7-10y'
    ELSE '10y+'
  END AS bucket,
  COUNT(*) AS n_tickers
FROM (
  SELECT u.ticker,
         SUM(CASE WHEN f.period_type='annual' THEN 1 ELSE 0 END) AS n_annual
  FROM   u
  LEFT JOIN financials f ON f.ticker = u.ticker
  GROUP BY u.ticker
) t
GROUP BY bucket ORDER BY 1;

-- Source mix for the run window.
SELECT data_source, COUNT(*) AS n_rows
FROM   financials
WHERE  inserted_at > now() - INTERVAL '4 hours'  -- adjust to actual window
GROUP BY data_source;
```

## Known caveats (audit §5.2)

1. BSE Peercomp `bs_annual` rows do not expose
   `current_liabilities` reliably across the full universe. ROCE
   will be NULL for older years; F.4's validator flags this.
2. Source precedence guard means re-running F.3 will not overwrite
   NSE_XBRL rows (rank 10). If a previously-bad NSE_XBRL row needs
   refreshing, delete it manually first.

## Discipline reminders

- **Not Railway.** Multi-tens-of-minutes job; run locally or on a
  long-lived GH Actions runner.
- **No CACHE_VERSION bump.** F.4 ships the manifest entry.
- **Backup first.** Confirm a fresh `financials` logical backup
  exists before launch.
