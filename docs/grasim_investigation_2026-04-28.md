# GRASIM.NS public-sweep flag investigation — 2026-04-28

## TL;DR

`scripts/public_sweep_check.py` flagged GRASIM.NS with three anomalies:
- `SCEN_ORDER`: bear=base=589.16 (collapsed scenario fan)
- `ROE_OUTLIER`: 380.03%
- `ROCE_OUTLIER`: 350.0%

**Root cause (ROE/ROCE):** real bug in
`backend/services/analysis/utils.py::_normalize_pct`. Its heuristic
treats any value with `|v| < 5` as a yfinance-style decimal and
multiplies by 100. But the financials parquet stores ROE/ROCE/ROA
already in **percent units** (matches the contract documented at
`backend/services/analysis/db.py:561` — `"roe": float | None  # percent`).

GRASIM's real ROE is **2.35%** (PAT 3,705 Cr / Equity 157,812 Cr,
parquet FY2025 row stores `roe = 2.348149`). The heuristic
mis-classifies 2.35 as a decimal and emits 234.81% — exactly the
local payload value. The 380.03% in the prod cache is the same bug
applied to a stale TTM blend.

**Bear-case collapse:** downstream consequence, not an independent bug.
Once the upstream confidence/MoS gate puts GRASIM into
`verdict=data_limited` (low confidence + extreme MoS), prod's older
DCF cache produced FV=589.16 with the bear scenario clamped to base.
Fresh local recompute returns a healthy FV=3,105 with bear=481, base=3,105,
bull=3,398 — i.e. the symptom resolves once the code path actually re-runs
DCF. So the "scenario collapse" symptom would clear on the next
CACHE_VERSION bump even without a code change. The ROE/ROCE bug would not.

**Diagnosis bucket: (a) real bug, code fix.** But shipping it without
following the discipline rules in `CLAUDE.md` would be unsafe: it
changes ROE/ROCE for every low-return stock in the universe and shifts
quality scoring downstream. It needs the coordinated CACHE_VERSION-bump
+ golden rebaseline workflow, not a one-shot PR.

## Phase 1 — verification

### 1. Prod symptom (confirmed)

```
$ curl -sS https://api.yieldiq.in/api/v1/public/stock-summary/GRASIM.NS
{
  "ticker":"GRASIM.NS","fair_value":589.16,"current_price":2700.0,
  "mos":-78.2,"verdict":"data_limited","score":20,"grade":"D",
  "bear_case":589.16,"base_case":589.16,"bull_case":1783.33,
  "wacc":0.098,"confidence":11,"roe":380.03,"de_ratio":0.0,
  "roce":350.0,"debt_ebitda":9.8,"interest_coverage":4.9,
  "current_ratio":0.87,"asset_turnover":0.27,
  "revenue_cagr_3y":0.0569,"revenue_cagr_5y":0.1247,
  "ev_ebitda":19.41,"market_cap":1830909433500.0,
  "last_updated":"2026-04-28T05:27:48.655447"
}
```

Headers: `x-source: analysis_cache_v35`, `x-cache: HIT, MISS`.

### 2. Local backend `/api/v1/analysis/GRASIM.NS` (with `AUTO_REFRESH_PARQUETS=0`, `YIELDIQ_DEV_MODE=true`)

Key fields:

- `valuation.fair_value = 3105.0` (NOT 589.16)
- `valuation.bear_case = 481.33`, `base_case = 3105.0`, `bull_case = 3398.37` — bear/base no longer equal
- `valuation.verdict = "fairly_valued"`, `dcf_reliable = true`
- `quality.roe = 234.81` (still wrong — same root cause)
- `quality.roce = 350.0` (still wrong — same root cause)
- `quality.de_ratio = 0.0` (parquet `debt_to_equity` is NULL → defaults to 0; data gap, not a code bug)
- `data_issues`:
  - `[warning] roe_pct=234.81 outside bounds [-100, 200]`
  - `[warning] roce_pct=350 outside bounds [-100, 200]`
- `computation_inputs.pat_ttm = 0.0`, `ebit_ttm = 0.0` (both NULL in parquet for FY2025)

So the prod cache is stale (carries the old `iv=589.16`) AND has the
ROE/ROCE bug; the live code path produces a sane FV but still has the
ROE/ROCE bug.

### 3. Source data — `data/parquet/financials.parquet`

```
ticker  period_end       roe       roa  net_margin  total_equity     pat
GRASIM  2025-03-31  2.348149  0.740343    2.517817     157812.83  3705.68
GRASIM  2024-03-31  4.048190  1.363384    4.340588     138938.38  5624.49
GRASIM  2023-03-31  5.554555  2.024661    5.861987     122912.82  6827.26
GRASIM  2022-03-31  6.498643  2.608816    7.981690     116174.71  7549.78
```

PAT/Equity in raw rupees crore: `3705.68 / 157812.83 = 0.02348 = 2.35%`.
The parquet's `roe = 2.348149` already encodes percent. The `2.51%` net
margin matches the API's `red_flag thin_margins` (Net margin: 2.7%).
This is a real-world Grasim Industries number — heavy capex into VSF +
paints + cement, low net return on equity right now. **Not a data
bug, not a demerger.**

Cross-check across other tickers in same parquet:

```
ticker      roe       (real-world)
TCS         50.69     ~50%   ✓ percent
INFY        28.06     ~28%   ✓ percent
ITC         49.36     ~49%   ✓ percent
HINDUNILVR  21.47     ~21%   ✓ percent
RELIANCE    6.90      ~7%    ✓ percent
ULTRACEMCO  8.17      ~8%    ✓ percent
TATASTEEL   3.74      ~4%    ✓ percent
GRASIM      2.35      ~2%    ✓ percent
```

Every value is in percent. The parquet column convention is unambiguous.

### 4. Real-world sanity

Grasim Industries (Aditya Birla Group, BSE 500300 / NSE GRASIM):
diversified into VSF (viscose staple fibre), chemicals, cement
(via Ultratech holding), paints (Birla Opus capex push). FY25 PAT was
suppressed by the paints capex ramp-up. Real ROE in the low single
digits is consistent with public reporting and Screener.in / TIKR
data. **YieldIQ's 234%-380% display is wrong by a factor of ~100x.**

## Phase 2 — root cause

`backend/services/analysis/utils.py:197-222`:

```python
def _normalize_pct(val) -> float | None:
    """Normalize a percentage-ish value to always be in PERCENTAGE form
    (23.5 for 23.5%).
    ...
    Rule: if |val| < 5 we treat it as decimal (since real ROE/ROCE > 5%
    wouldn't be expressed as a tiny decimal), else already percentage.
    """
    ...
    if -5.0 < v < 5.0:
        return round(v * 100, 2)
    return round(v, 2)
```

The 5.0 threshold is too aggressive. yfinance returns ROE as a decimal
in `[-1.0, 1.0]` (e.g. 0.235 for 23.5%). Real percent-units values like
2.35% (Grasim), 3.74% (TataSteel FY25), 4.05% (Grasim FY24), and any
loss-making period in `(-5%, 0%)` get falsely re-scaled by 100x.

Call sites:
- `backend/services/analysis/service.py:1695` — applied to `enriched["roe"]` (sourced from `local_data_service` reading parquet `roe` column → already percent)
- `backend/services/analysis/service.py:1697` — applied to `_roce_val` (already percent from `compute_roce` or `EBIT/TA × 100` fallback)
- `backend/services/analytical_notes.py:165` — same usage in narrative path

Same bug affects ROCE: GRASIM's local path returns `_roce_val` from the
EBIT/TA fallback at `service.py:1310` (`EBIT/TA × 100`). With FY24 EBIT
inferred from EBITDA ~20,344 Cr and TA 412,539 Cr: `4.93%` → re-scaled
by `_normalize_pct` to ~493%, but it sees 4.93 (>5? no, <5 if treated
loosely with rounding). Actual prod path math depends on whether
`compute_roce` returned a value or fell through; the surface symptom is
350.0, which is `_normalize_pct(3.5) = 350.0`. There's a `>100`
clamp inside `compute_roce` that returns None — but the surface 350 is
exactly `3.5 × 100`, indicating `_normalize_pct` is mis-scaling a 3.5%
ROCE that came through the fallback.

## Phase 3 — proposed fix (NOT shipped)

### Minimal change

`backend/services/analysis/utils.py`, line 220:

```python
# was:
if -5.0 < v < 5.0:
    return round(v * 100, 2)
# becomes:
if -1.0 < v < 1.0:
    return round(v * 100, 2)
```

Justification: yfinance decimals are bounded by `[-1, 1]` (a 100% ROE
encoded as 1.0 is the practical max, and real-world ROE >= 100% is
exceptional). Real-percent values >= 1% (the lowest plausible
percent-units value that would appear) fall outside this window and
pass through untouched. The `compute_roe_fallback` in the same file
already produces percent (NI/E × 100), so this is consistent.

### Why I am NOT shipping this in this session

`CLAUDE.md` lays down three rules. This change touches all three:

1. **"Never ship a data fix without running canary-diff first."**
   I cannot run a meaningful canary against this fix. Canary hits a
   live API; my locally-edited code only takes effect in a fresh
   recompute, but `analysis_cache` returns the old payload until
   `CACHE_VERSION` bumps. A `run_canary_local.ps1 -Mode gates` run
   against the unchanged prod or unbumped local cache would not
   exercise the fix.

2. **"Never bump CACHE_VERSION without a before/after snapshot."**
   This fix WILL change `q.roe` and `q.roce` for any stock with real
   percent-units ROE in `(-1, 1)` — including PSU / commodity / capex-
   cycle names where 0.5%-0.9% ROE windows are common in down years.
   Some of those values currently render as 50%-90% (clearly wrong)
   and would correctly drop to 0.5%-0.9%. That's a directionally-correct
   shift but a real value change that flows into:
   - `quality.fundamental_score` and `quality.grade`
   - `quality.yieldiq_score`
   - moat/quality narrative phrasing (`analytical_notes`)
   - red-flags structured items (`thin_margins` etc. are independent,
     but other rules read `roe`)
   - `ai_summary` text
   So this is a CACHE_VERSION-bump-class change. It needs:
   `python scripts/snapshot_50_stocks.py` BEFORE,
   `python scripts/canary_diff.py --diff-against latest` AFTER,
   and any FV change >15% on the canary 50 explained in the PR.

3. **"Never declare a bug 'fixed' based on a single Chrome MCP test."**
   I have a single `curl` reproduction. Per rule 3, "fixed" requires
   canary 5/5 + 7 nightly runs + reproducible from snapshotted inputs.
   Out of scope for one investigation session.

### Estimated blast radius

Stocks in the canary 50 with real ROE plausibly in the affected window
(`(-1%, 1%)` range, mostly from down years or loss-making periods),
based on canary_bounds:
- TATASTEEL (bound `[0.0, 0.3]` — FY24 was loss-making at -4.8%, FY25 at 3.7%)
- TATAMOTORS, BPCL, IOC, JSWSTEEL, ONGC, ULTRACEMCO, BHARTIARTL,
  HINDALCO, ICICIPRULI, TECHM, GRASIM, TATACONSUM, SHREECEM —
  all have lower bound below 0.10. Most actual values are 5-30%
  (above the heuristic), but cyclical down years can dip below 1%.

GRASIM today is the canonical case. Most of the canary 50 have real
ROE >= 5% so are not affected.

NOTE: the canary file's own `_meta` claims ROE bounds are decimals
(`"roe": "Return on equity (decimal, e.g. 0.20 = 20%)"`), but
`gate4_canary_bounds` does a direct `lo <= v <= hi` against the API
field which is in percent. So the canary's gate-4 ROE check is currently
a no-op false-positive surface — also worth a follow-up issue,
separate from this fix.

## Recommended follow-up

1. Open a PR titled
   `fix(ratios): tighten _normalize_pct decimal threshold to 1.0`
   that:
   - changes the `-5.0 < v < 5.0` window to `-1.0 < v < 1.0`
   - bumps `CACHE_VERSION` in `backend/services/cache_service.py`
   - includes before/after `snapshot_50_stocks.py` artifacts
   - explains every >15% FV shift on the canary 50
   - rebaselines `scripts/dcf_golden.json` after CI green
2. Open a separate issue: `canary_stocks_50.json` ROE bounds are in
   decimal form per `_meta`, but `gate4_canary_bounds` compares to the
   API's percent-form value. Either rescale in the harness or update
   the bounds file. (Not blocking GRASIM, but a latent gate hole.)
3. After the fix lands and one CACHE_VERSION cycle clears, prod
   `/public/stock-summary/GRASIM.NS` should return ROE ~2.35,
   ROCE ~3.5, FV in the 2,800-3,200 band, and a non-collapsed scenario
   fan. The current SCEN_ORDER flag will resolve once the prod cache
   recomputes (it's already healthy on the live code path locally).

## Files referenced

- `backend/services/analysis/utils.py` (the fix lives here, line 220)
- `backend/services/analysis/service.py:1695-1697` (call sites)
- `backend/services/analysis/db.py:561` (contract: `roe` is percent)
- `backend/services/local_data_service.py:204` (reads parquet `roe`)
- `data/parquet/financials.parquet` (source of truth for percent-units storage)
- `scripts/canary_stocks_50.json` (the units-mismatch sub-issue)
- `CLAUDE.md` (the discipline rules that gate the actual ship)

## What I deliberately did NOT do

- Did NOT add GRASIM to `config/ticker_aliases.yaml`. There is no
  corporate action here — Grasim Industries is the listed parent of
  the Aditya Birla Group, no demerger has been announced, no
  successor symbols. Aliasing it would mask a code bug behind a
  data-config flag, which is exactly the wrong fix.
- Did NOT touch `data/parquet/*.parquet`. The parquet files are
  correct; the consumer code is wrong.
- Did NOT bump `CACHE_VERSION` or rebaseline `dcf_golden.json`.
  Those belong in the dedicated PR with snapshots, per CLAUDE.md.
- Did NOT push a code change. Per the discipline rules, this needs
  human review of the snapshot diff before it ships.
