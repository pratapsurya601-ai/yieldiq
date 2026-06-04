# Analysis-page LCP 3,521ms — perf-cycle tracker

**Status:** filed 2026-06-04 from AlphaSpread comparison audit. **NOT actionable until day-14 Search Console read.**
**Priority:** CONDITIONAL — becomes acquisition-touching only IF the SEO content experiment shows impressions on `/fair-value/<ticker>` pages.

## The finding

From the YieldIQ-vs-AlphaSpread anonymous first-time-visitor comparison (`redesign/audits/alphaspread-comparison.md`):

- YieldIQ **landing** page anonymous LCP: **731 ms** ✅ (lab measurement, 1x CPU, no throttling)
- YieldIQ **analysis page** (HDFCBANK) anonymous LCP: **3,521 ms** ❌ — breakdown: 592 ms TTFB + 2,929 ms render delay

A stranger landing on a shared `/analysis/<TICKER>` URL from Google search has a non-trivial probability of bouncing in that 3.5s window before any content paints. Google's PageSpeed Insights "good LCP" threshold is 2.5s; this exceeds it by 40%.

## Why this is NOT urgent right now

At ~3 DAU with no SEO traffic landing on analysis pages, the bounce risk is theoretical, not actualized. The content experiment ships traffic to `/fair-value/<TICKER>` pages (which are server-rendered prose, much faster), and that traffic only clicks through to `/analysis/<TICKER>` after the user has already chosen to engage. The first-impression page is fast; the deep-dive page is slow.

The five acquisition PRs shipped this session correctly did NOT touch perf because perf is retention work disguised as acquisition work — UNTIL there's actual traffic to bounce, this is a theoretical loss.

## When this becomes urgent

**Day-14 Search Console read (2026-06-18):** if Tier-2 of the `day-14-success-criteria.md` framework returns ≥ 100 impressions across the 12 `/fair-value/` pages, AND a non-trivial fraction of those impressions are turning into clicks to `/analysis/<TICKER>`, then the 3.5s LCP becomes a real bounce-rate cost on real traffic — and perf-cycle work earns its hours.

**Decision rule for that read:** if `/analysis/<TICKER>` pages start receiving organic impressions in Search Console (separate from the new `/fair-value/` content), the bounce-rate cost is immediate and perf-cycle is the next thing after the content scale-up. If only `/fair-value/` pages get impressions and the click-through to `/analysis/` is sparse, the perf work waits.

## What a perf-cycle PR would look like (NOT for this session)

Phase 0 (diagnosis, ~1 hour):
- Open Chrome DevTools Performance tab on `https://yieldiq.in/analysis/HDFCBANK` anonymous
- Identify the LCP element (likely the Prism SVG or the HonestHero side rail)
- Identify what's blocking render until 2.9s — likely a combination of:
  - The `useHeroSignals` hook awaiting client-side data fetch before the Prism mounts
  - The Prism component's SVG path computation
  - The freshness chip queries that fire as a waterfall after initial render
- Read the agent's screenshot trace if it's saved alongside the audit

Phase 1 (likely fixes, all small):
- Move more of the hero data into the server component's initial render so the LCP element doesn't wait on hydration
- Defer non-critical components (`<NarrativeSummary>`, `<MemoryLane>`, the section list) below the fold
- `<Suspense>` boundaries around the Prism so it doesn't block above-fold paint
- Image preload hint for the OG/hero asset

Scope: 1-2 frontend PRs after the diagnosis. Not weeks of work.

## Cross-references

- `redesign/audits/alphaspread-comparison.md` (parent finding)
- `redesign/followups/day-14-success-criteria.md` (the read that gates this work)
- Phase 0 premise-check P0.4 (the four-hero retire already cleaned up the initial render surface, which is part of why LCP isn't worse — but the Prism + scenario components remain the slow spot)

## DO NOT

- Spawn a perf-cycle agent before day-14 Search Console data exists.
- Treat "the page is slow" as a known acquisition gap. It's a *conditional* gap — real only if real traffic arrives.
- Let this sit forgotten if day-14 reads "scale to 50 pages." This tracker is the reminder to check LCP-vs-traffic at that decision point.
