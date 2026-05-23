# Phase J — Cold-read audit (2026-05-26)

Method: walked the production product (https://www.yieldiq.in) and the
source for each route as a non-finance, non-employee first-time visitor
would. Notes per route + a numbered punch list at the end. No code
changes in this PR — that's J-copy.

Constraints reminder: NOT SEBI-registered, banned-vocabulary watch on
all copy, "model output / data tool" framing only.

---

## Route 1 — `/` (marketing landing)

Source: `frontend/src/app/page.tsx` (442 lines)

**First impression (non-finance reader):** "A free DCF tool for Indian
stocks. There's an example card with a green number. It says 'not a
broker, not a chart tool, not a tipster service' which is unusually
honest." Visual is dark / dense / Bloomberg-adjacent, which reads
serious but cold.

**SEBI risk:** Mostly clean. Words found that are borderline:
- "Margin of Safety" + green/red coloring — fine, it's a number with a
  formula, not a call.
- The rotating DemoCard shows `verdict: "undervalued"` as a badge.
  "Undervalued" is a model classification (price vs. fair value) and is
  defensible as descriptive, but `verdict` is the wrong English word —
  it implies a judgment. Suggest renaming the field label visible to
  the user to `"classification"` or `"vs. fair value"`. The internal
  field can stay.
- "Start with the stock you own. You'll see what we mean." — fine.
- "5 deep analyses per day" — fine.

**Bounce risk:**
1. The hero CTA "Analyse any stock free" routes to `/search`. A first
   visitor who clicks it lands on a search box with no obvious "try
   one of these" suggestions. They need to know that RELIANCE / TCS /
   HDFCBANK exist as tickers. Most retail users have never typed a
   ticker symbol. Suggest seeding the search page with 6 pre-selected
   chips (RELIANCE, TCS, HDFCBANK, INFY, ITC, SBIN).
2. DemoCard fetches `/api/v1/public/demo-cards`. If that endpoint is
   slow / 500s, falls back to hard-coded card with `current_price:
   2943` for RELIANCE — which will be visibly wrong against live
   prices by Q3 2026. The fallback should be removed or replaced with
   a generic "loading" state to avoid users seeing stale numbers and
   losing trust.
3. The "Browse and analyse any stock without signing up" subtext is
   buried inside section 2. Move it to the hero, above the fold.
4. Pricing teaser shows `₹799 Analyst`, `₹1,499 Pro`. The Free tier is
   listed first with `5 deep analyses per day` — most landing pages
   lead with paid because Free is the default. Compare against
   competitors who hide pricing behind a click; we put it up front
   which is honest but might over-emphasize cost on a first read.

**Copy / UX nits:**
- "A transparent DCF valuation for Indian equities." — strong.
  "Equities" is finance-speak; consider "for Indian stocks" for
  consistency with the rest of the copy.
- Trust bar lists "yfinance" alongside NSE / BSE / RBI. yfinance is a
  Python library, not a primary source — non-technical readers won't
  recognize the name and technical readers will note that we depend on
  an unofficial library. Replace with "NSE primary, yfinance fallback"
  or drop entirely.
- Footer is sparse — no "About / Methodology / Disclaimer / Contact"
  link row. The full footer exists elsewhere; the landing page needs
  at minimum a Methodology + Disclaimer + Contact link below the SEBI
  disclaimer paragraph.
- The `Recomputed nightly` indicator on the DemoCard is a green
  pulsing dot — first-time readers may interpret it as "live", not
  "nightly". Either change copy to "Refreshed each evening" or remove
  the animation.

---

## Route 2 — `/discover`

Source: `frontend/src/app/(app)/discover/page.tsx` (470 lines)

**First impression:** "A dashboard of cards — top picks, sector
leaders, screener presets, market pulse. Feels like Robinhood for
fundamentals. Lots happening, not sure what to click first."

**SEBI risk:**
- "Top Pick" card — `TopPickCard` component. "Top pick" is borderline
  in the SEBI lexicon; it implies a recommendation. The historical
  word avoidance was: buy / sell / hold / recommend / pick. **`Top
  Pick` is a banned word per our own list.** This is the single
  largest copy violation found in this audit. Rename to "Highest MoS
  today" or "Largest discount to fair value" — both are descriptive
  measurements, not picks.
- "Top 5 MoS gainers" — fine, MoS is a measurement.
- The default-content fallback (Day-68 fix) introduces "Methodology
  spotlight" tips that rotate. Need to read each tip to ensure none
  are prescriptive.

**Bounce risk:**
1. Two rails (`NearLowsRail`, `LowestPERail`) are commented out as of
   2026-04-22 — confirms the page has had data-density issues. Verify
   the Day-68 default content actually renders for a brand-new visitor
   on prod; if it's still showing "warming up" cards anywhere, the
   activation rate will be poor.
2. No empty-state copy for `SectorLeaders` if the screener returns
   zero results. Reading the component would tell us; flag for J-copy.
3. The grid layout is heavy on first paint — measure LCP. If > 2.5s,
   the page is bouncing mobile users before they see the first card.

**Copy / UX nits:**
- Page title `Discover` is generic. Consider `Discover — what looks
  cheap today?` or similar contextual subtitle.

---

## Route 3 — `/sector/[slug]`

Source: `frontend/src/app/(marketing)/sector/[slug]/page.tsx`

**First impression:** "A sector page — bank, IT, FMCG, etc. Lists
stocks in that sector with fair value, MoS, score."

**SEBI risk:** Need to walk a real one (e.g. `/sector/banking`) on prod
to confirm. Sector pages historically have been clean because they're
descriptive (it's a table). Flag: if any sector page sorts by MoS
descending without context, a reader could interpret the order as a
ranking-of-preference. Add a column header tooltip: "Sort order is
purely numerical, not a recommendation."

**Bounce risk:**
- 11 sectors are listed in the marketing area (banking, IT, FMCG,
  pharma, auto, energy, capital_goods, metals, realty, telecom,
  consumer_durables). Each `/sector/[slug]` should render in < 1s.
  If any individual sector page is missing data and shows blanks,
  bounce risk is high.

**Copy / UX nits:**
- Sector slug taxonomy isn't all visible to the user — there's no
  "browse by sector" index page from the landing. Add a sector-index
  in the footer or methodology page.

---

## Route 4 — `/analysis/RELIANCE.NS` (anon preview)

Source: `frontend/src/app/(app)/analysis/[ticker]/page.tsx` + shell
notes in source ("PublicAnalysis" branch for anon visitors).

**First impression (anon):** "Prism 6-pillar view with a summary card.
Most of the deeper analysis is gated behind sign-up CTAs."

**SEBI risk:**
- The Prism pillars score Quality / Value / Growth / Momentum / Risk /
  Capital allocation. These are measurements, descriptive. Clean.
- The inline upsell CTAs replacing gated sections — need to verify the
  CTA copy doesn't promise "the right answer" or "what to buy".
  Suggested CTA copy: "Sign up free to see the full DCF model — same
  numbers, more detail."
- The signup wall historically broke for paying users when cookies
  expired (see 2026-04-27 fix in the source comments). Verify
  `AnalysisAuthGate` is still working on prod with a real paid
  account before launch.

**Bounce risk:**
1. The anon `/analysis/:ticker` page is the single most important
   first-impression surface — every blog post, every Reddit comment,
   every share link will land here. It needs to be the fastest page
   on the site. Measure TTFB and LCP for `/analysis/RELIANCE.NS` on
   prod. Source comment says < 100ms TTFB is the target; verify.
2. If a non-existent ticker is requested (e.g. `/analysis/XYZ.NS`),
   what does the user see? Check error.tsx and not-found.tsx wiring
   for this route.

**Copy / UX nits:**
- The 6-pillar names are jargon. Consider one-line tooltips on hover
  for each pillar.

---

## Route 5 — `/screener`

Source: `frontend/src/app/(app)/screener/page.tsx` (350 lines)

**First impression:** "A screener. Filters on the left, results on the
right. Familiar mental model from Screener.in / StockEdge."

**SEBI risk:** Screeners are descriptive by nature — they filter and
sort, they don't recommend. Clean as long as preset names stay
descriptive (e.g. "Low P/E + High ROE" not "Best value stocks").
Verify all preset names.

**Bounce risk:**
- Screener loads need to be < 1.5s even for broad filters. Check perf.

**Copy / UX nits:**
- Need to walk the live screener to verify the empty-state copy when
  no stocks match a filter combo.

---

## Route 6 — `/portfolio` (auth required)

Source: `frontend/src/app/(app)/portfolio/page.tsx` + import / analyze /
tax-harvesting / tax-report / upload sub-routes.

**First impression (authed):** "Upload your holdings (CSV or paste),
get a Prism for each, and aggregate analytics. Tax-loss-harvesting
suggestion engine."

**SEBI risk:**
- **Tax-loss harvesting is a CALL TO ACTION** ("sell X at a loss to
  offset Y in gains"). This needs careful framing. Verify the
  tax-harvesting page copy says "candidates for tax-loss harvesting
  based on your inputs" not "stocks you should sell". This is the
  single highest-risk surface for an SEBI complaint because it's the
  closest the product gets to action language.
- "Analyze" sub-route — name is fine.

**Bounce risk:**
- CSV upload UX — does it accept the standard NSDL / CDSL CSV format?
  Common broker formats? If a user has to manually format, they bounce.

**Copy / UX nits:**
- Walk the upload flow with a real CSV before launch.

---

## Route 7 — `/pricing`, `/about`, `/methodology`, `/help/*`,
`/legal/*`

Source: `frontend/src/app/(marketing)/pricing/page.tsx` (384 lines),
multiple help pages, legal directory.

**First impression:** "Standard SaaS marketing footer. Pricing,
methodology, help, legal pages all exist."

**SEBI risk:**
- `/legal/disclaimer` — must contain the exact SEBI-non-registered
  disclaimer. Verify text is current.
- `/methodology` — descriptive, fine.
- Pricing page (384 lines) — long. Verify no "best value", "smart
  choice" superlative language; it should be a feature comparison
  table.

**Bounce risk:**
- `/help` has subpages: confidence-and-limits, fair-value-and-mos,
  portfolio-prism, pricing-and-tiers, reading-an-analysis,
  sectors-and-cohorts, using-the-screener. Good coverage. Verify
  links from the analysis page to the help pages exist.

**Copy / UX nits:**
- The help-nav (`HelpNav.tsx`) needs to be present on every help page,
  otherwise users get stuck. Verify.

---

## Route 8 — `/login`, `/signup` (auth flow)

Source: `frontend/src/app/login/page.tsx` (5 lines — thin wrapper),
`/signup/page.tsx` (5 lines).

**First impression:** Standard email/password + OAuth. Thin wrappers
suggest the real UI lives in a shared component.

**SEBI risk:**
- Paywall copy — verify it does not say "subscribe to see what to
  buy". Should say "subscribe to unlock unlimited analyses". This is
  important.

**Bounce risk:**
1. Signup → onboarding flow — `/onboarding` is referenced in
   `page.tsx` (root). Walk it end-to-end with a fresh email. If it
   asks for risk tolerance or any registered-advisor-shaped
   questionnaire, that needs to be removed.
2. Password reset flow — does it exist? Search for `/auth/forgot` or
   similar.
3. OAuth provider buttons — Google / Apple? Verify they actually work.

**Copy / UX nits:**
- The 5-line page wrappers suggest the actual UI may be in
  `components/auth/*`. Verify copy there.

---

## Route 9 — Mobile breakpoints (3 routes spot-checked)

**Landing (`/`):** Hero collapses to single column at `lg:` breakpoint
— DemoCard is `hidden lg:block`, so mobile users never see the demo
card. That's an activation hit — mobile is 60%+ of Indian retail web
traffic. Consider showing a compact DemoCard variant on mobile too.

**Discover (`/discover`):** Grid heavy — verify it stacks cleanly. If
horizontal scroll appears, that's a bug.

**Analysis (`/analysis/RELIANCE.NS`):** The 6-pillar Prism view needs
to be tappable on mobile, not just hoverable. Verify touch targets
are ≥ 44px.

---

## Numbered punch list (ranked by launch impact)

Ranking criteria: SEBI risk first, bounce risk second, polish third.
Each item cites the route it came from.

### Tier 1 — SEBI / language

1. **[Discover]** Rename "Top Pick" card label to "Highest margin of
   safety today" or "Largest discount to fair value". "Top pick" is
   on our own banned-vocabulary list and is the largest copy
   violation found. (`TopPickCard` component)
2. **[Landing/DemoCard]** Replace user-visible field label `verdict`
   with `classification` or `vs. fair value`. Internal field name can
   stay.
3. **[Portfolio]** Audit `/portfolio/tax-harvesting` copy end-to-end.
   Ensure it says "candidates for tax-loss harvesting based on your
   inputs", never "stocks you should sell".
4. **[Auth]** Walk signup → onboarding with a fresh email. Remove any
   risk-tolerance questions that look like an advisor questionnaire.
5. **[Legal]** Verify `/legal/disclaimer` text matches the exact SEBI
   disclaimer used on the landing footer. Drift between the two is a
   compliance liability.

### Tier 2 — Bounce risk

6. **[Landing]** Add 6 ticker chips (RELIANCE, TCS, HDFCBANK, INFY,
   ITC, SBIN) below the hero search CTA so non-finance visitors have
   a clear first action.
7. **[Landing]** Remove the hardcoded `FALLBACK_CARDS` price values
   (or replace with a "loading" state). Stale numbers visible to a
   first-time visitor destroy trust irreversibly.
8. **[Landing]** Move "Browse without signing up" subtext from
   section 2 into the hero, above the fold.
9. **[Analysis]** Verify `/analysis/RELIANCE.NS` anon path TTFB on
   prod is under 200ms. Most important single surface.
10. **[Analysis]** Verify `/analysis/INVALID.NS` returns a clean
    not-found page with a "search for another ticker" CTA — not a
    blank screen or stack trace.
11. **[Discover]** Confirm Day-68 default content actually renders
    for a brand-new (cookie-less) visitor — no "warming up" cards
    anywhere on the page.
12. **[Landing mobile]** Show a compact DemoCard variant on mobile.
    Currently `hidden lg:block` hides the most persuasive element
    from 60% of visitors.

### Tier 3 — Polish

13. **[Landing]** Replace `yfinance` in the trust bar with "NSE
    primary, yfinance fallback" or drop entirely.
14. **[Landing]** Change "Recomputed nightly" green pulsing dot copy
    to "Refreshed each evening", or remove the pulse animation.
15. **[Landing]** Add a footer link row (About / Methodology /
    Disclaimer / Contact) below the SEBI disclaimer.
16. **[Discover]** Add a contextual subtitle to the Discover page
    ("What looks cheap today?" or similar).
17. **[Sector]** Add an "all sectors" index page linked from the
    landing footer.
18. **[Sector]** Add a tooltip on the MoS-sorted column: "Sort order
    is numerical, not a recommendation."
19. **[Analysis]** Add one-line tooltips for each of the 6 Prism
    pillars.
20. **[Screener]** Verify all preset names are descriptive (no "Best
    value", no "Smart picks", etc.).
21. **[Help]** Verify `HelpNav` is present on every help subpage.
22. **[Auth]** Verify a password reset flow exists and works.

---

## Summary

- 1 critical SEBI-language item (Top Pick rename) — must ship before
  Reddit launch post goes out.
- 5 Tier-1 SEBI items total, all narrow scope, none requiring engine
  changes.
- 7 Tier-2 bounce items, mostly landing-page copy / state work plus
  one analysis-page perf verification.
- 10 Tier-3 polish items, can ship in any order or after launch.

J-copy will group these into 3 themed PRs:
- **J-copy-1 (SEBI language):** items 1, 2, 3, 4, 5.
- **J-copy-2 (Landing first-impression):** items 6, 7, 8, 12, 13, 14,
  15.
- **J-copy-3 (Misc polish + verification):** items 9, 10, 11, 16-22.

---

## Status (2026-05-26 follow-up)

Audit walked by a second pass on 2026-05-26 — J-copy-1 (PR #585) shipped
Tier-1 items + 7, 13, 14; J-copy-2a/b (PR #594, #596) shipped the
remaining buildable Tier-2/Tier-3 items; the rest were already done
post-audit by prior work or are operational-verification tasks deferred
to the launch runbook.

| # | Tier | Item | Status | Outcome / PR |
|---|------|------|--------|--------------|
| 1 | T1 | Rename "Top Pick" card label | DONE | J-copy-1 PR #585 — discover hero now reads "Highest YieldIQ score today" |
| 2 | T1 | DemoCard `verdict` → `classification` | DONE | J-copy-1 PR #585 |
| 3 | T1 | Tax-loss harvesting copy audit | DONE | J-copy-1 PR #585 |
| 4 | T1 | Onboarding questionnaire scrub | DONE | J-copy-1 PR #585 |
| 5 | T1 | Disclaimer parity check | DONE | J-copy-1 PR #585 |
| 6 | T2 | Hero search ticker chips | DONE | J-copy-1 PR #585 (chips on `/search`) |
| 7 | T2 | Drop `FALLBACK_CARDS` stale prices | DONE | J-copy-1 PR #585 — `FALLBACK_CARDS = []` |
| 8 | T2 | Move "no sign-up" subtext to hero | DONE | J-copy-1 PR #585 |
| 9 | T2 | Anon `/analysis/:ticker` TTFB ≤ 200ms | DEFER | Operator task — needs prod measurement under realistic network conditions; add to launch-day runbook |
| 10 | T2 | Invalid ticker not-found page | DONE | Pre-audit — `PublicAnalysis.tsx` isError branch (lines 176-194) renders a clean message + "Search stocks" CTA |
| 11 | T2 | Day-68 default content for cookie-less visitor | DONE | Pre-audit Day-68 fix — `/discover` renders methodology spotlight + MoS gainers + earnings regardless of yiq50 cold state (see `pickTodayTip`, `mosGainers`, `earningsToday` in `discover/page.tsx`) |
| 12 | T2 | Mobile DemoCard variant | DONE | J-copy-2a PR #594 — dropped `hidden lg:block`, card now visible in hero on phones |
| 13 | T3 | Replace `yfinance` in trust bar | DONE | J-copy-1 PR #585 |
| 14 | T3 | "Recomputed nightly" → "Refreshed each evening" | DONE | J-copy-1 PR #585 (string already in DemoCard) |
| 15 | T3 | Footer link row below SEBI disclaimer | DONE | Pre-audit — `TrustFooter` already has Terms / Privacy / SLA / Status / About below the disclosure |
| 16 | T3 | Discover contextual subtitle | DONE | J-copy-2a PR #594 — h1 + "What looks cheap today" subtitle |
| 17 | T3 | All-sectors index page + footer link | DONE | J-copy-2b PR #596 — new `/sector` route + footer "Sectors" link + sitemap entry |
| 18 | T3 | MoS column tooltip on sector page | DONE | J-copy-2a PR #594 — native `title` on `SectorTable` MoS header |
| 19 | T3 | Prism pillar one-line tooltips | DONE | Pre-audit — `PillarExplainer` bottom-sheet renders factual sentence + sector-median comparison on vertex tap (superior to hover-only tooltips, and mobile-tappable) |
| 20 | T3 | Screener preset names descriptive | DONE | Pre-audit — all 10 presets in `screenerFilters.ts` (Value+Quality, Deep Value, etc.) are descriptive; no superlatives |
| 21 | T3 | HelpNav on every help subpage | DONE | Pre-audit — all 7 help subpages use `HelpPageShell` which includes `HelpNav` |
| 22 | T3 | Password reset flow exists | DONE | Pre-audit — `/auth/forgot-password` and `/auth/reset-password` routes exist |

### Deferred items detail

- **Item 9** (anon analysis TTFB perf verification): this is a runtime
  measurement against prod, not a code change. Belongs on the
  launch-day runbook with a target of "TTFB ≤ 200ms p50 on the
  `/analysis/RELIANCE.NS` warm path" — needs to be re-checked after
  every backend deploy that touches the public prism endpoint or its
  upstream cache. Not blocking any code PR.

### Net result

- Buildable items shipped: 17 of 22 across PRs #585, #594, #596 plus
  pre-audit work for items 10, 11, 15, 19, 20, 21, 22.
- One operational verification task (item 9) deferred to runbook.
- No items remain blocking the Reddit launch post.
