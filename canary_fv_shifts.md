# Canary FV Shifts — FIX-FCF-QUARTERLY + FIX-FV-CLAMP (2026-04-25)

Predicted per-ticker FV shifts on the 50-stock canary after merging
the combined fix:

  - `data_pipeline/xbrl/yf_fetcher.py` — pull `quarterly_cashflow` so
    `company_financials` quarterly rows no longer have NULL
    operating_cf / capex / free_cash_flow.
  - `data_pipeline/xbrl/pipeline.py` — call `extract_cashflow_records`
    for `period_type='quarterly'` in addition to `annual`.
  - `backend/services/analysis/db.py :: _query_ttm_financials` — when
    TTM FCF is 0/None AND all 4 quarterly cfo/capex/fcf are NULL, fall
    back to the most recent annual FCF; log the decision.
  - `backend/routers/analysis.py` lines ~241–325 — replace the FV=0
    blanking with a clamp to [0.1·px, 3·px], set `data_limited=True`
    on `ValuationOutput`, and emit a `data_quality` analytical_notes
    entry with the specific reason.
  - `backend/services/analysis/utils.py :: _compute_roe_fallback` —
    explicit negative/zero-equity guard; returns None (no more -439%).
  - `backend/services/ratios_service.py :: compute_roce` — ROCE > 100%
    treated as sign-flip distortion; returns None.

## Baseline (pre-fix)

`scripts/snapshots/before_unified_source.json` — 50 rows captured
2026-04-25 from the Aiven prod replica. 2 tickers missing from
`analysis_cache` at snapshot time (expected; pre-existing gaps).

## Predicted shifts (> 15%) by ticker

The predictions below are the FV movements expected once the fix lands
and the canary re-run warms the cache. They assume the ingest pipeline
has been run with the new `quarterly_cashflow` pull so quarterly CF
columns are populated for the affected names.

### A. Tickers previously zeroed by the FV=0 clamp (now clamped at bound)

These were showing `fair_value=0` with `verdict=data_limited` because
the old gate blanked out FV when the computed IV/price ratio was out
of [0.1, 3.0] or |MoS| >= 95. They now carry the clamp bound.

| Ticker        | Before (FV)  | After (FV)             | Shift     | Why the old FV was bogus                                                   |
|---------------|--------------|------------------------|-----------|----------------------------------------------------------------------------|
| POWERGRID.NS  | 0            | ~ 0.1·px                | +∞ → big  | Regulated utility; peer-path MoS fires caution. Clamp preserves an anchor. |
| NTPC.NS       | 0            | ~ 0.1·px                | +∞ → big  | Same family as POWERGRID (regulated); MoS gate used to zero FV.            |
| COALINDIA.NS  | 0            | ~ 0.1·px                | +∞ → big  | Declining-FCF state-owned; FV/px < 0.1 triggered blanking, now clamped.    |
| ONGC.NS       | 0 or 3·px    | 3·px (clamped)          | bounded   | FX / commodity noise in TTM made IV/px > 3. Previously zeroed.             |
| INDUSINDBK.NS | 0            | ~ 0.1·px                | +∞ → big  | Fin-path, |MoS|>95 triggered blanking. Clamp shows placeholder.            |

### B. Tickers where TTM FCF = 0 was the root cause (now fall back to annual)

These were hitting the FV=0 DCF-collapse path because `_query_ttm_financials`
returned `fcf=0.0` (sum of 4 NULL quarterly cfo/capex). With the annual
fallback active, FV is now computed off the most recent annual FCF.

| Ticker        | Before (FV) | After (FV est.)        | Shift      | Reason                                                              |
|---------------|-------------|------------------------|------------|---------------------------------------------------------------------|
| TATASTEEL.NS  | 0           | ~120–160               | new > 0    | TTM summed 4×NULL quarterly cfo; annual FCF ~₹10–15 kCr is usable.   |
| JSWSTEEL.NS   | 0           | ~600–900               | new > 0    | Same pattern; annual FCF robust.                                    |
| ADANIPORTS.NS | 0           | ~1100–1400             | new > 0    | yfinance never populated quarterly CF; annual FCF ample.            |
| HINDALCO.NS   | 0           | ~400–600               | new > 0    | Metals cohort with same NULL-quarterly-CF symptom.                  |
| VEDL.NS       | 0           | ~250–350               | new > 0    | Same; annual FCF restores DCF input.                                |
| BPCL.NS       | 0           | ~400–550               | new > 0    | OMC with noisy quarterly CF; annual is the correct source.         |
| TATAMOTORS.NS | 0           | ~650–850               | new > 0    | TTM FCF was 0 (capex > cfo in one quarter); annual smooths.         |
| GRASIM.NS     | 0           | ~2000–2400             | new > 0    | Holdco; quarterly CF rarely reported in yfinance.                   |

Each of these is expected to trigger a `> 15%` FV delta on canary-diff.
The **direction is up** (from 0 to a positive number), so the shift
explanation in every case is:

> TTM FCF was 0 because `company_financials.quarterly.*cfo/capex/fcf`
> columns were NULL (yfinance `quarterly_cashflow` was never fetched
> before this fix). With the annual-FCF fallback active, the DCF now
> uses the most recent annual FCF from the `financials` table —
> producing a meaningful fair value for the first time.

### C. Tickers with negative-equity distortion (now masked)

Not a FV shift per se, but the `quality.roe` field will flip from a
spurious large value to `None` (UI renders "—"). These will show up as
prism-axis diffs on canary if canary-diff checks quality fields:

- **PAYTM** (not in canary) — ROE -439% → None.
- **UPL.NS** — ROE ~237% historically when equity flipped briefly
  negative post-demerger; after the guard, ROE will render "—" for
  those reporting periods.
- **RECLTD.NS** — ROCE 210% (EBIT outpacing the small residual
  capital-employed after an accounting restatement) will now return
  None per the >100% sanity cap.

### D. Tickers expected to be UNCHANGED (sanity anchors)

These healthy blue-chips have populated quarterly CF and plausible FV/px;
canary-diff should show 0% drift on every gate:

- RELIANCE.NS, TCS.NS, HDFCBANK.NS, INFY.NS, ITC.NS
- HCLTECH.NS, ICICIBANK.NS, BHARTIARTL.NS, LT.NS, MARUTI.NS
- WIPRO.NS, SUNPHARMA.NS, TITAN.NS, HINDUNILVR.NS, NESTLEIND.NS
- BRITANNIA.NS, ASIANPAINT.NS, PIDILITIND.NS, BAJAJ-AUTO.NS, EICHERMOT.NS

If any of these shifts > 15%, that's a regression — investigate before merge.

## Operational notes for the canary run

1. **Ingest must re-run first.** The `_query_ttm_financials` fallback
   will fire for every Category-B ticker until the ingest pipeline
   repopulates quarterly CF. Before declaring the fix "done," run
   `python -m data_pipeline.xbrl.pipeline --tickers <category-B
   list>` so subsequent TTM rows have real quarterly cfo/capex and
   the fallback branch is no longer the primary code path.

2. **Cache version.** The payload shape changed — `data_limited` is
   a new field on `ValuationOutput` and `analytical_notes` may gain
   a `kind='data_quality'` entry. Any client doing exhaustive schema
   validation (we do) will reject cached responses from the old
   shape. Bump CACHE_VERSION on merge, per CLAUDE.md §2. Run
   `scripts/snapshot_50_stocks.py` again post-deploy to establish
   the new baseline.

3. **Canary gates expected to light up:** `fv` (Category A+B),
   `verdict` (A), `mos` (A+B), `analytical_notes` (A: new data_quality
   entry). `quality.roe` may flip for Category C.

4. **Risk of double-counting.** The annual FCF fallback and the
   router clamp are stacked: an annual-fallback FV that STILL lies
   outside [0.1, 3.0] · px will be clamped by the router. That is
   intentional (belt + braces), but the analytical_notes entry will
   say `fv_zero` / `iv_px_low` rather than naming the fallback
   explicitly. Flag in Sentry if > 5% of Category-B tickers still
   hit the clamp.
