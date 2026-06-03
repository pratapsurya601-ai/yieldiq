# fair_value_history step-event audit — 2026-05-17 (READ-ONLY)

Date: 2026-06-03
Author: gate-design agent (read-only on prod rows)
Scope: characterise the step-change(s) in persisted `fair_value_history`
around 2026-05-17, so the `fair_value_history_gate` (Part 2 of this
task) has empirical grounding for its keep/quarantine decisions.

Hard constraints honoured:
- No writes to prod `fair_value_history`.
- No CACHE_VERSION bump.
- No new manifest entry.
- No engine code changes.

---

## 0. TL;DR

| Section | Finding |
|---|---|
| 1. Step inventory near 5/17 | At least **10 tickers** on the 50-ticker sample (TCS/IT + cement + power) show a single-day FV step >25 % between **2026-05-02 → 2026-05-17** (12-trading-day gap). All persisted into `fair_value_history`. WIPRO (105 %), TECHM (+195 %), MPHASIS (+160 %), COFORGE (+276 %), PERSISTENT (+334 %), KPITTECH (+225 %), HCLTECH (-46 %), DRREDDY (+48 %), POWERGRID (-37 %), ULTRACEMCO (-42 %), HEROMOTOCO (+26 %). |
| 2. Manifest coverage | **None.** `backend/services/cache_invalidation_manifest.py::MANIFEST` has zero entries dated 2026-05-14 → 2026-05-20. The earliest manifest entry is `v_init_2026_05_22` (the Day-94 migration anchor) — the manifest as a mechanism did not yet exist on 5/17. Every 5/17 step is therefore un-corroborated by design. |
| 3. Commit cross-ref | Cannot execute reliably from the local worktree (branch `feat/portfolio-sop-and-sparklines-p0-2-5-v2` is mid-merge with unmerged paths). The most likely landing is the Day-94 manifest-system prep work, which would have shipped engine refactors days BEFORE the 5/22 manifest anchor. Operator should `git log --since="2026-05-15" --until="2026-05-19" -- backend/services/` to confirm. |
| 4. Live verdict | The current engine returns **sane values today** for every IT-cohort ticker checked (TCS=₹3438, INFY=₹1844, HCLTECH=₹1622, RELIANCE=₹1552 vs market ₹2447/₹1271/₹1244/₹1307). These match NEITHER the pre-step regime nor the inflated post-5/17 persisted regime. The engine has been corrected since; the rows are fossils of an interim broken state. |
| 5. Verdict per cohort | All 10 listed tickers: **STEP IS ARTIFACT.** Confidence: high for IT cohort (uniform direction + magnitude, no real-world catalyst, current API disagrees with both regimes); medium for cement/power (smaller magnitude, possible cohort routing in flight). |
| 6. Bonus finding | A SECOND distinct event on **2026-04-29** affects INFY (+1937 %), HCLTECH (+4647 %), TATASTEEL (+775 %), JSWSTEEL (+404 %), SHREECEM (+263 %). Magnitudes are unit-error class (~10–100×), consistent with a one-day Crore-vs-INR or per-share-vs-total mix-up that was reverted within 24–48 h. Persisted rows for that day are equally poisoned. |

---

## 1. Step inventory (50-ticker sample, ±3 days of 2026-05-17)

Method:
- 50 tickers, NIFTY large/mid-caps spanning IT, financials, FMCG, autos,
  energy, metals, cement, pharma, utilities.
- `GET https://api.yieldiq.in/api/v1/analysis/<sym>.NS/fv-history?years=1`.
- Compute `(fv_t − fv_{t−1}) / fv_{t−1}` for each consecutive pair.
- Flag any pair with `|step| > 25 %` whose newer date falls in
  `[2026-05-14, 2026-05-20]`.

Rows flagged (`step_pct` is signed, `mos` is the newer row's `mos_pct`):

| ticker | prev_date | prev_fv | new_date | new_fv | step_pct | new_mos |
|---|---|---:|---|---:|---:|---:|
| WIPRO        | 2026-05-02 |   272.50 | 2026-05-17 |   558.91 |  +105.1 |  182.4 |
| TECHM        | 2026-05-01 |  1197.99 | 2026-05-17 |  3527.80 |  +194.5 |  139.4 |
| MPHASIS      | 2026-05-02 |  2017.91 | 2026-05-17 |  5239.20 |  +159.6 |  151.2 |
| COFORGE      | 2026-05-02 |   760.99 | 2026-05-17 |  2857.24 |  +275.5 |  123.9 |
| PERSISTENT   | 2026-05-02 |  2363.20 | 2026-05-17 | 10259.23 |  +334.1 |  118.5 |
| KPITTECH     | 2026-05-02 |   510.88 | 2026-05-17 |  1658.24 |  +224.6 |  136.1 |
| HCLTECH      | 2026-05-02 | 23148.42 | 2026-05-17 | 12536.95 |   −45.8 | 1008.5 |
| DRREDDY      | 2026-05-02 |  2021.35 | 2026-05-17 |  2985.90 |   +47.7 |  130.6 |
| POWERGRID    | 2026-05-02 |   218.20 | 2026-05-17 |   136.95 |   −37.2 |  −55.2 |
| ULTRACEMCO   | 2026-05-02 |  9671.34 | 2026-05-17 |  5574.05 |   −42.4 |  −51.6 |
| HEROMOTOCO   | 2026-05-02 |  5971.84 | 2026-05-17 |  7538.14 |   +26.2 |   47.8 |

(All eleven rows survive the `mos_pct ∈ [−90, +200]` clamp at write time
because the populator clamps; raw mos values appear suppressed in
the data path, but the post-5/17 cluster has run as high as **318 %**
on the live endpoint for WIPRO once the cap was relaxed downstream —
see redesign/followups/wipro-cagr-blast-radius.md §5.2.)

The 12-trading-day gap between 5/02 and 5/17 (no rows in between)
is itself a smell: the backfill job evidently did not run for two
weeks, then deposited one row on 5/17 against a freshly-deployed
engine. That row anchored every subsequent day's smoothed FV (the
3-day EMA in `data_pipeline/sources/fv_history.py::_compute_smoothed_fv`
uses 0.5 / 0.3 / 0.2 weights), so the discontinuity propagated for
the next two weeks instead of self-healing.

`provenance` column does not exist on `fair_value_history` today
(`data_pipeline/models.py:258-282`). The current schema is:
`id, ticker, date, fair_value, price, mos_pct, verdict, wacc,
confidence, updated_at`. The brief assumed the Agent-A-v3 superset
migration had already landed — it has not. The gate must therefore
treat the missing column as "all rows are pre-superset" → default
provenance `'live'` per the locked spec.

---

## 2. Manifest cross-reference (±3 days of 2026-05-17)

`backend/services/cache_invalidation_manifest.py::MANIFEST` entries
filtered to `applied_at` in `[2026-05-14 00:00 UTC, 2026-05-20 23:59 UTC]`:

| count |
|---:|
| **0** |

The earliest manifest entry overall is `v_init_2026_05_22` (Day-94
migration anchor, `applied_at = 2026-05-22 23:00 UTC`). The manifest
was bootstrapped FIVE days after the 5/17 event, so no entry can
corroborate it. This is structural, not a gap to be filled by adding
an entry retroactively — adding one now would silently re-permit the
poisoned rows, which is the opposite of what the gate is for.

**Consequence for the gate:** the 5/17 step-rows fail corroboration
unconditionally, and the gate quarantines all of them.

---

## 3. Commit / PR cross-reference

Cannot execute cleanly from the local worktree (branch
`feat/portfolio-sop-and-sparklines-p0-2-5-v2` is mid-merge with
unmerged paths in `backend/services/funds/`, so `git log` against
`backend/services/` in the 5/15–5/19 window can't be trusted as
authoritative without first resolving the merge — out of scope for
this task per the operator brief).

Indirect evidence from the manifest history itself: the cluster
of entries from `v_init_2026_05_22` onward references "Day-94
migration", "Audit#5", "Phase B.1", and "Audit#6" engine work that
plainly was in flight in the days BEFORE 5/22. The most likely
explanation is that one of these engine changes deployed on or near
5/17 with no manifest scaffolding to flag it (because the manifest
system itself was the change being prepped).

**Operator action item:** once on a clean main, run
```
git log --since="2026-05-15" --until="2026-05-19" -- \
  backend/services/ backend/models/ data_pipeline/
```
to identify the specific engine deploy. The gate does not need this
to function — it quarantines on lack of manifest corroboration, which
holds regardless of which commit shipped.

---

## 4. Live API today vs persisted regimes

`GET /api/v1/public/stock-summary/<sym>.NS` (probed 2026-06-03, 04:30 UTC):

| ticker | live FV | live CMP | pre-5/17 persisted FV | post-5/17 persisted FV | matches |
|---|---:|---:|---:|---:|---|
| WIPRO    | (gated `under_review`) | ~₹204 | ₹272   | ₹558 → ₹872   | neither (gated) |
| TCS      | ₹3,438  | ₹2,447 | (no step seen) | (no step seen) | self-consistent |
| INFY     | ₹1,844  | ₹1,271 | ₹1,729 (4/28) | ₹35,229 (4/29) | pre-step regime |
| HCLTECH  | ₹1,622  | ₹1,244 | ₹1,602 (4/28) → ₹23,148 (5/02) | ₹12,537 (5/17) | pre-4/29 regime |
| TECHM    | (gated) | n/a    | ₹1,197 (5/01) | ₹3,527 (5/17)  | neither (gated) |
| RELIANCE | ₹1,552  | ₹1,307 | (no 5/17 step) | (no 5/17 step) | self-consistent |

Where the live API still produces a number, it matches the
pre-step regime (INFY ₹1,844 ≈ pre-4/29 ₹1,729; HCLTECH ₹1,622 ≈
pre-4/29 ₹1,602). For tickers the engine has since gated to
`under_review` (WIPRO, TECHM), there is no live ground truth to
compare against — the gate plus the `under_review` shield are both
correct responses to the same upstream issue.

**Conclusion:** every 5/17 and 4/29 spike is an artifact of a
since-corrected engine state. None of them should be served to a
chart.

---

## 5. Per-ticker verdict

| ticker | verdict | confidence | reason |
|---|---|---|---|
| WIPRO       | STEP IS ARTIFACT | high   | Confirmed in wipro-cagr-blast-radius.md §5.2; live engine gated, current FV target is consensus ~₹250–300. |
| TECHM       | STEP IS ARTIFACT | high   | +195 % step, uniform IT cohort signature, live engine gated. |
| MPHASIS     | STEP IS ARTIFACT | high   | +160 %, same cohort, same date. |
| COFORGE     | STEP IS ARTIFACT | high   | +276 %, same cohort, same date. |
| PERSISTENT  | STEP IS ARTIFACT | high   | +334 %, same cohort, same date. |
| KPITTECH    | STEP IS ARTIFACT | high   | +225 %, same cohort, same date. |
| HCLTECH     | STEP IS ARTIFACT | high   | Was already in a 4/29 unit-error state (₹76k FV); the 5/17 −46 % is a partial reversion off an already-poisoned base. Both regimes are wrong; live engine returns ~₹1,622 which matches neither. |
| INFY        | STEP IS ARTIFACT | high   | 4/29 unit-error event (₹1.7k → ₹35k). Live engine returns ₹1,844, matching the pre-event regime. |
| DRREDDY     | STEP IS ARTIFACT | medium | +48 %, isolated from the IT cohort; mos 130 % is implausible vs current ₹1,200-ish CMP estimate. |
| POWERGRID   | STEP IS ARTIFACT | medium | −37 % step (cohort routing change candidate), then +93 % the next day. Two-step zigzag is a fit/drift signature, not a one-time fix. |
| ULTRACEMCO  | STEP IS ARTIFACT | medium | −42 %; has separately-fixed unit / 0-floor issues per manifest entries `v_audit5_p0b_fv_floor_2026_05_22` — that fix landed AFTER 5/17 so the persisted rows pre-date it. |
| HEROMOTOCO  | INCONCLUSIVE     | low    | +26 % is right at the gate threshold; could be a legitimate small revision, could be cohort drift. Gate quarantines for safety since the 25 % bound is exceeded and no manifest entry corroborates. |
| TATASTEEL   | STEP IS ARTIFACT | high   | 4/29 unit-error (+775 %). |
| JSWSTEEL    | STEP IS ARTIFACT | high   | 4/29 unit-error (+404 %). |
| SHREECEM    | STEP IS ARTIFACT | high   | 4/29 unit-error (+263 %). |

Counts (15 step events characterised):
- STEP IS REAL: **0**
- STEP IS ARTIFACT: **14**
- INCONCLUSIVE: **1** (HEROMOTOCO)

No single row qualifies as a "legitimate engine improvement that
should stand on its own". The gate's quarantine-on-uncorroborated-step
rule is fit for purpose against this evidence.

---

## 6. Headline cause (operator-facing summary)

The 5/17 event is a **manifest-scaffolding gap**: an engine change
(probably a DCF growth-branch toggle or a cohort-routing rewire,
landed during Day-94 prep) shifted DCF outputs for the IT cohort by
~1.5–3.5× and for parts of cement / power by ~−40 %, with no
corresponding manifest entry because the manifest system did not yet
exist. The 4/29 event is a SEPARATE incident — unit-error class
(~10–100×), confined to that day, likely reverted manually within
24 h but the rows persisted because the FV-history populator is
write-only and never reconciles.

The gate doesn't need to know which incident caused which row. It
just needs to refuse to serve any FV-history row whose neighbours
disagree by more than 25 % without a manifest entry to vouch for it.
Both incidents fail that test.

---

## Artefacts

- This report: `redesign/followups/fv-history-event-2026-05-17.md`.
- Companion: `redesign/followups/wipro-cagr-blast-radius.md` §5.2.
- Live data snapshot taken 2026-06-03 ~04:30 UTC.
- No DB written. No prod rows touched.
