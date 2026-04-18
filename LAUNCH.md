# YieldIQ Prism — Launch Kit

Paste-ready copy for Product Hunt, X/Twitter, r/IndiaInvestments, WhatsApp, and the launch blog post.
Everything here is SEBI-safe. No "buy/sell/hold" language anywhere.

---

## Before you launch — 10-minute checklist

1. **Trigger operational workflows** (GitHub → Actions → Run workflow). In this order:
   - [ ] **BSE Code Backfill** — unlocks promoter holding + pledged signals (~5 min)
   - [ ] **Fundamentals Gap Backfill** — fills 580 missing tickers (~15 min)
   - [ ] **Cache Warmup Top 500** — warms Prism cache (~30 min first run, <3 min after)
   - [ ] **Pulse Daily Data Refresh** — pulls estimate revisions + NSE deals (~10 min)
   - [ ] **Hex History Weekly Backfill** — populates Time Machine (~5 min)

2. **Clear the Prism cache** so the hex_service fix is applied to live data:
   ```js
   // Paste in browser console while logged into yieldiq.in as admin:
   fetch('https://api.yieldiq.in/api/v1/admin/cache/clear?prefix=prism:', {
     method: 'POST',
     headers: { Authorization: `Bearer ${JSON.parse(localStorage.getItem('yieldiq-auth')).state.token}` }
   }).then(r => r.json()).then(console.log)
   ```

3. **Verify**: open `/analysis/TCS.NS` → all 6 Prism pillars should light up (Safety/Growth/Value no longer n/a).

4. **Screenshot** `/analysis/TCS.NS` and `/prism/RELIANCE` (or your favorite stock) — these are your hero images.

5. **Submit sitemap** to Google Search Console (if not already done): `https://yieldiq.in/sitemap.xml`

---

## X / Twitter — Launch thread

### Tweet 1 (hero)
> Introducing **The YieldIQ Prism**.
>
> Every stock has a Signature — 6 pillars refracting fundamental data into one visual verdict.
>
> Unfold it into a Spectrum and you can *see* where the thesis breaks.
>
> Free for every NSE & BSE stock. 🇮🇳
>
> yieldiq.in/prism/RELIANCE
>
> [screenshot of Prism]

### Tweet 2
> Why build this?
>
> Simply Wall St's Snowflake is beautiful. But it's global-generic and ignores India-specific signals — promoter stake changes, insider filings, SEBI SAST disclosures.
>
> The Prism's 6th axis is Pulse: our India-native behavioral feed.

### Tweet 3
> Built-in moves no competitor ships:
> · Live morph between Signature (radial) and Spectrum (linear)
> · Refraction Index — how "opinionated" the stock is
> · Time Machine — scrub 12 quarters, watch the shape breathe
> · Auto-narration — tap "Tell me the story" for a 45-sec guided read

### Tweet 4
> Fully free. Educational use. Not SEBI-registered investment advice.
>
> Try it on your favorite stock: yieldiq.in
>
> Built by a 2-person team in 60 days. Feedback welcome 🙏
>
> #IndianStockMarket #FinTwit #YieldIQPrism

---

## Product Hunt — submission

**Name:** YieldIQ Prism

**Tagline (60 chars):** See every stock's fundamentals refract into one verdict

**Description:**
> YieldIQ Prism is a signature visual for stock fundamentals built for Indian investors.
>
> Every stock passes through 6 research pillars — Pulse, Quality, Moat, Safety, Growth, Value — and refracts into a composite score and a plain-English verdict.
>
> Unlike radar charts, the Prism has two interchangeable views: a radial **Signature** (great for sharing) and a linear **Spectrum** (great for reading the story top-to-bottom). Tap to live-morph between them.
>
> What's unique:
> • **India-native data** — NSE filings, BSE shareholding XBRL, SEBI insider feeds
> • **Pulse axis** — promoter stake changes + insider trades + analyst revisions (nobody else visualizes these)
> • **Time Machine** — scrub through 12 quarters, watch the shape breathe
> • **Auto-narration** — AI-generated 45-sec story for any stock
> • **Refraction Index** — single scalar telling you how opinionated the stock's profile is
>
> Free for educational use. 2,900+ NSE/BSE stocks. Not registered with SEBI as an investment adviser.
>
> Try it: https://yieldiq.in/prism/RELIANCE

**First comment from maker:**
> Hey PH 👋 I'm the maker of YieldIQ. After 60 days of building, we're launching the Prism — a signature visual we think beats Simply Wall St's Snowflake for Indian stocks because we include promoter/insider/SAST behavioral signals that global tools don't touch.
>
> The whole product is free. Ask me anything about the methodology, the data sources, or why we chose a hexagon-to-spectrum morph over a radar chart.
>
> Would love to hear which stock you try first.

**Category suggestion:** Fintech, Investing, India

**Thumbnail:** Screenshot of `/analysis/TCS.NS` or the Prism hero

**Gallery:**
1. Editorial hero (analysis page with Prism)
2. Time Machine modal
3. Compare overlay (`/prism/compare/RELIANCE-vs-TCS`)
4. Portfolio Prism
5. /about page with SEBI disclosure

---

## r/IndiaInvestments — post

**Title:**
> I built a free tool that visualizes every NSE stock's fundamentals in one 6-axis shape — feedback welcome

**Body:**
> Hi everyone,
>
> I've been working on **YieldIQ** for the last two months and just launched our signature feature: the **Prism** — a 6-pillar visualization for every Indian stock.
>
> Unlike Screener.in (data-dense) or Tickertape (category buckets), the Prism gives you a *single memorable shape* per stock that you can share. Each of the 6 axes — Pulse, Quality, Moat, Safety, Growth, Value — is scored 0-10 with sector-adjusted formulas (banks use P/BV instead of DCF, IT uses revenue multiples, etc.).
>
> **What's unique for Indian retail:**
> - Pulse axis includes promoter stake changes (BSE XBRL), SEBI SAST insider filings, and analyst estimate revisions — signals Simply Wall St / Morningstar don't visualize
> - Sector-adjusted: banks, NBFCs, IT, FMCG get appropriate valuation methods
> - WACC calibrated to India 10-yr G-Sec (not US treasury) — materially changes fair values
> - 2,900+ stocks covered
>
> **It's fully free.** Built for educational use. Not SEBI-registered.
>
> Try it: https://yieldiq.in/prism/RELIANCE (or any NSE ticker)
>
> I'd especially love feedback on:
> 1. Are there stocks where the Prism shape looks "wrong" vs your mental model?
> 2. Would you screenshot/share the Prism? Why or why not?
> 3. What's missing that would make you a repeat user?
>
> Not here to pump anything — just want brutal feedback from investors who've looked at more balance sheets than marketing copy.
>
> Thanks 🙏
>
> (Mods: happy to edit or remove if this doesn't fit. All data sources are public filings.)

---

## WhatsApp (for personal network)

> Hey — finally launched the Prism. Built it so every NSE/BSE stock gets one memorable shape you can share. Would love if you check one stock you own and tell me what's missing.
>
> yieldiq.in/prism/[TICKER]
>
> Completely free. Not investment advice (SEBI disclaimer obviously). Just trying to build the India-first Simply Wall St.

---

## LinkedIn post

> After 60 days of building, we launched **YieldIQ Prism** today.
>
> The thesis: Indian retail investors deserve the quality of fundamental analysis Wall Street has had for decades. We built a signature visual — six pillars per stock, refracted into one composite — that makes the verdict legible in 2 seconds.
>
> We took inspiration from Simply Wall St's Snowflake, but rebuilt the axes with India-native data that global tools can't source: promoter stake changes, SEBI insider filings, WACC from the 10-yr G-Sec.
>
> Free for educational use. 2,900+ NSE/BSE stocks.
>
> Would love feedback from anyone who's looked at more balance sheets than marketing pitches.
>
> yieldiq.in
>
> #FinTech #IndianMarkets #InvestingTools

---

## Blog post — `/blog/introducing-the-prism`

**Title:** Introducing The YieldIQ Prism — one shape for every Indian stock

**Slug:** introducing-the-prism

**Meta description:** A 6-pillar visualization for NSE & BSE stocks. See every stock's fundamentals refract into a single composite verdict.

**Body:**

> Every investor has the same mental moment: "Wait — is this a good business at a fair price, or is something broken?"
>
> Answering that in 2 seconds — before you dive into 200-row tables — is the point of a signature visual. Simply Wall St built the Snowflake for it. Morningstar built star ratings. Tickertape built scorecards.
>
> Today we're launching **The YieldIQ Prism** — our signature for the Indian market.
>
> ## What the Prism is
>
> Six pillars refract fundamental data into one composite score:
>
> - **Pulse** — momentum signal: promoter stake changes, insider filings, analyst estimate revisions
> - **Quality** — return on capital, earnings consistency, Piotroski F-score
> - **Moat** — brand, scale, switching costs
> - **Safety** — balance-sheet strength, leverage, interest coverage
> - **Growth** — revenue + earnings compounding
> - **Value** — price vs intrinsic worth
>
> Two views, one data: a radial **Signature** (shareable as a square, great for WhatsApp) and a linear **Spectrum** (great for reading top-to-bottom). Tap the toggle; it live-morphs between them.
>
> ## Why we built it differently
>
> Global tools like Simply Wall St use axes that make sense in the US — but they're structurally blind to Indian signals:
>
> - **Promoter holding changes** (BSE XBRL quarterly) — a declining promoter stake is a red flag in India in a way it isn't in the US
> - **SEBI SAST Reg 7/8 filings** — insider trades in listed securities, aggregated signed value
> - **WACC from the 10-yr G-Sec** — not US treasury. This single adjustment materially changes fair values
>
> Our Pulse axis bundles all three. When promoters quietly trim their stake and insiders net-sell, the Pulse lens narrows — you see it instantly.
>
> ## The Refraction Index
>
> Every stock gets a scalar 0-5 telling you how *opinionated* its Prism is. An "all-5s" company (boring, mediocre everything) refracts at ~0. A stock with 4 strong pillars and 2 very weak ones refracts at ~4.
>
> High refraction = high conviction (in either direction). Low refraction = unremarkable.
>
> ## What's also shipping
>
> - **Time Machine** — scrubber through 12 quarters. Watch the shape breathe as the business evolves.
> - **Auto-narration** — tap "Tell me the story" for a 45-sec guided read across the 6 pillars.
> - **Portfolio Prism** — weighted aggregate of your holdings, with strongest/weakest lens callouts.
> - **Overlay compare** — two stocks' Signatures on one canvas.
>
> Everything is free. The data sources are public filings (NSE, BSE, SEBI EDIFAR). We are not SEBI-registered as an investment adviser or research analyst; everything here is educational.
>
> ## Try it
>
> Paste any NSE/BSE ticker: **yieldiq.in/prism/RELIANCE** (or TCS, INFY, HDFCBANK, your favorite).
>
> Screenshot the Prism. Post it with #YieldIQPrism. Tell us which stock looks wrong — we'll investigate.
>
> — The YieldIQ team

---

## Post-launch metrics to watch (Day 1-7)

| Metric | Where | Target D1 | Target D7 |
|---|---|---|---|
| Unique visitors | Vercel Analytics | 200 | 2,000 |
| Sign-ups | Supabase / your auth | 20 | 200 |
| Prism URL shares (referrer traffic from twitter.com/whatsapp) | Vercel | 10 | 100 |
| `/prism/*` page views | Vercel | 100 | 1,000 |
| Time Machine opens | GA4 custom event (add if not there) | 20 | 200 |
| Narration plays | GA4 custom event | 10 | 100 |

If D1 visitors < 50, something's wrong with reach — push harder on r/IndiaInvestments + DM 10 finance friends.
If D1 > 500, something's right — prepare for Railway/Aiven scale-up.
