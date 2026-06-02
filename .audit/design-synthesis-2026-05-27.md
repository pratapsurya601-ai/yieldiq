# Design synthesis — analysis page — 2026-05-27

Implementable in one coordinated sprint (3 PRs). All decisions specified to a
hex / px / Tailwind class. No judgement calls left for the build agent.

Inputs: `competitor-walk-hdfcbank-2026-05-26.md`,
`tickertape-deep-walk-2026-05-27.md`, `.claude/design-manifesto.md`,
current `globals.css` (Tailwind v4 `@theme`), `verdict-colors.ts`.

---

## 1. Design north star

**Bloomberg-terminal density meets Stripe-doc clarity, narrated in one
honest-broker voice.** Every viewport should answer "what's the verdict, and
on what evidence?" without a second scroll, while every section reads like a
finance journalist wrote it — never a screener dump and never an ad. The page
is colorful only where color is signal; everything else is restrained slate
so the signal pops. Tickertape's traffic-light scorecard + AlphaSpread's
single-number-plus-slider clarity + our Honest Card disclosure.

---

## 2. Type scale

Font: **keep Inter** (sans + display) and **keep Fraunces** (`font-editorial`)
for the hero headline and primary score display only. No swap. Inter's
`tnum` + `slashed-zero` cover all numeric needs. JetBrains Mono stays for
`<code>` and DCF formula traces. Swapping families costs 4-8h of QA across
12k px of page for zero legibility win.

Eight steps. Tailwind v4 utility names assumed (`text-xs`/`text-sm`/…).
Where the default leading is wrong for data density we override with an
explicit `leading-*`.

| Token        | px / line-height | Tailwind                            | Use                                          |
|--------------|------------------|-------------------------------------|----------------------------------------------|
| caption      | 11 / 16          | `text-[11px] leading-4`             | Chip labels, axis ticks, "Source: …"         |
| body-sm      | 13 / 18          | `text-[13px] leading-[18px]`        | Table cells, dense metric rows, footnotes    |
| body         | 15 / 22          | `text-[15px] leading-[22px]`        | Default prose, card body                     |
| lead         | 17 / 26          | `text-[17px] leading-[26px]`        | Honest Card prose, Bull/Bear paragraphs      |
| h4           | 18 / 24          | `text-[18px] leading-6 font-semibold` | Sub-section labels                         |
| h3           | 22 / 28          | `text-[22px] leading-7 font-semibold` | Section titles                             |
| h2           | 30 / 36          | `text-[30px] leading-9 font-semibold` | Big metric numbers, Worry Index value      |
| h1-editorial | 44 / 48          | `text-[44px] leading-[48px] font-editorial` | Hero ticker name + primary score       |

Letter-spacing rules (one-line):

- `tracking-tight` (-0.02em) on `h1-editorial`, `h2`, `h3`.
- `tracking-normal` (0) on `body`/`lead`/`h4`.
- `tracking-[0.06em] uppercase` on `caption` when used as a section eyebrow.

Numeric rules:

- Every digit, %, currency uses `tabular-nums slashed-zero`. New utility
  to add in `globals.css`:
  ```css
  .num { font-variant-numeric: tabular-nums slashed-zero;
         font-feature-settings: "tnum","zero"; }
  ```
  Apply `className="num"` (or `font-mono`, which already wires tnum) to every
  numeric span on the page. Build agent: replace any bare `<span>{value}` in
  the metric grid with `<span className="num">`.

---

## 3. Color tokens

Audit: current `globals.css` has 11 semantic tokens + 4 Prism axis tokens =
**15 tokens already**. Cap is 25. We add 7 tone tokens and one surface step.

### Brand
- `--color-brand: #2563EB` (light) / `#60A5FA` (dark) — **keep**.
- `--color-brand-50: #EFF6FF` / `#1E3A8A` — **keep**.

### Semantic tones — bg / text / border per tone
Five tones. Each tone gets a `*-bg` (chip background), `*-fg` (chip text),
`*-bd` (1px border). Dark-mode pair specified.

| Tone     | Light bg   | Light fg   | Light bd   | Dark bg    | Dark fg    | Dark bd    |
|----------|------------|------------|------------|------------|------------|------------|
| good     | `#ECFDF5`  | `#047857`  | `#A7F3D0`  | `#064E3B`  | `#6EE7B7`  | `#065F46`  |
| neutral  | `#F1F5F9`  | `#334155`  | `#CBD5E1`  | `#1F2A3F`  | `#CBD5E1`  | `#334155`  |
| warn     | `#FFFBEB`  | `#B45309`  | `#FDE68A`  | `#451A03`  | `#FCD34D`  | `#78350F`  |
| bad      | `#FEF2F2`  | `#B91C1C`  | `#FECACA`  | `#450A0A`  | `#FCA5A5`  | `#7F1D1D`  |
| info     | `#EFF6FF`  | `#1D4ED8`  | `#BFDBFE`  | `#1E3A8A`  | `#93C5FD`  | `#1E40AF`  |

Add to `:root` and `html.dark` blocks: `--tone-good-bg/fg/bd`, ditto for
the other four tones — **15 new CSS variables, 5 Tailwind utility triplets**.
Build agent generates the three Tailwind class triplets per tone as static
strings the JIT can extract (mirror the pattern in `verdict-colors.ts`).

### Surface scale (light / dark)

| Token         | Light   | Dark    | Use                                  |
|---------------|---------|---------|--------------------------------------|
| `--color-bg`  | `#FFFFFF` | `#0B1220` | page canvas — **keep**            |
| `--color-surface` | `#F8FAFC` | `#131B2C` | card surface — **keep**       |
| `--color-raised`  | `#FFFFFF` | `#1A2336` | sticky rail, sticky scorecard (**new**) |
| `--color-overlay` | `rgba(15,23,42,0.6)` | `rgba(0,0,0,0.7)` | modal scrim (**new**) |

### Verdict cascade
**Keep `verdict-colors.ts` exactly as is.** Document it as the only place
verdict gradient strings live. No new tokens.

### Prism axis tokens
**Keep** the 4 `--prism-*` tokens. Used only inside `<Prism>` — not part of
the analysis-page semantic palette.

### Total token count
- Existing: 11 semantic + 4 prism = 15
- Added: 2 surfaces + 15 tone vars (but expressed as 5 tones × 3 facets) = 17
- Counted as user-facing tokens: 11 + 5 tone families + 2 surfaces + 4 prism = **22**. Under 25.

---

## 4. Spacing + grid

8pt grid. Tailwind defaults already align: `1=4px`, `2=8px`, `3=12px`,
`4=16px`, `6=24px`, `8=32px`, `12=48px`, `16=64px`. Permitted steps on the
analysis page: **only** `1,2,3,4,6,8,12,16`. Build agent: any inline `p-5`,
`p-7`, `gap-5`, `mt-10` is a lint error in this sprint — rewrite to nearest
permitted step.

Section vertical rhythm:
- Between numbered sections: `mt-16` (64px) on desktop, `mt-12` (48px) at `<md`.
- Between a section title (h3) and its content: `mt-4` (16px).
- Between a card and the next card inside a section: `mt-3` (12px).
- Between a metric label and its value: `mt-1` (4px).

Card internal padding rules:
- `card-sm` → `p-3` (12px). Used by chips, tag rows.
- `card-md` → `p-4 md:p-6` (16/24px). Default for data-dense and summary cards.
- `card-lg` → `p-6 md:p-8` (24/32px). Narrative cards (Honest Card, Bull/Bear, Reverse-DCF prose).

Sticky-rail (the new component shipping in PR #691 area):
- Width: **keep 336px on `≥lg`**. Matches Tickertape exactly and our existing
  decision.
- Top offset: `top-20` (80px) — clears global header + ticker strip.
- Internal: `card-md` padding, `space-y-3` between tiles.
- Below `lg` breakpoint: rail collapses into a sticky-top horizontal bar
  (`sticky top-14 z-30`) showing verdict pill + score + MoS only.

Page grid:
- `lg:grid lg:grid-cols-[336px_minmax(0,1fr)] lg:gap-8`.
- Main column max-width `max-w-[880px]` so prose never crosses ~75 chars.

---

## 5. Card patterns (3 variants)

Three components live at `frontend/src/components/cards/` and replace inline
`bg-white rounded-2xl shadow ...` strings across the page.

### `<DataCard>` — data-dense
Use: peers table, scorecard tiles, metric grids, F-Score breakdown,
financials table, shareholding table.

```tsx
className={[
  "rounded-lg border border-border bg-surface",
  "p-3 md:p-4",                       // card-sm → card-md
  "text-[13px] leading-[18px] num",   // body-sm + tabular
  "hover:bg-bg hover:border-ink/20 transition-colors",
].join(" ")}
```
- No shadow. Border-only.
- Headers in `caption` (`text-[11px] uppercase tracking-[0.06em] text-caption`).
- Numbers use tone tokens: `text-[var(--tone-good-fg)]` etc.

### `<SummaryCard>` — verdict / score / Worry / single big metric
Use: hero verdict tile, Worry Index gauge card, sticky scorecard tiles.

```tsx
className={[
  "rounded-2xl border border-border bg-raised",
  "p-4 md:p-6",                        // card-md
  "shadow-[0_1px_2px_rgba(15,23,42,0.04),0_4px_12px_rgba(15,23,42,0.04)]",
  "flex flex-col gap-1",
].join(" ")}
```
- Headline: `h2` (30/36) `num font-semibold`.
- Caption below: `caption text-caption`.
- Optional 4px left bar in verdict color: `before:absolute before:left-0 before:top-0 before:h-full before:w-1 before:rounded-l-2xl before:bg-[var(--verdict-bar)]`.

### `<NarrativeCard>` — prose
Use: Honest Card, Bull/Bear thesis, Reverse-DCF explanation, Data-Limited
banner, "How we got here" disclosures.

```tsx
className={[
  "rounded-2xl border border-border bg-surface",
  "p-6 md:p-8",                        // card-lg
  "text-[17px] leading-[26px] text-body",  // lead
  "[&_strong]:text-ink [&_h4]:text-ink",
  "max-w-[72ch]",
].join(" ")}
```
- Prose uses `prose prose-slate dark:prose-invert` for typography plugin.
- Eyebrow: `caption uppercase tracking-[0.06em] text-caption mb-2`.

---

## 6. Section-by-section synthesis

| Section | Done best by | Keep from ours | Adopt / synthesize | Our angle |
|---|---|---|---|---|
| Hero | AlphaSpread (calm photo + 1 number + slider) | Verdict-driven gradient + photo + Fraunces editorial type | One number (FV) + one chip (MoS) above the fold; collapse the other 6 into a `<details>` "How we got here" | Verdict-driven color cascade nobody else has |
| Sticky Scorecard | Tickertape (336px left rail, 5 traffic-light tiles) | Re-use computed verdict, FV, MoS, F-Score, Moat, Worry composite, red-flags | 5 `<SummaryCard>` tiles with traffic-light chip per tile, pinned `top-20`, visible across whole 12k-px page | No paywall overlays — verdict stays free (manifesto #7) |
| Worry Index | Ours (already strong) | Gauge + sub-bars in tone colors | Adopt body-sm tabular numbers; replace inline padding with `card-md` | Only app that names emotional state explicitly |
| Valuation Scenarios | AlphaSpread (bear/base/bull tabs + slider) | Spectrum + Signature toggle | Segmented `0/10/20/30/40/50% MoS` button row that recomputes "Buy zone at ₹X" inline | Story arc (Spectrum) instead of static tabs |
| Bull / Bear | Tickertape (~80-word LLM paragraphs, dated) | Honest framing, SEBI-clean copy | Expand each side from 3 fact-bullets to one 60-90 word paragraph in a `<NarrativeCard>`; date-stamp it ("Updated 27 May 2026") | Pair with Honest Card right below ("here's where we could be wrong") |
| Honest Card | **Ours — unique** | Everything | Promote into a `<NarrativeCard>` immediately after Bull/Bear; never collapse by default | Differentiator — keep visible |
| Compounded Growth | Ours (sparklines already shipped) | Sparkline rows | Add inline sector-median comparison chip per row ("CAGR 12% · sector 8%") | First-principles framing, no broker targets |
| Reverse DCF | Ours (playground is unique) | Sliders + WACC/growth/terminal inputs | Wrap in `<NarrativeCard>` (`card-lg`) so the prose breathes; sticky "Recompute FV" CTA in `--color-brand` | Interactive — nobody else has this |
| Financials | Tickertape (annual + quarterly P&L grids) | FinancialsChartPanel bar chart | Add a `<DataCard>` quarterly table (10 quarters × 10 line items) as a 3rd tab beside the chart; show numbers tabular | Captioned in plain English ("Margins compressed 80bps in Q3") |
| Dividends | Tickertape (yield vs sector) | Bar chart + payout chip | Add "Yield 5.5% · sector 3.2% · +71%" `<MetricVsSector>` chip | "Sustainable payout" framing (red if >100%) |
| Peers | Screener (inline sortable, editable cols) | Curated 5-row table | Move from `Compare →` link to **inline** `<DataCard>` peers table; one view (no edit-columns trap) | Opinionated 7-column shortlist instead of 30 |
| News | **Ours — already wins** | Sentiment chips (↑/→/↓) | Re-skin chips to use `tone-good/neutral/bad` tokens; size to `caption` | Per-headline sentiment label nobody else ships |
| Earnings Calls | Tickertape (full transcript search) | Our summary card | Quote-pull pattern: 2-3 dated quotes in `card-md`, link out for full transcript | Plain-English summary of what management actually said |

---

## 7. Microcopy voice rules

Audit of current strings across analysis page:

| Today (inconsistent)                          | Lock to                              |
|-----------------------------------------------|--------------------------------------|
| "Discount to FV" / "Margin of Safety" / "MoS" | **"Discount to FV"** primary; "MoS" allowed only inside Reverse-DCF playground as a power-user alias |
| "Score" / "Rating" / "Grade C"                | **"Score"** is the noun. Grade letter retired from this sprint (Manifesto #1 — one verdict per page) |
| "Verdict" / "Label" / "Tier"                  | **"Verdict"** everywhere user-facing. "Tier" stays internal (`VerdictTier` type) |
| "Under Review" / "data_limited" / "Unavailable" | **"Under Review"** for analyst-pause; **"Insufficient Data"** for cohort-data-missing |
| "Fair Value" / "Intrinsic Value" / "FV"       | **"Fair Value"** primary; "FV" allowed in compact tiles only |
| "Bulls Say" / "Bull thesis" / "Pros"          | **"Bull case"** / **"Bear case"** |

Banned words remain per `backend/services/analysis/sebi_filter.py` — no
buy / sell / target / cheap / strong / appears.

Build agent: produce a single sweep PR that renames the four pairs above
across `frontend/src/`. Diff-only — no logic changes.

---

## 8. Implementation sprint plan

Three PRs. Strict order. Honest hours (token refactors touch ~40 files).

### PR-A — Tokens + type scale + utilities (foundation)
**Touches**: `globals.css`, `frontend/src/lib/utils.ts` (add `cn` helpers
if missing), every component file that uses hard-coded `p-5`/`p-7`/`gap-5`/
`text-base`/`text-xl` (estimate ~40 components, mostly mechanical).
**Adds**:
- 5 tone variable families (15 CSS vars × 2 modes = 30 declarations)
- 2 new surface tokens (`--color-raised`, `--color-overlay`)
- `.num` utility (tnum + slashed-zero)
- Documents the 8-step type scale in `globals.css` header comment
**Removes**: ad-hoc `bg-emerald-50 text-emerald-700` strings — replaced by
tone tokens.
**Estimate**: **12–16 agent-hours**. Half is the find-and-replace sweep;
half is the snapshot diff QA on `vitest` snapshots.

### PR-B — Card components + microcopy lock
**Touches**: new files `frontend/src/components/cards/{DataCard,SummaryCard,NarrativeCard}.tsx`,
~30 call-sites across the analysis page that currently inline `bg-white
rounded-2xl shadow ...`. Plus the microcopy rename sweep from §7.
**Estimate**: **10–14 agent-hours**.

### PR-C — Section-by-section restyle to spec
**Touches**: each analysis-page section component, applying the §6 row for
that section. Includes:
- Hero collapse to 1 number + 1 chip (Manifesto #1)
- Sticky scorecard rail (5 tiles, traffic-light chips)
- Bull/Bear paragraph expansion (LLM prompt + length budget)
- Inline `<MetricVsSector>` chip on Dividends, Compounded Growth, Peers
- Inline peers table replacing `Compare →` link-out
- Quarterly P&L tab inside FinancialsChartPanel (data-shape audit first; if
  10-quarter P&L isn't in `computation_inputs` cache, defer this single
  sub-task to PR-D — do NOT bump CACHE_VERSION inside this sprint, per root
  CLAUDE.md rule)
**Estimate**: **20–28 agent-hours**. Largest PR. Acceptable because every
change is small and section-scoped — diff stays reviewable.

**Total sprint**: 42–58 agent-hours. Three PRs. Dependency order is strict —
B needs A's tokens, C needs B's card components.

---

## 9. NOT in scope

1. **Hero photo curation / Cloudinary swaps** — Phase C already shipped.
2. **Holdings ETL / shareholding-history table** — separate workstream;
   needs new backend pull (`shp.nse` filing).
3. **Mobile-specific layout overrides** beyond breakpoint mapping in §4. No
   mobile-only components; desktop adds columns per Manifesto #6.
4. **Reverse-DCF math / FV formula / score formula** — design only; logic
   frozen per root CLAUDE.md authority list.
5. **`/search` Suspense fix, CACHE_VERSION bump, canary rebuild** — known
   flake list in root CLAUDE.md; orthogonal to this sprint.

---

## 10. Shipping order

**Ship PR-A first because it unblocks B and C. Without locked tokens, every
restyle PR diverges into ad-hoc class strings and the coherent visual
upgrade dissolves into another 50 inconsistent PRs.**

---

## 11. Phase 1 — FV History contract

Locked 2026-06-02 by Agent B (contract-first) so Agent A (data) and
Agent C (UI) build against a stable interface. Endpoint:
`GET /api/valuation-history/{ticker}` returning
`FairValueHistoryResponse` (see `backend/models/fair_value_history.py`
and the mirrored TS in `frontend/src/types/api.ts`).

- **Provenance tagging + production-faithful-only rule.** Every point
  carries a `provenance` literal — `snapshot` (scripts/snapshots/*.json),
  `golden` (scripts/dcf_golden.json), or `live` (recompute hook). The
  series only contains FVs a user would actually have seen on that
  date, computed by the engine version live then; no back-recomputation
  with today's code against yesterday's inputs.
- **FV-series-driven annotations, not manifest-driven.** A material
  move is emitted off the FV series itself when `|delta_pct| >=
  FV_ANNOTATION_THRESHOLD_PCT`. A wildcard manifest entry that did not
  materially move this ticker emits no annotation; a financials/price
  refresh that DID move FV emits one even with no manifest entry. The
  `confidence` field carries the attribution quality
  (`high` / `inferred` / `data_refresh`).
- **Named threshold constant.** `FV_ANNOTATION_THRESHOLD_PCT = 2.0`
  lives in `backend/services/analysis/constants.py` with a locked
  comment. Single source of truth for both backfill and the live
  recompute hook.
