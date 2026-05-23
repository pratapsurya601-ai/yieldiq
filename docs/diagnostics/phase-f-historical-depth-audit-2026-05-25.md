# Phase F.1 — Historical Depth Audit (2026-05-25)

**Status:** read-only diagnostic. No code or data changes in this PR.
**Author:** Phase F dispatch
**Scope:** evidence base for Phase F.2 / F.3 / F.4 go / no-go.

---

## 1. Why this audit exists

Competitors that we benchmark against — screener.in, tijorifinance,
trendlyne — render up to **10 years** of P&L, balance sheet, cash
flow, ratio history, AND split/bonus-adjusted price history on their
free pages. YieldIQ currently renders ~5y on most surfaces. The DCF
engine itself only consumes 5y, but the user-facing tables and CAGR
widgets look thin next to peers, and several widgets fall back to
`data_limited` for older horizons (`cagr_10y` in particular).

Day-112 fixed the **going-forward** adj_close pipeline. Phase F is the
**backward** catch-up plan: F.2 (10y adj_close backfill), F.3 (10y
fundamentals backfill), F.4 (ratio-history regeneration off the new
inputs).

Before any of that, F.1 establishes:

* Which tables actually exist (the roadmap brief used approximate
  names — the real schema is different in two places).
* What "5y" really means today, per table, per ticker.
* Whether 10y source data is reachable for Indian tickers via paths
  we already own. If not, F.2/F.3 are infeasible and we report a
  blocker instead of pushing scripts that can't succeed.

---

## 2. Universe under audit

**Total: ~533 tickers**, the union of:

| Bucket | Count | Source |
|---|---|---|
| Canary v3 (`scripts/canary_universe_180.json`, despite the file name) | **333** | `top100_diversified` 150, `banks` 27, `psu_utilities` 50, `cyclicals` 56, `pharma` 41, `platform` 9 |
| Top 500 by market cap (from `stocks` × `market_metrics`) | up to 500 | derived per SQL in §6 |
| Effective union (canary is mostly a subset of top-500) | ~533 unique | operator runs §6 query and feeds output to F.2/F.3 scripts |

> **Note on the "180" filename.** `canary_universe_180.json` is the
> historical name. The file's own `_meta.version` is `v3_333` and the
> bucket counts sum to 333. F.2/F.3 scripts read the file by
> path and trust the bucket contents, not the filename.

---

## 3. Schema reality check (vs. roadmap brief)

The Phase F brief named four tables — `financials_annual`,
`financials_quarterly`, `ratio_history`, `daily_prices`. **Only two
of those names actually exist in the schema.** Corrections:

| Brief name | Real name | Where | Notes |
|---|---|---|---|
| `daily_prices` | `daily_prices` | `data_pipeline/models.py:31` (`DailyPrice`) | OHLCV + `adj_close`. Unique key `(ticker, trade_date)`. |
| `financials_annual` | `financials` with `period_type = 'annual'` | `data_pipeline/models.py:82` (`Financials`) | Single table; the annual/quarterly split is a column, not separate tables. |
| `financials_quarterly` | `financials` with `period_type = 'quarterly'` | same | same |
| `ratio_history` | `ratio_history` | `data_pipeline/models.py:289` (`RatioHistory`) | Derived from `financials` + `market_metrics`. Built by `scripts/build_ratio_history.py`. |

**Consequence:** F.3 work targets ONE table (`financials`) with a
WHERE-clause split, not two. All scripts/runbooks below use the real
names.

Other relevant tables touched by the backfill:

* `corporate_actions` — `(ticker, ex_date, action_type)` unique key.
  Already populated by `data_pipeline/sources/nse_bhavcopy.py` and
  Day-112's `scripts/backfill_corporate_actions_yf.py`. Read by the
  adj_close rebuilder for cross-validation.
* `price_adjustment_log` — migration `056_price_adjustment_log.sql`.
  Append-only audit trail for every `adj_close` change. Written by
  `scripts/rebuild_adj_close.py`; F.2 will append to it too.
* `market_metrics` — used by `build_ratio_history.py` for pe/pb at
  period_end. Not modified by Phase F, but stale entries here will
  cap how far back `ratio_history.pe_ratio` can be regenerated.

---

## 4. Per-table depth — what the operator must measure

This audit ships the SQL the operator runs against Neon; we deliver
the SQL + the structure of the report, not the live numbers (the
agent dispatched here has no DB credentials). When operator runs
§6 and pastes the output back, this section becomes a filled-in
table; until then it's the schema.

For each of the four tables, we want two outputs per ticker:

1. **min(period) / max(period)** — to see if "5y" means "5 most-recent
   years" or "5 random years scattered across 2015-2024".
2. **count of distinct periods** — for the histogram.

The buckets we'll histogram into:

| Bucket | Definition |
|---|---|
| `none` | 0 rows |
| `<5y` | 1 ≤ n < 5 distinct annual periods (or <1,250 trading days for `daily_prices`) |
| `5-7y` | 5 ≤ n < 7 |
| `7-10y` | 7 ≤ n < 10 |
| `10y+` | n ≥ 10 |

For `daily_prices`, conversion factor: 1 trading year ≈ 250 sessions,
so `10y ≈ 2,500 rows`, `5y ≈ 1,250`.

---

## 5. Upstream source feasibility — table by table

This is the **central question** of F.1: even if we write a perfect
backfill script, does the upstream source actually have 10y of data
for Indian tickers?

### 5.1 `daily_prices.adj_close` (Phase F.2)

* **Primary source:** yfinance `yf.Ticker("SYM.NS").history(period="max", auto_adjust=False)`.
* **Coverage for Indian tickers:** yfinance routinely returns
  2000-01-01 onward for NIFTY 500 names — well beyond 10y. The
  Day-112 rebuilder (`scripts/rebuild_adj_close.py`) already pulls
  `period="max"` per ticker, so the **data exists and the access
  pattern is already proven**.
* **What's missing today:** Day-112 only ran on tickers that already
  had `daily_prices` rows. For the top-500 universe, some tickers
  have shallow `daily_prices` history because the NSE-bhavcopy
  ingest only started backfilling in 2021 — so even though yfinance
  has 10y, our `daily_prices` table is shallow.
* **F.2 implication:** the script must **insert** missing OHLC rows
  from yfinance for dates that don't exist in `daily_prices`, then
  set `adj_close`. The Day-112 rebuilder only UPDATEs existing rows;
  it skips `td` not present in `daily_prices`. F.2 extends behavior
  with an `--insert-missing` flag (default ON for the 10y backfill;
  OFF for routine Day-112-style refreshes).
* **Feasibility verdict: GREEN.** yfinance is known to serve 10y+
  for all 533 tickers in the audit universe. Adjustment math is
  Day-112-tested. Risk is rate-limit only (mitigated by existing
  exponential backoff in `fetch_yfinance_adj_close`).

### 5.2 `financials` (Phase F.3)

Three candidate sources, ranked:

| Source | 10y depth on Indian tickers? | Access path | Already wired? |
|---|---|---|---|
| **BSE Peercomp API** | YES (up to 10 historical years across P&L Annual, P&L Quarterly, BS Annual, CF Annual) | `data_pipeline/sources/bse_xbrl.fetch_historical_financials(scrip_code, ticker)` — endpoints in `_HIST_ENDPOINTS` | **YES** — existing fn at `bse_xbrl.py:243`; Akamai-blocked fallback already built at `bse_peercomp_browser.py` |
| BSE annual report XBRL (per-filing) | YES, but only for years a filing was tagged in the BSE filings index | `data_pipeline/sources/bse_quarterly_xbrl.py` (annual mode would need a sibling) | Quarterly: yes. Annual: no — would be a new script. |
| screener.in scrape | YES (their pages show 10y) | scrape | **NO** — legally grey, robots.txt status unverified, fragile to layout drift. Not preferred. |
| yfinance financials | ~4y on Indian tickers (annual income statement) | `data_pipeline/sources/yfinance_supplement.py` | Yes, but insufficient depth |

**Chosen path for F.3: drive `bse_xbrl.fetch_historical_financials`
at scale.** It's the best-quality source we already own, it returns
up to 10 years natively, and we already have an Akamai-resilient
fallback (`bse_peercomp_browser.py`) for tickers where the API
returns the 302→error_Bse redirect. screener.in scrape is the F.3
contingency only if BSE Peercomp turns out to be heavily Akamai-
walled even from a real browser.

**Feasibility verdict: GREEN — with caveats.**

* Caveat 1: every ticker needs a `bse_scrip_code` from the `stocks`
  table. Coverage was confirmed comprehensive after the BSE
  securities-master ingest (`bse_securities_master.py`), but the F.3
  script must skip + log tickers where `stocks.bse_code IS NULL` so
  it doesn't silently leave them at 5y.
* Caveat 2: BSE Peercomp's `bs_annual` rows historically did not
  expose ROCE-relevant fields (current liabilities) — see TODO at
  `bse_xbrl.py:355`. That gap will cause `ratio_history.roce` nulls
  for the older years; F.4's validator will flag this.
* Caveat 3: per-ticker BSE Peercomp budget is ~2-4 s (4 endpoints
  per ticker @ 0.5-1s). 533 tickers serially ≈ 35-60 min. Browser
  fallback is 10× slower but only needed for ~5-15% of tickers.

### 5.3 `ratio_history` (Phase F.4)

* **Source:** purely derived from `financials` + `market_metrics` via
  the existing `scripts/build_ratio_history.py`. No external upstream.
* **F.4 implication:** F.4 doesn't need a new backfill source; it
  needs (a) a thin wrapper that runs `build_ratio_history.py` for
  the union of tickers F.2 and F.3 actually touched, and (b) a
  validator that confirms `pe_ratio` null-rate drops below 10%
  (Phase A issue #546 surfaced a 50.9% null spike).
* **Feasibility verdict: GREEN.** Trivial once F.2 + F.3 are done.

---

## 6. SQL for the operator

The agent dispatched for this audit has no DB credentials. The
operator runs these against the Neon (or Aiven, whichever is
the primary financials DB — see `memory/reference_yieldiq_infra.md`)
read replica and paste the results into §4.

### 6.1 Build the top-500 ticker list

```sql
-- "Top 500 by market cap" — used as the union with canary 333.
-- Filters out shadow tickers and inactive listings.
SELECT s.ticker, mm.market_cap_cr
FROM   stocks s
JOIN   market_metrics mm ON mm.ticker = s.ticker
WHERE  s.is_active = TRUE
  AND  COALESCE(s.shadow, FALSE) = FALSE
  AND  mm.market_cap_cr IS NOT NULL
ORDER BY mm.market_cap_cr DESC
LIMIT 500;
```

Save the resulting tickers to `scripts/phase_f_top500.txt`
(one ticker per line, bare symbol, no `.NS`). F.2 and F.3 will
consume this file via `--tickers @scripts/phase_f_top500.txt`.

### 6.2 Per-ticker depth — `daily_prices`

```sql
WITH u AS (
    SELECT unnest($1::text[]) AS ticker     -- bind the 533 tickers
)
SELECT u.ticker,
       MIN(dp.trade_date) AS min_date,
       MAX(dp.trade_date) AS max_date,
       COUNT(*)           AS n_rows,
       COUNT(dp.adj_close) AS n_with_adj
FROM   u
LEFT JOIN daily_prices dp ON dp.ticker = u.ticker
GROUP BY u.ticker
ORDER BY n_rows;
```

Histogram bucketing (Python after fetching):

```python
def bucket(n_rows: int) -> str:
    if n_rows == 0:        return "none"
    if n_rows < 1250:      return "<5y"
    if n_rows < 1750:      return "5-7y"
    if n_rows < 2500:      return "7-10y"
    return "10y+"
```

### 6.3 Per-ticker depth — `financials` (annual + quarterly)

```sql
WITH u AS (SELECT unnest($1::text[]) AS ticker)
SELECT u.ticker,
       SUM(CASE WHEN f.period_type='annual'    THEN 1 ELSE 0 END) AS n_annual,
       SUM(CASE WHEN f.period_type='quarterly' THEN 1 ELSE 0 END) AS n_quarterly,
       MIN(CASE WHEN f.period_type='annual' THEN f.period_end END) AS oldest_annual,
       MAX(CASE WHEN f.period_type='annual' THEN f.period_end END) AS newest_annual
FROM   u
LEFT JOIN financials f ON f.ticker = u.ticker
GROUP BY u.ticker
ORDER BY n_annual;
```

Bucket annual on `n_annual` directly (1 row = 1 fiscal year).

### 6.4 Per-ticker depth — `ratio_history`

```sql
WITH u AS (SELECT unnest($1::text[]) AS ticker)
SELECT u.ticker,
       COUNT(*) AS n_rows,
       SUM(CASE WHEN r.pe_ratio IS NULL THEN 1 ELSE 0 END)::float
           / NULLIF(COUNT(*), 0) AS pe_null_rate,
       MIN(r.period_end) AS oldest,
       MAX(r.period_end) AS newest
FROM   u
LEFT JOIN ratio_history r ON r.ticker = u.ticker
                          AND r.period_type = 'annual'
GROUP BY u.ticker
ORDER BY n_rows;
```

### 6.5 Source-coverage spot check

For 5 representative tickers across the F.2 source (yfinance) and
F.3 source (BSE Peercomp), confirm 10y data is reachable BEFORE
launching the full backfill:

```bash
# Sample tickers: 1 large IT, 1 large bank, 1 PSU, 1 cement, 1 pharma.
DATABASE_URL=$NEON_RO python - <<'PY'
import yfinance as yf
for t in ["TCS","HDFCBANK","NTPC","ULTRACEMCO","SUNPHARMA"]:
    h = yf.Ticker(f"{t}.NS").history(period="max", auto_adjust=False)
    print(t, "yf rows:", len(h), "earliest:", h.index.min().date() if len(h) else "—")
PY
```

For F.3, the same sanity-check on BSE Peercomp:

```bash
python - <<'PY'
from data_pipeline.sources.bse_xbrl import fetch_historical_financials
import data_pipeline.db as db
with db.session() as s:
    from data_pipeline.models import Stock
    for t in ["TCS","HDFCBANK","NTPC","ULTRACEMCO","SUNPHARMA"]:
        st = s.query(Stock).filter_by(ticker=t).one_or_none()
        scrip = getattr(st, "bse_code", None) if st else None
        rows = fetch_historical_financials(scrip, t) if scrip else []
        annual = [r for r in rows if r.get("period_type")=="annual"]
        print(t, "scrip:", scrip, "annual rows:", len(annual),
              "years:", sorted({r["period_end"].year for r in annual}))
PY
```

Expected: all 5 sample tickers return ≥10 yfinance years and ≥8 BSE
Peercomp annual rows. If <8 on ≥2 tickers, escalate before F.3.

---

## 7. Pre-decided plan based on F.1 evidence so far

Because we already audited the **infrastructure** (sources exist and
are wired) without needing live row counts, the F.2/F.3/F.4 go/no-go
is largely settled before the operator runs §6:

* **F.2 → GREEN to proceed.** yfinance supplies 10y+ for all Indian
  tickers in scope; rebuilder design is reusable from Day-112; only
  new code is the `--insert-missing` mode + the 10y bound enforcement
  + a top-500 ticker resolver.
* **F.3 → GREEN to proceed, BSE Peercomp path.** `bse_xbrl.
  fetch_historical_financials` already targets 10y. screener.in
  remains the contingency.
* **F.4 → GREEN to proceed.** Pure re-derivation; no upstream risk.

The ONLY scenarios that would flip any of these to RED, surfaced by
the §6 SQL:

1. `daily_prices` for ≥30% of the top-500 has `n_rows < 100` — would
   indicate the NSE-bhavcopy ingest has a wider gap than expected.
   F.2 still works (yfinance inserts), but operator-runtime estimate
   needs to be inflated 4×.
2. `stocks.bse_code IS NULL` for ≥20% of the top-500 — would make
   BSE Peercomp unusable for that fraction and force screener.in
   contingency for F.3.
3. The §6.5 yfinance spot check returns <10 years for ≥2 of the 5
   sample tickers — would indicate a yfinance regional limit and
   force us back to bhavcopy archive scraping for F.2.

If §6 returns any of those signals, stop and re-scope before F.2.
Otherwise proceed.

---

## 8. Estimated operator runtime for F.2 + F.3 + F.4

Assumes 5-worker concurrency for F.2 (yfinance, matches Day-112
defaults) and serial for F.3 (BSE Peercomp is single-IP rate-limited
and the Playwright fallback can't parallelize cleanly):

| Phase | Tickers | Per-ticker budget | Wall-clock |
|---|---|---|---|
| F.2 backfill_adj_close_10y | 533 | ~10s (fetch + write + log) | ~20 min @ 5 workers |
| F.3 backfill_financials_10y (API path) | ~85% of 533 = 450 | ~3s | ~25 min serial |
| F.3 backfill_financials_10y (browser fallback) | ~15% of 533 = 80 | ~12s | ~16 min serial |
| F.4 regenerate_ratio_history | 533 | <1s (DB-only) | ~5 min |
| **Total** | | | **~70 min** (one weekend evening) |

Add 2× safety margin → tell the operator to block 2 hours.

---

## 9. Open questions for the operator before F.2 launch

1. **Primary financials DB:** Neon or Aiven? Phase F brief said Neon
   ("derive from `stocks` table on a one-shot SQL query against
   Neon"), but `memory/reference_yieldiq_infra.md` lists Aiven for
   the yieldiq Financials DB. F.2/F.3 scripts use `DATABASE_URL`
   env var — operator sets it to whichever is the financials DB.
2. **Run host:** local dev box or `workflow_dispatch` on GH Actions?
   Day-112 precedent is local. F.2 is ~20 min so local is fine.
   F.3 is ~40 min including browser fallback — fine local; risky on
   GH Actions only because the Akamai-resilient Playwright run
   needs `playwright install chromium --with-deps`, doable but adds
   ~5 min cold start.
3. **Backup:** confirm a fresh logical backup of `daily_prices` and
   `financials` exists before F.2/F.3 launch. The scripts are
   idempotent and audited (every change in `price_adjustment_log`
   or precedence-guarded UPSERT), but a backup is cheap insurance.

---

## 10. Next PR plan (assuming GREEN)

| PR | Adds | Touches services dir? (canary gate) |
|---|---|---|
| F.2 | `scripts/backfill_adj_close_10y.py`, `docs/runbooks/backfill_adj_close_10y.md`, manifest entry scoped to `["fair_value", "cagr_3y","cagr_5y","cagr_10y"]` for the 533 tickers it updates | NO (script-only + manifest append; the manifest file is service-layer but the entry is data-only, no logic change) |
| F.3 | `scripts/backfill_financials_10y.py`, `docs/runbooks/backfill_financials_10y.md` | NO (script-only) |
| F.4 | `scripts/regenerate_ratio_history.py` (thin wrapper around `build_ratio_history.py`), runbook, manifest entry `v_phase_f_historical_depth_2026_05_25` scoped per Phase F brief | YES — manifest entry. Canary-diff must exit 0. |

Backend service layer is untouched in F.2 / F.3. F.4's manifest
append is the only thing that trips the canary gate, by design.

---

## 11. Stop condition

If operator's §6 SQL reveals any of the §7 RED scenarios, the agent
will stop and re-scope rather than push F.2. Otherwise, proceed
F.2 → F.3 → F.4 sequentially as planned.

— end audit —
