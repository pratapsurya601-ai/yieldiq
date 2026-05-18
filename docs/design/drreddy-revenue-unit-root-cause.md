# DRREDDY DCF inflation — root-cause investigation

Date: 2026-05-18
Branch: `fix/drreddy-root-cause`
Status: **hypothesis-confirmed but no DB access from sandbox → ships diagnostic
probe + design only; no production fix yet**. PR #332 defensive
`cf_reality_cap` stays in place as defense-in-depth.

## TL;DR

PR #332 added a defensive cap on `_compute_fcf_base` that pulls DRREDDY's
FV from ₹3,949 down to ₹2,016. That cap masked the symptom but **the
real bug is in `enriched["latest_revenue"]`**: production live values
for DRREDDY.NS show it equals ~₹2,331 Cr (i.e. ~14× too small — real
TTM revenue is ~₹32,554 Cr). FCF, debt, cash, shares are all
**correct**. Only revenue is broken, and the malformed magnitude
("₹2,331 Cr" ≈ sum of 4 *standalone* quarterly filings) is the smoking
gun.

## Production evidence (live, captured 2026-05-18)

Endpoint: `GET https://api.yieldiq.in/api/v1/public/reverse-dcf/DRREDDY.NS`
returns the values that the analysis-service-cached `computation_inputs`
fed into the reverse-DCF solver:

| field            | prod value                | unit check      | real     |
|------------------|---------------------------|-----------------|----------|
| current_fcf      | 33,431,000,000.0          | ₹3,343 Cr  ✅    | ~₹3-4 k Cr |
| **current_revenue**  | **23,314,107,546.4**       | **₹2,331 Cr ❌**   | ~₹32,554 Cr |
| current_margin   | 1.4339386542446562        | 143% ❌          | ~10–12%    |
| total_debt       | 67,732,000,000.0          | ₹6,773 Cr ✅    | ~₹6,700 Cr |
| total_cash       | 18,657,000,000.0          | ₹1,866 Cr ✅    | ~₹1,500 Cr |
| shares           | 832,594,805               | 83.3 Cr  ✅     | 83.3 Cr   |
| normalized_fcf   | 57,480,000,000.0          | ₹5,748 Cr ✅    | ~₹5-6 k Cr |

`current_revenue / 1e7 = 2,331.4 Cr` — exactly the "₹2,331 Cr" figure
the original a273 audit flagged. This is **NOT a 1e7 unit-mismatch**
(the magnitudes match across FCF/debt/cash/shares); revenue itself
carries the wrong numerical value.

Reference annual data (from same prod, `/public/financials/DRREDDY.NS`)
confirms the table holds correct data — DRREDDY FY25 annual revenue is
32,553.5 Cr (`data_source=yfinance`), FY24 is 27,916.4 Cr
(`data_source=NSE_XBRL`), all `currency=INR`. So the annual / yfinance
ladder data is healthy; the contamination is somewhere in the *TTM
resolution* step.

## Five hypotheses (from prior audit) — disposition

| # | Hypothesis | Verdict |
|---|------------|---------|
| 1 | Reverse-DCF display layer extra ÷1e7 | **REJECTED** — units balance correctly across FCF/debt/cash; the displayed margin 143% is the *consequence* of the wrong revenue, not a unit display bug. |
| 2 | `_query_ttm_financials` USD-tagged row survives the >1e10 guard then ×83 | **REJECTED** — `_detect_currency("DRREDDY")` returns "INR" (DRREDDY is *not* in `USD_REPORTER_TICKERS` in `data_pipeline/sources/bse_xbrl.py:24`). FX multiplier is 1.0; the ×83 path cannot fire here. |
| 3 | `_apply_scale_guard` skipping 3 of 4 quarters → partial TTM | **REJECTED** — if `_sum("revenue_cr")` returns None on partial, `compute_ttm_from_xbrl` returns `revenue_ttm=None`, `resolve_ttm_for_analysis` would NOT overwrite `enriched.latest_revenue` (line 586 guard), and yfinance income_df value (raw INR ~3.25e11) would survive. We'd see ~3.25e11, not 2.33e10. |
| 4 | Different code path populating `enriched.latest_revenue` (EPS×shares÷PE, stale Financials row, etc.) | **PARTIAL** — see hypothesis #5; not a separate path but a specific data shape. |
| 5 | "₹2,331 figure is quarterly, not TTM" | **STRONG MATCH** — see below. |

## Likely root cause: standalone-fallback in `get_quarterly_results`

`backend/services/quarterly_results_service.py:235-251` prefers consolidated
rows but falls back to standalone when no consolidated rows exist for the
ticker:

```python
def _fetch(is_consolidated: bool) -> list[dict]:
    rows = db.execute(text(
        "SELECT ... FROM company_quarterly_results "
        "WHERE ticker = :t AND is_consolidated = :c "
        "ORDER BY period_end DESC LIMIT :n"
    ), {"t": db_ticker, "c": is_consolidated, "n": n_quarters}).mappings().all()
    return [dict(r) for r in rows]

if consolidated:
    rows = _fetch(True)
    if not rows:
        rows = _fetch(False)         # ← standalone fallback
```

DRREDDY's STANDALONE quarterly revenue is ~₹580 Cr (versus consolidated
~₹8,000 Cr). 4 standalone quarters sum to ~₹2,300 Cr — exactly the
2,331 Cr we observe in production. So DRREDDY's
`company_quarterly_results` rows are very likely **standalone-only** in
prod (no `is_consolidated=true` rows), the fallback triggers, and
`compute_ttm_from_xbrl` happily aggregates them into a "TTM" that's
~14× too small.

`partial=False` (4 quarters present), so `resolve_ttm_for_analysis`
**does** overwrite `enriched["latest_revenue"]` with the bogus value.
The whole revenue-scaled candidate stack downstream
(`nopat_proxy`, `pharma_rd_adjusted`, `hist_p75_margin`) is then
computed off ₹2,331 Cr × margin × scaling factors — producing modest
candidates (e.g. nopat_proxy ~ ₹350 Cr) that the `latest_fcf` /
`max_recent_fcf` candidates dominate via the `max()` selection in
`_compute_fcf_base`. Net effect:

- `latest_fcf` candidate ≈ ₹3,343 Cr (correct, from cf_df)
- `max_recent_fcf` ≈ ₹4,001 Cr (correct, from cf_df 5-tail)
- Revenue-scaled candidates ~ ₹350-1,000 Cr (depressed; not selected)
- Forward-DCF picks `max_recent_fcf` → FV ≈ ₹4,000 Cr base

That FV-side selection isn't where the 196% MoS came from. The
*reverse-DCF surfaced* `normalized_fcf=2.43e+16` value cited in PR #332
points at a *different* shape — but per the live data we now see,
`normalized_fcf` is back to ₹5,748 Cr (sane). So either:

  a) The prod cache for DRREDDY has been recomputed since the PR #332
     write-up and the 2.43e+16 number is stale, or
  b) The 196% MoS came primarily from the verdict layer using
     `current_margin=143%` directly to size some other component (e.g.
     forward-DCF rebuilds FCF from `revenue × margin` somewhere).

Either way, **fixing the consolidated/standalone fallback is necessary
even if PR #332 cap holds**, because the wrong-magnitude revenue
poisons every margin/ratio/red-flag that uses it.

## Why I'm not shipping the fix in this PR

Per CLAUDE.md "Data-fix discipline":
- The fix would touch `backend/services/quarterly_results_service.py`,
  which means **canary-diff must pass** before merge.
- The canary will likely show DRREDDY FV moving from ₹2,016 → ~₹1,200-
  1,500 (consensus band) which is **expected and good**, but other
  tickers that share the "standalone-only filings" shape (need to be
  enumerated) will also move. PR description must explain each >15% FV
  delta — that requires running canary_diff against the proposed fix,
  which needs DB access.
- Sandbox has no DNS to Aiven (`pg-…aivencloud.com` unresolvable), so
  I cannot run `compute_ttm_from_xbrl("DRREDDY.NS")` locally to confirm
  the exact `is_consolidated` distribution of the cached rows.

## Concrete next-step verification (must be run with DB access)

```sql
-- 1. Confirm DRREDDY is standalone-only in company_quarterly_results.
SELECT is_consolidated, COUNT(*) AS n,
       MIN(period_end) AS oldest, MAX(period_end) AS newest,
       AVG(revenue_cr) AS avg_rev_cr
  FROM company_quarterly_results
 WHERE ticker = 'DRREDDY'
 GROUP BY is_consolidated;

-- 2. Confirm period_type='ttm' row in financials (if any) for DRREDDY.
SELECT period_end, currency, data_source, revenue, pat, free_cash_flow
  FROM financials
 WHERE ticker = 'DRREDDY'
   AND period_type = 'ttm'
 ORDER BY period_end DESC LIMIT 5;
```

Expected (if hypothesis is right):
- Query 1: 0 rows with `is_consolidated=true`, 4+ rows with `false`,
  `avg_rev_cr` ≈ 580.
- Query 2: 0 rows OR ttm row with `revenue ≈ 2331` (Cr; the
  standalone-sum TTM that was persisted).

## Proposed fix (~30 LOC, ships in next PR with canary)

Two layered changes, both in `backend/services/quarterly_results_service.py`:

1. **Make `get_quarterly_results` log + tag a `standalone_fallback`
   flag when it falls back**, instead of silently returning standalone
   rows that the rest of the pipeline treats as authoritative. The flag
   propagates into the returned dict's `data_issues` so
   `resolve_ttm_for_analysis` can choose to *skip* the XBRL TTM in
   favour of the legacy `_query_ttm_financials` / annual ladder.

   ```python
   # quarterly_results_service.py: get_quarterly_results
   if consolidated:
       rows = _fetch(True)
       if not rows:
           rows = _fetch(False)
           if rows:
               # NEW: tag so callers can detect standalone-only data
               for r in rows:
                   r["_standalone_fallback"] = True
   ```

2. **Treat standalone-fallback as `partial=True`** for large-cap NSE
   tickers (configurable allowlist) so the resolver falls through to
   the yfinance-backed legacy TTM ladder, which uses `income_df` (raw
   INR, already correct for DRREDDY at ₹32,554 Cr).

   ```python
   # quarterly_results_service.py: compute_ttm_from_xbrl, after rows fetch
   if rows_window and rows_window[0].get("_standalone_fallback"):
       _logger.warning(
           "%s: only standalone quarterly rows available — marking "
           "TTM as partial to defer to legacy ladder", ticker,
       )
       return {..., "partial": True, "data_issues": ["standalone_only"]}
   ```

Tests: extend `backend/tests/test_quarterly_results_service.py` with a
case where `_fetch(consolidated=True)` returns `[]` and the helper
flags `partial=True`.

Expected DRREDDY FV change post-fix (no cap):
- `enriched.latest_revenue` reverts to yfinance income_df value
  (~₹32,554 Cr / 3.25e11 raw INR).
- `current_margin` snaps back to ~10% (3,343 / 32,554).
- `nopat_proxy = revenue × op_margin × (1-tax) × 0.85 ≈ ₹4,000 Cr`,
  becomes a sensible candidate.
- DCF FV expected band: **₹1,200-1,500** (matches consensus).

PR #332 cap stays as belt-and-suspenders.

## Out of scope for this branch

- The standalone vs consolidated tagging in
  `data_pipeline/sources/nse_quarterly_xbrl.py` ingestion layer — that's
  where DRREDDY should be *getting* consolidated rows but isn't. Need
  a follow-up to audit which other tickers have standalone-only
  XBRL rows in `company_quarterly_results`. The fallback fix above
  defends against ALL such tickers without needing to enumerate them.
- The dupont endpoint bug (revenue_cr=0.0 on all years) — separate
  issue, unrelated to the DCF inflation.
