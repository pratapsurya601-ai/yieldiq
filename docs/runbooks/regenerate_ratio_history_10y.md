# Runbook — Phase F.4: regenerate ratio_history (10y)

**Script:** `scripts/regenerate_ratio_history_10y.py`
**Owner-on-call:** data-pipeline owner
**Expected wall-clock:** ~5 min for top-500 (DB-only work — no upstream).
**Audit:** `docs/diagnostics/phase-f-historical-depth-audit-2026-05-25.md`

## What this does

Thin wrapper over the canonical `scripts/build_ratio_history.py` that:

1. Resolves the same `--tickers` spec the F.2 / F.3 scripts accepted.
2. Delegates the actual recomputation to `build_ratio_history.py`
   via subprocess (preserves single-owner code path; no logic
   duplication).
3. Runs a post-regen validator: queries `ratio_history.pe_ratio` null-
   rate per ticker; logs a warning when any ticker exceeds 10 %
   (Phase A issue #546 — surfaced a 50.9 % null spike, F.4 prevents
   silent regression).

The companion manifest entry `v_phase_f_historical_depth_2026_05_25`
ships in the same PR. It invalidates cached `cagr_3y`, `cagr_5y`,
`cagr_10y`, `ratio_history`, and `compounded_growth` across all
tickers — first-read recompute will use the deeper history backfilled
by F.2 / F.3.

## Operator commands

```bash
export DATABASE_URL='postgres://...'

# 1. Real regen for the canary-333 universe.
python scripts/regenerate_ratio_history_10y.py --tickers canary-333

# 2. Full top-500.
python scripts/regenerate_ratio_history_10y.py --tickers top-500

# 3. Validator only (no regen) — useful immediately after F.3 to
#    establish the baseline before F.4 runs.
python scripts/regenerate_ratio_history_10y.py \
    --tickers top-500 --validate-only

# 4. Restrict to annual ratios.
python scripts/regenerate_ratio_history_10y.py \
    --tickers canary-333 --period-types annual
```

## Post-regen validation

The script emits its own validator output. Additionally:

```sql
-- Per-ticker ratio_history depth post-regen.
WITH u AS (SELECT unnest($1::text[]) AS ticker)
SELECT u.ticker,
       COUNT(*) AS n_rows,
       SUM(CASE WHEN r.pe_ratio IS NULL THEN 1 ELSE 0 END)::float
           / NULLIF(COUNT(*), 0) AS pe_null_rate
FROM   u
LEFT JOIN ratio_history r ON r.ticker = u.ticker
                          AND r.period_type = 'annual'
GROUP BY u.ticker
HAVING SUM(CASE WHEN r.pe_ratio IS NULL THEN 1 ELSE 0 END)::float
       / NULLIF(COUNT(*), 0) > 0.10
ORDER BY 3 DESC;
```

## Manifest entry expectations

After F.4 deploys, expect a single warming spike on the first read of
each ticker (cold recompute of `cagr_*` + `ratio_history` + `compounded_growth`).
The granular manifest matcher scopes the invalidation to those fields
only — `fair_value`, `score`, etc. are not invalidated and remain
warm.

Canary-diff gate is the safety net: any FV swing > 15 % on the 50
snapshot stocks will block the merge per the data-fix discipline rule.

## Discipline reminders

- Run F.4 only AFTER F.2 and F.3 have both completed against the
  same universe. Running F.4 first will re-derive ratios from the
  pre-backfill shallow `financials` rows and ship the manifest
  invalidation prematurely.
- No CACHE_VERSION bump.
