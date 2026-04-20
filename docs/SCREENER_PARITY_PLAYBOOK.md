# Screener Parity — Where We Are + What's Next

Last updated: 2026-04-20 (post-session snapshot)

## What shipped in the 2026-04-20 session

### Data pipelines
| Phase | What | Status |
|---|---|---|
| A | BSE-only universe expansion via bhavcopy | ✅ Live |
| B | NSE bhav 2004-2015 → Parquet archive | ⏸ Deferred (NSE throttles 4 parallel) |
| C | Fundamentals 10Y via NSE XBRL | 🟡 Running (replaces dead BSE Peercomp) |
| D | Shareholding 5Y via NSE XBRL | 🟡 Running |
| E | Quarterly fundamentals | ✅ Folded into Phase C |
| F | Canary-diff gate | ✅ Workflow exists, passes on existing data |

### Infrastructure
- `scripts/archive_windowed_tables.py` + Sunday 09:00 IST cron — keeps Aiven <500MB
- `scripts/warm_prism_pages.py` + daily 09:30 IST cron — pre-renders SEO pages
- `scripts/parity_scorecard.py` + daily 10:30 IST cron — tracks progress vs Screener
- `backend/services/price_history_service.py` — unions PG + Parquet for 10Y charts
- `GET /api/v1/public/price-history/{ticker}` — long-range OHLC endpoint
- `scripts/keep_awake.ps1` — laptop sleep suppression

### Known dead paths (don't revisit without new info)
1. **BSE Peercomp JSON** (`api.bseindia.com/BseIndiaAPI/api/Peercomp/w`) — 302 → error_Bse.html. Akamai-walled from all IPs incl. GH Actions + residential.
2. **BSE Peer_Comparison.aspx** — 403 even from real Chromium+cookies+stealth
3. **BSE XBRL AttachLive** (raw XBRL PDFs) — WAF-blocked (signed-referer check we can't reproduce)
4. **BSE shareholding JSON** — same Akamai wall
5. **BSE bulk master `ListOfScripCode/w`** — 301 to error_Bse.html (bulk retrieval deprecated)

**Working fallbacks in order of priority:**
- BSE bulk master → per-ticker `PeerSmartSearch` (implemented ✅)
- BSE fundamentals → NSE `corporates-financial-results` + XBRL parse (implemented ✅)
- BSE shareholding → NSE `corporate-share-holdings-master` + XBRL (implemented ✅)
- BSE-only ticker fundamentals → **open gap** (those companies don't file on NSE)

---

## Tomorrow (priority order)

### 1. Dual-DB architecture — Aiven + Neon (~3 hrs)

**Why:** Aiven Hobby 20-slot cap keeps biting during concurrent ingestion. Moving writes to Neon (unlimited pooled) keeps frontend reads on Aiven (unchanged speed) without any slowdown.

**Steps:**

```bash
# 1. Create Neon project (user action) — neon.tech, region ap-south-1 (Mumbai)
#    Copy pooled URL into GH Actions secret NEON_DATABASE_URL

# 2. Clone schema to Neon
pg_dump --schema-only $AIVEN_DATABASE_URL > schema.sql
psql $NEON_DATABASE_URL < schema.sql

# 3. Seed initial data (stocks + last 90d hot tables only — not full dump)
pg_dump $AIVEN_DATABASE_URL -t stocks -t analysis_cache -t fair_value_history --data-only > hot.sql
psql $NEON_DATABASE_URL < hot.sql
python scripts/resync_pg_sequences.py  # with DATABASE_URL=neon url

# 4. Update ingestion scripts to use NEON_DATABASE_URL
#    Files to change: 
#      scripts/backfill_fundamentals_nse_xbrl.py
#      scripts/backfill_shareholding_history.py
#      scripts/backfill_daily_prices_legacy.py
#      scripts/ingest_bse_only_universe.py
#    Add: url = os.environ.get("NEON_DATABASE_URL") or os.environ["DATABASE_URL"]

# 5. Build sync job (new file: scripts/sync_neon_to_aiven.py)
#    For tables app reads: pull last 90d rows from Neon → upsert to Aiven nightly
#    ratio_history, peer_groups, analysis_cache cached entries rebuild on Aiven locally

# 6. Schedule sync
#    .github/workflows/sync_neon_to_aiven_nightly.yml — 02:00 UTC daily
```

**Validation:**
```bash
# Diff row counts
for t in financials shareholding_pattern; do
  A=$(psql $AIVEN_DATABASE_URL -tA -c "SELECT COUNT(*) FROM $t")
  N=$(psql $NEON_DATABASE_URL -tA -c "SELECT COUNT(*) FROM $t")
  echo "$t: aiven=$A neon=$N"
done
```

### 2. Close the BSE-only fundamentals gap (~2 hrs)

The ~2,500 BSE-only tickers added by Phase A have ticker+name+ISIN but no fundamentals because NSE doesn't file them. Options:

**Option A (recommended):** Use yfinance's `Ticker("{SYMBOL}.BO")` — usually returns 4-5Y. Write `scripts/backfill_fundamentals_bse_only_yf.py`. Won't reach 10Y but covers the visible gap.

**Option B:** Screener.in scrape — 12Y depth, but ethically gray (competitor). User vetoed this 2026-04-20.

**Option C:** Playwright with human-mimicking behavior (mouse movement, scroll, dwell) to pass BSE's Akamai. Would need ~1 week of iteration.

### 3. Retry Phase B (pre-2016 prices) with correct parallelism (~1 hr)

The cancelled 2004-2015 bhav backfill needs `max-parallel: 1` or explicit single-job processing. Edit workflow, retrigger. Low value — only top-500 tickers would benefit, and most charts don't go back that far.

### 4. Frontend wiring — 10Y price chart (~45 min)

Add a "10Y" toggle to the technical chart on `/stocks/{ticker}/fair-value` that calls `GET /api/v1/public/price-history/{ticker}?start=YYYY-MM-DD`. The backend endpoint already unions PG + Parquet.

### 5. Canary re-baseline (~30 min)

Once post-parity data lands:
```bash
python scripts/snapshot_50_stocks.py  # new baseline
```
Commit the snapshot. Next 7 nightly canary runs compare against this, then parity is "blessed."

---

## Parity scoreboard ETA

| Metric | Current | Post-tonight | Post-tomorrow |
|---|---:|---:|---:|
| Universe | 3,068 | ~5,500 | ~5,500 |
| 10Y annuals | 0 | ~2,500 | ~2,500 (+ 1,500 yf 4-5Y) |
| 5Y annuals | 11 | ~3,000 | ~4,500 |
| Quarterly | 0 | ~2,800 | ~4,000 |
| 5Y shareholding | 89 | ~3,500 | ~3,500 |
| PE coverage | 31.6% | ~75% | ~85% |
| **Overall parity** | **28.8%** | **~70%** | **~80%** |

The last ~15% gap to full Screener parity is structural:
- Delisted/inactive stocks (irrelevant for a valuation app)
- 20Y price history for microcaps
- Paid data (concalls, credit ratings)

## Key runbook commands

```bash
# Trigger any phase manually
gh workflow run phase_c_nse_xbrl.yml -f shards=4
gh workflow run phase_d_shareholding_5y_all.yml -f shards=2
gh workflow run phase_a_bse_universe.yml

# Force parity scorecard now
python scripts/parity_scorecard.py

# Full rebuild chain locally
bash scripts/rebuild_chain.sh

# Canary (requires CANARY_AUTH_TOKEN env)
python scripts/canary_diff.py --api-base https://api.yieldiq.in
```
