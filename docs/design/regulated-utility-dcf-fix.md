# Regulated-Utility DCF Fix — Design

**Status:** Draft, awaiting implementation
**Author:** investigation agent (handoff)
**Trigger:** POWERGRID.NS FV ₹59.66 vs CMP ₹290.9 (-79.5% MoS, "overvalued"). Street consensus ₹280–320.
**Companion tickers blocked by the same defect:** NTPC, NHPC, PFC, RECLTD, GAIL, TORNTPOWER, ADANIENSOL/ADANITRANS, IRFC, IEX
**Cache version at time of report:** v102

---

## 1. Failure trace (POWERGRID.NS path)

DCF path entry: `backend/services/analysis/service.py` lines 700–990 (non-financial branch, L959+).

| Step | File:Line | Result for POWERGRID |
|------|-----------|----------------------|
| Sector detect | `models/industry_wacc.py:965` → `detect_sector()` | `regulated_utility` (ticker in `REGULATED_UTILITY_TICKERS`) — **fires correctly** |
| WACC | `models/industry_wacc.py:308` (`wacc_default: 0.09`) → `compute_wacc()` | `wacc ≈ 0.09` — **correct** |
| Terminal g | `service.py:744` `country.get("default_terminal_growth", 0.025)` then `config/countries.py:44` India = `0.04` | `terminal_g = 0.04` (NOT the sector value — country default is used; happens to match). DCF engine then caps at `MAX_TERMINAL_GROWTH = 0.04` (`screener/dcf_engine.py:27`). |
| FCF base | `models/forecaster.py:_compute_fcf_base` | **PROBLEM ZONE.** POWERGRID is not in `_CYCLICAL_SECTORS`, not super-cyclical, not inventory-heavy. Selection = `median(latest_fcf, nopat_proxy, max_recent_fcf)` with `nopat_floor = 0.60 × nopat`. POWERGRID's reported `latest_fcf` swings (capex-heavy years can drive CFO − CapEx near zero or negative); `max_recent_fcf` is positive but only a few thousand Cr in good years; `nopat_proxy` is suppressed by the regulated 15.5% ROE on a huge asset base then run through `fcf_conv_factor 0.50` (sector config L316) giving a small number. Median + 60% nopat floor lands at a base FCF that is far below true earning power. |
| Growth (`g`) | `forecaster._rule_based_growth` | Mcap > ₹50,000 Cr → `LONG_RUN_TARGET = 0.06`; revenue growth ~6% → blended ~6%. OK. |
| Project + fade | `forecaster.predict` (5y explicit + 5y fade) | 10y projected FCFs all small. |
| `terminal_norm` | `service.py:969` `mean(projected_fcfs[-3:])` | Small. |
| `EV` | `screener/dcf_engine.py:130` `terminal_value = norm × (1+g)/(r-g) = norm × 1.04/0.05` → 20.8× | TV ≈ 21× a small terminal FCF. |
| **Equity value** | `dcf_engine.py:379` `equity_value = EV − total_debt + total_cash` | **DECISIVE COLLAPSE.** POWERGRID `total_debt ≈ ₹120,000 Cr`, `total_cash ≈ ₹5,000 Cr`. EV is computed from a depressed FCF base; subtracting net debt of ~₹115,000 Cr leaves a small residual equity value. |
| FV/share | `equity_value / shares` (~9.3 B shares) | ≈ ₹59.66 |

**Root cause: the FCF→EV→Equity arithmetic is structurally wrong for regulated utilities.** It is not one bug; it is the model itself.

Two compounding effects:

1. **FCF understates economic earnings.** Regulated capex is the business — the asset base IS the value creator. CERC tariffs return 15.5% ROE on the regulated rate base. Subtracting growth capex from CFO and calling the remainder "free" cash flow erases the very investment that produces future regulated revenue. NOPAT × 0.50 conv-factor (sector config) compounds the understatement.
2. **Debt subtraction double-penalises.** Utilities fund the rate base with regulated debt at allowed cost. Regulators set tariffs to cover both debt service AND equity returns. Subtracting ₹120,000 Cr debt from a depressed FCF-derived EV treats the debt as if it were unfunded — but the rate base already pays it back via the tariff.

Net effect: FV ≈ (small EV) − (large debt) ≈ small residual ÷ shares ≈ ₹59.

## 2. Why generic DCF can never work for regulated utilities

Generic DCF assumes:
- FCF = cash available to capital providers after maintenance capex
- Growth capex is optional, financed at WACC
- Terminal value reflects competitive equilibrium

For a CERC-regulated transmission utility:
- ALL capex is mandated and tariff-recovered (no "optional")
- Growth capex EXPANDS the rate base, which mechanically expands future regulated revenue
- There is no competitive equilibrium — returns are set by formula on the rate base
- Cash flow is bond-like; valuation should be driven by the rate base, allowed ROE, and a yield-comparable discount rate

The mismatch is structural. No amount of FCF-candidate tweaking inside `_compute_fcf_base` will fix it without effectively reinventing rate-base accounting.

## 3. Candidate fixes

### A. Rate-Base Valuation (recommended)
```
FV_equity = regulated_asset_base × (1 + ROE_premium)
         + PV(excess_returns_during_explicit_period)
FV_per_share = FV_equity / shares
```
Where:
- `regulated_asset_base ≈ gross_block − accumulated_depreciation` (proxy: `net_block` from balance sheet, or `total_assets − current_assets − intangibles`)
- `ROE_premium ≈ (allowed_ROE − COE) / COE`, allowed_ROE = 0.155 (CERC), COE ≈ 0.105
- Implies P/B ≈ 1.5 for regulated utilities — matches POWERGRID's historical 2.5× P/B band when growth optionality is added back

Bypasses FCF-DCF entirely. Same math used by US utility analysts (rate-base × premium-to-book).

### B. Yield-aware DCF
Cap implied discount rate at `dividend_yield + risk_premium ≈ 0.075` (POWERGRID yield 4.5–5%, premium 2.5–3%). Then run a residual-cash-flow DCF on `NOPAT + D&A − maintenance_capex_only` (NOT total capex). Requires distinguishing growth vs maintenance capex — fragile, hard to defend in cache traces.

### C. Sector-relative (P/B × book)
```
FV = sector_median_PB × BVPS
```
Same as the financial-sector path (`compute_financial_fair_value`). Simple, defensible, already wired for banks/NBFCs. But P/B alone ignores the ROE premium — POWERGRID's ROE > sector average, so a flat sector P/B median undervalues it relative to peers within the regulated bucket.

### Recommendation: **A**, with **C** as fallback when balance-sheet data is incomplete

Approach A captures the economics correctly. The math is publicly documented in CERC tariff orders and matches how brokers (Kotak, Motilal, JM) value POWERGRID. C is a robust fallback when `net_block` or `total_equity` are missing/stale.

Implementation: introduce a new branch in `service.py` mirroring `is_financial` — `is_regulated_utility` — that routes to a new `compute_regulated_utility_fair_value` service. Default to A; fall through to C on missing data; never fall through to generic DCF.

## 4. Acceptance criteria

- POWERGRID.NS FV ∈ [₹250, ₹350] (street consensus ₹280–320)
- NTPC.NS FV ∈ [₹300, ₹430] (street ₹350–400)
- GAIL.NS FV ∈ [₹160, ₹220]
- PFC.NS / RECLTD.NS FV ∈ [₹400, ₹600] / [₹450, ₹650]
- POWERGRID `reliability_score ≥ 70`
- Verdict NOT "overvalued" when stock trades within 15% of street median
- No canary FV-drift > 15% on the other 49 canary stocks (these are non-utilities, so should be invariant)
- New unit test `tests/test_regulated_utility_valuation.py` covering POWERGRID, NTPC, GAIL, PFC golden FVs

## 5. Companion tickers (must use the new engine)

Already in `REGULATED_UTILITY_TICKERS` (WACC fix only, model still generic):
- POWERGRID, NTPC, NHPC, PFC, RECLTD, GAIL, TORNTPOWER, ADANITRANS, ADANIENSOL

Missing — ADD to set as part of this PR:
- IRFC (Indian Railway Finance — regulated NBFC, rate-base analogue)
- IEX (Indian Energy Exchange — regulated exchange, near-bond cash flows)
- NHPC is present, also add **SJVN** (state hydro, regulated tariff)
- **HUDCO** (housing-and-urban-dev, regulated lender, similar to PFC/RECLTD)

Verify each addition against canary before merging — IRFC's debt structure differs from POWERGRID's; may want a separate "regulated_nbfc" sub-branch.

## 6. Implementation surface

| File | Change | Est. LOC |
|------|--------|----------|
| `backend/services/regulated_utility_valuation_service.py` | NEW. Mirrors `financial_valuation_service.py` shape. Implements approach A + C fallback. | ~250 |
| `backend/services/analysis/service.py` | Add `is_regulated_utility` branch (parallel to `is_financial`) around L772, route to new service. Skip DCFEngine entirely for these tickers. | ~80 |
| `backend/services/analysis/constants.py` | Add `is_regulated_utility(ticker)` helper. Reuse `REGULATED_UTILITY_TICKERS` import. Already partially staged at `analytical_notes.py:90`. | ~15 |
| `models/industry_wacc.py` | Add IRFC, IEX, SJVN, HUDCO to `REGULATED_UTILITY_TICKERS`. | ~10 |
| `models/responses.py` / `models/requests.py` | Add `valuation_method: "rate_base"` enum value if surfaced in API contract. | ~5 |
| `tests/test_regulated_utility_valuation.py` | NEW. Golden FV tests for 6+ tickers. Unit-test approach A and C math in isolation. | ~200 |
| `scripts/canary_stocks_50.json` | Verify POWERGRID/NTPC/GAIL/PFC/RECLTD in canary set, update goldens. | ~5 |
| `backend/services/cache_service.py` | Bump `CACHE_VERSION` from 102 → 103 (REQUIRED — model output changes). | ~1 |
| `CHANGELOG.md` / PR description | Document. | n/a |

**Estimated PR size: ~570 LOC + tests. Single PR; do NOT split.** Splitting causes interim states where some utilities use the new engine and others don't, polluting cache.

## 7. Test plan

1. **Unit tests (new file `tests/test_regulated_utility_valuation.py`):**
   - `test_powergrid_rate_base_fv()` — assert FV ∈ [250, 350]
   - `test_ntpc_rate_base_fv()` — assert FV ∈ [300, 430]
   - `test_missing_net_block_falls_back_to_pb()` — verify approach C fallback
   - `test_negative_fcf_no_longer_crashes_fv()` — even if `latest_fcf < 0`, FV must be positive
   - `test_high_debt_does_not_subtract_from_equity()` — regression for the L379 collapse
   - `test_terminal_growth_capped_at_4pct()` — sanity
2. **Canary diff:** `python scripts/canary_diff.py` — must pass 5/5 gates on all 50.
3. **Pre/post snapshot:** `python scripts/snapshot_50_stocks.py` before, `--diff-against latest` after. Document any non-utility FV drift > 5% in PR (expected: none).
4. **Manual prod-shape check:** run `python scripts/test_dcf.py POWERGRID.NS NTPC.NS GAIL.NS PFC.NS RECLTD.NS` and confirm:
   - FV within target band
   - `valuation_method = "rate_base"` or `"sector_pb_fallback"`
   - `reliability_score >= 70`
   - No "Negative equity value" flag
5. **Reverse-DCF compatibility:** confirm `screener/reverse_dcf.py` either short-circuits for regulated utilities or reports rate-base-implied ROE instead of growth rate. New ticker on the skip list if needed.
6. **Frontend smoke:** load `/stock/POWERGRID.NS` in dev; verify the DCF panel either shows the new rate-base breakdown or is replaced with a "Regulated utility — rate-base valuation" explainer card.

## 8. Risks / open questions for implementer

- **Rate base proxy quality.** `net_block` from yfinance/screener filings may lag actuals by a quarter. Acceptable; tariffs lag too.
- **PFC/RECLTD are NBFCs not transmission utilities.** Their "rate base" is the loan book. Approach A works but the multiplier is different (P/B ~1.0–1.5, not ROE-premium derived). Consider a `regulated_nbfc` sub-class.
- **ADANIENSOL** is private-sector but CERC-regulated — same engine, no special handling.
- **TORNTPOWER** is state-DISCOM-regulated, less reliable rate-base recovery. Wider FV band acceptable.
- **CACHE_VERSION bump impact.** All cached analyses invalidate. Schedule the merge so prod rebuild can run overnight.

## 9. Out of scope

- US utilities (`us_utilities` sector) — separate fix, different regulators (FERC).
- Renewable-energy IPPs without regulated tariff (ADANIGREEN, etc.) — these are merchant + PPA, not rate-base.
- Reverse-DCF UI redesign for utilities — flag as follow-up.
