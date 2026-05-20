# YieldIQ Week-2 Frontend UX Audit (Day 27)

**Date**: 2026-05-20
**Scope**: `/home`, `/analysis/[ticker]`, `/discover`, `/screener`, `/public/[ticker]`, `/pricing`, `/login`
**Method**: Static code audit across 3 dimensions × parallel agents
**Deliverable**: Ranked issue list seeding Days 28-38

---

## TL;DR

| Day | Theme | Effort | Pre-existing? |
|---|---|---|---|
| 28 | Loading skeletons | Medium | Partial — home panels good; Analysis page has CLS |
| 29 | Error states | Medium | Generic "temporarily unavailable" everywhere |
| 30 | Mobile breakpoints | Small | 3 hardcoded `grid-cols-3` without `sm:` fallback |
| 31 | `/discover` UX | Medium | Functional but unmotivating empty state |
| 32 | Watchlist | **Small** | **Backend complete; just need pin button on home panel** |
| 33 | Screener presets | **Small** | **4 presets exist; need 6-8 more + better surfacing** |
| 34 | Verdict-chip consistency | Medium | 5 components duplicate VERDICT_COLORS inline |
| 35 | Currency consistency | Small | `formatCurrency` exists; ad-hoc `.toLocaleString` in 5 places |
| 36 | Dark mode polish | Medium | 11 components have ZERO `dark:` variants |
| 37 | Empty states | Small | Most have CTAs; Discover + Login the gaps |
| 38 | QA + screenshot regression | Medium | Establish baseline via Chrome MCP |

**Total Week-2 estimate: 12 days as planned, but many fixes are smaller than expected because most infrastructure already exists.**

---

## Day 28: Loading skeletons

| Severity | File:line | Issue |
|---|---|---|
| HIGH | `app/(app)/analysis/[ticker]/PublicAnalysis.tsx:127-137` | Skeleton doesn't match final layout — summary card placeholders missing; CLS burst when real data lands |
| MED | `components/home/v2/PortfolioPanel.tsx:59-72` | Empty state has CTA but no loading skeleton matches final table shape |
| MED | `app/(app)/screener/page.tsx:282-296` | Suspense boundary renders generic spinner; could render presets eagerly during SSR |
| LOW | Home panels (Watchlist, QuantPicks, MarketsStrip) | ✓ Already use clean `animate-pulse` skeletons. No work needed |

**Fix path**: Expand `PrismSkeleton` to include summary card placeholders with pill shapes matching final design. Same pattern in PortfolioPanel.

---

## Day 29: Error states

| Severity | File:line | Current state | Fix |
|---|---|---|---|
| HIGH | `app/(app)/home/page.tsx:56-61` | Generic `"{label} temporarily unavailable"` for every panel failure | Add retry button + error detail; distinguish 429 from 500 |
| HIGH | `app/(app)/screener/page.tsx:247-255` | Error banner but no retry; rate-limit errors show misleading copy | Retry button + 429-specific copy ("too many requests — try in a moment") |
| MED | `app/(app)/discover/page.tsx:149-161` | YieldIQ 50 "warming up" card has no retry | Add manual refresh button |
| MED | `app/auth/login/page.tsx:135-154` | OAuth errors surface via query param; no in-flight feedback beyond "Signing in..." text | Spinner + disable button during fetch |
| LOW | `analysis/[ticker]` auth path | ErrorBoundary fallback is generic; no distinction between "still computing" vs "tier doesn't include this" | Tier-aware error copy |

---

## Day 30: Mobile breakpoints

| Severity | File:line | Issue | Fix |
|---|---|---|---|
| HIGH | `app/(app)/concall/page.tsx:135` | `grid-cols-2` with no `sm:` fallback — breaks at 375px | `grid-cols-1 sm:grid-cols-2` |
| HIGH | `app/(app)/analysis/[ticker]/AnalysisBody.tsx:688` | `grid-cols-3` SCV section, no breakpoint | `grid-cols-1 md:grid-cols-3` |
| HIGH | `app/(app)/portfolio/page.tsx:246` | `grid-cols-3` holdings summary, no `sm:` | `grid-cols-1 sm:grid-cols-3` |
| MED | `components/analysis/AnalysisHero.tsx:401` | Hero metric grid may compress on <640px | Verify; add `sm:grid-cols-1` if needed |
| MED | `components/screener/ResultsTable.tsx` | Has `overflow-x-auto` (good); needs explicit table wrapper on <768px | Add `min-w-[800px]` on table |

---

## Day 31: `/discover` UX

**Current**: filter dump + YieldIQ50 widget. Empty-data states show "warming up" with no recovery path.

**Plan**: sector quick-tiles (Pharma / Banks / IT / Energy / Consumer) + "Recently analyzed by community" + "Movers today" widget.

---

## Day 32: Watchlist (SMALL — backend already exists)

**Discovery**: Backend `routers/watchlist.py` is **complete** (249 LoC):
- `POST /api/v1/watchlist/` add
- `POST /api/v1/watchlist/add` alias
- `DELETE /api/v1/watchlist/{ticker}` remove
- `GET /api/v1/watchlist/check/{ticker}` membership

**Frontend gap**: `WatchlistPanel.tsx` is read-only display (8-item home widget). No "Add to Watchlist" button on analysis page; no pin/unpin from results table.

**Fix scope**: Add a `WatchlistButton` component used on:
- `/analysis/[ticker]` next to the verdict chip
- `/screener` results table (per-row pin icon)
- `/discover` quick tiles (per-card pin)

Single component, 3 placement sites. Likely 1-day effort.

---

## Day 33: Screener presets (SMALL — already partly done)

**Discovery**: `lib/screenerFilters.ts:102-143` already has 4 presets:
- `cheap_quality` — Low P/E + high ROCE
- `high_quality` — High ROE + low leverage
- `deep_value` — MoS > 30% + PE < 15
- `smallcap_value` — Market cap < 5000 Cr + MoS > 20%

**Surface**: `/screener` empty-state shows them as 4 buttons.

**Plan additions**:
- "Indian Dividend Aristocrats" — DivYield > 2% + 5y growing dividends
- "PSU Power Bargains" — sector=Utilities + PE < 12
- "Hospital Chains" — sector=Pharma + Day-16 sub-bucket members
- "Story-DCF Watchlist" — engine=story_dcf (just shipped)
- "Recent IPO Bargains" — IPO < 48mo + FV/CMP > 0.85

Plus: persist last-run filter; "Trending screens this week" surfaced from telemetry.

---

## Day 34: Verdict-chip consistency

| Severity | File:line | Issue | Fix |
|---|---|---|---|
| HIGH | `app/(app)/concall/page.tsx:50-54` | `sentimentColor()` custom palette, diverges from `VERDICT_COLORS` | Import + reuse canonical |
| HIGH | `components/analysis/PeerComparisonCard.tsx:10-19` | `verdictClasses()` duplicates `VERDICT_COLORS` inline | Delete local copy; import |
| MED | `components/analysis/ConvictionRing.tsx:26` | Hardcodes blue `#185FA5` | Reference `VERDICT_COLORS.undervalued.hex` |
| MED | `ActionBar.tsx`, `InsightCards.tsx`, `QualityRatios.tsx` | Raw `text-green-600 text-red-500` for MoS | Centralized `mosToneClass()` helper |
| LOW | `lib/constants.ts` | `undervalued` is BLUE `#185FA5` not green | Verify product intent (this might be deliberate brand choice) |

---

## Day 35: Currency consistency

| Severity | File:line | Issue |
|---|---|---|
| HIGH | `lib/utils.ts:40` | `formatCurrency()` uses `.toLocaleString("en-IN")` but `formatPct()` doesn't — inconsistent decimals |
| MED | `components/screener/ResultsTable.tsx:41` | Fallback `.toLocaleString` with 1 DP vs `formatCurrency` 2 DP |
| MED | `app/(app)/admin/story-dcf/page.tsx:91-99` | Local `fmtNum()`/`fmtPct()` don't match canonical helpers |
| LOW | `components/analysis/PeerComparisonCard.tsx:43-45` | Local `fmtNum()` truncates to 1 DP |
| LOW | `app/(app)/portfolio/page.tsx:288, 294, 308` | Hardcodes `"INR"` instead of using `currency` prop |

**Fix path**: ESLint rule `no-restricted-syntax` forbidding `.toLocaleString` in component files; mandatory import of `formatCurrency` from `lib/utils`.

---

## Day 36: Dark mode polish

**Setup**: No `next-themes`; manual `localStorage`-driven `.dark` class via `layout.tsx:71` theme init script. Only "light" + "dark" (system option removed 2026-05).

**Zero `dark:` variants — 11 components**:
1. `FilterBuilder.tsx:55` — `bg-white` ⇒ add `dark:bg-surface`
2. `ResultsTable.tsx:102` — `bg-white`
3. `ResultsTable.tsx:147` — `bg-white`
4. `SavedQueries.tsx:58` — `bg-white`
5. `screener/page.tsx:200` — preset grid `bg-white`
6. `CoverageTierBadge.tsx:52-54` — 3 tier `bg-*-50` with no dark
7. `ActionBar.tsx` — partial; inherits `bg-surface`
8. `IncidentBanner.tsx` — likely hardcoded light
9-11. Analysis components (RedFlagInsights / InsightCards / DividendTracker) — likely missing variants

**Inconsistent contrast — 9 components**:
- `PeerComparisonCard.tsx:13,19` — `text-gray-300` insufficient on dark bg
- `ValuationGrid.tsx:59-72` — `dark:text-red-300` on 950 bg borderline
- (others detailed in audit)

---

## Day 37: Empty states

- ✓ Home panels (Portfolio, Watchlist) — illustrated CTAs guiding next action
- ✓ Screener — preset suggestions + "build from scratch"
- ⚠ Discover — YieldIQ 50 "warming up" lacks refresh
- ⚠ Login — OAuth manual form has no in-flight visual feedback

---

## Day 38: QA + screenshot regression

- Chrome MCP screenshot of every page in this audit at 1024×768 + 375×667
- Save baseline to `frontend/__screenshots__/baseline/`
- Diff against post-Week-2 screenshots; flag any unexplained pixel deltas
- Wire to CI for ongoing regression catch

---

## Sprint mechanics

Each day = 1 PR (Day 28 → Day 38). Branch naming `feat/day{N}-{topic}`. Each PR carries:
- The fix
- A regression-guard test (source-text grep where possible, vitest where layout is involved)
- A 1-screenshot before/after if visual

No CACHE_VERSION bumps in Week-2 (pure frontend).

---

**Audit complete.** Days 28-38 have specific file:line targets — no more guessing where the work is. Half the items (Watchlist, Presets, Currency) are smaller than the original plan estimated because the infrastructure already exists.
