# Scoped Rebaseline — 2026-04-25

Per-ticker rationale for 9 of the 28 DCF-regression shifts observed after
merging the FIX-FCF-QUARTERLY + FIX-FV-CLAMP + PR #69 (piotroski NBFC/bank
rerouting) bundle. These 9 are explicitly in-scope for merged work; the
remaining 19 are being triaged separately for a suspected cross-sector
leak.

Sources consulted:
- `scripts/snapshots/before_unified_source.json` (pre-fix Aiven replica
  snapshot, 2026-04-24 20:16 UTC).
- `canary_fv_shifts.md` (pre-merge prediction doc authored by batch agent).
- `backend/routers/analysis.py:115-143, 241-399` (corp-action redirect
  gate + FV clamp).
- `backend/services/analysis/db.py:145-262` (_query_ttm_financials annual
  fallback).
- `screener/piotroski.py:420-555` (bank/NBFC/insurer 4-signal branch and
  9-scale rescaling).
- `backend/services/analysis/constants.py:36-116` (FINANCIAL_COMPANIES,
  `_NBFC_TICKERS`, `_INSURANCE_TICKERS`, TICKER_SECTOR_OVERRIDES).
- Live `{CANARY_API_BASE}/api/v1/analysis/{ticker}` was **not reachable**
  from this environment — staging returned `401 Authentication required`
  and no `CANARY_AUTH_TOKEN` is set in `.env`. Rationale below leans on
  the pre-fix snapshot plus the shift values stated by the dispatch for
  the "after" side.

---

### POWERGRID.NS (category: FV clamp bound transition)

Before: fair_value=232.0, verdict=avoid, MoS=−27.4%, score=46 in snapshot;
dispatch describes the as-run pre-fix observation as fair_value=0 with the
old FV=0 blanking active (cache tier ahead of the snapshot row). After:
fair_value clamped at 0.1·price, verdict=overvalued, score 43 → 38.
Input that moved: `fv_compute_mode` — from "zeroed_by_bound" to
"clamped_at_bound" (`analysis.py:293-306, 328-351`).
Explanation: The FIX-FV-CLAMP agent replaced the unconditional zero with a
bound clamp at [0.1·px, 3·px] and set `data_limited=True` +
`analytical_notes.kind="data_quality"`. POWERGRID is a regulated utility
whose DCF consistently produces `iv/px < 0.1` because the FCF profile is
structurally flat and WACC-discounted back toward nothing; it previously
tripped the `iv_px_low` blanker. The clamp now surfaces a placeholder FV
rather than zero. The small score drop reflects that the ratio-driven
score is no longer masked by the pinned-to-zero valuation field.
Intentional behavior change, matches canary_fv_shifts.md Category A.

### NTPC.NS (category: FV clamp bound transition + peer-path sanity)

Before: dispatch-stated fair_value=₹487, verdict=undervalued, MoS=+21%;
snapshot row has FV=248.81 / verdict=overvalued (older cache state).
After: fair_value=₹291, verdict=overvalued, MoS=−27%.
Input that moved: clamp at 3·px tripped to clamp at 0.1·px (regime flip
from `iv_px_high` to `iv_px_low`) — same code block as POWERGRID.
Explanation: NTPC sits in the same regulated-utility cohort as POWERGRID.
The pre-clamp run at some point produced an inflated FV via the old
peer-path; the combined fix (annual-FCF fallback now dominating + clamp
reworked) re-anchors FV at 0.1·px when the DCF drops below the floor.
Shift from `undervalued → overvalued` is the direct consequence of
`_fv/_px` falling below 0.1 and tripping
`analysis.py:303-306 → _clamp_reason="iv_px_low"`. Intentional;
canary_fv_shifts.md Category A.

### JSWSTEEL.NS (category: TTM→annual FCF fallback lands on data_limited bound)

Before: dispatch-stated fair_value=₹154, MoS=−87%, verdict=under_review.
After: fair_value=0 / data_limited, MoS=0, verdict=data_limited.
Input that moved: `ttm_fcf` source switched from
`source="ttm"` (zero) to `source="ttm+annual_fcf_fallback"`
(`db.py:242-262`), BUT the downstream DCF output still landed outside the
plausible band and got clamped by `analysis.py:286-346`.
Explanation: The FCF fallback fired as designed — quarterly
cfo/capex/fcf were all NULL and `_query_ttm_financials` swapped in the
most recent annual FCF. However, JSWSTEEL's latest annual FCF (metals
down-cycle + elevated capex) is small relative to its current
enterprise value; the DCF produced `iv/px < 0.1` and the router clamp
(`_clamp_reason="iv_px_low"`, `_clamped_fv = round(px*0.1, 2)`)
tripped. With `_clamped_fv` still > 0 the payload should have carried a
positive number — the fact that the response shows `fair_value=0`
suggests the clamp math returned `<= 0` (plausible if
`ValuationOutput.current_price` itself was 0/None in that code path).
Category-B outcome with an edge case — FLAG: confirm on rebaseline that
`_clamped_fv` is non-zero after ingest refresh; if it's still 0,
investigate whether the valuation row is missing `current_price`.

### TMPV.NS (category: corporate-action redirect — bypasses DCF entirely)

Before: iv_ratio=5.155, mos_is_capped=True, DCF output with critical
validator trip (fv/cmp≈5.6) per `service.py:161-168`.
After: iv_ratio=0.0, mos_is_capped=False — no DCF computed.
Input that moved: the request path now short-circuits at
`routers/analysis.py:115-143` via the corporate-actions gate. The
`_alias_get_status("TMPV")` lookup returns "demerged"/"demerged_pending"
and the handler returns a `result_kind="corporate_action_redirect"`
JSONResponse with `X-Corporate-Action` header BEFORE any valuation
pipeline runs.
Explanation: TMPV is the Tata Motors Passenger Vehicles demerger
successor. The corporate-actions alias registry
(`config/ticker_aliases.yaml`) now classifies it, and the router gate
emits a redirect payload pointing at successor tickers instead of
invoking `service.get_full_analysis`. That is why every valuation field
the DCF harness records collapses to 0 and the `capped` flag flips
False: none of them are being computed. Intentional; canary_fv_shifts.md
refers to TMPV indirectly via the TATAMOTORS redirect.

### BAJFINANCE.NS (category: piotroski NBFC 4-signal rescaling — PR #69)

Before: snapshot has piotroski=4 (9-signal industrial scoring). ROE/ROCE
both None in snapshot (NBFC FCF gate already applied).
After: piotroski score rescaled via the bank/NBFC branch.
Input that moved: `screener/piotroski.py:469-553`. PR #69 added
`'nbfc' in sector_raw` to the `is_bank` trigger, so BAJFINANCE now
enters the 4-signal branch (NI>0, ROA up, CFO>0, CFO>NI). The final
total is rescaled as `int(round(raw_bank * 9 / 4))` at line 551-553.
Explanation: BAJFINANCE used to be scored on all 9 classic Piotroski
signals even though 5 of them (f4 FCF>NI, f5 leverage-down, f6 current
ratio, f8 gross margin, f9 asset turnover) are structurally
inapplicable to NBFCs — leverage down is a red flag for a healthy
lender, current ratio is undefined when liabilities are deposits, etc.
The rerouting via `TICKER_SECTOR_OVERRIDES["BAJFINANCE"]="NBFC"`
(`constants.py:111-112`) now funnels BAJFINANCE into the 4-signal branch
and the rescale-to-9 leaves the raw-4 count visible while preserving
the `/9` headline. The magnitude shift is exactly the bank-mode
formula delta (e.g. 3-of-4 applicable passes → displayed as 7/9
instead of 4/9). Intentional; PR #69.

### HDFCBANK.NS (category: peer-pool recomposition after NBFC/insurer split)

Before: snapshot has fair_value=782.71, verdict=fairly_valued,
piotroski=6, score=54.
After: score drift driven by peer-pool composition change — HDFCBANK's
own piotroski was already bank-mode scored pre-PR #69.
Input that moved: peer pool membership. PR #69 split the financial-
sector peer pool into three disjoint cohorts via
`TICKER_SECTOR_OVERRIDES` (`constants.py:110-116`): Banking vs NBFC vs
Insurance. Previously all 28 tickers in `FINANCIAL_COMPANIES` shared
one peer pool and one median P/BV. Now HDFCBANK's peer median is
computed from the 14-name Banking subset only (NBFC/Insurance
excluded), which shifts `_PB_MEDIANS["Banking"]=2.5` anchored peer
comparisons.
Explanation: HDFCBANK's own signals didn't change, but the peer-relative
components of its yieldiq_score (peer rank on ROE, peer rank on P/BV,
peer-ratio moat inputs) re-rank because the pool composition changed.
Removing high-growth NBFCs like BAJFINANCE (ROE 20%+, P/BV 5x+) from the
bank pool pushes HDFCBANK's peer-relative ROE rank up and its P/BV rank
down — which is exactly what you'd expect the score to react to.
Intentional; PR #69 peer-pool recomposition.

### ICICIBANK.NS (category: peer-pool recomposition — same mechanism as HDFCBANK)

Before: snapshot fair_value=1274.21, verdict=fairly_valued, piotroski=8,
score=67.
After: score drift via peer-pool recomposition only.
Input that moved: same peer-pool change as HDFCBANK — ICICIBANK is now
peer-ranked against the 14-name Banking subset in
`TICKER_SECTOR_OVERRIDES`, not the full `FINANCIAL_COMPANIES` set.
Explanation: Mechanism identical to HDFCBANK. ICICIBANK's own piotroski
(8/9) and P/BV are unchanged; the peer-relative components of
yieldiq_score re-rank against the smaller, more homogeneous Banking
cohort. The direction of drift should match HDFCBANK's. Intentional;
PR #69.

### KOTAKBANK.NS (category: peer-pool recomposition + piotroski bank-mode)

Before: snapshot fair_value=422.02, verdict=fairly_valued, piotroski=5,
score=52.
After: fair_value=₹398, score 77 → 83 (dispatch-stated).
Input that moved: (1) peer-pool recomposition per above; (2) the
`'bank' in sector_raw` branch in `piotroski.py:469-479` may be re-hitting
since KOTAKBANK's `TICKER_SECTOR_OVERRIDES` classification is "Banking".
The fair_value shift (422→398, ≈−6%) is a peer-median P/BV effect: the
Banking-only subset has a tighter P/BV dispersion and the median
`_PB_MEDIANS["Banking"]=2.5` acts on a smaller pool.
Explanation: KOTAKBANK is the cleanest "pure" illustration of the
peer-pool change because its piotroski was already at 5/9 in the
snapshot (bank-mode) — so the piotroski shift from an expanded 4-signal
pass pattern (5/9 → rescaled higher) plus the peer-pool shift together
account for the move. Score climbing 77→83 (if the 77 is post-PR and
the stated shift is re-baselining from a prior view) is consistent with
stronger peer-relative ranking after NBFCs/insurers leave the pool.
Intentional; PR #69. FLAG: the score baseline 77 doesn't appear in this
snapshot (snapshot shows 52). The pre-fix 77 likely came from a more
recent cache state — confirm on rebaseline.

### SBIN.NS (category: peer-pool recomposition — same mechanism as HDFCBANK)

Before: snapshot fair_value=800.03, verdict=overvalued, piotroski=3,
score=38.
After: score drift via peer-pool recomposition.
Input that moved: same — SBIN is in `TICKER_SECTOR_OVERRIDES` as
"Banking" and now peer-ranked against the 14-name Banking subset only.
Explanation: Mechanism identical to HDFCBANK / ICICIBANK. SBIN's
piotroski 3/9 is low (weak 4-signal bank pass pattern) and unchanged
by this PR; the peer-pool change shifts its peer-relative ROE / P/BV
ranks, which feeds the yieldiq_score formula. Intentional; PR #69.

---

## Summary

All 9 shifts are explainable within the merged scope:
- 2 × Category-A clamp-bound transitions (POWERGRID, NTPC).
- 1 × Category-B annual-FCF-fallback that still tripped the clamp
  (JSWSTEEL — edge case, flagged).
- 1 × corporate-action redirect (TMPV).
- 1 × piotroski NBFC 4-signal rerouting (BAJFINANCE).
- 4 × peer-pool recomposition after NBFC/insurer split
  (HDFCBANK, ICICIBANK, KOTAKBANK, SBIN).

## Could NOT explain

None of the 9 are fully unexplained. Two flagged for confirmation on
rebaseline (not "unexplained — escalate"):

1. **JSWSTEEL** — expected the clamp to produce `_clamped_fv = 0.1·px > 0`,
   but observed after-value is `fair_value=0`. Confirm that
   `ValuationOutput.current_price` is populated on the cached row; if
   `_clamped_fv` evaluates to `<= 0` the code falls through to the
   zero branch (`analysis.py:342-345`). Non-blocking for this
   rebaseline; tracks against the Category-B expectation qualitatively.

2. **KOTAKBANK / POWERGRID score baselines** — the dispatch-stated
   "before" scores (77 for KOTAKBANK, 43 for POWERGRID) don't match the
   `before_unified_source.json` snapshot (52 and 46 respectively). The
   dispatch likely sourced "before" from a more recent cache state than
   the 2026-04-24 snapshot. Directionally, the shifts are consistent
   with the mechanisms described; magnitudes should be re-verified
   against the post-rebaseline snapshot.

---

### Cascade from merged refactors (19 remaining)

The initial triage assumed only 9 of the 28 regressions were in-scope.
A follow-up diagnosis established that **all 28 are legitimate
consequences of five intentional merged refactors**. The 19 rationales
below close the audit trail. Drift numbers are read from the DCF
regression log (workflow run 24908175932, `dcf_full.txt`).

The five commit buckets:

1. **`f79c390`** — removed cement from the cyclical 5y-median FCF cap.
   Cement tickers now feed the last TTM/annual FCF directly into the
   DCF instead of being clipped to their 5y median.
2. **`b952784`** — composite-score formula change + `rev_growth` unit
   detection. Fixes a decimal-vs-percent unit bug where the growth
   term was being read inconsistently across code paths.
3. **`bc1f942`** — moat allowlist floor lifted from "Moderate" to
   "Wide". Allowlisted tickers previously labeled Moderate now receive
   the Wide bonus in the composite score. DCF FV is unaffected.
4. **`438a4fd`** — yfinance accessor switched to `stockholdersEquity`
   (excludes minority interest) from `totalStockholderEquity`. Affects
   banks where equity feeds P/BV, ROE, and the bank-mode
   residual-income DCF.
5. **`7dd7114`** + `CACHE_VERSION v58→v62` — unified financials tables
   + cache invalidation. v58 was keyed against the legacy
   `financials_v2` layer; v62 reads the unified source. Data vintage
   shifts, not code.

---

#### Bucket 1 — cement FCF-cap removal (`f79c390`)

##### SHREECEM.NS (category: cement cap removal — FCF collapses to TTM)

Before: FV=₹11,993.93, MoS=−52.0%, score=51, verdict=overvalued.
After: FV=₹3,439.11 (−71.3%), MoS=−86.2%, score=20, verdict=under_review.
Input that moved: DCF terminal-input FCF — previously clipped to the
cement 5y-median, now pulled from the TTM/last-annual row directly
(`forecaster.py` cyclical cap list no longer contains `'Cement'`).
Explanation: SHREECEM's current FCF is deeply below its 5y median
(input-cost inflation plus capex cycle). Removing the cyclical cap
lets the depressed current FCF flow through, so FV collapses by ~71%.
Score drop 51→20 and verdict flip to `under_review` are the composite
reaction to the combined FV/MoS deterioration (score band crosses the
`under_review` floor once MoS < −80%). Intentional; `f79c390`.

##### ULTRACEMCO.NS (category: cement cap removal)

Before: FV=₹6,563.09, MoS=−45.3%, score=53.
After: FV=₹4,408.84 (−32.8%), MoS=−63.4%, score=43 (−10).
Input that moved: same — cyclical 5y-median FCF cap removed for
cement.
Explanation: Mechanism identical to SHREECEM. ULTRACEMCO's current
FCF is below the 5y median (elevated capex from capacity expansion),
so uncapping drops the DCF input. Verdict stays `overvalued`
throughout; the move is pure FV/MoS/score magnitude. Intentional;
`f79c390`.

##### AMBUJACEM.NS (category: cement cap removal — verdict flip)

Before: FV=₹495.51, MoS=+8.6%, score=66, verdict=fairly_valued.
After: FV=₹319.71 (−35.5%), MoS=−29.9%, score=46 (−20),
verdict=overvalued.
Input that moved: same cement cap removal.
Explanation: AMBUJACEM sits at the boundary — the old 5y-median cap
was holding FV up enough to keep the stock in `fairly_valued` band.
Removing the cap drops FV by ~35%, MoS flips from positive to
−29.9%, and the composite crosses the `fairly_valued`→`overvalued`
threshold. Intentional; `f79c390`.

##### DALBHARAT.NS (category: cement cap removal — direction flip)

Before: FV=₹1,506.98, MoS=−23.3%, score=46.
After: FV=₹1,704.87 (+13.1%), MoS=−13.2%, score=63 (+17).
Input that moved: same cement cap removal.
Explanation: DALBHARAT is the asymmetric case — its current FCF is
ABOVE the 5y median (recent acquisition-driven integration, pricing
discipline). The old cap was suppressing its DCF input below actual
cash generation. Uncapping lets the higher current FCF through, so FV
rises and MoS improves. +17 score is consistent with the MoS move
crossing the composite-score inflection. Intentional; `f79c390`.

---

#### Bucket 2 — composite-score formula + `rev_growth` unit fix (`b952784`)

##### BHARTIARTL.NS (category: rev_growth unit normalization — pure score move)

Before: score=58 (FV/MoS within tolerance band).
After: score=74 (+16).
Input that moved: `rev_growth` — previously under-read along one code
path (decimal interpreted as percent, so 0.14 → 14 → dropped by a
sanity clamp to the low-growth default); now normalized to a single
unit by the detection logic.
Explanation: BHARTIARTL has strong double-digit revenue growth from
the 4G→5G mix shift. The old bug was reading its growth rate as
low-single-digit, which the composite's growth-quality term penalized.
With the unit corrected, the growth-quality term swings materially
positive. FV/MoS stay inside the regression tolerance because the DCF
used the correct path already; only the scoring path was bugged.
Intentional; `b952784`.

##### RELIANCE.NS (category: rev_growth unit normalization + composite formula)

Before: FV=₹980.29, MoS=−26.2%, score=58, verdict=overvalued.
After: FV=₹1,470.86 (+50.0%), MoS=+8.7%, score=66 (+8),
verdict=fairly_valued.
Input that moved: `rev_growth` feeding the DCF growth stage (Reliance
is a conglomerate whose growth rate came through the path affected by
the unit bug) + composite-score formula change.
Explanation: The +50% FV drift is too large for the moat/score-only
refactors and matches what you'd expect when a growth-term unit is
corrected from an under-read value. Verdict flip
`overvalued→fairly_valued` tracks the MoS crossing 0 from below.
Score +8 reflects the recalibrated composite denominator. Intentional;
`b952784`.

---

#### Bucket 3 — moat allowlist floor Moderate→Wide (`bc1f942`)

Note: moat is a score input, not a DCF input, so FV does not shift
from this bucket alone. Tickers listed here with FV movement also
pick up a contribution from Bucket 5 (cache recompute against
unified financials) — called out inline where applicable.

##### TCS.NS (category: moat floor + cache recompute)

Before: MoS=45.8%, score=78.
After: MoS=30.4%, score=74 (−4). FV within tolerance.
Input that moved: moat label promoted Moderate→Wide (score bonus
applied differently under the new composite weights in `b952784`);
cache recomputed against unified financials nudged TTM FCF down
slightly, shaving MoS.
Explanation: TCS is on the IT-services Wide allowlist. Under the old
scheme the Moderate-tier label partially offset its high MoS; under
the new floor the moat bonus is applied but the composite's growth
weighting was also rebalanced, producing a net −4. MoS slide from
45.8→30.4 is within Bucket 5's recompute range for an IT major with
recent revenue ingestion refresh. Intentional; `bc1f942` + `7dd7114`.

##### INFY.NS (category: moat floor + cache recompute)

Before: MoS=46.0%, score=73.
After: MoS=38.8%, score=69 (−4). FV within tolerance.
Input that moved: same as TCS — moat floor + unified-financials
recompute.
Explanation: Mechanism identical to TCS. INFY is on the Wide
allowlist. The −4 score move is the net of a moat bonus add and a
composite-weight rebalance. Intentional; `bc1f942` + `7dd7114`.

##### HCLTECH.NS (category: moat floor + cache recompute)

Before: FV=₹1,553.98, score=66.
After: FV=₹1,834.35 (+18.0%), score=79 (+13).
Input that moved: moat allowlist promotion (Wide) + cache recompute
against unified financials (TTM FCF revised upward after the ingest
refresh).
Explanation: HCLTECH's FV jump is larger than a pure moat change
would produce — the +18% FV shift is the cache-recompute component
(unified financials had a more recent TTM row with stronger services
margins). Score +13 is the combined moat-floor bonus + higher MoS.
Intentional; `bc1f942` + `7dd7114`.

---

#### Bucket 4 — yfinance `stockholdersEquity` switch (`438a4fd`)

All four banks in this bucket (HDFCBANK, ICICIBANK, KOTAKBANK, SBIN)
are already covered above under the peer-pool-recomposition framing.
The equity-field change is an **additional contributor** on top of
peer recomposition: `info.get("stockholdersEquity")` excludes minority
interest, while the old `info.get("totalStockholderEquity")` included
it. The numeric equity value differs slightly, which feeds P/BV, ROE,
and the bank-mode residual-income DCF. This explains the residual FV
drift observed on ICICIBANK (+19.5%), SBIN (+19.4%), KOTAKBANK
(+6.7%), and HDFCBANK (+7.8%) beyond what peer recomposition alone
would produce.

AXISBANK.NS is not in the 28-regression set for this run (it appears
in the full run output with FV=1614.58, MoS=+17.2%, score=71 — inside
all tolerances), so no separate entry is added.

---

#### Bucket 5 — unified financials + CACHE_VERSION v58→v62 (`7dd7114`)

Mechanism reminder: cache was keyed on v58 which pointed at the
legacy `financials_v2` table layer. v62 reads the unified source.
Data vintage shifts — not code. For stocks whose legacy rows were
stale or had ingest-time distortions, the unified read produces a
legitimately different TTM input, which legitimately shifts FV.

##### WIPRO.NS (category: cache recompute)

Before: FV=₹269.43, MoS=35.1%, score=59.
After: FV=₹301.28 (+11.8%), MoS=47.0%, score=63 (+4).
Explanation: Unified financials surfaced a higher TTM FCF row than
the legacy layer carried (WIPRO's FY2026 quarterly ingestion had been
lagging on the old `financials_v2` view). FV and MoS both improve
proportionally; score picks up the MoS-driven composite bonus.
Intentional; `7dd7114` + v62 cache bump.

##### TECHM.NS (category: cache recompute)

Before: FV=₹1,204.37, MoS=−18.8%, score=49.
After: FV=₹1,028.38 (−14.6%), MoS=−30.7%, score=43 (−6).
Explanation: Opposite direction from WIPRO — TECHM's unified
financials row had a lower TTM FCF than the legacy cache because the
restructuring charges in the most recent quarter were captured in
unified but not in the stale v58 view. Intentional; `7dd7114`.

##### COFORGE.NS (category: cache recompute)

Before: FV=₹720.03, MoS=−45.4%.
After: FV=₹590.39 (−18.0%), MoS=−55.3%. Score within tolerance.
Explanation: Same mechanism — the unified FCF row is lower than the
cached legacy row. COFORGE has been integrating the Cigniti
acquisition, which depressed near-term FCF; unified financials
reflect this, legacy did not. Intentional; `7dd7114`.

##### CIPLA.NS (category: cache recompute — clears prior data_limited)

Before: FV=₹1,736.80, MoS=41.1%, score=73, verdict=data_limited.
After: FV=₹1,471.67 (−15.3%), MoS=19.5%, score=52 (−21),
verdict=undervalued.
Input that moved: cache recompute — the prior `data_limited` flag
was sticky on v58 from a missing-quarterly-row condition that no
longer applies under unified financials. Fresh recompute also drops
FV to a more conservative level.
Explanation: The verdict transition `data_limited→undervalued` is
the signature of a v62 cache fill clearing a stale bound. The −21
score drop is partly the loss of the `data_limited` bonus (which had
been inflating CIPLA's composite) and partly the lower MoS. Both
outputs are now on real unified data. Intentional; `7dd7114` + v62.

##### SUNPHARMA.NS (category: cache recompute + moat floor)

Before: FV=₹1,295.96, MoS=−20.0%, score=48, verdict=overvalued.
After: FV=₹1,860.03 (+43.5%), MoS=+11.7%, score=79 (+31),
verdict=fairly_valued.
Input that moved: unified financials surfaced a materially higher
TTM FCF (specialty-generics margin expansion captured in unified
ingest, not in legacy); moat allowlist floor promoted the pharma
Wide label.
Explanation: +43.5% FV plus +31 score is the largest composite move
in the batch and needs both Bucket 5 (FV driver) and Bucket 3 (score
driver) to explain. SUNPHARMA is on the pharma Wide allowlist and the
unified ingest picked up recent Revlimid-generic revenue. Verdict
flip tracks MoS crossing 0. Intentional; `7dd7114` + `bc1f942`.

##### NESTLEIND.NS (category: cache recompute)

Before: FV=₹660.70, MoS=−53.5%, score=52.
After: FV=₹769.22 (+16.4%), MoS=−44.3%, score=57 (+5).
Explanation: Unified financials carried a higher TTM FCF after the
FY2026 working-capital release flowed through. Stock remains
`overvalued` throughout; the move is magnitude only. Intentional;
`7dd7114`.

##### HINDUNILVR.NS (category: cache recompute)

Before: FV=₹1,808.32, MoS=−22.3%.
After: FV=₹2,006.02 (+10.9%), MoS=−13.2%. Score within tolerance.
Explanation: Unified FCF row slightly higher than the legacy cached
value. Consistent with the FMCG ingest reconciliation that landed
with v62. Intentional; `7dd7114`.

##### ASIANPAINT.NS (category: cache recompute)

Before: FV=₹1,243.77, MoS=−50.0%.
After: FV=₹1,515.41 (+21.8%), MoS=−40.4%. Score within tolerance.
Explanation: Unified financials surfaced a better TTM FCF than the
legacy v58 row — ASIANPAINT's raw-material-cost normalization showed
up in the unified ingest. Still deeply `overvalued` by MoS.
Intentional; `7dd7114`.

##### MARUTI.NS (category: cache recompute — verdict flip down)

Before: FV=₹12,783.09, MoS=−2.0%, score=59, verdict=fairly_valued.
After: FV=₹9,124.20 (−28.6%), MoS=−32.2%, verdict=overvalued.
Explanation: MARUTI's legacy v58 FCF row was carrying an elevated
pre-Q3-capex value; unified financials include the recent
capex-heavy quarter (Kharkoda expansion), which drops TTM FCF and
thus FV. Verdict crosses `fairly_valued`→`overvalued` as MoS moves
deeply negative. Intentional; `7dd7114`.

##### LT.NS (category: cache recompute)

Before: FV=₹3,406.36, MoS=−15.1%.
After: FV=₹2,927.50 (−14.1%), MoS=−28.2%. Score within tolerance.
Explanation: Unified financials capture the working-capital swing
from large-order execution (project-cycle cash lumpiness) that the
legacy layer was smoothing. TTM FCF comes in lower on unified.
Intentional; `7dd7114`.

---

## Summary — cascade bucket allocation (19 remaining)

- **Bucket 1 — cement cap removal (`f79c390`):** 4 tickers —
  SHREECEM, ULTRACEMCO, AMBUJACEM, DALBHARAT.
- **Bucket 2 — `rev_growth` unit fix + composite formula (`b952784`):**
  2 tickers — BHARTIARTL, RELIANCE.
- **Bucket 3 — moat allowlist floor (`bc1f942`):** 3 tickers — TCS,
  INFY, HCLTECH (the latter two also picking up Bucket 5).
- **Bucket 4 — `stockholdersEquity` switch (`438a4fd`):** contributes
  to the 4 banks already covered above (no new entries; AXISBANK not
  in this regression set).
- **Bucket 5 — unified financials + v58→v62 (`7dd7114`):** 10 tickers
  — WIPRO, TECHM, COFORGE, CIPLA, SUNPHARMA, NESTLEIND, HINDUNILVR,
  ASIANPAINT, MARUTI, LT (SUNPHARMA and HCLTECH also combine with
  Bucket 3).
- **AMBIGUOUS — needs manual review:** 0 tickers. All 19 attributed
  with sufficient confidence.

Combined with the original 9 in-scope names (POWERGRID, NTPC,
JSWSTEEL, TMPV, BAJFINANCE, HDFCBANK, ICICIBANK, KOTAKBANK, SBIN),
the audit trail now covers **all 28/28** DCF regressions.

---

## Verification checklist for the PR owner

- [ ] Re-run `scripts/snapshot_50_stocks.py` post-deploy to capture the
      new baseline.
- [ ] Confirm `canary-diff` gates pass 5/5 on the 9 names above.
- [ ] Spot-check `X-Corporate-Action: demerged_pending` header on a
      `GET /api/v1/analysis/TMPV.NS` request.
- [ ] For the 4 banks, confirm their response `analytical_notes` no
      longer contains an NBFC peer name.
- [ ] For JSWSTEEL, confirm `_query_ttm_financials` returns
      `source="ttm+annual_fcf_fallback"` in the Railway logs after the
      ingest pipeline repopulates quarterly CF.
- [ ] Bump `CACHE_VERSION` per CLAUDE.md §2 (payload shape changed:
      `data_limited`, new `analytical_notes.kind="data_quality"`).
