# YieldIQ Analysis Page — Stage 0 Audit

**Date:** 2026-06-02
**Stage:** 0 (audit only — no code changes)
**Auditor:** Claude (automated capture + scoring)

---

## 1. Methodology

Drove Chrome DevTools MCP through the production site at `https://yieldiq.in/analysis/<TICKER>.NS` while authenticated. For each of four edge-case tickers (TCS, HDFCBANK, M&M, WIPRO) captured the page top viewport at four breakpoints (1440, 1024, 768, 390) and additionally a `~80%` scroll on the two most-instrumented tickers (TCS, HDFCBANK at 1440) to validate sticky-rail persistence. Two Beginner-mode captures (TCS, HDFCBANK at 1440) confirm the personalization reorder.

Captures are stored at absolute path `E:\Projects\yieldiq_v7\redesign\screenshots\` (20 PNGs).

Scoring is against the four north-star gates G1 (no second scroll), G2 (density without clutter), G3 (one honest-broker voice), G4 (scannability).

**Note on auth state:** the test session is logged in. The bare `/analysis/TCS` form 302-redirects to `/home`; canonical URL is `/analysis/<TICKER>.NS`. All captures use the `.NS` form.

---

## 2. Current section inventory

Route module: `E:\Projects\yieldiq_v7\frontend\src\app\(app)\analysis\[ticker]\page.tsx` (server shell) → `AnalysisAuthGate.tsx` → `AnalysisBody.tsx` (auth users).

The Summary tab renders (DOM order on default style):

| # | Section | Key data points observed |
|---|---|---|
| — | `TickerStrip` | Indices + watchlist marquee |
| — | `AdrCohortBanner` | Data Limited banner for ADR cohort (TCS, WIPRO) |
| — | Compact ticker row | Ticker + price + Time-Machine/Save/Alert/Share buttons |
| — | Sticky **`ScoreCard`** complementary rail (1024+ only) | Verdict pill, Price, FV+conf, Discount, Worry, Score, Moat, Red flags, "Tell me the story" CTA |
| — | `EditorialHero` / `StockHeroImage` | Hero image strip with UNDERVALUED pill + market cap |
| — | `Breadcrumb` / classification chips | NSE / sector / cap |
| — | Share / Compare buttons + `NarrativeSummary` model-summary blurb | Long literal "Model-generated description …" paragraph |
| — | `ConfidenceIndicators` (Valuation summary region) | Verdict heading, FV ± band, confidence %, current price, discount, alert radios, Prism Spectrum |
| — | `AnalyticalNotes` (conditional) | "Fair value clamped — data quality" (WIPRO) |
| — | `AnalysisTabs` | Summary / Valuation / Quality / Financials / History / Peers |
| — | `WorryIndex` (always-on, ABOVE the numbered list) | Worry dial + drivers |
| 1 | `scenarios` — DCF bear/base/bull + 5y projection chart |
| 2 | `bulls_bears` thesis (paragraph format) |
| 3 | `honest_card` (confident / best estimate / could-be-wrong / would-change-our-verdict) |
| 4 | `peers` table |
| 5 | `compounded_growth` (CAGR tiles + ROE-vs-sector) |
| 6 | `FinancialStatements` 10-year (additional, not in personalization sectionOrder) |
| 7 | `reverse_dcf` (sliders or "Not applicable for banks" stub) |
| 8 | `dividends` |
| 9 | `news` (BSE / Reuters filings) |
| 10 | `earnings_calls` (NSE filings) |
| 11 | `community` view (sentiment voting) |
| — | `MemoryLane` (auth-only) |
| — | Share report card + Excel-Pro download |
| — | `FreshnessStamp` disclosure |
| — | `SeeAlsoPeers` strip |
| — | Quality side cards (Piotroski / Moat / Red flags / Strengths / Dividends / Analyst / Insider / Ownership) |
| — | `AnalysisFAQ` |
| — | Model change log + disclaimer |

Total: ~14 above-numbered-list chrome rows + 11 numbered personalized sections + 7 below-section trailer rows. **Long page** — 12,067 px tall on HDFCBANK @ 1440, 12,534 px on TCS @ 1440.

The section title for `reverse_dcf` is rendered for banks too (HDFCBANK), with body "Not applicable for banks." — clean degradation but the numbered header still occupies vertical real estate.

---

## 3. Personalization layer summary

From `E:\Projects\yieldiq_v7\frontend\src\lib\personalization.ts`:

- **5 styles:** value, growth, income, beginner, speculator. Persisted as `yq:investing-style` localStorage key (NOT `yieldiq:style` as the brief assumed).
- **`DEFAULT_SECTION_ORDER`** (no style picked) = `insight_cards, red_flags, scenarios, bulls_bears, honest_card, peers, compounded_growth, reverse_dcf, dividends, news, earnings_calls, community`. (Observed: this is the rendered order today on TCS / HDFCBANK / M&M / WIPRO with no style set, though `insight_cards` and `red_flags` keys don't appear as numbered sections on the captured pages — only ten numbered regions appear, suggesting some keys map to other surfaces or are skipped.)
- Each style reorders the 12 keys and sets `defaultExpanded` (3-ish sections kept expanded). Beginner additionally sets `showSectionExplainers: true`, which renders a `What this means` expander per section header and collapses non-default-expanded sections.
- `accentHue` per style (emerald / amber / sky / rose / slate) is plumbed but its visual effect was not loud enough to register in captures.

**Confirmed working in capture:** beginner reorder lands Honest Card as `1.` and Bull/Bear as `2.`, with peers / scenarios / growth / financials / dividends / news / reverse-dcf / earnings / community all collapsed. The `What this means` expander appears next to each section header.

---

## 4. Per-ticker findings

### TCS (UNDERVALUED, +40.5% disc, conf 67%, ADR-cohort flag)
- Screenshots: `TCS_1440.png`, `TCS_1024.png`, `TCS_768.png`, `TCS_390.png`, `TCS_1440_bottom.png`, `TCS_1440_beginner.png`.
- **First viewport at 1440:** YieldIQ navbar + indices marquee + "Data Limited" banner + ticker price row + green divider + sticky scorecard rail (left, ~280 px wide) + H1 "Tata Consultancy Services" + classification chips + Share/Compare buttons + the `NarrativeSummary` literal model-blurb. **No verdict pill, no FV figure, no discount figure, no Worry dial visible above the fold.** Scorecard rail does contain FV ₹3,438 and +40.5% disc — but it's small, ~14 px, and competes with seven other tiles in the rail.
- Mobile @ 390: collapsed scorecard strip is a pill row (Worry · Normal | Score · 50/100 | Moat · Wide | Flags · 3) above ticker. Below the fold: H1, classification chips, NarrativeSummary blurb. Verdict pill **not** in first viewport.
- Discount = +40.5%, FV ₹3,438 — i.e. TCS is NOT the "+50%" deep-undervalued state the brief expected (brief was a guess). Verdict is honest and clean.

### HDFCBANK (UNDERVALUED, +53.4% disc, conf 90%, banking — Reverse-DCF stubs cleanly)
- Screenshots: `HDFCBANK_1440.png`, `HDFCBANK_1024.png`, `HDFCBANK_768.png`, `HDFCBANK_390.png`, `HDFCBANK_1440_bottom.png`, `HDFCBANK_1440_beginner.png`.
- Same first-viewport composition as TCS minus the ADR banner. EditorialHero with bank image renders.
- **Reverse-DCF gracefully degrades:** the section header still says "7. REVERSE DCF" with body "Not applicable for banks. Banks, NBFCs and insurers use ROE / RoA / NIM instead of FCF-based valuation. See the Quality panel for those metrics." No broken slider, no zero state. Good. But the section consumes ~140 px for one line of explanatory text — wasted real estate.
- BankKpiPanel not visible above-section-list (existed in import, may render on the Quality tab).
- Bottom screenshot (`HDFCBANK_1440_bottom.png`) shows sticky scorecard **persists** beautifully (verdict pill + FV + disc + Worry + Score + Moat + Red flags + "Tell me the story" CTA still visible at scroll depth ~9.6k px / 80%). G3 evidence persists. The Community section is right next to it.

### M&M (FAIRLY VALUED, +6.4% disc, conf 16%, cyclical with peak-FCF normalization)
- Screenshots: `MM_1440.png`, `MM_1024.png`, `MM_768.png`, `MM_390.png`.
- **No EditorialHero image** (cyclical / no Wikipedia image registered) — falls back to a plain valuation card with "YieldIQ Score · model estimate" headline + tier-C "Low Confidence" chip. This is actually a more compact and arguably clearer hero than the image-bearing tickers.
- "MAGM has been renamed to M&M. Showing M&M data." rename-redirect breadcrumb shown — good but uses prime first-viewport vertical space.
- Cyclical normalization (post-PR #671) lands a labelled `off-scale — likely trough-margin distortion` warning in the Reverse-DCF section with "≥ 50.0% (off-scale)" implied growth. Solver-bound semantics are visible to the user. **Differentiator (honest broker) actually showing up where it should.** But it's at section 7 of 11, well below the fold.
- 1440 first viewport DOES include the score/FV/discount/moat strip (compact 4-card grid) because the EditorialHero is replaced by a smaller card. This is the only ticker where G1 is close to passing at 1440.

### WIPRO (UNDERVALUED, +200.0% disc clamped, conf 43%, "Possible value trap" label)
- Screenshots: `WIPRO_1440.png`, `WIPRO_1024.png`, `WIPRO_768.png`, `WIPRO_390.png`.
- **Real state diverges from brief assumption:** WIPRO is NOT "Insufficient Data." Post-#697 sanitize_cagr loosening, WIPRO renders an `Undervalued` verdict with FV ₹629.52 (displayed) / ₹882.78 (raw, clamped). An `AnalyticalNotes` `CAUTION` card explains the 3x clamp.
- The Valuation summary correctly carries a **"Possible value trap"** subtitle (deep discount + no moat + 4 red flags + revenue contraction -77.1%) — strong honest-broker voice surfaced in the hero region.
- However, three-way Bear/Base/Bull discounts all show "+200.0%" — the clamp flattens the spread. The DCF scenario card visually loses its differentiation (5-year projection chart still ranges ₹0–₹8,000 and is plottable).
- Compounded Growth section is largely empty (only ROE 15.9% vs sector tile renders, no CAGR tiles) — graceful degradation for missing historical bars, but again a numbered section header consuming space for one tile.
- StylePicker modal triggered on first WIPRO visit (because we cleared localStorage). We dismissed by setting `yq:investing-style = __skipped__`. The modal itself is well-designed (5 lens buttons + Skip) but blocks all interaction — worth noting for the first-visit funnel even though that's out of scope here.

---

## 5. Scored gap table

Severity legend: H = HIGH (blocks G1 / hides differentiator / breaks edge-case state), M = MEDIUM (degrades but doesn't break), L = LOW (polish).

| Ticker | BP | G1 (no 2nd scroll) | G2 (density) | G3 (honesty visible) | G4 (scannability) | First-scroll px | Top-of-fold competing cards | Notes |
|---|---|---|---|---|---|---|---|---|
| TCS | 1440 | **FAIL · H** — no verdict pill / FV / discount / dial above fold; only sticky-rail micro-figures + H1 + NarrativeSummary blurb visible | 2/5 — chrome-heavy, valuation hero pushed to ~viewport-bottom | **FAIL · M** — Honest Card is section 3 of 11 (~3,500 px down). Sticky rail does carry conf 67% though | 3/5 — ScoreCard rail provides decent skim, but main column burns space on model-blurb prose | ~720 (first scroll hits ConfidenceIndicators/Prism) | nav + indices + ADR banner + ticker strip + sticky rail + EditorialHero + Compare/Share + NarrativeSummary = 7 distinct surfaces | Data Limited banner takes ~90 px |
| TCS | 1024 | **FAIL · H** — same as 1440, scorecard rail still present | 2/5 | **FAIL · M** | 3/5 | ~680 | 6 surfaces | — |
| TCS | 768 | **FAIL · H** — sticky rail gone (mobile-style strip), no verdict pill in viewport | 2/5 | **FAIL · M** | 2/5 | ~620 | 5 surfaces | Tab strip "Summary/Valuation/…" lands below model-blurb |
| TCS | 390 | **FAIL · H** — collapsed scorecard strip is the only verdict signal; no FV; no discount; no dial in first viewport | 2/5 | **FAIL · H** — Honest Card extremely far down on mobile | 2/5 | ~580 | bottom-nav adds another competing surface | Mobile bottom-nav + scorecard strip + ticker = three sticky bars |
| HDFCBANK | 1440 | **FAIL · H** — same composition as TCS | 2/5 | **FAIL · M** | 3/5 | ~700 | 6 surfaces (no ADR banner) | EditorialHero image renders |
| HDFCBANK | 1024 | **FAIL · H** | 2/5 | **FAIL · M** | 3/5 | ~670 | 6 surfaces | — |
| HDFCBANK | 768 | **FAIL · H** | 2/5 | **FAIL · M** | 2/5 | ~610 | 5 surfaces | — |
| HDFCBANK | 390 | **PARTIAL · M** — collapsed scorecard strip carries verdict + score + moat + flags as pill row; FV/discount still not visible until scroll | 3/5 | **FAIL · M** | 3/5 | ~560 | 4 surfaces (mobile) | Closest any breakpoint comes to G1 — passing via concession that pill-row counts |
| M&M | 1440 | **PARTIAL · M** — compact valuation card with score 60/100, FV ₹3,189.66, discount +6.4%, moat Moderate IS visible above fold (no EditorialHero crowds out) | 3/5 | **PARTIAL · M** — "Low Confidence" tier-C chip + rename banner visible, Honest Card still 3 sections down | 4/5 — denser than image-bearing tickers | ~780 (smaller hero) | 6 surfaces incl. rename banner | Best 1440 result of the four |
| M&M | 1024 | **PARTIAL · M** | 3/5 | **PARTIAL · M** | 4/5 | ~750 | 6 surfaces | — |
| M&M | 768 | **FAIL · H** | 2/5 | **FAIL · M** | 3/5 | ~700 | 5 surfaces | — |
| M&M | 390 | **PARTIAL · M** | 3/5 | **FAIL · M** | 3/5 | ~590 | 4 surfaces | — |
| WIPRO | 1440 | **FAIL · H** — "Possible value trap" honest-broker line IS in the valuation hero but the hero is below the fold | 2/5 | **PARTIAL · M** — value-trap callout exists but lives below the fold | 3/5 — scorecard rail shows +200% discount, raises questions skim doesn't answer | ~720 | nav + indices + Data Limited banner + ticker strip + sticky rail + EditorialHero + NarrativeSummary | Clamp interaction degrades scenarios card |
| WIPRO | 1024 | **FAIL · H** | 2/5 | **PARTIAL · M** | 3/5 | ~680 | 6 surfaces | — |
| WIPRO | 768 | **FAIL · H** | 2/5 | **PARTIAL · M** | 2/5 | ~620 | 5 surfaces | — |
| WIPRO | 390 | **FAIL · H** — value-trap subtitle lost entirely on first viewport | 2/5 | **FAIL · H** — broker honesty buried | 2/5 | ~580 | 5 surfaces | Compose problem worst on this combo |

**Tally:** HIGH = 11, MEDIUM = 15 (counting "PARTIAL · M" as MEDIUM), LOW = 0 surfaced at this depth. The page is failing G1 on 13 of 16 captures.

---

## 6. Top 5 HIGH-severity items

1. **G1 — Verdict + FV + discount-to-FV are below the fold at every desktop breakpoint on every ticker except M&M.** The first viewport burns ~700–800 px on nav, indices marquee, ADR/rename banners, ticker strip, EditorialHero image, classification chips, Share/Compare buttons, and a literal "Model-generated description …" prose blurb before the user reaches `ConfidenceIndicators`. The sticky `ScoreCard` rail technically carries the figures but in 12–14 px type and competes with 7 sibling tiles. Affects: TCS, HDFCBANK, WIPRO @ 1440/1024/768/390. Differentiator at risk: the core "Bloomberg-honest pricing in one glance" promise.

2. **G1 mobile — at 390 the collapsed scorecard strip is the only verdict surface in the first viewport.** It carries Worry · Normal | Score · 40/100 | Moat · Wide | Flags · 2 but **no FV and no discount-to-FV** for any ticker. A first-time mobile user has no fair-value reference until they scroll. Differentiator at risk: differentiating against generic stock-quote apps.

3. **G3 — Honest Card and the WIPRO "Possible value trap" subtitle are below the fold on every breakpoint.** On default style Honest Card is section 3 (after Scenarios + Bull/Bear). On WIPRO the value-trap callout is in `Valuation summary` ~700 px down. The honesty differentiator is the brand promise; it should not require a scroll. Beginner style fixes Honest Card position (lands `1.`) but is opt-in and behind a one-time modal.

4. **G2 — top-of-fold competing surfaces (6–7 distinct cards/chips/CTAs at 1440 on 3 of 4 tickers).** Counted on TCS @ 1440: navbar, indices marquee, Data Limited banner, ticker price strip, sticky scorecard rail, EditorialHero image+pill, classification chips, Compare button, NarrativeSummary prose card. The eye has nowhere to rest. Differentiator at risk: "calm, scannable" voice.

5. **Edge-case rendering — WIPRO's three-way scenario discounts all collapse to +200.0% when the FV is clamped, flattening the bear/base/bull spread.** The chart is preserved but the three discount tiles read identically — fails G4 (scannability of the scenarios card) and creates a "broken hero" perception even though it's a defensive clamp. Worth a Stage-1 treatment that either shows the raw FV with a "clamped for display" toggle or replaces the three identical discount tiles with the conditioning statement.

---

## 7. Differentiator presence audit

| Differentiator | Visible at default first viewport? | Elevated or buried? | Breakpoints |
|---|---|---|---|
| **Honest Card** | No on any default-style breakpoint | Buried (section 3 of 11, ~3,500 px down at 1440) | All — fix requires either default-style reorder, or a hero-level surfacing |
| **Sticky scorecard** | Yes at 1024 & 1440 (left rail), persistent through scroll | Elevated and durable, but visually crowded (7+ tiles) | 1024 & 1440 only; at 768 & 390 it degrades to a collapsed pill strip that drops FV+discount |
| **Reverse-DCF slider (interactive — the real differentiator)** | No — section 7 of 11 (~6,000 px down). Section header degrades gracefully to "Not applicable for banks" on banks (good). For cyclicals (M&M) carries the cycle-distortion bound-not-point caveat (good). | Buried | All |
| **Dated bull/bear narrative** | No — section 2 of 11. "Updated June 2026" stamp present. Paragraph format (post PR-B microcopy) reads well. | Buried; only the Bull/Bear chevron header peeks above 2nd viewport at 1440 | All |

---

## 8. PR-C state

- **Local branch only:** `feat/design-pr-c-restyle` exists in the working repo (`E:\Projects\yieldiq_v7`) with **0 commits ahead of main** (`git rev-list --count main..feat/design-pr-c-restyle` returns 0).
- **No PR opened:** `git ls-remote --heads origin` shows only `feat/design-pr-a-tokens` and `feat/design-pr-b-cards-microcopy` pushed. PR-C never reached the remote.
- **No PR-C worktree:** `git worktree list` does not contain any `.agent-worktrees/design-pr-c*` or `wkt/design-pr-c*` path. (The 50+ worktrees under `E:\Projects\wkt\` are unrelated feature branches.)
- The local PR-A and PR-B branches are also present locally; PR-A and PR-B are both merged to main (commits `e4b8465` and `03553e0` visible in `git log main`).
- **Recommendation:** PR-C effectively a no-op branch. Operator can delete the local branch at any time without losing work.

---

## 9. Suggested Stage-1 inputs

(NOT a spec — these are facts the spec author needs to know going in.)

1. **First-viewport real estate is the dominant problem, not section copy.** ~700–800 px of chrome lives above `ConfidenceIndicators` on every desktop breakpoint. Spec must decide which surfaces are non-negotiable (nav, ticker strip, ADR/rename banners) and which collapse, merge, or move below the fold (EditorialHero image, NarrativeSummary prose card, Share/Compare buttons, Compare CTA, classification chips).

2. **The sticky `ScoreCard` rail already does the G1 job at 1024+** — the question is whether the page even needs a separate `ConfidenceIndicators` block, or whether the first-viewport hero should *be* an enlarged scorecard with the verdict / FV / discount / Worry dial as the primary cards and the EditorialHero image demoted to a slim band or removed entirely on the desktop layout.

3. **Mobile (390) is its own problem.** The collapsed scorecard strip carries Worry+Score+Moat+Flags but **not** FV and discount. Either the strip needs FV/discount added (probably at the cost of dropping Moat to a secondary card), or the strip needs to be the new mobile hero (full scorecard above ticker).

4. **Section-numbering UX has a soft cost:** "1. VALUATION SCENARIOS" / "2. BULL / BEAR THESIS" reads like a checklist and burns ~80 px per section on a header + caption that the brief assumed users would skim. Beginner mode collapses sections by default, which is the right pattern for a deep page — consider applying default-collapse with chevron preview tiles to other styles too, not just Beginner.

5. **The `Reverse-DCF "Not applicable for banks"` and `Compounded Growth "ROE only"` empty-state stubs are good honesty but currently waste a full numbered section apiece.** A spec for "stub state" — collapse-by-default with a one-line caption — would recover ~250 px each on bank and limited-history tickers.

---

## Screenshots reference

All paths relative to `E:\Projects\yieldiq_v7\redesign\screenshots\`:

- `TCS_1440.png`, `TCS_1024.png`, `TCS_768.png`, `TCS_390.png`, `TCS_1440_bottom.png`, `TCS_1440_beginner.png`
- `HDFCBANK_1440.png`, `HDFCBANK_1024.png`, `HDFCBANK_768.png`, `HDFCBANK_390.png`, `HDFCBANK_1440_bottom.png`, `HDFCBANK_1440_beginner.png`
- `MM_1440.png`, `MM_1024.png`, `MM_768.png`, `MM_390.png`
- `WIPRO_1440.png`, `WIPRO_1024.png`, `WIPRO_768.png`, `WIPRO_390.png`

20 screenshots total.
