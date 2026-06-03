# 71 TRUE duplicate rows in `company_financials` — find the write path

**Status:** filed 2026-06-03. Tracker only — NOT dispatched.
**Workstream:** valuation
**Priority:** LOW. Non-blocking. Hygiene, not user-facing.

---

## Context

Source-aware re-count on 2026-06-03 (`corruption-recount-2026-06-03.md`) found **71 canary tickers with ≥2 rows sharing the same `(ticker_nse, period_end_date, statement_type, source)` 5-tuple** in `company_financials`. These are TRUE duplicates — the writer's `ON CONFLICT` key is exactly that 5-tuple, so these rows should not exist if they came through the writer.

The XBRL writer at `data_pipeline/xbrl/db_writer.py:202` has correct `ON CONFLICT … DO UPDATE`. The 71 dups came from some OTHER write path.

## Why this is low priority

`v_financials_unified` (PR #703) already defends consumers at read time via `cf_is_corrupt`. The 71 dups produce zero user-facing wrong values the moment consumers switch to the view. This investigation is hygiene — finds and closes the leak that creates fresh dups — but the leak's downstream impact is already contained.

## Why it shouldn't gate anything

This is the kind of investigation that has spawned three premise cracks already this session (the original reconciliation diagnosis, the ON CONFLICT writer claim, the "5 zero-row tickers" claim — all wrong). The agent's three hypotheses for the actual write path are plausible-but-untested:

- Historical pre-`ON CONFLICT` inserts (rows from before the writer was hardened)
- Batch loaders that bypass the writer (candidates: `scripts/transform_financials_to_company_financials.py`, `scripts/backfill_xbrl_10y.py`, `data_pipeline/sources/yfinance_supplement.py`)
- `period_type` normalization mismatches (`'annual'` vs `'A'`) — would defeat the conflict key

If this investigation cracks open a fourth hypothesis or surfaces yet another miscount, the right move is **STOP investigating and just contain** — the view defends consumers; further investigation has diminishing returns.

## What a dispatch looks like (when convenient)

Small read-only agent, hard 15-minute time-box, scope explicitly bounded to:

1. **For each of the 71 dup tickers, examine the row pair(s).** Get the full row including `created_at` (if column exists), `source` value, all financial columns. Are the duplicates byte-identical (true dup) or do columns differ (sequential overwrite that wasn't deduplicated)?
2. **Search git history for INSERT statements targeting `company_financials`** — both in code on `origin/main` and in `scripts/` (one-off backfills). Identify which paths exist and which are no-`ON CONFLICT`.
3. **Check `period_type` distribution** — are there both `'annual'` and `'A'` values? Both `'quarterly'` and `'Q'`? A normalization mismatch would defeat the conflict key without touching the writer.
4. **Report findings.** Either: (a) identified specific write path X, recommend fix; (b) historical insert pre-dating hardening, recommend cleanup query + leave writer alone; (c) inconclusive, recommend stopping.

NO write-side fixes. NO migrations. NO PRs. NO consumer rewiring. Diagnosis only.

## When to dispatch

- After Phase 1 chain settles AND consumer-rewiring PR is merged. The view's `cf_is_corrupt` is already defending; this is pure hygiene that benefits from happening in a quiet window when no other valuation work is in flight.
- Or: never, if the recurring-investigation pattern this session has taught us suggests this thread isn't worth pulling. Defensible.

## Acceptable end-states

- "The 71 dups come from path X; here's the cleanup query + the writer/loader fix." Ship the fix.
- "Inconclusive after 15 min. Containment via the view is the practical answer." File closed, view continues to defend.

Either is fine. What is NOT acceptable: a multi-hour investigation that spawns three sub-investigations and consumes attention proportional to its low priority.

## Cross-references

- `redesign/followups/corruption-recount-2026-06-03.md` §2 (the 71 count, the three hypotheses)
- `redesign/followups/financials-table-reconciliation.md` (SUPERSEDED — the original diagnosis whose ON CONFLICT premise was wrong)
- `PR #703` (`feat/v-financials-unified-view`) — the read-time defense that makes this LOW priority
