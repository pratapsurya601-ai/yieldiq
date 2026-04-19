# Data Coverage Runbook — One-Time Backfill + Ongoing Ops

This is the operator runbook for bringing YieldIQ's data coverage to parity
with Screener.in / Tickertape / Trendlyne. Walk through it in order the
first time, then the last section becomes your ongoing ops reference.

---

## Prerequisites

You need, on whatever box runs these commands (your laptop is fine):

1. **Python 3.11+** with the `dcf_screener` conda env (or any env with
   `sqlalchemy`, `psycopg2-binary`, `requests`, `pandas`, `yfinance`).
2. **Aiven Postgres read+write DATABASE_URL.** Get it from Aiven CLI:
   ```bash
   avn service cli yieldiq-pg --json | jq -r '.service_uri'
   ```
   You'll paste this as `DATABASE_URL=postgres://...` in the commands below.
3. **BSE API reachability** — the XBRL fetcher hits `api.bseindia.com`
   directly. If your ISP blocks, run from a VPN or from Railway shell.

---

## One-time Phase-1 backfill (takes ~8 hours total)

Run these three scripts in order. They're idempotent — safe to re-run
if anything hiccups.

### Step 1 — Apply migration 005 to Aiven

```bash
# From the repo root
psql "$DATABASE_URL" -f data_pipeline/migrations/005_ratio_history_peer_groups.sql
```

Expected output:
```
CREATE TABLE
CREATE INDEX
CREATE INDEX
CREATE TABLE
CREATE INDEX
```

Verify:
```bash
psql "$DATABASE_URL" -c "\dt ratio_history peer_groups"
```

### Step 2 — Financials backfill (~3-4 hours)

This runs the existing `run_fundamentals.py` — BSE Peercomp primary,
yfinance fallback. Populates the `financials` table for every active
stock.

```bash
export DATABASE_URL="postgres://..."  # paste your Aiven URI
python data_pipeline/run_fundamentals.py 2>&1 | tee logs/fundamentals_$(date +%Y%m%d_%H%M).log
```

Tail the log while it runs. Progress prints every ticker. If you
Ctrl-C, restart — the script skips tickers already ingested from BSE.

When it completes, verify coverage:
```bash
psql "$DATABASE_URL" -c "
  SELECT COUNT(DISTINCT ticker) AS tickers_with_financials,
         MIN(period_end) AS earliest,
         MAX(period_end) AS latest
  FROM financials;
"
```

Target: **2,000+ distinct tickers**, earliest at least 5 years back.

### Step 3 — Ratio history build (~20 min)

```bash
export DATABASE_URL="postgres://..."
python scripts/build_ratio_history.py --all 2>&1 | tee logs/ratios_$(date +%Y%m%d_%H%M).log
```

Processes every ticker with financials. Computes derived ratios per
(ticker, period_end, period_type) and UPSERTs into `ratio_history`.

Verify:
```bash
psql "$DATABASE_URL" -c "
  SELECT COUNT(DISTINCT ticker) AS tickers,
         COUNT(*) AS rows,
         AVG(CASE WHEN roe IS NOT NULL THEN 1 ELSE 0 END) AS roe_coverage,
         AVG(CASE WHEN roce IS NOT NULL THEN 1 ELSE 0 END) AS roce_coverage
  FROM ratio_history;
"
```

Target: **2,000+ tickers, 40,000+ rows, ROE coverage > 90%, ROCE > 70%**.

### Step 4 — Peer groups (~5 min)

```bash
export DATABASE_URL="postgres://..."
python scripts/build_peer_groups.py --all 2>&1 | tee logs/peers_$(date +%Y%m%d_%H%M).log
```

Builds top-6 peers per ticker based on same sub_sector + market-cap proximity.

Verify:
```bash
psql "$DATABASE_URL" -c "
  SELECT COUNT(DISTINCT ticker) AS tickers_with_peers,
         AVG(num_peers) AS avg_peers_per_ticker
  FROM (
    SELECT ticker, COUNT(*) AS num_peers
    FROM peer_groups
    GROUP BY ticker
  ) t;
"
```

Target: **2,000+ tickers, average 5-6 peers**.

### Step 5 — Hit a public endpoint to verify frontend sees data

```bash
curl -s "https://api.yieldiq.in/api/v1/public/financials/RELIANCE.NS?years=5" | jq '.periods | length'
# expect >= 5

curl -s "https://api.yieldiq.in/api/v1/public/ratios-history/RELIANCE.NS?years=10" | jq '.periods | length'
# expect >= 10

curl -s "https://api.yieldiq.in/api/v1/public/peers/RELIANCE.NS?limit=5" | jq '.peers | length'
# expect 5
```

Then open https://yieldiq.in/stocks/RELIANCE.NS/fair-value and you should
see the three new sections (historical financials, ratio sparklines,
peer comparison).

---

## Set up GitHub Actions secrets (one-time)

The CI workflows can't run without `DATABASE_URL`.

```bash
gh secret set DATABASE_URL --body "$DATABASE_URL" --repo pratapsurya601-ai/yieldiq
```

Or manually: GitHub → Settings → Secrets and variables → Actions → "New
repository secret" → name `DATABASE_URL`, value = your Aiven URI.

---

## Ongoing ops (after Phase-1 is done)

### Automatic — runs on GitHub Actions

| Workflow | Schedule | Purpose |
|----------|----------|---------|
| `ratio_history_daily.yml` | 03:30 UTC daily | Rebuild ratio_history from latest financials + market_metrics |
| `peer_groups_weekly.yml` | 04:00 UTC Sun | Rebuild peer groups |
| `fundamentals_backfill_chunked.yml` | existing | Incremental XBRL ingestion for new filings |
| `cache_warmup_top500.yml` | 3× per weekday | Warm analysis_cache for top 500 by market cap |

If `ratio_history_daily` goes red for more than 2 days, the derived
ratios fall out of sync with the financials table and users see stale
growth rates. Check the workflow logs and rerun manually:

```bash
gh workflow run ratio_history_daily.yml --repo pratapsurya601-ai/yieldiq
```

### Manual — when you need to fix a ticker

Ticker `X` looks wrong on the SEO page? Check in this order:

1. **Is it in `stocks`?**
   ```bash
   psql "$DATABASE_URL" -c "SELECT * FROM stocks WHERE ticker = 'X';"
   ```
   If no → it's not in our universe. Add it via `data_pipeline/populate_stocks.py`.

2. **Does it have `financials`?**
   ```bash
   psql "$DATABASE_URL" -c "
     SELECT period_end, period_type, revenue, pat
     FROM financials WHERE ticker = 'X'
     ORDER BY period_end DESC LIMIT 10;
   "
   ```
   If sparse → manually refetch:
   ```bash
   python -c "
   from data_pipeline.sources.bse_xbrl import get_bse_scrip_code, fetch_historical_financials, store_financials
   from data_pipeline.db import Session
   s = Session()
   scrip = get_bse_scrip_code('<ISIN of X>')
   fetch_historical_financials(s, 'X', scrip, years=10)
   store_financials(s, 'X', ...)  # see run_fundamentals.py for the full flow
   "
   ```

3. **Does it have `ratio_history`?**
   ```bash
   psql "$DATABASE_URL" -c "
     SELECT period_end, roe, roce, de_ratio, pe_ratio
     FROM ratio_history WHERE ticker = 'X'
     ORDER BY period_end DESC LIMIT 10;
   "
   ```
   If sparse → rebuild just this ticker:
   ```bash
   python scripts/build_ratio_history.py --tickers X
   ```

4. **Does it have `peer_groups`?**
   ```bash
   psql "$DATABASE_URL" -c "SELECT * FROM peer_groups WHERE ticker = 'X';"
   ```
   If empty → rebuild just this ticker:
   ```bash
   python scripts/build_peer_groups.py --ticker X
   ```

5. **Clear the public cache so users see the fix immediately:**
   ```bash
   curl -X POST "https://yieldiq.in/api/revalidate?secret=$REVALIDATE_SECRET" \
     -H 'content-type: application/json' \
     -d '{"path":"/stocks/X.NS/fair-value"}'
   ```

---

## Metrics dashboard queries

Run these weekly to monitor health.

### Coverage (how many tickers have data)

```sql
SELECT
  (SELECT COUNT(*) FROM stocks WHERE is_active = TRUE)                AS active_stocks,
  (SELECT COUNT(DISTINCT ticker) FROM financials)                     AS with_financials,
  (SELECT COUNT(DISTINCT ticker) FROM ratio_history)                  AS with_ratio_history,
  (SELECT COUNT(DISTINCT ticker) FROM peer_groups)                    AS with_peers,
  (SELECT COUNT(DISTINCT ticker) FROM market_metrics
   WHERE trade_date > current_date - interval '7 days')               AS with_recent_prices;
```

### Freshness (median days since last update)

```sql
WITH latest AS (
  SELECT ticker, MAX(period_end) AS latest_period
  FROM financials GROUP BY ticker
)
SELECT
  PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY current_date - latest_period) AS median_days_stale,
  PERCENTILE_CONT(0.9) WITHIN GROUP (ORDER BY current_date - latest_period) AS p90_days_stale
FROM latest;
```

### Accuracy spot-check vs known-good values

For the top 20 tickers you care about (RELIANCE, TCS, INFY, HDFCBANK,
ICICIBANK, BHARTIARTL, ITC, SBIN, LT, HINDUNILVR, etc.), eyeball against
Screener.in / company investor-relations pages once a month. Our targets:

| Ratio | Acceptable error vs Screener |
|-------|------------------------------|
| ROE   | ±5% absolute (e.g., if Screener says 18%, we should say 17-19%) |
| ROCE  | ±5% absolute |
| D/E   | ±0.2 |
| PE    | ±2 points |
| EV/EBITDA | ±2× |
| Revenue growth YoY | ±3% absolute |

If any ticker exceeds these, file an issue with the specific ratio +
observed vs expected + likely root cause (usually unit mismatch, TTM
normalization, or currency reporter mis-classified).

---

## Escalation

**Symptom: every ratio null across the board.**
→ DATABASE_URL isn't set, or Aiven is down. Check `SELECT 1` first.

**Symptom: only new tickers affected.**
→ `populate_stocks.yml` didn't run or ISIN lookup failed. Check the
 `isin` column on the new rows in `stocks`.

**Symptom: ratios wrong for ADR/USD reporters (INFY, WIPRO, HCLTECH).**
→ Currency detection fell back wrong. See `USD_REPORTER_TICKERS` in
 `data_pipeline/sources/bse_xbrl.py` and add the ticker.

**Symptom: peer_groups empty for a specific ticker.**
→ That ticker has no same-sub_sector same-cap peers. Run the script
 with `--debug` (add flag if missing) to see which candidates were
 evaluated. Consider relaxing the peer rule for that ticker's sector.

---

_This runbook is living. Update it when new failure modes surface._
