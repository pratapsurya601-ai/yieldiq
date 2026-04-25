# Ingest gap: `financials.period_type='ttm'` rows are never written

**Status:** open
**Filed:** 2026-04-25
**Affects:** PR #70's TTM-FCF annual-fallback (`backend/services/analysis/db.py::_query_ttm_financials`, lines 197-246)

## TL;DR

The `financials` table on Neon contains **zero** rows with
`period_type='ttm'` for **any** ticker. Every TTM-related code path in
`_query_ttm_financials` (PR #70) — Path 1 (healthy TTM), Path 2
(propagation gap), and Path 3 (annual-FCF fallback) — is unreachable in
production. The function always returns `None` at the early
`if row is None: return None` guard (db.py:179-180).

The TTM ingest function `data_pipeline/sources/bse_xbrl.py::store_ttm`
exists and is wired into `data_pipeline/run_fundamentals.py`, but it is
gated behind a BSE Peercomp ingest path that has produced **0 rows** in
production. The actual financials data was loaded via the NSE_XBRL
pipeline, which never invokes `store_ttm`.

## Evidence

Run against `NEON_DATABASE_URL` on 2026-04-25:

```sql
SELECT period_type, COUNT(*) FROM financials GROUP BY period_type;
-- annual    | 14340
-- quarterly | 40015
-- (no ttm row)

SELECT data_source, COUNT(*) FROM financials GROUP BY data_source ORDER BY 2 DESC;
-- NSE_XBRL            | 40476
-- NSE_XBRL_SYNTH      |  7606
-- yfinance            |  4006
-- NSE_XBRL_STANDALONE |  2267
-- yfinance_backfill   |     3
-- (no BSE_PEERCOMP, no BSE_TTM)
```

Distinct `period_type` values are exactly `{'annual','quarterly'}`.

Latest quarterly period across the universe is `2024-12-31` (1,892 of
1,942 tickers) — over a year stale relative to today (2026-04-25).

## Root cause

`data_pipeline/run_fundamentals.py` at line 64-65:

```python
if stored_from_bse > 0:
    store_ttm(ticker, db)
```

`store_ttm` only fires when the BSE Peercomp branch returns rows.
Production data came in via `data_pipeline/sources/nse_xbrl_fundamentals.py`
(invoked by `phase_c_fundamentals_10y.yml` and friends). That code path
writes `period_type='annual'` and `period_type='quarterly'` rows but
never calls `store_ttm` or any equivalent.

Result: `_query_ttm_financials` returns `None` on every call in prod, so
PR #70's PR-70 fallback ladder (Paths 2 and 3) is dead code. The DCF for
RELIANCE post-PR-70 looks correct only because the `local_db_parquet`
fast path (`backend/services/local_data_service.py::assemble_local`)
synthesises a TTM data point itself from `company_financials` quarterlies
(see `local_data_service.py:236-265`) — a **separate code path** that
does not touch the `financials.ttm` rows.

## Why this matters

Two unrelated TTM mechanisms exist:

1. `financials.period_type='ttm'` rows — the intended canonical store,
   queried by `_query_ttm_financials` from `analysis/service.py:392`.
   **Empty in production.**
2. On-the-fly TTM synthesis inside `assemble_local` — reads
   `company_financials` quarterlies and appends a synthetic TTM data
   point with `fcf ≈ 0.6 * ttm_ebitda`. **Currently the only reason
   DCF outputs are reasonable.**

When `assemble_local` returns data, `_query_ttm_financials` is still
called (service.py:392) but produces nothing, so the request silently
falls through to `_query_latest_annual_financials`. The "TTM" label
reported in cache/diagnostics is therefore misleading: the actual TTM
behaviour comes from path #2, not path #1.

## Options

### A. Backfill `financials.ttm` from NSE_XBRL quarterlies (recommended)

Add a post-pass to `data_pipeline/sources/nse_xbrl_fundamentals.py` (or
to a new `data_pipeline/build_ttm.py`) that, after quarterly rows land,
calls the existing `store_ttm` helper for every ticker that has 4 fresh
quarters. The helper already does the right thing — it just needs to be
invoked from the pipeline that actually runs.

Estimated change: ~10 lines, plus a new GitHub Actions step in
`financial_data_pipeline_full.yml` to run the backfill once per pipeline.

Caveat: latest quarterly today is 2024-12-31. A backfilled TTM row would
be ~16 months stale. We need to fix the upstream quarterly refresh
cadence (separate issue) before the backfill produces useful data.

### B. Drop the `financials.ttm` mechanism entirely

If the on-the-fly synthesis in `assemble_local` is considered the
canonical TTM, then `_query_ttm_financials` and `store_ttm` are both
vestigial. Remove them and update `analysis/service.py:392` to skip
straight to `_query_latest_annual_financials`. PR-70's tests would be
removed alongside.

Risk: any future code that wants TTM (e.g. for tickers without
`company_financials` quarterly coverage) would have nowhere to read it
from.

### C. Status quo — document and leave

Keep the dead code with the understanding that it's a shim for a future
ingest fix. Risk: contributors continue to assume TTM is populated and
write more dead branches against it.

## Recommendation

Option A. The infra (`store_ttm`, `calculate_ttm`, the schema, the
unit-test suite in `backend/tests/test_fcf_fallback_and_fv_clamp.py`)
already exists. The missing piece is a single call site in the
NSE_XBRL pipeline.

Track upstream quarterly staleness (latest = 2024-12-31) as a separate
issue — without fresh quarterlies, even a working TTM backfill is of
limited value.

## Do not

- Do **not** modify `_query_ttm_financials` to "make it work" against
  the empty TTM table. The function is correct; the table is empty.
- Do **not** delete `backend/tests/test_fcf_fallback_and_fv_clamp.py` —
  those tests document the expected behaviour for when TTM rows do
  exist, and they exercise the function directly via mocks.

## Files referenced

- `backend/services/analysis/db.py` — `_query_ttm_financials` (lines 145-253)
- `backend/services/analysis/service.py` — call site at line 392
- `backend/services/local_data_service.py` — TTM synthesis at lines 236-265
- `data_pipeline/sources/bse_xbrl.py` — `calculate_ttm` (589), `store_ttm` (642)
- `data_pipeline/run_fundamentals.py` — `store_ttm` call gated at line 64-65
- `data_pipeline/sources/nse_xbrl_fundamentals.py` — actual prod ingest path, no TTM call
- `backend/tests/test_fcf_fallback_and_fv_clamp.py` — unit tests (10/10 pass against mocks)
