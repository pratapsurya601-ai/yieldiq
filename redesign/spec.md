# YieldIQ Analysis Page — Stage 1 Spec

**Date:** 2026-06-03
**Stage:** 1 (spec only — no code, no migrations, no PR)
**Author:** Claude (spec agent)
**Inputs:** `redesign/audit.md` (Stage 0), 20 PNG captures under `redesign/screenshots/`, `AnalysisBody.tsx`, `lib/personalization.ts`, root + frontend `CLAUDE.md`, `memory/feedback_yieldiq_discipline.md`.

The redesign re-arranges and re-styles what exists today. No new product
features. One new primitive is justified inline (`DegradedScenarioCard`,
section 2) because it is required to express an honest state that the
current DOM cannot.

Banned vocabulary policy: all user-facing copy proposals below were
filtered against the SEBI list (should, appears, strong, weak, cheap,
poor, buy, sell, hold, recommend, target, expensive). Prose ABOUT the
redesign discipline uses the operator-permitted terms (buried,
elevated, promoted, cut).

---

## 1. Target above-the-fold composition — WIPRO-first

The hardest ticker is WIPRO: clamped FV, three identical bear/base/bull
discounts (+200.0%), `Possible value trap` subtitle, four red flags,
revenue contraction -77.1%, no moat. If the above-the-fold treatment
serves WIPRO honestly, every cleaner ticker (TCS, HDFCBANK, M&M)
inherits the win.

Above-the-fold goal is a single hero region — `HonestHero` — that
carries, in order of priority:

1. Verdict pill (gated through `shouldGateVerdict`)
2. Fair Value figure + confidence band
3. Discount-to-FV (or the degraded scenario card from section 2)
4. Worry signal
5. One-line caveat row (value-trap / data-limited / clamp note)
6. Honest Card teaser (collapsed by default on desktop, two-line preview)

The legacy `EditorialHero` (Wikipedia photo) demotes to a slim band
(spec section 5). `ConfidenceIndicators` becomes the visual primary.
`NarrativeSummary` prose card moves below the fold inside the Bull/Bear
panel as the "Why this verdict" lead-in.

### One rail, not two — `ScoreCard` retirement (Fold 1)

The first-pass spec left two components answering the same G1 question:
the existing `ScoreCard` (currently rendered inside the "Confidence and
methodology" `<details>` disclosure on `AnalysisBody.tsx`, around the
`ScoreCard` import at line 43 — verified by grep) and a new HonestHero
side rail. Two rails drift. We collapse them into one.

- **Killed:** `frontend/src/components/analysis/ScoreCard.tsx` — file
  is retired as a top-level mount. Its 4 tiles (Score / Grade / Sector
  Rank / Refraction / Market cap / 12M sparkline / distress-flag grade
  clamp) move INTO `HonestHero`'s side rail at desktop. The file may
  remain on disk until Stage 2 cluster A confirms no other surface
  imports it (verified with grep at spec time: only `AnalysisBody.tsx`
  and `EditorialHero.tsx` import it; both go away in this redesign).
  Cluster A or C deletes the file at the end of Stage 2.
- **Absorbed by:** `HonestHero` (new, cluster A). The side rail (320 px
  at >=1280, see §1.1) gains the following props that ScoreCard used to
  own: `score100`, `grade`, `trend12m`, `sectorRank`, `refractionIndex`,
  `marketCapCr`, `redFlags` (for the distress-flag grade-cap rule —
  preserve the `capGrade` / `DISTRESS_FLAGS` logic verbatim inside
  HonestHero so the "Grade A while page lists Consecutive Losses"
  defence is not lost). Side-rail tiles inside HonestHero:
  Score / Moat / Red flags / Worry / 12M sparkline / Refraction /
  Market cap. The Honest Card teaser and Reverse-DCF deep-link stay at
  the bottom of the rail as before.
- **Scroll/sticky behaviour at >=1024:** the side rail uses
  `position: sticky; top: <header offset>;` and remains pinned through
  the page scroll. ScoreBreakdownPanel + ConfidenceIndicators below
  the fold keep their `<details>` disclosure ("Confidence and
  methodology") — the disclosure stops carrying ScoreCard, but keeps
  ScoreBreakdownPanel and ConfidenceIndicators as "details on the
  score that's pinned above."
- **Mobile fallback (<=768):** the side rail collapses INTO
  `MobileScoreStrip` (the 4-tile strip from §6). MobileScoreStrip
  stays a separate component but reads from the SAME source-of-truth
  resolver (a new `useHeroSignals(payload)` hook owned by cluster A in
  `frontend/src/lib/scenarios.ts` next to `isDegradedScenario`) so
  desktop and mobile cannot drift. The hook returns
  `{ verdict, fairValue, discount, worry, score, grade, moat, redFlags,
  refraction, marketCapCr, trend12m }` and is the only thing both
  surfaces consume.

### 1.1 WIPRO @ 1440 — hero composition (verbatim)

```
+------------------------------------------------------------------------+
| TickerStrip (indices + watchlist) — slim 28 px                         |
+------------------------------------------------------------------------+
| AdrCohortBanner (Data Limited) — slim 32 px                            |
+------------------------------------------------------------------------+
| Ticker row: WIPRO  Rs.245.30   [Time-M] [Save] [Alert] [Share]         |
+--------------------------------+---------------------------------------+
| HonestHero (left, 720 px)      | Side rail (right, 320 px)             |
|                                |                                       |
|  WIPRO  Wipro Ltd              |  YieldIQ Score   40 / 100             |
|  [ UNDERVALUED ]  conf 43%     |  Moat            None                 |
|                                |  Red flags       4                    |
|  Fair Value  Rs.629.52         |  Worry           Elevated             |
|     (clamp ceiling; raw model  |  ---                                  |
|      Rs.882.78 — see notes)    |  Honest Card teaser >                 |
|                                |  Reverse-DCF >                        |
|  DegradedScenarioCard          |  Tell me the story >                  |
|  ----------------------------- |                                       |
|  Scenario spread exceeds       |                                       |
|  model display bounds.         |                                       |
|  Bear / base / bull collapse   |                                       |
|  to the +200% clamp ceiling.   |                                       |
|  Possible value trap: deep     |                                       |
|  discount paired with a        |                                       |
|  shrinking revenue trend, no   |                                       |
|  moat, and 4 red flags. See    |                                       |
|  valuation notes below.        |                                       |
|                                |                                       |
+--------------------------------+---------------------------------------+
| EditorialHero (demoted slim band, 96 px) — photo + caption strip       |
+------------------------------------------------------------------------+
| AnalysisTabs (Summary / Valuation / Quality / Financials / History /   |
| Peers)                                                                  |
+------------------------------------------------------------------------+
```

Above-the-fold surface count: 4 chrome rows (Ticker strip, ADR banner,
ticker row, EditorialHero slim band) + 1 HonestHero + 1 side rail. The
verdict, FV (with clamp disclosure), the value-trap caveat, the
degraded-scenario explanation, Worry, and Score all fit within ~720 px
of vertical space at 1440. G1 passes.

### 1.2 WIPRO @ 1024 — hero composition

Side rail collapses to a horizontal `MiniScoreRow` (Score | Moat | Flags
| Worry) under the HonestHero. EditorialHero slim band stays.

```
TickerStrip  /  AdrCohortBanner  /  Ticker row
HonestHero (full width)
  verdict pill | FV (clamp note) | DegradedScenarioCard
MiniScoreRow (4 tiles)
EditorialHero slim band (80 px)
AnalysisTabs
```

### 1.3 WIPRO @ 768 — hero composition

Single-column. ADR banner collapses to a dot + tooltip on the ticker row.

```
TickerStrip
Ticker row + [ADR dot]
HonestHero (full width)
  verdict pill
  FV row (clamp pill inline)
  DegradedScenarioCard (compact — single paragraph)
MiniScoreRow (4 tiles, equal width)
AnalysisTabs (scrollable)
```

EditorialHero band is hidden below 768; the photo is not load-bearing
at tablet/mobile and burns the only real estate that matters.

### 1.4 WIPRO @ 390 — hero composition

```
[Mobile top nav]
Ticker row (price, no buttons — buttons live in the bottom action bar)
HonestHero (compact)
  [ UNDERVALUED · conf 43% ]
  FV Rs.629.52  (clamp)
  Possible value trap
  Bear/base/bull collapse to +200% ceiling. Tap for notes.
MobileScoreStrip (4 tiles: see section 6)
AnalysisTabs (scrollable)
```

`MobileScoreStrip` carries `Verdict · FV · Discount · Worry` (section 6).
For WIPRO specifically the Discount tile renders `+200% (clamp)` with a
caution dot so the strip cannot pretend the spread exists.

### 1.5 TCS — hero compositions (clean ADR case)

@ 1440: identical chassis to WIPRO. HonestHero shows
`[UNDERVALUED] conf 67% · FV Rs.3,438 · Discount +40.5% · Worry Normal`
plus a single-line Honest Card teaser ("We are confident TCS will
remain a top-3 IT services firm; our FV depends on a 9% FCF growth
assumption"). No `DegradedScenarioCard` (use the normal three-tile
scenario row from `FVProjectionFan` micro-tiles).

@ 1024 / 768 / 390: same chassis as WIPRO at the same breakpoints.
ADR banner remains because TCS is in the ADR cohort.

### 1.6 HDFCBANK — hero compositions (bank case)

@ 1440: identical chassis. HonestHero shows
`[UNDERVALUED] conf 90% · FV Rs.2,160 · Discount +53.4% · Worry Normal`.
No ADR banner. EditorialHero bank photo demotes to slim band.

Bank-specific footer row inside HonestHero: a one-line `BankKpiTeaser`
(ROE | NIM | GNPA) that links to the Quality tab. This earns the space
the demoted Reverse-DCF stub (section 7) gives back.

@ 1024 / 768 / 390: same chassis. The current HDFCBANK @ 390 is the
closest the live site comes to G1 — the new spec keeps that win and
adds FV + Discount tiles the mobile strip is missing today.

### 1.7 M&M — hero compositions (cyclical, no Wikipedia image)

M&M is the proof-of-concept for the demoted-EditorialHero state because
there is no photo to demote. The current live M&M layout is the closest
the codebase comes to a G1 pass at 1440 today.

@ 1440: HonestHero shows
`[FAIRLY VALUED] conf 16% · FV Rs.3,189.66 · Discount +6.4% · Worry Normal`
plus the cyclical-cycle caveat as the value-trap-style one-liner:
`Low confidence (16%) — peak-cycle FCF normalisation in play. Reverse-DCF
implies >=50% growth (off-scale).` This is the same honest language the
audit captured at section 7; the spec elevates it.

EditorialHero slim band: when no Wikipedia image exists, the band
becomes a neutral classification chip row (sector | cap | rename
breadcrumb if present) so the layout grid does not shift.

@ 1024 / 768 / 390: same chassis with the rename breadcrumb folded into
the ticker row as a small chip on mobile (not a full-width banner).

---

## 2. Degraded scenario state spec (WIPRO trigger)

New primitive: `<DegradedScenarioCard>` (frontend/src/components/analysis/DegradedScenarioCard.tsx — to be created in Stage 2).

### 2.1 Trigger conditions

Render `<DegradedScenarioCard>` in place of the normal three-tile
scenario row when ALL of the following are true on the live payload:

```
clamped == true                              // valuation.fair_value_clamped flag from backend
&& bear_disc == base_disc == bull_disc        // arithmetic equality, both finite
&& abs(bear_disc) >= 199.0                    // at/above the +/-200% display ceiling
```

Partial degradation (any two of bear/base/bull collapsing but not the
third) falls back to the legacy `FVProjectionFan` with an inline
`AnalyticalNotes` caution chip; do NOT render the new card.

### 2.2 Copy (vocab-checked)

Title: `Scenario spread exceeds display bounds`

Body (verbatim):
```
Bear, base and bull scenarios all collapse to the +200% clamp ceiling.
The raw model fair value (Rs.{raw}) sits more than 3x current price,
which we cap at +200% for display. The three-way spread is unavailable
for this payload. See valuation notes for clamp context.
```

Optional second paragraph (renders only when `valuation.value_trap_flag`
or `quality.red_flags >= 3 && quality.moat == "None"`):
```
Possible value trap: the discount pairs with {red_flags} red flags,
a shrinking revenue trend, and {moat} moat. The depth of the
discount is itself a signal — read the Honest Card before acting
on the headline figure.
```

Verification gate B note (Fold 4 / spec §11.6): the prior template
inlined `{revenue_cagr_3y}%` directly. That figure is computed by
`backend/services/cagr_service.py` which accepts any value with
`abs(CAGR) <= 100.0`. WIPRO's Stage-0-captured -77.1% is not
real-world plausible for a Tier-1 IT firm (revenue is in
Rs.90,000+ Cr range and has not shrunk 77% per year on any window).
Until the engine workstream instruments and audits the compute, the
hero copy renders the QUALITATIVE phrase "shrinking revenue trend"
and omits the specific percentage. The condition that triggers the
phrase is `compounded_growth.revenue.3y < 0` (i.e. the SIGN of the
CAGR, which is robust to the unit-mismatch failure mode) rather than
the magnitude.

All vocabulary verified against the SEBI ban list: no `should`,
`appears`, `strong`, `weak`, `cheap`, `poor`, `buy`, `sell`, `hold`,
`recommend`, `target`, `expensive`. `Possible` is permitted (factual
hedge, not a directive). `Acting` is operator-permitted in this context.

### 2.3 Visual treatment

Single card, full HonestHero width. Left edge accent bar = caution amber
(reuse `AnalyticalNotes` caution styling so the user has already learned
the visual grammar from existing FV-clamped notes). No three-tile
attempt. No fake spread.

Caption chip in card header: `CLAMP CEILING`.

### 2.4 Fallback for clamp without flat collapse

If `clamped == true` but discounts diverge (normal clamp on a ticker
with a wide model spread), the legacy `FVProjectionFan` renders with
the existing `AnalyticalNotes` clamp note prepended. No new card.

---

## 3. Section grading table

Inventory taken from `AnalysisBody.tsx` Summary tab and audit section 2.
Above-the-fold chrome (Ticker strip, ADR banner, ticker row,
EditorialHero, Breadcrumb, Share/Compare, NarrativeSummary,
ConfidenceIndicators, AnalyticalNotes, AnalysisTabs, WorryIndex) is
graded together below the numbered list because those surfaces are
covered by sections 1, 5 and 6. `ScoreCard` (formerly a standalone
mount inside the "Confidence and methodology" disclosure) is retired
into HonestHero's side rail per the Fold 1 resolution in §1.

| # | Section (Summary tab numbered) | Tag | Rationale | Default-expanded? | Personalization override notes |
|---|---|---|---|---|---|
| H1 | `WorryIndex` (above numbered list) | promote | Risk signal; brand promise is honesty about risk. Fold into HonestHero side rail and below-fold full panel. | yes (in hero, condensed) | unchanged across styles |
| H2 | `ConfidenceIndicators` (Valuation summary block) | promote | Becomes the spine of HonestHero (section 1). | yes (it IS the hero) | unchanged |
| H3 | `AnalyticalNotes` (conditional clamp / data-quality notes) | promote | Currently below fold; spec hoists into HonestHero caveat row. | yes (when present) | unchanged |
| 1 | `scenarios` (FVProjectionFan) | promote (conditional) / collapse-by-default (when degenerate) | When the spread is healthy the chart is primary evidence (see §4.2 conditional rule). When degenerate / clamped (WIPRO-class) the DegradedScenarioCard in HonestHero carries the story and the full section demotes. | yes when spread healthy; no when degenerate | `value` / `income` overrides are reasserted in §4.1 for the healthy path |
| 2 | `bulls_bears` thesis | promote | Dated narrative is a differentiator. Move to numbered slot 1 in DEFAULT and absorb the demoted `NarrativeSummary` model-blurb as its lead-in. | yes | `growth`/`speculator` already lead with it — converges |
| 3 | `honest_card` | promote (to hero teaser + numbered slot 2) | The brand promise. Teaser in HonestHero (2 lines), full card as numbered slot 2. | yes | `beginner` already has it at slot 2 — converges |
| 4 | `peers` (`InlinePeerComparison`) | keep | Cohort table earns its space; users do not scroll up to compare. | no by default (collapse with preview row of 3 peers) | `value`/`income` keep expanded |
| 5 | `compounded_growth` (`CompoundedGrowthPanel` + trust strip) | collapse-by-default | Single-tile state on WIPRO/data-limited tickers wastes 250 px. Show CompoundedGrowthTrustStrip always; collapse the panel behind a chevron. | no (strip visible, panel collapsed) | `growth` expands by default |
| 6 | `FinancialStatements` (10-year) | collapse-by-default | Deep table; power-user surface, not first-read. Render header + collapsed body. | no | unchanged |
| 7 | `reverse_dcf` (`ReverseDcfPanel` slider) | promote | The interactive differentiator. Move to numbered slot 3 in DEFAULT and never render the "Not applicable for banks" stub as a numbered section — collapse to a 32 px banner inside the BankKpiTeaser. | yes (when applicable) | `value` keeps mid-list; spec promotes it for DEFAULT and all non-bank styles |
| 8 | `dividends` (`DividendTracker` + trust strip) | keep | Earns its space for dividend payers; auto-collapses for non-payers via existing `has_dividends` check. | yes for payers, hidden otherwise | `income` keeps at slot 2 |
| 9 | `news` (`NewsWidget`) | collapse-by-default | List view; not a first-read. Show 3-headline preview, collapse rest. | no | `speculator` expands |
| 10 | `earnings_calls` (`EarningsCallsWidget`) | collapse-by-default | Same as news. | no | `speculator` expands |
| 11 | `community` (`CommunitySentiment`) | collapse-by-default | Sentiment is a periphery signal. | no | unchanged |
| T1 | `MemoryLane` (trailer) | keep | Auth-only, self-hides; current placement is fine. | n/a | unchanged |
| T2 | `ShareReportCard` + `ProExcelExportButton` | keep | Below-fold trailer is correct location. | n/a | unchanged |
| T3 | `FreshnessStamp` | keep | Footer disclosure. | n/a | unchanged |
| T4 | `SeeAlsoPeers` | keep | Cross-link strip; valuable trailer. | n/a | unchanged |
| T5 | Quality side cards (Piotroski / Moat / Red flags / Strengths / Dividends / Analyst / Insider / Ownership) | collapse-by-default | Currently a wall. Group under a single `Quality detail` accordion with named sub-panels. | no | unchanged |
| T6 | `AnalysisFAQ` | keep | SEO + reassurance. | n/a | unchanged |
| T7 | Model change log + `ModelDisclaimer` | keep | Legal footer. | n/a | unchanged |
| C1 | `EditorialHero` / `StockHeroImage` | collapse-by-default (demoted to slim band — see section 5) | Brand texture, not load-bearing. | n/a (band, not collapsible) | unchanged |
| C2 | `NarrativeSummary` (model-blurb prose) | cut from above-fold; fold into `bulls_bears` lead-in | Burns prime real estate on prose the user does not read first. | n/a | unchanged |
| C3 | `Breadcrumb` / classification chips above tabs | cut | Already duplicated in ticker row and EditorialHero band; redundant. | n/a | unchanged |
| C4 | Share / Compare buttons row above NarrativeSummary | cut | Migrate Share into ticker row icon set (already present); move Compare into AnalysisTabs as a tab-adjacent button. | n/a | unchanged |
| C5 | "MAGM has been renamed to M&M" rename banner | keep but slim | Useful for rename redirects; collapse to a 24 px line under ticker row, not a full-width banner. | n/a | unchanged |
| C6 | `ScoreCard` (standalone mount inside "Confidence and methodology" disclosure) | cut (absorb into HonestHero side rail) | One rail, not two. The Score / Grade / Trend / SectorRank / Refraction / MarketCap tiles merge into HonestHero side rail (§1 Fold 1). ScoreCard.tsx is retired as a standalone mount. The distress-flag grade-cap (`DISTRESS_FLAGS`, `capGrade`) logic moves with it. | n/a | unchanged |

Tally: **5 promoted (sec 1 reclassified as conditional)**, **9 kept**, **8 collapsed-by-default**, **5 cut**.

(Counts: H1, H2, H3, sec 2, sec 3, sec 7 promoted (sec 1 = conditional promote / conditional collapse, counted under the conditional bucket and not double-counted); sec 4, sec 8, T1, T2, T3, T4, T6, T7 kept; sec 5, sec 6, sec 9, sec 10, sec 11, T5, C1, C5 collapsed; C2, C3, C4, C6, + the bank Reverse-DCF stub treatment counted as a cut of the stub-as-numbered-section pattern = 5 cuts.)

### 3.1 Critical anti-pattern: collapse-by-default must NOT touch promoted sections

Implementing agents in Stage 2 must read the table column `Tag`
literally. A blanket `defaultExpanded: false` sweep on the
personalization config would quietly recollapse `honest_card`,
`scenarios`, `reverse_dcf`, `bulls_bears` and undo the redesign.

Stage 2 cluster B (personalization, section 9) owns enforcing that
every `promote` row has `defaultExpanded: true` across ALL five styles
plus the DEFAULT order. The Stage 3 gate (section 10) verifies it.

---

## 4. Section order — new DEFAULT_SECTION_ORDER

Current `DEFAULT_SECTION_ORDER` (legacy, from `lib/personalization.ts`):
```
insight_cards, red_flags, scenarios, bulls_bears, honest_card,
peers, compounded_growth, reverse_dcf, dividends, news, earnings_calls,
community
```

(Note: `insight_cards` and `red_flags` are nulled out for the Summary
tab in `AnalysisBody` — keys retained for picker vocabulary. Order
below reflects the actual rendered subset.)

**Fold 3 — intentional null on `insight_cards` and `red_flags`:** these
two keys appear in `AnalysisBody.tsx`'s `summarySectionMap` only as
nulled-out entries. They are retained on purpose so the personalization
picker's vocabulary (`StylePickerModal`) keeps its complete set of
toggleable terms and existing user style profiles do not break when
loaded. A future agent MUST NOT "discover" that these slots render
nothing and revive them as numbered sections — `insights` is surfaced
through the per-section AnalyticalNotes + HonestCard panels, and red
flags surface through the side-rail `Red flags` tile and the Quality
detail accordion (T5). This is documentation only; no code change.

Proposed new `DEFAULT_SECTION_ORDER`:
```
insight_cards, red_flags,              // (still nulled on Summary tab — vocabulary only; Fold 3 above)
bulls_bears,                           // PROMOTED — usually slot 1, but ceded to scenarios when spread is healthy (see §4.2)
honest_card,                           // PROMOTED — slot 2 — full card, hero teaser previews it
reverse_dcf,                           // PROMOTED — slot 3 — interactive differentiator
scenarios,                             // CONDITIONAL — slot 1 when spread healthy (§4.2), slot 4 (or collapsed) when degenerate
peers,                                 // KEPT — slot 5
compounded_growth,                     // collapsed default — slot 6
dividends,                             // KEPT for payers — slot 7
news,                                  // collapsed default — slot 8
earnings_calls,                        // collapsed default — slot 9
community                              // collapsed default — slot 10
```

Implementing agents in Stage 2 cluster B: the array above is the
NOMINAL order. The `scenarios` slot is dynamic per §4.2 — at render
time, when `isHealthyScenarioSpread(payload) === true`, splice
`scenarios` from slot 4 to slot 1 (and push `bulls_bears` to slot 2,
`honest_card` to slot 3, `reverse_dcf` to slot 4). When the spread is
degenerate, leave the array as-is AND set `defaultExpanded` for
`scenarios` to `false` (the DegradedScenarioCard inside HonestHero
already carries the story; do not also show a collapsed-to-clamp tile
row below the fold).

Justification per move:
- `bulls_bears` to slot 1: dated narrative is one of four named
  differentiators in the audit; absorbing `NarrativeSummary` removes
  the prose-blurb crowding the hero today.
- `honest_card` to slot 2: brand promise. Already at slot 2 in
  `beginner` style — DEFAULT now converges.
- `reverse_dcf` to slot 3: interactive slider is the audit's named
  "actual differentiator, currently sec 7". Stub state (banks) renders
  as a 32 px banner inside the bank KPI teaser, not as a numbered
  section.
- `scenarios` is now CONDITIONAL (Fold 2 — see §4.2 below). When the
  spread is healthy the chart is the primary evidence and slots in at
  the top; when degenerate (WIPRO clamp class) the
  DegradedScenarioCard in HonestHero owns the story and the full
  section collapses by default at slot 4. Honest-broker logic applied
  to section ordering, not just copy.

### 4.2 Scenario prominence — conditional rule (Fold 2)

The first-pass spec demoted `scenarios` to a fixed slot 4. That
implicitly told the reader "the narrative matters more than the model"
even when the model spread is the strongest evidence we have. Replace
the fixed slot with a single conditional rule:

```python
# pseudocode — lives in frontend/src/lib/scenarios.ts alongside isDegradedScenario
_NEAR_CAP_THRESHOLD = 75.0   # any CAGR with |pct| >= 75 is treated as brushing
                              # the backend _SANITY_ABS_CAP=100 ceiling. A value
                              # at/near the cap is almost always a unit-bug /
                              # base-near-zero artifact, not a real move (see
                              # §11.6 + WIPRO -77.1% precedent). Treat near-cap
                              # as IMPLICITLY clamped even when the backend has
                              # not set fair_value_clamped.

def has_suspect_growth_inputs(payload) -> bool:
    """A growth input is suspect when at/near the backend sanity cap. Because
    the cap admits |pct| <= 100, any input within _NEAR_CAP_THRESHOLD of that
    ceiling is treated as implicitly clamped for the purposes of scenario
    promotion. This catches the WIPRO failure mode: degenerate inputs that
    happen to escape the explicit clamp flag but produce a bear/base/bull
    spread that looks healthy on paper while being entirely artificial."""
    cg = payload.compounded_growth or {}
    for metric in ('revenue', 'eps', 'fcf'):
        m = cg.get(metric) or {}
        for horizon in ('3y', '5y', '10y'):
            pct = m.get(horizon)
            if pct is not None and abs(pct) >= _NEAR_CAP_THRESHOLD:
                return True
    return False

def is_healthy_scenario_spread(payload) -> bool:
    v = payload.valuation
    bear, base, bull = v.bear_disc, v.base_disc, v.bull_disc
    if bear is None or base is None or bull is None:
        return False
    if v.fair_value_clamped is True:
        return False                                  # explicit clamp -> not healthy
    if has_suspect_growth_inputs(payload):
        return False                                  # implicit clamp: a near-cap
                                                       # growth input means the
                                                       # spread is built on a
                                                       # suspect figure even if
                                                       # the backend did not flag
    if not (bear < base < bull):
        return False                                  # ordering must hold
    if (bull - bear) < 15.0:                          # 15 percentage points
        return False                                  # spread too tight to be informative
    return True
```

Threshold rationale: 15pp between bear and bull is the operator's
chosen floor. It is wide enough that the three tiles tell genuinely
different stories (e.g. bear -5% / base +25% / bull +40% reads as a
real spread; bear +18% / base +24% / bull +30% reads as model
overconfidence dressed up as three numbers). The explicit `fair_value_clamped`
guard catches payloads the backend already knows are display artifacts.

The `has_suspect_growth_inputs` guard exists because the previous predicate
had a latent bug that defeated its own purpose: it trusted the
`fair_value_clamped` flag and the bear/base/bull spread to detect degeneracy,
but those same numbers can be COMPUTED FROM a suspect input (the WIPRO
-77.1% case — `_SANITY_ABS_CAP=100` admits it, no clamp fires, the
resulting bear/base/bull spread can look healthy while being entirely
artificial). The near-cap input check is the sign-based sanity signal the
hero copy uses, applied here so scenario placement and hero copy degrade in
lockstep. A clamp OR a degenerate input both force the degraded path —
**one predicate, both guards.** A future calibration task (see §11.7) will
revisit the 15pp threshold once the live spread distribution is observable;
the same task should revisit `_NEAR_CAP_THRESHOLD = 75` once the WIPRO
blast-radius diagnosis (§11.6) returns numbers.

Two layouts:

- **Healthy spread (e.g. TCS, HDFCBANK, M&M):** `scenarios` renders
  at numbered slot 1 with the full `FVProjectionFan` (5-year
  projection chart + 24-month actual price tail, from PR-D /
  task #216). It is the primary evidence; everything below supports
  it. `defaultExpanded: true` across all 5 styles.
- **Degenerate / clamped spread (WIPRO-class):** `scenarios` demotes
  to slot 4 AND defaults to collapsed. The `DegradedScenarioCard`
  inside `HonestHero` (§2) carries the scenario story above the fold.
  Rendering the full scenarios panel below would either (a) re-paint
  three identical +200% tiles — the regression we are fixing — or (b)
  re-paint the DegradedScenarioCard, duplicating it.

Personalization interaction:

- `beginner` mode: when degenerate, `defaultExpanded` for `scenarios`
  stays `false` (Beginner already collapses non-default-expanded
  sections, so this is a no-op). When healthy, `scenarios` enters
  Beginner's `defaultExpanded` list alongside `honest_card` and
  `bulls_bears` so the lens to the model is open on first paint.
- `value` style: already keeps `scenarios` in its `defaultExpanded`
  list. The conditional adds a one-line override — when the payload
  is degenerate, the Value lens demotes `scenarios` in line with
  DEFAULT (open scenarios on a clamp would be actively misleading
  for a Value-lens reader). Document this override in
  `personalization.ts` as a comment, not as a separate field — the
  ordering reshuffle in DEFAULT covers it.
- `growth`, `income`, `speculator`: ordering reshuffle in DEFAULT
  cascades through unchanged.
- `accentHue`: no interaction (accent applies only to numbered
  headers and dividers).

### 4.1 Per-style override deltas

- `value` — keep current order, but apply `defaultExpanded` to
  `[scenarios, honest_card, bulls_bears, reverse_dcf]` (add
  `reverse_dcf` so the value lens sees its DCF tool open).
- `growth` — keep current order, add `reverse_dcf` to
  `defaultExpanded` alongside `bulls_bears, compounded_growth`.
- `income` — keep current order; no change to `defaultExpanded`.
- `beginner` — keep current order (already converged on honest-first);
  ensure `defaultExpanded` includes `honest_card, bulls_bears` only
  (current state). `showSectionExplainers` stays true.
- `speculator` — keep current order; `defaultExpanded` adds `scenarios`
  alongside `news, scenarios` (already present).

No `sectionOrder` arrays change for the five styles — only the DEFAULT
changes and `defaultExpanded` arrays get the additions noted above.

---

## 5. EditorialHero treatment — demoted form

Two demotion options. Spec recommends Option B; G1 arbitrates the final
visual in Stage 2 implementation.

### Option A — Slim band above tabs

```
[ HonestHero + side rail occupy first viewport ]
+----------------------------------------------------------+
| [photo 96px tall, blurred edges, ticker title overlay]   |
| Caption: "Wipro Limited — Bengaluru-headquartered IT     |
| services firm. Photo: Wikipedia."                        |
+----------------------------------------------------------+
[ AnalysisTabs ]
```

Pros: photo survives, brand texture intact, clean separation from
HonestHero. Cons: 96 px tax on every desktop view; below 768 the band
hides entirely (already in spec).

### Option B — Side-by-side at desktop (recommended)

```
+--------------------------------+----------------------+
| HonestHero (720 px)            | EditorialHero photo  |
|   verdict / FV / scenarios     |   (320 px x 280 px)  |
|   honest-card teaser           |   ticker title       |
|                                |   "Photo: Wikipedia" |
+--------------------------------+----------------------+
[ Side rail moves to below MiniScoreRow on this option ]
```

Pros: photo coexists with the honest signal, no vertical tax,
ConfidenceIndicators owns visual primary. Cons: image gets cropped on
ticker pages with portrait photos; competes with side rail for the
right column.

Recommendation: **Option B at >=1280, Option A at 1024-1279, both
hidden below 1024.** The right-column slot at >=1280 swaps between
photo (when present) and a neutral classification block (when absent,
e.g. M&M).

**Fold 1 interaction with the absorbed side rail:** at >=1280 the
HonestHero side rail (the absorbed-ScoreCard, §1 Fold 1) is the
authoritative right column. The Option B photo cannot also live there.
Resolution: at >=1280 the rail OWNS the 320 px right column; the
EditorialHero photo demotes to a slim band ABOVE the AnalysisTabs
(Option A geometry — 96 px band) even at >=1280. Option B's
side-by-side photo is dropped from the recommendation; the right
column is too valuable for ornament when the page also has to carry
Score / Moat / Worry / Red flags.

Updated recommendation: **Option A everywhere at >=1024 (96 px slim
band above tabs), photo hidden <1024.** Option B is preserved in the
section only as documentation of an earlier exploration; it is no
longer the recommended state. Stage 2 cluster A builds
`EditorialHeroBand` (Option A geometry) only.

### 5.1 M&M reference (no Wikipedia image)

When `prismResolved.editorial.image_url` is null or
`StockHeroImage` returns null, the demoted slot renders the neutral
classification block instead:

```
NSE  /  Auto - Passenger Vehicles
Large cap  ·  Rs.4.6L Cr mkt cap
[Tier-C Low Confidence chip if conf < 30%]
```

This is effectively the current M&M layout — the audit notes it is
already the closest-to-G1 ticker today. The spec generalises that
treatment.

---

## 6. Mobile @ 390 strip spec

Replaces the current `MobileScoreStrip` (Worry / Score / Moat / Flags).

Exact 4 tiles, left-to-right:

```
[ Verdict ]  [ FV ]            [ Discount ]   [ Worry ]
 UNDERVAL.    Rs.629.52         +200% (clamp)  Elevated
 conf 43%     (clamp)
```

- Verdict pill uses `shouldGateVerdict` (same gate as desktop). When
  gated, renders `Under Review`.
- FV shows the display value with a `(clamp)` chip when
  `fair_value_clamped == true` and a `(low conf)` chip when
  `confidence_score < 30`.
- Discount shows MoS. When the degraded scenario trigger fires
  (section 2.1), renders `+200% (clamp)` with a caution dot.
- Worry tile shows the dial state label (`Normal` / `Elevated` /
  `High`) — no numeric, no dial graphic at 390. Tap opens the full
  WorryIndex panel.

### 6.1 Written order of sacrifice principle

A principle banner lives in `MobileScoreStrip.tsx` as a top-of-file
comment so future contributors cannot unwind it:

```
ORDER OF SACRIFICE (DO NOT REORDER WITHOUT REVIEW):
  1. Drop Score    (quality grade — duplicated in Quality tab)
  2. Drop Moat     (qualitative tag — duplicated in Quality tab)
  3. NEVER drop:   Verdict, FV, Discount, Worry
The brand promise is honesty about RISK and PRICE. Quality grading is
secondary. If the device is too narrow for 4 tiles, drop in the order
above and document the breakpoint.
```

### 6.2 Behaviour when FV is null or clamped

| State | Verdict tile | FV tile | Discount tile | Worry tile |
|---|---|---|---|---|
| Normal | verdict + conf% | Rs.X | +/-X% | label |
| Clamped (WIPRO) | verdict + conf% | Rs.X (clamp) | +200% (clamp) | label |
| `data_limited` | `Under Review` | `--` | `--` | label or `--` |
| `unavailable` | strip hides entirely; error page already covers this |

Tiles never render mock values, never render zero where data is
missing. The dash glyph (`--`) is the canonical empty state.

---

## 7. Personalization handling

The new DEFAULT_SECTION_ORDER is the only change to
`lib/personalization.ts`. Style overrides stay where they are; only
the additions to `defaultExpanded` arrays noted in section 4.1.

Interactions:

- **Beginner mode**: continues to set `showSectionExplainers: true`
  and continues to collapse non-default-expanded sections. The new
  DEFAULT order already leads with `honest_card` at slot 2 and
  `bulls_bears` at slot 1, so Beginner's view converges to DEFAULT
  more than today (currently Beginner re-orders to honest-first;
  with DEFAULT also honest-first, the only Beginner-unique behaviour
  is explainers + collapse-non-defaults).
- **Value / Growth / Income / Speculator**: ordering unchanged, but
  `defaultExpanded` gains `reverse_dcf` for value/growth and
  `scenarios` for speculator. This guarantees the promoted slider is
  open by default for the personas it serves.
- **`accentHue`**: stays subtle. The audit noted accent did not
  register in captures — that is acceptable. The accent applies only
  to numbered headers, dividers, and the personalization chip. Verdict
  cascade still owns the hero. **Do not amplify the accent into the
  HonestHero**; the verdict colour cascade is the visual primary and
  must not compete with a persona hue.
- **First-visit modal gate**: unchanged. Still fires after 3+ ticker
  visits for signed-in users only.

---

## 8. Before / after sketch — WIPRO @ 1440

```
BEFORE (audit capture)                         AFTER (spec)
----------------------------------             ----------------------------------
[ navbar ]                                     [ navbar ]
[ TickerStrip indices marquee ]                [ TickerStrip slim 28 px ]
[ AdrCohortBanner Data Limited ]               [ AdrCohortBanner slim 32 px ]
[ ticker row WIPRO + buttons ]                 [ ticker row WIPRO + buttons ]
[ sticky rail (L) | EditorialHero (R) ]        +-------------------+------------+
[ H1 + classification chips ]                  | HonestHero        | side rail  |
[ Share / Compare buttons ]                    |  verdict pill     |  Score 40  |
[ NarrativeSummary prose card ]                |  FV Rs.629.52     |  Moat None |
[ ConfidenceIndicators ]                       |   (clamp note)    |  Flags 4   |
   (fold ends ~720 px here, no verdict yet)    |  DegradedScenario |  Worry Elev|
[ AnalyticalNotes clamp caution ]              |   - spread bounds |  ---       |
[ AnalysisTabs ]                               |   - value trap    |  Honest >  |
[ WorryIndex ]                                 |   - see notes     |  Reverse > |
[ 1. VALUATION SCENARIOS                       +-------------------+------------+
    bear +200% | base +200% | bull +200% ]     [ EditorialHero slim band 96 px ]
[ 2. BULL / BEAR THESIS ]                      [ AnalysisTabs ]
[ 3. HONEST CARD ]                              (fold ends ~720 px here, hero done)
[ 4. PEERS ]                                   [ 1. BULL / BEAR THESIS ]
[ 5. COMPOUNDED GROWTH (1 tile) ]              [ 2. HONEST CARD (full) ]
[ 6. FINANCIAL STATEMENTS ]                    [ 3. REVERSE DCF (slider) ]
[ 7. REVERSE DCF (slider) ]                    [ 4. VALUATION SCENARIOS ]
[ 8. DIVIDENDS ]                               [ 5. PEERS (collapsed, 3-preview)]
[ 9. NEWS ]                                    [ 6. COMPOUNDED GROWTH (collapsed)]
[10. EARNINGS CALLS ]                          [ 7. FINANCIAL STATEMENTS (coll.) ]
[11. COMMUNITY ]                               [ 8. DIVIDENDS ]
                                               [ 9. NEWS (3-preview, collapsed) ]
                                               [10. EARNINGS CALLS (collapsed) ]
                                               [11. COMMUNITY (collapsed) ]
```

Win: verdict + FV + clamp disclosure + value-trap caveat + Worry are
above the fold. Three identical "+200%" tiles are replaced by one
honest `DegradedScenarioCard`. Section count is unchanged — the page
re-orders and collapses, no functionality is removed.

---

## 9. Stage 2 cluster plan

Six clusters. Cluster A (shared primitives) MUST land first and be
merged to the redesign branch before clusters B-F begin parallel work.
File ownership is disjoint — no file appears in two clusters.

### Cluster A — Shared primitives (BLOCKING, must merge first)

Owns:
- `frontend/src/components/analysis/HonestHero.tsx` (new — includes the
  absorbed-ScoreCard side rail per §1 Fold 1; preserves the
  `DISTRESS_FLAGS` / `capGrade` distress-flag grade-cap logic from
  `ScoreCard.tsx`)
- `frontend/src/components/analysis/DegradedScenarioCard.tsx` (new)
- `frontend/src/components/analysis/MobileScoreStrip.tsx` (new — replaces inline strip in AnalysisBody; reads from `useHeroSignals` so it cannot drift from HonestHero)
- `frontend/src/components/analysis/EditorialHeroBand.tsx` (new — demoted form, Option A only)
- `frontend/src/components/analysis/BankKpiTeaser.tsx` (new — for HDFCBANK hero footer)
- `frontend/src/lib/scenarios.ts` (new — exports
  `isDegradedScenario(payload): boolean` matching §2.1,
  `isHealthyScenarioSpread(payload): boolean` matching §4.2, and
  the `useHeroSignals(payload)` hook that returns the single
  source-of-truth bag consumed by both HonestHero side rail and
  MobileScoreStrip — see §1 Fold 1)
- `frontend/src/components/analysis/ScoreCard.tsx` — RETIRED at the
  end of Stage 2 (file deletion handled by cluster A in the same PR
  that lands `HonestHero.tsx`, after grep confirms no other surface
  imports it)

### Cluster B — Personalization + section order

Owns:
- `frontend/src/lib/personalization.ts` (DEFAULT_SECTION_ORDER + defaultExpanded edits per section 4.1)
- `frontend/src/components/personalization/CollapsibleSection.tsx` (verify `defaultExpanded` propagation for promoted sections)
- `frontend/src/components/personalization/StylePickerModal.tsx` (no behaviour change; verify vocabulary still SEBI-clean)
- `frontend/src/components/personalization/PersonalizationBanner.tsx`

### Cluster C — AnalysisBody chassis re-wire

Owns:
- `frontend/src/app/(app)/analysis/[ticker]/AnalysisBody.tsx`
- `frontend/src/app/(app)/analysis/[ticker]/page.tsx`
- `frontend/src/app/(app)/analysis/[ticker]/AnalysisAuthGate.tsx`

Wires HonestHero (from A), MobileScoreStrip (from A), EditorialHeroBand
(from A) into the Summary tab. Cuts the prose `NarrativeSummary`
above-fold render and folds it into `BullsBearsPanel` as a lead-in.
Cuts Breadcrumb classification chips row, Share/Compare row.

### Cluster D — Scenarios + Reverse-DCF promotion

Owns:
- `frontend/src/components/analysis/FVProjectionFan.tsx` (consume `isDegradedScenario`; render `<DegradedScenarioCard>` when true)
- `frontend/src/components/analysis/ReverseDcfPanel.tsx` (slot 3 default-expanded; bank stub becomes a 32 px banner inside BankKpiTeaser, NOT a numbered section)
- `frontend/src/components/analysis/CompoundedGrowthPanel.tsx` (collapse-by-default with trust strip always visible)
- `frontend/src/components/analysis/CompoundedGrowthTrustStrip.tsx`

### Cluster E — Bull/Bear + Honest Card + NarrativeSummary fold-in

Owns:
- `frontend/src/components/analysis/BullsBearsPanel.tsx` (absorb NarrativeSummary as lead-in paragraph)
- `frontend/src/components/analysis/HonestCard.tsx` (add 2-line teaser export for HonestHero)
- `frontend/src/components/analysis/NarrativeSummary.tsx` (becomes a sub-component, no longer rendered standalone — keep file for the BullsBearsPanel import)

### Cluster F — Trailer compaction

Owns:
- `frontend/src/components/analysis/NewsWidget.tsx` (3-headline preview + collapse)
- `frontend/src/components/analysis/EarningsCallsWidget.tsx` (collapse)
- `frontend/src/components/analysis/CommunitySentiment.tsx` (collapse)
- `frontend/src/components/analysis/FinancialStatements.tsx` (collapse)
- `frontend/src/components/analysis/InlinePeerComparison.tsx` (3-peer preview + collapse)
- Quality side cards: group under a new `frontend/src/components/analysis/QualityDetailAccordion.tsx`

No file overlap across clusters. Cluster A blocks the rest; B-F can run
in parallel after A merges.

---

## 10. Cross-cutting gates for Stage 3

### 10.1 G1 proof (no second scroll)

- Chrome DevTools MCP capture matrix: 4 breakpoints (390, 768, 1024,
  1440) x 4 tickers (TCS, HDFCBANK, M&M, WIPRO) = 16 captures.
- Each capture must visibly contain, above the fold:
  verdict pill, FV figure (or clamp pill), discount-to-FV figure (or
  DegradedScenarioCard), Worry signal.
- Captures stored at `redesign/screenshots/post/` with the same naming
  convention as Stage 0.
- Pass = 16/16. Anything less blocks Stage 3 merge.

### 10.2 Personalization regression

- Render all 5 styles on TCS @ 1440. No render errors, no missing
  sections, no broken collapse states.
- `defaultExpanded` enforcement check: `honest_card`, `bulls_bears`,
  `reverse_dcf` (when applicable) must be expanded by default across
  every style. Automated via a unit test in
  `frontend/src/lib/__tests__/personalization.test.ts` (new).

### 10.3 Mobile (390) strip

- All four tiles render on TCS, HDFCBANK, M&M, WIPRO @ 390.
- WIPRO Discount tile shows `+200% (clamp)` with caution dot.
- HDFCBANK strip carries FV (the audit noted FV is missing today —
  this is a regression check).

### 10.4 Accessibility

- Run `web.dev` a11y skill against TCS @ 1440 and WIPRO @ 390.
- Verify semantic structure: HonestHero is `<section aria-labelledby>`
  with the verdict as the heading. DegradedScenarioCard has
  `role="status"` with the caveat as the accessible name.
- Tap targets on MobileScoreStrip tiles >= 40 px.
- Colour contrast on the clamp pill, caution dot, and verdict pill
  meets WCAG AA on both light and dark themes.

### 10.5 Performance (LCP)

- Today's LCP element is typically the EditorialHero photo. With
  EditorialHero demoted to a slim band (Option B side-by-side at 1280+),
  the new LCP candidate is the HonestHero verdict pill text
  (server-rendered) or the side photo (if Option B fires).
- Measurement gate: capture LCP via Chrome DevTools performance trace
  on TCS, HDFCBANK, M&M, WIPRO @ 1440. New LCP must be <= 2.5 s on
  cable throttling. Regression budget: do not exceed current LCP by
  more than 200 ms.
- If side photo becomes LCP, set `fetchpriority="high"` on it.

### 10.6 SEBI-lint

- Run `python scripts/check_sebi_words.py` against all touched files.
- Note: PR #695 and #693 surfaced false-positive patterns where
  `should` matches inside JSX prop names (`shouldGateVerdict`) and
  inside utility function names. Stage 3 must verify the script
  excludes identifier matches or, if it does not, document each
  flagged line as a known false positive in the PR description.
- The new copy in `DegradedScenarioCard` (section 2.2) is pre-checked
  but must run through the lint again post-implementation.

### 10.7 Visual regression

- Generate side-by-side diffs against the 20 Stage 0 screenshots for
  the four tickers x four breakpoints.
- Diff tool: any pixel-diff tool with a threshold mask for the
  scorecard rail (which intentionally moves).
- A separate diff for the WIPRO @ 1440 case showing the
  three-identical-tiles state replaced by `DegradedScenarioCard` —
  this is the marquee win and goes in the PR description.

### 10.8 Canary-diff (data discipline)

Per root `CLAUDE.md` rule 1: even though this redesign does not touch
`backend/services/` or engine code, the AnalysisBody change consumes
`fair_value_clamped` and the degraded-scenario trigger reads
`bear/base/bull mos_pct`. Run `python scripts/canary_diff.py` once
against main and confirm 0 unexpected payload diffs.

---

## 11. Out of scope — Stage 1 follow-ups

These items were surfaced during spec authoring but do not belong in
this redesign. They are flagged for separate tracking.

1. **Re-verify WIPRO clamp + `data_limited` tracker drift** (tracker
   #244). The audit observed WIPRO renders an `Undervalued` verdict
   with a 3x clamp; tracker #244 has it as `data_limited`. One of the
   two is stale. Engine workstream owns the re-verification; this
   redesign treats the clamped-flat state as a UI rendering problem
   and ships the `DegradedScenarioCard` regardless of which side
   wins. **Cluster: valuation engine. Owner: TBD.**

2. **First-visit StylePickerModal cold-load on cleared localStorage**.
   The picker modal triggered on WIPRO when localStorage was cleared
   during the audit. The current 3-visit gate works for steady-state
   users but cold visitors hit the modal on what may be their first
   ever ticker. Out of scope for the analysis-page redesign; belongs
   in onboarding workstream.

3. **`canary.yml` flake on Aiven rate limits** (per root `CLAUDE.md`).
   Stage 3 PR may hit this; admin-merge is permitted under the
   documented carve-out.

4. **`/search` page Suspense bailout** (per root `CLAUDE.md`). Pre-
   existing, unrelated to this redesign; flagged so Stage 3 does not
   chase it.

5. ~~Sticky `ScoreCard` rail at 1024+~~ — **RESOLVED in this spec via
   Fold 1 (§1).** ScoreCard is absorbed into HonestHero's side rail;
   there is no longer a follow-up to file. Bullet retained as a
   strikethrough so reviewers can see the resolution and not re-file
   the same item.

6. **WIPRO compounded growth integrity — defended in spec §1 hero copy
   but underlying compute is suspect.** Verification gate B (this
   spec) re-ran the maths on the audit's -77.1% revenue CAGR claim:
   `cagr_service.py::_cagr` admits any value with `abs(pct) <= 100.0`
   and both endpoints `> 0`. A -77.1% 3y or 5y CAGR for a Tier-1 IT
   services firm with ~Rs.90,000 Cr revenue is not real-world
   plausible; the figure most likely originated from a unit / scale
   mismatch (e.g. partial-year revenue compared to a full-year, or a
   USD-INR mix-up on ADR cohort, in line with task #232 / #244 / #83
   history). The hero copy has been rewritten to a qualitative
   "shrinking revenue trend" phrase that survives the lint AND does
   not depend on the suspect number. **Follow-up tracker for engine
   workstream: instrument `cagr_service` to log inputs and outputs
   when |CAGR| > 50% so the compute can be retroactively audited.
   Owner: backend engine workstream. NOT a Stage 2 cluster task.**

8. **Promote `fair_value_clamped` to a typed field on `ValuationOutput`**
   (Agent B contract pass). The Stage 2 primitives agent
   (`feat/redesign-stage2-primitives-v2`) currently reads the clamp
   signal via a string marker scan on `data_issues` (looking for
   "Fair value clamped" substring) because the typed flag does not
   exist on `ValuationOutput`. A string-marker guard silently breaks
   when someone reworks `data_issues` copy. **Fold into Agent B's
   next contract pass: add `fair_value_clamped: bool` as a typed
   field on `ValuationOutput`, set it at compute time alongside the
   existing `data_issues` append, and update `useHeroSignals` /
   `isHealthyScenarioSpread` / `DegradedScenarioCard` trigger to
   read the typed flag with the string scan as a deprecated
   fallback.** Same contract pass should also thread
   `compounded_growth` onto `AnalysisResponse` (per §4 latent gap)
   so `has_suspect_growth_inputs` arms its second half. Owner:
   Phase 1 Agent B. NOT a Stage 2 cluster task.

7. **Calibrate the scenario-spread threshold against the live
   distribution (post-launch).** The 15pp `bull_disc - bear_disc`
   threshold and the 75pp `_NEAR_CAP_THRESHOLD` in `is_healthy_scenario_spread`
   are both currently operator-chosen defaults — reasonable middles
   chosen without sight of the actual distribution across the ~250-name
   universe. The risk of the 15pp default: stable low-volatility names
   (regulated utilities, large-cap FMCG) may legitimately produce
   spreads under 15pp and would be wrongly demoted to slot 4. The risk
   of the 75pp default: too tight rejects real cyclical swings; too
   loose lets WIPRO-class artifacts through. **Calibration task,
   post-launch:** compute the empirical distribution of (a) `bull_disc -
   bear_disc` across all tickers in the canary 180 universe and (b)
   `max(|cg.revenue|, |cg.eps|, |cg.fcf|)` across the same set. Set
   the spread threshold at the elbow that genuinely separates degenerate
   spreads from merely-narrow ones; set the near-cap threshold at the
   99th-percentile of legitimate large moves cross-checked against
   raw history. Single-source both constants in `lib/scenarios.ts` so
   the change is one-line. Owner: redesign workstream, deferred to
   after the §11.6 diagnosis returns. NOT a Stage 2 cluster task.

---

## 12. PR-C reconcile log

The orphan diff at `redesign/pr-c-orphan.diff` is 9 modified files,
0 commits ahead of main, captured from worktree
`E:\Projects\yieldiq_v7\.agent-worktrees\design-pr-c-retry` (task
#259, "PR-C section-by-section restyle"). For each file, the diff
intent is classified against this Stage 1 spec.

Classification key: **(a) SUPERSEDED** — spec already covers this
intent; **(b) PARTIALLY SUPERSEDED** — spec covers most but missed
something specific; **(c) NOT SUPERSEDED** — genuine new intent the
spec missed.

| # | File | Class | Spec section(s) covering it / action taken |
|---|---|---|---|
| 1 | `AnalysisBody.tsx` | (a) SUPERSEDED | The diff introduces a "minimal hero + 'How we got here' disclosure" pattern. The spec's HonestHero (§1, §1.1) is a fuller, more honest version of the same idea (verdict + FV + clamp + worry + caveat, not just verdict + FV). The diff's `<details>` "How we got here" disclosure is also superseded by §1's promotion of ConfidenceIndicators into HonestHero and the existing "Confidence and methodology" disclosure (which the spec keeps). The retired `Compare ->` link-out matches spec §3 row C4. The retired `MetricVsSectorChip` above `CompoundedGrowthPanel` is preserved-with-relocation in PR-C diff and matches spec §3 row 5 (collapse-by-default with trust strip always visible). No spec change. |
| 2 | `BullsBearsPanel.tsx` | (b) PARTIALLY SUPERSEDED | Spec §3 row 2 and §4 promote `bulls_bears` and have it absorb `NarrativeSummary`. The DIFF adds two further intents not in the spec: **(i)** wrap each side (Bull / Bear) in its own `NarrativeCard` shell (PR-B card primitives), and **(ii)** stamp each card with an "Updated {date}" footer that falls back to today's IST-format date when the backend has no `thesis_updated`. Fold into spec §9 cluster E ownership notes: BullsBearsPanel SHOULD adopt the NarrativeCard shell from PR-B primitives AND render an "Updated" stamp per side, using `thesis_updated` when present and falling back to render-time IST long-form date when absent. Stage 2 cluster E reads this entry. |
| 3 | `CompoundedGrowthPanel.tsx` | (a) SUPERSEDED | The diff adds a `sectorMedians` prop to thread cohort medians through to the sparklines. Spec §3 row 5 already calls for `CompoundedGrowthTrustStrip` to always render and the panel to collapse. The sector-median plumbing is an internal refactor of how the panel renders its own tiles; it does not change the section's grading or default-expanded state. The intent fits inside cluster D ownership (which already owns CompoundedGrowthPanel). No spec change beyond a note in §9 cluster D that the panel's tiles surface inline sector-median chips when available. |
| 4 | `CompoundedGrowthSparklines.tsx` | (b) PARTIALLY SUPERSEDED | Same as #3 — companion change. Adds per-tile `MetricVsSectorChip` rendering when `sectorMedians.roe` is non-null; other tiles render without a chip. Spec §3 row 5 covers the collapse + trust-strip behaviour but does not mention per-tile cohort chips. **Folded into spec §9 cluster D ownership notes: each sparkline tile surfaces an inline sector-median chip when the matching cohort median is present and finite; silently self-hides otherwise. No "vs sector --" rendering.** |
| 5 | `DividendBarChart.tsx` | (a) SUPERSEDED | Pure PR-B primitives migration (`div.bg-surface...` → `<DataCard hover={false}>`). Spec §3 row 8 keeps dividends and §9 cluster F owns the file. The card-shell migration is implementation polish for cluster F. No spec change. |
| 6 | `FinancialsChartPanel.tsx` | (c) NOT SUPERSEDED | The diff adds a plain-English caption above the annual chart (e.g. "Revenue growth accelerated in the latest fiscal year." / "Margins compressed N bps in the latest fiscal year." / fallback "Financial performance over the last N fiscal years."). This is a genuine new intent — the spec never proposes a generated descriptive caption for the financials chart. **Folded into spec §9 cluster F ownership notes: `FinancialsChartPanel` renders a one-line plain-English caption above the chart, derived from the two most recent annual rows (revenue YoY for the > 15% accelerator, operating-margin bps delta for the < -100bps compression call-out; otherwise the neutral fallback). All wording must clear the SEBI lint — no `should` / `appears` / etc. The diff's three captions all clear today.** |
| 7 | `HonestCard.tsx` | (a) SUPERSEDED | Migrates the outer `<section>` to a `NarrativeCard` shell with an "THE HONEST CARD" eyebrow. Spec §3 row 3 promotes honest_card to numbered slot 2 + adds a hero teaser. The card-shell migration is implementation polish; the eyebrow ("THE HONEST CARD") is consistent with cluster E ownership and §1's hero teaser. No spec change. |
| 8 | `InlinePeerComparison.tsx` | (a) SUPERSEDED | Migrates EmptyState / LoadingSkeleton / main section to `DataCard`. Spec §3 row 4 keeps peers (with collapse-by-default) and §9 cluster F owns the file. Card-shell migration only. No spec change. |
| 9 | `ReverseDcfPanel.tsx` | (a) SUPERSEDED | Migrates both the "applicable false" stub and the main panel to `NarrativeCard` with "REVERSE DCF" eyebrow. Spec §3 row 7 promotes reverse_dcf to numbered slot 3 AND collapses the bank stub to a 32 px banner inside `BankKpiTeaser`. **Note for cluster D:** the diff's `NarrativeCard` wrapping of the `applicable === false` stub is INCONSISTENT with the spec's plan to retire that stub as a numbered section entirely. Cluster D should NOT preserve the diff's NarrativeCard wrapping for the bank stub; the bank stub becomes part of `BankKpiTeaser` (cluster A). For the regular (applicable === true) Reverse-DCF panel, the NarrativeCard shell migration is fine. |

Folded items count: **3** (rows 2, 4, 6 — one (b)+(b)+(c); rows 6's NarrativeCard inconsistency on the bank stub is a NEGATIVE fold, captured as a "do not do this" note in cluster D ownership rather than as a new intent).

Worktree disposition: the worktree at
`E:\Projects\yieldiq_v7\.agent-worktrees\design-pr-c-retry` is NOT
deleted by Stage 1. Operator-triggered follow-up. Stage 2 cluster
agents will re-implement the (b) and (c) intents against the merged
spec rather than rebasing this orphan diff.

---

## 13. Exit criteria for Stage 1 to Stage 2 handoff

A Stage 2 cluster agent may begin work when ALL of the following are
true:

- This spec file exists at `E:\Projects\yieldiq_v7\redesign\spec.md`
  and the operator has marked it APPROVED.
- The operator has confirmed the EditorialHero demotion recommendation
  (Option B at 1280+, Option A at 1024-1279) OR has selected an
  alternative.
- The operator has confirmed the new `DEFAULT_SECTION_ORDER` (section
  4) OR has issued specific edits.
- The operator has confirmed the mobile strip composition + order of
  sacrifice principle (section 6).
- The follow-up tracker for WIPRO clamp + #244 drift (section 11.1)
  has an owner assigned in the valuation workstream.
- The Stage 2 cluster A agent has read this spec end-to-end and
  acknowledged the file-ownership contract (section 9).

No code, no migrations, no PR has been opened in service of this
spec. All implementation is deferred to Stage 2.

---

## 14. Phase 1 dependency chain (added 2026-06-03)

The FV-history audit chain surfaced (via the WIPRO §11.6 diagnosis,
the FV-history sanity gate agent's universe-wide event
characterization, and the operator's per-category disposition
reasoning) that the persisted `fair_value_history` table holds dozens
of poisoned rows from two distinct undocumented engine events
(2026-04-29 unit-error spikes; 2026-05-17 universe-wide regime
shift), both pre-dating the manifest epoch (`v_init_2026_05_22`).

Cluster D in this redesign renders whatever the
`/api/valuation-history/<ticker>` endpoint returns. If that endpoint
serves the poisoned rows, the redesign's most-scrutinized trust
feature ships broken on day one. The serve-time gate
(`fix/phase1-fv-history-sanity-gate`, agent `aaf78f86`) is
defensive — but the table holds the poison at rest, which means raw
readers (admin tools, Alerts, prism_service, any future feature)
re-eat it, and Agent A v3's superset migration touches those rows
in place.

**The conclusion is a hard dependency chain that reorders Phase 1
itself.** Cluster D is now the LAST thing to dispatch in the
redesign, behind the entire clean-data chain. Specifically:

1. **At-rest quarantine column lands** (`quarantine_reason` /
   `quarantined_at` / `quarantine_source` on
   `fair_value_history`). Disposition diagnosis in flight at
   `redesign/followups/fv-history-at-rest-disposition.md`; once that
   diagnosis returns, the column ships as a separate small migration
   on the valuation workstream.
2. **Agent A v3 superset migration lands** carrying the quarantine
   columns AND respecting the no-recompute-pre-epoch precondition
   from the disposition diagnosis. The migration's data-fill step
   sets `quarantine_reason='pre_manifest_epoch'` on all rows dated
   before 2026-05-22.
3. **`fix/phase1-fv-history-sanity-gate` merges** — canary now green
   for the right reason (the rows the gate would have filtered are
   already marked at rest). Admin-merge via known-flaky carve-out is
   forbidden here; the gate must prove correctness on a clean table.
4. **Agent B's endpoint goes live** serving rows filtered by both
   `quarantine_reason IS NULL` (at-rest defense) and the serve-time
   gate (belt-and-braces).
5. **Cluster D dispatches** — renders gated, clean data. This is
   the LAST cluster to dispatch in the redesign. Clusters A / B / C
   / E may dispatch any time after the shared-primitives branch
   lands; Cluster D waits for steps 1-4 above.

This is not scope creep. It is the trust feature refusing to ship
on poisoned data — which is the feature working as designed. The
sequencing must be explicit so no implementation agent dispatches
Cluster D the moment primitives lands and wonders why the chart is
rendering quarantined rows.

Cross-references:
- `redesign/followups/wipro-cagr-blast-radius.md` (§11.6 diagnosis,
  identified the WIPRO step)
- `redesign/followups/fv-history-event-2026-05-17.md` (universe-wide
  event characterization, ~10 tickers stepped 5/17 + 5 tickers
  spiked 4/29, both events 100% artifact except 1 inconclusive)
- `redesign/followups/financials-table-reconciliation.md` (the
  upstream `company_financials` populator bugs that feed the engine
  events — 64 of 333 tickers flagged, 41 traceable to one
  `db_writer.py` ON CONFLICT bug)
- `redesign/followups/fv-history-at-rest-disposition.md` (in
  flight — the schema delta + A-v3 precondition)
- `CLAUDE.md` Manifest invariants section (added 2026-06-03 —
  contemporaneous-only corroboration rule that locks step 3 against
  the easy-out "just add a backdated manifest entry to make canary
  green")

STAGE 1 COMPLETE — AWAITING OPERATOR REVIEW BEFORE STAGE 2.
