# YieldIQ Analysis Page — Target Architecture (v3)

> Companion to ANALYSIS_PAGE_REDESIGN_BIBLE.md (the as-is inventory).
> v3 = v2 + the LOCKED VISUAL LANGUAGE (§7, from the 2026-06-11 interactive
> mockup series approved by the founder). v2 superseded the tab-based v1.
> Four locked decisions drive the structure:
> 1. **One guided scroll**, not 7 tabs — a sticky jump-rail gives random-access without breaking the narrative flow.
> 2. **North-star metric = Margin of Safety vs Fair Value.** The YieldIQ Score is demoted to a quality sub-signal. This resolves the Score-vs-Verdict contradiction (bible ROOT CAUSE #6).
> 3. **Fast lane + deep lane.** A Decision Box up top answers "cheap? safe? what do I do?" in 10 seconds; the analyst narrative below carries the proof.
> 4. **Confidence is a ribbon**, threaded through every section — not one gauge.
>
> Standing principle (unchanged from v1): every datum has ONE canonical home; every other
> appearance is a different view (over time, vs peers) or a link — never a static reprint.

---

## 1. THE ORGANIZING PRINCIPLE

A fundamental analyst reads a company in a fixed order:

> Snapshot → Is it cheap? → Business model → **Income statement → Balance sheet → Cash flow → Returns** → Growth → Valuation → Risk → Ownership → Management voice → Peers → News → Decide

The page is **answer-first, then evidence in that exact build order**, delivered as a **single vertical scroll**. Tabs were rejected because they are random-access — the opposite of the "flow of information in the sequence analysts read" the page must honor. A sticky **jump-rail** (the demoted tabs) lets a reader leap to any section without losing the top-to-bottom narrative. This is also the only structure that degrades gracefully to mobile.

**Two reading speeds, no duplication:**
- **Fast lane** — a **Decision Box** pinned at the top: Verdict · Margin of Safety · the single biggest risk · "set alert at ₹X". Answers the retail user in 10 seconds.
- **Deep lane** — the analyst narrative below. Same numbers, but as *workings*, not headlines. The Decision Box is the conclusion; the narrative is the proof. (One number as a headline + once as its detailed surface is allowed; the same chart twice is not.)

**North star = Margin of Safety vs Fair Value.** Fair Value is the anchor; MoS (= (FV − Price)/FV, clamped) is the hero quantity that recurs as the spine of the page. The YieldIQ Score becomes a *business-quality* sub-signal shown alongside — never a second verdict. No surface may imply a valuation conclusion that disagrees with MoS.

---

## 2. INFORMATION TIERS (top-to-bottom of the single scroll)

| # | Section (jump-rail label) | Question it answers | Confidence ribbon |
|---|---|---|---|
| — | **Identity band** (chrome) | What is this, how big, what price | — |
| ★ | **Decision Box** (fast lane) | Cheap? Safe? What do I do? | aggregate |
| 1 | **The Answer** | Intrinsic value vs price; MoS | per-section |
| 2 | **Thesis** | Why — bulls / bears / honest take | per-section |
| 3 | **Business** | How it makes money | per-section |
| 4 | **Financials** | Statements: P&L → BS → CF → returns | per-section |
| 5 | **Valuation** | How we got the number | per-section |
| 6 | **Risk** | What breaks the thesis | per-section |
| 7 | **Ownership** | Who owns it, what mgmt says | per-section |
| 8 | **Peers + History** | Relative + model track record | per-section |

Persistent: a floating **AI assistant** and an **action rail** (Watchlist · Alert · Note · Share · Export) ride along the whole scroll.

---

## 3. SECTION-BY-SECTION (the single scroll, in order)

### Chrome (collapse 11 elements → 3)
1. Indices strip (TickerStrip)
2. Identity band (StockHeroImage; fix hardcoded slate-950 → tokens)
3. **Sticky jump-rail** (replaces StickyAnalysisNav + StickyTableOfContents — ONE nav). "AI" pill removed; AI is the floating assistant.

> Kill: duplicate sticky-header price, 2 of 3 freshness surfaces, 4 hand-rolled banner styles → ONE `<Notice severity>`. Dead Save/Alert buttons → real actions in the action rail.

### ★ Decision Box (fast lane — the new top surface)
Verdict pill · **Margin of Safety (hero)** · Fair Value vs Price · the #1 risk (one line from the Risk section) · "Set alert at ₹X" CTA · aggregate confidence chip. Mobile gets this in full (today alerts are hidden <1024px). Everything here links down to its detailed section.

### 1 · The Answer
HonestHero composer: MoS hero number, ValuationRangeStrip (scenario summary), one confidence gauge, one methods one-liner ("blend of N estimators → link to §5"). **Confidence shown once here as the gauge; per-section markers everywhere else.**

### 2 · Thesis
ONE "Investment Thesis" block = Bulls/Bears paragraphs + ValuationDrivers (3 drivers) + HonestCard ("where we're sure / unsure"). Qualitative → ribbon marked *mixed*.

### 3 · Business
Compact "what it does / sector / segment-mix one-liner / moat label". Links into §4 for segment detail.

### 4 · Financials (the heart — analyst statement order)
1. **Snapshot** — FinancialsKpiGrid (revenue/profit/margin + YoY)
2. **Income Statement** — Profit Bridge (renamed EarningsWaterfall) + RevenueSankey + Quarterly Cadence + Revenue by Segment. Banks: NII → provisions → operating profit.
3. **Profitability & Returns** — margins, ROE, ROIC/ROCE, ROA *(the old Quality-tab ratio grid, moved to where analysts compute it)*. Banks: NIM, ROA, cost-to-income.
4. **Balance Sheet & Solvency** — D/E, current ratio; banks: CRAR + GNPA/NNPA/PCR.
5. **Cash Flow** — OCF, FCF, conversion. ONE source (kill FinancialBars' divergent source).
6. **Growth & Track Record** — CompoundedGrowth CAGR (ONE rendering), 10y trend.
7. **Detailed Statements** — full tables (appendix).

### 5 · Valuation (how the Answer was derived)
1. **Methods table (canonical)** — ValuationMethodsPanel + CompositeCompositionPanel merged; the ONE home for every estimator's value/weight/contribution. Absorbs CrossConfirmationChip, ConsensusSignalBadge, §1 method rows.
2. **Interactive DCF** — InteractiveDcfPlayground with Reverse-DCF as a mode (kill standalone ReverseDcfPanel + /playground dup).
3. **Scenarios** — FVProjectionFan (ONE mount) — full version of §1's range strip.
4. **Sensitivity & Stress** — SensitivityPanel + Tornado + StressTestScenarios; clarify free-vs-paid.
5. **Relative valuation** — AnalystConsensusReframePanel (Wall St vs YIQ).
6. **Tax efficiency** — TaxEfficiencyCalculator.

### 6 · Risk
WorryIndex (ONE) → RedFlagInsights (ONE) → Solvency/Debt (the leverage view, reframed as risk) → Stress tests → Governance: PromoterPledgePanel + InsiderDealsTimeline (ONE insider surface — kill InsiderTradingPanel + BulkBlockDealsPanel). The #1 risk line feeds the Decision Box.

### 7 · Ownership & Voice
Shareholding (HoldingsTrendMiniChart, ONE chart — drop the QualityRatios stacked bar) → Institutional (MutualFundHoldersPanel + FII/DII) → Management voice (ConcallSignalsPanel + ConcallsPanel merged) → ARSignalsPanel (split the 1,221-line monolith) → NewsWidget (ONE — kill EarningsCallsWidget overlap) → CommunitySentiment.

### 8 · Peers + History (merged — Peers is one table, not a tab)
- **Peers** — PeerComparison, ONE table (InlinePeerComparison, SeeAlsoPeers, SectorHeatmapMini collapse into views of it).
- **History** — Time Machine scrubber (ONE entry) → ValuationTrajectoryChart (FV vs Price over time, ONE — FairValueHistory + PriceChart FV-line collapse in) → MosHeatmapCalendar → TotalReturnDisplay → calibration link → VersionedSnapshotsPanel (ONE change log — kill tail ManifestHistoryPanel).

### Persistent
- **Action rail**: Watchlist · Alert · Note · Share · Export. ONE notes journal (merge SaveNotePanel + MemoryLane-note). Mobile parity.
- **Floating AI assistant** (AnalysisChatPanel) — absorbs ELI15 + AIPromptPresetsPanel + AnalysisPromptPresets (4 AI surfaces → 1).

---

## 4. CANONICAL-HOME ASSIGNMENT (the dedup kill list)

| Datum | Canonical home | Kill / convert to reference |
|---|---|---|
| Margin of Safety (north star) | Decision Box (hero) + §1 | every other MoS print → reference the same value |
| Fair Value / IV | §1 hero | MultiCurrencyFVDisplay (fold currency in), FAQ Q1/Q2 (auto-gen), 2nd FVProjectionFan |
| Verdict | Decision Box + 4px bar | MobileScoreStrip verdict → reference |
| YieldIQ Score | §4 returns (quality sub-signal) | any use as a 2nd verdict → removed |
| Scenarios | §1 range strip + §5 fan | cards-vs-fan-vs-bands triplication; 2nd fan mount |
| Confidence | §1 gauge + per-section ribbon | kill 4 of 6 standalone confidence renders |
| "Estimators agree" | §5 methods table | CrossConfirmationChip, ConsensusSignalBadge, §1 method rows → 1 line + link |
| ROE / ratios | §4 returns layer | duplicate QualityRatios mount |
| InsightCards (×3) | dissolved | every chip → link to its dedicated section |
| Insider activity | InsiderDealsTimeline (§6) | InsiderTradingPanel, BulkBlockDealsPanel |
| Shareholding | HoldingsTrendMiniChart (§7) | QualityRatios stacked bar |
| Notes | ONE journal | merge SaveNotePanel + MemoryLane note |
| Model change log | VersionedSnapshotsPanel (§8) | tail ManifestHistoryPanel |
| AI Q&A | floating assistant | ELI15, AIPromptPresetsPanel, AnalysisPromptPresets → deep-links |
| Time Machine | §8 scrubber | sticky-header icon + chip → reference |
| Reverse DCF | §5 playground mode | standalone ReverseDcfPanel, /playground dup |
| Financial statements | ONE data source | FinancialBars (divergent source) |
| Freshness | DataFreshnessWidget | FreshnessStamp row, band stamp → reference |
| Red flags | RedFlagInsights (§6) | InsightCards card, EditorialHeroBand chips |
| Worry | WorryIndex (§6) | rail repeat, mobile-strip repeat |

**Net: ~25 duplicate surfaces removed, 17 orphaned components deleted.**

---

## 5. CROSS-CUTTING CONTRACTS

| System | Today | Target |
|---|---|---|
| Layout | 7 tabs + 4 sticky layers + 2 rails | ONE scroll + ONE sticky jump-rail |
| North-star metric | Score vs Verdict contradict | MoS vs FV is the single spine; Score = sub-signal |
| Empty state | empty shells render (recurring bug) | **Contract (lint-enforced): no section renders an empty shell — it collapses, or states why (no-data vs paid vs not-applicable-for-sector).** |
| Confidence | 6 visualizations | 1 gauge (§1) + a per-section ribbon marker |
| Card shell | 6 systems (16/130 use primitives) | ONE card primitive set |
| Headings / numbering | 25+ class strings, 3 schemes | ONE `SectionHeader` + ONE numbering scheme |
| Color | raw palette (37 files) + tone-* + tokens | ONE token system; zero raw slate/emerald/rose |
| Motion | 4 systems; ~100/130 unanimated | ONE motion lib; consistent reveal cadence |
| Charts | recharts + d3 + hand-SVG + CSS | ONE chart theme module |
| Banners | 5 hand-rolled | ONE `<Notice severity>` |
| Type debt | `as unknown as` casts | add score_verdict_divergence + cross_engine_consensus to types/api.ts |

---

## 6. MIGRATION PHASING

- **Phase 0 — Decide the spine (no UI):** make MoS-vs-FV the single source of valuation truth; demote Score to sub-signal; add the empty-state lint. Closes ROOT CAUSE #6. Pure logic/guard work.
- **Phase 1 — Consolidate (no visual change):** delete the ~25 duplicate mounts + 17 orphans; merge 4 AI surfaces + 2 notes journals. Page gets shorter and faster; nothing looks different. Lowest risk.
- **Phase 2 — Restructure to the scroll:** collapse tabs into one ordered scroll + sticky jump-rail; add the Decision Box; thread the confidence ribbon; dissolve Quality (ratios→§4, governance→§6, ownership→§7); fold Peers into §8. Mobile parity here.
- **Phase 3 — Systematize:** one card / motion / chart / token / numbering / banner system.
- **Phase 4 — Restyle & polish:** the Apple/Stripe/Bloomberg visual layer + final motion. Cheap now, because we polish ONE copy of each number on ONE system.

Each phase = a few small canary-clean PRs, adversarially reviewed. Order is load-bearing: decide the spine and consolidate *before* restyling, so we never polish 16 copies of the same number.

---

## 7. LOCKED VISUAL LANGUAGE (v3 — founder-approved mockup series, 2026-06-11)

Iterated across ~10 interactive mockups in-session; everything below is the approved end state.
**Governing rule: no chart shape appears twice on the page.** Every section owns one
distinct visual. All motion honors `useReducedMotion` (snap to final state).

### 7.1 Decision Box (hero)
- **Left:** verdict pill → MoS hero number (counts up) → **sequenced fair-value bar**
  (blue price fill animates to 83.8%, THEN green MoS zone scales in, THEN marker + count
  — the discount gets its own beat) → price/FV labels → live **alert slider**
  (recomputes target price) → **pillar inspector slot** (fed by Spectrum taps).
- **Right: the SPECTRUM** — the brand centerpiece (see 7.2).

### 7.2 The Spectrum (locked — merges Prism shape + Hex depth on this page)
- Keep the existing product identity: RAW beam → prism diamond → **six refraction
  trapezoid bands** (PULSE/QUALITY/MOAT/SAFETY/GROWTH/VALUE, width = score/10) →
  center thread → core overall number + region label (e.g. VALUE REGION) + tagline.
- **Unfold animation:** raw beam draws in, bands refract open top-to-bottom (back-ease),
  thread stitches down, core counts up, narrative fades in. In the real build this is
  scroll-triggered (fires when the section enters viewport).
- **Vertical median tick** inside each band = sector median (legend: "| sector median").
  NOT slanted (reads as a stray slash).
- **Tap a band** → inspector shows score, Hex band chip (e.g. "Strong discount · 81st
  pctile of 41 bank peers"), the axis `why`, median gap. Data already exists in
  `HexResponse` (axes.*.why, band, percentile, sector_peers, sector_medians).
- **+PEER toggle** → dashed outline bands overlay (one peer at a time).
- **Pulse band breathes** (slow fill-opacity oscillation — momentum pillar only; never
  animate size, that would read as changing data).
- REMOVED by founder decision: Signature fold toggle, Today/12m time morph.
- Honesty rule: a `data_limited` axis renders as a **hollow outlined band**, never filled.
- Narrative line uses the existing `prismNarrative.ts` engine verbatim.
- `/hex/[ticker]` page survives as the deep-dive view; OG share images adopt this render.

### 7.3 Per-section visuals (the no-repeat table)
| Section | Canonical visual | Signature motion |
|---|---|---|
| Hero | FV discount bar + Spectrum | sequenced fill; refraction unfold |
| 1 Answer | semicircle **gauge** + vertical **price ladder** | needle swings w/ overshoot, green arc pulses on land; "now" marker climbs ladder |
| 2 Thesis | **balance beam** (bull/bear weights) + impact-weighted tap-to-expand points + honesty note | beam tilts to 58/42 with springy settle |
| 3 Business | **money-machine flow** (Deposits → SPREAD/NIM → Advances, marching-ant arrows) + **treemap** w/ ₹ values + tap captions + moat chips | tiles pop staggered; arrows flow |
| 4 Financials | grouped 5y columns; **true waterfall** profit bridge (floating bars at running levels, dashed connectors, signed values, builds left→right); BS/asset-quality KPI tiles; peer **lollipops**; 10-cell **score battery**; dividend **staircase**; collapsible 5y P&L | bars grow in sequence; lollipops slide; battery fills; staircase draws |
| 4b Quarterly | **beat/miss pearl timeline** (8 quarters, dot size = surprise) + last-quarter scorecard vs estimates + next-earnings countdown card ("Remind me" / "What to watch" → AI assistant) | pearls rise/drop in sequence; countdown counts |
| 5 Valuation | 3 numbered steps: ① **forest plot** (dot size = weight, agreement-zone band, ₹ axis, composite + price reference lines, tap row → assumption) ② **weighted blend bar** (segments color-matched to forest dots → ₹ composite) ③ DCF playground (fwd/reverse toggle, sliders, price-vs-FV marker bar, clickable **sensitivity heatmap**) | dots pop; blend segments grow; live recompute |
| 5b Forecast | **projection fan/cone** (bear 6% / base 11% / bull 15% FV paths) + horizon slider + implied-pace readout. Framing locked: "Projection, not a promise"; implied pace labeled as arithmetic, not a price forecast | fan sweeps open via clip |
| 6 Risk | **likelihood × impact matrix** w/ tinted watch zone + worry number | dots plot themselves |
| 7 Ownership | **waffle grid** (100 squares = 1% each) + concall card | fills square-by-square |
| 8 Peers/History | sortable peer table ⇄ **quadrant bubble map** (row hover cross-highlights) + **jagged daily price vs dashed FV line** w/ soft under-fade, hover scrubber w/ dual anchored tooltips, track-record stat tiles | price line draws itself; band washes in |

### 7.4 Cross-cutting locks
- Charts: hand-rolled SVG components (no new chart lib) inside ONE chart-theme module;
  all colors via tokens; the mockups' hex values map to the token palette in build.
- The §4 **score battery must display the Prism overall** (same aggregate, two views) —
  never a second competing score (do not recreate ROOT CAUSE #6).
- History chart style locked: thin jagged line (real daily volatility), airy fade fill —
  NOT smooth curves, NOT heavy solid bands.
- Copy locked SEBI-safe as written in mockups ("trades below intrinsic value",
  "Undervalued", "margin of safety", "beat/missed estimates").
- Estimator-coverage displays (forest plot, methods table) depend on PR #906 landing.
- Mockup reference (chat widget titles, 2026-06-11 session): full assembly
  `yieldiq_analysis_page_full_assembly_v10`; refinements `yieldiq_refine_business_bridge_valuation`,
  `yieldiq_spectrum_final_simplified`, `yieldiq_valuation_history_v2_jagged_airy`,
  `yieldiq_forecast_fan_quarterly_earnings`, gap closure `yieldiq_missing_sections_complete_set`.

### 7.5 Gap-closure surfaces (locked 2026-06-11, second mockup set — founder: "add all, no design compromise")
| Surface | Placement | Visual (no-repeat rule still holds) |
|---|---|---|
| **Provenance bar** | chrome, under Decision Box | freshness strip: live-price pulse dot · financials as-of · model version · "computed Xh ago / recompute" |
| **52-week range** | chrome, same strip | dumbbell (low—now—high) with sliding marker |
| **Confidence depth** | §1 + every section chip | chip tap → **5-pillar dot-matrix** (data quality / model fit / stability / sensitivity / agreement, 1–5 dots each + one-line why). ONE engine behind all chips. |
| **Ownership depth** | §7 (rebuilt) | FII/DII **8-quarter streamgraph** + delta chips; insider **3-lane swimlane timeline** (▲ buy ▼ sell ◆ block, size=value; promoter lane prints "none — widely held"); MF holder chips (top 4 + n more); concall **quote cards** (AI-tallied, incl. "most-asked question") |
| **News & catalysts** | NEW §9, after §8 | catalyst chips (results / ex-div / AGM) + **tiered feed rail** (T1 exchange filing > T2 national > T3 aggregator badges) + community split pill (n votes) |
| **Model-change flags** | §8 history chart | manifest entries stamped as **pennant flags ON the FV/price chart** (tap → plain-English changelog). Implements task #265's annotation markers. Caption: "no silent revisions, ever." |

### 7.6 Tier map (free vs Pro)
**Design rule (locked): a gated feature stays fully designed and visibly previewed —
veil at ~78% opacity + lock card with one-line value pitch + Unlock. NEVER a missing
section, never an empty shell.** Paywall copy carries zero SEBI-banned vocabulary.
- **Free = the whole answer.** Decision Box, full Spectrum (incl. tap inspector),
  thesis, business, financials core (5y) + bridge, 4b scorecard + countdown,
  §5 steps 1–2 (forest + blend, read-only), risk map, ownership snapshot
  (waffle + streamgraph), peer table + quadrant, history 1y + change flags, news T1/T2.
- **Pro = the tools.** DCF sliders + sensitivity heatmap + reverse DCF, forecast
  horizon slider (static fan free), insider history beyond 2 events, full AR-signals
  + concall archives, full MF holder list, peer overlay on the Spectrum,
  history beyond 1y, multi-alerts, exports.
