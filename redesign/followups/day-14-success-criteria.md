# Day-14 success criteria — content experiment + two-week deadline

**Status:** filed 2026-06-03, before any data exists. **Pre-committed by design** — the entire point is to write these thresholds DOWN before the data comes in, so the operator cannot rationalize an ambiguous middle number either direction on day 14.

**Decision date:** 14 days after sitemap submission to Google Search Console (NOT 14 days after content PR merges — the clock starts at submission).

---

## The honest framing on the SEO clock

SEO impressions land on Google's schedule, not the operator's. The realistic timeline for the 12-page programmatic SEO experiment:

| Day | What's reasonable |
|---|---|
| 0 | Sitemap submitted to Search Console |
| 1–5 | Googlebot crawls the new URLs (visible in Search Console "Crawled - currently not indexed" status, then "Submitted and indexed") |
| 5–10 | First indexed pages show in Search Console Performance > Search results > Impressions tab (usually trickle, not flood) |
| 10–14 | Pattern across the 12 pages becomes readable as a leading indicator — NOT as final impression volume |
| 14–30 | Real impression volume settles; query-fit becomes clear |
| 30–90 | Click-through and conversion data accumulates if impressions justify it |

**Day 14 is too early for lagging indicators (clicks, signups, payments via SEO). It is correct for leading indicators (indexing, query-discovery, impression-presence).** The thresholds below are designed against this reality.

---

## The three-tier decision matrix

### Tier 1 — Indexing (the most important leading indicator)
**Question:** Did Google index the 12 new pages at all?

**How to read on day 14:** Search Console → Coverage report → filter to pages under `/fair-value/`. Count "Submitted and indexed" vs "Submitted, not indexed" vs "Discovered – currently not indexed" vs "Crawl errors."

| Indexed count (of 12) | Verdict | Next action |
|---|---|---|
| 10–12 | ✅ Indexing healthy. Move to Tier 2 to evaluate query-fit. | Continue — read impressions. |
| 5–9 | ⚠️ Partial indexing — Google has technical concerns or low quality signals on some pages. | Diagnose: open Search Console URL Inspection on 2-3 unindexed URLs, read the rejection reason. Common: thin content, duplicate content, low E-E-A-T. Fix the template, request reindex. Do NOT add more pages until existing 12 index. |
| 0–4 | 🛑 Indexing failure — almost certainly a technical issue (sitemap not submitted, robots.txt blocking, canonical loop, JSON-LD invalidating). | DO NOT conclude anything about SEO viability. Diagnose technical first. Re-verify sitemap submission, re-check robots.txt allows `/fair-value/`, re-validate JSON-LD via Rich Results Test. |

### Tier 2 — Any impressions at all (the query-fit signal)
**Question:** Are people searching queries that match these pages, even if rarely?

**How to read on day 14:** Search Console → Performance → filter to `/fair-value/` URLs → look at total impressions across all 12 pages over the last 7 days.

| Total impressions (7-day, across all 12 indexed pages) | Verdict | Next action |
|---|---|---|
| 100+ | ✅ Query-fit confirmed. Scale to 50 pages. The bet is real. | Plan the next 38 pages; consider mid-cap tickers next, longer-tail keywords. |
| 25–99 | ✅ Query-fit present but ranking is low. Each page sees a few impressions = pages exist on result pages 3-10. With time + age + backlinks, they climb. | Hold at 12 pages, do not add more yet. Wait the additional 2 weeks for the lagging signal (clicks, ranking improvement) before scaling. |
| 5–24 | ⚠️ Marginal — possibly real, possibly within noise. Watch which 1-2 tickers get most impressions; those are the queries with real volume. | Examine the top-impression page individually. If it's a high-search ticker (RELIANCE / HDFCBANK), the channel works but ranking will take longer. If it's a random tail, query-fit is weak. |
| 0–4 | 🛑 Either pages aren't indexed (re-check Tier 1) or queries have no volume / pages are buried beyond page 10 of results. | Don't scale to more pages. Diagnose: pick the highest-search ticker (HDFCBANK), Google "HDFCBANK fair value" in Indian incognito, see where YieldIQ ranks. If not in top 30, ranking issue not query issue. |

### Tier 3 — Errors / health (the don't-bleed-trust check)
**Question:** Are the indexed pages clean — no crawl errors, no Core Web Vitals warnings, no SEBI vocabulary lints?

**How to read on day 14:**
- Search Console → Coverage → "Error" and "Valid with warnings" tabs
- Search Console → Core Web Vitals (separate for mobile + desktop)
- Re-run `scripts/check_sebi_words.py` on the deployed template output

| Health state | Verdict | Next action |
|---|---|---|
| Clean | ✅ Continue per Tier 2's call | Nothing |
| 1-3 errors / warnings | ⚠️ Fix the specific page(s) flagged | One-page PR; do not let it block scaling |
| Widespread errors | 🛑 Template has a structural issue — pause scaling | Fix template, redeploy, request reindex |

---

## The pivot-vs-persist meta-rule

If at day 14:
- **Tier 1 = healthy AND Tier 2 = 100+** → SEO is viable. Two-week deadline says "scale this." Plan next 38 pages. Distribution channel exists.
- **Tier 1 = healthy AND Tier 2 = 25-99** → SEO is plausible but slow. Two-week deadline says "hold and let it mature; do not scale or pivot yet." Re-read at day 30.
- **Tier 1 = healthy AND Tier 2 = 5-24** → SEO might work for specific queries; hold, study the top-impression pages, do NOT generalize.
- **Tier 1 = healthy AND Tier 2 = 0-4** → SEO is unlikely to be the channel at YieldIQ's current authority level. Pivot to fast-channel distribution (Reddit / Twitter / community posts / paid acquisition). Do not write more programmatic content.
- **Tier 1 = unhealthy** → The experiment hasn't started; fix technical, do not conclude.

**The trap to pre-commit against:** at day 14 with a Tier-2 score of, say, 15 impressions, it will be tempting to read this as "we're getting traction!" because anything beats zero. **Re-read this document on day 14 BEFORE looking at any numbers**, then look at the numbers, then apply the rule above. The pre-commitment is what stops the rationalization.

---

## What day 14 cannot tell you

- **Conversion to paid.** Two weeks via SEO is structurally too short for SEO → click → trial → payment. Any paid users in the window who came via SEO are bonus; their absence is not signal.
- **Lifetime value of SEO traffic.** Need 90+ days.
- **Whether the SEBI line in the content template ages well.** Need a Google human reviewer to ever look (rare) or a user complaint (rarer) to discover.

These are read on different clocks. Day 14 is the *indexing-and-query-discovery* check, not the business check.

---

## The fast-channel parallel — also read at day 14

The 2-week deadline is shorter than SEO's structural feedback window. So the deadline must be read against BOTH the SEO leading indicators above AND a fast-channel signal that fits inside 14 days.

**Fast-channel hypothesis (operator picks the channel + ticker):** one honest YieldIQ analysis post on `<community>` for `<ticker>` drives ≥X visits to the page, ≥Y signups, ≥Z paid conversions within 7 days of posting.

Pre-committed thresholds (operator fills in target numbers; suggested starting points):
- Visits to the page within 7 days: target 100+
- Signups from those visits: target 5+
- Paid conversions within 14 days: target 1+ (one stranger paying ₹799 is the entire "working as a business" proof; even one closes the loop)

**This is the channel whose feedback fits inside the deadline.** SEO is the durable bet; the fast channel is what gives the operator a real conversion signal by day 14.

---

## Calendar reminders to set NOW

- **Sitemap submission day:** the day the content PR merges (record the date here when it happens: `_______`)
- **Day 7 check (interim):** indexing progress only (Tier 1) — verify pages are crawling
- **Day 14 read:** full three-tier evaluation against this document
- **Day 30 re-read:** if Day 14 = "hold and mature," this is when the patience pays off or doesn't

---

## Cross-references

- `redesign/audits/funnel-2026-06-03/AUDIT.md` — the original funnel finding (~3 DAU, acquisition the constraint)
- `redesign/followups/payment-observability-2026-06-03.md` — where stranger conversions will be visible (Razorpay → Supabase `subscriptions` table → eventual Slack alert once payment-alert PR ships + env var is set)
- Content experiment PR — when it lands, the URL goes here: `_______`
- Search Console submission timestamp — record here: `_______`
