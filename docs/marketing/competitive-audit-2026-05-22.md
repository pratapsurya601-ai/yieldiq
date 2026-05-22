# Competitive audit — Indian retail stock-analysis tools

**Date**: 2026-05-22
**Author**: Day-102 competitive sweep
**Scope**: Indian retail-facing stock-analysis tools, plus Simply Wall St
as the global DCF reference. Free-tier walkthroughs + public marketing
pages — no logged-in screens.

---

## TL;DR

YieldIQ is the only tool in this set that ships a **complete DCF
pipeline with explicit fair value, MoS band, scenario tree, and a
transparent verdict gate** — and does so without using SEBI-banned
advisory vocabulary.

Screener.in is a data presentation tool (no valuation). Tickertape and
Trendlyne are scorecard / signal tools (no DCF, vocabulary leans
advisory). Simply Wall St does DCF but with a US-first cohort + opaque
methodology and high price.

**The positioning sentence**: "The only Indian DCF tool that shows you
exactly why the number changed."

Pricing position: ₹99/month sits between Tickertape's discounted
₹120/month and Screener's ₹400/month. We're cheaper than Screener
despite shipping more analytical work; that's a deliberate
acquisition lever, not a long-term floor.

---

## Competitor cards

### Screener.in
**What they do well**
- Massive raw-data depth: 13 quarters of P&L, 12 years of annual data,
  balance sheet, cash flow, ratios, all on one scrollable page.
- 28+ concall transcripts going back to 2018, linked.
- Annual reports linked back to FY2012.
- Credit ratings panel (CARE, CRISIL, Fitch).
- Shareholding pattern by quarter, including shareholder count.
- Compounded growth metrics (3y / 5y / 10y for sales, profit, stock
  CAGR, ROE).
- Custom screener builder is the de-facto retail-quant tool in India.

**Gaps**
- No fair value, no DCF, no MoS, no verdict, no score.
- Machine-generated Pros / Cons read templated.
- UI is dense, table-heavy, retail-Excel aesthetic.
- "Insights" panel locked behind login — freemium hook.

**Pricing**: ₹4,799 / year (~₹400/month).

**What we learn**: depth of raw data is their moat. We don't beat them
on raw data depth; we beat them on **what the data means** for value.

---

### Tickertape
**What they do well**
- Clean modern UI, prominent dark-theme product surface.
- Stock Scorecard with 6 dimensions (Performance / Valuation / Growth /
  Profitability / Entry point / Red flags), each with a one-word verdict.
- Sentiment / Forecasts / Financials / Peers / Holdings / Events / News
  tabs — broad surface area.
- 40 %-off promo is always running — signals price-sensitive segment.

**Risks they're taking**
- "Entry point: Good — The stock is underpriced and is not in the
  overbought zone" — borderline advisory language.
- "Buy Reco %" aggregated from broker recommendations — dressing
  broker advice as data. SEBI-risky for them; differentiating for us.

**Gaps**
- No DCF, no fair value, no methodology disclosure.
- Forecasts panel teases high/median/low but locks values behind Pro.
- Scorecard verdicts are opaque (what counts as "Good" in Valuation?).

**Pricing**: ₹2,399 / year regular, often ₹1,440 / year discounted
(~₹120 / month).

**What we learn**: the scorecard pattern resonates with retail. We
already have the building blocks (verdict, score, confidence, MoS, hex
visualization) — we should ensure they're as glanceable as
Tickertape's, with the methodology link Tickertape lacks.

---

### Trendlyne
**What they do well**
- 9 tabs vs our 6: Overview, Forecaster, Buy Sell Zone, F&O,
  Financials, Charts & Report, News, Reports, Technicals, Shareholding.
- "MarketMind AI" branding.
- Baskets / model portfolios.
- Superstars page (notable-investor portfolios).
- Mutual fund + F&O coverage.

**Gaps**
- "Buy Sell Zone" naming is SEBI-risky for them.
- DCF / fair value not the primary signal — technicals and signals are.
- F&O focus signals a different user persona (active trader, not the
  long-term holder our DCF appeals to).

**What we learn**: their breadth (MF, F&O, Superstars) is their hook.
We deliberately stay focused on long-term valuation. That's a feature,
not a bug — but we should be explicit about it in our positioning.

---

### Simply Wall St (global)
**What they do well**
- DCF on every covered stock, with snowflake visualization.
- Excellent visual storytelling (Snowflake / Pie chart).
- 5-year forecast embedded in the narrative.
- Global coverage.

**Gaps**
- US-first cohort means Indian sector defaults are wrong (telcos,
  utilities, banks all treated with US-bank or US-utility models).
- Methodology opaque — users see the snowflake but not the assumptions.
- High price (US$80+/year). Wrong currency, wrong tier for Indian
  retail.

**What we learn**: the snowflake / visual encoding works. Our hex chart
plays a similar role. But Indian-first sector models (Day-92 utility
floor, Day-76 cyclical normalization, Day-84 pharma cohort) are a real
moat that Simply Wall St cannot quickly close.

---

## What YieldIQ has that none of them have

1. **Public DCF with full methodology disclosure.** Every assumption
   visible — WACC, terminal growth, scenario weights. Help page links
   to each ingredient. (`/help/reading-an-analysis`,
   `/help/confidence-and-limits`)
2. **Verdict-gate transparency**. We tell users when we are NOT
   confident (data_limited / under_review) instead of always producing
   a number. Day-91 and Day-103 (PR #503) hardened this gate.
3. **Indian-first sector models**. Regulated utility bear-floor
   (Day-92), pharma franchise cohort (Day-84), cyclical normalization
   (Days 51-56), reverse-DCF for cyclicals (Day-76), bank PB skip
   (Day-76). Each documented in code with a hook to the audit that
   surfaced it.
4. **Industry-relative percentiles** (Day-99). Per-pillar ordinal
   ranks within a peer cohort — "Top quartile in Banks - Private
   Sector". Nobody else in this set ranks per-pillar.
5. **Backtest harness**. YIQ50 vs Nifty over 36 months, shown on
   `/backtest`. Tickertape teases forecasts; we show what would have
   happened if you followed our verdicts.
6. **SEBI-safe vocabulary across the entire surface** — Tickertape /
   Trendlyne names ("Buy Reco %", "Buy Sell Zone") would not survive a
   SEBI review. Ours does. Compliance is a moat in this market.
7. **Granular cache invalidation manifest** (Day-94) — when we ship a
   fix, it propagates only to affected tickers. Lets us ship 20+ fixes
   in a day without nuking everyone's session.

---

## What YieldIQ is missing — priority list

Most-to-least valuable to close, given the competitive set:

### P0 — close within 30 days
1. **Concall transcript + AI summary panel** (Screener has 28+ per
   ticker). Cheap to ship — Groq Llama 3.3 already wired for AI summary
   surfaces. Source: BSE / SEBI concall PDFs. Big retail trust signal.
2. **Annual report links per ticker** (Screener has FY2012+). Easy:
   scrape from BSE annual report directory, store URL + filing date,
   render as a list. No ingestion needed.
3. **3y / 5y / 10y compounded growth metrics on the stock summary page**
   (Screener default panel). We already compute revenue / profit
   history; just need the CAGR view. Likely <100 LoC.

### P1 — close within 60 days
4. **Credit ratings panel** (Screener has CARE/CRISIL/Fitch). Source
   exists in BSE filings. Helpful for the bank / NBFC / utility cohort
   our DCF specializes in.
5. **Shareholder count + quarterly shareholding pattern history**
   (Screener has this). We track shareholding for ITC dividend signal
   already — extend to all tickers as a tab.
6. **Per-pillar scorecard one-liners** (Tickertape pattern, applied to
   our hex). For each of 6 pillars (Quality / Growth / Value / Momentum
   / Trend / Risk), render one sentence: "Top quartile in private
   banks". We already have the data (Day-99 percentiles); just package
   it as a 6-card grid above the analysis body.

### P2 — close within 90 days, only if user demand surfaces
7. **Mutual fund analyzer** (Trendlyne). Big surface, separate product.
   Don't ship until we have 500+ paid users on the equity side.
8. **F&O data** (Trendlyne). Wrong audience for DCF buyers. Skip.
9. **Superstars / notable investor portfolios** (Trendlyne). Possible
   feature but only after dividend tracker, tax harvesting, and the
   sample portfolio onboarding land for real users.

### Explicitly NOT shipping (deliberate scope discipline)
- Stock signals / buy-sell zones — every other tool has these and they
  all walk the SEBI line. We don't.
- Aggregated broker recommendations — same SEBI risk.
- News-driven sentiment scores as the headline signal — we have news
  tier chips (Day-79/85), but they stay supporting, not headline.

---

## Pricing position

Current Pro at ₹99/month is competitive but probably under-priced.

| Tool | Price | What you get |
|---|---|---|
| YieldIQ Pro | ₹99/mo | DCF, fair value, MoS, verdict, scenarios, backtest, alerts, watchlist |
| Tickertape Pro | ₹120/mo | Scorecard, forecasts (high/med/low), screener |
| Tickertape Pro Max | ~₹250/mo | + portfolio tools |
| Screener Premium | ₹400/mo | Raw data depth, custom screener |
| Simply Wall St | ~$8/mo (~₹670) | DCF, snowflake, global coverage |

**Recommendation**: keep ₹99/month for acquisition for next 90 days.
Test ₹199/month on a 50/50 split of new signups after we have 200 paid
users — the data depth + DCF combo justifies the premium over
Tickertape's scorecard-only tier.

---

## Marketing copy primitives (lift-and-use snippets)

These are written SEBI-safe, intended for the marketing page, the
r/IndiaInvestments post, and the cold-outreach emails when we have any.

> *"Three Indian retail tools tell you a stock is "good". One tells you
> what it's worth, why, and when we last got it wrong."*

> *"We publish the WACC, the terminal growth, the scenario weights, and
> the audit log of every fix. Nobody else in Indian retail does."*

> *"Indian-first sector models. We don't treat NTPC like a US utility,
> or HDFC Bank like a US bank, because they aren't."*

> *"When we're not confident, we tell you. The pill turns to "Under
> Review" — not a fake "Hold" with a confidence floor of 0%."*

---

## Next steps

1. Ship P0 items (concall summaries, annual report links, CAGR panel)
   as 3 separate PRs over the next 14 days.
2. Use the snippets above in the Reddit post draft
   (`docs/marketing/reddit-post-draft-2026-05-22.md`) — already shipped.
3. Re-run this audit on Day 200 to track competitor movement, especially
   if any of them ship a real DCF.
