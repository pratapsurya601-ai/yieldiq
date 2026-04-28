# `ratio_history` audit + rebuild — design

Status: scaffolding (this PR). Real prod rebuild is a separate ops session.

## Why this matters

The analysis page applies a **peer-cap** to fair-value estimates: when
the implied fair value would exceed the peer-set's median P/E or
EV/EBITDA multiple by an unreasonable margin, the FV is capped. This
is one of the strongest defences against the +60-91% Margin-of-Safety
outliers the 2026-04-28 launch audit surfaced on JUSTDIAL, EMAMILTD,
NATCOPHARM, SANOFI, ZYDUSLIFE, and MAYURUNIQ.

Peer-cap reads `pe_ratio` and `ev_ebitda` from the `ratio_history`
table. If those columns are NULL or unit-bug-corrupted on the peer
set, peer-cap silently falls back to "no cap" and the outliers walk
straight through to the user.

This audit confirms — and the rebuild surgically corrects — that the
required peer multiples are present and within sane bounds for every
ticker in the canary + outlier universe **before** peer-cap is
declared "live" on the analysis page.

### The two bug classes the audit looks for

| Class           | Symptom                              | Origin |
|---              |---                                   |---     |
| `null_pe`       | `pe_ratio IS NULL` on latest row     | builder skipped — no pat / no price / silent failure |
| `sub_one_pe`    | `pe_ratio` between 0 and 1           | pre-PR-#126 `_normalize_pct` double-multiplied a percent value |
| `hyper_roe`     | `roe > 100`                          | same family — decimal-already-percent multiplied by 100 |
| `hyper_roce`    | `roce > 100`                         | as above |
| `stale`         | latest `period_end` > 90 days old    | builder never reached the ticker, or hasn't since |
| `missing`       | no rows at all                       | builder failure or first-time ticker |

The IT-services peers (HCLTECH 0.30, WIPRO 0.25, TECHM 0.36) are
canonical examples of `sub_one_pe`. The audit's pure-function
`evaluate_row` is the single source of truth for these rules and is
exercised by `tests/test_ratio_history_audit.py`.

## How to run

### 1. Audit (read-only)

```bash
export DATABASE_URL='postgres://...neon...'
python scripts/audit_ratio_history.py --include-canary \
    --out reports/ratio_history_audit_$(date +%F).csv
```

CSV columns: `ticker, flag, latest_period_end, pe_ratio, ev_ebitda,
pb_ratio, roe, roce, days_stale, remediation_hint`.

Default ticker scope is the 9 outliers from the launch audit
(`JUSTDIAL, EMAMILTD, NATCOPHARM, SANOFI, ZYDUSLIFE, MAYURUNIQ,
HCLTECH, WIPRO, TECHM`). `--include-canary` extends scope to
`scripts/canary_stocks_50.json` + `scripts/canary_outliers_7.json`.
`--tickers T1,T2,...` overrides both.

Exit code is always 0 unless DB connectivity fails — flagging is not
a failure. The CSV is the artefact downstream tooling consumes.

### 2. Rebuild (writes — opt-in)

```bash
# Single-ticker dry-run first
python scripts/rebuild_ratio_history.py --ticker JUSTDIAL --dry-run

# Single-ticker apply
python scripts/rebuild_ratio_history.py --ticker JUSTDIAL --apply

# All flagged from a prior audit CSV
python scripts/rebuild_ratio_history.py --all-flagged \
    --audit-csv reports/ratio_history_audit_2026-04-28.csv \
    --apply
```

`--apply` is required for any DB writes; without it, the script
prints the `build_ratio_history.py` invocation it would run but does
not execute it. Idempotent — UPSERT keyed on
`UNIQUE (ticker, period_end, period_type)`.

The rebuild shells out to the canonical `build_ratio_history.py` per
ticker so this driver script never duplicates the recompute logic
(EBIT fallbacks, FX conversion, corp-action adjustment). Subprocess
isolation also means a crash on one ticker doesn't take out the run.

### 3. Verify (post-rebuild gate)

```bash
python scripts/verify_peer_cap_inputs.py --tickers \
    JUSTDIAL,EMAMILTD,NATCOPHARM,SANOFI,ZYDUSLIFE,MAYURUNIQ
```

Asserts that for every ticker in scope, **at least 3 same-industry
peers** have a latest-row `pe_ratio` AND `ev_ebitda` within bounds
(P/E in [5, 50], EV/EBITDA in [3, 25]). Exit code 0 = peer-cap
precondition met. Exit code 1 = at least one ticker lacks usable
peers — peer-cap will silently no-op on those tickers and a further
rebuild round is needed.

This is intended to be wired into the merge-gate harness alongside
`canary_diff.py` once peer-cap goes live.

## Schema reference

`ratio_history` is defined in
`data_pipeline/migrations/005_ratio_history_peer_groups.sql`. The
columns the audit reads:

- `ticker` (FK-shape, no FK constraint)
- `period_end` (DATE) + `period_type` ("annual" | "quarterly" | "ttm")
- `pe_ratio`, `ev_ebitda`, `pb_ratio` (DOUBLE PRECISION)
- `roe`, `roce` (DOUBLE PRECISION, **percent**)
- Unique constraint: `(ticker, period_end, period_type)`
- Index: `idx_ratio_history_ticker_period (ticker, period_end DESC)`

The audit's "latest row per ticker" query uses
`SELECT DISTINCT ON (ticker) ... ORDER BY ticker, period_end DESC`
which rides the existing index without an extra sort.

## Open questions

These are deliberately left for the prod-rebuild ops session, not
this scaffolding PR:

1. **Wipe + rebuild, or surgical?**
   Recommended: surgical for the 9 known outliers + every ticker the
   first audit run flags. A full universe rebuild is hours of work
   and risks collateral damage if the builder regresses on a class
   of tickers we haven't validated. Surgical scales to "one bug
   class at a time."

2. **Source of truth for the rebuild — TTM `financials` or live yfinance?**
   Recommended: stored `financials` only. yfinance live values would
   convert this from a "repair history" job into a "snapshot today"
   job, defeating the purpose. The corrected `_normalize_pct` (PR
   #126) is sufficient to recompute correctly from the same raw rows
   that produced the bug originally.

3. **CACHE_VERSION bump?**
   No — per CLAUDE.md rule 2, never bump casually. The fix is at the
   data layer (`ratio_history`) not the analysis layer; analysis
   code already reads whatever's in the table and recomputes
   downstream signals on the fly.

4. **Run cadence.**
   One-shot for the launch fix. Beyond that: hook the audit into the
   nightly canary run so any future regression in
   `build_ratio_history.py` is caught within 24h.

5. **Failure mode if the rebuild doesn't fix a ticker.**
   The `verify_peer_cap_inputs.py` exit-1 is the gate. If verify
   keeps failing on the same ticker after rebuild, the upstream
   defect is in `financials` (XBRL parse / yfinance backfill) not
   `ratio_history` — escalate to the data-pipeline track, do not
   patch around it in the analysis layer.

## Discipline checks

- `python -m pytest tests/test_ratio_history_audit.py` — 15/15
  passing on synthetic data, no live DB required.
- `--dry-db` mode lets the audit run end-to-end (CSV + summary) with
  no DB at all, suitable for CI smoke tests.
- The rebuild script defaults to `--dry-run`; writes require explicit
  `--apply`.
- No `CACHE_VERSION` bumps. No long-running jobs in any worker.
