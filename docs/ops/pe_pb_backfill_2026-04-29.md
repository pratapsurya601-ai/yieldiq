# PE / PB Backfill — 2026-04-29

One-shot backfill of `market_metrics.pe_ratio` and `market_metrics.pb_ratio`
for the full active universe (~2,918 .NS tickers).

Script: `scripts/data_patches/backfill_pe_pb_all_2026-04-29.py`

## RUN THIS

The actual data run takes ~30-60 minutes (rate-limited by yfinance at 1 req/sec
per thread, 5 threads). It must be executed by a human with the Neon
`DATABASE_URL` available locally — the script is committed without secrets.

```bash
# from repo root, on branch wkt/pe-pb-full-backfill
export DATABASE_URL="$(sed -n '2p' .env.local)"
# optional fallbacks; safe to omit
# export FINNHUB_API_KEY=...
# export FMP_API_KEY=...

python scripts/data_patches/backfill_pe_pb_all_2026-04-29.py --workers 5
```

The script is **resumable** — Ctrl-C is safe; re-running picks up from
`scripts/data_patches/_backfill_pe_pb_progress.json` (gitignored).

To inspect coverage without writing anything:

```bash
python scripts/data_patches/backfill_pe_pb_all_2026-04-29.py --stats-only
```

## Source cascade

For each ticker whose latest `market_metrics` row is missing `pe_ratio` or
`pb_ratio` (or has no row at all), the script tries:

1. **yfinance** `.info` -> `trailingPE`, `priceToBook`
2. **Finnhub** `/stock/metric?metric=all` -> `peTTM`, `pbAnnual`
   (only if `FINNHUB_API_KEY` is set)
3. **FMP** `/key-metrics-ttm/{symbol}` -> `peRatioTTM`, `pbRatioTTM`
   (only if `FMP_API_KEY` is set)

If a metric is missing from yfinance but present from Finnhub/FMP, the script
top-ups the missing metric (so you can end up with `pe` from yf + `pb` from
finnhub on the same ticker — both are written).

Sanity bound: PE / PB outside `(-1000, 10000)` is treated as junk and skipped.

## Write strategy

- Writes a row keyed by `(ticker, trade_date = today)` using
  `INSERT ... ON CONFLICT (ticker, trade_date) DO UPDATE SET
   pe_ratio = COALESCE(EXCLUDED.pe_ratio, market_metrics.pe_ratio), ...`.
- Idempotent: re-runs the same day overwrite nothing that was already filled.
- Never touches `market_cap_cr`, `ev_cr`, `ev_ebitda`, `dividend_yield`,
  `beta_*` — only the two target columns.

## Constraints honoured

- Neon only (no Aiven).
- No `CACHE_VERSION` bump.
- No changes under `backend/`, `models/`, `screener/`.
- Script and progress JSON live in `scripts/data_patches/`; progress JSON
  is gitignored.
- API keys read from env only; never written into the script.

## Results

> Fill in after running.

- Wall clock: _TBD_
- Tickers attempted: _TBD_
- Source counts (yf / yf+finnhub / yf+fmp / finnhub / fmp / untouchable): _TBD_
- Pre-fill latest-row coverage: pe=_TBD_  pb=_TBD_  total=_TBD_
- Post-fill latest-row coverage: pe=_TBD_  pb=_TBD_  total=_TBD_
- Estimated time savings: nightly cache warmup will skip ~_N_ tickers that
  now have valid PE / PB metrics.

### Top 20 untouchable tickers

> Fill in after running. Likely candidates: recent IPOs (no TTM yet),
> recently delisted, suspended, ticker symbol drift between NSE and yfinance.

| Ticker | Reason |
| --- | --- |
| _TBD_ | _TBD_ |
