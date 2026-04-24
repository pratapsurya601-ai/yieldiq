# HEX Axis Source Map — Phase 2 Scoring Audit

**Date:** 2026-04-24
**Status:** Read-only investigation
**Scope:** Trace every HEX axis's compute path end-to-end so a fresh engineer
can identify the table/column/function each axis depends on.

**Why this document exists:** Today's audit (2026-04-24) revealed catastrophic
HEX scores for Nifty blue-chips:

| Ticker      | Overall | Grade |
|-------------|---------|-------|
| HDFCBANK    | 17      | D     |
| ASIANPAINT  | 20      | D     |
| BAJFINANCE  | 22      | D     |
| RELIANCE    | 25      | D     |
| ICICIBANK   | 27      | D     |

Only 4 of Nifty top-30 score above 60. Data-layer patches today (currency
tags, revenue rows, OneD/FourD parser) did not move the needle. Therefore the
bug likely lives in the scoring axes themselves. This map is the input to the
Phase 2 fix.

## Table of Contents

1. [Pulse axis](#1-pulse-axis--axis_pulse)
2. [Quality axis](#2-quality-axis--axis_quality)
3. [Moat axis](#3-moat-axis--axis_moat)
4. [Safety axis](#4-safety-axis--axis_safety)
5. [Growth axis](#5-growth-axis--axis_growth)
6. [Value axis](#6-value-axis--axis_value)
7. [Summary — table dependency matrix](#7-summary--table-dependency-matrix)
8. [Sector classification audit](#8-sector-classification-audit)
9. [Top-5 suspected bugs](#9-top-5-suspected-bugs)
10. [Data the auditor should pull next](#10-data-the-auditor-should-pull-next)

---

## Core infrastructure (common to all axes)

### The HEX data envelope

All six axes read from a single `data` dict built by
`_fetch_core_data()` at `backend/services/hex_service.py:240-363`.
That dict has four top-level keys:

| Key            | Populated by                                          | Source table / column                                                                                                              |
|----------------|-------------------------------------------------------|------------------------------------------------------------------------------------------------------------------------------------|
| `analysis`     | `analysis_cache.payload` JSON                         | `analysis_cache` table (writer: `backend/services/analysis/service.py`, the AnalysisResponse serialiser around lines 1590-1700)    |
| `metrics`      | `market_metrics` row                                  | `market_metrics` table — cols `pe_ratio`, `pb_ratio`, `ev_ebitda`, `market_cap_cr`, `trade_date` (ORDER BY `trade_date` DESC)       |
| `financials`   | last ~6y of annuals                                   | `financials` table — cols `period_end`, `revenue`, `free_cash_flow`, `operating_margin`, `eps_diluted`, `debt_to_equity`            |
| `sector`       | `stocks.sector`                                       | `stocks` table, `sector` column                                                                                                    |

### Ticker suffix discipline

- `market_metrics` is queried using `ticker` (canonical, normally `.NS`-suffixed) **then** `bare` (suffix-stripped) (line 286).
- `financials` is queried using `bare` ONLY (line 333).
- `stocks` is queried using `bare` ONLY (line 354).

This asymmetry is a **known footgun**: if upstream writers are inconsistent
about suffix, one table may have data under `BPCL` while another has it
under `BPCL.NS`, silently starving the axis of signal.

### Null handling convention

Every axis function defines its own "must have at least one of these inputs
or return `_neutral_axis` (score=5.0, data_limited=True)" gate. See each
axis section below for the specific gate.

`_clamp()` (line 171-178) is used everywhere to cast to float and protect
against NaN/inf — but when the cast fails it quietly returns 5.0, which can
mask unit-mismatch bugs (decimal "0.15" for ROE may look benign instead of
being 15%).

---

## 1. Pulse axis — `_axis_pulse`

### A. Code location
- **File:** `backend/services/hex_service.py`
- **Lines:** 1118-1200
- **Sector branches:** None. Signature is `_axis_pulse(ticker: str)` — does
  NOT take `data` and does NOT branch on sector.

### B. Input sources

| data dict path                           | upstream writer                                            | DB source                                                             | Unit                    | On NULL                                  |
|------------------------------------------|------------------------------------------------------------|-----------------------------------------------------------------------|-------------------------|------------------------------------------|
| `hex_pulse_inputs.estimate_revision_30d` | `backend/services/pulse_data_service.py` (Agent D / `backend/scripts/pulse_daily.py`) | table `hex_pulse_inputs` col `estimate_revision_30d`                  | decimal −1..+1          | skipped; each signal independent         |
| `hex_pulse_inputs.insider_net_30d`       | same                                                       | table `hex_pulse_inputs` col `insider_net_30d`                        | score ±3                | skipped                                  |
| `hex_pulse_inputs.promoter_delta_qoq`    | same (reads `shareholding_pattern`)                        | table `hex_pulse_inputs` col `promoter_delta_qoq`                     | decimal; ×2 internally  | skipped                                  |
| `hex_pulse_inputs.pledged_pct_delta`     | same                                                       | table `hex_pulse_inputs` col `pledged_pct_delta`                      | decimal, sign-negative  | skipped                                  |
| yfinance `recommendations_summary`       | runtime `yfinance.Ticker(ticker)` fallback                 | yfinance.com (external)                                               | count buckets           | returns neutral 5.0, `data_limited=True` |

### C. Scoring formula

```python
if pulse_inputs_row:
    raw = 0
    raw += clip(est_rev * 5, -5, 5)
    raw += clip(insider_net_30d, -3, 3)
    raw += clip(promoter_delta_qoq * 2, -2, 2)
    raw -= clip(pledged_pct_delta, -2, 2)
    score = 5.0 + raw * 0.5         # range ~[-5, +5] -> [2.5, 7.5]
else:
    # yfinance fallback
    net = (2*SB + B - S - 2*SS) / total
    score = 5.0 + net * 4.0         # range [1.0, 9.0]
else:
    return neutral(5.0, data_limited=True)
```

### D. Known failure modes

1. **`hex_pulse_inputs` row missing** (common, likely universal until
   pulse agent runs nightly). Falls through to yfinance path.
2. **yfinance call blocked / rate-limited / returns empty DataFrame** —
   returns neutral 5.0 `data_limited=True`. Observed behaviour for many
   stocks that show an "n/a" pulse tile.
3. **Ticker normalisation inconsistency**: `_axis_pulse(ticker)` is called
   with the `.NS`-suffixed form (from `compute_hex` line 1336), but
   `hex_pulse_inputs.ticker` is PRIMARY KEY TEXT; we do not know how the
   writer stores it. Worth confirming.
4. **yfinance `recommendations_summary` in India**: Indian tickers often
   return empty or None. In practice the fallback is dead for most names,
   so Pulse defaults to neutral 5.0 (`data_limited=True`) for the majority
   of tickers.

### E. Observed bad data

- Pulse on BPCL was **6.9** (screenshot), which suggests real yfinance data
  came through for that ticker. On the Nifty-30 blue-chips the pulse axis
  would similarly fluctuate around 5–7 depending on analyst sentiment. On
  its own Pulse has weight 0.10 — cannot drag a composite from 60 to 20.
- **Low confidence** that Pulse is a material contributor to the 17/25
  collapse. Suspect axes are Value, Growth, Moat, Safety — not Pulse.

---

## 2. Quality axis — `_axis_quality`

### A. Code location
- **File:** `backend/services/hex_service.py`
- **Lines:** 537-651
- **Sector branches:**
  - `sector == "bank"` (line 553) — uses ROA + ROE + Cost-to-Income,
    explicitly de-emphasises Piotroski.
  - default (general + IT) — Piotroski + ROCE (or ROE fallback) + op-margin stability.

### B. Input sources

| data dict path                                   | upstream writer                                                                                       | DB source                                                                                                 | Unit           | On NULL                                                                       |
|--------------------------------------------------|-------------------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------------|----------------|-------------------------------------------------------------------------------|
| `analysis.quality.piotroski_score`               | `service.py:1639` <- `compute_piotroski_fscore(enriched)` in `screener/piotroski.py`                  | derived from `financials` rows + enriched yfinance info                                                   | 0..9 integer   | skipped; if also ROCE/ROE missing -> neutral 5.0                              |
| `analysis.quality.roce`                          | `service.py:1653` <- `_normalize_pct(_roce_val)` from `ratios_service.compute_roce(ebit, ta, cl)`     | `financials`: EBIT, total_assets, current_liabilities (plus `_cl_db` fallback)                             | percent 12.3   | falls back to ROE                                                             |
| `analysis.quality.roe`                           | `service.py:1651` <- `_normalize_pct(enriched.roe or _compute_roe_fallback(enriched))`                | primary: yfinance `info.returnOnEquity` (decimal); fallback: `financials.pat / financials.total_equity`   | percent 24.5  | if ROCE also None -> score stays at 5.0 baseline                              |
| `analysis.quality.roa`                           | `service.py:1670` <- `_bm.get("roa")` from `_fetch_bank_metrics_inputs`                               | `financials.roa` (bank-only pre-computation path)                                                          | percent 1.2   | bank path: if ROA & ROE both None -> neutral 5.0                              |
| `analysis.quality.cost_to_income`                | `service.py:1671` <- `_compute_c2i(operating_expenses, net_income)`                                   | derived from `financials` (bank-specific)                                                                  | percent 55     | skipped                                                                       |
| `data.financials[*].op_margin`                   | `_fetch_core_data` lines 328-344                                                                      | `financials.operating_margin`                                                                              | percent        | margin_stability = None; doesn't block axis when ROCE/ROE present            |

### C. Scoring formula

Bank branch:
```python
score = 5.0
score += clip((ROA  - 1.0) * 2.5, -2.0, 3.0)     # 1.0% ROA = neutral
score += clip((ROE  - 12.0) * 0.25, -2.0, 2.5)   # 12% ROE = neutral
score += clip((55.0 - C2I) * 0.05, -1.2, 0.8)    # c/i anchor 55%
```

General branch:
```python
score = 5.0
score += (Piotroski - 4.5) * 0.6                 # 9/9 -> +2.7
primary = ROCE if not None else ROE
score += (primary - 15.0) * 0.12                 # 15% = neutral; 25% -> +1.2
if op_margin_stdev over ≥3 yrs:
    score += clip((5.0 - stdev) * 0.1, -1.0, 1.0)
```

### D. Known failure modes

1. **ROE unit mismatch**. `enriched["roe"]` from yfinance is a DECIMAL
   (0.245). `_normalize_pct` (see `service.py` helper) converts to
   percent. If a code path bypasses `_normalize_pct` (e.g. `_compute_roe_fallback`),
   the axis will read 0.245 and compute `(0.245-15)*0.12 = -1.77`,
   collapsing Quality. **Worth auditing.**
2. **ROCE currency-unit contamination** — `ratios_service.compute_roce`
   comment specifically notes EBIT/TA/CL must be in the same unit; if
   `enriched.total_assets` is in raw INR and `_cl_db` is in Crores, ratio
   is nonsense, and `_sanitize_cagr`-style clamp does NOT apply here.
   ROCE is exposed directly.
3. **Piotroski misreported as 0** when any underlying series is missing.
   Piotroski treats missing data pessimistically, so a thinly-covered
   large-cap can score 2-3/9 purely from data gaps.
4. **Bank mis-classification** — a bank treated as "general" gets Piotroski
   + ROCE logic. ROCE is None for banks (no capital-employed in the
   EBIT/TA-CL sense), so the axis collapses to Piotroski-only + baseline
   5.0.

### E. Observed bad data

- BPCL (general) showed Quality **6.1** — plausible.
- For HDFCBANK (sector=bank): if ROA/ROE are None in `analysis_cache.payload`
  (check next), this axis returns `_neutral_axis("No bank quality data")` -> 5.0,
  contributing ~1.0 to the composite — insufficient to save the score.
- For RELIANCE / ASIANPAINT (general): low Piotroski OR a decimal-ROE
  unit bug would push Quality to 3–4 and contribute to the collapse.

---

## 3. Moat axis — `_axis_moat`

### A. Code location
- **File:** `backend/services/hex_service.py`
- **Lines:** 794-929
- **Sector branches:**
  - `sector == "bank"` (line 812) — uses mcap scale + cost-to-income.
    Traditional Wide/Narrow/None grade is ignored because analysis returns
    "N/A (Financial)".
  - default — Moat grade (text) + numeric `moat_score` fallback + op-margin
    stability.

### B. Input sources

| data dict path                           | upstream writer                                                  | DB source                                                                              | Unit            | On NULL                                                                |
|------------------------------------------|------------------------------------------------------------------|----------------------------------------------------------------------------------------|-----------------|------------------------------------------------------------------------|
| `analysis.quality.moat`                  | `service.py:1643` <- `moat_result.get("grade")` from `screener/moat_engine.compute_moat_score` | derived: ROE/ROCE/gross_margin/revenue_growth from `financials` + `enriched`          | "Wide"/"Narrow"/"Moderate"/"None"/"N/A (Financial)" | falls back to `moat_score`   |
| `analysis.quality.moat_score`            | `service.py:1644` <- `moat_result.get("score")`                 | same engine                                                                             | 0..100          | skipped; if also no op-margin history -> neutral 5.0                   |
| `data.metrics.market_cap_cr`             | `_fetch_core_data` line 301                                      | `market_metrics.market_cap_cr`                                                          | INR Crores      | bank branch: if also no c2i -> neutral 5.0                             |
| `analysis.quality.cost_to_income`        | `service.py:1671`                                                | derived                                                                                 | percent         | skipped                                                                |
| `data.financials[*].op_margin`           | `_fetch_core_data` line 340                                      | `financials.operating_margin`                                                           | percent         | margin_signal=False; if no moat label -> neutral 5.0                   |

### C. Scoring formula

Bank branch:
```python
score = 5.0 + clip(log10(mcap_cr / 50000) * 2.0, -3.0, 3.5)   # 50k Cr = neutral
score += clip((50.0 - C2I) * 0.04, -0.8, 0.8)
```

General branch:
```python
score = 5.0
if moat_grade: score += {Wide: +3, Moderate: +2, Narrow: +1.5, None: -1.5}
elif moat_score is not None:
    if ms >= 75: +3
    elif ms >= 60: +2
    elif ms >= 40: +1.5
    else: -1.0
if ≥3y op_margins:
    score += clip((5.0 - stdev) * 0.15, -0.5, 1.0)
```

### D. Known failure modes

1. **`analysis_cache.payload.quality.moat` is "N/A (Financial)"** for non-bank
   stocks. The string match at line 849 only catches "wide"/"moderate"/
   "narrow"/"none"/"no moat" substrings, so "n/a" falls through — then
   `moat_score` fallback kicks in. If `moat_score == 0`, the `else
   score -= 1.0` branch is reached (line 896) when `ms_f > 0.0` — but for
   `ms_f == 0.0` no branch matches so **no signal is recorded**, and if
   margin history is also absent -> neutral 5.0.
2. **Bank without `market_cap_cr`** (ticker-suffix mismatch between `market_metrics`
   writer & reader) returns neutral 5.0 for moat. HDFCBANK was observed
   earlier to have `market_metrics` under bare form only — the dual-probe
   at line 286 should handle that, but only if ticker≠bare. Worth checking
   whether HDFCBANK still lands as neutral.
3. **Op-margin stability as a fallback "moat"** is a weak proxy. A commodity
   stock with steady 4% margins looks like a moat; a growth compounder
   with expanding margins looks like no moat.
4. **Stale moat grade** in `analysis_cache.payload`. If the payload was
   computed before the Moderate band was introduced, a modern blue-chip
   may still be tagged "None".

### E. Observed bad data

- BPCL: Moat **3.5** — expected; BPCL is a commodity refiner with a narrow
  moat.
- RELIANCE: the analysis cache likely carries `moat == "Moderate"`
  (allowlist). If it has been invalidated to "None" via a stale write, Moat
  would drop from 7.0 to 3.5. Worth verifying.
- HDFCBANK: If `market_cap_cr` is NULL or `sector != "bank"` in classifier,
  Moat collapses to 5.0 neutral. Given the observed 17 composite, Moat is
  likely at ~5.0 for banks.

---

## 4. Safety axis — `_axis_safety`

### A. Code location
- **File:** `backend/services/hex_service.py`
- **Lines:** 932-1115
- **Sector branches:**
  - `sector == "bank"` (line 956) — prefers GNPA / NNPA / Tier-1; falls
    back to P/BV franchise proxy.
  - `sector == "it"` (line 1038) — D/E + op-margin stability.
  - default — D/E + Interest coverage + Altman Z.

### B. Input sources

| data dict path                                     | upstream writer                                     | DB source                                                                                      | Unit        | On NULL                                                                |
|----------------------------------------------------|-----------------------------------------------------|------------------------------------------------------------------------------------------------|-------------|------------------------------------------------------------------------|
| `analysis.quality.de_ratio` / `debt_to_equity`     | `service.py:1652` (or derive from total_debt/equity at 1471-1475) | yfinance `info.debtToEquity` (or `financials.total_debt / total_equity`)                      | ratio 1.2  | general: if also ic & altman None -> neutral 5.0                       |
| `analysis.quality.interest_coverage`               | `service.py:1656` <- `compute_interest_coverage(ebit, interest_expense)` | `financials.ebit / financials.interest_expense`                                                | ratio ×    | skipped                                                                |
| `analysis.quality.altman_z`                        | `service.py` (via quality pipeline; compute location not inspected) | derived from `financials` + market_metrics                                                     | unitless    | skipped                                                                |
| `analysis.quality.gnpa_pct` / `nnpa_pct` / `tier1_ratio` | **NOT CURRENTLY POPULATED** (comment line 959-962 confirms) | planned sources: BSE XBRL filings / RBI Form A                                              | percent     | bank path falls back to P/BV proxy                                     |
| `data.metrics.pb_ratio`                            | `_fetch_core_data` line 302                         | `market_metrics.pb_ratio`                                                                      | ratio ×    | bank fallback: if None -> neutral 5.0                                  |

### C. Scoring formula

Bank branch (ideal path):
```python
score = 5.0
score += clip((tier1 - 12) * 0.5, -2.5, 2.5)
score += clip((4 - gnpa) * 0.4, -2.5, 1.5)
score += clip((1.5 - nnpa) * 0.7, -2.0, 1.0)
```

Bank fallback (what actually runs):
```python
if pb is None: return neutral
score = 5.0 + clip((pb - 1.5) * 0.8, -2.0, 2.5)
```

IT branch:
```python
score = 5.0
score += clip((0.3 - DE) * 4.0, -1.0, 2.5)   # OR +1.5 if DE is None
score += clip((4.0 - margin_stdev) * 0.25, -1.0, 1.5)
```

General:
```python
score = 5.0
score += clip((1.0 - DE) * 2.0, -3.0, 2.5)
score += clip((IC - 4.0) * 0.25, -2.0, 2.0)
score += clip((Z - 2.4) * 0.8, -2.0, 2.0)
```

### D. Known failure modes

1. **Bank Safety is a documented blind spot.** Lines 1016-1023 log INFO
   "bank Safety inputs missing... using generic formula" — meaning
   HDFCBANK/ICICIBANK/SBIN etc. score Safety purely from P/BV. That formula
   rewards *expensive* banks and punishes *cheap* ones. At the current
   HDFCBANK P/BV ~2.8, Safety = 5 + min(2.5, (2.8-1.5)*0.8) = 5 + 1.04 =
   **6.04**. But for a PSU bank at P/BV 1.1, Safety = 5 + (1.1-1.5)*0.8 =
   **4.68**. This **inverts** credit risk — SBIN looks weaker than RBLBANK.
2. **NBFCs are routed into bank Safety branch** via `_NBFC_TICKERS` (line
   44-48). BAJFINANCE, MUTHOOTFIN etc. have D/E that a generic formula
   would interpret correctly, but the bank branch takes over and uses P/BV
   instead. A high-quality NBFC at P/BV 5+ would hit the clip ceiling at
   +2.5, giving Safety ~7.5 — but BAJFINANCE composite is 22. Suggests
   Safety isn't the single culprit for BAJFINANCE; Growth/Value are.
3. **`debt_to_equity` unit swap.** yfinance returns D/E as percent (e.g.
   45.0 means 0.45). If that raw number reaches the axis unmodified, the
   `(1.0 - 45.0)*2.0 = -88` -> clipped to -3.0 path collapses Safety to
   **2.0** for any yfinance-derived D/E. Line 1471-1475 derives D/E only
   when `enriched.get("debt_to_equity") is None` — so if yfinance provides
   45.0 it is **used as-is** without unit normalisation. **High-confidence
   bug.**
4. **Altman Z for banks is structurally nonsensical** but banks are routed
   to the bank branch before this matters.

### E. Observed bad data

- BPCL: Safety **5.5** — low D/E (~0.3), OK int coverage, plausible.
- HDFCBANK: bank branch with no GNPA/NNPA/Tier-1 plumbed -> P/BV proxy.
  HDFCBANK P/BV ~2.5 -> Safety ~5.8. Not the collapse source for HDFCBANK.
- RELIANCE / ASIANPAINT (general): if yfinance D/E comes through as 45
  instead of 0.45, Safety = 2.0. **Top-suspected Nifty-collapse contributor.**

---

## 5. Growth axis — `_axis_growth`

### A. Code location
- **File:** `backend/services/hex_service.py`
- **Lines:** 654-791
- **Sector branches:**
  - `sector == "bank"` (line 671) — Advances YoY + Deposits YoY + PAT YoY.
  - default — Revenue CAGR (3y preferred, 5y fallback) + EPS CAGR from financials.

### B. Input sources

| data dict path                              | upstream writer                                      | DB source                                                             | Unit         | On NULL                                                      |
|---------------------------------------------|------------------------------------------------------|-----------------------------------------------------------------------|--------------|--------------------------------------------------------------|
| `analysis.quality.revenue_cagr_3y` / `_5y`  | `service.py:1660-1661` <- `compute_revenue_cagr(rev_series, n)` | `financials.revenue` via `enriched.income_df`                        | DECIMAL 0.12 | bank: N/A. general: tries EPS CAGR next; both None -> neutral |
| `analysis.quality.advances_yoy`             | `service.py:1672` (line 1381 `_compute_yoy(total_assets[0], [1])` — PROXY) | `financials.total_assets` (last two annuals)                         | PERCENT 12.5 | skipped                                                      |
| `analysis.quality.deposits_yoy`             | `service.py:1673` (line 1387 `_compute_yoy(total_liab[0], [1])` — PROXY) | `financials.total_liab`                                              | PERCENT 12.5 | skipped                                                      |
| `analysis.quality.pat_yoy_bank`             | `service.py:1675`                                    | `financials.pat` YoY                                                  | PERCENT 12.5 | skipped                                                      |
| `data.financials[*].revenue`                | `_fetch_core_data` line 336                          | `financials.revenue`                                                  | INR (likely Cr) | fallback CAGR                                             |
| `data.financials[*].eps`                    | `_fetch_core_data` line 340                          | `financials.eps_diluted`                                              | INR per share | skipped                                                      |

### C. Scoring formula

Bank branch:
```python
avg = mean([adv_yoy, dep_yoy, pat_yoy])    # PERCENT inputs
score = 5.0 + avg * 0.10                   # 20% avg -> 7.0
```

General branch:
```python
# rev_cagr from analysis is DECIMAL; convert to PERCENT
rv = float(rev_cagr)
if -1.5 < rv < 1.5: rev_cagr = rv * 100  # decimal detected
# else already in percent

# eps_cagr computed locally in percent
score = 5.0
score += rev_cagr * 0.10       # 10% -> 5.5, 20% -> 6.5
score += eps_cagr  * 0.08
```

### D. Known failure modes

1. **`_sanitize_cagr` (service.py:1446-1454) clamps `|CAGR| > 50%` to None.**
   For a young or demerging company with real 80% CAGR, revenue_cagr lands
   at None in `analysis_cache.payload`. If the `_fetch_core_data`
   `financials` series is also absent (ticker-suffix mismatch!), Growth
   axis degrades to neutral 5.0. **Plausibly a contributor for RELIANCE**
   post-Jio/retail restructurings.
2. **Decimal/percent branch line 726.** The `-1.5 < rv < 1.5` guard is
   meant to distinguish decimal (0.12) from percent (12). But a real
   fast-grower with 120% CAGR would have `rv = 1.2` — the guard treats
   that as decimal and multiplies by 100 -> 120%. Then `120 * 0.10 = 12`
   is added -> score clipped at 10. Not a bug here, but fragile.
3. **Bank Growth depends on PROXY calculations.** `_compute_yoy(total_assets[0], [1])`
   is called "proxy: total_assets YoY" (line 1381). Actual "advances" is
   a sub-item of total assets; using total_assets overstates growth
   during periods of investment-portfolio shifts. Acceptable for a proxy
   but not precise.
4. **EPS CAGR direction.** Line 742: `old = eps_series[-1]` (DESC-ordered
   `financials`, so last=oldest). Looks correct.
5. **CAGR needs 4 annual rows for 3y CAGR.** `len(eps_series) >= 3`
   means 3 rows = 2 years of growth, not 3. Minor imprecision.
6. **Ticker-suffix-mismatch on `financials`** (line 333 uses `bare`). If
   a ticker is only present under `.NS` suffix in `financials`, `out["financials"]`
   is empty, `rev_cagr` fallback path dies, and Growth goes neutral.

### E. Observed bad data

- BPCL: Growth **6.6** — healthy.
- For HDFCBANK, Growth depends on `advances_yoy` / `deposits_yoy` /
  `pat_yoy_bank` being populated in `analysis_cache.payload`. If the cached
  payload predates the bank-metrics feature (feat/bank-prism-metrics
  2026-04-21), these fields are all None and bank Growth returns neutral
  5.0 for HDFCBANK/ICICIBANK.
- For general stocks: if `revenue_cagr_3y` is clamped to None by
  `_sanitize_cagr` AND the financials-table fallback (bare ticker) returns
  `[]`, Growth = neutral 5.0.

---

## 6. Value axis — `_axis_value`

### A. Code location
- **File:** `backend/services/hex_service.py`
- **Lines:** 409-535
- **Sector branches:**
  - `sector == "bank"` -> `_axis_value_bank` (line 479) — P/BV + MoS.
  - `sector == "it"` -> `_axis_value_it` (line 512) — revenue multiple, with
    fallback to general logic.
  - default -> `_axis_value_general` (line 409) — MoS + P/E via sigmoid.

### B. Input sources

| data dict path                              | upstream writer                                          | DB source                                                                     | Unit                  | On NULL                                                                       |
|---------------------------------------------|----------------------------------------------------------|-------------------------------------------------------------------------------|-----------------------|-------------------------------------------------------------------------------|
| `analysis.valuation.margin_of_safety`       | `service.py:1597` <- `round(mos_pct, 1)` from `(FV-CMP)/CMP*100`, line 729 | derived: DCFEngine + moat adjustment vs current_price                       | PERCENT (e.g. -35)    | computed from FV/price if both present; else None                            |
| `analysis.valuation.fair_value`             | `service.py:1595` <- `round(iv, 2)`                      | `DCFEngine` OR `compute_financial_fair_value` (P/B) OR growth valuation      | INR per share         | if price also missing -> MoS None                                             |
| `analysis.valuation.current_price`          | `service.py` — latest close from `price_history`         | `price_history` table                                                         | INR                   | MoS None                                                                      |
| `data.metrics.pe_ratio`                     | `_fetch_core_data` line 301                              | `market_metrics.pe_ratio`                                                     | ratio ×               | sigmoid uses MoS only                                                         |
| `data.metrics.pb_ratio`                     | line 302                                                  | `market_metrics.pb_ratio`                                                     | ratio ×               | bank fallback: if also MoS None -> neutral 5.0                                |
| `data.metrics.market_cap_cr`                | line 305                                                  | `market_metrics.market_cap_cr`                                                | INR Crores            | IT path falls back to general                                                 |
| `data.financials[0].revenue`                | line 336                                                  | `financials.revenue` latest                                                   | INR (likely Cr)       | IT path falls back to general                                                 |

### C. Scoring formula

General (sigmoid, FIX-PRISM-VALUE-SIGMOID 2026-04-22):
```python
signal = 0
if mos_pct:  signal += mos_pct                      # percent
if pe:       signal += clip((22 - PE) * 3.3, -13, 13)
score = 10 / (1 + exp(-0.08 * signal))
```
Calibration points:
- MoS −50% -> 0.18 ; MoS −33% -> 0.67 ; MoS 0% -> 5.00 ; MoS +33% -> 9.34.

Bank:
```python
score = 5.0 + clip((2.5 - PB) * 1.5, -2.5, 2.5) + 0.10 * MoS
```

IT:
```python
rev_multiple = mcap_cr / (revenue / 1e7)
score = 5.0 + (5.0 - rev_multiple) * 0.6
```

### D. Known failure modes

1. **Revenue unit in IT branch.** Line 526: `rev / 1e7` assumes `revenue`
   is in raw INR. But `_fetch_core_data` pulls from `financials.revenue`
   which is frequently stored in Crores (the rest of the system treats it
   that way — `market_cap_cr` is in Crores). If `revenue` is already in Cr
   and we divide by 1e7 again, `rev_multiple` becomes ridiculously tiny
   and the axis saturates to ~10.0. **High-confidence unit-mismatch bug.**
   (The calibration comment "IT cohort median EV/Rev ~4-5x" confirms author
   intent was to compute a normalised multiple, but the denominator math
   depends on revenue being in raw INR.)
2. **MoS cap asymmetry.** `margin_of_safety_display=min(mos_pct, 80)` at
   service.py:1598 — the display is capped at 80%, but the payload carries
   the uncapped `margin_of_safety`. The sigmoid handles extreme MoS well,
   but a naive reader of `analysis.valuation.margin_of_safety` may expect
   the capped number.
3. **NBFC routed to bank Value path.** `_NBFC_TICKERS` hits line 216.
   BAJFINANCE P/BV ~5.5 -> Value = 5 + clip((2.5-5.5)*1.5, -2.5, 2.5) =
   5 - 2.5 = **2.5**. Then MoS adds ~0.10 × (BAJFINANCE's MoS). If DCF
   thinks BAJFINANCE is −30% overvalued, Value = 2.5 - 3.0 = clamped to
   **0.0**. **This is the RELIANCE / BAJFINANCE collapse signature.**
4. **P/E=0 pathological.** `pe_adj = (22 - 0) * 3.3 = 72.6` -> clipped to
   +13pp. Not a bug in this direction but worth noting.
5. **Stale `margin_of_safety` from `analysis_cache`**. If a cached payload
   predates the post-FIX1 MoS convention, sign may be inverted.

### E. Observed bad data

- BPCL: Value **10.0** — near-certain MoS is very positive (deep value);
  sigmoid asymptotes at 9.97 for MoS +100%.
- RELIANCE=25: a Value of **0.0** (MoS ≈ −35%, clamped by sigmoid to 0.18)
  and all other axes near 4-5 produces composite in the 20s. **Matches.**
- BAJFINANCE=22 (NBFC): bank Value branch + rich P/BV + negative MoS
  produces Value 0.0–1.5. **Matches.**
- ASIANPAINT=20 (general, rich P/E): if MoS is deeply negative (true —
  ASIANPAINT trades at P/E 60+), Value collapses. General sigmoid helps
  (never exactly 0), but combined with poor Growth (revenue decline post-
  competition) produces the 20 composite.

---

## 7. Summary — table dependency matrix

### Tables × Axes

| Table                    | pulse | quality | moat | safety | growth | value |
|--------------------------|:-----:|:-------:|:----:|:------:|:------:|:-----:|
| `analysis_cache`         |       | ✔       | ✔    | ✔      | ✔      | ✔     |
| `market_metrics`         |       |         | ✔(bank) |  ✔(bank-fallback, IT) |   | ✔   |
| `financials`             |       | ✔ (stability) | ✔ (stability) | ✔ (IT stability) | ✔ (EPS CAGR + rev fallback) | ✔ (IT rev) |
| `stocks` (sector)        | —     | ✔ (branch) | ✔ (branch) | ✔ (branch) | ✔ (branch) | ✔ (branch) |
| `hex_pulse_inputs`       | ✔     |         |      |        |        |       |
| `price_history`          |       |         |      |        |        | ✔ (indirect via CMP) |
| `shareholding_pattern`   | ✔ (via pulse) |   |      |        |        |       |
| yfinance (runtime)       | ✔ (fallback) | ✔ (ROE raw) |   | ✔ (D/E raw) |   |       |
| `fair_value_history`     |       |         |      |        |        | ✔ (via MoS write-back) |

### Mixed-table footgun observations

- Quality and Safety both read D/E but from different paths (one via
  `analysis.quality.de_ratio`, one via its own lookup). Discrepancy risk.
- Moat (bank) and Value (bank) BOTH depend on `market_metrics` with the
  dual `(ticker, bare)` probe — but Moat (general) relies only on
  `analysis.quality.moat`. A writer-suffix bug on `market_metrics` thus
  silently disables Moat AND Value for banks simultaneously.
- `financials` is queried by `bare` everywhere downstream, but some
  older writers store `.NS`. Grep log: `hex: financials fetch failed` at
  INFO level in Railway logs would confirm.

---

## 8. Sector classification audit

### Classification source

- `_classify_sector(ticker_bare, sector_str)` at lines 213-227.
- Step 1: hand-maintained ticker sets `_BANK_TICKERS` (14 entries),
  `_NBFC_TICKERS` (12 entries), `_IT_TICKERS` (18 entries).
- Step 2: fallback to `stocks.sector` string match on "bank",
  "financial services", "nbfc", "lending" (any one triggers "bank") or
  "information technology", "technology", "software", "it services"
  (any triggers "it").

### Failure modes

1. **Ticker not in hand-maintained set, `stocks.sector` is NULL/wrong.**
   Any bank not in `_BANK_TICKERS` (e.g. IDFCFIRSTB is there but
   SURYODAY, CSBBANK, KARURVYSYA, DCBBANK, CUB are **not**) falls to
   "general" and gets D/E + Altman Z scoring that's meaningless for banks.
2. **`stocks.sector` overpowered by hand-maintained list.** If a ticker
   enters the IT list by mistake it cannot be overridden via DB. Example:
   `LICHOUSFIN` and `LICHSGFIN` are BOTH in `_NBFC_TICKERS` (line 46) —
   defensively redundant, but a sign of ad-hoc maintenance.
3. **Non-bank with "bank" in sector string.** E.g. a manufacturer with
   sector "Bank Equipment Manufacturing" falls into `bank`. Internal
   guard at line 222 uses substring — aggressive false-positive risk.
4. **`enrich_stocks_sector_yf.py`** (under `scripts/`) is the sole writer
   for `stocks.sector`. If that script hasn't run for a ticker, `sector`
   is NULL, and classifier depends entirely on the hand-maintained sets.

### Reliability assessment

For the Nifty-30, all banks and major IT names are in the hand-maintained
sets. Sector **misclassification is a low-probability contributor** to the
Nifty-30 score collapse. However:

- `ASIANPAINT` — falls to "general" (correct).
- `RELIANCE` — falls to "general" (correct in this codebase, though some
  would argue it's "oil & gas" deserving its own branch).
- `BAJFINANCE` — routed to "bank" as an NBFC. **Correct classification
  but wrong scoring** (NBFC's Value shouldn't be judged by P/BV against
  banking cohort of 2.5x).

**Conclusion:** sector classification is fine; it's the NBFC-treated-as-
bank-for-scoring logic that's broken (see Top-5 bug #2 below).

---

## 9. Top-5 suspected bugs

Priority-ordered best guesses for the Nifty-30 score collapse.

### Bug #1 — General-path D/E ingested as percent not ratio
**Axis:** Safety (general + IT branches).
**File/line:** `backend/services/hex_service.py:1086-1092`, consuming
`analysis.quality.de_ratio`, which comes from yfinance `info.debtToEquity`
via `service.py:1652`.
**Symptom:** yfinance returns D/E as PERCENT (45.0 = 45%, i.e. 0.45).
The axis treats it as a ratio (expects 0.45). Formula:
`clip((1 - 45.0)*2, -3.0, 2.5) = -3.0` -> Safety = **2.0** for any
yfinance-D/E name. Every Nifty mid-cap with real debt hits this.
**Confirm with:** RELIANCE, ASIANPAINT, any non-IT general stock —
check `analysis_cache.payload.quality.de_ratio` raw value and compare to
actual balance-sheet D/E. If raw value >5 on blue-chips it is in percent.
**Refute with:** NESTLE (near-zero debt — de_ratio near 0 either way
looks OK).

### Bug #2 — NBFC tickers forced through bank Value/Safety branch
**Axis:** Value + Safety (bank branch).
**File/line:** `hex_service.py:44` (`_NBFC_TICKERS`), dispatching at
line 1309-1310.
**Symptom:** NBFCs have P/BV 3–6x (structurally higher than banks because
capital turnover). Bank Value formula `(2.5 - PB) * 1.5` floors at −2.5,
giving Value 2.5. Combined with DCF MoS ≈ −30% (BAJFINANCE trades rich
to DCF): Value drops to 0. Safety falls back to P/BV proxy which rewards
expensive banks (wrong direction for NBFCs). Explains BAJFINANCE=22.
**Confirm with:** BAJFINANCE, CHOLAFIN, MUTHOOTFIN composites and raw
Value scores. Compare to SBIN (genuine bank at lower P/BV).
**Refute with:** SHRIRAMFIN if its P/BV is near 2 — then Value works OK.

### Bug #3 — Bank Safety uses P/BV as a credit-quality proxy (inverted)
**Axis:** Safety (bank branch fallback).
**File/line:** `hex_service.py:1025-1036` (the `if pb is None: neutral`
block). `gnpa_pct` / `nnpa_pct` / `tier1_ratio` are never populated.
**Symptom:** Richer P/BV -> higher Safety. HDFCBANK (P/BV 2.8) gets
Safety ~6.0; RBLBANK (P/BV 0.9) gets Safety ~4.5. This inverts credit
risk: RBLBANK has real NPA stress yet scores "safer". HDFCBANK's overall
isn't crushed by Safety; the real HDFCBANK=17 driver is likely bank
Growth returning neutral 5.0 (see Bug #4) AND bank Quality being thin
when ROA is missing.
**Confirm with:** Query `analysis_cache.payload.quality` for HDFCBANK
and check `roa`, `advances_yoy`, `deposits_yoy`, `pat_yoy_bank`,
`cost_to_income`. If any are None, the corresponding axis is running on
baseline 5.0 only.
**Refute with:** If `advances_yoy` etc. are populated and scores are still
collapsed, the bug is elsewhere.

### Bug #4 — Stale analysis_cache missing bank-metric fields
**Axis:** Growth + Quality (bank branch).
**File/line:** `hex_service.py:672-700` and `537-597`.
**Symptom:** The bank-metrics feature (`feat/bank-prism-metrics 2026-04-21`)
added `advances_yoy`, `deposits_yoy`, `pat_yoy_bank`, `roa`,
`cost_to_income`. Tickers with `analysis_cache.payload` written before
that feature will have all those fields = None. Bank Growth = neutral 5.0.
Bank Quality = neutral 5.0. Composite would drop significantly.
**Confirm with:** `SELECT ticker, payload->'quality'->>'advances_yoy' FROM
analysis_cache WHERE ticker IN ('HDFCBANK','ICICIBANK','SBIN','KOTAKBANK')`.
If any are NULL, stale cache is the root cause.
**Refute with:** All values present and still low -> bug lies in the
proxy formulas (total_assets/liabilities YoY is not a good advances/deposits
proxy in a quarter with heavy investment-book shifts).

### Bug #5 — Revenue CAGR `_sanitize_cagr` over-clamps legitimate growth
**Axis:** Growth (general branch).
**File/line:** `service.py:1446-1454`. Also `ratios_service.compute_revenue_cagr`
emits DECIMAL, and `_sanitize_cagr` strips `|v| > 0.50`.
**Symptom:** Real CAGR > 50% (post-demerger RELIANCE segments, or
mid-cap compounder) -> None in payload. If `_fetch_core_data`'s
`financials` fallback ALSO fails (e.g. ticker suffix mismatch — `financials`
uses `bare`, but some writers may have stored `.NS`), rev_cagr is None.
If eps_cagr also None (common — EPS is noisier) -> Growth = neutral 5.0.
**Confirm with:** Diff `len(financials)` for tickers like RELIANCE,
ADANIENT. If fewer than 3 annual rows, the fallback path never fires.
**Refute with:** Growth axis returns real score on same tickers -> clamp
isn't biting.

---

## 10. Data the auditor should pull next

Run these queries / API calls (read-only) to confirm or refute the top
bugs. All assume access to the Neon/Aiven production read replica.

### Query 1 — Confirm Bug #1 (D/E percent-vs-ratio)

```sql
SELECT
  ticker,
  payload->'quality'->>'de_ratio'          AS de_ratio,
  payload->'quality'->>'interest_coverage' AS ic,
  payload->'quality'->>'altman_z'          AS z
FROM analysis_cache
WHERE ticker IN ('RELIANCE.NS', 'ASIANPAINT.NS', 'HINDUNILVR.NS',
                 'ITC.NS', 'LT.NS', 'TITAN.NS');
```
**Refutes if** every de_ratio is < 3. **Confirms if** any are >5.

### Query 2 — Confirm Bug #4 (stale bank cache)

```sql
SELECT
  ticker,
  payload->'quality'->>'roa'             AS roa,
  payload->'quality'->>'advances_yoy'    AS adv,
  payload->'quality'->>'deposits_yoy'    AS dep,
  payload->'quality'->>'pat_yoy_bank'    AS pat,
  payload->'quality'->>'cost_to_income'  AS c2i,
  updated_at
FROM analysis_cache
WHERE ticker IN ('HDFCBANK.NS','ICICIBANK.NS','SBIN.NS','KOTAKBANK.NS','AXISBANK.NS');
```
**Confirms stale cache if** any of the bank-metrics fields are NULL on
tickers whose `updated_at` is before `2026-04-21`.

### Query 3 — Confirm Bug #2 (NBFC P/BV in bank formula)

```python
# Python snippet, backend shell:
from backend.services.hex_service import compute_hex
for t in ["BAJFINANCE.NS","CHOLAFIN.NS","MUTHOOTFIN.NS","SBIN.NS","HDFCBANK.NS"]:
    h = compute_hex(t)
    print(t, h["axes"]["value"]["score"], h["axes"]["value"]["why"],
          h["axes"]["safety"]["score"], h["axes"]["safety"]["why"])
```
**Confirms if** NBFCs show Value score < 3 with reason containing "P/BV 4.x"
or similar.

### Query 4 — Confirm Bug #5 (CAGR clamped + financials fallback empty)

```sql
SELECT
  ticker,
  payload->'quality'->>'revenue_cagr_3y' AS cagr3,
  payload->'quality'->>'revenue_cagr_5y' AS cagr5,
  (SELECT count(*) FROM financials f
    WHERE f.ticker = replace(replace(ac.ticker,'.NS',''),'.BO','')
      AND f.period_type='annual') AS annual_rows_bare
FROM analysis_cache ac
WHERE ticker IN ('RELIANCE.NS','ADANIENT.NS','BAJFINANCE.NS','ASIANPAINT.NS');
```
**Refutes if** all cagr3 values are populated AND annual_rows_bare >= 3.
**Confirms if** annual_rows_bare is 0 for a ticker whose `financials`
obviously exists under the `.NS` form — indicates suffix-writer bug.

### Query 5 — Confirm `market_metrics` suffix consistency

```sql
SELECT ticker, COUNT(*) AS rows, MAX(trade_date) AS latest
FROM market_metrics
WHERE ticker ILIKE 'HDFCBANK%' OR ticker ILIKE 'BAJFINANCE%'
   OR ticker ILIKE 'RELIANCE%' OR ticker ILIKE 'TCS%'
GROUP BY ticker
ORDER BY ticker;
```
**Informs Bug #3** — if only bare-ticker rows exist, the `(ticker, bare)`
dual-probe on line 286 resolves it. If only .NS rows exist, the bank
branch at line 286's ordering is fine. If NEITHER exists for a live
Nifty ticker, that's a separate pipeline bug.

---

## Closing notes

- **Nothing in this document has been executed against prod.** Every
  suspected bug is a read-of-the-code hypothesis.
- **Observability gap:** when an axis returns neutral 5.0 due to missing
  inputs, the `why` string says "No bank quality data" etc. — but no
  metric/log counter tracks how often this fires per-axis in production.
  Consider a lightweight `axis_data_limited_total{axis=...}` counter before
  Phase 2 fixes land, so we can measure improvement.
- **Every axis has at least one silent-neutral path** triggered by
  missing DB data. If the audit shows widespread 5.0 scores, the fix is
  likely upstream (data-pipeline coverage), not in the axis math.
- **Piotroski 0/9 is a plausible silent bug** not covered by the top-5:
  the `compute_piotroski_fscore` fallback when inputs are missing has
  not been traced in this audit. If Piotroski is consistently 2-3 on
  names that should score 7+, it would drag Quality ~1.5 points. Suggest
  adding a Piotroski spot-check to the SQL query list.
