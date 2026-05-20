# YieldIQ Week-3 SEO Audit (Day 39)

**Date**: 2026-05-20
**Scope**: `/analysis/[ticker]`, `/public/<ticker>`, sitemap, robots, JSON-LD, OG images
**Method**: Static code audit
**Deliverable**: Ranked issue list seeding Days 40-42

---

## TL;DR — 6 issues, 3 days

| # | Issue | Severity | Day |
|---|---|---|---|
| 1 | No JSON-LD structured data (FinancialProduct + BreadcrumbList) | **HIGH** | 40 |
| 2 | `/analysis/{ticker}` missing from dynamic sitemap; stale fallback | **HIGH** | 40 |
| 3 | No `canonical` URL on `/analysis/{ticker}` | MED | 41 |
| 4 | Peer/sector links absent on public analysis page | MED | 41 |
| 5 | `robots.txt` missing crawl-budget hints | LOW | 42 |
| 6 | OG image metadata incomplete (`alt`, `image:type`, `secure_url`) | LOW | 42 |

**Total scope: ~650 LOC across 4 files.**

---

## Day 40: JSON-LD + sitemap

### JSON-LD (zero today)
Status: NO structured data emitted anywhere. Google's Rich Results crawler sees the FV/MoS/score as plain text — invisible to financial-result rich snippets.

Plan:
- New SSR component `src/app/(app)/analysis/[ticker]/JsonLd.tsx`
- Emits `FinancialProduct` schema (FV / price / MoS / score) + `BreadcrumbList` (Sector → Stock)
- Imported into the analysis layout

### Sitemap
Status: Dynamic sitemap `src/app/sitemap.ts` covers `/stocks/{ticker}/fair-value`, `/hex/{ticker}`, `/prism/{ticker}` — but NOT `/analysis/{ticker}` (the actual entry surface). Plus a stale `public/sitemap.xml` from 2026-04-25 with only 20 tickers.

Plan:
- Remove `public/sitemap.xml` (stale; the dynamic one supersedes it)
- Add `/analysis/{ticker}` to dynamic sitemap routes
- Reduce `revalidate` from 86400 → 3600 so new tickers surface in 1h not 24h

---

## Day 41: Canonical + peer links

### Canonical URLs
Status: `layout.tsx:35` `generateMetadata` has no `canonical` field. Google may index `/analysis/RELIANCE.NS` and `/analysis/RELIANCE.NS?utm_source=foo` as separate pages.

Plan: add `alternates.canonical: "https://yieldiq.in/analysis/{ticker}"`.

### Peer / sector internal links
Status: Public analysis page links only to the company itself. Breadcrumb sector / exchange / cap-tier are TEXT (not clickable). No peer recommendation block.

Plan:
- Make Breadcrumb sector clickable → `/stocks?sector={s}` faceted view
- Add 3-4 top-peer cards below the hero (anon users see them too — drives discovery + SEO)
- Link related indices (NIFTY 50 / NIFTY NEXT 50) when applicable

---

## Day 42: robots + OG polish

### robots.txt
Status: Basic Allow/Disallow. Missing crawl-budget hints. Google will hammer the public API during a full crawl.

Plan:
- Explicit `Allow: /stocks`, `Allow: /prism`, `Allow: /hex`
- Optional `Crawl-delay: 1` for non-Google bots
- `User-agent: Googlebot` block without crawl-delay (Google ignores it anyway)

### OG image metadata
Status: 4 OG routes already cover ticker / analysis / prism / hex. Missing:
- `og:image:alt` for accessibility
- `og:image:type: image/png` for older scrapers
- `og:image:secure_url` redundancy

Plan: add the 3 fields to `layout.tsx` Metadata object.

---

## Sprint mechanics

3 PRs (Days 40, 41, 42). Each carries:
- The fix
- Regression-guard tests (Python source-text, same Week-2 pattern)
- No CACHE_VERSION bump (pure frontend + SEO)
- No backend changes (sitemap is SSR)

After Day 42, install Google Search Console + Bing Webmaster Tools and submit the updated sitemap. Re-audit in 30 days for impression / click delta.
