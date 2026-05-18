# Pharma DCF Fix — Design

**Status:** Draft, awaiting implementation
**Author:** investigation agent (handoff)
**Trigger:** Audit flagged MANKIND.NS (FV ₹1,244 vs CMP ₹2,494, "overvalued") and DRREDDY.NS (brief said FV ₹3,949 "undervalued", but current prod is `data_limited`/FV=0).
**Cache version at report time:** v102

---

## TL;DR

- **MANKIND and DRREDDY are NOT the same bug.**
- **DRREDDY is already mitigated** by v96 ttm-aggregator-scale-sanity-guard — prod returns `data_limited`/FV=0, not ₹3,949. The brief's ₹3,949 figure is stale (likely a pre-v96 cached observation; v75-era snapshot has DRREDDY at FV=2028.38 verdict=undervalued — never ₹3,949 in any committed snapshot). The 2.96e17 overflow referenced in the brief was collapsed first by ADR-currency mistag fix (PR #75 via `scripts/data_pipelines/fix_adr_indian_currency_mistag.py`) and then by the v96 scale-guard which forces `data_limited` when TTM is scale-corrupt. **DRREDDY's residual issue is "no FV at all"**, i.e. data-pipeline cleanup for that ticker, not a model bug.
- **MANKIND is a live model bug**, but it is NOT a missing pharma engine; it is FCF-base under-counting on a high-growth recent-IPO pharma whose 3y history is too short for the existing FCF candidates to anchor on a sensible mid-cycle base.
- **Hard-rule check (per brief):** Neither ticker shares a root cause with POWERGRID (which is a regulated-utility-engine-missing problem). DRREDDY is in the "pre-existing fix has cache-invalidated me into data_limited" bucket — flagging that explicitly per the brief's instruction.

---

## 1. Failure traces

### 1.1 MANKIND.NS path

Prod `/og-data` (2026-05-18):

```
fair_value=1244.42  price=2493.9  mos=-50.1%  verdict=overvalued
bear=710.82  base=1244.42  bull=1752.95
roe=13.89  roce=13.3  wacc=0.098  ev_ebitda=30.83
ttm_source=nse_xbrl  coverage_tier=C 5/7
valuation_model=dcf  fair_value_source=dcf
sector=Pharma  rev_cagr_3y=15.11%  piotroski=5  moat=Moderate
```

| Step | File:Line | Result for MANKIND |
|------|-----------|--------------------|
| Sector detect | `models/industry_wacc.py:1015` (TICKER_OVERRIDES) | `pharma` — keyword `"mankind"` hits. **Correct.** |
| `is_recent_ipo` gate | `backend/services/analysis/service.py:1335` calling `ipo_framework.is_recent_ipo` | Listed 2023-05-09 → 36 months on 2026-05-09 → today (2026-05-18) is **just past the 36-month window** → IPO override does NOT fire. Borderline. |
| WACC | `models/forecaster.py:706` `compute_wacc()` (pure CAPM, NOT the industry_wacc table) | β=0.7 (sector default for `pharma`/`Pharma`), Rf≈7%, MRP=6% → Re = 7 + 0.7×6 = 11.2%; after d_w tax-shield blend with mkt-cap-dominant V → WACC≈0.098. **Pharma tier's `wacc_default: 0.115` is unused** — `industry_wacc.py` only supplies beta defaults to `compute_wacc`, not the WACC itself. Surfaced 0.098 is below what street uses for an Indian pharma (typically 10.5-12%). |
| Terminal g | `service.py:744` (India default 0.04, then clamped) | 0.04 (capped at `MAX_TERMINAL_GROWTH`) |
| FCF base | `models/forecaster._compute_fcf_base` | Non-cyclical / not super-cyclical / not inventory-heavy. Path: candidates = {`latest_fcf`, `nopat_proxy` (margin_3y_avg × rev × (1-tax) × 0.85), `pharma_rd_adjusted` (rev × op_margin × (1-tax) + growth_rd × (1-tax)) × 0.80, `max_recent_fcf`, `median_recent_fcf`, `hist_p75_margin`}. Selection = `median(latest_fcf, nopat_proxy, max_recent_fcf)` then `max(primary, 0.60×nopat_proxy)`. The `pharma_rd_adjusted` candidate is **computed but never voted on** — the median selection only sees `[latest_val, nopat_val, max_val]`. |
| Growth `g` | `_rule_based_growth` (pharma REV_WEIGHT=0.80) | rev_cagr_3y=15.1% → blended ≈ 12-15%, then size-tier capped (MANKIND mcap ≈ ₹1.03 lakh Cr → large-cap tier, terminal target ~6%). |
| Project + fade | `forecaster.predict` 10y (5y explicit + 5y fade) | Projection respects margin_fade_to_3y if TTM > 130% of 3y avg. |
| Terminal norm | `service.py:969` `mean(projected[-3:])` | Modest because growth fades to 6% by year 5 then to 4% terminal. |
| EV | `dcf_engine.terminal_value` | `tv = norm × 1.04 / (0.098 − 0.04) = norm × 17.93`. TV-pct likely high (>75% of EV). |
| Equity value | `dcf_engine.intrinsic_value_per_share` `equity_value = EV − total_debt + total_cash` | MANKIND is debt-light (D/E≈0, debt/ebitda 2.4 from ratios — modest, post-Bharat Serums acquisition). Net debt subtraction NOT decisive here. |
| FV/share | `equity_value / shares` | ≈ ₹1,244 |

**Key observations on MANKIND:**

1. **FCF base under-counts economic earnings.** Mankind is a young (3-year audited) pharma with 15% revenue CAGR and ~15% PAT margins. Generic DCF anchors on the median of (latest_fcf, nopat_proxy, max_fcf). `latest_fcf` is depressed by Bharat Serums acquisition capex / working capital absorption (FY24 saw a major M&A). `pharma_rd_adjusted` would add back growth R&D (60% × 8% × revenue) — that candidate is *computed* in `_compute_fcf_base` lines 255-268 but is **never used in selection** (lines 398-411 only see latest/nopat/max). This is a code defect: the candidate is dead code for selection purposes. For MANKIND this likely loses 6-10% of effective FCF base.
2. **EV/EBITDA = 30.8** — the market is pricing growth-pharma optionality. A 17.9× TV multiple on a fade-to-6%-then-4% terminal cannot reach there. Generic DCF will always underweight scarcity/brand premium for a domestic-OTC franchise (Manforce, Prega News, Unwanted-72 — pricing power in non-prescription space).
3. **Recent-IPO window expired 9 days ago.** The sector-relative recent-IPO override (which would have priced MANKIND off cohort P/E — sector pharma P/E ~30 — on ~₹54/sh EPS would give ~₹1,620 FV, still bearish but better) is now off. The 36-month boundary is a hard cliff, not a fade.
4. **No `MANKIND` entry in `ticker_overrides.py`** (no `terminal_growth_override`, no `ipo_listing_date`, no model caveat). Surface lookup via `MANKIND` and `MANKINDPHARMA.NS` both miss.
5. **WACC 9.8% is reasonable for pharma** (street uses 10-11%) but the `industry_wacc.py` pharma tier specifies `wacc_default: 0.115`. The pipeline does not honour it — `compute_wacc` re-derives via CAPM. Not the root cause for MANKIND, but worth noting as a calibration mismatch.

### 1.2 DRREDDY.NS path

Prod `/og-data` (2026-05-18):

```
fair_value=0.0  price=1295.0  mos=0.0  verdict=data_limited
bear=null  base=null  bull=null
roe=16.96  roce=22.0  wacc=0.098  ev_ebitda=12.19
ttm_source=nse_xbrl  quarterly_last_filed_at=2026-03-31
```

Snapshot evolution:

- **Pre-v75 (April 2026):** `equity_value ≈ 2.96e17` per the brief — a USD-as-INR overflow because yfinance returned `financialCurrency='USD'` with INR-magnitude values on DRREDDY's annual rows.
- **v75 (PR #75, 2026-04-29):** `fix_adr_indian_currency_mistag.py` ran a data-layer patch on 15 IT+pharma tickers. **DRREDDY is NOT in `AFFECTED_TICKERS`** (`COFORGE, CYIENT, DIVISLAB, HCLTECH, INFY, KPITTECH, LAURUSLABS, LTIM, MASTEK, MPHASIS, OFSS, PERSISTENT, TATAELXSI, TECHM, WIPRO`). DRREDDY's overflow was not patched by that script.
- **v89 / pre-v96 snapshot:** DRREDDY had FV=2028.38, verdict=undervalued, MoS=+65.9%, WACC=0.097, rev_cagr_3y=11.9%, cache_version=75. This is the state the brief approximates as "₹3,949 +205% MoS" — the snapshot file disagrees; brief number is from a different (probably interim) state.
- **v96 (2026-05-17):** TTM-aggregator scale-sanity guard added. The cache-service comment lists DRREDDY explicitly in the cohort that flipped to `data_limited`: *"WIPRO/TECHM/DRREDDY/MPHASIS/COFORGE/PERSISTENT/KPITTECH similarly flip to data_limited (their pre-fix FVs were derived from scale-poisoned TTM rows; data_limited is the honest answer until re-ingest cleans these tickers)"*.
- **Today (v102):** still `data_limited`, FV=0.

**Key observations on DRREDDY:**

1. **DRREDDY is a USD reporter on yfinance.** yfinance returns `financialCurrency='USD'` for it. The v90 currency-conversion path in `backend/services/currency_conversion_service.py` only converts tickers on the allow-list `USD_REPORTER_TICKERS = {MPHASIS, COFORGE, PERSISTENT, KPITTECH}`. DRREDDY is not on this list, so:
   - `data_pipeline/sources/yf_info_cache.py:215` rejects the yfinance `info` row with reason `"financialCurrency=USD on Indian-primary ticker DRREDDY (suspected ADR mistag — see PR #208 lineage)"` (Rule 1 of `_is_plausible_info`).
   - The XBRL fallback path also produces TTM rows whose scale fails the v96 guard (likely a combination of unit/currency mistagging in the underlying parser).
2. **DRREDDY is a pharma USD reporter (legitimate),** parallel to MPHASIS/COFORGE in IT. It exports ~50% of revenue to the US, files 20-F with SEC, and yfinance picks up the US-segment USD statements. Same fix shape as the v90 IT allow-list applies: add DRREDDY (and DIVISLAB, LAURUSLABS, AUROPHARMA — see §6) to `USD_REPORTER_TICKERS`. The currency-conversion service then converts USD→INR at period-end spot inside `data_pipeline/xbrl/yf_fetcher.py:189-204`, and the `_is_plausible_info` carve-out at `yf_info_cache.py:215-227` already short-circuits for legit USD reporters.
3. **The 2.96e17 overflow is gone** (current `equity_value` field returns 0 because no DCF runs). The residual issue is purely "DCF doesn't run" — the model itself is not producing a wrong answer, it's producing no answer.

---

## 2. Root-cause classification

| Ticker | Bucket | Detail |
|--------|--------|--------|
| **MANKIND** | **B + D** (model calibration + ticker-specific) | Pharma DCF works structurally for SUNPHARMA/CIPLA. MANKIND specifically suffers: (i) `pharma_rd_adjusted` FCF candidate is computed but unused in selection, (ii) recent IPO with 3y audited history → `nopat_proxy` 3y margin avg pulls *down* not up because FY24 absorbed an acquisition, (iii) generic DCF can't price domestic-OTC scarcity premium reflected in EV/EBITDA 30.8. |
| **DRREDDY** | **A** (data quality) | yfinance USD financialCurrency tag → info-row rejection + XBRL scale-poisoning → v96 guard correctly flips to `data_limited`. No model change needed; needs the same allow-list extension that fixed MPHASIS/COFORGE in v90. |

**MANKIND and DRREDDY are different bugs.** They are NOT the same root cause; they are NOT POWERGRID-style (no regulated/asset-base economics involved); MANKIND is NOT a cache-invalidation latency issue (v102 is live). DRREDDY IS effectively a "pre-existing fix shape exists, just not applied to this ticker" — per the brief's hard rule, flagged here explicitly: **the DRREDDY fix is the v90 USD-reporter allow-list extension, not a new pharma engine.**

---

## 3. Recommended fixes

### 3.1 DRREDDY (and other pharma USD reporters) — data fix only

**One-line change:** add pharma tickers to `USD_REPORTER_TICKERS` in `backend/services/currency_conversion_service.py:73`.

```python
USD_REPORTER_TICKERS: frozenset[str] = frozenset({
    # IT services (seeded 2026-05-17)
    "MPHASIS", "COFORGE", "PERSISTENT", "KPITTECH",
    # Pharma USD reporters (added pharma-fix)
    "DRREDDY", "DIVISLAB", "LAURUSLABS",  # confirm AUROPHARMA via yfinance check
})
```

Verify each candidate's `financialCurrency` via a one-off yfinance call before merge (script: `python -c "import yfinance as yf; print(yf.Ticker('DRREDDY.NS').info.get('financialCurrency'))"`). DO NOT add a pharma ticker unless it actually reports USD.

Then run the v90-style data fix path:
- `data_pipeline/xbrl/yf_fetcher.py` converts at spot
- `data_pipeline/sources/yf_info_cache.py:215` carve-out passes the row through
- TTM aggregator no longer sees scale-corrupt rows for these tickers → v96 guard doesn't trip
- CACHE_VERSION bump (102 → 103) forces recompute

No new engine. No new DCF branch.

### 3.2 MANKIND — three targeted lever changes

In order of impact (do all three; each alone is insufficient):

**A. Wire the `pharma_rd_adjusted` candidate into selection.** `models/forecaster.py:255-268` computes it; the selection at `models/forecaster.py:398-411` ignores it. Add it to the median pool when sector == "pharma":

```python
if _sector == "pharma" and "pharma_rd_adjusted" in candidates:
    valid_candidates = [v for v in [latest_val, nopat_val, max_val, candidates["pharma_rd_adjusted"]] if v > 0]
```

This adds back growth R&D (60% × 8% × revenue) to the economic-earnings anchor. For MANKIND this is ~₹400-500 Cr added to a ~₹1,800 Cr nopat_proxy base.

**B. Extend the recent-IPO window for pharma to 60 months.** `ipo_framework._RECENT_IPO_WINDOW_MONTHS = 36` is a single constant for all sectors. Pharma has slower-maturing economics (post-launch ramp, US ANDA approval cycles, Bharat Serums-style M&A integration). Make it sector-dependent:

```python
_RECENT_IPO_WINDOW_MONTHS_BY_SECTOR = {"pharma": 60, "default": 36}
```

For MANKIND today this would route through `sector_relative_recent_ipo` (cohort pharma P/E median × EPS_ttm) which produces ~₹1,500-1,700 FV depending on cohort. Still below CMP but no longer flagged "overvalued" — verdict caps at `data_limited` unless deviation > 30%.

**C. Add `MANKIND` ticker override entry** in `backend/services/analysis/ticker_overrides.py` with a model caveat noting domestic OTC scarcity premium not captured by DCF, and a `terminal_growth_override: 0.05` (vs 0.04 default — splits the difference between FMCG TITAN's 6% and generic pharma 4%, reflecting Mankind's tobacco-pricing-power-style OTC moat in chronic care + branded contraceptives).

Combined effect on MANKIND FV: estimated band ₹1,500-1,800 (vs current ₹1,244). Still bearish vs CMP ₹2,494 (street ₹2,500-2,800). Honest answer is `data_limited` or "overvalued with caveat". The fix is not "make MANKIND fairly_valued"; it's "make the model's bear stance defensible and the IPO scarcity premium acknowledged".

### 3.3 What we explicitly DO NOT recommend

- **No new pharma engine.** Pharma is not regulated-utility-shaped. FCF-DCF + sector beta works for SUNPHARMA/CIPLA/TORNTPHARM/ALKEM. The bug is calibration + dead-code in the FCF selection, not a structural model mismatch.
- **No SOTP for DRREDDY.** Multi-geography ≠ conglomerate. The income statement consolidates fine once the currency is right.
- **No `is_pharma` sector branch in `service.py`.** Adding a third special-case after `is_financial` and (future) `is_regulated_utility` would dilute the model surface. The pharma fixes belong inside `_compute_fcf_base` and the IPO window.
- **No widening of WACC to honour `industry_wacc.py` pharma `wacc_default: 0.115`.** That would lower MANKIND FV further. The CAPM-derived 0.098 is already conservative for a domestic-OTC pharma; pushing it to 0.115 is a calibration error in the other direction.

---

## 4. Acceptance criteria

After implementation:

- **DRREDDY.NS** FV ∈ [₹1,100, ₹1,600] (street consensus ₹1,200-1,500). `valuation_method` returns to `dcf`; `data_limited` flag clears.
- **MANKIND.NS** FV ∈ [₹1,500, ₹2,000] (model bearish vs street ₹2,500-2,800 is acceptable; verdict either "overvalued" with explicit IPO/OTC caveat, or `data_limited` via sector-relative window extension). NOT below ₹1,400.
- DCF golden snapshot (`scripts/dcf_golden.json`) rebaselined post-merge; document drift for DRREDDY in PR.
- Canary diff (`python scripts/canary_diff.py`) passes 5/5 gates on all 50.
- New unit tests:
  - `test_pharma_rd_adjusted_candidate_voted` — assert `_fcf_base_source` for MANKIND/CIPLA equals one of `nopat_floor | median | pharma_rd_adjusted` (not `latest_fcf` when latest is depressed).
  - `test_pharma_usd_reporter_converted` — assert DRREDDY annual revenue post-conversion lands in [₹25,000Cr, ₹32,000Cr].
  - `test_recent_ipo_window_pharma_60m` — MANKIND with listing_date 2023-05-09 returns `is_recent_ipo=True` for sector="pharma".
- No canary FV-drift > 15% on non-pharma tickers.

---

## 5. Pharma peer impact prediction

For each peer, "would the fix help" classified as: **YES** (currently broken and fix applies), **NO** (already fine), **MAYBE** (could regress slightly if currency check is wrong).

| Ticker | Current prod state | Same fix helps? | Reasoning |
|--------|-------------------|-----------------|-----------|
| SUNPHARMA.NS | DCF runs (golden has it) | NO | Mature, INR-reporter, R&D pickup helps marginally (~+5% FV). Run canary to verify no regression. |
| CIPLA.NS | DCF runs (golden has it) | MAYBE | Domestic-focused, INR-reporter. R&D candidate addition lifts FV ~3-7%. Verify post-merge. |
| DIVISLAB.NS | Likely `data_limited` post-v96 (it was in the v75 ADR-fix list) | **YES** (USD-reporter allow-list) | Pure-play API exporter, US-listed customer base, financialCurrency=USD common. Add to allow-list. |
| AUROPHARMA.NS | Verify; suspect `data_limited` | **YES (likely)** | US generics-heavy; verify financialCurrency before adding. |
| LUPIN.NS | Verify | MAYBE | US generics-heavy but historically reports INR on yfinance per anecdotal observation. Verify via `yf.Ticker('LUPIN.NS').info`. |
| LAURUSLABS.NS | In v75 ADR-fix list; currently INR | NO additional fix | v75 patch held; data is clean. Watch for re-corruption on next NSE backfill. |
| GLENMARK.NS | DCF runs | NO | INR reporter, mid-cap, generic DCF works. R&D pickup helps ~+5%. |
| TORNTPHARM.NS | DCF runs (also in pharma keywords) | NO | Domestic + select exports, INR reporter, mature. |
| ALKEM.NS | DCF runs | NO | Domestic chronic care, INR reporter. |
| ZYDUSLIFE.NS | DCF runs | MAYBE | Some USD exposure; verify currency tag. R&D candidate helps. |
| IPCALAB.NS | DCF runs | NO | Domestic-heavy, mid-cap, INR reporter. |
| BIOCON.NS | (Not listed in brief but relevant) — verify | MAYBE | Biosimilars heavy, US exposure, may report USD. Verify. |

Run `python -c "import yfinance as yf; [print(t, yf.Ticker(t).info.get('financialCurrency')) for t in 'DRREDDY.NS DIVISLAB.NS AUROPHARMA.NS LUPIN.NS BIOCON.NS GLENMARK.NS ZYDUSLIFE.NS LAURUSLABS.NS'.split()]"` and add to allow-list ONLY where output is `USD`.

---

## 6. Implementation surface

| File | Change | Est. LOC |
|------|--------|----------|
| `backend/services/currency_conversion_service.py` | Add 2-4 pharma tickers to `USD_REPORTER_TICKERS` (after live `financialCurrency` verification). | ~5 |
| `models/forecaster.py` | Wire `pharma_rd_adjusted` candidate into median selection inside `_compute_fcf_base` (sector-gated). Add unit-test hook stash key `_pharma_rd_used`. | ~15 |
| `backend/services/analysis/ipo_framework.py` | Make `_RECENT_IPO_WINDOW_MONTHS` sector-aware. Accept `sector` kwarg in `is_recent_ipo()`. | ~25 |
| `backend/services/analysis/service.py` | Pass `sector` to `is_recent_ipo()` call at line 1335. | ~3 |
| `backend/services/analysis/ticker_overrides.py` | Add `MANKIND` entry with model caveat + `terminal_growth_override: 0.05`. Optionally `MANKIND.NS` alias. | ~15 |
| `tests/test_pharma_dcf.py` | NEW. Unit tests per §4. | ~150 |
| `scripts/dcf_golden.json` | Rebaseline post-merge (separate PR, follow project rule). | ~5 |
| `backend/services/cache_service.py` | Bump `CACHE_VERSION` 102 → 103 (REQUIRED — model output changes). | ~1 |
| `CHANGELOG.md` / PR description | Document. Include before/after FV table for DRREDDY, MANKIND, DIVISLAB, AUROPHARMA. | n/a |

**Estimated PR size: ~220 LOC + tests. Single PR.** Smaller than the regulated-utility PR; do not split.

---

## 7. Test plan

1. **Pre-bump snapshot:** `python scripts/snapshot_50_stocks.py` — copy to `scripts/snapshots/before_v103_pharma_dcf.json`.
2. **Live yfinance check:** verify financialCurrency for each candidate USD-reporter pharma ticker. ONLY add to allow-list when output is "USD".
3. **Unit tests (new file `tests/test_pharma_dcf.py`):**
   - `test_pharma_rd_adjusted_candidate_voted()` — synthetic enriched dict for a pharma with op_margin=0.18, R&D=8% of revenue; assert `_fcf_base_source` ≠ `latest_fcf` and base ≥ `nopat_proxy × 0.95`.
   - `test_drreddy_currency_conversion_path()` — mock yfinance to return `financialCurrency='USD'` and synthetic statements; assert `enriched['latest_revenue']` lands in [₹25,000Cr, ₹32,000Cr].
   - `test_mankind_ipo_window_extends_pharma_to_60m()` — listing 2023-05-09 + sector="pharma" + today=2026-05-18 → `is_recent_ipo=True`.
   - `test_mankind_ticker_override_terminal_growth()` — `_get_ticker_override("MANKIND")` returns `terminal_growth_override=0.05`.
   - `test_non_pharma_unaffected()` — TCS/HDFCBANK FV unchanged by these changes (sector-gate test).
4. **Canary diff:** `python scripts/canary_diff.py` — must pass 5/5 gates on all 50.
5. **Pre/post snapshot diff:** verify FV moves:
   - DRREDDY: 0 → ~₹1,200-1,500
   - MANKIND: ₹1,244 → ~₹1,500-1,800 (or `data_limited` if IPO window catches it)
   - DIVISLAB / AUROPHARMA: out of `data_limited` if added to USD allow-list
   - SUNPHARMA / CIPLA / TORNTPHARM / ALKEM / IPCALAB: drift < ±5%
6. **Manual prod-shape check:** `python scripts/test_dcf.py --update` and review the diff against the golden. Re-baseline `dcf_golden.json` in the immediately-next PR per CLAUDE.md rule.
7. **Frontend smoke:** load `/stock/MANKIND.NS` and `/stock/DRREDDY.NS` in dev; verify (a) DCF panel renders for DRREDDY, (b) MANKIND shows IPO/OTC caveat note.

---

## 8. Risks / open questions for implementer

- **financialCurrency tag is yfinance-dependent and not stable.** Tag for DIVISLAB has flipped at least twice between INR and USD in 12 months per the v50/v75/v90 lineage in cache_service.py. The USD_REPORTER allow-list is the right level of caution; data-side fallback at `yf_info_cache.py:215` blocks legitimate ADR mistags from the allow-list scope.
- **MANKIND's listing date** must be sourced from a reliable place. `raw.get("listing_date")` depends on yfinance `firstTradeDateEpochUtc`. For MANKIND this should resolve to 2023-05-09; verify in `service.py:1321`. If absent, fall through to data-side recent-IPO check (`_n_annual < 3`) — but MANKIND now has 3 annuals (FY23, FY24, FY25) so the data-side gate WON'T fire. The fix MUST go through the listing-date branch, hence the explicit `ticker_overrides.py` entry as belt-and-braces.
- **`pharma_rd_adjusted` candidate selection** could inflate FV for asset-light pharma that already has high `nopat_proxy`. Sector-gate the change and run the canary on all 12 pharma peers before merge. If any peer drifts > 15%, narrow the gate to `sector=="pharma" AND latest_fcf < 0.8 × nopat_proxy` (i.e. only when conventional FCF is depressed vs economic earnings).
- **DRREDDY's XBRL TTM** may still produce scale-corrupt rows even after the currency fix lands — the underlying NSE XBRL parser bug from PR #57 lineage could still be at play. If post-fix DRREDDY remains `data_limited`, run `python scripts/data_pipelines/fetch_annual_financials.py DRREDDY.NS` to force a clean re-ingest, and verify the v96 scale-guard no longer trips for it.
- **CACHE_VERSION bump invalidates every cached payload.** Schedule the merge so the worker rebuild can complete overnight.
- **`ev_ebitda` 30.8 for MANKIND** is real market signal. The model SHOULD show bearish vs that multiple — the goal is not to chase the market. "Overvalued with explicit OTC scarcity caveat" is an honest answer; the verdict's information value is in the caveat, not the FV number.

---

## 9. Out of scope

- **Conglomerate pharma / multi-segment SOTP** (e.g. SUNPHARMA + branded generics + Taro). Not a current outlier; defer until canary flags it.
- **CDMO sub-sector engine** (LAURUSLABS, NEULAND, SYNGENE) — has different unit economics (capex-heavy contract manufacturing). Separate fix when those tickers fail.
- **Biosimilars valuation methodology** (BIOCON). Pipeline / royalty-stream models are a distinct problem.
- **Reverse-DCF / implied-growth UI** for pharma — separate follow-up if MANKIND's implied growth is incoherent post-fix.
- **Pharma WACC tier honoured from `industry_wacc.py`.** Calibration mismatch noted in §1.1, but moving CAPM toward 0.115 hurts FV; not pursued here.
