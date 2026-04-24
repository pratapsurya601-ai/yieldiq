# Data Sanity Validation Layer for XBRL Ingest

Status: Draft
Owner: Data pipeline
Last updated: 2026-04-24

## Motivation

On 2026-04-24 we discovered that the BSE/NSE XBRL parser had been silently
selecting the OneD (single-quarter) context instead of the FourD
(year-to-date, full-year) context for annual revenue fields. The effect: for
~2,710 rows (~45% of the NSE ticker universe), annual revenue was written
3x-9x smaller than reality. Examples:

- HCLTECH FY24 revenue stored as Rs.12,000 Cr vs actual Rs.1,09,913 Cr.
- BPCL FY24 revenue stored as Rs.1,32,000 Cr vs actual Rs.4,47,000 Cr.

The bug survived for weeks because four different control layers missed it:

1. There is no pre-insert sanity check comparing a candidate row against the
   prior period for the same ticker.
2. There is no post-backfill reconciliation comparing `financials`
   (XBRL source) against `company_financials` (yfinance source).
3. The nightly canary harness only checks ~50 reference tickers, so a
   sub-sector-level regression is invisible to it.
4. The `/financials` API endpoint reads from `company_financials`
   (yfinance-sourced), which was unaffected, so the bug never surfaced on
   the public surface until a paying customer opened a DCF score that read
   from `financials` directly.

This document specifies a pre-insert validation layer that catches the
entire class of bug above before the row hits Postgres.

## 1. Goals

- Detect OneD-vs-FourD style bugs where annual revenue collapses >50%
  year-over-year with no business reason.
- Detect unit-conversion bugs where a row is off by a 10x/100x/1000x factor
  (rupees vs lakhs vs crores).
- Detect shape-of-data bugs (net income greater than revenue, negative
  total assets, capex with the wrong sign).
- Block bad rows from reaching the `financials` or `company_financials`
  tables *before* a customer-facing score is computed from them.
- Produce a durable, queryable audit trail of every violation so we can
  tune thresholds empirically.

## 2. Non-goals

- Not a replacement for the canary harness. The canary checks a fixed set
  of tickers against known-good reference values; the sanity layer checks
  internal consistency of every row. Both are needed.
- Not a filing-correctness validator. We trust the underlying MCA / NSE
  filing. The layer validates the *parser's output* against the parser's
  own prior outputs and against universal accounting identities.
- Not trying to catch slow drift (e.g. a 2% rounding error compounding
  over five years). Focus is acute errors: off by >50%, wrong sign, wrong
  unit.
- Not a data-quality scoring system. Binary pass/fail per rule, per row.

## 3. Validation rules

All rules live in `data_pipeline/validators/financials_sanity.py` as pure
functions of the candidate row and a small lookup context (prior period
row for the same ticker, latest quarterly row, sector, listing age).

Each rule returns a `Violation(rule_name, severity, message, observed,
expected_range)` or `None`.

### 3.1 `RULE_REVENUE_YOY_SANITY`

- **Checks:** For an annual row, `revenue` must be in
  `[0.5 * prior_revenue, 3.0 * prior_revenue]`.
- **Severity:** BLOCK
- **Exceptions:**
  - Ticker has <2 years of prior data (new listing).
  - Ticker is in `KNOWN_GROWTH_ALLOWLIST` (e.g. recent IPOs expected
    to >3x YoY).
  - Prior period had `revenue < 100 Cr` (tiny base, ratio meaningless).
- **Rationale:** This is the rule that would have caught the OneD/FourD
  bug directly. A parser switching from FY-context to Q4-only context
  produces exactly the "revenue drops to ~25% of prior year" signature.

### 3.2 `RULE_ONED_DETECTION`

- **Checks:** For an annual row, `revenue` must be in
  `[1.5 * latest_quarterly_revenue, 5.0 * latest_quarterly_revenue]`.
  A full-year number should be roughly 4x a single quarter; we widen to
  [1.5x, 5x] to accommodate seasonality and cyclical businesses.
- **Severity:** BLOCK
- **Exceptions:** No quarterly row exists in the last 18 months.
- **Pseudo-code:**
  ```python
  def check_oned(row, ctx):
      if row["period"] != "annual":
          return None
      q = ctx.latest_quarterly_revenue
      if q is None or q <= 0:
          return None
      ratio = row["revenue"] / q
      if not (1.5 <= ratio <= 5.0):
          return Violation(
              rule_name="RULE_ONED_DETECTION",
              severity="BLOCK",
              message=f"Annual revenue {row['revenue']:.0f} is {ratio:.2f}x "
                      f"latest quarterly {q:.0f}; expected [1.5x, 5x]. "
                      f"Likely OneD/FourD context confusion.",
              observed=ratio,
              expected_range=(1.5, 5.0),
          )
      return None
  ```

### 3.3 `RULE_PAT_REVENUE_RATIO`

- **Checks:** `net_income / revenue` must be in `[-0.5, 0.8]`.
- **Severity:** BLOCK
- **Exceptions:** `revenue == 0` (skip; division undefined; usually covered
  by other rules).
- **Rationale:** A single-period margin above 80% or a loss larger than
  50% of revenue is almost always a unit error or a sign flip.

### 3.4 `RULE_PAT_LT_REVENUE_ABS`

- **Checks:** `abs(net_income) <= revenue`. Net income is a sub-component
  of revenue minus expenses; it cannot exceed revenue in absolute value
  for a normally operating firm.
- **Severity:** BLOCK
- **Exceptions:** Firms flagged `is_holding_company=true` (holdings can
  post investment gains exceeding operating revenue). Keep this list
  explicit; do not infer.

### 3.5 `RULE_TOTAL_ASSETS_POSITIVE`

- **Checks:** `total_assets > 0`.
- **Severity:** BLOCK
- **Exceptions:** None.

### 3.6 `RULE_TOTAL_ASSETS_YOY_SANITY`

- **Checks:** `total_assets` in `[0.1 * prior_total_assets,
  10 * prior_total_assets]`.
- **Severity:** BLOCK
- **Exceptions:** Ticker has <2y history. Major M&A event flagged in
  `corporate_actions` table within the fiscal year.

### 3.7 `RULE_CAPEX_SIGN`

- **Checks:** `capex <= 0`. Capex is a cash outflow; our convention stores
  it as negative.
- **Severity:** WARN initially, promote to BLOCK after one backfill cycle.
- **Exceptions:** None. If capex comes in positive, the parser has
  flipped a sign.

### 3.8 `RULE_FCF_IDENTITY`

- **Checks:** `abs(fcf - (cfo + capex)) / max(abs(cfo), 1) <= 0.05`.
  (capex is already negative per 3.7, so `cfo + capex == cfo - |capex|`.)
- **Severity:** WARN
- **Exceptions:** Any of `fcf`, `cfo`, `capex` is NULL.
- **Rationale:** Identity check. A 5% drift tolerates minor
  reclassifications between leasing and investing sections.

### 3.9 `RULE_UNIT_DETECTION_REVENUE`

- **Checks:** `revenue` in `[10, 1_500_000]` (in Crores).
  - Below 10 Cr for a listed large/mid-cap is suspicious (likely
    reported in rupees, not crores — off by 1e7).
  - Above 15,00,000 Cr is larger than Reliance Industries; almost
    certainly a unit bug.
- **Severity:** BLOCK
- **Exceptions:** Micro-cap tickers (market cap < 100 Cr) skip the lower
  bound. Banks / financial institutions skip the upper bound (interest
  income reporting can legitimately push above).

### 3.10 `RULE_SECTOR_REVENUE_PLAUSIBILITY`

- **Checks:** Per-sector band lookup. Example bands (large-cap tier):
  - IT services: `[100 Cr, 5,00,000 Cr]`
  - Oil & gas: `[500 Cr, 10,00,000 Cr]`
  - Banks: `[100 Cr, 15,00,000 Cr]` (total income basis)
  - Pharma: `[50 Cr, 2,00,000 Cr]`
- **Severity:** WARN (bands are heuristic; we don't want to block on them
  until tuned).
- **Exceptions:** Ticker in the bottom market-cap decile for its sector.

### 3.11 `RULE_EQUITY_CONSISTENCY`

- **Checks:** `total_equity = total_assets - total_liabilities` within 1%
  tolerance.
- **Severity:** WARN
- **Exceptions:** Any of the three is NULL.

### 3.12 `RULE_NULL_CORE_FIELDS`

- **Checks:** `revenue`, `net_income`, `total_assets` are all non-NULL for
  annual rows.
- **Severity:** BLOCK
- **Exceptions:** Listing age <90 days (first filing may be partial).

## 4. Implementation

### 4.1 Module layout

```
data_pipeline/
  validators/
    __init__.py
    financials_sanity.py     # rule functions + runner
    sanity_context.py        # loads prior_row, latest_quarterly, sector
    sanity_config.py         # thresholds, allowlists, exceptions
    test_financials_sanity.py
```

Each rule is a top-level function with signature:

```python
def rule_revenue_yoy_sanity(
    row: dict,
    ctx: SanityContext,
) -> Violation | None: ...
```

A single `run_all_rules(row, ctx) -> tuple[bool, list[Violation]]`
evaluates every rule, returns `(ok, violations)` where `ok == True` means
no BLOCK-severity violation fired.

### 4.2 Call sites

1. `data_pipeline/sources/bse_xbrl.py :: store_financials()`
   — immediately before the `INSERT INTO financials` statement.
2. `data_pipeline/xbrl/db_writer.py :: upsert_records()`
   — immediately before the `INSERT INTO company_financials` statement
     (covers the other code path that currently populates financial rows).

Both call sites use the same `run_all_rules` entry point.

### 4.3 Behaviour on violation

- **BLOCK:**
  1. Log a structured record at ERROR level (JSON, one line per violation,
     fields: `ticker, period, rule, observed, expected_range, source`).
  2. Increment the `yieldiq_sanity_blocks_total{rule=...}` Prometheus
     counter.
  3. Do not write the row.
  4. Insert a row into `data_quality_events` (new table) so the nightly
     canary can query it.

- **WARN:**
  1. Log at WARN level with the same structured format.
  2. Increment `yieldiq_sanity_warns_total{rule=...}`.
  3. Write the row normally.
  4. Insert into `data_quality_events` for later review.

### 4.4 `data_quality_events` schema

```sql
CREATE TABLE data_quality_events (
  id            BIGSERIAL PRIMARY KEY,
  ticker        TEXT NOT NULL,
  period_end    DATE NOT NULL,
  source        TEXT NOT NULL,   -- 'nse_xbrl', 'bse_xbrl', 'yfinance'
  rule          TEXT NOT NULL,
  severity      TEXT NOT NULL,   -- 'BLOCK' | 'WARN'
  observed      DOUBLE PRECISION,
  expected_low  DOUBLE PRECISION,
  expected_high DOUBLE PRECISION,
  message       TEXT NOT NULL,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ON data_quality_events (ticker, period_end);
CREATE INDEX ON data_quality_events (rule, created_at);
```

## 5. Historical backtest

Before enabling the layer in the ingest path, run the validators against
the CURRENT state of `financials` to confirm they would have caught the
OneD/FourD bug.

### 5.1 Test script

`scripts/backtest_sanity_validators.py`

```python
def backtest():
    rows = db.fetch_all("""
      SELECT * FROM financials WHERE source = 'nse_xbrl'
    """)
    counts = defaultdict(int)
    for row in rows:
        ctx = SanityContext.for_row(row)
        ok, violations = run_all_rules(row, ctx)
        for v in violations:
            counts[v.rule_name] += 1
    print(counts)
    print(f"Total rows: {len(rows)}; blocked: {sum(...)}")
```

### 5.2 Expected results

- `RULE_REVENUE_YOY_SANITY`: fires on approximately 2,710 rows.
- `RULE_ONED_DETECTION`: fires on approximately 2,710 rows (substantial
  overlap with the above).
- Overall row block rate: approximately 4% of the `nse_xbrl` corpus.
- `RULE_PAT_LT_REVENUE_ABS`: fires <50 times (sanity upper bound).
- `RULE_CAPEX_SIGN`: fires 0 times if the sign convention is consistent.

If `RULE_ONED_DETECTION` fires materially less than 2,700, the threshold
is too permissive and must be tightened before rollout.

## 6. Canary harness integration

Add one new check to the nightly canary job:

```
sanity_failure_rate = count(data_quality_events where severity='WARN'
                            and created_at > now() - interval '24 hours')
                    / count(rows inserted in same window)
```

Alert if `sanity_failure_rate > 0.01` (1%). This catches a regression
where a previously-clean rule starts firing because a new parser change
drifted the data.

A second check: re-run the full validator suite against the last 30 days
of `financials` rows. Alert if the re-run BLOCK count differs from the
live BLOCK count by more than 10% (indicates drift in `SanityContext`
lookups such as `latest_quarterly_revenue`).

## 7. Performance

- Target: 0.5 ms per row, dominated by the two context lookups
  (`prior_period_row`, `latest_quarterly_revenue`).
- A full 3,000-ticker x 20-year backfill is ~60,000 rows, giving
  ~30 seconds of added overhead. Acceptable for a weekly job.
- Optimisation path if needed: batch-load context once per ticker at the
  start of that ticker's backfill and pass it to every row, instead of
  one lookup per row.
- The module must not issue any per-row network calls. All context comes
  from the same DB connection the writer already holds.

## 8. Rollout plan

**Phase 1 — WARN-only (2 weeks).** Every rule ships at WARN severity
regardless of the spec above. Rows continue to be written. Collect two
weeks of `data_quality_events` and review the top-firing rules weekly.

**Phase 2 — Selective BLOCK.** Promote the rules that produced <0.1%
false-positive rate during Phase 1 to BLOCK severity. Expected promotions
based on the spec: `RULE_REVENUE_YOY_SANITY`, `RULE_ONED_DETECTION`,
`RULE_PAT_LT_REVENUE_ABS`, `RULE_TOTAL_ASSETS_POSITIVE`,
`RULE_NULL_CORE_FIELDS`, `RULE_UNIT_DETECTION_REVENUE`. Noisy rules
(sector plausibility, equity consistency, FCF identity) stay WARN.

**Phase 3 — Full enforcement.** Any BLOCK-severity violation during a
backfill automatically files a GitHub issue (via the existing `gh`
workflow) tagged `data-quality` with the violation payload attached.

## 9. Open design questions

These require a human decision before Phase 2:

1. **Growth-stock allowlist source.** How is `KNOWN_GROWTH_ALLOWLIST`
   maintained? Options: (a) market-cap based (auto-include any ticker
   under 5y old and in the top market-cap quintile of its sector),
   (b) sector-tagged, (c) manual YAML curated quarterly. Each has
   different maintenance cost and failure mode.
2. **WARN alerting channel.** Where do WARN-severity events surface?
   GitHub issue per event is too noisy. Options: daily digest issue,
   Slack webhook with dedupe, Prometheus Alertmanager rule with
   grouping. Preference depends on who owns the rotation.
3. **Partial-backfill policy.** If >10% of rows in a single backfill run
   BLOCK, should the job abort entirely or continue and surface the
   partial-state warning? Aborting protects the table; continuing
   preserves the good rows and avoids re-running a 12-hour job.
4. **Retro-cleanup of the existing 2,710 bad rows.** Once the validator
   is live, do we hard-delete the existing bad rows, soft-mark them
   `is_invalid=true`, or leave them and rely on the re-backfill to
   overwrite? Affects how `/financials` queries must filter.
5. **Holding-company flag source.** `RULE_PAT_LT_REVENUE_ABS` depends on
   a holding-company allowlist. Where does that list come from, and who
   maintains it?
