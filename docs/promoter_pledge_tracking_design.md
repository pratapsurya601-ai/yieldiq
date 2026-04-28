# Promoter pledge tracking — design

Status: scaffolding landed (PR `feat(governance): promoter pledge tracking — scaffolding`). Schema, service stubs, ingest skeleton, fixture-backed tests in place. **No real scraper yet.** No frontend integration yet.

## Why this matters

In Indian equities, promoter share pledging is governance signal #1. When a promoter group pledges its own shares as collateral for personal or group-level loans, two things happen: (a) the promoter has a strong incentive to prop up the share price (margin calls force liquidation, which can collapse the cap table); (b) the company's downside is now correlated with the promoter's *personal* leverage, not just the underlying business. The historical record is unambiguous — sharp jumps in pledged_pct preceded the Reliance Communications, Zee Entertainment, Future Retail, and DHFL collapses, often by 6–18 months. Domestic broker research desks all track this; foreign coverage (Bloomberg, Refinitiv) routinely misses it because the disclosures are India-specific and only published on BSE/NSE.

## Data sources

Both exchanges publish pledge disclosures publicly under SEBI (SAST) Reg. 31(1) and 31(2). No API key required, but both rate-limit aggressively.

| Source | URL | Format | Notes |
|---|---|---|---|
| BSE | https://www.bseindia.com/corporates/sastpledge.aspx | HTML form | Filter by scrip code (we already store `stocks.bse_code`). One disclosure per row, dated. Use `bse_shareholding_service.py` headers pattern. |
| NSE | https://www.nseindia.com/companies-listing/corporate-filings-pledge | JSON via `/api/corporate-pledgedata?index=equities` | Cookie-gated: GET landing page first to seed `requests.Session`. Single payload returns ALL recent disclosures across symbols — batch, don't loop. |
| Screener.in | https://www.screener.in/company/{symbol}/ | HTML, derived | Reasonable cross-check; not a primary source. |

## Schema

`data_pipeline/migrations/016_promoter_pledges.sql`:

```
promoter_pledges
  id BIGSERIAL PK
  ticker VARCHAR(20) FK -> stocks(ticker)
  as_of_date DATE                    -- disclosure date
  promoter_group_pct NUMERIC(6,3)    -- promoter holding % of company total
  pledged_pct NUMERIC(6,3)           -- of promoter holding, % pledged
  pledged_shares BIGINT
  source_url VARCHAR(500)
  fetched_at TIMESTAMPTZ DEFAULT NOW()
  UNIQUE(ticker, as_of_date)
INDEX (ticker, as_of_date DESC)
```

Convention: `pledged_pct` is the fraction of the **promoter holding** that's pledged, NOT the fraction of total shares outstanding. This matches BSE/NSE/screener.in. With `promoter_group_pct` stored alongside, we can reconstruct an "% of total" view downstream as `promoter_group_pct * pledged_pct / 100`.

## Service surface

`backend/services/promoter_pledge_service.py`:

- `get_latest_pledge(ticker) -> PledgeRow | None` — most recent snapshot.
- `compute_pledge_change_pp(ticker, lookback_days=90) -> float | None` — pp delta vs the last row on or before `latest - lookback_days`. Positive = pledging increased (the bad direction).
- `fetch_from_bse(ticker)` — stubbed; raises `NotImplementedError`.
- `fetch_from_nse(ticker)` — stubbed; raises `NotImplementedError`.

## Open implementation questions

1. **Refresh frequency.** Disclosures are event-driven (filed within 7 working days of any change), but a daily 06:00 IST cron is probably right — captures intraday-filed disclosures by next morning. Weekly is too slow for the leading-indicator use case. Hourly is overkill and risks NSE blacklisting our IP.
2. **Alerting threshold.** Suggested defaults to validate against historical data: warn at `pledged_pct > 25%` (absolute) OR `compute_pledge_change_pp(90) > +5pp` (rate). Need to backtest these against the 2018–2024 window.
3. **Historical backfill window.** BSE retains 5 years of disclosures publicly. NSE keeps ~2 years on the public endpoint. For the launch, 2 years is sufficient — enough to fit the 90d rate calc and a YoY chart. Going past that requires the BSE archive (paid) or screener.in scraping.
4. **Cross-check policy.** When BSE and NSE disagree on a single date (happens occasionally — different filings from the same promoter), which wins? Proposal: store both, last-write-wins on `(ticker, as_of_date)`, log the discrepancy. Don't silently pick one.
5. **Quarter-end vs event dates.** Some teams normalize to quarter-end. We're storing the actual disclosure date — gives us higher-resolution time series.
6. **"Promoter group" boundary.** When a promoter entity is itself an LLP/family-trust holding the shares on behalf of multiple individuals, the disclosure aggregates them. We trust the disclosure's aggregation; no further rollup logic needed.

## Frontend integration sketch (not built yet)

Two surfaces:

1. **Analysis page red-flag card** (`frontend/app/analysis/[ticker]/...`).
   New card in the governance/risk row, only rendered when `get_latest_pledge(ticker)` returns non-null. Two numbers: latest `pledged_pct` (color-coded: green <10%, amber 10–25%, red >25%) and `compute_pledge_change_pp(ticker, 90)` with a +/- arrow. Source link to the BSE/NSE filing.
2. **Hex Pulse axis** (`backend/services/hex_service.py`).
   Pulse already consumes shareholding deltas from `bse_shareholding_service`. Add pledge deltas as a Pulse component — a +5pp pledge increase in 90d should drag Pulse score down meaningfully, on par with a major shareholding cut by an institutional holder.

Screener and watchlist UIs can pick this up later from the same service helpers; nothing on either of those surfaces needs to block on this.

## Follow-up tasks

1. Implement `fetch_from_bse` against `https://www.bseindia.com/corporates/sastpledge.aspx`. Reuse the headers/Referer pattern from `bse_shareholding_service.py`. ~1 day incl. parsing.
2. Implement `fetch_from_nse` against `/api/corporate-pledgedata?index=equities`. Single batch fetch, group by symbol. ~half day.
3. Wire `scripts/ingest_pledges.py --source=nse --all` into the daily cron (06:00 IST) once both fetchers land.
4. Backtest alerting thresholds against the 2018–2024 historical window before exposing them as user-tunable.
5. Build the analysis-page red-flag card.
6. Add pledge deltas to the Pulse axis of the YieldIQ Hex.
