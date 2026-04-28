# Diagnosis: market indices showing em-dashes in sidebar

**Date:** 2026-04-27 (~05:00 IST)
**Symptom:** NIFTY 50, SENSEX, and BANK NIFTY all render as `—` (em-dash) in
the `TickerStrip` on every page that mounts the analysis sidebar. ~6 hours
prior in the same browser session, real values were observed
(NIFTY 50 24,099.75 / SENSEX 77,224.05 / BANK NIFTY 56,270.45).

## Conclusion

**Operational, not a code regression.** No PR is required. The fix is a
worker / data-pipeline action on Railway + Aiven Postgres.

## Code path traced

1. **Frontend** — `frontend/src/components/analysis/TickerStrip.tsx`
   - `useQuery({ queryKey: ["market-pulse"], queryFn: () => getMarketPulse(false), retry: 0, staleTime: 5min })`.
   - Indices are pulled out via `byName` lookup; if `byName.get(name)` is
     `undefined` (i.e. the backend returned an empty `indices` array OR
     omitted that name), the component renders `<Cell value={"—"} />`.
   - Last meaningful change: commit `0481cc2` (2026-04-19) — only
     adjusted color classes and the literal `—` JSX bug. Logic for
     "no data → dash" is unchanged.

2. **Backend** — `backend/routers/market.py::get_market_pulse`
   - In-process raw-dict cache, key `market:pulse:raw:0`, TTL 60 s.
   - On miss, delegates to `DataService.get_market_pulse()`.

3. **DataService** — `backend/services/data_service.py::get_market_pulse`
   - Class-level cache with 5 min TTL (`_pulse_cache` / `_pulse_ts`).
   - For each of `("NIFTY 50","^NSEI")`, `("SENSEX","^BSESN")`,
     `("NIFTY Bank","^NSEBANK")`:
     - Try DB row via `market_data_service.get_index_snapshot(symbol)`.
     - On DB miss, fall back to `yfinance.Ticker(symbol).fast_info`.
     - On both failures, append `MarketIndex(name=name)` with
       `price=None` and `change_pct=None`.

4. **DB read** — `backend/services/market_data_service.py::get_index_snapshot`
   - Single SELECT against `index_snapshots` keyed by `symbol`.
   - Returns `None` only if the row is absent or session creation fails.

5. **Refresher** — `backend/workers/market_data_refresher.py`
   - `INDEX_SYMBOLS` includes the three indices in scope.
   - Scheduled via `backend/main.py::_start_pipeline_scheduler` →
     `_run_refresh_index_snapshots` on `CronTrigger(minute="*/15")`,
     **24×7, Asia/Kolkata**. UPSERT into `index_snapshots`.

## Why em-dashes are showing now

For every cell to render `—` simultaneously, *both* the DB read AND the
yfinance fallback must yield no usable price for all three symbols. That
narrows the root cause to one (or more) of:

| Hypothesis | Likelihood | Notes |
|---|---|---|
| **A. Refresher worker not firing** (APScheduler stuck / process restarted, last successful run fell off the 5-min in-process cache window) | **High** | Indices job is `*/15`, not gated by market hours, so a single missed tick leaves stale rows. If Railway recently restarted the API container, the in-process scheduler restarts cold; first tick on the `*/15` cron may not have fired yet at 05:00 IST. |
| **B. yfinance fallback failing from Railway egress at 05:00 IST** | Medium | Yahoo Finance 429s/blocks Railway IP ranges intermittently, especially outside US market hours. Combined with (A), no data lands in either path. |
| **C. `index_snapshots` row exists but `price IS NULL`** | Medium | `get_index_snapshot` returns the row even if `price` is null; `data_service` then keeps the `MarketIndex(name=...)` no-price fallback. Could happen if a refresher run hit yfinance, got a partial response, and wrote a null. |
| **D. Aiven Postgres connection pool exhaustion / DB session refused** | Low | Other endpoints would also be degraded; user only reported indices. |
| **E. Code regression** | **Excluded** | Last edit to relevant files: `0481cc2` (8 days ago, cosmetic). Today's only main commit `bc94632` disabled the digest/newsletter crons and **did not touch** `market_index_snapshots`, `data_service`, `market_data_service`, `market_data_refresher`, or `TickerStrip`. |

There is also an **architectural concern** worth flagging (out of scope
for this incident): `_start_pipeline_scheduler()` runs in-process inside
every uvicorn worker. Railway boots 4 workers, so the index-snapshot
refresher fires 4× per tick — same architectural defect the digest cron
was disabled for in commit `bc94632` today. For a read-only UPSERT into
`index_snapshots` this is benign (idempotent, bounded volume), but if
yfinance starts rate-limiting, having 4 concurrent calls per tick makes
the throttling worse.

## Recommended ops actions (in order)

1. **Check Railway logs** for the `yieldiq.market_data_refresher` logger
   over the last 2 hours. Look for:
   - `index_snapshots refresh failed: ...` (caught in `_run_refresh_index_snapshots`)
   - 429 / rate-limit errors from yfinance
   - Any "scheduler" startup messages indicating the API process was
     restarted recently.

2. **Inspect `index_snapshots` table directly** via Aiven psql:
   ```sql
   SELECT symbol, name, price, change_pct, as_of
   FROM index_snapshots
   WHERE symbol IN ('^NSEI','^BSESN','^NSEBANK')
   ORDER BY symbol;
   ```
   - If `as_of` is hours/days stale → refresher is not running. Restart
     the Railway API service to re-arm APScheduler.
   - If `price IS NULL` → bad upsert; manually run
     `python -m backend.workers.market_data_refresher` (or call
     `refresh_index_snapshots()` from a one-off Railway shell) to
     repopulate.
   - If row is absent → same fix.

3. **Manual repopulate** (fastest unblock):
   ```bash
   railway run --service yieldiq-api python -c \
     "from backend.workers.market_data_refresher import refresh_index_snapshots; refresh_index_snapshots()"
   ```
   Then bust the in-process cache by hitting the API or waiting 5 min
   for `_pulse_cache` to age out.

4. **If yfinance is the upstream blocker** (429 from Railway IP), the
   short-term workaround is to retry from a different egress (e.g. run
   the refresher once from a GitHub Action with `actions/runner`'s IP)
   so at least one good row lands; the in-process refresher will keep
   it warm thereafter.

## Why no code fix is being shipped

The two code-side improvements one might consider here are both
debatable and not launch-blockers:

- **Render last-known stale value with a "stale" badge instead of a
  dash.** Would require persisting the last good value client-side or
  surfacing `as_of` from the API. Reasonable feature, but the current
  honest-em-dash behaviour is intentional (per the in-file comment:
  "we honestly render em-dashes rather than inventing numbers").
- **Treat `price IS NULL` rows as DB-miss to force the yfinance
  fallback.** Mostly cosmetic; if yfinance is also failing (the actual
  root cause here) it changes nothing.

Neither addresses the actual problem, which is that no fresh data is
landing in `index_snapshots`. The fix is operational.
