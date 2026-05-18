# Cement DCF Fix — Design

**Status:** Draft, awaiting decision
**Author:** investigation agent (handoff)
**Trigger:** Competitive audit flagged cement as a broken sector. Sector has been thrashed: v56 removed cement from `_CYCLICAL_SECTORS`; v81 layered a "cement methodology + super-cyclical FCF window" via cafc463/1988fa4 (SHREECEM 26568→5316, ULTRACEMCO 11523→4282); PR #314 then exempted cement from the canary fv/cmp 0.35 floor (override → 0.25). Net state today is unstable and inconsistent across the cohort.
**Cache version at report time:** v102

---

## TL;DR

- **Half the cohort is already in band.** SHREECEM, DALBHARAT, JKCEMENT, RAMCOCEM are within ±30% of consensus today.
- **Three names are catastrophically broken**, all post-M&A integrators: ULTRACEMCO (-72%), AMBUJACEM (-82%), ACC (-62% to -65%).
- **The bug is not "cement is cyclical" any more.** It is FCF-base under-anchoring on tickers whose latest_fcf is depressed by acquisition absorption (UltraTech ate Kesoram + India Cements; Adani bought Ambuja+ACC and ran heavy capacity-expansion capex). The 10y signed-median introduced in v81 (cafc463/1988fa4) does the wrong thing here because the trailing 10y straddles two acquirer regimes.
- **AMBUJACEM has a second, independent bug:** sector resolves to `"General/Diversified"`, not `"Cement"`. None of the cement-specific code paths fire for it.
- **Hard-rule check:** acceptance test says "if already in ±30% band, recommend no fix". 4/7 tickers ARE in band. The three failures share a single proximate cause (post-M&A FCF anchor pollution), not a sector-engine gap. **Recommended path is targeted (option A + a sector-detect patch), not a new engine.**

---

## 1. Current prod state (top 7 cement tickers, 2026-05-18)

Pulled from `https://api.yieldiq.in/api/v1/public/stock-summary/<ticker>.NS`:

| Ticker | FV | CMP | MoS | Verdict | Consensus band | In ±30%? |
|---|---:|---:|---:|---|---|---|
| SHREECEM | 25,988 | 24,425 | +6.4% | fairly_valued | ₹23k-28k | YES |
| **ULTRACEMCO** | **3,029** | **11,529** | **-73.7%** | **overvalued** | ₹10k-12k | **NO (-72%)** |
| **AMBUJACEM** | **100.7** | **425.4** | **-76.3%** | **overvalued** | ₹500-600 | **NO (-82%)** |
| **ACC** | **911** | **1,344** | **-32.2%** | **overvalued** | ₹1,800-2,400 (street ₹2,200) | **NO (-58%)** |
| DALBHARAT | 1,813 | 1,704 | +6.4% | fairly_valued | ₹1,800-2,200 | YES |
| JKCEMENT | 5,775 | 5,428 | +6.4% | fairly_valued | ₹5,000-5,800 | YES |
| RAMCOCEM | 853 | 898 | -5.0% | fairly_valued | ₹900-1,100 | borderline YES |

Notable second-order signals:

- **ULTRACEMCO, AMBUJACEM, ACC all have `revenue_cagr_5y` = null** in prod (UltraTech 5y shows but ACC/AMBUJA do not). The 10y signed-median FCF cannot have been computed honestly when 5y history is itself thin/non-resolving.
- **AMBUJACEM `sector` = "General/Diversified"** in the API response. Compare SHREECEM/ACC/JKCEMENT/RAMCOCEM all surfacing `sector="Cement"`. AMBUJA is silently routed through generic (non-cement) DCF.
- **WACC 0.098 for ULTRACEMCO / AMBUJA / DALBHARAT / JKCEMENT / RAMCOCEM; 0.128 for SHREECEM and ACC.** The split is incoherent — SHREECEM (debt-free, AAA) on 12.8% while leveraged AMBUJA on 9.8% is the opposite of credit reality. This is a separate calibration tail but not the proximate cause of the FV gap.
- **`mcap / cmp` implied shares match BSE filings within 2%** for all four broken tickers (ULTRACEMCO 29.4 cr, AMBUJA 248.5 cr, ACC 18.8 cr, SHREECEM 3.61 cr). v102 shares-outstanding reconciliation worked. **Shares-count is not the bug.**

## 2. History — why prior interventions fell short

| Phase | Change | Effect | Why it didn't stick |
|---|---|---|---|
| Original (pre-v56) | Cement in `_CYCLICAL_SECTORS` → 5y median FCF cap | Capped peak-cycle FCF to 5y median | The 5y window (2019-2024) sat **entirely inside India's post-COVID infra upcycle**. Median was structurally below current mid-cycle. SHREECEM landed at fv/cmp=0.226, ULTRACEMCO 0.306 — canary perma-failed. |
| v56 (PR #64, 2026-04-24) | **Removed cement** from `_CYCLICAL_SECTORS` | Unblocked canary, restored TTM-driven FCF anchor | Over-corrected the other way for post-M&A tickers. ULTRACEMCO/AMBUJA/ACC TTM FCF is depressed by acquisition capex, but without ANY normalisation the "latest_fcf median nopat max" pool now leans on `latest_fcf` directly. |
| v81 (cafc463 + 1988fa4, 2026-05-03) | "Cement methodology + super-cyclical FCF window" | SHREECEM 26568→5316 (-80%), ULTRACEMCO 11523→4282 (-63%) | Aggressive recalibration crushed FVs; later partially clawed back. Today SHREECEM has rebounded to 25,988 but ULTRACEMCO sits at 3,029 — i.e. the v81 over-correction **persists for the post-M&A names only**. Suggests the 10y signed-median is now mis-anchoring on the pre-acquisition entity's FCF profile. |
| PR #314 (canary fv/cmp floor exemption) | Lowered fv/cmp floor 0.35 → 0.25 for cement super-cyclicals | Stopped canary gate from blocking PRs on these tickers | **This is a compensating control, not a fix.** It hides the bug from canary. ULTRACEMCO fv/cmp = 3029/11529 = 0.263 — passes the relaxed 0.25 floor but is plainly wrong. |
| `ticker_overrides.py` (current) | `ULTRACEMCO` / `SHREECEM` get a model_caveat noting "10y signed-median can over-correct in upcycles; half-weight signed-median fix on Q3 roadmap" | UI shows caveat | Caveat ≠ correctness. AMBUJA/ACC not even on the override list. |

**Common thread:** every intervention has been at the **FCF-normalisation candidate level** (which window, which median). None has addressed the actual mechanism — M&A absorption transiently suppresses latest_fcf AND drags the multi-year median because the acquired entity's pre-deal FCFs are included.

## 3. Root cause classification

| Ticker | Bucket | Detail |
|---|---|---|
| SHREECEM | (none — in band) | Mature, debt-free, no M&A. The 10y signed-median works here because the trailing window is a single entity. Surface WACC=12.8% is high but compensated. |
| DALBHARAT | (none — in band) | Cement + sugar holdco; FV close to CMP. Honest answer. |
| JKCEMENT | (none — in band) | Regional, low M&A, clean signal. |
| RAMCOCEM | (none — in band; thin coverage) | Confidence=12, low-quality data but FV in spitting distance of CMP. |
| **ULTRACEMCO** | **B (model calibration)** | M&A absorber. Bought Kesoram cement (2024) + India Cements (2025). Latest_fcf includes integration capex; 10y signed-median straddles pre-M&A and post-M&A regimes, anchoring below true mid-cycle. revenue_cagr_5y resolves (11.8%) so data isn't gone, just mis-anchored. |
| **AMBUJACEM** | **A + B (data quality + calibration)** | **Sector mistag** (`"General/Diversified"` not `"Cement"`) — cement-specific code paths don't fire. PLUS the Adani 2022 takeover means yfinance/XBRL 5y history is mixed-regime (Holcim → Adani). revenue_cagr_5y = null is the smoking gun. |
| **ACC** | **A + B (data quality + calibration)** | Same Adani-regime transition as AMBUJA. revenue_cagr_5y = null. WACC=12.8% is too high for the credit profile post-Adani. Sector correctly resolves to "Cement" but the FCF anchor still trips on the regime change. |

Not a "sector engine missing" problem (like regulated-utility / financial). The DCF shape is correct for cement when history is clean. The failure is on three names whose history is **transiently dirty** because of M&A.

## 4. Candidate approaches

### A. Wider FCF normalisation window (10y → 12-15y, post-M&A-aware)

Already partly here: `SUPER_CYCLICAL_WINDOW_YEARS = 15` exists for the `_CAPEX_SUPER_CYCLICAL_TICKERS` set, but cement is intentionally excluded from that set (per v56 hotfix comment).

The targeted fix is NOT to add cement back into `_CAPEX_SUPER_CYCLICAL_TICKERS` wholesale — that would re-break SHREECEM. Instead:

1. **Detect post-M&A regime change** for cement tickers: if (sector ∈ cement) AND (`revenue_cagr_5y` is null OR `revenue_cagr_3y` < 0.5 × `revenue_cagr_5y` of peer median), route through a normalised path.
2. For those tickers: anchor on **forward-NOPAT estimate** = `revenue_ttm × peer_median_ebit_margin × (1-tax) × peer_median_fcf_conv`, where peer-median is the trimmed mean of the in-band cement cohort (SHREECEM/DALBHARAT/JKCEMENT/RAMCOCEM).
3. Wider window only for the polluted tickers (15y), with **acquirer-era only** filter (drop years before majority acquisition where detectable; for AMBUJA/ACC, drop pre-2022; for ULTRACEMCO the full window is the acquirer-era so no drop).

Pros: surgical; reuses existing super-cyclical signed-median machinery; doesn't touch in-band tickers.
Cons: needs an M&A regime-change detector; "peer-median FCF conv" introduces a circular-peers risk if all peers shift.

### B. Capacity-utilisation based model (volume × pricing × normalised margin)

Build cement-specific revenue model: `revenue = installed_capacity_MT × utilisation × realisation_per_tonne`. Margin from sector-median EBITDA/tonne (~₹900-1100 currently). FCF from D&A + maintenance capex/tonne.

Pros: cleanest economics, defensible to a sell-side analyst, immune to M&A history pollution because installed_capacity is a forward fact.
Cons: requires installed-capacity per ticker (~13 tickers), realisation_per_tonne quarterly, maintenance capex per tonne. Data pipeline doesn't have any of these. ~500-800 LOC + multi-week data sourcing. **Out of proportion** for 3 broken tickers in a sector that's otherwise fine.

### C. EV/EBITDA cohort-relative valuation (peer-band)

For broken tickers, set `FV = peer_median_ev_ebitda × ticker_ebitda - net_debt`, with peer-median computed from the in-band cement cohort. Today SHREECEM/JKCEMENT trade ~16-18× EV/EBITDA; applying 16× to ULTRACEMCO's EBITDA gets you back into the consensus band quickly.

Pros: tiny implementation (~80 LOC). Mirrors the financial-sector P/B path. Self-correcting (uses live peer prices). Direct comparable to how brokers value cement.
Cons: not a "DCF" — surfaces `valuation_method = "peer_relative_ev_ebitda"`. Two-tier model in the same sector is a smell. Cohort is small (4 in-band names); if the cohort drifts together the FV drifts with it.

### Recommendation: **A**, with **C** as fallback when M&A regime detection trips

Approach A addresses the actual mechanism (M&A absorption pollutes FCF history) without spinning up a sector engine the rest of the cement cohort doesn't need. Half-weight signed-median (already on the Q3 roadmap per `ticker_overrides.py` comment) is the simplest expression of A — give half-weight to pre-M&A years for tickers flagged with regime change.

Approach B is over-build for 3 tickers. Approach C is a good emergency fallback when A can't get history (sector unknown, no peers).

Also bundle the **AMBUJACEM sector mistag fix** — add `AMBUJACEM` to `TICKER_SECTOR_OVERRIDES` mapping → `"Cement"`. This is a one-line data fix that unblocks every cement-aware path for AMBUJA regardless of which approach (A/B/C) ships.

**Confidence: medium.** The M&A-regime hypothesis fits the evidence (revenue_cagr_5y nulls for ACC/AMBUJA, sector mistag for AMBUJA, ULTRACEMCO's post-acquisition capex absorption is public knowledge), but I haven't been able to inspect `enriched["fcf_history"]` or `_fcf_base_source` for these tickers from the worktree. Implementer should verify the FCF candidate trail before committing to A.

## 5. Acceptance criteria

After implementation:

- **ULTRACEMCO.NS** FV ∈ [₹9,500, ₹13,000] (street ₹10,000-12,000). Verdict NOT "overvalued".
- **AMBUJACEM.NS** FV ∈ [₹450, ₹650] (street ₹500-600). Sector field returns `"Cement"`, not `"General/Diversified"`.
- **ACC.NS** FV ∈ [₹1,700, ₹2,500] (street ₹1,800-2,400). WACC re-derived ≤ 11% (post-Adani credit profile).
- **SHREECEM.NS** FV stays within ±10% of current ₹25,988 (no regression).
- **DALBHARAT / JKCEMENT / RAMCOCEM** FV stays within ±10% (no regression).
- Canary diff (`python scripts/canary_diff.py`) passes 5/5 gates on all 50.
- PR #314 fv/cmp floor override of 0.25 can be **reverted to 0.35** post-fix (i.e. the relaxed floor was a compensating control; the fix removes the need).
- New unit tests covering the four broken tickers' golden FVs.

## 6. Implementation surface

| File | Change | Est. LOC |
|---|---|---|
| `backend/services/analysis/constants.py` | Add `AMBUJACEM` to `TICKER_SECTOR_OVERRIDES` → `"Cement"`. Add a curated `POST_MA_REGIME_CHANGE` set `{"ULTRACEMCO", "AMBUJACEM", "ACC"}` with `regime_start_year` per ticker. | ~20 |
| `models/forecaster.py` | Inside `_compute_fcf_base`: for cement tickers in `POST_MA_REGIME_CHANGE`, restrict the FCF candidate window to ≥ `regime_start_year`. Use half-weight signed-median over the post-regime years; fall back to peer-median EV/EBITDA (option C) when fewer than 3 post-regime years exist. Stash `_fcf_anchor_strategy` for debuggability. | ~80 |
| `backend/services/analysis/ticker_overrides.py` | Promote ULTRACEMCO caveat to apply to AMBUJACEM + ACC; remove the "10y signed-median can over-correct" wording (will no longer be the path). | ~10 |
| `scripts/canary_diff.py` | Revert PR #314 cement floor overrides 0.25 → 0.35 (default). Keep the metals overrides untouched. | ~5 |
| `tests/test_cement_dcf.py` | NEW. Golden FV tests + a regression test asserting SHREECEM/DALBHARAT/JKCEMENT/RAMCOCEM FVs do NOT drift more than 10% pre/post. | ~150 |
| `scripts/dcf_golden.json` | Rebaseline post-merge (immediately-next PR, per CLAUDE.md). | ~5 |
| `backend/services/cache_service.py` | Bump `CACHE_VERSION` 102 → 103 (REQUIRED — model output changes for 3+ cement tickers). | ~1 |
| `CHANGELOG.md` / PR description | Document. Include before/after table for all 7 cement tickers. | n/a |

**Estimated PR size: ~270 LOC + tests. Single PR.** Smaller than the regulated-utility PR (570 LOC). Larger than pharma (220 LOC). Do not split — interim states would leave the post-M&A cohort half-fixed.

## 7. Test plan

1. **Pre-bump snapshot:** `python scripts/snapshot_50_stocks.py` → `scripts/snapshots/before_v103_cement_dcf.json`.
2. **Verify M&A regime years from filings** before committing to the curated set:
   - ULTRACEMCO: Kesoram absorption FY24, India Cements FY25 → regime_start_year = 2024
   - AMBUJACEM: Adani takeover Sep 2022 → regime_start_year = 2023
   - ACC: same Adani takeover → regime_start_year = 2023
3. **Unit tests (new file `tests/test_cement_dcf.py`):**
   - `test_ultracemco_post_ma_fcf_anchor()` — synthetic enriched dict with pre-2024 FCF flat, post-2024 FCF depressed; assert `_fcf_anchor_strategy == "post_regime_signed_median"` and FV ∈ [9500, 13000].
   - `test_ambujacem_sector_routed_correctly()` — assert `enriched['sector'] == 'Cement'` after override, not yfinance's "General/Diversified".
   - `test_acc_wacc_recomputed_post_adani()` — assert WACC ≤ 0.11 after credit-profile update.
   - `test_shreecem_no_regression()` — golden FV stays within ±10% of v102 reading.
   - `test_jkcement_dalbharat_ramcocem_no_regression()` — same for the rest of the in-band cohort.
   - `test_peer_median_ev_ebitda_fallback()` — when M&A ticker has <3 post-regime years, falls back to option C; assert FV ∈ consensus band.
4. **Canary diff:** `python scripts/canary_diff.py` — must pass 5/5 gates on all 50 **with the cement fv/cmp floor reverted from 0.25 to 0.35**. If the relaxed floor is still needed post-fix, the fix didn't work.
5. **Pre/post snapshot diff:** verify expected moves:
   - ULTRACEMCO: 3,029 → ~10,500
   - AMBUJACEM: 100.7 → ~525
   - ACC: 911 → ~2,100
   - SHREECEM, DALBHARAT, JKCEMENT, RAMCOCEM, BIRLACORPN, INDIACEM, NUVOCO, HEIDELBERG, ORIENTCEM: drift < ±10%
   - Non-cement canary: drift < ±5%
6. **Manual prod-shape check:** `python scripts/test_dcf.py ULTRACEMCO.NS AMBUJACEM.NS ACC.NS SHREECEM.NS JKCEMENT.NS DALBHARAT.NS RAMCOCEM.NS` and confirm bands.
7. **Frontend smoke:** load `/stock/ULTRACEMCO.NS`, `/stock/AMBUJACEM.NS`, `/stock/ACC.NS` in dev; confirm `valuation_method` field surfaces `post_ma_signed_median` or `peer_relative_ev_ebitda` so support can debug if customers ask.

## 8. Risks / open questions for implementer

- **Verify the M&A hypothesis before committing.** Inspect `enriched["fcf_history"]` for ULTRACEMCO/AMBUJA/ACC in cache. If FY24/FY25 FCF is in fact strong and the median is being pulled down by ancient years, the fix shape is "drop pre-regime", not "depress for capex absorption". If both pre- AND post-regime FCFs are depressed, the bug is elsewhere (likely data-pipeline) and approach A won't work — fall to C.
- **revenue_cagr_5y nulls** for AMBUJA/ACC may indicate the upstream `annual_financials` table lacks 5y rows for these tickers post-Adani re-listing. If so, no model fix can produce a 10y signed-median honestly — option C (peer-relative) is the only sound path and option A degrades to C.
- **Peer-cohort drift risk** in option C: if all 4 in-band cement names rally 30% together, the implied "peer median EV/EBITDA" rises and pulls broken-ticker FVs up with the cohort. Cap the peer multiple at the trailing 5y sector median (~14× EV/EBITDA) to prevent late-cycle inflation.
- **AMBUJACEM sector mistag is hardcoded yfinance behaviour.** Once `TICKER_SECTOR_OVERRIDES` is set, verify every downstream consumer (`sector_isolation_check.py`, `update_sector_snapshot.py`, frontend sector facet) sees `"Cement"`. Check that AMBUJACEM doesn't appear under "General/Diversified" anywhere in the snapshot files.
- **PR #314 floor reversion.** Revert ONLY the cement entries in the canary override map. Keep the metals/auto super-cyclical overrides — those are a different problem class.
- **CACHE_VERSION bump invalidates every cached payload.** Schedule overnight rebuild per the established v71/v73/v77/v88/v90 pattern.

## 9. Out of scope

- **Cement EBITDA/tonne forecasting model** (approach B). Defer until peer-relative cohort drift becomes a real signal.
- **Capacity-expansion announcements as a forward growth input** (UltraTech's 2026 200MT target). Outside DCF input shape; would need a separate analyst-input table.
- **Realisation-per-tonne quarterly tracking.** Same — separate data pipeline.
- **The WACC=12.8% vs 9.8% incoherence** across the cement cohort (SHREECEM/ACC vs the rest). Flagged in §1 but not the proximate cause of the FV gap. Separate calibration follow-up.
- **BIRLACORPN, INDIACEM, NUVOCO, HEIDELBERG, ORIENTCEM** — small-cap cement tail. Not probed in §1 (top-5 only per brief). Run them through the canary post-fix; if any flunks, extend `POST_MA_REGIME_CHANGE` or fall through to peer-median.
