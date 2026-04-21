# Ticker Format Audit

*Last updated: 2026-04-21*

## Problem statement

The YieldIQ database uses inconsistent ticker formats across tables.
This causes JOINs to silently miss rows (e.g. `analysis_cache` row for
`TCS.NS` never matches `stocks.ticker = 'TCS'`), and forces every
reader to carry ad-hoc `replace(".NS", "").replace(".BO", "")` logic.

This PR lays **groundwork only** - a helper module and tests, plus this
audit. The migration itself is staged across 3-5 follow-up PRs.

## Current state (as of 2026-04-21)

| Table                 | Format              | Rows (approx) | Notes                                   |
| --------------------- | ------------------- | ------------- | --------------------------------------- |
| `financials`          | BARE                | ~2k           | No `.NS`, no `.BO`                      |
| `market_metrics`      | BARE (mostly)       | 3,780         | ~70% dup due to NSE+BSE dual listings   |
| `ratio_history`       | BARE                | ~10k          |                                         |
| `daily_prices`        | BARE                | millions      | partitioned parquet + DB mirror         |
| `stocks`              | BARE (+ 175 `.BO`)  | ~2k           | 175 BSE-only rows use `.BO` suffix      |
| `analysis_cache`      | **MIXED**           | 322           | 173 `.NS` + 149 bare                    |
| `live_quotes`         | `.NS` (canonical)   | ~500          | **100% canonical** - the target format  |

## Canonical format (target)

We are moving toward `<BARE>.NS` for NSE tickers, `<BARE>.BO` for
BSE-only tickers - the same format `live_quotes` already uses. Reasons:

1. **Matches yfinance**: no translation layer on the data-pipeline side.
2. **Self-identifying**: the suffix tells you which exchange was queried.
3. **One table already there**: `live_quotes` pins the convention so we
   don't have to argue about it.
4. **Bare form is lossy**: `TCS` could be NSE or BSE - the canonical
   form removes that ambiguity.

## Migration plan - staged over 3-5 PRs

**PR 1 (THIS PR)** - Groundwork, zero behaviour change.
- Add `backend/services/ticker_utils.py` with `to_canonical` /
  `from_canonical` helpers.
- Add unit tests in `backend/tests/test_ticker_utils.py`.
- Document current state and target (this file).
- Dedupe `market_metrics` at read time in every caller.

**PR 2 - New writes land in canonical form.**
- Wire `to_canonical` into every `INSERT` / `UPSERT` path:
  - `analysis_cache` writes (`backend/services/analysis_service.py`)
  - `live_quotes` writes (already canonical, no change)
  - `fair_value_history` writes (confirm + align)
- No reader changes - readers still tolerate both formats via fallback
  `WHERE ticker = :t OR ticker = :t || '.NS'` patterns.

**PR 3 - Backfill.**
- One-off script `scripts/backfill_canonical_tickers.py` that rewrites
  every row in `analysis_cache`, `stocks`, `market_metrics`,
  `ratio_history`, `daily_prices`, `financials` to canonical.
- Run under `CACHE_VERSION` bump + canary-diff before/after snapshot
  (per CLAUDE.md data-fix discipline).
- Keep a `ticker_old` column on every mutated table for rollback.

**PR 4 - Flip readers.**
- Drop the `OR ticker = :t || '.NS'` fallback from every reader (grep
  for the literal pattern; there are ~12 of them).
- Every DB-query in `backend/services/` and `backend/routers/` uses
  `to_canonical(ticker)` at the boundary.

**PR 5 - Drop legacy support.**
- Remove `replace(".NS", "").replace(".BO", "")` and any remaining
  `from_canonical` shims from callers that no longer need them.
- Drop the `ticker_old` rollback columns from PR 3.

## Don't do this

These are the unsafe patterns that caused the current chaos. If you
catch any of them in a PR review, reject.

### 1. `ticker = s.ticker` without normalisation

```python
# WRONG - compares bare "TCS" against canonical "TCS.NS" -> 0 matches
row = db.execute(text("SELECT * FROM analysis_cache WHERE ticker = :t"),
                 {"t": "TCS"}).fetchone()
```

```python
# RIGHT - always route through to_canonical at the boundary
from backend.services.ticker_utils import to_canonical
row = db.execute(text("SELECT * FROM analysis_cache WHERE ticker = :t"),
                 {"t": to_canonical("TCS")}).fetchone()  # -> "TCS.NS"
```

### 2. `replace(".NS", "").replace(".BO", "")` in new code

This works but is error-prone (what about `-EQ`? `-X`?). Prefer
`from_canonical(ticker)` which also handles hyphen suffixes.

### 3. Assuming one row per ticker in `market_metrics`

`market_metrics` has **2 rows for dual-listed tickers** (NSE + BSE) by
design. Any JOIN or COUNT that does not `DISTINCT ON (ticker)` or
`GROUP BY ticker` first will produce inflated results. See the design
note at the top of `backend/routers/screener.py`.

### 4. Writing a mix of bare and suffixed tickers to the same table

This is how `analysis_cache` got into its current MIXED state. Decide
the format at write time (use `to_canonical`) - the consumer should
never have to guess.

### 5. Building a ticker string with `f"{t}.NS"` directly

```python
# WRONG - if t is already "TCS.NS" you get "TCS.NS.NS"
full = f"{t}.NS"
```

```python
# RIGHT
full = to_canonical(t)
```

## References

- `backend/services/ticker_utils.py` - the helpers
- `backend/services/portfolio_service.py::_fetch_yfinance_price` - the
  precedent for hyphen-suffix stripping
- `backend/routers/screener.py` - the `market_metrics` dedupe design note
