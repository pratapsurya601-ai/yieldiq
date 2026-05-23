# Runbook — Price data rebuild (`adj_close`)

_Last updated 2026-05-23 (Day-112)_

The canonical owner of `daily_prices.adj_close` is
`scripts/rebuild_adj_close.py`. Bhavcopy populators intentionally
write `NULL` into `adj_close` because bhavcopy is an unadjusted
feed and writing `close_price` into `adj_close` produced months of
broken stock CAGR (RELIANCE 5y rendered as -7.8% pre-Day-112).

This runbook covers:

1. [When to run the rebuild manually](#when-to-rebuild)
2. [How to run it](#how-to-run)
3. [Reading the audit log](#reading-the-audit-log)
4. [Investigating a `corp_action_discrepancy`](#investigating-a-discrepancy)
5. [Interpreting validator output](#interpreting-validator-output)
6. [Rollback procedure](#rollback)
7. [Admin dashboard endpoint](#admin-dashboard)

---

## When to rebuild

Run the rebuild script when any of the following are true:

* The nightly `adj_close_validation` workflow opens a GitHub issue.
* `GET /api/v1/admin/price-data-health` returns:
  * `tickers_with_null_adj_close > 0`, or
  * `tickers_adj_equals_close_pct90` is high (suggests bhavcopy
    populator regression — adj_close has been silently written
    from close_price again), or
  * `discrepancies_last_30d` shows a sudden spike, or
  * `last_successful_rebuild` is older than ~7 days.
* You added a batch of new tickers (e.g. via
  `scripts/sync_nse_active_universe.py`) — they will have NULL
  `adj_close` until the next rebuild.
* A corporate action lands on a name we already have in production
  (split / bonus). The next-day NSE corp-action ingest captures
  the event; running the rebuild for that single ticker propagates
  it into `adj_close`:

  ```bash
  DATABASE_URL=postgres://... python scripts/rebuild_adj_close.py \
      --tickers TCS
  ```

* You bumped `CACHE_VERSION` for any reason adjacent to price data
  (rare — most cache bumps don't need this).

Do NOT run the rebuild from Railway. It's a 2-4 hour job and the
Railway worker tier will time out. Run on a developer machine or a
long-lived GH Actions runner instead.

## How to run

Full universe (default):

```bash
DATABASE_URL=postgres://... python scripts/rebuild_adj_close.py
```

A subset of tickers:

```bash
DATABASE_URL=postgres://... python scripts/rebuild_adj_close.py \
    --tickers RELIANCE,TCS,HDFCBANK
```

Resume after a Ctrl-C / crash (skips tickers already marked
`status=ok` in `_rebuild_adj_close.checkpoint`):

```bash
DATABASE_URL=postgres://... python scripts/rebuild_adj_close.py --resume
```

Start fresh (deletes checkpoint + dead-letter):

```bash
DATABASE_URL=postgres://... python scripts/rebuild_adj_close.py --reset-checkpoint
```

Tune parallelism (default 5 workers; yfinance 429s aggressively
above ~10):

```bash
DATABASE_URL=postgres://... python scripts/rebuild_adj_close.py --workers 3
```

### Expected runtime

| Tickers   | Workers | Wall clock      |
| --------- | ------- | --------------- |
| 50        | 5       | ~5-10 min       |
| 500       | 5       | ~40-90 min      |
| ~2,400    | 5       | **2-4 hours**   |

### Artifacts left behind

* `_rebuild_adj_close.checkpoint` — per-ticker status + timestamp.
  Resumable. Safe to delete to force a full re-run.
* `_rebuild_adj_close.dead_letter.json` — tickers that failed
  permanently (after exponential-backoff retries). Inspect, then
  rerun those specific tickers manually.

## Reading the audit log

Every UPDATE to `daily_prices.adj_close` writes a row to
`price_adjustment_log`. To answer "why did `RELIANCE` 2020-08-12
adj_close change from X to Y?":

```sql
SELECT trade_date, close_price,
       adj_close_before, adj_close_after,
       adjustment_factor, source, corp_actions, rebuilt_at
FROM price_adjustment_log
WHERE ticker = 'RELIANCE' AND trade_date = '2020-08-12'
ORDER BY rebuilt_at DESC;
```

`corp_actions` is JSONB with the splits and bonuses in effect:

```json
{
  "splits": [{"ex_date": "2020-09-09", "ratio": "1:5", "factor": 5.0}],
  "bonuses": []
}
```

`adjustment_factor = adj_close_after / close_price` — the multiplier
applied to the raw close.

## Investigating a discrepancy

A row with `source = 'reconciled'` means yfinance's Adj Close and
our corporate_actions-derived adj_close disagreed by more than
0.5% on that date. The conservative value (smaller absolute
adjustment) wins.

Typical causes:

1. **Stale corporate_actions row.** NSE's feed sometimes posts
   amended ratios. Re-run `data_pipeline.sources.nse_bhavcopy.
   download_corporate_actions` then re-run the rebuild for the
   affected ticker.
2. **yfinance bug.** Yahoo has historically misclassified mergers
   as splits (e.g. July-2023 HDFC Ltd → HDFCBANK merger was treated
   as a ~2.12× split). When this happens, our derived series is
   the correct one — the reconciliation picks it automatically.
3. **A structural event (merger / demerger) the engine wasn't
   warned about.** Add a row to `corporate_actions` with one of
   the structural `action_type` values (`MERGER`, `DEMERGER`,
   `REVERSE_MERGER`, etc.) — see migration 041. Then re-run.

To find recent discrepancies:

```sql
SELECT ticker, trade_date,
       adj_close_before, adj_close_after, adjustment_factor,
       corp_actions, rebuilt_at
FROM price_adjustment_log
WHERE source = 'reconciled'
  AND rebuilt_at >= now() - interval '30 days'
ORDER BY rebuilt_at DESC
LIMIT 50;
```

## Interpreting validator output

`scripts/validate_adj_close.py` runs two pools:

* **COMPOUNDERS** — 20 names that MUST show a positive 5y CAGR
  (e.g. TCS in [+5%, +30%]). A FAIL here usually means
  `adj_close` was silently written from raw close (the Day-112
  bug), or the corp-action for a recent split/bonus is missing.
* **UNDERPERFORMERS** — 20 names whose 5y CAGR should be deeply
  negative or near-zero (e.g. VODAFONEIDEA, DHFL). A FAIL here
  means our adjustment math over-corrected.

Exit code 0 = >= 95% of judged tickers pass. CI fires on exit 1.

A SKIP status means we couldn't fetch any `adj_close` rows for
that ticker in the 14-day window around today — usually a delisted
name, or one added after the last rebuild.

## Rollback

The audit log is the rollback mechanism. For one ticker:

```sql
-- Restore the last-good adj_close from the audit log
UPDATE daily_prices dp
SET adj_close = log.adj_close_before
FROM (
    SELECT DISTINCT ON (ticker, trade_date)
        ticker, trade_date, adj_close_before
    FROM price_adjustment_log
    WHERE ticker = 'RELIANCE'
    ORDER BY ticker, trade_date, rebuilt_at DESC
) log
WHERE dp.ticker = log.ticker
  AND dp.trade_date = log.trade_date;
```

If the populator regresses (writes close into adj_close again)
and the audit log fills with garbage, the safest reset is:

```sql
-- Nuclear: NULL all adj_close, then rerun the rebuild from scratch.
UPDATE daily_prices SET adj_close = NULL;
```

Then re-run the rebuild script with `--reset-checkpoint`.

## Admin dashboard

`GET /api/v1/admin/price-data-health` (admin-only) returns the
ops-relevant snapshot:

```json
{
  "ok": true,
  "tickers_with_null_adj_close": 0,
  "tickers_adj_equals_close_pct90": 14,
  "discrepancies_last_30d": 3,
  "last_successful_rebuild": "2026-05-23T18:00:00+00:00",
  "recent_adjustments": [...]
}
```

`tickers_adj_equals_close_pct90 = 14` is normal — those are
tickers genuinely with no corporate actions in our window
(adj_close == close_price for them is correct). A spike here
(into the hundreds) is the signal that the populator regressed.
