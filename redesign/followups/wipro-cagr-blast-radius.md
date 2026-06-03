# WIPRO CAGR — blast-radius diagnosis (READ-ONLY)

Date: 2026-06-03
Author: diagnosis agent (read-only)
Scope: `_SANITY_ABS_CAP=100.0` in `backend/services/cagr_service.py`
Inputs: live prod API (`api.yieldiq.in`), 333-ticker canary universe
(`scripts/canary_universe_180.json`)

Hard constraint observed: no code changes, no canary-diff, no
CACHE_VERSION bump, no PR. Output is this report.

---

## 0. TL;DR

| Section | Finding |
|---|---|
| 1. WIPRO ground truth | The live system **cannot reproduce -77.1%** today. WIPRO is gated to `under_review` and `company_financials` has only 3 annual rows (FY23-FY25, revenue 90,488 → 89,760 → 89,088 Cr). The honest 3y CAGR over those inputs is **-0.77%**, not -77.1%. Most-likely upstream cause for the captured value: an **input-source bug** (stale/partial/duplicate row in `company_financials`) that produced a near-zero start-of-window denominator. |
| 2. Cap blast radius | **0 of 268 measurable canaries** have any CAGR field with `\|pct\| > 100%`. The cap **never fires** in the current universe. p99 = 85.1%, p99.5 = 91.4%, p99.9 = 98%, max = 98%. The cap is doing essentially no protective work, but raising it isn't the bug. |
| 3. FV history threat | **CAGR does NOT feed the FV / DCF pipeline.** `compute_cagr_panel` is called from exactly one site (`backend/routers/public.py:446`) and the value is forwarded to the `compounded_growth` JSON field of `/stock-summary` only. The persisted `fair_value_history` table sources its `fair_value` from `analysis_cache.payload.valuation.fair_value` (see `backend/scripts/backfill_fair_value_history_monthly.py:144-176`), not from CAGR. **A bad CAGR cannot poison persisted FV history.** Conditional caveat: if a future feature ever wires CAGR into terminal growth / fade rate, this stops being true — guard with a code-search before adding any such dependency. |
| 4. Recommendation | **(A) — Cap is fine; WIPRO is an isolated input-source bug class.** Several other tickers in the top-20-by-magnitude list exhibit the same upstream symptom (CRISIL FY2024 revenue = 738 Cr against a true ~3,000 Cr; ABB FY2024 = 3,080 Cr against a true ~10,000 Cr; ANANTRAJ / ADANIENSOL with duplicated FY2024 rows). Fix the populator, leave the cap. |
| 5. Stop-the-line count | **6 tickers** with user-facing CAGR magnitudes I believe are inflated/wrong due to upstream input bugs (CRISIL, ABB, DIXON-suspected, ADANIENSOL, ANANTRAJ, BAJAJHLDNG); plus a separate **FV-jump finding on WIPRO itself** (FV ₹272 → ₹864 over 2 weeks in May, persisted into `fair_value_history`) which is independent of CAGR but was uncovered during the investigation. |

---

## 1. WIPRO ground truth

### 1.1 The data the live engine sees today

`/api/v1/analysis/WIPRO.NS/financials?years=10` returns
`years_available: 3` from the `company_financials` table:

| FY | period_end | revenue (Cr) | net_income (Cr) |
|---|---|---|---|
| FY2025 | 2025-03-31 | 89,088.4 | 13,135.4 |
| FY2024 | 2024-03-31 | 89,760.3 | 11,045.2 |
| FY2023 | 2023-03-31 | 90,487.6 | 11,350.0 |

These match Wipro's published consolidated income statements. No
unit error visible at this level. Revenue is essentially flat
(slight -0.7% YoY) — consistent with the post-COVID IT-services
demand softness. There is no real-world collapse.

### 1.2 Hand-computed CAGR from the live inputs

`cagr_service._window_endpoints` for `(years=3, attr="revenue")`:

- `newest` = FY2025 (revenue 89,088.4)
- `target_fy` = 2025 − 3 = 2022
- No FY2022 row exists → fallback `abs(p.fy - target_fy) <= 1` → FY2023 (90,487.6)
- `actual_years = 2025 − 2023 = 2`
- `_cagr(90487.6, 89088.4, 2) = ((89088.4/90487.6)^(1/2) − 1) × 100 = -0.775%`

**The honest current 3y CAGR is -0.8%, well within plausibility. The
labelled "3y" window is actually 2y due to the ±1 FY fallback —
that's a separate label-vs-actual smell worth filing but not the cap
issue.**

### 1.3 Live `compounded_growth` for WIPRO

`/api/v1/public/stock-summary/WIPRO.NS` currently returns
`status: under_review`, `reason: validation_critical`,
`issue_count: 2`. No `compounded_growth` block is emitted. WIPRO has
been pulled from the public surface, so the -77.1% the spec author
captured is **not reproducible from the live API today**.

### 1.4 Coverage-tier delta (worth filing separately)

`/api/v1/coverage/WIPRO.NS` reports `annual_history.value = 7` (7
annual rows in the `financials` table — the OLD table used by the
DCF engine in `backend/services/analysis/db.py`).

But `cagr_service._fetch_annual_points` queries the NEW
`company_financials` table, which returns 3 rows. **The DCF engine
and the CAGR service read different tables, with very different
coverage for the same ticker.** That is the most likely vector for
historical -77.1%: at some prior moment, `company_financials` for
WIPRO may have contained a corrupt row (mis-classified quarterly as
annual, currency unit confusion, or a partial-period row from XBRL
ingest) whose revenue value was small enough to push CAGR to a
double-digit-negative regime. With 3 clean rows today, that exact
condition is no longer present.

### 1.5 Verdict

**Most likely an input-source bug, not a cap bug, not a math bug.**
The CAGR formula is correct; `_SANITY_ABS_CAP=100` admitted whatever
value the bad input produced. Today the inputs are clean (just
sparse). The reproduction window has closed without anyone
deliberately closing it.

---

## 2. Sanity-cap blast radius (universe scan)

### 2.1 Method

- Universe: 333 tickers from `scripts/canary_universe_180.json` (the
  file is named "180" but the manifest now holds the v3 333-ticker
  expansion; see `_meta.universe_version: v3_333`).
- For each ticker, `GET https://api.yieldiq.in/api/v1/public/stock-summary/<sym>.NS`.
- Sequential, 150 ms throttle. Raw results in
  `redesign/followups/_cagr_scan.csv`.
- Per ticker captured: revenue.{3y, 5y, 10y}, profit.{3y, 5y, 10y},
  stock.{3y, 5y, 10y}, stock.status.

### 2.2 Status breakdown

| status | count |
|---|---|
| ok (CAGR observable) | 268 |
| under_review (gated, no payload) | 11 |
| ERR / 503 / not-found | 54 |
| **Total** | 333 |

The 54 ERRs include `LT`, `GRASIM`, `ADANIGREEN`, `ZOMATO`, `PAYTM`,
etc. Sticky 503s, not transient. Treat as data-limited for this
audit. The 268 measurable tickers carry the signal.

### 2.3 Histogram of `|CAGR|` across all 800 non-null cells

| band | n cells |
|---|---|
| [0, 20%) | 528 (66%) |
| [20%, 30%) | 111 |
| [30%, 40%) | 71 |
| [40%, 50%) | 32 |
| [50%, 60%) | 22 |
| [60%, 70%) | 16 |
| [70%, 80%) | 10 |
| [80%, 90%) | 4 |
| [90%, 95%) | 5 |
| [95%, 99%) | 1 |
| **[99%, 100%)** | **0** |
| **[100%, ∞)** | **0 (cap never fires)** |

Percentiles of `|CAGR|`: p50=13.9, p75=24.8, p90=42.7, **p95=57.8,
p99=85.1, p99.5=91.4, p99.9=98.0, max=98.0**.

### 2.4 Headline thresholds (any field per ticker)

| condition | n tickers (of 268 measurable) |
|---|---|
| any abs(CAGR) > 50% | 45 |
| any abs(CAGR) > 75% | 14 |
| any abs(CAGR) > 90% | 6 |
| **revenue.Xy < -50%** (WIPRO failure mode) | **0** |

**The WIPRO failure mode (revenue CAGR < -50%) does not currently
exist for any other ticker in the universe.** The worst negative
revenue CAGR observed is `VEDL rev3y = -19.2%`, which is partly a
real Hindustan-Zinc-demerger reclass and partly consistent with the
commodity-cycle drop.

### 2.5 Top-20 by absolute magnitude

```
ticker      field    pct
ANANTRAJ    prof3y    98.0
ADANIENSOL  rev5y     94.0
SAGILITY    prof3y    93.8
LICI        prof5y    93.2
BAJAJHLDNG  rev5y     91.4
CRISIL      prof3y    91.1
ABB         prof3y    89.6
IDFCFIRSTB  prof5y    86.8
AIIL        prof3y    85.1
AKZOINDIA   prof3y    80.6
NUVAMA      prof3y    79.8
DIXON       prof3y    77.9
PNB         prof3y    76.4
ABB         rev3y     75.6
JSWSTEEL    prof3y    75.3
ANANTRAJ    prof5y    73.9
BSE         prof3y    73.4
MRPL        prof3y   -73.3
CRISIL      rev5y     71.5
APOLLOHOSP  prof5y    70.0
```

### 2.6 Spot-checks on top-20 (raw financials)

`/api/v1/analysis/<sym>.NS/financials?years=6` for the top movers:

- **LICI** — FY26 rev 978k Cr / pat 57k vs FY24 rev 849k / pat 41k.
  Real numbers; participating-fund accounting changes around the
  IPO inflate apparent profit CAGR. **Likely real.**
- **BAJAJHLDNG** — holding-co; revenue is investment income, lumpy.
  **Likely real but noisy.**
- **CRISIL** — FY24 revenue = **738 Cr**, FY25 = 3,260 Cr, FY26 =
  3,649 Cr. **FY24 row is broken** (real CRISIL FY24 revenue is
  ~₹3,000 Cr — possibly a standalone-vs-consolidated mix or a
  partial-period row). Drives both prof3y=91.1% and rev5y=71.5%.
  **Upstream input bug.**
- **ABB** — FY24 revenue = **3,080 Cr**, FY25 = 12,088 Cr, FY26 =
  13,065 Cr. Real ABB India revenue is ~₹10-12k Cr. **FY24 row is
  broken** (probably a partial-period or wrong-currency ingest).
  Drives prof3y=89.6% and rev3y=75.6%. **Upstream input bug.**
- **DIXON** — FY24 rev 17,614 → FY26 48,873. Dixon did genuinely
  double-then-double; the EMS surge is real. Plausible.
- **VEDL** — FY24 rev 141,793 vs FY25 61,605: clearly a
  consolidation-scope change (Hindustan Zinc reclass / demerger).
  Real corporate-action, not a unit bug — but the CAGR is misleading
  to a casual reader.
- **SAGILITY** — newly listed (Nov 2024), tiny baseline.
  **Likely base-effect, not a bug.**
- **ADANIENSOL** — FY2024 appears **twice** in the response (two
  rows both labelled FY2024 with slightly different values),
  FY2023 is missing. **Upstream duplicate-key bug.**
- **ANANTRAJ** — same pattern as ADANIENSOL: FY2024 duplicated, no
  FY2023. **Upstream duplicate-key bug.**
- **MRPL** — refinery PAT collapsed (3,597 → 56 Cr) on weak GRMs.
  Real.

Estimated false-positive rate in the top 20: **~5 of 20 (25%)** are
driven by upstream input bugs rather than real moves. Several more
are base-effects (legit but misleading to a retail reader).

### 2.7 Implication for the cap

The cap (`100.0`) never fires in the live universe (max observed
98.0). The cap also doesn't filter out the 5-or-so genuinely-wrong
values in the top-20 — they're all in the 70-95% band, well below
the cap. **Tightening the cap to, say, 75% would null out roughly
14 tickers' top-1 CAGR cells, of which only ~5 are actually wrong
and ~9 are real (newly-listed names, restructured holdings,
genuinely cyclical recoveries, real demergers).** The cap is the
wrong lever.

---

## 3. Threat to FV History

### 3.1 Call-site audit for `compute_cagr_panel`

```
backend/routers/public.py:446    "compounded_growth": _safe_compute_cagr_panel(...)
backend/routers/public.py:451    def _safe_compute_cagr_panel(...)
backend/routers/public.py:454        from backend.services.cagr_service import compute_cagr_panel
backend/routers/public.py:455        return compute_cagr_panel(ticker)
```

`compounded_growth` is consumed only by frontend display code
(verified via repo grep — no DCF/forecaster/terminal-growth path
reads the field). It is a pure JSON pass-through to the
`/stock-summary` payload.

### 3.2 What `fair_value_history` actually stores

Reading `backend/scripts/backfill_fair_value_history_monthly.py`:

- `_fetch_current_fv` (line 144) reads
  `analysis_cache.payload.valuation.fair_value` — sources the FV
  from the cached DCF result.
- `_fetch_monthly_closes` (line 202) reads `daily_prices.close_price`
  for monthly anchor prices.
- `_upsert_rows` (line 253) computes `mos_pct = (fv_today − close) / close × 100`
  and clamps to `[-90, +200]` before insert.
- Insert columns: `ticker, date, fair_value, price, mos_pct, verdict, wacc, confidence, updated_at`.

There is **no CAGR field** in `fair_value_history`. There is **no
read of `compounded_growth` in the backfill script**. The
DCF engine (in `backend/services/analysis_service.py` and
`backend/services/analysis/`) reads from the OLD `financials`
table, not from `company_financials`, and computes its own growth
assumptions internally via `models/forecaster.py` — not via
`cagr_service`.

### 3.3 Verdict

**No. A bad CAGR cannot poison persisted FV history today.** The
two systems are isolated. CAGR is a display-only metric attached
to `/stock-summary`; FV history is populated from
`analysis_cache.valuation.fair_value`.

**Conditional caveat for the Phase-1 FV-history feature:** if Agent
B's roadmap wires `compounded_growth.revenue.3y` into any new
terminal-growth / fade-rate / sanity-check field for the DCF engine
or for the persisted history, this isolation breaks. Add a grep
guard in CI: `grep -r "compounded_growth" backend/services/analysis*
backend/models/forecaster*` should match nothing.

---

## 4. Recommendation: (A) — Cap is fine, fix the input source

**Reasoning:**
1. The cap (`100.0`) never fires in the live universe (§2.3, §2.5).
2. The WIPRO `-77.1%` is not reproducible today; current inputs
   produce a sane `-0.8%` (§1.2).
3. The handful of suspect CAGRs in the top 20 (CRISIL, ABB,
   ADANIENSOL, ANANTRAJ) are all driven by visible upstream input
   bugs (partial-period rows, duplicate FY rows) — not by the math
   or the cap (§2.6).
4. Tightening the cap risks false-rejects on legitimate large moves
   (newly-listed names like SAGILITY, holding-co restructurings like
   BAJAJHLDNG, real cyclical recoveries) without catching the actual
   bug class.
5. The FV-history workstream is not at risk from CAGR (§3).

**What to actually fix (advisory, not a code change to make in this
task):**
- File a separate task: audit `company_financials` for duplicate
  `(ticker, period_end)` rows and partial-period rows. ANANTRAJ,
  ADANIENSOL, CRISIL, ABB are confirmed starter cases.
- File a separate task: investigate why
  `company_financials` has 3 rows for WIPRO while the OLD
  `financials` table has 7 rows. Two-table-divergence is itself a
  brittleness — the `cagr_service` reads one, the DCF engine reads
  the other, and there is no reconciliation.
- Optional: add the validator from
  `backend/services/data_quality/validators/cagr_service_output.py`'s
  plausibility band (`[-30, 50]`) to ALL CAGR cells, not just the
  5 canary tickers — would flag CRISIL/ABB/ADANIENSOL today.

**Do not** tighten `_SANITY_ABS_CAP`. Do not bump CACHE_VERSION.

---

## 5. Stop-the-line list

Tickers where I believe a user-facing number is currently wrong:

### 5.1 CAGR-related (display only — does NOT corrupt FV history)

| ticker | suspect figure | suspected cause |
|---|---|---|
| **CRISIL** | profit.3y = +91.1%, revenue.5y = +71.5% | `company_financials` FY2024 revenue row = 738 Cr (real ~3,000 Cr). Bad XBRL row or standalone-vs-consolidated mix-up. |
| **ABB** | profit.3y = +89.6%, revenue.3y = +75.6% | `company_financials` FY2024 revenue row = 3,080 Cr (real ~10,000 Cr). Partial-period or wrong-currency ingest. |
| **ANANTRAJ** | profit.3y = +98.0%, profit.5y = +73.9% | FY2024 row duplicated, FY2023 missing in `company_financials`. Walk-back picks wrong baseline. |
| **ADANIENSOL** | revenue.5y = +94.0% | FY2024 row duplicated, FY2023 missing. Same pattern. |
| **BAJAJHLDNG** | revenue.5y = +91.4% | Holding-company revenue is investment income — lumpy and dependent on associate-dividend booking. Not a bug per se but the "revenue CAGR" framing is misleading; should probably be suppressed for holdcos at the panel level. |
| **DIXON** (lower confidence) | profit.3y = +77.9% | Inputs look plausible (real EMS surge); flagged only because it's high enough that a reader will discount the panel. |

None of the above flow into the DCF or into persisted FV history.
All are confined to the `compounded_growth` block on
`/stock-summary` and the frontend CompoundedGrowthPanel.

### 5.2 Not CAGR-related but found during investigation

**WIPRO `fair_value_history` discontinuity (CRITICAL — independent of CAGR):**
`/api/v1/analysis/WIPRO.NS/fv-history?years=1` shows a step-change
on 2026-05-17 from FV ₹272 → ₹558.91 → ₹631.43 → ₹715.93 → … →
₹872.67 (2026-06-02), with `mos_pct` running 182% → 318% throughout
the second half of May. The price has been ~₹200 the whole time.
These rows are **persisted** in `fair_value_history`. The 30-row
history shows two distinct regimes joined by a discontinuity; this
is the textbook "provenance poison" the §3 question was asking
about — but the poison came from the DCF engine, NOT from CAGR.

Possible upstream causes (do not investigate in this task, file
separately):
- A WACC/Ke change landed on 2026-05-17 that wasn't accompanied by
  a cache-version bump.
- The `under_review` gate was added recently; before the gate, bad
  WIPRO valuations were being persisted to `fair_value_history`.
- A `data_limited`-verdict transition on 2026-05-19 (visible in the
  payload) coincides with the FV doubling — there may be a fallback
  computation path that produces inflated FVs when full inputs are
  unavailable.

This is the most important finding in this report. The CAGR cap is
fine; **the FV-history population path needs its own audit before
Phase-1 Agent-B treats persisted rows as ground truth.**

### 5.3 Process / discipline finding

The `cagr_service` reads `company_financials`; the DCF engine reads
`financials` (the older table). They diverge sharply for some
tickers (WIPRO: 3 vs 7 rows). Any future "CAGR sanity check" that
compares engine inputs against CAGR outputs will be comparing
different rowsets and producing false alarms. Worth a one-time
reconciliation pass on the populators.

---

## Artefacts

- Raw scan CSV: `redesign/followups/_cagr_scan.csv` (333 rows; 268
  with full CAGR data, 11 under_review, 54 ERR/503).
- This report: `redesign/followups/wipro-cagr-blast-radius.md`.

No code changed. No PR opened. No cache bumped.
