# DCF Terminal Growth + WACC Audit
Branch: `audit/dcf-terminal-growth-wacc-recalibration`
Date: 2026-04-27 (audit task #1 of 4)

## 1. Where the parameters live

| Parameter | File | Line | Current value |
|---|---|---|---|
| Global default WACC | `utils/config.py` | 15 | `DISCOUNT_RATE = 0.10` (10%) |
| Global default terminal growth | `utils/config.py` | 16 | `TERMINAL_GROWTH_RATE = 0.025` (2.5%) |
| Hard cap on terminal growth in engine | `screener/dcf_engine.py` | 27 | `MAX_TERMINAL_GROWTH = 0.04` (4%) |
| Floor on WACC in engine | `screener/dcf_engine.py` | 26 | `MIN_DISCOUNT_RATE = 0.07` (7%) |
| India terminal growth default | `config/countries.py` | 44 | `default_terminal_growth = 0.04` (4%) |
| India equity-risk-premium (UI/screener annotation) | `config/countries.py` | 43 | `equity_risk_premium = 0.08` |
| **CAPM market-risk-premium actually used in compute_wacc** | `models/forecaster.py` | 476 | `DEFAULT_MRP = 0.060` (India) — **inconsistent with country file's 8%** |
| India CAPM Re floor | `models/forecaster.py` | 531 | `re_floor = 0.09` |
| India CAPM WACC floor | `models/forecaster.py` | 573 | `wacc_floor = 0.09` |
| Beta clamp | `models/forecaster.py` | 511 | `np.clip(_raw_beta, 0.5, 3.0)` |
| Mean-reversion long-run growth (India) | `models/forecaster.py` | 400 | `LONG_RUN_TARGET = 0.10` (10%) |
| Mean-reversion blend | `models/forecaster.py` | 402 | `0.60 × actual + 0.40 × 10%` |
| Floor on projected growth (any +FCF co.) | `models/forecaster.py` | 408 | `LONG_RUN_TARGET × 0.5 = 5%` |
| Max FCF growth cap | `models/forecaster.py` | 33 | `MAX_FCF_GROWTH = 0.35` (35%) |
| Fade rate | `models/forecaster.py` | 36 | `FADE_K = 0.25` (slow) |
| Forecast horizon | analysis service | 494 | `forecast_yrs = 10` |
| Industry-WACC sector defaults | `models/industry_wacc.py` | 41+ | per-sector |
| `get_industry_wacc()` blend | `models/industry_wacc.py` | 1291 | `0.40 × CAPM + 0.60 × industry` |

## 2. Two valuation paths — they use DIFFERENT WACC sources

The DCF parameters are NOT the same in the two paths the product exposes:

| Path | WACC source | Terminal growth source |
|---|---|---|
| Backend `analysis_service.compute_analysis` (single-stock /api/v1/analyze) | `compute_wacc(raw, is_indian, enriched)` → CAPM-derived; floor 9% | `country.default_terminal_growth = 4%` |
| Buffett screener `stock_screener.analyse_ticker` | `get_industry_wacc()` → blends CAPM 40% + industry 60% | `INDUSTRY_WACC[sector]['terminal_growth']` (2.5–4%) |

The screener (where the seven outliers were spotted) goes through the **second** path. So for the seven names:

## 3. Sector classification + parameters for the 7 outliers

| Ticker | Detected sector | Industry `wacc_default` | Terminal `g` | wacc_min/max | Notes |
|---|---|---|---|---|---|
| TCS.NS | `it_services` | 11.0% | 3.5% | 10.0–12.0% | Keyword `"tcs"` |
| JUSTDIAL.NS | `it_services` | 11.0% | 3.5% | 10.0–12.0% | Keyword `"justdial"` |
| EMAMILTD.NS | `fmcg` | 10.0% | 4.0% | 9.0–11.0% | Keyword `"emamiltd"` |
| NATCOPHARM.NS | `pharma` | 11.5% | 3.5% | 10.0–13.0% | Keyword `"natco"` |
| SANOFI.NS | `pharma` | 11.5% | 3.5% | 10.0–13.0% | Keyword `"sanofi"` |
| ZYDUSLIFE.NS | `pharma` | 11.5% | 3.5% | 10.0–13.0% | Keyword `"zyduslife"` |
| MAYURUNIQ.NS | `general` (no kw match) | 11.5% | 3.0% | 10.0–13.0% | falls through to "general" |

(Final WACC after blending CAPM-40 / Industry-60 then ±50bps RF adj. For Indian RF currently ~7%, the +50bps "tight conditions" adjustment likely fires on every ticker, giving final WACC ~11.5–12.0%.)

## 4. Quick sensitivity — terminal multiplier `(1 + g) / (WACC − g)`

| Scenario | g | WACC | Terminal multiple | Δ vs current |
|---|---|---|---|---|
| Current (TCS path) | 3.5% | 11.0% | 13.80× | baseline |
| Current (FMCG path) | 4.0% | 10.0% | 17.33× | +25% |
| Current (pharma path) | 3.5% | 11.5% | 12.94× | -6% |
| Sanity (uniform) | 5.0% | 13.0% | 13.13× | -5% |
| Conservative (uniform) | 4.0% | 13.0% | 11.56× | -16% |
| Aggressive (uniform) | 5.0% | 12.0% | 15.00× | +9% |

**Surprise finding:** **terminal-stage parameters are NOT the dominant lever** for the 44% TCS inflation. Moving WACC from 11% → 13% with g=4% only knocks ~16% off the terminal multiple. To produce a 44% over-FV, the inflation must come predominantly from the **PV of years 1–10 FCFs** (driven by `fcf_base` + `growth_schedule`), not the terminal tail.

## 5. Decomposition of likely contribution to MoS inflation

Approximate (sensitivity per unit of FV, not exact ticker recompute):

| Driver | Estimated contribution | Lever |
|---|---|---|
| `fcf_base` over-statement (NOPAT proxy on a peak-margin TTM) | 30–60% | `_compute_fcf_base` selects max-of-candidates with NOPAT floor |
| `predict_growth_rate` mean-reverting to 10% with floor 5% over 10 years | 20–40% | `_rule_based_growth` + `FADE_K=0.25` |
| Industry WACC ~150bp too low for India large-caps | 10–20% | `INDUSTRY_WACC` defaults |
| Terminal `g` (3–4%) — already at/under India long-run real GDP | 0–5% | `MAX_TERMINAL_GROWTH=0.04` |

The biggest cohort effect is therefore **margin reversion + fcf_base**, which is exactly what the `wip/forecaster-margin-reversion-needs-canary` branch addresses (audit task #3). The terminal-growth + WACC lever (this branch) is a smaller, second-order corrective.

## 6. Recommended recalibration (this branch, smallest possible diff)

Two changes only — both via config constants, no formula edits:

### 6a. Tighten India industry WACC defaults by 50 bps where they sit below realistic Indian large-cap COE

Currently `it_services.wacc_default = 11.0%`, `fmcg.wacc_default = 10.0%`, `pharma.wacc_default = 11.5%`. Realistic Indian COE for a beta-1 large-cap is `Rf 7% + 1.0 × ERP 7% = 14%`. WACC after debt weighting ~12.5–13%. We bump industry defaults conservatively (50 bps), which is well within the existing wacc_max ceiling and avoids a step-change:

| Sector | Old default | New default | Old ceiling | (No change to ceiling) |
|---|---|---|---|---|
| `it_services` | 11.0% | 11.5% | 12.0% | |
| `fmcg` | 10.0% | 10.5% | 11.0% | |
| `pharma` | 11.5% | 12.0% | 13.0% | |
| `consumer_durable` | 11.0% | 11.5% | 12.0% | |
| `general` | 11.5% | 12.0% | 13.0% | |

### 6b. Lower `LONG_RUN_TARGET` for mean-reversion from 10% → 8%

`forecaster.py:400` mean-reverts year-1 growth to 10% (India nominal GDP minus a small discount). With FADE_K=0.25, year-10 growth still sits well above the 4% terminal — the model reverts 60/40 toward 10%, not toward terminal. Lowering this anchor to **8%** (closer to consensus India earnings-growth-through-cycle) brings 10-year compound projections meaningfully closer to fundamentals without touching the cap-or-floor logic. The 50%-of-long-run floor (`5% → 4%`) is a beneficial side-effect.

### What we are NOT changing in this branch
- `MAX_TERMINAL_GROWTH` (already 4% — fine)
- `MIN_DISCOUNT_RATE` (7% — only matters as a floor)
- `compute_wacc` CAPM Re/wacc floors
- `MAX_FCF_GROWTH` cap, `FADE_K`, `BLEND_WEIGHTS`
- The `LONG_RUN_TARGET × 0.5` growth floor logic (overlaps with margin-reversion branch — defer)

## 7. Sequencing notes vs sibling WIP branches

- `wip/forecaster-margin-reversion-needs-canary` (audit task #3) — addresses one-off-margin spikes via mean-reverting margin. **Overlaps with this branch's 6b** (both touch `models/forecaster.py` and both reduce projection-period growth). Sequence:
  1. Land this branch first (config-only, smallest diff).
  2. Run 7-night canary.
  3. Merge margin-reversion branch on top — re-canary.
  4. Either may obviate the other; check 7-day MoS distribution after each.

- `wip/score-model-confidence-deduction-needs-canary` (audit task #4) — independent (touches confidence scoring, not FV), no sequencing concern.

## 8. Pre-change canary snapshot
`scripts/snapshots/snapshot_20260428_013802_33e11c61d2cc.json` (50 stocks, captured on clean main before any edits).
