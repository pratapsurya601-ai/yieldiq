# Performance Retrospective — Implementation Notes (Phase 2)

This document covers the **engine + proof-of-concept backfill** that
turns `/methodology/performance` from a sample-data preview into a
real, DB-backed quarterly retrospective. It complements the design
doc (`performance_retrospective_design.md`) which justifies the
methodology choices; this doc describes how the code is wired.

## Methodology — counterfactual reconstruction (pragmatic variant)

For each `(ticker, prediction_date)` pair we ask:

> What would the **current model** (`CACHE_VERSION` at run time) say
> about this stock, using the **price that was live on
> prediction_date**?

Concretely, `compute_for_date(ticker, date)`:

1. Looks up the closest trading-day close in `daily_prices` on or
   before `date` (7-day backstop for holidays).
2. Calls the live `AnalysisService.get_full_analysis(ticker)` to get
   FV, score, grade, verdict.
3. Reprojects margin-of-safety as `(FV − historical_price) /
   historical_price × 100`.

The **fair value** therefore reflects today's financials — not the
financials that were available on `prediction_date`. This is the
**pragmatic variant** documented in the module docstring of
`backend/services/analysis/compute_for_date.py`. It is honest for
short windows (≤ 30 days, where financials are essentially unchanged)
and clearly mis-marked as a look-ahead-prone shortcut for windows ≥
90 days.

Phase 3 (full 90d × 3000 backfill) should land the **strict variant**
that threads `_as_of_date` through the financial-fetch helpers in
`backend/services/analysis/db.py`. The PoC behind a `--strict` flag,
gated on canary-diff parity, would unblock honest year-over-year
publication.

## Caveats published on the public page

1. **Past results are not indicative of future returns.** SEBI-
   compliance non-negotiable; sits at the very top of the page.
2. **Survivorship bias** — `daily_prices` no longer carries delisted
   tickers. Predictions on companies that were delisted within the
   outcome window silently disappear from the summary. The bias is
   small for our universe (large-cap heavy) but real.
3. **Look-ahead bias on financials** (pragmatic variant only) — see
   above. Mitigated to negligible for a 30-day window; meaningful for
   90 days.
4. **Selection bias** — only stocks the model called "undervalued"
   (margin-of-safety ≥ 30%) enter the headline number. The page
   surfaces this explicitly in the hero.
5. **Cache-version drift** — every row stores
   `cache_version_at_prediction`. If a future audit shows a buggy
   cohort (e.g. `_normalize_pct` v32–v35), those rows can be filtered
   without invalidating the entire history.

## Refresh cadence

* **Daily snapshot** (cron, 19:30 IST after `daily_prices` ETL)
  — `retrospective_service.record_daily_predictions(today)` writes one
  row per covered ticker into `model_predictions_history`. Idempotent
  on `(ticker, prediction_date)`.
* **Daily outcome compute** (cron, 19:35 IST) —
  `scripts/compute_outcomes.py --apply` fills t+30/60/90/180/365
  rows whose outcome_date has elapsed. Idempotent on
  `(prediction_id, outcome_date)`.
* **Quarterly publication ritual** — at the end of each Indian fiscal
  quarter (last business day of Jun/Sep/Dec/Mar), publish a "QnFYyy"
  blog post linking to the live page. Phase 3 work item.

## Operational rollout — open questions

1. **Full universe rollout cost.** 3000 tickers × 90 days × ~3 s /
   compute_for_date ≈ 225 hours of compute. Needs:
   * Parallel workers (Railway worker shape, not the API service —
     see `feedback_yieldiq_discipline.md` rule "no long jobs in
     Railway worker"). Best path: a one-shot GitHub Actions matrix.
   * Sharded by ticker prefix to stay within Aiven connection limits.
2. **Alert noise.** When a quarter publishes with a low hit-rate (or
   a previously-touted stock turning into the worst loser), the email
   newsletter and the public page should agree. Phase 3 will add a
   "publication freeze" — once a quarter is published, the page is
   pinned to that exact snapshot.
3. **Archival.** `prediction_outcomes` grows by ~15k rows / quarter.
   After 5 years (~300k rows) we should partition by year, mirroring
   the approach in `scripts/archive_windowed_tables.py`.
4. **IPO handling.** Stocks listed within the outcome window have
   undefined `prediction_date` returns. Phase 2 silently drops them
   (no row in `daily_prices` on prediction_date → `compute_for_date`
   returns None). Phase 3 should surface "n IPO'd in window" as a
   footnote rather than dropping silently.

## Files touched

| File | Role |
|---|---|
| `backend/services/analysis/compute_for_date.py` | New. Pragmatic counterfactual entry point. |
| `backend/services/analysis_service.py` | Re-exports `compute_for_date` for backward-compat callers. |
| `backend/services/retrospective_service.py` | Phase 2 DB paths for `record_daily_predictions`, `compute_outcome`, `summarize_for_period`. |
| `backend/routers/public.py` | `/retrospective` endpoint now reads from DB; `is_sample=False` when data exists. |
| `frontend/src/app/(marketing)/methodology/performance/page.tsx` | Renders `last_updated`; banner conditional on `is_sample`. |
| `scripts/backfill_predictions.py` | Real orchestrator. Argparse, resume-safe UPSERT, throttle. |
| `scripts/compute_outcomes.py` | New. Fills `prediction_outcomes` for elapsed windows. |
| `tests/test_compute_for_date.py` | Counterfactual computation, no DB. |
| `tests/test_backfill_orchestrator.py` | Grid generation + resume-safe path, no DB. |
| `tests/test_outcome_computation.py` | Return math + window-skipping, no DB. |

## How to run the PoC backfill

```bash
# 1. Backfill 30d × 50 canary stocks
python scripts/backfill_predictions.py \
    --start-date 2026-03-28 --end-date 2026-04-26 \
    --tickers canary50 \
    --apply --rate 4

# 2. Compute outcomes for windows that have elapsed
python scripts/compute_outcomes.py \
    --since 2026-03-28 --until 2026-04-26 --apply

# 3. Verify the public endpoint
curl https://api.yieldiq.in/api/v1/public/retrospective?period=last30d&window=30
# Expect: is_sample=false, n_predictions > 0, last_updated set.
```

`DATABASE_URL` is sourced from `.env.local` automatically (best-effort
loader in both scripts). Set `--rate` low (≤ 4 / sec) when running
against prod Aiven to stay polite to the connection pool.
