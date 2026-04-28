# Performance Retrospective — Design Notes

**Status:** Phase 1 (scaffolding) — Task 12.
**Owner:** YieldIQ analyst team.
**Last updated:** 2026-04-27.

## 1. Goal

Publish a quarterly Performance Retrospective on
`yieldiq.in/methodology/performance` that says, in plain language:

> Of N stocks our model called undervalued (margin-of-safety ≥ 30%) in
> Q1FY26, M (X%) outperformed the Nifty 500 over the next 90 days.
> Mean return was Y%, median Z%, hit-rate H%.

This is the single biggest trust-builder a model-based stock platform
can ship. Morningstar publishes the analytical equivalent. Indian
retail platforms don't. Doing it well — including publishing the
losers — differentiates YieldIQ from advisory pretenders.

## 2. Methodology

### 2.1 Snapshot writer

`backend.services.retrospective_service.record_daily_predictions(date)`
runs as a daily cron (target: 19:30 IST, after the daily-prices ETL).
For every ticker in the analysis universe it inserts one row into
`model_predictions_history` with: ticker, prediction_date,
current_price (close on prediction_date), fair_value,
margin_of_safety_pct, yieldiq_score, grade, verdict, and the live
cache_version. `UNIQUE(ticker, prediction_date)` makes retries safe.

### 2.2 Outcome computation

`compute_outcome(prediction_id, outcome_date)` reads
`daily_prices.close` for the outcome_date and writes one row to
`prediction_outcomes` with `return_pct = (outcome - prediction) /
prediction × 100`. The default windows are **30, 60, 90, 180, 365**
days. The public page defaults to **90** because it's the longest
window that lets us publish quarterly without lag.

### 2.3 Summary

`summarize_for_period(start, end, mos_threshold=30, window=90)`
returns the contract dict the public page consumes (see service
docstring). Filtering by `mos_threshold` ensures we measure
high-conviction calls, not the entire universe.

## 3. Methodology — open questions

### Q1. Counterfactual vs reconstructed historical model

> When we say "our Q1FY26 prediction on TICKER X", do we mean
>
> **(A)** what the *current* model (cache_version 66) would have
> said given only data available on that date — *counterfactual*; or
> **(B)** what the model that was actually live on that date said —
> *reconstruction*?

**Recommendation: (A) Counterfactual.**

* (B) replays known bugs. The `_normalize_pct` double-percent bug
  (PR #126, cache_version 66) was systematically wrong — publishing
  those numbers as our retrospective record is misleading.
* (A) tests the model we're shipping today against data the model
  could not peek at. That's the question users actually care about:
  is the thing you're publishing right now any good?
* Strict point-in-time discipline (no look-ahead in financials, no
  look-ahead in price) keeps (A) honest.

This decision is open for revision during Phase 2 review.

### Q2. Stocks that didn't exist on prediction_date (no IPO yet)

Skip them. Do not retroactively assert a model prediction for a
non-existent ticker. The backfill should join against the earliest
`daily_prices.date` per ticker and short-circuit if
`prediction_date < first_listed_date`.

### Q3. Benchmark choice

Default: **Nifty 500**. Rationale: closer cross-cap match to our
3000-stock universe than Nifty 50.

Future: optional per-summary breakdowns by sector and size tier
(large/mid/small). The summary endpoint can accept
`?benchmark=NIFTY50.NS` for caller-controlled override.

### Q4. Recompute frequency

Daily snapshot of all 3000 covered tickers is heavy but not
impossible (~3000 rows × 1 KB × 365 days ≈ 1 GB / year). Weekly is
cheaper but loses the ability to assert "we said this on date X".
**Recommendation: daily.**

### Q5. Universe scope — free-tier or paid only?

If the retrospective is the trust-building artefact, it must cover
the same universe a free user can see. **Recommendation: include
free-tier stocks**, with a sub-summary that filters to paid-tier
analysis universe for honest like-for-like.

## 4. Caveats (must appear on the public page)

* **Past results are not indicative of future returns.** Required
  framing under SEBI (IA) Regulations descriptive carve-out.
* **Selection bias.** We summarise the high-MoS subset. The model
  may also produce many *correct* "fair value" calls that don't show
  up because they don't clear the 30% threshold.
* **Survivorship bias.** Stocks delisted between prediction_date and
  outcome_date drop out. Phase 2 should annotate the count of
  excluded survivors at minimum, ideally back-fill outcome_price with
  the delisting price.
* **Look-ahead bias.** Avoidable only with strict point-in-time
  discipline. Counterfactual recomputes (recommendation Q1) MUST use
  as-of snapshots of `company_financials` and `daily_prices`, never
  the live tables.
* **Sample size.** With ≤100 high-MoS calls per quarter, single-window
  hit-rates have wide confidence intervals. We should publish the
  count alongside the rate, and cumulative across multiple quarters
  once we have them.

## 5. SEBI compliance posture

YieldIQ is **not** a SEBI-registered Investment Adviser. The
retrospective is descriptive, not advisory:

* It reports **realised** returns of past model output, not
  recommendations.
* It does not solicit investment, recommend transactions, or offer
  personalised advice.
* The mandatory caveat appears at the top of the public page and is
  echoed in the API payload's `disclaimer` field.

Legal review checklist before each quarterly publication:

- [ ] Caveat present at top of page, not behind a fold
- [ ] No language implying future returns
- [ ] No personal-advice phrasing ("you should buy")
- [ ] Methodology link prominent
- [ ] Sample-size and bias caveats listed

## 6. Roadmap

| Phase | Scope | This PR |
|---|---|---|
| **1. Scaffolding** | Schema, service, endpoint, sample frontend, fixture tests, design doc | ✅ |
| **2. Backfill** | Implement `analysis_service.compute_for_date`; run `scripts/backfill_predictions.py` for last 90d; ensure point-in-time discipline | ❌ |
| **3. Public page** | Real histogram, sortable full-table, sector / size breakdowns | ❌ |
| **4. Quarterly publication ritual** | Calendar entry; legal review checklist; archive past quarters under `/methodology/performance/{quarter}` | ❌ |

## 7. Files in this PR

* `data_pipeline/migrations/019_model_predictions_history.sql`
* `backend/services/retrospective_service.py`
* `backend/routers/public.py` — added `GET /api/v1/public/retrospective`
* `scripts/backfill_predictions.py`
* `frontend/src/app/(marketing)/methodology/performance/page.tsx`
* `tests/fixtures/sample_predictions.json`
* `tests/test_retrospective_service.py`
* `docs/performance_retrospective_design.md` (this file)
