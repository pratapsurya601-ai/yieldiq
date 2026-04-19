# YieldIQ Data Strategy — Parity with Screener.in / Tickertape / Trendlyne

_Last updated: 2026-04-19_

## Current state (post-launch audit)

**What works today:**
- NSE + BSE price data (daily EOD) for ~2,970 active stocks via NSE bhavcopy ingestion
- BSE XBRL fetcher + yfinance fallback (see `data_pipeline/sources/bse_xbrl.py`,
  `data_pipeline/sources/yfinance_supplement.py`, `data_pipeline/run_fundamentals.py`)
- `Financials` table schema with quarterly + annual P&L / BS / CF fields
- `MarketMetrics` for derived PE / PB / EV-EBITDA / dividend yield / beta
- `ShareholdingPattern` for promoter / FII / DII holdings
- DCF fair value + MoS + scenarios per ticker — **this is our unique differentiator**

**What's missing vs peers:**
1. **Coverage** — Financials table is only backfilled for ~500 tickers (top-market-cap set).
   The remaining 2,400+ listed stocks have partial or no fundamental data.
2. **Historical ratios as time series** — we compute ratios on-the-fly from the latest
   `Financials` row. There's no `RatioHistory` table, so the frontend cannot render
   "ROE over 10Y" or "PE trend" charts that Screener serves as a baseline.
3. **Peer comparison** — we have sector classification on `Stock`, but no precomputed
   peer-group tables. A `/peers/{ticker}` endpoint would currently scan the whole
   stocks table on every request.
4. **API surface** — no public endpoints for historical financials / ratio series /
   peers. The analysis page renders only the current point-in-time snapshot.

## Strategy — 3 phases

### Phase 1 — Fill the gaps (ship this week)

**P1.1 — Run full fundamentals backfill**
  - Already-runnable: `DATABASE_URL=... python data_pipeline/run_fundamentals.py`
  - Processes all ~2,970 active stocks. BSE Peercomp primary, yfinance fallback.
  - Takes ~3-4 hours end-to-end (rate-limited to respect BSE).
  - Result: Financials table goes from ~500 → ~2,500+ tickers with at least 1Y history.

**P1.2 — Deepen historical depth to 10Y**
  - Existing XBRL pipeline (`data_pipeline/xbrl/pipeline.py`) fetches only 4-8 quarters per run.
  - Add `--years=10` flag to fetch 40 quarters per ticker (BSE XBRL archive supports this).
  - Runtime: ~6 hours for top-500 tickers at 10Y depth.
  - Result: Parity with Screener on historical P&L / BS / CF.

**P1.3 — Build `RatioHistory` table**
  - New model: one row per (ticker, period_end, period_type).
  - Columns: roe, roce, de_ratio, gross_margin, operating_margin, net_margin,
    fcf_margin, revenue_growth_yoy, pat_growth_yoy, pe, pb, ev_ebitda,
    dividend_yield, current_ratio, debt_ebitda, interest_coverage, asset_turnover.
  - Computed from `Financials` rows via `scripts/build_ratio_history.py`.
  - Indexed on (ticker, period_end DESC) for fast time-series queries.

**P1.4 — Build `PeerGroup` table**
  - New model: one row per (ticker, peer_ticker, rank).
  - Peer selection: same `sub_sector` (or `sector` if sub_sector missing) AND
    same `market_cap_category` (Large / Mid / Small).
  - Top-6 peers per ticker by market-cap proximity.
  - Built via `scripts/build_peer_groups.py`, rebuilt weekly by CI workflow.

**P1.5 — Public API endpoints**
  - `GET /api/v1/public/financials/{ticker}?period=annual|quarterly&years=10`
    → historic P&L + BS + CF as arrays ordered by `period_end DESC`.
  - `GET /api/v1/public/ratios-history/{ticker}?years=10`
    → same shape but for derived ratios.
  - `GET /api/v1/public/peers/{ticker}?limit=5`
    → array of peers with their current FV / MoS / score / ROE / PE for side-by-side.
  - All behind the existing public router's 1-hour edge cache.

**P1.6 — Frontend**
  - `HistoricFinancialsTable` component: P&L / BS / CF toggle, 5Y / 10Y toggle.
  - `RatioSparklines` component: small inline charts next to each current-value ratio.
  - `PeerComparisonCard` component: 5-column table on the analysis page.
  - All rendered Server-Side on `/stocks/{ticker}/fair-value` for SEO.

### Phase 2 — Fundamentals upgrades (next 2-3 weeks)

**P2.1 — Quarterly result feeds**
  - New BSE result-announcement scraper (daily CI workflow).
  - Triggers re-ingestion for tickers that announced results in the last 24h.
  - Guarantees we never serve a stale quarter after results drop.

**P2.2 — Segment-level data**
  - BSE XBRL carries `segment_revenue` / `segment_results` for many companies.
  - Parse + persist into new `SegmentFinancials` table.
  - Unlocks "consumer vs digital" split for companies like Bharti Airtel,
    "two-wheeler vs CV" for Bajaj Auto, etc. — Tickertape has this today.

**P2.3 — Shareholding history**
  - `ShareholdingPattern` today has only the current quarter. Backfill 5Y.
  - Power "promoter pledge rising" / "FII outflow" signals on the analysis page.

**P2.4 — Corporate actions enrichment**
  - Existing `CorporateAction` has bare data. Enrich with:
    - Dividend history table (ex_date, record_date, amount, yield).
    - Buyback history (offer size, completion, avg price).
    - Split/bonus timeline.

### Phase 3 — Data-quality moat (month 2+)

**P3.1 — Cross-source reconciliation**
  - For every ratio we serve, compute it from BOTH BSE XBRL and yfinance.
  - Flag discrepancies > 5% in a new `DataQualityFlag` table.
  - Run weekly; post-launch this becomes our competitive edge — _"our numbers
    are audited against two independent sources."_

**P3.2 — Restatement tracking**
  - When a company restates a prior quarter (e.g. auditor qualification,
    accounting standard change), our cached Financials row goes stale.
  - Store `filing_date` + `revision_number` + `restated_from` to detect.
  - Separate `FinancialsRevision` audit log.

**P3.3 — Sector-relative ratio normalization**
  - ROCE of 15% is "great" for a bank but "mediocre" for FMCG.
  - Compute sector percentiles per period, store in `SectorPercentiles`.
  - Drive color-coding on the analysis page: _"ROE = 22% (78th percentile
    in IT Services)"_ — a signal Screener doesn't surface.

## Data source ranking (by trust + cost)

| Rank | Source | Coverage | Cost | Latency | Notes |
|------|--------|----------|------|---------|-------|
| 1 | **BSE XBRL** | All listed | Free | Filed within T+45 days of quarter-end | Gold standard. SEBI-mandated. What peers use. |
| 2 | **NSE bhavcopy** | Daily prices all listed | Free | T+0 EOD | Already wired via `data_pipeline/nse_prices/` |
| 3 | **yfinance** | Most tickers | Free | ~real-time | Patchy for Indian market; use only for supplementation |
| 4 | **Finnhub / FMP** | Limited Indian | Paid subscription | ~real-time | Keep for intraday prices only |
| 5 | **Annual report PDFs** | Everything | Free but unstructured | T+90 days | Fallback-of-last-resort for small-cap gaps |

**Recommendation:** BSE XBRL as primary + NSE bhavcopy for prices + yfinance only
for gaps. This matches what Screener.in themselves use.

## Timeline + execution order

**Week 1 (this week):**
- Day 1 (today): ship Phase 1 schema + scripts + endpoints (this PR)
- Day 2: you run `run_fundamentals.py` + `build_ratio_history.py` +
  `build_peer_groups.py` against prod DB — ~8 hours of compute on your box
- Day 3: frontend components go live via Vercel; audit coverage; patch holes

**Week 2:** Phase 2.1 and 2.2 (quarterly feeds + segment data).

**Week 3:** Phase 2.3 and 2.4 (shareholding history + corporate actions).

**Month 2:** Phase 3.

## KPIs to track

1. **Coverage:** % of NSE-listed stocks with at least 5 years of Financials rows.
   _Target: 95% by end of week 2._
2. **Freshness:** median days since last Financials row update.
   _Target: under 30 days._
3. **Accuracy:** for top-50 tickers, absolute % difference between our ROE/ROCE/D-E
   and Screener.in's. _Target: under 5% on 90% of ratios._
4. **Coverage of ratio series:** % of tickers with at least 20 quarterly RatioHistory
   rows. _Target: 80% by end of week 1._

## Non-goals (deliberately not building)

- **Intraday tick data.** Expensive, not useful for long-term valuation app.
- **Options chain / Greeks.** Out of product scope.
- **Crypto.** Out of product scope.
- **Technical indicators as first-class citizens.** We surface a few (RSI, MACD)
  but this is a fundamentals app, not a charting platform.

---

_This doc lives with the code. Update it whenever strategy changes._
