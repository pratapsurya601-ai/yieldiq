# Price data architecture (Day-112, 2026-05-23)

## Why this document exists

For months, `daily_prices.adj_close` carried the value of
`close_price`. Three populators (`data_pipeline/sources/nse_bhavcopy.py`,
`scripts/backfill_daily_prices_gap.py`,
`scripts/backfill_daily_prices_legacy.py`) all had the same one-line
bug:

```python
"adj_close": close,   # WRONG — bhavcopy is unadjusted
```

`cagr_service.py` happily compared `close_price` 5 years ago vs
`close_price` today. RELIANCE shows a 1:5 bonus on 2017-07-19 and
a 1:1 bonus on 2024-10-28 — between them, raw closes drop ~10x
without any actual loss in shareholder value. The 5y stock-CAGR
endpoint thus rendered RELIANCE at `-7.8%`.

Day-112 makes this class of bug **structurally impossible to
ship silently** by separating the data layers, adding an audit
trail, and wiring an automatic nightly validator.

## End-to-end flow

```
┌─────────────────────────┐       ┌──────────────────────────┐
│ NSE bhavcopy (daily)    │──┐    │ NSE corp_actions feed    │
│ — unadjusted close      │  │    │ (download_corporate_     │
└─────────────────────────┘  │    │  actions)                │
                             │    └──────────────────────────┘
                             ▼                  │
                  ┌──────────────────────┐      │
                  │ daily_prices         │      │
                  │   close_price        │      │
                  │   adj_close = NULL   │      │
                  └──────────────────────┘      │
                             │                  │
                             │   ┌──────────────┴───────────────┐
                             │   │                              │
                             ▼   ▼                              │
            ┌─────────────────────────────────────────┐         │
            │ scripts/rebuild_adj_close.py            │◀────────┘
            │   1. fetch yfinance Adj Close           │
            │   2. derive from corp_actions table     │
            │   3. reconcile (>0.5% disagreement →    │
            │      log + conservative pick)           │
            │   4. UPDATE daily_prices.adj_close      │
            │   5. INSERT into price_adjustment_log   │
            └─────────────────────────────────────────┘
                             │
                             ▼
                  ┌──────────────────────┐
                  │ daily_prices         │
                  │   close_price        │
                  │   adj_close = <adj>  │  ◀── owned by rebuild script
                  └──────────────────────┘
                             │
                             ▼
            ┌─────────────────────────────────────────┐
            │ backend/services/cagr_service.py        │
            │   stock_panel reads adj_close ONLY      │
            │   (no silent fallback to close_price)   │
            └─────────────────────────────────────────┘
                             │
                             ▼
            ┌─────────────────────────────────────────┐
            │ /api/v1/public/stock-summary            │
            │   compounded_growth.stock = {           │
            │     "3y": +12.4, "5y": +18.1,           │
            │     "10y": null,                        │
            │     "status": "ok"                      │
            │   }                                     │
            └─────────────────────────────────────────┘
                             │
                             ▼
            ┌─────────────────────────────────────────┐
            │ scripts/validate_adj_close.py           │
            │ (nightly cron 02:00 UTC)                │
            │   if >5% of validator panel fails       │
            │   → open GitHub issue                   │
            └─────────────────────────────────────────┘
```

## Integrity checks at each layer

| Layer | Check | Failure surface |
| --- | --- | --- |
| Bhavcopy populator | Writes `NULL` into `adj_close` (never `close_price`) | Code review; PR diff against `'adj_close":` |
| `rebuild_adj_close.py` | Cross-validates yfinance vs corp_actions | `price_adjustment_log.source = 'reconciled'` row |
| `rebuild_adj_close.py` | Per-ticker exponential backoff on 429 | Dead-letter JSON if all retries fail |
| `cagr_service.py` | Returns `status='rebuild_pending'` when adj_close missing | Status field on API response |
| `cagr_service.py` | Sanity gate \|CAGR\| > 100% → None | Null cell in payload |
| Nightly workflow | 20 compounders must have CAGR in expected band | GitHub issue auto-filed |
| Nightly workflow | 20 under-performers must have CAGR in expected band | GitHub issue auto-filed |
| Admin endpoint | `tickers_with_null_adj_close` | Ops dashboard |
| Admin endpoint | `tickers_adj_equals_close_pct90` | Ops dashboard (regression signal) |

## Why two sources (yfinance + NSE corp actions)

A single source is a single point of failure:

* **yfinance** can mis-classify mergers as splits. Real example:
  HDFCBANK in July 2023 was treated as a ~2.12× split by Yahoo,
  halving every close in our pipeline (₹1,700 → ₹800). This is
  why the previous fix in `yf_downloader.py` set
  `auto_adjust=False` and kept raw close as the canonical
  pricing input — but the trade-off was no adjustment at all.
* **NSE corp_actions** can be incomplete for older history,
  ambiguous about ratio direction (1:2 vs 2:1), and slow to
  reflect amendments.

Reconciliation: when they disagree by >0.5% on any date, pick the
**more conservative** value (smaller delta from raw close) and log
the row. Operator can review via the admin endpoint.

The rebuild script falls back to yfinance-only when corp_actions
has no rows for a ticker — this is the common case (no splits,
no bonuses, no merger).

## What "broken" looks like at each layer

| Symptom | Likely cause |
| --- | --- |
| `tickers_with_null_adj_close > 0` | Rebuild script never ran for some tickers (newly added, or dead-letter). |
| `tickers_adj_equals_close_pct90 > 100` | A populator regressed — writing close into adj_close again. |
| `discrepancies_last_30d` spike | yfinance or NSE feed shifted; investigate `price_adjustment_log` for the offending tickers. |
| Validator fails on 5+ compounders | Whole rebuild produced wrong output. Roll back and rerun. |
| API returns `status='rebuild_pending'` for a known ticker | Rebuild missed it. Run `rebuild_adj_close.py --tickers <T>`. |
| `compounded_growth.stock.5y` = `null` while financials present | Either (a) ticker too young, or (b) `adj_close` not yet populated. Status field disambiguates. |

## Cache invalidation contract

Adding `compounded_growth.stock.status` is **additive** at the
response shape level (new field, no removed field). The Day-112
manifest entry is scoped to:

```python
"scope": {
    "tickers": "*",
    "fields": ["compounded_growth.stock", "stock_cagr_status"],
}
```

This invalidates the per-ticker `compounded_growth.stock` cell
for every cached stock-summary row predating the deploy — but
does NOT touch DCF, ratios, verdict, or any other field. Cost:
one CAGR recompute per ticker per cache row (cheap; the panel
is a few SQL queries).

`CACHE_VERSION` is **not** bumped. This entry sits inside the
manifest exactly as the Day-94 architecture intends.

## What was rejected

* **Auto-running the rebuild from Railway.** The job is multi-hour.
  Railway's worker tier will OOM or time-out. Runs externally.
* **Falling back to `close_price` when `adj_close` is NULL.** The
  whole pre-Day-112 bug was a silent fallback. Day-112 makes the
  fallback impossible: the status field forces the consumer to
  acknowledge "rebuild_pending" explicitly.
* **Bumping `CACHE_VERSION`.** Day-94 manifest exists exactly so
  we don't have to.
* **A live NSE corp-actions scrape inside the rebuild script.** We
  already ingest those via the bhavcopy daily job into
  `corporate_actions` — re-reading them is faster and avoids
  doubling the NSE API load.
