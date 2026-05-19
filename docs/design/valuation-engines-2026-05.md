# YieldIQ Valuation Engines — May 2026 Architecture

**Last refreshed: 2026-05-19**, after the 6-day sprint that landed
24 PRs and reduced benchmark-reconciliation outliers from 312 → ~75.

This document is the single source of truth for the YieldIQ
valuation pipeline. If anything below is wrong, *fix this file* —
don't let the code and docs diverge.

---

## Pipeline overview

```
                            ┌─────────────────────┐
                            │  ticker, financials │
                            └──────────┬──────────┘
                                       │
                          ┌────────────▼─────────────┐
                          │  Sector classifier      │
                          │  (constants.py +        │
                          │   TICKER_SECTOR_OVERRIDES│
                          │   + is_bank_like        │
                          │   + is_realty_developer │
                          │   + is_regulated_utility│
                          │   + is_reit)            │
                          └────────────┬─────────────┘
                                       │
            ┌──────────────────────────┼──────────────────────────┐
            │                          │                           │
       Tier-1 dedicated           Tier-1 financial            Generic DCF
       sector engines               cohort engine               (default)
            │                          │                           │
   ┌────────┼─────────┐            ┌───┼───┐                       │
   │        │         │            │       │                       │
 rate_   appraisal   realty       PSU    Private                Tier 2
 base    value      pb_plus      banks   banks (incl.           cohort
 (utili-  (life     land_bank   p_bv_   stressed sub)            │
  ties)  insurance) (DLF,        peer    pharma generic-cap     │
                    Lodha etc.)         everything else         │
                                                                 │
                                                          ┌──────▼──────┐
                                                          │ DCF collapse│
                                                          │ safety net  │
                                                          └──────┬──────┘
                                                                 │
                                              ┌──────────────────┼──────────────────┐
                                              │                  │                  │
                                       Tier 2 cohort       Platform P/S        Story DCF
                                       (P/E peer median)   (Damodaran)         (narrative)
                                              │                  │                  │
                                              └──────────────────┴──────────────────┘
                                                                 │
                                                          data_limited
                                                          (verdict gate)
```

## Engine catalogue

### Layer A: reconciliation gate (always-on)
- `benchmark_reconciliation_service.py` — daily 10am IST job that compares
  `analysis_cache.payload->valuation->fair_value` to `consensus_estimates.target_median`.
  Flags any ticker where `|delta| > 30%` (or adaptive threshold by analyst-count
  band). Surfaces on `/admin/outliers`.

### Layer B: confidence verdict gate (per-request)
- `confidence_service._apply_confidence_verdict_gate` — caps verdicts to
  `under_review` when `data_quality / model_confidence / valuation_stability`
  composite is below threshold OR when FV/CMP ratio is extreme.
- Wired in `analysis/service.py` before `ValuationOutput` construction.

### Layer C: Tier-1 dedicated sector engines

| Engine | Sectors | File |
|---|---|---|
| `compute_regulated_utility_fair_value` | POWERGRID/NTPC/PFC/RECLTD/GAIL (3 sub-types: transmission_utility, regulated_nbfc, gas_transmission, regulated_other) | `regulated_utility_valuation_service.py` |
| `compute_appraisal_fair_value` | Life insurers (LICI/HDFCLIFE/SBILIFE/ICICIPRULI) | `insurance_appraisal_service.py` |
| `compute_realty_fair_value` | Realty developers (DLF/Lodha/Oberoi/Godrej/Phoenix/Prestige/Sobha/Brigade) — requires `realty_land_bank_inputs` row | `realty_valuation_service.py` |
| `compute_financial_fair_value` | Banks/NBFCs/HFCs/Insurance — 11 peer groups (see below) | `financial_valuation_service.py` |
| Generic DCF | Everything else | `models/forecaster.py` + `models/dcf_engine.py` |

### Layer C.1: financial peer groups
| Group | Members | Method | Fallback (P/B, ROE) |
|---|---|---|---|
| `psu_banks` | SBIN, BANKBARODA, PNB, CANBK, UNIONBANK, INDIANB, BANKINDIA, IOB, CENTRALBK, UCOBANK, MAHABANK, IDBI | p_bv_peer | (0.9, 0.14) |
| `private_banks` | HDFCBANK, ICICIBANK, KOTAKBANK, AXISBANK, FEDERALBNK | p_bv_peer | (2.0, 0.13) |
| `stressed_private_banks` | YESBANK, RBLBANK, BANDHANBNK, IDFCFIRSTB, INDUSINDBK | p_bv_peer, asymmetric clamp (0.85, 1.0) | (1.25, 0.05) |
| `lending_nbfc` | BAJFINANCE, BAJAJFINSV, CHOLAFIN, MUTHOOTFIN, MANAPPURAM, M&MFIN, SHRIRAMFIN, ... | p_bv_peer | (4.0, 0.20) |
| `govt_nbfc` | PFC, REC, RECLTD, IRFC, HUDCO | p_bv_peer | (1.2, 0.18) |
| `traditional_hfc` | LICHSGFIN, PNBHOUSING | p_bv_peer, asymmetric clamp (0.95, 1.0) | (1.0, 0.13) |
| `premium_hfc` | AAVAS, HOMEFIRST, CANFINHOME | p_bv_peer | (2.2, 0.17) |
| `life_insurance` | LICI, HDFCLIFE, SBILIFE, ICICIPRULI | p_ev_peer (Appraisal) | (2.0, 0.14) |
| `psu_gi` | NIACL, GICRE | p_bv_peer | (1.05, 0.08) |
| `private_gi` | ICICIGI, GODIGIT | p_bv_peer | (5.5, 0.15) |
| `health_insurance` | STARHEALTH, NIVABUPA | p_bv_peer | (3.5, 0.08) |
| `asset_mgmt` | HDFCAMC, ICICIAMC, NIPPONLIFE, UTIAMC | p_e_peer | (8.0, 0.25) |

### Layer D: DCF-collapse safety net
- `dcf_collapse_safety_net.attempt_tier2_fallback` — fires when FV/CMP ratio outside
  `[0.30, 3.5]` (widened from `[0.10, 5.0]` on Day-4) OR when FV ≤ 0.
- Three-rung rescue chain:
  1. **Tier 2 cohort** (`tier2_cohort_valuation_service`) — peer-median P/E with
     quality buckets (premium/core/tail). Min 3 peers.
  2. **Platform P/S** (`platform_valuation_service`) — peer-median P/Sales for
     internet platforms and fintech brokers. Min 3 peers with valid P/S.
  3. **Story DCF** (`story_dcf_engine`) — Damodaran narrative + numbers using
     per-industry defaults + per-ticker overrides in `config/story_dcf_overrides.json`.
- If all three return None, caller marks `data_limited` and the verdict gate
  suppresses display.

### Layer E: cyclical handling
- `is_cyclical(ticker, sector)` detects steel/oil/metals/cement
- `_query_normalized_fcf(ticker, years=N)` smooths FCF over N years
- **Peak-phase detection (Day-5/Day-6)**: if 3y FCF mean is > 1.35× the 5y mean,
  use 5y. If > 1.50× the 10y mean, use 10y (catches multi-year supercycles like
  VEDL FY20-FY25).
- `cyclical_trough_anchor` — pins FV to 0.95× CMP when DCF FV < 0.2× CMP for
  CYCLICAL_TICKERS

### Layer F: pharma sub-bucketing (Day-5/Day-6)
- 15 generic-exporter tickers (`_PHARMA_GENERIC_TICKERS` in `models/forecaster.py`)
  get a tighter WACC floor (0.105 vs default 0.09) and lower terminal-g cap
  (0.035 vs default 0.04). Franchise pharma (SUNPHARMA, CIPLA, MANKIND, BIOCON,
  ABBOTINDIA, GLAXO, PFIZER, SANOFI, ERIS, AJANTPHARM, DIVISLAB) revert to
  default CAPM.

---

## Operator-curated inputs (3 tables)

| Table | Engine | Status |
|---|---|---|
| `insurance_appraisal_inputs` | Life insurance Appraisal Value | 4 of 4 populated; HDFCLIFE verified, others APPROXIMATE |
| `realty_land_bank_inputs` | Realty developers PB + land bank | 8 of 14 populated; DLF verified, others APPROXIMATE |
| `config/story_dcf_overrides.json` | Story DCF per-ticker assumptions | 10 platforms populated; APPROXIMATE — operator review pending |

All `APPROXIMATE` rows have an explicit note in their `entered_by` /
`notes` field flagging operator verification needed.

---

## Verdict-gate confidence tiers

| Engine | Confidence cap | Why |
|---|---:|---|
| Tier 1 sector engines (rate_base, appraisal, etc.) | 80-90 | Dedicated math, anchored to operator data |
| Generic DCF | 70-90 | Multi-year FCF data |
| Tier 2 cohort (P/E) | 75 | Peer-relative, depends on peer cohort quality |
| Platform P/S | 65 | Less stable than P/E |
| Story DCF | 50 | Narrative-driven, operator-curated assumptions |
| `data_limited` | n/a (verdict suppressed) | All rescues failed; user sees "under review" |

---

## Test coverage

| File | Tests | Last updated |
|---|---:|---|
| `test_financial_valuation.py` | 22 | Day 5 (PR #392) |
| `test_tier2_cohort.py` | 21 | Day 2 (PR #380) |
| `test_tier2_peer_lookup.py` | 7 | Day 3 (PR #389) |
| `test_platform_valuation.py` | 12 | Day 4 (PR #390) |
| `test_story_dcf_engine.py` | 12 | Day 6 (PR #395) |
| `test_regulated_utility_dcf.py` | 26 | Day 4 (PR #390) |
| `test_benchmark_reconciliation.py` | 22 | Day 2 (PR #383) |
| `test_dcf_nbfc_wacc_floor.py` | 7 | Day 1 (PR #373) |
| `test_pharma_dcf_fix.py` | 14 | (legacy) |

**Total: 143 backend tests passing** as of 2026-05-19.

---

## Discipline rules (from CLAUDE.md)

1. **Canary diff before merging** PRs that touch `backend/services/` or
   `backend/routers/`. `python scripts/canary_diff.py` must exit 0.
2. **No CACHE_VERSION bump without snapshot.** Run `snapshot_50_stocks.py`
   before, `canary_diff.py --diff-against latest` after. Explain any FV
   change > 15%.
3. **Never declare a fix "fixed" on a single Chrome MCP test.** Need 7
   consecutive clean nightly canary runs.

---

## Next-engineer onboarding (5-minute version)

1. Read this doc.
2. Open `backend/services/analysis/service.py` and search for `is_financial`,
   `is_realty_branch_active`, `is_regulated_utility_ticker`, `is_etf_ticker`,
   `is_reit_ticker` — those are the Tier-1 routing branches.
3. Open `backend/services/dcf_collapse_safety_net.py` for the three-rung rescue.
4. Open `screener/sector_relative.py` for the 33 peer cohorts that power Tier 2.
5. When debugging a specific ticker, query `analysis_cache.payload` and check
   `valuation.valuation_engine_used` + `valuation._meta` — they tell you which
   engine actually fired and with what parameters.
