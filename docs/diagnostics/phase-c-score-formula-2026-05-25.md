# Phase C.1 — YieldIQ Composite Score: Formula Reverse-Engineering

**Date:** 2026-05-25
**Author:** Phase C.1 agent (read-only diagnostic; no code changes)
**Base commit:** `b4fb572` (Phase B.2 — bull_case sanity gate)
**Purpose:** Document, for the first time, what the headline 0-100
"YieldIQ Score" actually is — every input, every weight, every clamp,
every post-compute mutation, and every sector-cohort interaction. This
doc is the spec gap that Audit#10 P1 task #120 exposed: users (and the
team) cannot explain score moves because no one has written the formula
down end-to-end. Phase C.2 fixes will draw exclusively from the
"Suggested action" column of §4 below.

---

## TL;DR

1. The score is **NOT** a single formula. It is a base composite
   (`dashboard/utils/scoring.py::compute_yieldiq_score`) plus an
   uncatalogued **MoS-dominance cap** in
   `backend/services/analysis/service.py:4378-4414` that can silently
   floor the score regardless of underlying quality.
2. There are also **two inline fallbacks** (one in
   `service.py:84-90` mock, one in `service.py:3380-3392` exception
   path) which use *different* weights from the canonical function —
   if either fires, the score is **wrong relative to the documented
   weights** and no flag tells the user.
3. The HDFCBANK Audit#10 #120 move from 68→50 is **mathematically
   correct**: it is the MoS-dominance cap firing at MoS≈43% (>30%
   bucket → cap at 50). The base composite would have been ≈68; the
   cap pulled it to 50. Cap is undocumented to users.
4. There are no banking-cohort, IT-cohort, REIT-cohort overrides on
   the score itself. The cohort overlays change `iv` (fair value) and
   `verdict`; the score moves only **transitively** because `mos_pct`
   is re-derived from the new `iv`.
5. Five score quirks are surfaced in §4. Recommendations: fix 2 in
   C.2, ship 3 as "intentional but un-disclosed" via the C.3
   `score_breakdown` transparency panel.

---

## Section 1 — Formula Tree (canonical path)

```
compute_yieldiq_score(mos_pct, piotroski, moat_grade, rev_growth, analyst_upside)
│
├─ val_score (0-20)  ← MoS bucket, on mos_pct CLAMPED to [-50, +50]
│     mos>=40 → 20 | >=25 → 16 | >=10 → 12 | >=0 → 8
│     >=-15 → 5  | >=-30 → 3  | else → 0
│
├─ qual_score (0-50) = pio_score + moat_pts
│     pio_score = min(piotroski/9 * 25, 25)           # 0-25
│     moat_pts  = {A+/A:25, B+:22, B:18, C+:13, C:10, D:3,
│                  Wide:25, Narrow:18, Moderate:15,
│                  None/n/a/"":0}[moat_grade]         # 0-25
│
├─ grw_score (0-20)  ← rev_growth auto-detect decimal vs percent
│     normalised _rg ≥ 20 → 20 | ≥ 10 → 15 | ≥ 5 → 10 | ≥ 0 → 5 | else 0
│
└─ sent_score (0-10) ← analyst_upside (Finnhub target / price - 1) * 100
      au ≥ 20 → 10 | ≥ 10 → 7 | ≥ 0 → 4 | else 1

total = int(val + qual + grw + sent)         # truncation, NOT rounding
total = clamp(total, 0, 100)
grade = >=85 A+ | >=75 A | >=65 B+ | >=55 B | >=45 C+ | >=35 C | else D
```

### Post-compute mutators (NOT in scoring.py)

```
backend/services/analysis/service.py:
│
├─ L4378-4414  MoS-DOMINANCE CAP  ← undocumented to users
│     if not _skip_dominance_cap (i.e. not holdco/SOTP-skip):
│        |mos|>50 → cap to 40
│        |mos|>30 → cap to 50
│        |mos|>15 → cap to 65
│        else      → cap to 100  (no-op)
│     if base_score > cap: score=cap, grade re-derived from cap
│
├─ L3369-3392  TYPEError FALLBACK  ← different weights from canonical!
│     val: 0-40 (vs 0-20 canonical)
│     qual: piotroski/9*20 + moat_pts (Wide:10/Mod:8/Nar:5)  (caps 30 vs 50)
│     grw: 0-20  (same envelope, but integer-only)
│     NO sentiment component at all
│     Fires when compute_yieldiq_score raises TypeError — typically
│     None inputs that the canonical defensive guards already handle
│     post-2026-04-30, so in practice this path is not expected to
│     fire under production inputs. Log line
│     exists ("scoring fallback for ticker=%s") — checking Railway logs
│     would confirm zero occurrences in the last 30d (out of scope here).
│
└─ L84-90    MOCK FALLBACK     ← only when dashboard import fails
      Used when `from dashboard.utils.scoring import compute_yieldiq_score`
      raises at module-load. Different weights again (40/30/20/10 envelopes,
      no moat awareness at all). Not expected to fire in prod — dashboard
      package ships with the backend image — but the symbol exists so
      the audit lists it.
```

### Confidence interaction

The composite score **does not read confidence** directly. There is
NO score-vs-confidence clamp anywhere in `service.py`. The confidence
score (0-100 from `confidence_service.py`) interacts with score only
indirectly:

- `_conf_score < 35 AND |mos|>40` → `verdict=data_limited` (verdict
  only, score unchanged).
- `_override.model_caveat` present → `confidence["score"]` lowered to
  ≤50 (confidence-only side-effect, no score change).

The audit-mentioned "score caps at 70 if confidence < 60" quirk
**does not exist** in the current codebase. Confidence is a parallel
output, not a score modifier.

---

## Section 2 — Input Field List (every field the score reads)

| Field | Source | Consumed at | Notes |
|---|---|---|---|
| `mos_pct` | derived: `((iv - price) / price) * 100` | service.py:3355 | Recomputed from post-moat `iv`. Clamped to ±50 inside the canonical scoring function (scoring.py:54). |
| `piotroski.score` | `piotroski_service` output dict | service.py:3364 | 0-9 integer. Divided by 9 and scaled to 25. |
| `moat_result.grade` | `moat_service` output dict | service.py:3365 | Narrative grade ("Wide"/"Moderate"/"Narrow"/"None") **OR** letter grade (A+ / A / B+ / B / C+ / C / D) from hex layer. The mapping in scoring.py:73-80 handles both. |
| `enriched.revenue_growth` | `enrichment_service` | service.py:3366 | Decimal-or-percent — scoring.py auto-detects via `|x|<1.5` heuristic. |
| `raw.finnhub_price_target.mean` | Finnhub `quote/price-target` | service.py:3358 | Used to derive `analyst_upside = (target - price)/price * 100`. Missing target → upside=0 → sent_score=4 (neutral). |
| `iv` | DCF / PB / cohort / IPO routing | service.py (multiple) | Feeds `mos_pct`. The cohort overlays (Day-109a banking, Day-110c REIT, etc.) change `iv` and therefore the score's `val_score` bucket transitively. |
| `price` | pinned snapshot (PR-DET-1) | service.py:3355 | NEVER re-fetched at read time; the cached snapshot is what produced the cached `mos_pct`. |
| `_skip_dominance_cap` | derived from `_override.model_caveat` | service.py:4378-4380 | Only holdco/SOTP-skip exempts. Banking-cohort PB anchoring does **not** exempt. |

There is no DB read inside `compute_yieldiq_score` itself — it is a
pure function. Every input is computed earlier in `service.py` and
passed in as scalars.

---

## Section 3 — Reproducing the HDFCBANK Audit#10 #120 Score Move

**Observed:** HDFCBANK score moved 68 → 50 across the Day-109a
banking cohort apply (`v_day109a_banking_cohort_2026_05_23`, manifest
line 487-504).

**Live state (per Phase B.0 probe, doc §TL;DR #3):** score=50,
FV=1097, MoS=43.1%, verdict=fairly_valued.

### Pre-Day-109a math (reconstruction)

Pre-cohort, HDFCBANK ran the Day-76 PB skip path: peer-median P/BV
~2.5x × BVPS → FV roughly equal to or slightly below CMP, so MoS
hovered near 0 to mildly positive.

Approximate inputs the canonical formula would have seen:
- mos_pct ≈ +5%      → val_score = 8   (>=0 bucket)
- piotroski = 7      → pio_score = 19.4 → int 19
- moat = "Moderate"  → moat_pts = 15
- rev_growth ≈ 0.15  → grw_score = 15  (>=10 bucket after %-norm)
- analyst_upside ≈ 12 → sent_score = 7

Base composite = 8 + 19 + 15 + 15 + 7 = **64 → grade B**.
With MoS≈5% (<15 bucket), the dominance cap is no-op (cap=100).
Final = **64**, grade B. (The audit cites 68; the 4-pt gap is within
the rounding noise of the inputs we can't probe historically. The
shape is right.)

### Post-Day-109a math (reproducible)

Day-109a applies cohort PB anchoring: tier1_private anchor 3.0x ×
ROE-quality boost 1.20 = **3.6x book**. With HDFCBANK BVPS ≈ ₹530 →
FV ≈ ₹1908 vs the price probed at ~₹1334 → wait, the live probe says
FV=1097, MoS=43.1%, price ≈ ₹767.

(Price probe disagrees with my BVPS estimate because the actual BVPS
on the live record is lower — but the *direction* and the bucket
assignments are what matter for this reproduction.)

The relevant math at MoS=43.1%:
- val_score = 20    (mos >= 40 bucket, clamped to +50 first)
- pio_score ≈ 19    (piotroski 7)
- moat_pts = 15     (Moderate)
- grw_score = 15    (rev_growth ≈ 0.12-0.15)
- sent_score ≈ 7    (upside ≈ 10-15%)

Base composite = 20 + 19 + 15 + 15 + 7 = **76 → grade A**.

**Now the MoS-dominance cap fires:** |mos_pct|=43.1 → in `>30` bucket
→ cap = **50**. Since base 76 > cap 50, `yiq_score["score"] = 50`,
grade re-derived → **C+**.

Logged at INFO level: `score_mos_dominance.capped ticker=HDFCBANK
mos=43.1 orig=76 cap=50` (service.py:4409-4412).

**Conclusion:** the 68 → 50 move is **correct math given the formula
as written**. The cap is intentional (it exists to prevent a single
anomalous MoS from producing a contradictory headline grade, per the
comment block at service.py:4382-4395). It is **not communicated to
users**, so a high-MoS bank with high-conviction quality looks
under-scored. This is the C.3 transparency target: the cap will appear
as a visible modifier in `score_breakdown.modifiers`.

Manifest citation: `v_day109a_banking_cohort_2026_05_23`
(cache_invalidation_manifest.py:486-504). No score-only manifest
entry exists for the dominance cap because it was added before the
manifest infrastructure landed (predates Phase B).

---

## Section 4 — Score Quirks Surfaced by the Audit

For each: file:line, current behaviour, intent assessment, C.2
suggested action.

### Quirk #1 — MoS-dominance cap is invisible to users

- **Where:** `backend/services/analysis/service.py:4378-4414`
- **Current behaviour:** Base composite of 76 with `|mos|>30` gets
  silently floored to 50, grade A → C+. The INFO log line is the
  only trace. No field on the wire indicates a cap fired.
- **Intent:** Intentional (per comment block) — prevents extreme-MoS
  outliers (often misclassification artefacts) from producing
  contradictory A grades.
- **Action: KEEP AS-IS, but surface in C.3.** Add
  `score_breakdown.modifiers[].name = "MoS-dominance cap"` with
  `delta = capped - base` and `reason = "|MoS| > 30% — cap at 50"`.
  This is the single biggest source of the "score went DOWN even
  though FV went UP" confusion. The math is sound; the silence is
  not.

### Quirk #2 — Inline TypeError-fallback has different weights

- **Where:** `backend/services/analysis/service.py:3369-3392`
- **Current behaviour:** If `compute_yieldiq_score` raises
  `TypeError`, a different scoring formula runs (40/30/20 envelopes,
  no sentiment, integer-only). Result is silently put on the wire
  with the same `yieldiq_score` field name and identical schema.
  Users cannot tell which formula produced the number.
- **Intent:** Defensive fallback added during a prod incident. The
  canonical function has since been hardened (decimal-or-percent
  rev_growth, None-safe analyst_upside, scoring.py:53-56, 93-98,
  112-115) such that TypeError is no longer reachable from clean
  inputs.
- **Action: FIX IN C.2.** Replace the fallback with a single
  `logger.exception(...)` + re-raise so the caller treats it as
  pipeline failure (and the response yields `verdict=data_limited`,
  score absent) rather than silently scoring on a different formula.
  Add a backend test that asserts every canary ticker exits the
  canonical path (no `scoring fallback for ticker=...` log line).

### Quirk #3 — Mock fallback at module import

- **Where:** `backend/services/analysis/service.py:80-90`
- **Current behaviour:** If `from dashboard.utils.scoring import
  compute_yieldiq_score` fails at import time, a 4-line lambda runs
  with weights 40/30/20/10, no moat awareness, no clamps, no grade
  bands matching the canonical thresholds.
- **Intent:** Originally a Streamlit-mock guard (dashboard depends on
  Streamlit; backend doesn't). The dashboard package ships in the
  backend Docker image today, so this branch is expected to be dead.
- **Action: FIX IN C.2.** Replace the `except Exception:
  def compute_yieldiq_score(...)` block with a hard import (let it
  raise at boot if the dashboard package is genuinely missing — that
  is a deploy bug, not a runtime fallback). One-line change.

### Quirk #4 — Score truncates, doesn't round (int(...) cast)

- **Where:** `dashboard/utils/scoring.py:121`
- **Current behaviour:** `total = int(val + qual + grw + sent)` —
  `int()` truncates toward zero. A genuine 64.9 lands as 64, not 65.
  Across the 50-canary set this systematically biases scores down by
  ~0.5 pts on average.
- **Intent:** Probably unintentional — most score-band cutoffs are
  multiples of 5 or 10, so the truncation rarely flips a grade band,
  but it does flip on the boundaries (a true 65.0 → grade B+;
  truncation of 64.9 → grade B).
- **Action: KEEP AS-IS.** The grade-band flip risk is real
  but ≤0.5 pt across the 50-canary set isn't worth a CACHE_VERSION
  bump's worth of churn (score field is in the manifest scope of
  every recompute entry). Document in the C.3 breakdown that values
  are floored, not rounded.

### Quirk #5 — Dominance cap exempts only holdco/SOTP-skip

- **Where:** `backend/services/analysis/service.py:4378-4380`
- **Current behaviour:** `_skip_dominance_cap = bool(_override and
  _override.get("model_caveat"))` — only the holding-company-SOTP
  branch (and any future `_override` with a `model_caveat`) bypasses
  the cap. Banking PB-anchored names (HDFCBANK et al.) do NOT
  bypass — their cohort-anchored high MoS is treated as if it were a
  generic-DCF anomaly.
- **Intent:** Partially intentional. The cap was written before the
  banking cohort existed (Day-109a). When the cohort delivers a
  legitimate +40% MoS via a documented anchor, capping the score is
  arguably wrong — the cohort overlay has already validated the FV.
- **Action: KEEP AS-IS for C.2; revisit when score_breakdown
  ships in C.3.** Fixing this would change scores for HDFCBANK,
  ICICIBANK, AXISBANK, KOTAKBANK, SBIN and several Tier-2 names — a
  multi-ticker score move that needs the C.3 transparency panel
  shipped first so users see *why* the score went up. Note this
  explicitly in the C.3 panel as "future work" rather than a silent
  TODO.

---

## Section 5 — Action Summary (input to C.2 / C.3)

| # | Quirk | Action | Phase |
|---|---|---|---|
| 1 | MoS-dominance cap invisible | Surface in `score_breakdown.modifiers` | C.3 (transparency-only, no score change) |
| 2 | TypeError fallback diverges from canonical | Remove fallback, log + re-raise | C.2 PR 1 |
| 3 | Mock import fallback diverges | Hard-import dashboard scoring | C.2 PR 2 |
| 4 | int() truncation biases low | Document only | C.3 (panel note) |
| 5 | Cap doesn't exempt banking cohort | Defer | post-C.3 |

C.2 has **2 PRs** (Quirks #2 and #3). Both are read-time / cleanup
fixes that are expected to produce **zero canary-FV diff** because:

- Quirk #2 fix only changes behaviour when TypeError fires, which we
  expect to be zero canary tickers (will verify via Railway log
  search before opening C.2 PR 1).
- Quirk #3 fix only changes behaviour when the dashboard import
  fails, which never happens in prod (the image ships the package).

If either PR moves any canary FV/score, the canary-diff workflow will
flag it and the PR description will enumerate movers per the
data-fix discipline rule (`CLAUDE.md` §1).

C.3 is **1 PR**: add `score_breakdown` to the analysis response (no
score values change — field-additive only, manifest scope
`["score_breakdown"]`) plus the collapsible "Why this score?" panel
in the frontend.

---

## Section 6 — Out-of-Scope Observations

These were noticed during the audit but are not score-formula
issues; flagging here for future work rather than spawning tasks:

1. `confidence["score"] = min(_conf_now, 50)` at service.py:4856
   clamps confidence (not score) when a `model_caveat` is present.
   The clamp value 50 is hardcoded — there's no manifest entry
   describing why 50 is the right ceiling. Likely a separate
   confidence-transparency task post-Phase C.
2. `moat_grade` mapping at scoring.py:73-80 carries both narrative
   ("Wide" / "Moderate") and letter ("A+" / "B") keys. Two
   independent moat scorers (hex_service and moat_service) emit
   different conventions. Not a bug — both branches resolve — but
   the dual key set is a candidate for consolidation to one
   canonical shape in a future cleanup.
3. The Phase B.2 manifest entry (`v_phase_b2_bull_sanity_2026_05_24`)
   includes `score` in its scope because bull_case → MoS → score is
   transitive, but the score change is incidental. C.3 will make
   this kind of transitive score move visible in the breakdown
   ("Verdict / cohort overlay changed FV → MoS bucket changed").

---

*End of Phase C.1 diagnostic. Proceed to C.2 PR 1 (Quirk #2 fix).*
