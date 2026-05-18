# HDFC merger growth normalization — design doc

**Status:** Draft (design only — no code changes proposed in this PR)
**Author:** YieldIQ data-quality
**Date:** 2026-05-18
**Related:** `backend/services/corporate_actions_service.py` (Phase-A skeleton),
`db/migrations/012_corporate_actions_structural.sql`,
`data_pipeline/migrations/041_corporate_actions_structural.sql`,
`screener/piotroski.py` (`RECENT_MERGER_BANKS`),
`backend/services/analysis/constants.py` (`TOP_PRIVATE_BANKS`)

---

## 0. TL;DR — the fix is already half-built

This is **not a green-field design**. The corporate-actions structural-overlay
plumbing is already in the repo:

* DDL migrations (010 quality-rank, 012/041 structural columns) are merged.
* `backend/services/corporate_actions_service.py` exists as a Phase-A
  **skeleton**: `STRUCTURAL_ACTION_TYPES` (MERGER / REVERSE_MERGER / DEMERGER /
  SCHEME_OF_ARRANGEMENT / MATERIAL_ACQUISITION), `get_actions()`,
  `has_structural_break()`, and a stubbed `compute_cagr_structural_aware()`
  that today always falls through to plain `ratios_service.compute_revenue_cagr`.
* The skeleton header explicitly says: *"As a result, the public methods here
  are DESIGNED to be safe no-ops until Phase B lands seed data."*

So this doc is **not proposing a new mechanism**. It is proposing:

1. **Land Phase B** (seed structural rows for HDFCBANK + 4 companion banks).
2. **Land Phase C** (wire `compute_cagr_structural_aware()` into the
   analysis pipeline call-site at `backend/services/analysis/service.py:2062`,
   replacing the bare `_rcagr(_rev_series, 3/5)` calls).
3. **Implement the truncation branch** inside `compute_cagr_structural_aware()`
   that the Phase-A docstring already reserves.

The doc that the Phase-A source-comments reference
(`docs/design/corporate-actions-overlay.md`) is **missing from main** — it
lives only on the unmerged branch `feat/corporate-actions-overlay-phase-a-ddl`.
This doc supersedes / re-grounds it for the HDFCBANK use case.

---

## 1. Failure trace

### 1.1 Production symptom

```bash
$ curl -s https://api.yieldiq.in/api/v1/public/stock-summary/HDFCBANK.NS
```

Relevant fields (2026-05-18 fetch):

| Field              | Value         |
| ------------------ | ------------- |
| `revenue_cagr_3y`  | **0.3011** (30.1%) |
| `revenue_cagr_5y`  | `null`        |
| `roe`              | 8.77          |
| `asset_turnover`   | 0.08          |
| `piotroski`        | 6             |
| `fair_value`       | 805.56        |
| `valuation_model`  | `pb_ratio`    |

Implied 3y revenue CAGR of **30.1%** for the largest Indian private bank is
not credible. Consensus organic growth for HDFCBANK over FY22→FY25 is
~10–12%. The `revenue_cagr_5y` is `null` because the merger row breaks the
log-linear CAGR window cleanly enough that the `±50%` `_sanitize_cagr` clamp
in `analysis/service.py` rejects the 5y but lets the 3y through.

### 1.2 Where the bump enters the series

The merger closed **2023-07-01**. HDFC Bank's reported revenue series
(income_df, oldest→newest, ₹ Cr, rounded):

| FY     | Total income | YoY     | Comment                                  |
| ------ | ------------ | ------- | ---------------------------------------- |
| FY21   | ~146,000     | —       | pre-merger                               |
| FY22   | ~157,000     | +7.5%   | pre-merger                               |
| FY23   | ~204,000     | +29.9%  | pre-merger (Q4 FY23 ramp; merger pending)|
| FY24   | ~407,000     | **+99%**| **merger absorbed mid-year; HDFC Ltd's interest income from housing book consolidated** |
| FY25   | ~474,000     | +16%    | first clean post-merger comp             |

3y CAGR(FY22 → FY25) = `(474 / 157) ^ (1/3) − 1 ≈ 0.444` — actually higher
than the 0.301 the API reports, which means our pipeline is using
**(FY22 → FY24)** as the 3y window, not (FY22 → FY25). Either way, the
endpoint contains the merger discontinuity, and the CAGR is meaningless.

### 1.3 Why the sanity-clamp didn't catch it

`backend/services/analysis/service.py:2073` — `_sanitize_cagr` rejects
`abs(CAGR) > 0.50`. The reported 0.301 is well inside the clamp. The clamp
was tuned for **HCLTECH-style data artifacts** (-75% bogus CAGR), not for
real-but-misleading merger growth.

### 1.4 Why the existing Piotroski/Bellwether guards don't help

* `RECENT_MERGER_BANKS` (`screener/piotroski.py:62`) — only neutralizes
  Piotroski f3 (ROA improving) and f7 (no dilution). Doesn't touch CAGR.
* `TOP_PRIVATE_BANKS` (`constants.py:407`) — only used by:
  (a) the null-CAGR bellwether exemption (not relevant — CAGR is non-null),
  (b) the P/B fair-value bump factor (downstream of growth).
* `compute_cagr_structural_aware()` — exists, but Phase-A no-op.

The DCF / fair-value path for HDFCBANK currently uses `pb_ratio`
(`valuation_model: "pb_ratio"`) which masks part of the damage, but
`revenue_cagr_3y` is **also surfaced directly** to:

* hex-axis GROWTH score (`analysis/hex_axes.py:262`)
* narrative-blurb generator (`analysis/narrative.py:62`)
* downstream peer-comparison ranking

So the 30% number is visibly wrong on the product surface even when DCF
isn't the active model.

---

## 2. Root cause classification

This is **both** a data-quality issue **and** a model-calibration issue, but
the cleaner framing is: **the reported FY24 income figure is correct as
reported by the company, but it is not comparable to FY22/FY23 on an
organic basis.** Any growth statistic computed across the merger date is
arithmetically valid and economically meaningless.

Conclusion: this is a **structural-break problem**, not a bad-data
problem. The cure is to make the pipeline merger-aware, not to mutate
the underlying financials table.

This is exactly the framing the existing `corporate_actions_service.py`
Phase-A skeleton uses (`STRUCTURAL_ACTION_TYPES`, `has_structural_break`).

---

## 3. Three candidate fixes

### A. Re-stated financials (manual pro-forma)

Operator enters combined HDFC+HDFCBANK pro-forma FY22/FY23 rows so YoY
normalizes naturally.

* **Pros:** most economically faithful; works for every downstream metric
  (revenue, PAT, ROA, asset_turnover) without per-metric branching.
* **Cons:** highest operator burden; pro-forma figures must be sourced
  from the merger scheme docs / investor presentations and re-validated
  every annual filing cycle; doesn't generalize cheaply to the next
  M&A event; one bad pro-forma row poisons every dependent ratio with
  no audit trail.

### B. Merger-aware growth clamp (post-break truncation)

For tickers with a `STRUCTURAL_ACTION_TYPES` row in `corporate_actions`
within the trailing CAGR window, truncate the input series to the
post-break window before computing CAGR. If post-break window has fewer
than 2 years, return `None` (let `_sanitize_cagr` / null-CAGR gate handle
display).

* **Pros:** zero operator burden once the structural row is seeded;
  generalizes to every M&A event automatically (one row per event);
  Phase-A skeleton already wired exactly for this; transparent to the
  user via a `series_truncated_at` audit-trail field; clean fallback
  (plain CAGR) when no structural row exists.
* **Cons:** until ~3 years post-merger HDFCBANK will have `revenue_cagr_3y`
  = `None` (only FY24 and FY25 available post-2023-07 break — 1y growth,
  not enough for 3y CAGR). This is **correct** but the UI must render
  `—` and the hex GROWTH axis needs a fallback (industry-median).

### C. Skip merger-year in CAGR window

Same as (B) but instead of truncating to post-break, **drop** the
merger fiscal year and compute CAGR across the gap (e.g. FY22 → FY25,
3y span, log-linear).

* **Pros:** preserves a 3y CAGR number; no `None` regime.
* **Cons:** silently spans the discontinuity — FY25 includes the merged
  asset base, FY22 doesn't, so the resulting CAGR still encodes ~half
  the merger bump. Mathematically dishonest. Hard to explain in the
  UI's "how is this computed" tooltip.

---

## 4. Recommendation — Approach **B** (post-break truncation)

Confidence: **high**.

Reasons:

1. **It is the design the codebase already committed to.** The
   Phase-A skeleton's docstring literally says *"Phase C will branch
   here on the truncation logic"* — implementing (B) is finishing
   what's started, not picking a new direction.
2. **Lowest operator burden of the three.** One seed row per merger,
   sourced from already-existing curation in
   `screener/piotroski.py:RECENT_MERGER_BANKS`.
3. **Generalizes.** When the next M&A event hits (ICICI, KOTAK, anyone
   doing a scheme-of-arrangement), one INSERT into `corporate_actions`
   is all that's needed.
4. **The `None`-during-grace-period failure mode is acceptable** because:
   * `_sanitize_cagr` already returns `None` for HDFCBANK's 5y CAGR;
     the product handles `None` gracefully today.
   * The null-CAGR-gate bellwether exemption
     (`analysis/service.py:2090`) already shields HDFCBANK / ICICIBANK
     / KOTAKBANK / AXISBANK from the `data_limited` verdict-flip.
   * The hex GROWTH axis can fall back to **sector-median revenue
     growth** for the grace window — that's a one-line change in
     `hex_axes.py:262`.

(A) is rejected on operator-burden grounds: it would require entering
~12 line items per merger and re-validating with each annual filing.
(C) is rejected because it's quietly dishonest — and the methodology
page is public, so we have to be able to explain the formula.

---

## 5. Companion banks (apply same fix)

Seed `corporate_actions` rows of `action_type='MERGER'` (or
`REVERSE_MERGER` / `SCHEME_OF_ARRANGEMENT` where appropriate) for:

| Ticker        | Event                                  | Ex-date / close   | action_type            |
| ------------- | -------------------------------------- | ----------------- | ---------------------- |
| HDFCBANK      | HDFC Ltd parent absorbed                | 2023-07-01        | REVERSE_MERGER         |
| AXISBANK      | Citi India consumer-banking acquisition | 2023-03-01        | MATERIAL_ACQUISITION   |
| INDUSINDBK    | Bharat Financial Inclusion merger       | 2024-Q1           | MERGER                 |
| IDFCFIRSTB    | IDFC Ltd reverse merger into IDFC First | 2024-Q4           | REVERSE_MERGER         |
| KOTAKBANK     | ING Vysya merger                        | 2015-04-01        | MERGER                 |

KOTAKBANK is **outside** the 3y CAGR window today (10+ years post-merger)
so the structural row is informational only — it should not affect
`compute_cagr_structural_aware()` because `has_structural_break(window_years=3)`
filters by ex_date. We seed it anyway for completeness and for
future analytical (5y / 10y) use.

The set of tickers to seed is exactly `RECENT_MERGER_BANKS` ∪ `{KOTAKBANK}`.
Phase B should also remove the curated `RECENT_MERGER_BANKS` set in
`piotroski.py` in favour of a query against `corporate_actions` — but
that's a follow-up cleanup, not part of the growth-normalization fix.

---

## 6. Acceptance criteria

1. `revenue_cagr_3y` for HDFCBANK falls in `[0.08, 0.14]` band **OR**
   returns `None` (acceptable interim state during the 3y post-merger
   grace window — see §4 footnote on null handling).
2. Same applies to `revenue_cagr_3y` for AXISBANK, INDUSINDBK,
   IDFCFIRSTB (each within their own grace window from their own
   merger date).
3. KOTAKBANK `revenue_cagr_3y` **unchanged** (merger outside window —
   regression guard that the gate doesn't over-fire).
4. Canary-diff (`scripts/canary_diff.py`) shows **no FV shift > 15%**
   on any of the 50 canary stocks except those explicitly listed in
   the PR description. Per CLAUDE.md rule 2 a before/after snapshot is
   mandatory.
5. Hex GROWTH score for HDFCBANK is not `null` after the fix — falls
   back to sector-median when raw CAGR is `None`.
6. `RECENT_MERGER_BANKS` Piotroski neutralization continues to fire
   (regression guard: don't break Phase-A behaviour).

---

## 7. Implementation surface

### 7.1 Files

| File                                                              | Change                                                                                                             | Est. LOC |
| ----------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------ | -------- |
| `data_pipeline/migrations/042_seed_structural_mergers.sql` (new)  | INSERT rows for 5 tickers (HDFCBANK, AXISBANK, INDUSINDBK, IDFCFIRSTB, KOTAKBANK). Idempotent (`ON CONFLICT DO NOTHING`). | ~40      |
| `db/migrations/013_seed_structural_mergers.sql` (new mirror)      | Same content; the repo keeps the two migration trees in sync (see `db/migrations/012_*.sql` header comment).        | ~40      |
| `backend/services/corporate_actions_service.py`                   | Flesh out `compute_cagr_structural_aware()` truncation branch (currently the docstring's reserved `# Phase C` slot). Needs the structural ex_date → fiscal-year mapping helper. | ~60      |
| `backend/services/analysis/service.py` (~line 2062)               | Replace `_rcagr(_rev_series, 3)` / `_rcagr(_rev_series, 5)` with `compute_cagr_structural_aware(ticker, "revenue", 3, _rev_series)`. | ~6       |
| `backend/services/analysis/hex_axes.py` (~line 262)               | Sector-median fallback for GROWTH axis when `revenue_cagr_3y` is `None`. | ~15      |
| `scripts/test_dcf.py`                                              | Add HDFCBANK + AXISBANK fixtures asserting CAGR in [0.08, 0.14] or `None`. | ~20      |
| `tests/services/test_corporate_actions_service.py`                 | New unit tests for the truncation branch (in/out of window, no-rows fallback). | ~80      |
| `docs/design/corporate-actions-overlay.md`                         | Re-land the missing Phase-A design doc (currently only on the unmerged feature branch) and append a Phase-B section pointing at this doc. | ~40      |
| `CACHE_VERSION` bump                                               | Required because HDFCBANK / AXISBANK / INDUSINDBK / IDFCFIRSTB cached payloads now diverge. Follow CLAUDE.md rule 2 (before/after snapshot mandatory). | 1        |

### 7.2 PR sizing

Recommend splitting into **two PRs** per the project's PR-ladder
convention:

* **PR-1 — Phase-B seed** (`migrations/042` + `db/migrations/013` +
  the missing design doc re-land). DDL/data only; zero behaviour
  change; canary-diff must be **bit-identical**. ~120 LOC.
* **PR-2 — Phase-C wire-in** (`corporate_actions_service.py` truncation
  branch + `analysis/service.py` call-site swap + hex_axes fallback +
  tests + CACHE_VERSION bump). ~180 LOC. This is the PR where
  HDFCBANK's 30% CAGR becomes 10-12% (or `None`) and where the canary
  before/after snapshot is non-trivial.

Total est. **~300 LOC across 2 PRs**.

### 7.3 Out of scope for this fix

* DCF terminal-growth / fade-curve calibration for banks (separate
  doc: `bank-equity-source-fix.md`).
* Removing the `RECENT_MERGER_BANKS` literal in `piotroski.py` in
  favour of a `corporate_actions` query — cleanup follow-up, schedule
  after PR-2 lands and bakes for 7 nightly canary cycles.
* PAT / EBITDA / ROA CAGR — same `compute_cagr_structural_aware`
  primitive applies, but the call-sites are different and each needs
  its own canary review. File as follow-ups; the `field` parameter
  in the Phase-A signature is already reserved for this.

---

## 8. Open questions

1. **Fiscal-year vs calendar-year mapping for the structural cutoff.**
   The HDFC merger closed 2023-07-01 — that's **mid-FY24** in Indian
   fiscal-year (Apr-Mar) terms. Truncation must drop FY24 entirely
   (first comparable post-merger year is FY25), not just everything
   after 2023-07-01. The Phase-C helper needs an explicit fiscal-year
   resolver, not naive `ex_date.year`.

2. **What happens during the 1-year window** when HDFCBANK only has
   FY25 post-merger (CAGR mathematically impossible — needs ≥ 2 data
   points)? Current proposal: return `None`, let the bellwether
   exemption hold the verdict, fall back to sector-median for hex.
   Confirm this is acceptable UX before PR-2.

3. **Does `MATERIAL_ACQUISITION` (AXISBANK / Citi) really warrant
   truncation**, or is it small enough to skip? Citi consumer book
   added ~3% to Axis's loan book — a real but sub-structural bump.
   Recommend seeding it as `MATERIAL_ACQUISITION` and letting Phase-C
   decide per-action-type whether to truncate. The current
   `STRUCTURAL_ACTION_TYPES` set treats all 5 types equivalently —
   may want a per-type policy table in Phase C.
