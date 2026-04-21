# YieldIQ — yfinance Independence Audit (2026-04-22)

## TL;DR

- **44 prod-impacting callsites** (not 152 like initial raw grep suggested — dashboard/scripts are legacy/one-shot)
- **80% can be replaced in ~2 weeks** via existing own-data + Kite Connect
- Cost: **₹2,000/month** (Kite Connect)
- No complete removal — keep yfinance as a **fallback-only** source with Sentry alerting when it fires

## Scope split

| Bucket | Callsites | Notes |
|---|---|---|
| Backend (prod API) | 23 | User-impacting. Top priority. |
| `data/collector.py` | 6 | The central collector — biggest ROI file |
| `data_pipeline/sources/` | 5 | Batch ingestion |
| `data_pipeline/xbrl/` | 3 | XBRL enrichment |
| `screener/` | 5 | Screener endpoint (still used) |
| `utils/config.py` | 1 | Config helper |
| **Dashboard (Streamlit, legacy)** | 22 | **Can ignore** — not hit by production users |
| **One-time scripts** | 8 | **Can ignore** — ran once per backfill |
| **XBRL test/probe files** | 2 | **Can ignore** — dev tools |

## Replacement buckets — by call pattern

### 🔴 Bucket A — `fast_info` live quotes (10 prod callsites)

**Purpose:** current price, market cap, trading-day high/low, 52-week range.

**Current problem:** `fast_info` is yfinance's "less rate-limited but still fragile" accessor. Hits Yahoo, can stale in real-time, breaks whenever Yahoo shifts schema.

**Replacement: Zerodha Kite Connect** (₹2K/mo)
- API: `kite.quote(["NSE:TCS", "NSE:INFY"])` returns real-time LTP, volume, OHLC, market depth
- Batch up to 500 symbols per call (vs yfinance's 1-at-a-time)
- Built for Indian markets (unlike yfinance which treats India as an afterthought)

**Callsites (prod only):**
| File:Line | Purpose | Replacement |
|---|---|---|
| `backend/routers/admin.py:159` | Admin dashboard quote check | `kite.quote("NSE:{t}")` |
| `backend/services/alert_service.py:193` | Alert evaluator | `kite.quote(["NSE:{ticker}"])` — already batch-friendly |
| `backend/services/data_service.py:81` | VIX price | `kite.quote("NSE:INDIAVIX")` |
| `backend/services/macro_service.py:167` | USDINR rate | RBI reference rate API (better source than yfinance anyway) |
| `backend/services/macro_service.py:188,208,213` | NIFTY / NSEMDCP50 / NSMIDCP150 indices | `kite.quote(["NSE:NIFTY 50", "NSE:NIFTY MIDCAP 50", ...])` |
| `backend/workers/market_data_refresher.py:116,192,245` | Bulk price refresh worker | `kite.quote([batch of 500])` — massive win here |

**Migration effort: 2-3 days.** New `backend/services/quote_service.py` wraps Kite, every callsite becomes `from quote_service import get_quote; q = get_quote("TCS")`.

---

### 🟡 Bucket B — `.info` metadata (6 prod callsites)

**Purpose:** sector, industry, long business description, website, number of employees. This data **rarely changes** (once per year at most).

**Current problem:** hit Yahoo every request just for strings that don't change. Slow, fragile, wasteful.

**Replacement: Static table + one-time backfill**

Add columns to `stocks` table (you already have `stocks.industry`, add the rest):
```sql
ALTER TABLE stocks
  ADD COLUMN IF NOT EXISTS business_summary TEXT,
  ADD COLUMN IF NOT EXISTS website TEXT,
  ADD COLUMN IF NOT EXISTS employees INTEGER,
  ADD COLUMN IF NOT EXISTS logo_url TEXT,
  ADD COLUMN IF NOT EXISTS metadata_updated_at TIMESTAMPTZ;
```

Backfill: use your existing `scripts/enrich_stocks_sector_yf.py` as a template — one-shot run, then refresh monthly via GH Actions.

Source options (ranked):
1. **NSE company master** — free, official — name, sector, ISIN, listing date
2. **BSE company master** — similar
3. **Scrape company websites** for logos (or use Clearbit's logo API — free for basic)
4. yfinance as fallback — last resort

**Callsites (prod only):**
| File:Line | Purpose | Replacement |
|---|---|---|
| `backend/services/analysis_service.py:2943` | Fallback info lookup | Use static table; yfinance fallback stays |
| `data_pipeline/sources/yf_info_cache.py:107` | Already has a CACHE layer — extend TTL to 30 days | Just bump `TTL` — you're already caching |
| `screener/ev_ebitda.py:103` | EV/EBITDA peer lookup | Use static table |
| `screener/fcf_yield.py:85` | FCF yield peer lookup | Use static table |
| `screener/sector_relative.py:260` | Sector relative valuation | Use static table |
| `data_pipeline/xbrl/test_adr_fix.py:23` | Test file | Can remove |

**Migration effort: 1-2 days** (backfill script + table + code updates).

---

### 🟢 Bucket C — `.history()` / `yf.download()` historical OHLCV (4 prod callsites)

**Purpose:** historical price series for volatility, returns, chart data.

**Current problem:** **This is the one you're MOSTLY already done with** — `nse_bhavcopy.py` fetches daily OHLCV and writes to `daily_prices`. The remaining callsites are gaps or unintentional.

**Replacement: Your existing `DailyPrice` table.** Zero new infrastructure needed.

**Callsites (prod only):**
| File:Line | Purpose | Replacement |
|---|---|---|
| `backend/routers/analysis.py:973` | `/chart-data` endpoint historical | Query `daily_prices WHERE ticker = :t AND trade_date >= :start` |
| `backend/routers/pipeline.py:311` | Method 2 fallback `yf.download` | Already has Method 1 (bhavcopy). Make Method 1 authoritative. |
| `data_pipeline/nse_prices/yf_downloader.py:48` | `yf.Ticker().history` — secondary source | Already a secondary; just promote bhavcopy to primary |
| `data_pipeline/sources/yfinance_supplement.py:*` | Supplement fetch (the one with the session-rollback fix today) | Reduce scope — only fetch fields bhavcopy doesn't have (e.g., adjusted close for splits) |

**Migration effort: 1 day.** Mostly removing fallbacks and pointing to `daily_prices` table reads.

---

### 🔵 Bucket D — `yf.Ticker(...)` object access (24 prod callsites)

This is the long tail — `t = yf.Ticker(...)` instantiated and then various fields accessed. Each needs individual inspection because some use `.balance_sheet`, some use `.income_stmt`, some use `.get_shares_full`, etc.

**Replacement strategies (per subfield):**

| yfinance field | Replacement |
|---|---|
| `.balance_sheet`, `.income_stmt`, `.cash_flow` | **`company_financials` table** (XBRL-sourced, already populated for Indian tickers) |
| `.get_shares_full()` | NSE corporate actions — you fetch these already |
| `.calendar` (earnings date) | NSE/BSE corporate announcements |
| `.dividends` | `corporate_actions` table (you have this) |
| `.splits` | `corporate_actions` table |
| `.actions` | `corporate_actions` table |
| `.news` | Separate problem — Finnhub already configured OR scrape Moneycontrol |
| `.fast_info.market_cap` | Derived: `shares × live_quote` (Kite Connect) |

**Top files in this bucket:**

| File | Callsites | Priority |
|---|---|---|
| `data/collector.py` | 6 | 🔴 HIGHEST — this is the central flow. Refactor this first and you eliminate ~half of other callsites transitively. |
| `backend/routers/pipeline.py` | 3 | High — pipeline ingestion path |
| `backend/services/data_service.py` | 3 | High — authed data fetches |
| `backend/services/dividend_service.py` | 1 | Medium — has `corporate_actions` fallback |
| `backend/services/financials_service.py` | 1 | Low — already has XBRL primary |
| `backend/services/hex_service.py` | 1 | Low — check what it's fetching, likely a peer lookup |
| `backend/services/news_service.py` | 1 | Low — news is a secondary feature |
| `backend/services/portfolio_service.py` | 1 | Medium — portfolio page |
| `backend/services/pulse_data_service.py` | 1 | Low — macro/pulse |

**Migration effort: 3-5 days** to do them all properly.

---

## Recommended execution order (2-3 week plan)

### Week 1 — Quick wins (no new cost)

1. **Day 1: Flip `yf_info_cache.py` TTL from whatever-it-is to 30 days.** 15-min change, immediate reduction in yfinance hit volume.
2. **Day 2: Kill `.history()` callsites.** Point `backend/routers/analysis.py:973` and the yfinance_supplement historical calls to `daily_prices` table. Keep yfinance as fallback with 3s timeout.
3. **Day 3-4: Refactor `data/collector.py`.** This is the central fan-out. Once clean, ~10 downstream callsites inherit the fix.
4. **Day 5: Stabilize.** Watch Sentry for `data_source=yfinance_fallback` tagging — identify remaining stragglers.

### Week 2 — Kite Connect integration (₹2K/mo kicks in)

1. **Day 1: Sign up for Zerodha Kite Connect.** Note: requires a Zerodha trading account (you probably already have one).
2. **Day 2-3: New `backend/services/quote_service.py`** wrapping `kite.quote()` / `kite.ltp()`. Cache responses for 5 seconds (market data doesn't need millisecond freshness).
3. **Day 4: Replace `fast_info` callsites** — start with `macro_service.py` (4 callsites, all indices — highest hit rate).
4. **Day 5: `market_data_refresher.py`** — biggest batch win. Was hitting yfinance 500 times sequentially; now one `kite.quote()` batch call.

### Week 3 — Metadata + long tail

1. **Day 1-2: `stocks` table extension** + one-time backfill of sector/industry/description for all 2000+ tickers.
2. **Day 3: Update `.info` callsites** to read from the extended `stocks` table.
3. **Day 4-5: Remaining `yf.Ticker(...)` callsites** — each one ~30 min if the replacement data is already in your DB.

### Ongoing

- **Sentry tag every yfinance call** with `data_source=yfinance`. Target: <1% of requests tagged within 30 days. >5% = pipeline regression.
- **Monthly `stocks.metadata_updated_at` refresh** via GH Actions (1 hour/month).

---

## Cost comparison

| Option | Monthly cost | Reliability | SLA |
|---|---|---|---|
| **Today (yfinance only)** | ₹0 | 🔴 Poor | None |
| **Hybrid (yfinance + DailyPrice + XBRL)** ← YOU ARE HERE | ₹0 | 🟡 Medium | Partial |
| **Hybrid + Kite Connect** | ₹2,000 | 🟢 Excellent | Zerodha's SLA |
| Full institutional (Refinitiv / Bloomberg) | ₹10L+ | 🟢 Excellent | Enterprise |

**Recommendation:** Hybrid + Kite Connect. Get to ~95% data independence for ₹24K/yr. Bump to institutional only if you hit 100K+ users or need options/F&O data.

---

## Data-quality moat (free side-benefit)

Once you're on your own pipeline, you can build things yfinance users cannot:

1. **Confidence scores per metric** — "₹3,465 FV — high confidence (3 sources agree, data <30 days)"
2. **Historical accuracy tracking** — publish "YieldIQ called 68% of flagships within ±15% over 12 months"
3. **Source transparency** — "This ratio sourced from NSE XBRL Q4 FY25 filing, last updated Apr 5"
4. **"Verified by YieldIQ" badge** — implicit reliability brand

None of these are possible while yfinance is your primary source. All of them are free marketing.

---

## What I'd actually do this weekend (4-hour session)

1. **Run `yf_info_cache.py` TTL bump** — 15 min
2. **Kill 2-4 `.history()` callsites** — 2 hours (test against prod)
3. **Sign up for Kite Connect developer account** — 30 min (no code yet, just account)
4. **Audit the `data/collector.py:72-82` `_yf_ticker` helper** — understand what goes through it — 1 hour

That alone removes ~30% of yfinance dependency. The rest can wait until you have the 500 users to justify the Kite ₹2K/mo spend.

---

*Audit generated 2026-04-22. See `yfinance_audit_20260422.txt` for the raw grep output.*
*Raw count: 79 callsites. Prod-impacting: 44 callsites. Dashboard (Streamlit legacy): 22. One-time scripts: 13.*
