# Units canonical reference

**Status:** Authoritative as of 2026-04-27. Owner: backend/data team.

This document is the single source of truth for "which API field is in
which unit" and where each value is transformed across the YieldIQ
pipeline. It exists because the codebase grew up with multiple
heuristic-based normalisers (`_normalize_pct`, `_normalize_pct_to_decimal`,
`_convert_row_to_inr`) and at least one of them shipped a silent
double-conversion bug (PR #126, 2026-04-26 — window `±5` → `±1`)
that corrupted ROE/ROCE/ROA for ~100 stocks for two weeks.

If you add a new monetary or ratio field, **document it here in the
same PR**.

---

## 1. Unit-detection helpers

| File | Function | Window / rule | Direction |
| --- | --- | --- | --- |
| `backend/services/analysis/utils.py` | `_normalize_pct` | `|v| < 1` ⇒ decimal; else percent | → percent |
| `backend/services/analytical_notes.py` | `_normalize_pct` | `|v| < 1.5` ⇒ decimal; else percent | → percent |
| `data/collector.py` | `_normalize_pct_to_decimal` | three-band: `<= 0.20` decimal, `0.20 < v <= 1.0` percent-decimal-form, `> 1.0` percent | → decimal |
| `backend/services/analysis/db.py` | `_convert_row_to_inr` | raw_inr if `> 1e10` (₹1,000 Cr) | idempotency guard |
| `backend/validators/ground_truth.py` | `_resolve(market_cap_cr)` | divide raw INR by `1e7` | → crore |
| `backend/services/units.py` (new) | `to_percent`, `to_decimal`, `to_inr_crore` | hint-first, heuristic-fallback | both |

All five sites are covered by `tests/test_unit_normalization_comprehensive.py`.

---

## 2. Field-by-field unit map

The table below covers every metric that crosses a unit boundary in the
pipeline. Columns:

* **Source** — where the raw value enters the system.
* **Source unit** — the unit at the boundary.
* **Transform** — function/file that converts to canonical form.
* **Canonical** — what the field looks like after transform.
* **Persisted** — what the DB column stores.
* **Served** — what the public API returns.

### Profitability ratios

| Field | Source | Source unit | Transform | Canonical | Persisted | Served |
| --- | --- | --- | --- | --- | --- | --- |
| `roe` | yfinance `info.returnOnEquity` | decimal (0.235) | `analysis/utils._normalize_pct` | percent (23.5) | `companies.roe_ttm` (percent) | percent |
| `roe` | Aiven XBRL `ratios.roe` | percent (23.5) | `analysis/utils._normalize_pct` (idempotent) | percent | percent | percent |
| `roce` | computed `EBIT / (TA − CL)` | decimal | `analysis/service.py::_compute_roce` × 100 | percent | percent | percent |
| `roa` | yfinance `info.returnOnAssets` | decimal | `analysis/utils._normalize_pct` | percent | percent | percent |

**Discipline:** In any service that consumes these values, use
`backend.services.units.assert_percent(value, name="roe")` to log a
warning if the upstream layer accidentally hands you a decimal.

### Capital structure & liquidity

| Field | Source | Source unit | Canonical | Persisted | Served |
| --- | --- | --- | --- | --- | --- |
| `de_ratio` | yfinance `info.debtToEquity` (often percent, e.g. 45 = 0.45) **or** Aiven (decimal) | dimensionless ratio | `decimal` ratio (0.45) | ratio | ratio |
| `current_ratio` | Aiven `current_assets / current_liabilities` | dimensionless | ratio (1.5) | ratio | ratio |
| `wacc` | computed in `analysis/service.py` | decimal (0.12) | decimal | not persisted | percent (UI) |
| `mos` | computed `(fair_value − price) / fair_value` | decimal (0.25) | decimal | not persisted | percent (UI) |

**Note:** `de_ratio` from yfinance is **percent-multiplied-by-100**
(yfinance returns `45.0` to mean `0.45`). Some pipelines divide by 100;
audit before re-using.

### Growth

| Field | Source | Source unit | Canonical | Persisted | Served |
| --- | --- | --- | --- | --- | --- |
| `revenue_cagr` (3y/5y) | computed in `data/collector.py` | decimal | decimal at ingest, percent on serve | decimal | percent |
| `eps_growth_3y` | yfinance | decimal | decimal | decimal | percent |

### Market & valuation

| Field | Source | Source unit | Canonical | Persisted | Served |
| --- | --- | --- | --- | --- | --- |
| `market_cap` | yfinance `info.marketCap` | raw INR | `to_inr_crore` (heuristic) | `companies.market_cap_cr` (Crore) | Crore |
| `market_cap_cr` | Aiven materialised | Crore | passthrough | Crore | Crore |
| `shares_outstanding` | yfinance | raw count | divide by 1e5 in some paths | `companies.shares_lakh` (lakh) **or** raw count depending on source — see `local_data_service.py:338` | both forms exist |
| `pe_ratio` | yfinance / computed | dimensionless | ratio | ratio | ratio |
| `pb_ratio` | yfinance / computed | dimensionless | ratio | ratio | ratio |
| `ev_ebitda` | computed `(market_cap_cr + debt_cr − cash_cr) / ebitda_cr` | dimensionless | ratio | not persisted | ratio |

### Financial-statement values

| Field | Source | Source unit | Canonical | Persisted | Served |
| --- | --- | --- | --- | --- | --- |
| `revenue`, `pat`, `fcf` (Financials table) | XBRL ingestion | raw INR for USD-tagged rows; otherwise Crore | `_convert_row_to_inr` (idempotency-guarded; `> 1e10` ⇒ raw_inr) | Crore (post-conversion) | Crore |

---

## 3. Guard recipes

Use the central canonicaliser at every boundary:

```python
from backend.services import units as U

# at ingestion — caller knows the source contract
roe_pct = U.to_percent(yf_info.get("returnOnEquity"), hint="decimal", name="roe")
roe_pct = U.to_percent(aiven_row.roe,                   hint="percent", name="roe")

# at consumption — defensive assertion, never raises
U.assert_percent(enriched["roe"], name="roe")

# at conversion — idempotent
mcap_cr = U.to_inr_crore(yf_info.get("marketCap"))  # heuristic OK

# mark a dict as normalised so downstream can detect double-convert
U.mark_normalised(enriched, "roe")
if U.is_normalised(enriched, "roe"):
    ...  # skip a second pass
```

---

## 4. Boundary-warning policy

`backend.services.units.to_percent` and `to_decimal` log a `WARNING`
when the input falls within `PCT_BOUNDARY_BAND = 0.05` of the
decimal/percent threshold (`PCT_DECIMAL_BOUND = 1.0`). These are the
values most likely to flip class when the threshold changes — exactly
the failure mode that produced the GRASIM bug.

In production, route this logger to your observability stack and alert
on a sustained spike of `boundary` warnings — that almost certainly
means an upstream feed switched units.

---

## 5. Migration plan (informational)

This file documents the **target state**. Existing callers of
`_normalize_pct` and `_normalize_pct_to_decimal` are not yet migrated.
Migration is intentionally deferred so the central module can ship
behind the canary diff without changing FV/screener output. Migration
order, when scheduled:

1. New code: must use `backend.services.units` directly.
2. `analytical_notes._normalize_pct` → `units.to_percent` (caller-side
   threshold differs; needs a `hint` audit).
3. `analysis/utils._normalize_pct` → `units.to_percent` (drop-in,
   parity test guarantees no canary delta).
4. `data/collector._normalize_pct_to_decimal` → `units.to_decimal`
   (three-band heuristic needs a custom path; not yet supported by
   `units` — this is the only known case).

Each step lands as its own PR with a canary-diff run.
